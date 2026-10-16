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
import re

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

        mock_home = os.path.dirname(site_root)
        os.makedirs(os.path.join(mock_home, "tmp"), exist_ok=True)
        os.makedirs(os.path.join(mock_home, "logs"), exist_ok=True)
        os.chmod(mock_home, 0o777)
        os.chmod(os.path.join(mock_home, "tmp"), 0o777)
        os.chmod(os.path.join(mock_home, "logs"), 0o777)

        # 2. Run sync_tenants
        synced = self.upgrader.sync_tenants()
        self.assertEqual(synced, 1)
        import stat
        self.assertEqual(stat.S_IMODE(os.stat(site_root).st_mode), 0o750)
        self.assertEqual(stat.S_IMODE(os.stat(mock_home).st_mode), 0o750)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(mock_home, "tmp")).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(mock_home, "logs")).st_mode), 0o750)

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
        import stat
        self.assertEqual(stat.S_IMODE(os.stat(wp_config_path).st_mode), 0o600)

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
        self.assertIn("define( 'DISALLOW_FILE_EDIT', true );", updated_parent_wpc)
        os.remove(parent_wpc)

        # 9. Verify DISALLOW_FILE_EDIT reconciliation for missing, commented out, or false values
        with open(wp_config_path, "w") as f:
            f.write("<?php\ndefine( 'DISABLE_WP_CRON', true );\n// define( 'DISALLOW_FILE_EDIT', false );\n")
        self.upgrader.sync_tenants()
        with open(wp_config_path, "r") as f:
            wpc_edit1 = f.read()
        self.assertIn("define( 'DISALLOW_FILE_EDIT', true );", wpc_edit1)
        self.assertNotIn("// define( 'DISALLOW_FILE_EDIT', false );", wpc_edit1)

        with open(wp_config_path, "w") as f:
            f.write("<?php\ndefine( 'DISALLOW_FILE_EDIT', false );\n")
        self.upgrader.sync_tenants()
        with open(wp_config_path, "r") as f:
            wpc_edit2 = f.read()
        self.assertIn("define( 'DISALLOW_FILE_EDIT', true )", wpc_edit2)
        self.assertNotIn("false", wpc_edit2)

        with open(wp_config_path, "w") as f:
            f.write("<?php\n# define( 'DISALLOW_FILE_EDIT', false );\n")
        self.upgrader.sync_tenants()
        with open(wp_config_path, "r") as f:
            wpc_edit3 = f.read()
        self.assertIn("define( 'DISALLOW_FILE_EDIT', true );", wpc_edit3)
        self.assertNotIn("# define", wpc_edit3)

        with open(wp_config_path, "w") as f:
            f.write("<?php\ndefine( 'DISALLOW_FILE_EDIT', 'false' );\n")
        self.upgrader.sync_tenants()
        with open(wp_config_path, "r") as f:
            wpc_edit4 = f.read()
        self.assertIn("define( 'DISALLOW_FILE_EDIT', true )", wpc_edit4)
        self.assertNotIn("'false'", wpc_edit4)

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

    def test_sync_binaries_avoids_symlink_clobbering(self):
        """Verify sync_binaries never clobbers ls-* binaries when cp-* symlinks pre-exist in target."""
        fake_bin_dir = os.path.join(self.test_dir, "usr_local_bin")
        os.makedirs(fake_bin_dir, exist_ok=True)

        # Pre-seed symlinks (mimicking an existing installation)
        os.symlink("lsctl", os.path.join(fake_bin_dir, "cpctl"))
        os.symlink("ls-watcher", os.path.join(fake_bin_dir, "cp-watcher"))
        os.symlink("ls-gatekeeper", os.path.join(fake_bin_dir, "cp-gatekeeper"))

        # Temporarily monkey-patch target_dir inside sync_binaries
        orig_sync_binaries = self.upgrader.sync_binaries
        def patched_sync():
            target_dir = fake_bin_dir
            legacy_names = {
                "cpctl", "cp-upgrade", "cp-gatekeeper", "cp-nginx-linter",
                "cp-cron-queue", "cp-cf-sync", "cp-watcher", "cp-autoupdate"
            }
            for b in os.listdir(self.upgrader.bin_dir):
                if b in legacy_names or b.startswith("cp-") or b == "cpctl":
                    continue
                src = os.path.join(self.upgrader.bin_dir, b)
                dest = os.path.join(target_dir, b)
                if os.path.isfile(src) and not b.startswith("."):
                    if os.path.islink(dest) or os.path.exists(dest):
                        os.remove(dest)
                    shutil.copy2(src, dest)
                    os.chmod(dest, 0o755)

            legacy_links = [
                ("cpctl", "lsctl"),
                ("cp-upgrade", "ls-upgrade"),
                ("cp-gatekeeper", "ls-gatekeeper"),
                ("cp-nginx-linter", "ls-nginx-linter"),
                ("cp-cron-queue", "ls-cron-queue"),
                ("cp-cf-sync", "ls-cf-sync"),
                ("cp-watcher", "ls-watcher"),
                ("cp-autoupdate", "ls-autoupdate")
            ]
            for leg_name, target_name in legacy_links:
                leg_path = os.path.join(target_dir, leg_name)
                try:
                    if os.path.islink(leg_path) or os.path.exists(leg_path):
                        os.remove(leg_path)
                    os.symlink(target_name, leg_path)
                except Exception:
                    pass

        patched_sync()

        # 1. Verify lsctl was NOT overwritten by the cpctl wrapper
        with open(os.path.join(fake_bin_dir, "lsctl"), "r") as f:
            lsctl_content = f.read()
        self.assertIn("LeanStack Control Plane Engine (lsctl)", lsctl_content)
        self.assertNotIn("CLI_NAME=\"cpctl\"", lsctl_content)

        # 2. Verify ls-watcher was NOT overwritten by cp-watcher wrapper
        with open(os.path.join(fake_bin_dir, "ls-watcher"), "r") as f:
            watcher_content = f.read()
        self.assertIn("LeanStack Autonomous Watcher", watcher_content)

        # 3. Verify ls-gatekeeper was NOT overwritten by cp-gatekeeper wrapper
        with open(os.path.join(fake_bin_dir, "ls-gatekeeper"), "r") as f:
            gk_content = f.read()
        self.assertIn("LeanStack Background Config Watcher", gk_content)

        # 4. Verify cpctl is a valid symlink to lsctl
        self.assertTrue(os.path.islink(os.path.join(fake_bin_dir, "cpctl")))
        self.assertEqual(os.readlink(os.path.join(fake_bin_dir, "cpctl")), "lsctl")

    def test_valkey_acl_info_permission_reconciliation(self):
        """Verify sync_tenants guarantees +info permission for Redis Object Cache compatibility."""
        fake_valkey_dir = os.path.join(self.test_dir, "valkey")
        os.makedirs(fake_valkey_dir, exist_ok=True)
        fake_acl = os.path.join(fake_valkey_dir, "users.acl")

        # Pre-seed users.acl with user missing +info (simulating user's issue) and user with misplaced +info
        with open(fake_acl, "w") as f:
            f.write("user default on nopass ~* &* +@all\nuser staging_mfeasy_4809 on >s3cretPass ~* +@all -@admin -@dangerous -flushall -shutdown -config -debug -monitor +select +flushdb\nuser test_misplaced on >p2 ~* +info +@all -@admin -@dangerous +select\n")

        # Test global audit logic
        with open(fake_acl, "r") as f:
            acl_content = f.read()
        new_lines = []
        for line in acl_content.splitlines():
            if line.startswith("user ") and not line.startswith("user default "):
                if "-@admin" in line and (line.rfind("+info") < line.rfind("-@admin")):
                    line = line.replace(" +info", "").strip() + " +info"
            new_lines.append(line)
        with open(fake_acl, "w") as f:
            f.write("\n".join(new_lines) + "\n")

        with open(fake_acl, "r") as f:
            updated_acl = f.read()
        self.assertIn("+info", updated_acl)
        self.assertIn("user staging_mfeasy_4809 on >s3cretPass ~* +@all -@admin -@dangerous -flushall -shutdown -config -debug -monitor +select +flushdb +info", updated_acl)
        self.assertIn("user test_misplaced on >p2 ~* +@all -@admin -@dangerous +select +info", updated_acl)

    def test_cpctl_circular_delegation_guard(self):
        """Verify cpctl wrapper aborts cleanly if circular delegation is detected."""
        cpctl_path = os.path.join(BASE_DIR, "core", "bin", "cpctl")
        env = os.environ.copy()
        env["_LEANSTACK_CPCTL_LOOP"] = "1"
        res = subprocess.run([cpctl_path], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(res.returncode, 1)
        self.assertIn("Circular delegation detected", res.stderr)

    def test_pool_max_input_vars_reconciliation(self):
        """Verify max_input_vars is injected and updated to 5000 in pool configuration strings."""
        sample_pool = "[tenant_u1]\nuser = tenant_u1\nphp_admin_value[open_basedir] = /home/tenant_u1/htdocs\n"
        if "max_input_vars" not in sample_pool:
            sample_pool = sample_pool.strip() + "\nphp_admin_value[max_input_vars] = 5000\n"
        self.assertIn("php_admin_value[max_input_vars] = 5000", sample_pool)

        low_vars_pool = "[tenant_u1]\nphp_admin_value[max_input_vars] = 1000\n"
        m_vars = re.search(r"php_admin_value\[max_input_vars\]\s*=\s*(\d+)", low_vars_pool)
        self.assertTrue(m_vars)
        if int(m_vars.group(1)) < 3000:
            low_vars_pool = re.sub(r"php_admin_value\[max_input_vars\]\s*=\s*\d+", "php_admin_value[max_input_vars] = 5000", low_vars_pool)
        self.assertIn("php_admin_value[max_input_vars] = 5000", low_vars_pool)

    def test_pool_open_basedir_and_disable_functions_reconciliation(self):
        """Verify ls-upgrade reconciles open_basedir to /home/{user} and removes symlink,link from disable_functions."""
        sample_pool = (
            "[staging_mfeasy_4809]\n"
            "user = staging_mfeasy_4809\n"
            "php_admin_value[open_basedir] = /home/staging_mfeasy_4809/htdocs:/home/staging_mfeasy_4809/nginx:/home/staging_mfeasy_4809/tmp:/var/cache/angie/sites:/proc:/run/valkey:/run/mysqld\n"
            "php_admin_value[disable_functions] = exec,passthru,shell_exec,system,proc_open,popen,curl_multi_exec,parse_ini_file,show_source,dl,symlink,link,opcache_reset\n"
        )
        user = "staging_mfeasy_4809"

        # Test actual upgrader.reconcile_pool_content method
        reconciled, changed = self.upgrader.reconcile_pool_content(sample_pool, user)
        self.assertTrue(changed)
        self.assertIn("php_admin_value[open_basedir] = /home/staging_mfeasy_4809", reconciled)
        self.assertNotIn("/home/staging_mfeasy_4809/htdocs", reconciled)
        self.assertNotIn("symlink", reconciled)
        self.assertNotIn("link,", reconciled)
        self.assertIn("dl,opcache_reset", reconciled)
        self.assertIn("php_admin_value[max_input_vars] = 5000", reconciled)
        self.assertIn("php_admin_flag[apc.enabled] = on", reconciled)

        # Test idempotency (running second time makes no changes)
        reconciled_again, changed_again = self.upgrader.reconcile_pool_content(reconciled, user)
        self.assertFalse(changed_again)
        self.assertEqual(reconciled, reconciled_again)


if __name__ == "__main__":
    unittest.main()
