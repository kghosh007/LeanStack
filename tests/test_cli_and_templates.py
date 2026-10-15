#!/usr/bin/env python3
"""
Unit Tests for LeanStack Agency Profiles, Templates & SQLite Schema
"""

import unittest
import os
import sys
import yaml
import sqlite3
import tempfile

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

class TestProfilesAndTemplates(unittest.TestCase):

    def test_agency_profiles_yaml(self):
        """Verify profiles.yaml exists and parses cleanly with valid schema."""
        profile_path = os.path.join(BASE_DIR, "core", "config", "profiles.yaml")
        self.assertTrue(os.path.exists(profile_path))
        with open(profile_path, "r") as f:
            data = yaml.safe_load(f)

        expected_profiles = ["default", "agency_woocommerce", "high_traffic", "headless_wp"]
        for prof in expected_profiles:
            self.assertIn(prof, data)
            cfg = data[prof]
            self.assertIn("php", cfg)
            self.assertIn("memory_limit", cfg)
            self.assertIn("pool_mode", cfg)
            self.assertIn("plugins", cfg)

    def test_vhost_template_security(self):
        """Verify vhost.conf.tpl contains all hardening, 8G WAF, and HTTP/3 directives."""
        tpl_path = os.path.join(BASE_DIR, "core", "templates", "vhost.conf.tpl")
        self.assertTrue(os.path.exists(tpl_path))
        with open(tpl_path, "r") as f:
            content = f.read()

        # Check HTTP/3 QUIC
        self.assertIn("listen 443 quic;", content)
        # Check ACME native client
        self.assertIn("acme_client", content)
        self.assertIn("acme acme_{{ZONE_KEY}};", content)
        self.assertIn("$acme_cert_acme_{{ZONE_KEY}}", content)
        # Check modular SSL headers snippet
        self.assertIn("include /etc/angie/snippets/ssl-headers.conf;", content)
        # Check 8G WAF snippet
        self.assertIn("include /etc/angie/snippets/8g-firewall.conf;", content)
        # Check hard blocks: uploads PHP execution denied
        self.assertIn("location ~* /(?:uploads|files|wp-content/uploads|wp-content/cache)/.*\\.php$", content)
        # Check FastCGI microcache
        self.assertIn("fastcgi_cache CACHE_{{ZONE_KEY}};", content)
        # Check Native WordPress Brute-Force Rate Limiting
        self.assertIn("zone=wplogin", content)
        self.assertIn("location = /wp-login.php", content)
        # Check Sensitive file masking
        self.assertIn("readme\\.html", content)
        # Check Tenant custom slots and security headers
        self.assertIn("custom-early.conf", content)
        self.assertIn("custom-rules.conf", content)
        self.assertIn("security-headers.conf", content)
        self.assertIn("avif", content)
        self.assertIn("wasm", content)

    def test_pool_template_isolation(self):
        """Verify pool.conf.tpl enforces tenant sandboxing, open_basedir, and expanded disable_functions."""
        tpl_path = os.path.join(BASE_DIR, "core", "templates", "pool.conf.tpl")
        self.assertTrue(os.path.exists(tpl_path))
        with open(tpl_path, "r") as f:
            content = f.read()

        self.assertIn("php_admin_value[open_basedir]", content)
        self.assertNotIn(":/tmp", content)  # Global /tmp must not be in open_basedir
        self.assertIn("php_admin_value[disable_functions]", content)
        self.assertIn("dl,symlink,link", content)
        self.assertIn("php_admin_value[upload_tmp_dir]", content)
        self.assertIn("listen.mode = 0660", content)

    def test_wp_config_template_socket_and_proxy(self):
        """Verify wp-config.php.tpl configures Valkey ACL socket, database, and reverse-proxy SSL."""
        tpl_path = os.path.join(BASE_DIR, "core", "templates", "wp-config.php.tpl")
        self.assertTrue(os.path.exists(tpl_path))
        with open(tpl_path, "r") as f:
            content = f.read()

        self.assertIn("WP_REDIS_SCHEME", content)
        self.assertIn("/run/valkey/valkey.sock", content)
        self.assertIn("WP_REDIS_USER", content)
        self.assertIn("WP_REDIS_PASSWORD", content)
        self.assertIn("WP_REDIS_DATABASE", content)
        self.assertIn("DISABLE_WP_CRON", content)
        self.assertIn("HTTP_X_FORWARDED_PROTO", content)
        self.assertIn("HTTP_CF_VISITOR", content)

    def test_cron_queue_sandboxing(self):
        """Verify cp-cron-queue applies strict PHP open_basedir and disable_functions."""
        cron_bin = os.path.join(BASE_DIR, "core", "bin", "ls-cron-queue")
        self.assertTrue(os.path.exists(cron_bin))
        with open(cron_bin, "r") as f:
            content = f.read()
        self.assertIn("-d open_basedir=", content)
        self.assertIn("-d disable_functions=", content)

    def test_leanstack_shield_mu_plugin(self):
        """Verify leanstack-shield.php.tpl disables XML-RPC and hides version."""
        shield_tpl = os.path.join(BASE_DIR, "core", "templates", "leanstack-shield.php.tpl")
        self.assertTrue(os.path.exists(shield_tpl))
        with open(shield_tpl, "r") as f:
            content = f.read()
        self.assertIn("xmlrpc_enabled", content)
        self.assertIn("wp_generator", content)
        self.assertIn("author", content)
        self.assertIn("image_editor_output_format", content)
        self.assertIn("image/avif", content)

    def test_tenant_config_and_security_suite(self):
        """Verify Nginx linter, gatekeeper, bridge plugin, and CSP worker-src blob:."""
        linter_bin = os.path.join(BASE_DIR, "core", "bin", "cp-nginx-linter")
        self.assertTrue(os.path.exists(linter_bin) and os.access(linter_bin, os.X_OK))

        bridge_tpl = os.path.join(BASE_DIR, "core", "templates", "leanstack-bridge.php.tpl")
        self.assertTrue(os.path.exists(bridge_tpl))
        with open(bridge_tpl, "r") as f:
            b_content = f.read()
        self.assertIn("LeanStackBridge", b_content)
        self.assertIn("worker-src", b_content)
        self.assertIn("blob:", b_content)
        self.assertIn("custom-early", b_content)

        ssl_headers = os.path.join(BASE_DIR, "core", "snippets", "ssl-headers.conf")
        with open(ssl_headers, "r") as f:
            h_content = f.read()
        self.assertIn("worker-src 'self' blob:;", h_content)

        lsctl_bin = os.path.join(BASE_DIR, "core", "bin", "lsctl")
        with open(lsctl_bin, "r") as f:
            c_content = f.read()
        self.assertIn("custom-early.conf", c_content)
        self.assertIn("security-headers.conf", c_content)
        self.assertIn(".nginx.conf", c_content)

    def test_cache_architecture_and_mu_plugins(self):
        """Verify FastCGI per-site cache, SSI hole-punching, APCu, and Bridge cache suite."""
        # 1. Templates exist
        holepunch_tpl = os.path.join(BASE_DIR, "core", "templates", "leanstack-holepunch.php.tpl")
        apcu_tpl = os.path.join(BASE_DIR, "core", "templates", "leanstack-apcu.php.tpl")
        bridge_tpl = os.path.join(BASE_DIR, "core", "templates", "leanstack-bridge.php.tpl")
        vhost_tpl = os.path.join(BASE_DIR, "core", "templates", "vhost.conf.tpl")

        self.assertTrue(os.path.exists(holepunch_tpl))
        self.assertTrue(os.path.exists(apcu_tpl))
        self.assertTrue(os.path.exists(bridge_tpl))
        self.assertTrue(os.path.exists(vhost_tpl))

        # 2. Vhost template checks
        with open(vhost_tpl, "r") as f:
            v_content = f.read()
        self.assertIn("fastcgi_cache CACHE_{{ZONE_KEY}};", v_content)
        self.assertIn("ssi on;", v_content)
        self.assertIn("cache-config.conf", v_content)
        self.assertIn("location ~ /leanstack-purge", v_content)
        self.assertIn("location /leanstack-esi/", v_content)

        # 3. Bridge template cache controls
        with open(bridge_tpl, "r") as f:
            b_content = f.read()
        self.assertIn("leanstack-cache", b_content)
        self.assertIn("purge_fastcgi_url", b_content)
        self.assertIn("purge_tenant_opcache", b_content)
        self.assertIn("purge_tenant_apcu", b_content)
        self.assertIn("purge_cloudflare_all", b_content)

        # 4. lsctl provisioning checks
        lsctl_bin = os.path.join(BASE_DIR, "core", "bin", "lsctl")
        with open(lsctl_bin, "r") as f:
            c_content = f.read()
        self.assertIn("cache-config.conf", c_content)
        self.assertIn("leanstack-holepunch.php", c_content)
        self.assertIn("leanstack-apcu.php", c_content)
        self.assertIn("/var/cache/angie/sites", c_content)
        self.assertIn("/etc/angie/cache-zones", c_content)

    def test_sqlite_db_lifecycle(self):
        """Verify SQLite database schema and operations."""
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            conn = sqlite3.connect(tmp.name)
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE sites (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    domain TEXT UNIQUE NOT NULL,
                    user TEXT NOT NULL,
                    php_version TEXT NOT NULL,
                    pool_type TEXT NOT NULL,
                    pool_mode TEXT DEFAULT 'dynamic',
                    memory_limit TEXT DEFAULT '256M',
                    table_prefix TEXT DEFAULT 'wp_',
                    is_cf INTEGER DEFAULT 0,
                    profile_used TEXT DEFAULT 'default',
                    site_path TEXT NOT NULL,
                    db_name TEXT NOT NULL,
                    db_user TEXT NOT NULL,
                    db_pass TEXT NOT NULL,
                    admin_user TEXT NOT NULL,
                    admin_pass TEXT NOT NULL,
                    admin_email TEXT NOT NULL,
                    wp_version TEXT DEFAULT 'latest',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
            """)
            # Insert site
            cur.execute("""
                INSERT INTO sites (domain, user, php_version, pool_type, site_path, db_name, db_user, db_pass, admin_user, admin_pass, admin_email)
                VALUES ('shop.example.com', 'shop_u123', '8.4', 'dedicated', '/home/shop_u123/htdocs', 'shop_db', 'shop_usr', 'secret', 'admin', 'pass', 'a@e.com');
            """)
            conn.commit()

            cur.execute("SELECT domain, user, php_version FROM sites WHERE domain='shop.example.com'")
            row = cur.fetchone()
    def test_cpctl_profile_commands(self):
        """Verify cpctl profile:list and profile:show CLI commands output valid data."""
        import subprocess
        import json
        cpctl_bin = os.path.join(BASE_DIR, "core", "bin", "cpctl")
        
        # Test profile:list --json
        res = subprocess.run([cpctl_bin, "profile:list", "--json"], stdout=subprocess.PIPE, text=True, check=True)
        profiles = json.loads(res.stdout)
        self.assertIn("default", profiles)
        self.assertIn("agency_woocommerce", profiles)
        self.assertEqual(profiles["default"]["php"], "8.5")

        # Test profile:show agency_woocommerce --json
        res_show = subprocess.run([cpctl_bin, "profile:show", "agency_woocommerce", "--json"], stdout=subprocess.PIPE, text=True, check=True)
        woo = json.loads(res_show.stdout)
        self.assertEqual(woo["php"], "8.5")
        self.assertEqual(woo["memory_limit"], "512M")
        self.assertTrue(woo["cf"])

if __name__ == "__main__":
    unittest.main()
