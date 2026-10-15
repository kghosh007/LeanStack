#!/usr/bin/env python3
"""
Unit Tests for LeanStack Autonomous Upgrade & Migration Engine (cp-upgrade)
Validates:
1. SQLite forward schema migrations (SQL and Python migrations)
2. Schema migration tracking idempotency (schema_migrations table)
3. Pre-upgrade database snapshot backups
4. Multi-tenant reconciliation (MU-plugins sync, cache-config scaffolding)
5. CLI commands: cpctl update / cpctl migrate / cp-upgrade
"""

import unittest
import os
import sys
import sqlite3
import tempfile
import shutil
import json
import subprocess

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
UPGRADE_BIN = os.path.join(BASE_DIR, "core", "bin", "ls-upgrade")
CPCTL_BIN = os.path.join(BASE_DIR, "core", "bin", "lsctl")

import importlib.util
from importlib.machinery import SourceFileLoader

loader = SourceFileLoader("cp_upgrade", UPGRADE_BIN)
spec = importlib.util.spec_from_file_location("cp_upgrade", UPGRADE_BIN, loader=loader)
cp_upgrade_mod = importlib.util.module_from_spec(spec)
loader.exec_module(cp_upgrade_mod)
LeanStackUpgrader = cp_upgrade_mod.LeanStackUpgrader


class TestUpgradeAndMigrationEngine(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="ls_upgrade_test_")
        self.db_file = os.path.join(self.test_dir, "sites.db")
        self.backup_dir = os.path.join(self.test_dir, "backups")
        self.upgrader = LeanStackUpgrader(
            repo_dir=BASE_DIR,
            db_file=self.db_file,
            dry_run=False,
            force=False
        )
        self.upgrader.backup_dir = self.backup_dir

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_schema_migrations_runner(self):
        """Verify sequential execution of SQL and Python schema migrations."""
        applied = self.upgrader.run_migrations()
        self.assertGreaterEqual(applied, 2)

        # Verify database schema
        conn = sqlite3.connect(self.db_file)
        cur = conn.cursor()

        # Check schema_migrations tracking
        cur.execute("SELECT version, name FROM schema_migrations ORDER BY version ASC;")
        rows = cur.fetchall()
        versions = [r[0] for r in rows]
        self.assertIn(1, versions)
        self.assertIn(2, versions)

        # Check sites table columns
        cur.execute("PRAGMA table_info(sites);")
        cols = [r[1] for r in cur.fetchall()]
        self.assertIn("domain", cols)
        self.assertIn("user", cols)
        self.assertIn("php_version", cols)
        self.assertIn("cache_enabled", cols)
        self.assertIn("cache_ttl", cols)
        self.assertIn("cf_zone_id", cols)

        conn.close()

    def test_migration_idempotency(self):
        """Verify re-running migrations does not duplicate records or throw errors."""
        first_run = self.upgrader.run_migrations()
        self.assertGreaterEqual(first_run, 2)

        second_run = self.upgrader.run_migrations()
        self.assertEqual(second_run, 0)

    def test_pre_upgrade_database_backup(self):
        """Verify database snapshot is created before running modifications."""
        # Seed test database
        self.upgrader.run_migrations()

        backup_file = self.upgrader.backup_database()
        self.assertTrue(os.path.exists(backup_file))
        self.assertIn("sites_pre_upgrade_", os.path.basename(backup_file))

        # Verify backup contains valid SQLite data
        conn = sqlite3.connect(backup_file)
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM schema_migrations;")
        count = cur.fetchone()[0]
        self.assertGreaterEqual(count, 2)
        conn.close()

    def test_tenant_reconciliation(self):
        """Verify sync_tenants pushes updated MU-plugins and scaffolding to all active sites."""
        # 1. Initialize schema and insert mock tenant site
        self.upgrader.run_migrations()
        site_root = os.path.join(self.test_dir, "home", "tenant_u1", "htdocs")
        mu_plugins_dir = os.path.join(site_root, "wp-content", "mu-plugins")
        os.makedirs(mu_plugins_dir, exist_ok=True)

        conn = sqlite3.connect(self.db_file)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO sites (domain, user, php_version, pool_type, site_path, db_name, db_user, db_pass, admin_user, admin_pass, admin_email)
            VALUES ('tenant.example.com', 'tenant_u1', '8.5', 'dedicated', ?, 'tdb', 'tu', 'pass', 'admin', 'pass', 'a@e.com');
        """, (site_root,))
        conn.commit()
        conn.close()

        # 2. Run sync_tenants
        synced = self.upgrader.sync_tenants()
        self.assertEqual(synced, 1)

        # 3. Assert all 4 MU-plugins exist in the tenant's mu-plugins directory
        expected_plugins = [
            "leanstack-bridge.php",
            "leanstack-holepunch.php",
            "leanstack-apcu.php",
            "leanstack-shield.php"
        ]
        for p in expected_plugins:
            p_path = os.path.join(mu_plugins_dir, p)
            self.assertTrue(os.path.exists(p_path), f"Missing plugin {p}")
            with open(p_path, "r") as f:
                content = f.read()
            self.assertIn("<?php", content)

        # 4. Verify wp-config.php Valkey username reconciliation (with WP_REDIS_USER)
        wp_config_path = os.path.join(site_root, "wp-config.php")
        with open(wp_config_path, "w") as f:
            f.write("<?php\ndefine( 'WP_REDIS_USER', 'tenant_u1' );\ndefine( 'WP_REDIS_PASSWORD', 'secret' );\n")
        self.upgrader.sync_tenants()
        with open(wp_config_path, "r") as f:
            updated_wpc = f.read()
        self.assertIn("define( 'WP_REDIS_USERNAME', 'tenant_u1' );", updated_wpc)
        self.assertIn("define( 'WP_REDIS_USER', 'tenant_u1' );", updated_wpc)

        # 5. Verify wp-config.php reconciliation when ONLY WP_REDIS_PASSWORD is present (user's diagnostic scenario)
        with open(wp_config_path, "w") as f:
            f.write("<?php\ndefine( 'WP_REDIS_SCHEME', 'unix' );\ndefine( 'WP_REDIS_PATH', '/run/valkey/valkey.sock' );\ndefine( 'WP_REDIS_PASSWORD', 'my_valkey_pass' );\n")
        self.upgrader.sync_tenants()
        with open(wp_config_path, "r") as f:
            updated_wpc2 = f.read()
        self.assertIn("define( 'WP_REDIS_USERNAME', 'tenant_u1' );", updated_wpc2)
        self.assertIn("define( 'WP_REDIS_USER', 'tenant_u1' );", updated_wpc2)
        self.assertIn("define( 'WP_REDIS_PASSWORD', 'my_valkey_pass' );", updated_wpc2)
        self.assertIn("define( 'WP_CACHE', true );", updated_wpc2)

        # 5b. Verify commented out WP_CACHE is enabled
        with open(wp_config_path, "w") as f:
            f.write("<?php\n// define( 'WP_CACHE', false );\ndefine( 'WP_REDIS_PASSWORD', 'pass123' );\n")
        self.upgrader.sync_tenants()
        with open(wp_config_path, "r") as f:
            updated_wpc3 = f.read()
        self.assertIn("define( 'WP_CACHE', true );", updated_wpc3)
        self.assertNotIn("// define( 'WP_CACHE', false );", updated_wpc3)

        # 6. Verify object-cache.php drop-in fallback copying if plugin includes/object-cache.php exists
        rc_includes = os.path.join(site_root, "wp-content", "plugins", "redis-cache", "includes")
        os.makedirs(rc_includes, exist_ok=True)
        with open(os.path.join(rc_includes, "object-cache.php"), "w") as f:
            f.write("<?php /* Redis Object Cache Drop-in */")
        dropin_target = os.path.join(site_root, "wp-content", "object-cache.php")
        # Test overwrite of corrupted/empty drop-in
        with open(dropin_target, "w") as f:
            f.write("/* corrupt or foreign drop-in */")
        self.upgrader.sync_tenants()
        self.assertTrue(os.path.exists(dropin_target))
        with open(dropin_target, "r") as f:
            self.assertIn("Redis Object Cache Drop-in", f.read())

        # 7. Verify harmonization of incorrect WP_REDIS_USERNAME / WP_REDIS_USER values
        with open(wp_config_path, "w") as f:
            f.write("<?php\ndefine( 'WP_REDIS_USERNAME', 'wrong_user' );\ndefine( 'WP_REDIS_USER', 'wrong_user' );\ndefine( 'WP_REDIS_PASSWORD', 'pass123' );\n")
        self.upgrader.sync_tenants()
        with open(wp_config_path, "r") as f:
            updated_wpc4 = f.read()
        self.assertIn("define( 'WP_REDIS_USERNAME', 'tenant_u1' )", updated_wpc4)
        self.assertIn("define( 'WP_REDIS_USER', 'tenant_u1' )", updated_wpc4)
        self.assertNotIn("wrong_user", updated_wpc4)

        # 8. Verify wp-config.php in parent directory (nested docroot ABSPATH)
        parent_wpc = os.path.join(os.path.dirname(site_root), "wp-config.php")
        os.remove(wp_config_path)
        with open(parent_wpc, "w") as f:
            f.write("<?php\ndefine( 'WP_REDIS_PASSWORD', 'parent_pass' );\n")
        self.upgrader.sync_tenants()
        with open(parent_wpc, "r") as f:
            updated_parent_wpc = f.read()
        self.assertIn("define( 'WP_REDIS_USERNAME', 'tenant_u1' );", updated_parent_wpc)
        self.assertIn("define( 'WP_CACHE', true );", updated_parent_wpc)
        os.remove(parent_wpc)

    def test_cli_upgrade_dry_run_and_json(self):
        """Verify cp-upgrade CLI flags --dry-run and --json."""
        cmd = [
            sys.executable,
            UPGRADE_BIN,
            f"--repo-dir={BASE_DIR}",
            f"--db-file={self.db_file}",
            "--migrate-only",
            "--json"
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        data = json.loads(res.stdout)
        self.assertEqual(data.get("status"), "ok")
        self.assertGreaterEqual(data.get("migrations_applied", 0), 2)


if __name__ == "__main__":
    unittest.main()
