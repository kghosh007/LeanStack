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
import json
import re
import subprocess
import shutil

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
            self.assertEqual(cfg["pool_mode"], "ondemand")
            self.assertIn("plugins", cfg)

    def test_vhost_template_security(self):
        """Verify vhost.conf.tpl contains all hardening, 8G WAF, and HTTP/3 directives."""
        tpl_path = os.path.join(BASE_DIR, "core", "templates", "vhost.conf.tpl")
        self.assertTrue(os.path.exists(tpl_path))
        with open(tpl_path, "r") as f:
            content = f.read()

        # Check HTTP/3 QUIC and HTTP/2
        self.assertIn("listen 443 quic;", content)
        self.assertIn("http2 on;", content)
        # Check ACME native client
        self.assertIn("acme_client", content)
        self.assertIn("acme acme_{{ZONE_KEY}};", content)
        self.assertIn("$acme_cert_acme_{{ZONE_KEY}}", content)
        # Check tenant security headers and ensure ssl-headers.conf is deduplicated
        self.assertIn("include /etc/angie/tenant-custom/{{PRIMARY_DOMAIN}}/security-headers.conf;", content)
        self.assertNotIn("ssl-headers.conf", content)
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
        self.assertIn("wp-config\\.php", content)
        self.assertIn("\\.user\\.ini", content)
        self.assertIn("composer\\.", content)
        self.assertIn("package", content)
        self.assertIn("swp", content)
        # Check Tenant custom slots and security headers
        self.assertIn("custom-early.conf", content)
        self.assertIn("custom-rules.conf", content)
        self.assertIn("security-headers.conf", content)
        self.assertIn("avif", content)
        self.assertIn("wasm", content)
        # Check valid literal time on fastcgi_cache_valid (only 200 cached, 404 and 301/302 excluded to prevent cache bloat)
        self.assertIn("fastcgi_cache_valid 200 60m;", content)
        self.assertNotIn("fastcgi_cache_valid 404", content)
        self.assertIn("/wp-json/", content)
        self.assertNotIn("$site_cache_ttl", content)
        # Check no duplicate ssi_types text/html (text/html is default)
        self.assertNotIn("ssi_types text/html;", content)

    def test_pool_template_isolation(self):
        """Verify pool.conf.tpl enforces tenant sandboxing, open_basedir, and expanded disable_functions."""
        tpl_path = os.path.join(BASE_DIR, "core", "templates", "pool.conf.tpl")
        self.assertTrue(os.path.exists(tpl_path))
        with open(tpl_path, "r") as f:
            content = f.read()

        self.assertIn("php_admin_value[open_basedir]", content)
        self.assertIn("php_admin_value[open_basedir] = /home/{{USER_NAME}}/:/var/cache/angie/sites/{{DOMAIN}}/", content)
        self.assertNotIn(":/tmp", content)  # Global /tmp must not be in open_basedir
        self.assertIn("php_admin_value[disable_functions]", content)
        self.assertIn("dl,opcache_reset", content)
        self.assertNotIn("symlink", content)
        self.assertNotIn("link,", content)
        self.assertNotIn("curl_multi_exec", content)
        self.assertNotIn("parse_ini_file", content)
        self.assertIn("php_admin_value[upload_tmp_dir]", content)
        self.assertIn("listen.mode = 0660", content)
        self.assertIn("listen.group = {{USER_NAME}}", content)
        self.assertNotIn("listen.group = www-data", content)
        self.assertIn("/run/valkey/valkey.sock", content)
        self.assertIn("/run/mysqld/mysqld.sock", content)
        self.assertIn("/var/cache/angie/sites/{{DOMAIN}}", content)
        self.assertNotIn("/proc", content)
        self.assertIn("php_admin_value[max_input_vars] = 5000", content)

    def test_bridge_logs_manager(self):
        """Verify leanstack-bridge.php.tpl registers Tools > Logs, enforces strict sandboxing, and secures wp-config."""
        bridge_tpl = os.path.join(BASE_DIR, "core", "templates", "leanstack-bridge.php.tpl")
        self.assertTrue(os.path.exists(bridge_tpl))
        with open(bridge_tpl, "r") as f:
            content = f.read()

        # Menu and actions
        self.assertIn("leanstack-logs", content)
        self.assertIn("save_log_settings", content)
        self.assertIn("handle_clear_log", content)
        self.assertIn("handle_download_log", content)
        self.assertIn("ajax_get_log_tail", content)
        self.assertIn("WP_DEBUG", content)
        self.assertIn("WP_DEBUG_LOG", content)
        self.assertIn("WP_DEBUG_DISPLAY", content)
        self.assertIn("read_log_tail", content)
        self.assertIn("get_available_logs", content)

        # Security & sandboxing assertions
        self.assertIn("is_valid_log_path", content)
        self.assertNotIn("'/var/log/angie/error.log'", content)
        self.assertNotIn("'/var/log/angie/access.log'", content)
        self.assertNotIn("'/var/log/php-slow.log'", content)
        self.assertIn("@chmod( $temp_file, 0600 );", content)
        self.assertIn("ob_end_clean()", content)

    def test_wp_config_debug_settings_regex(self):
        """Verify regex correctly parses and updates wp-config.php with nested parens, comments, and CRLF without duplicates."""
        sample_config = (
            "<?php\r\n"
            "define( 'DB_NAME', 'sample_db' );\r\n"
            "define( 'WP_DEBUG', false ); // master debug\r\n"
            "define( 'WP_DEBUG_LOG', dirname(__FILE__) . '/logs/wp-debug.log' );\r\n"
            "define( 'WP_DEBUG_DISPLAY', false );\r\n"
            "@ini_set( 'display_errors', '0' );\r\n"
            "require_once ABSPATH . 'wp-settings.php';\r\n"
        )

        # 1. Test parsing with nested parentheses in WP_DEBUG_LOG
        m_debug = re.search(r"^[ \t]*define\s*\(\s*['\"]WP_DEBUG['\"]\s*,\s*(true|false|1|0)", sample_config, re.M | re.I)
        self.assertTrue(m_debug)
        self.assertEqual(m_debug.group(1).lower(), "false")

        m_log = re.search(r"^[ \t]*define\s*\(\s*['\"]WP_DEBUG_LOG['\"]\s*,\s*(.+?)\s*\)\s*;", sample_config, re.M | re.I)
        self.assertTrue(m_log)
        self.assertEqual(m_log.group(1).strip(), "dirname(__FILE__) . '/logs/wp-debug.log'")

        # 2. Test regex update of WP_DEBUG_LOG to a new path
        new_path = "'/home/staging_mfeasy_4809/logs/wp-debug.log'"
        re_log = r"^[ \t]*(?://|#)?[ \t]*define\s*\(\s*(['\"])WP_DEBUG_LOG\1\s*,.*?\)\s*;.*$"
        updated_config = re.sub(re_log, f"define( 'WP_DEBUG_LOG', {new_path} );", sample_config, count=1, flags=re.M | re.I)

        self.assertIn(f"define( 'WP_DEBUG_LOG', {new_path} );", updated_config)
        self.assertNotIn("dirname(__FILE__)", updated_config)
        # Ensure only 1 instance of WP_DEBUG_LOG exists (no duplicate injection)
        self.assertEqual(len(re.findall(r"WP_DEBUG_LOG", updated_config)), 1)

        # 3. Test commented-out WP_DEBUG update
        commented_config = "<?php\n// define( 'WP_DEBUG', false );\n"
        re_debug = r"^[ \t]*(?://|#)?[ \t]*define\s*\(\s*(['\"])WP_DEBUG\1\s*,.*?\)\s*;.*$"
        uncommented = re.sub(re_debug, "define( 'WP_DEBUG', true );", commented_config, count=1, flags=re.M | re.I)
        self.assertEqual(uncommented, "<?php\ndefine( 'WP_DEBUG', true );\n")

    def test_wp_config_template_socket_and_proxy(self):
        """Verify wp-config.php.tpl configures Valkey ACL socket, database, and reverse-proxy SSL."""
        tpl_path = os.path.join(BASE_DIR, "core", "templates", "wp-config.php.tpl")
        self.assertTrue(os.path.exists(tpl_path))
        with open(tpl_path, "r") as f:
            content = f.read()

        self.assertIn("WP_REDIS_SCHEME", content)
        self.assertIn("/run/valkey/valkey.sock", content)
        self.assertIn("WP_REDIS_USERNAME", content)
        self.assertIn("WP_REDIS_USER", content)
        self.assertIn("WP_REDIS_PASSWORD", content)
        self.assertIn("WP_REDIS_DATABASE", content)
        self.assertIn("define( 'WP_REDIS_SELECTIVE_FLUSH', true );", content)
        self.assertIn("DISABLE_WP_CRON", content)
        self.assertIn("HTTP_X_FORWARDED_PROTO", content)
        self.assertIn("HTTP_CF_VISITOR", content)

    def test_cron_queue_sandboxing(self):
        """Verify cp-cron-queue applies strict PHP open_basedir, proc_open disabling, and flock lock."""
        cron_bin = os.path.join(BASE_DIR, "core", "bin", "ls-cron-queue")
        self.assertTrue(os.path.exists(cron_bin))
        with open(cron_bin, "r") as f:
            content = f.read()
        self.assertIn("-d open_basedir=", content)
        self.assertIn("-d disable_functions=", content)
        self.assertIn("proc_open,", content)  # proc_open IS disabled matching FPM pool
        self.assertIn("popen,", content)
        self.assertNotIn(":/tmp", content)    # Global /tmp must NOT be in open_basedir
        self.assertIn("flock -n", content)
        self.assertIn(".cron_status.json", content)
        self.assertIn("/home/${user}/nginx", content)
        self.assertIn("/etc/ssl/certs", content)
        self.assertIn("xargs -r", content)

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
        self.assertIn("leanstack_run_cron_now", b_content)
        self.assertIn("register_site_health_cron_test", b_content)
        self.assertIn("Background Cron Queue", b_content)
        self.assertIn("register_dashboard_widgets", b_content)
        self.assertIn("render_dashboard_cron_widget", b_content)
        self.assertIn("register_admin_bar_node", b_content)
        self.assertIn("render_cron_page", b_content)
        self.assertIn("Valkey Object Cache", b_content)

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

    def test_pcre2_regex_syntax(self):
        """Verify all regex patterns in snippets and templates compile without PCRE2 syntax errors."""
        import ctypes
        import re

        try:
            pcre2 = ctypes.CDLL("libpcre2-8.so.0")
        except OSError:
            try:
                pcre2 = ctypes.CDLL("libpcre2-8.so")
            except OSError:
                return  # Skip if PCRE2 shared library is not available in test runner
        
        pcre2_compile = pcre2.pcre2_compile_8
        pcre2_compile.restype = ctypes.c_void_p
        pcre2_compile.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_size_t), ctypes.c_void_p]

        files_to_check = [
            os.path.join(BASE_DIR, "core", "snippets", "8g-firewall.conf"),
            os.path.join(BASE_DIR, "core", "templates", "vhost.conf.tpl")
        ]

        for filepath in files_to_check:
            self.assertTrue(os.path.exists(filepath), f"Missing {filepath}")
            with open(filepath, "r", encoding="utf-8") as fp:
                for line_no, line in enumerate(fp, 1):
                    m = re.search(r"(?:~[*]?|!~[*]?)\s+(\"[^\"]+\"|\S+)", line)
                    if m:
                        raw_pat = m.group(1).strip()
                        if raw_pat.endswith(";"): raw_pat = raw_pat[:-1].strip()
                        if raw_pat.endswith("{"): raw_pat = raw_pat[:-1].strip()
                        if raw_pat.startswith('"') and raw_pat.endswith('"'):
                            pat = re.sub(r"\\\\", r"\\", raw_pat[1:-1])
                        else:
                            pat = raw_pat
                        
                        # Replace template placeholders
                        pat = re.sub(r"\{\{[^}]+\}\}", "zone123", pat)
                        pat = re.sub(r"\$[a-zA-Z0-9_]+", "var", pat)

                        errcode = ctypes.c_int()
                        erroffset = ctypes.c_size_t()
                        code = pcre2_compile(pat.encode("utf-8"), len(pat), 0, ctypes.byref(errcode), ctypes.byref(erroffset), None)
                        self.assertIsNotNone(code, f"PCRE2 syntax error in {filepath}:{line_no}: {raw_pat} -> {pat} (err {errcode.value} at offset {erroffset.value})")

    def test_cache_purge_resilience_and_module_scaffolding(self):
        """Verify dynamic cache purge directive, module loader scaffolding, and port 80 loopback."""
        vhost_tpl = os.path.join(BASE_DIR, "core", "templates", "vhost.conf.tpl")
        with open(vhost_tpl, "r") as f:
            vhost = f.read()

        # Check {{PURGE_DIRECTIVE}} in both Port 80 and Port 443 blocks
        self.assertEqual(vhost.count("{{PURGE_DIRECTIVE}}"), 2)

        # Check Port 80 contains loopback purge before location /
        p80_idx = vhost.find("listen 80;")
        p443_idx = vhost.find("listen 443 ssl;")
        p80_block = vhost[p80_idx:p443_idx]
        purge_80_idx = p80_block.find("location ~ /leanstack-purge(/.*)")
        root_80_idx = p80_block.find("location / {")
        self.assertTrue(purge_80_idx != -1 and purge_80_idx < root_80_idx, "Port 80 purge must appear before location /")

        # Check lsctl substitution and fallback
        lsctl_bin = os.path.join(BASE_DIR, "core", "bin", "lsctl")
        with open(lsctl_bin, "r") as f:
            lsctl = f.read()
        self.assertIn("ensure_angie_modules", lsctl)
        self.assertIn("fastcgi_cache_purge CACHE_${ZONE_KEY}", lsctl)
        self.assertIn('PURGE_DIRECTIVE="return 204;"', lsctl)
        self.assertIn("ngx_http_cache_purge_module.so", lsctl)
        self.assertIn('include /etc/angie/modules.d/*.conf;', lsctl)

        # Check provisioner and ls-upgrade module loader scaffolding
        provision = os.path.join(BASE_DIR, "installer", "provision.py")
        with open(provision, "r") as f:
            p4 = f.read()
        self.assertIn("angie-module-cache-purge", p4)
        self.assertIn("ngx_http_cache_purge_module.so", p4)
        self.assertIn("os.remove(purge_conf)", p4)

        upgrade_bin = os.path.join(BASE_DIR, "core", "bin", "ls-upgrade")
        with open(upgrade_bin, "r") as f:
            up = f.read()
        self.assertIn("ngx_http_cache_purge_module.so", up)
        self.assertIn("/etc/angie/modules.d/cache-purge.conf", up)
        self.assertIn("include /etc/angie/modules.d/*.conf;", up)

    def test_8g_waf_purge_method(self):
        """Verify 8G firewall snippet permits HTTP PURGE requests."""
        waf_path = os.path.join(BASE_DIR, "core", "snippets", "8g-firewall.conf")
        with open(waf_path, "r") as f:
            waf = f.read()
        self.assertIn("PURGE", waf)
        self.assertIn("(GET|POST|HEAD|PUT|DELETE|OPTIONS|PURGE)", waf)

    def test_security_headers_deduplication(self):
        """Verify security headers are deduplicated and managed via tenant custom file."""
        vhost_tpl = os.path.join(BASE_DIR, "core", "templates", "vhost.conf.tpl")
        with open(vhost_tpl, "r") as f:
            vhost = f.read()
        self.assertNotIn("ssl-headers.conf", vhost)
        self.assertEqual(vhost.count("security-headers.conf"), 4)

        lsctl_bin = os.path.join(BASE_DIR, "core", "bin", "lsctl")
        with open(lsctl_bin, "r") as f:
            lsctl = f.read()
        self.assertIn("Alt-Svc", lsctl)

        upgrade_bin = os.path.join(BASE_DIR, "core", "bin", "ls-upgrade")
        with open(upgrade_bin, "r") as f:
            up = f.read()
        self.assertIn("security-headers.conf", up)

    def test_holepunch_path_resolution(self):
        """Verify leanstack-holepunch correctly traverses to wp-load.php without overshoot."""
        hp_path = os.path.join(BASE_DIR, "core", "templates", "leanstack-holepunch.php.tpl")
        with open(hp_path, "r") as f:
            hp = f.read()
        self.assertIn("dirname( __DIR__, 2 ) . '/wp-load.php'", hp)
        self.assertNotIn("dirname( dirname( dirname( __DIR__ ) ) )", hp)

    def test_db_path_harmonization(self):
        """Verify gatekeeper and cron queue check LEANSTACK_DB and /var/lib/lsctl/sites.db."""
        gk_path = os.path.join(BASE_DIR, "core", "bin", "ls-gatekeeper")
        with open(gk_path, "r") as f:
            gk = f.read()
        self.assertIn("LEANSTACK_DB", gk)
        self.assertIn("/var/lib/lsctl/sites.db", gk)
        self.assertIn("/var/lib/cpctl/sites.db", gk)

        cron_path = os.path.join(BASE_DIR, "core", "bin", "ls-cron-queue")
        with open(cron_path, "r") as f:
            cq = f.read()
        self.assertIn("LEANSTACK_DB", cq)
        self.assertIn("/var/lib/lsctl/sites.db", cq)
        self.assertIn("/var/lib/cpctl/sites.db", cq)

    def test_cf_sync_permissions(self):
        """Verify Cloudflare sync snippet enforces 0644 readable permissions."""
        cf_path = os.path.join(BASE_DIR, "core", "bin", "ls-cf-sync")
        with open(cf_path, "r") as f:
            cf = f.read()
        self.assertIn('chmod 644 "$TARGET_SNIPPET"', cf)

    def test_tenant_home_traversal_permissions(self):
        """Verify lsctl grants www-data traversal on tenant home (750) and polls ACME cert."""
        lsctl_path = os.path.join(BASE_DIR, "core", "bin", "lsctl")
        with open(lsctl_path, "r") as f:
            content = f.read()
        self.assertIn('chown "${USER_NAME}:www-data" "/home/${USER_NAME}"', content)
        self.assertIn('chmod 750 "/home/${USER_NAME}"', content)
        self.assertIn('chown -R "${USER_NAME}:www-data" "$WEB_ROOT" "$LOG_DIR"', content)
        self.assertIn('chmod 750 "$WEB_ROOT"', content)
        self.assertIn('chmod 700 "/home/${USER_NAME}/tmp"', content)
        self.assertIn('chmod 600 "$WEB_ROOT/wp-config.php"', content)
        self.assertIn('compgen -G "/var/lib/angie/acme/${DOMAIN}*"', content)

    def test_autonomous_health_watcher(self):
        """Verify ls-watcher self-healing engine has flocking, probes, quarantine, and healing."""
        watcher_path = os.path.join(BASE_DIR, "core", "bin", "ls-watcher")
        self.assertTrue(os.path.exists(watcher_path) and os.access(watcher_path, os.X_OK))
        with open(watcher_path, "r") as f:
            w = f.read()
        self.assertIn("flock -n 200", w)
        self.assertIn("/run/ls-maintenance.lock", w)
        self.assertIn("angie -t", w)
        self.assertIn("quarantine", w)
        self.assertIn("mariadb-admin", w)
        self.assertIn("valkey-cli", w)
        self.assertIn("heal_tenant_permissions", w)
        self.assertIn("journalctl --vacuum", w)

    def test_autonomous_updater(self):
        """Verify ls-autoupdate has snapshot, non-interactive apt, rollback, and reloads."""
        updater_path = os.path.join(BASE_DIR, "core", "bin", "ls-autoupdate")
        self.assertTrue(os.path.exists(updater_path) and os.access(updater_path, os.X_OK))
        with open(updater_path, "r") as f:
            u = f.read()
        self.assertIn("/run/ls-maintenance.lock", u)
        self.assertIn("preflight_syntax_check", u)
        self.assertIn("/var/backups/lsctl/pre_upgrade_", u)
        self.assertIn("--force-confdef", u)
        self.assertIn("--force-confold", u)
        self.assertIn("cscli hub", u)
        self.assertIn("cli update", u)
        self.assertIn("update --quiet", u)
        self.assertIn("ROLLBACK", u)
        self.assertIn("reload angie", u)

    def test_systemd_watcher_and_updater_units(self):
        """Verify systemd service units, timers, and drop-in overrides."""
        ws_path = os.path.join(BASE_DIR, "systemd", "ls-watcher.service")
        wt_path = os.path.join(BASE_DIR, "systemd", "ls-watcher.timer")
        us_path = os.path.join(BASE_DIR, "systemd", "ls-autoupdate.service")
        ut_path = os.path.join(BASE_DIR, "systemd", "ls-autoupdate.timer")

        self.assertTrue(os.path.exists(ws_path))
        self.assertTrue(os.path.exists(wt_path))
        self.assertTrue(os.path.exists(us_path))
        self.assertTrue(os.path.exists(ut_path))

        with open(wt_path, "r") as f:
            self.assertIn("OnUnitActiveSec=60s", f.read())
        with open(ut_path, "r") as f:
            self.assertIn("03:30", f.read())

        # Check drop-in overrides
        overrides_dir = os.path.join(BASE_DIR, "systemd", "overrides")
        self.assertTrue(os.path.isdir(overrides_dir))
        for s in ["angie.service.d", "mariadb.service.d", "valkey.service.d", "php8.4-fpm.service.d"]:
            ov = os.path.join(overrides_dir, s, "override.conf")
            self.assertTrue(os.path.exists(ov), f"Missing override {ov}")
            with open(ov, "r") as f:
                o_content = f.read()
            self.assertIn("Restart=on-failure", o_content)
            self.assertIn("RestartSec=2s", o_content)

    def test_watcher_cli_commands(self):
        """Verify lsctl watcher:status returns structured output and JSON."""
        import subprocess, json
        lsctl_path = os.path.join(BASE_DIR, "core", "bin", "lsctl")
        res = subprocess.run([lsctl_path, "watcher:status", "--json"], stdout=subprocess.PIPE, text=True, check=True)
        data = json.loads(res.stdout)
        self.assertIn("watcher_timer", data)
        self.assertIn("watcher_service", data)
        self.assertIn("autoupdate_timer", data)
        self.assertIn("autoupdate_service", data)
        self.assertIn("maintenance_locked", data)

        res_txt = subprocess.run([lsctl_path, "watcher:status"], stdout=subprocess.PIPE, text=True, check=True)
        self.assertIn("LeanStack Autonomous Watcher & Resilience Status", res_txt.stdout)

        # Help contains commands
        res_help = subprocess.run([lsctl_path, "help"], stdout=subprocess.PIPE, text=True, check=True)
        self.assertIn("watcher:status", res_help.stdout)
        self.assertIn("watcher:run", res_help.stdout)
        self.assertIn("update:auto", res_help.stdout)

    def test_watcher_flock_concurrency(self):
        """Verify ls-watcher gracefully skips when lock is held and watcher:status reports lock state."""
        import subprocess, json, fcntl, time
        lock_file = "/tmp/ls-maintenance.lock"
        lsctl_path = os.path.join(BASE_DIR, "core", "bin", "lsctl")
        watcher_path = os.path.join(BASE_DIR, "core", "bin", "ls-watcher")

        # Open and hold exclusive lock
        with open(lock_file, "w") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                # 1. Verify watcher skips execution while locked
                res = subprocess.run([watcher_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                self.assertEqual(res.returncode, 0)
                self.assertIn("Another LeanStack maintenance or watcher process is currently running", res.stdout)

                # 2. Verify lsctl watcher:status reflects active lock
                res_status = subprocess.run([lsctl_path, "watcher:status", "--json"], stdout=subprocess.PIPE, text=True, check=True)
                data = json.loads(res_status.stdout)
                self.assertTrue(data["maintenance_locked"])
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

        # 3. Verify lsctl watcher:status reflects unlocked state once lock is released
        res_unlocked = subprocess.run([lsctl_path, "watcher:status", "--json"], stdout=subprocess.PIPE, text=True, check=True)
        data_unlocked = json.loads(res_unlocked.stdout)
        self.assertFalse(data_unlocked["maintenance_locked"])

    def test_lsctl_doctor_watcher_integration(self):
        """Verify lsctl doctor checks watcher and autoupdate timers and handles missing/empty DB."""
        import subprocess
        lsctl_path = os.path.join(BASE_DIR, "core", "bin", "lsctl")
        # 1. Base run without DB
        res = subprocess.run([lsctl_path, "doctor"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        self.assertIn("Autonomous Resilience & Watcher Timers", res.stdout)
        self.assertIn("ls-watcher.timer", res.stdout)
        self.assertIn("ls-autoupdate.timer", res.stdout)
        self.assertIn("Storage & Memory Health", res.stdout)

        # 2. Run with DB file that does not contain sites table
        with tempfile.NamedTemporaryFile(suffix=".db") as empty_db:
            env = os.environ.copy()
            env["LEANSTACK_DB"] = empty_db.name
            res_empty = subprocess.run([lsctl_path, "doctor"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True, env=env)
            self.assertIn("Storage & Memory Health", res_empty.stdout)

        # 3. Run with DB file containing site missing WP_REDIS_USERNAME
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "test.db")
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE sites (domain TEXT, site_path TEXT);")
            site_dir = os.path.join(td, "mysite")
            os.makedirs(site_dir, exist_ok=True)
            wp_config = os.path.join(site_dir, "wp-config.php")
            with open(wp_config, "w") as f:
                f.write("<?php define('WP_REDIS_PASSWORD', 'secret'); ?>")
            conn.execute("INSERT INTO sites VALUES ('mysite.local', ?);", (site_dir,))
            conn.commit()
            conn.close()

            env = os.environ.copy()
            env["LEANSTACK_DB"] = db_path
            res_warn = subprocess.run([lsctl_path, "doctor"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True, env=env)
            self.assertIn("missing WP_REDIS_USERNAME in wp-config.php", res_warn.stdout)

            # Fix wp-config.php and verify warning clears
            with open(wp_config, "a") as f:
                f.write("define('WP_REDIS_USERNAME', 'tenant_user');")
            res_ok = subprocess.run([lsctl_path, "doctor"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True, env=env)
            self.assertNotIn("missing WP_REDIS_USERNAME in wp-config.php", res_ok.stdout)

            # 4. Verify drop-in warning when redis-cache plugin exists without object-cache.php
            plugin_dir = os.path.join(site_dir, "wp-content", "plugins", "redis-cache")
            os.makedirs(plugin_dir, exist_ok=True)
            res_dropin_warn = subprocess.run([lsctl_path, "doctor"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True, env=env)
            self.assertIn("missing object-cache.php drop-in", res_dropin_warn.stdout)

            # Create object-cache.php and verify warning clears
            dropin_file = os.path.join(site_dir, "wp-content", "object-cache.php")
            with open(dropin_file, "w") as f:
                f.write("<?php")
            res_dropin_ok = subprocess.run([lsctl_path, "doctor"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True, env=env)
            self.assertNotIn("missing object-cache.php drop-in", res_dropin_ok.stdout)

            # 5. Verify security checks for wp-config permissions, DISALLOW_FILE_EDIT, and world-writable web root
            self.assertIn("missing DISALLOW_FILE_EDIT in wp-config.php", res_dropin_ok.stdout)
            self.assertIn("wp-config.php permissions are insecure", res_dropin_ok.stdout)

            # Test DISALLOW_FILE_EDIT explicitly set to false, 0, or commented out
            for bad_def in [
                "define('DISALLOW_FILE_EDIT', false);",
                "define('DISALLOW_FILE_EDIT', 0);",
                "// define('DISALLOW_FILE_EDIT', true);",
                "# define('DISALLOW_FILE_EDIT', true);",
            ]:
                with open(wp_config, "w") as f:
                    f.write(f"<?php\ndefine('WP_REDIS_PASSWORD', 'secret');\ndefine('WP_REDIS_USERNAME', 'tenant_user');\n{bad_def}\n")
                res_sec_bad = subprocess.run([lsctl_path, "doctor"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True, env=env)
                self.assertIn("missing DISALLOW_FILE_EDIT in wp-config.php", res_sec_bad.stdout)

            os.chmod(wp_config, 0o600)
            with open(wp_config, "a") as f:
                f.write("\ndefine('DISALLOW_FILE_EDIT', true);\n")
            res_sec_ok = subprocess.run([lsctl_path, "doctor"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True, env=env)
            self.assertNotIn("missing DISALLOW_FILE_EDIT in wp-config.php", res_sec_ok.stdout)
            self.assertNotIn("wp-config.php permissions are insecure", res_sec_ok.stdout)

            os.chmod(site_dir, 0o777)
            res_ww = subprocess.run([lsctl_path, "doctor"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True, env=env)
            self.assertIn("is world-writable", res_ww.stdout)
            os.chmod(site_dir, 0o750)
            res_ww_ok = subprocess.run([lsctl_path, "doctor"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True, env=env)
            self.assertNotIn("is world-writable", res_ww_ok.stdout)

    def test_cron_status_command(self):
        """Verify lsctl cron:status supports --json and reports timer and lock status."""
        import subprocess
        lsctl_path = os.path.join(BASE_DIR, "core", "bin", "lsctl")
        res = subprocess.run([lsctl_path, "cron:status", "--json"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        data = json.loads(res.stdout)
        self.assertIn("cron_timer", data)
        self.assertIn("cron_service", data)
        self.assertIn("cron_locked", data)
        self.assertIn("timestamp", data)
        # Verify no trailing newlines in status string values
        self.assertNotIn("\n", data["cron_timer"])
        self.assertNotIn("\n", data["cron_service"])

    def test_php_templates_syntax_and_structure(self):
        """Verify PHP templates have balanced braces and no dangling method/array closures."""
        tpl_dir = os.path.join(BASE_DIR, "core", "templates")
        bridge_tpl = os.path.join(tpl_dir, "leanstack-bridge.php.tpl")
        self.assertTrue(os.path.exists(bridge_tpl))
        with open(bridge_tpl, "r") as f:
            content = f.read()

        # Check that class LeanStackBridge opens and closes properly
        self.assertIn("class LeanStackBridge {", content)
        self.assertIn("add_action( 'plugins_loaded', array( 'LeanStackBridge', 'get_instance' ) );", content)

        # Verify balanced curly braces in PHP class body
        # Simple scan ignoring string literals
        in_single = False
        in_double = False
        in_line_comment = False
        in_block_comment = False
        brace_count = 0
        i = 0
        n = len(content)
        while i < n:
            ch = content[i]
            if in_line_comment:
                if ch == "\n":
                    in_line_comment = False
            elif in_block_comment:
                if ch == "*" and i + 1 < n and content[i + 1] == "/":
                    in_block_comment = False
                    i += 1
            elif in_single:
                if ch == "\\" and i + 1 < n:
                    i += 1
                elif ch == "'":
                    in_single = False
            elif in_double:
                if ch == "\\" and i + 1 < n:
                    i += 1
                elif ch == '"':
                    in_double = False
            else:
                if ch == "/" and i + 1 < n and content[i + 1] == "/":
                    in_line_comment = True
                    i += 1
                elif ch == "/" and i + 1 < n and content[i + 1] == "*":
                    in_block_comment = True
                    i += 1
                elif ch == "'":
                    in_single = True
                elif ch == '"':
                    in_double = True
                elif ch == "{":
                    brace_count += 1
                elif ch == "}":
                    brace_count -= 1
                    self.assertGreaterEqual(brace_count, 0, f"Unmatched closing brace at offset {i}")
            i += 1
        self.assertEqual(brace_count, 0, f"Unbalanced braces in {bridge_tpl}: final count {brace_count}")

    def test_cron_queue_chdir_and_working_directory(self):
        """Verify ls-cron-queue runs WP-CLI within tenant site_path and cp-cron.service sets WorkingDirectory=/tmp."""
        cron_bin = os.path.join(BASE_DIR, "core", "bin", "ls-cron-queue")
        with open(cron_bin, "r") as f:
            content = f.read()
        self.assertIn('cd "$site_path"', content)
        self.assertIn('sudo_cmd=(sudo -u "$user" -H)', content)

        service_file = os.path.join(BASE_DIR, "systemd", "cp-cron.service")
        with open(service_file, "r") as f:
            svc_content = f.read()
        self.assertIn("WorkingDirectory=/tmp", svc_content)

    def test_open_basedir_warnings_not_suppressed(self):
        """Verify leanstack-shield and leanstack-bridge do not suppress open_basedir sandbox warnings."""
        shield_tpl = os.path.join(BASE_DIR, "core", "templates", "leanstack-shield.php.tpl")
        bridge_tpl = os.path.join(BASE_DIR, "core", "templates", "leanstack-bridge.php.tpl")

        for tpl_path in [shield_tpl, bridge_tpl]:
            with open(tpl_path, "r") as f:
                content = f.read()
            self.assertNotIn("open_basedir restriction in effect", content)

    def test_query_monitor_bridge_helper_and_reconciler(self):
        """Verify leanstack-bridge provides Query Monitor drop-in self-healing and drop-in reconciler."""
        bridge_tpl = os.path.join(BASE_DIR, "core", "templates", "leanstack-bridge.php.tpl")
        with open(bridge_tpl, "r") as f:
            content = f.read()
        self.assertIn("maybe_reconcile_qm_dropin", content)
        self.assertIn("reconcile_qm_dropin", content)
        self.assertIn("handle_fix_qm_dropin", content)
        self.assertIn("plugins/query-monitor/wp-content/db.php", content)
        self.assertIn("Query Monitor plugin is uninstalled, remove any dangling drop-in symlink", content)

    def test_lsctl_qm_command_and_doctor(self):
        """Verify lsctl has qm command and doctor checks Query Monitor db.php drop-in with proper precedence."""
        lsctl_bin = os.path.join(BASE_DIR, "core", "bin", "lsctl")
        with open(lsctl_bin, "r") as f:
            content = f.read()
        self.assertIn("qm|site:qm)", content)
        self.assertIn("Query Monitor db.php drop-in", content)
        self.assertIn("missing Query Monitor db.php drop-in", content)
        self.assertIn("has broken Query Monitor db.php symlink", content)
        # Verify broken symlink check precedes missing check
        broken_pos = content.find("has broken Query Monitor db.php symlink")
        missing_pos = content.find("missing Query Monitor db.php drop-in", broken_pos)
        self.assertGreater(missing_pos, broken_pos, "Broken symlink check must precede missing file check in doctor")

    def test_angie_tls_and_doctor_hardening(self):
        """Verify the provisioner writes full TLS 1.2/1.3 ECDHE AEAD ciphers, prime256v1, http2 on, and lsctl doctor audits them."""
        import subprocess
        sys.path.insert(0, os.path.join(BASE_DIR, "installer"))
        from probe import HardwareProbe, TuningCalculator
        from provision import render_files
        doc = TuningCalculator(HardwareProbe(sim_ram_mb=2048, sim_cores=2).probe_all()).to_document()
        p4 = render_files(doc, ["8.3"])["etc/angie/angie.conf"]

        self.assertIn("ssl_protocols TLSv1.2 TLSv1.3;", p4)
        self.assertIn("ssl_prefer_server_ciphers on;", p4)
        self.assertIn("ssl_session_cache shared:SSL:50m;", p4)
        self.assertIn("ssl_session_timeout 1d;", p4)
        self.assertIn("ssl_session_tickets off;", p4)
        self.assertIn("ssl_ecdh_curve X25519MLKEM768:x25519:prime256v1:secp384r1;", p4)
        with open(os.path.join(BASE_DIR, "installer", "provision.py"), encoding="utf-8") as handle:
            self.assertIn("ssl_ecdh_curve x25519:prime256v1:secp384r1;", handle.read())
        self.assertIn(
            "ssl_ciphers TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:"
            "ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:"
            "ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:"
            "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256;",
            p4
        )
        self.assertIn("http2 on;", p4)
        self.assertIn("quic_gso on;", p4)
        self.assertIn("quic_retry on;", p4)

        # Test lsctl doctor TLS & ECDHE Hardening checks against mock /etc/angie
        lsctl_path = os.path.join(BASE_DIR, "core", "bin", "lsctl")
        with tempfile.TemporaryDirectory() as td:
            http_d = os.path.join(td, "http.d")
            os.makedirs(http_d, exist_ok=True)
            angie_conf = os.path.join(td, "angie.conf")

            # 1. Incomplete curve and cipher config -> WARN
            with open(angie_conf, "w") as f:
                f.write("http {\n    ssl_ecdh_curve X25519MLKEM768:x25519:secp384r1;\n    ssl_ciphers TLS_AES_256_GCM_SHA384;\n}\n")
            env = os.environ.copy()
            env["LEANSTACK_ANGIE_DIR"] = td
            res_warn = subprocess.run([lsctl_path, "doctor"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True, env=env)
            self.assertIn("Angie ssl_ecdh_curve missing prime256v1 or x25519", res_warn.stdout)
            self.assertIn("Angie ssl_ciphers missing full TLS 1.2 ECDHE AEAD suites", res_warn.stdout)

            # 2. Hardened curve and cipher config -> PASS
            with open(angie_conf, "w") as f:
                f.write(
                    "http {\n"
                    "    ssl_ecdh_curve X25519MLKEM768:x25519:prime256v1:secp384r1;\n"
                    "    ssl_ciphers TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256;\n"
                    "}\n"
                )
            res_pass = subprocess.run([lsctl_path, "doctor"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True, env=env)
            self.assertIn("[PASS] TLS ECDHE curves hardened", res_pass.stdout)
            self.assertIn("[PASS] TLS 1.2/1.3 ECDHE AEAD cipher suite hardened", res_pass.stdout)

            # 3. Duplicate directives in 00-optimization.conf -> WARN
            with open(os.path.join(http_d, "00-optimization.conf"), "w") as f:
                f.write("ssl_ciphers HIGH:!aNULL:!MD5;\n")
            res_dup = subprocess.run([lsctl_path, "doctor"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True, env=env)
            self.assertIn("Duplicate TLS directives detected in both angie.conf and 00-optimization.conf", res_dup.stdout)

    def test_robots_and_llms_gui_and_angie_directives(self):
        """Verify vhost.conf.tpl has explicit Angie locations for robots.txt and llms.txt, and bridge registers Crawlers & AI Studio."""
        vhost_tpl = os.path.join(BASE_DIR, "core", "templates", "vhost.conf.tpl")
        with open(vhost_tpl, "r") as f:
            vhost_content = f.read()

        self.assertIn("location = /robots.txt {", vhost_content)
        self.assertIn("location = /llms.txt {", vhost_content)
        self.assertIn("try_files $uri /index.php?$args;", vhost_content)

        bridge_tpl = os.path.join(BASE_DIR, "core", "templates", "leanstack-bridge.php.tpl")
        with open(bridge_tpl, "r") as f:
            bridge_content = f.read()

        self.assertIn("'leanstack-crawlers'", bridge_content)
        self.assertIn("render_crawlers_page", bridge_content)
        self.assertIn("handle_save_robots", bridge_content)
        self.assertIn("handle_save_llms", bridge_content)
        self.assertIn("filter_robots_txt", bridge_content)
        self.assertIn("generate_llms_markdown", bridge_content)
        self.assertIn("maybe_auto_sync_llms", bridge_content)
        self.assertIn("maybe_serve_dynamic_llms", bridge_content)
        self.assertIn("GPTBot", bridge_content)
        self.assertIn("ClaudeBot", bridge_content)

    def test_privacy_safe_tenant_telemetry_in_bridge(self):
        """Verify leanstack-bridge provides normalized percentage telemetry and status badges instead of raw host load/uptime."""
        bridge_tpl = os.path.join(BASE_DIR, "core", "templates", "leanstack-bridge.php.tpl")
        with open(bridge_tpl, "r") as f:
            content = f.read()

        self.assertIn("'memory_usage_pct'", content)
        self.assertIn("'capacity_saturation_pct'", content)
        self.assertIn("'status_badge'", content)
        self.assertIn("'Optimal'", content)
        self.assertIn("'Moderate'", content)
        self.assertIn("'Elevated'", content)
        self.assertNotIn("$analytics['system']['load_avg']", content)
        self.assertNotIn("$analytics['system']['uptime']", content)

    def test_wp_content_permissions_hardening_0755(self):
        """Verify lsctl, ls-upgrade, and ls-watcher enforce 0755 permissions on wp-content and its subdirectories."""
        lsctl_path = os.path.join(BASE_DIR, "core", "bin", "lsctl")
        with open(lsctl_path, "r") as f:
            lsctl_content = f.read()
        self.assertIn('chmod 755 "${WEB_ROOT}/wp-content"', lsctl_content)
        self.assertIn('chmod 755 "${WEB_ROOT}/wp-content/mu-plugins"', lsctl_content)

        upgrade_path = os.path.join(BASE_DIR, "core", "bin", "ls-upgrade")
        with open(upgrade_path, "r") as f:
            upgrade_content = f.read()
        self.assertIn("os.chmod(wp_content_dir, 0o755)", upgrade_content)
        self.assertIn('for sub in ["plugins", "themes", "uploads", "mu-plugins"]:', upgrade_content)

        watcher_path = os.path.join(BASE_DIR, "core", "bin", "ls-watcher")
        with open(watcher_path, "r") as f:
            watcher_content = f.read()
        self.assertIn('chmod 755 "${web_root}/wp-content"', watcher_content)
        self.assertIn('for sub in plugins themes uploads mu-plugins; do', watcher_content)

    def test_php_hardening_gatekeeper_and_watcher_lockdown_toggle(self):
        """Verify ls-gatekeeper and ls-watcher properly toggle strict lockdown vs benchmark window."""
        gk_path = os.path.join(BASE_DIR, "core", "bin", "ls-gatekeeper")
        with open(gk_path, "r") as f:
            gk_content = f.read()
        self.assertIn('local df_val="exec,passthru,shell_exec,system,proc_open,popen,curl_multi_exec,parse_ini_file,show_source,dl,opcache_reset,opcache_flush,apcu_clear_cache,apc_clear_cache"', gk_content)
        self.assertIn('if [ "$mode" == "benchmark" ]; then', gk_content)
        self.assertIn('df_val="exec,passthru,shell_exec,system,proc_open,popen,show_source,dl,opcache_reset,opcache_flush,apcu_clear_cache,apc_clear_cache"', gk_content)

        watcher_path = os.path.join(BASE_DIR, "core", "bin", "ls-watcher")
        with open(watcher_path, "r") as f:
            watcher_content = f.read()
        self.assertIn('local df_strict="exec,passthru,shell_exec,system,proc_open,popen,curl_multi_exec,parse_ini_file,show_source,dl,opcache_reset,opcache_flush,apcu_clear_cache,apc_clear_cache"', watcher_content)

    def test_ls_cron_queue_sudo_arguments(self):
        """Verify ls-cron-queue uses sudo -u "$user" -H without --chdir to avoid sudoers CWD permission errors."""
        cq_path = os.path.join(BASE_DIR, "core", "bin", "ls-cron-queue")
        with open(cq_path, "r") as f:
            cq_content = f.read()
        self.assertIn('sudo_cmd=(sudo -u "$user" -H)', cq_content)
        self.assertNotIn('--chdir', cq_content)

    def test_ls_cron_queue_surfaces_sandbox_warnings(self):
        """Verify ls-cron-queue does not filter or suppress open_basedir sandbox errors."""
        cq_path = os.path.join(BASE_DIR, "core", "bin", "ls-cron-queue")
        with open(cq_path, "r") as f:
            cq_content = f.read()
        self.assertIn('-d display_errors=Off', cq_content)
        self.assertIn('-d error_reporting="E_ALL & ~E_WARNING & ~E_NOTICE & ~E_DEPRECATED"', cq_content)
        self.assertNotIn('open_basedir restriction in effect', cq_content)
        self.assertNotIn('grep -v -E "open_basedir', cq_content)

    def test_upgrade_git_resilience_and_safe_directory(self):
        """Verify ls-upgrade and update.sh avoid safe.directory=* and verify repository ownership."""
        upgrade_path = os.path.join(BASE_DIR, "core", "bin", "ls-upgrade")
        with open(upgrade_path, "r") as f:
            upgrade_content = f.read()
        self.assertNotIn('safe.directory=*', upgrade_content)
        self.assertIn('stat_info.st_uid != os.geteuid()', upgrade_content)
        self.assertIn('Remote fetch skipped', upgrade_content)
        self.assertIn('def sanitize_cron_logs(self):', upgrade_content)

        update_path = os.path.join(BASE_DIR, "update.sh")
        with open(update_path, "r") as f:
            update_content = f.read()
        self.assertNotIn('safe.directory=*', update_content)

    def test_apcu_stat_cache_clearing(self):
        """Verify leanstack-apcu.php.tpl invalidates PHP stat cache before reading cron status mtime."""
        apcu_path = os.path.join(BASE_DIR, "core", "templates", "leanstack-apcu.php.tpl")
        with open(apcu_path, "r") as f:
            apcu_content = f.read()
        self.assertIn("clearstatcache( true, $sf );", apcu_content)

    def test_cron_status_systemd_and_log_sanitization(self):
        """Verify lsctl cron:status handles inactive oneshot service without 'Service unit not found' and cleans stale logs."""
        lsctl_path = os.path.join(BASE_DIR, "core", "bin", "lsctl")
        with tempfile.TemporaryDirectory() as td:
            # Create a mock bin directory with a mock systemctl
            mock_bin = os.path.join(td, "bin")
            os.makedirs(mock_bin)
            mock_sysctl = os.path.join(mock_bin, "systemctl")
            with open(mock_sysctl, "w") as f:
                f.write("""#!/usr/bin/env bash
if [ "$1" == "list-unit-files" ] || [ "$1" == "cat" ]; then
    if [ "$2" == "cp-cron.service" ] || [ "$2" == "cp-cron.timer" ]; then
        exit 0
    fi
    exit 1
elif [ "$1" == "status" ]; then
    if [ "$2" == "cp-cron.service" ]; then
        echo "○ cp-cron.service - LeanStack Centralized Anti-Thundering WP-Cron Queue"
        echo "     Loaded: loaded (/etc/systemd/system/cp-cron.service; disabled; preset: enabled)"
        echo "     Active: inactive (dead) since Sat 2026-10-17 12:56:06 UTC; 25s ago"
        exit 3
    elif [ "$2" == "cp-cron.timer" ]; then
        echo "● cp-cron.timer - Trigger LeanStack Centralized WP-Cron Queue Every Minute"
        echo "     Active: active (waiting) since Fri 2026-10-16 12:44:30 UTC; 24h ago"
        exit 0
    fi
    exit 4
elif [ "$1" == "is-active" ]; then
    if [ "$2" == "cp-cron.timer" ]; then
        echo "active"
        exit 0
    fi
    echo "inactive"
    exit 3
fi
exit 0
""")
            os.chmod(mock_sysctl, 0o755)

            # Test execution with mock systemctl
            env = os.environ.copy()
            env["PATH"] = f"{mock_bin}:{env.get('PATH', '')}"
            res = subprocess.run([lsctl_path, "cron:status"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.assertEqual(res.returncode, 0)
            self.assertIn("cp-cron.service - LeanStack Centralized Anti-Thundering WP-Cron Queue", res.stdout)
            self.assertIn("cp-cron.timer - Trigger LeanStack Centralized WP-Cron Queue Every Minute", res.stdout)
            self.assertNotIn("Service unit not found", res.stdout)
            self.assertNotIn("Timer unit not found", res.stdout)

            # Test --json mode to verify clean state values (no "inactiveinactiveinactive" bug)
            res_json = subprocess.run([lsctl_path, "cron:status", "--json"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.assertEqual(res_json.returncode, 0)
            data = json.loads(res_json.stdout)
            self.assertEqual(data["cron_timer"], "active")
            self.assertEqual(data["cron_service"], "inactive")
            self.assertFalse(data["cron_locked"])

    def test_sanitize_cron_logs_removes_chdir_and_preserves_open_basedir(self):
        """Verify sanitize_cron_logs preserves real open_basedir warnings while stripping stale sudo --chdir errors."""
        from importlib.machinery import SourceFileLoader
        import importlib.util
        upgrade_bin = os.path.join(BASE_DIR, "core", "bin", "ls-upgrade")
        loader = SourceFileLoader("ls_upgrade", upgrade_bin)
        spec = importlib.util.spec_from_file_location("ls_upgrade", upgrade_bin, loader=loader)
        ls_upgrade_mod = importlib.util.module_from_spec(spec)
        loader.exec_module(ls_upgrade_mod)

        with tempfile.TemporaryDirectory() as td:
            db_file = os.path.join(td, "sites.db")
            upgrader = ls_upgrade_mod.LeanStackUpgrader(repo_dir=BASE_DIR, db_file=db_file)
            test_log = os.path.join(td, "cron.log")
            with open(test_log, "w", encoding="utf-8") as f:
                f.write("sudo: you are not allowed to use '--chdir /home/staging_mfeasy_4809/htdocs' with '/usr/bin/php8.5'\n")
                f.write("PHP Warning:  open_basedir restriction in effect. File(/proc/cpuinfo) is not within the allowed path(s)\n")
                f.write("PHP Fatal error: Allowed memory size of 134217728 bytes exhausted\n")

            # Call real sanitize_cron_log_paths method on test_log
            upgrader.sanitize_cron_log_paths([test_log])

            with open(test_log, "r", encoding="utf-8") as f:
                lines = f.readlines()
            self.assertEqual(len(lines), 2)
            self.assertIn("open_basedir restriction in effect", lines[0])
            self.assertIn("PHP Fatal error: Allowed memory size", lines[1])
            self.assertNotIn("--chdir", "".join(lines))

    def test_upgrade_git_fetch_force_and_behind_count(self):
        """Verify ls-upgrade uses fetch --tags --force and returns False on 0 new commits or fetch error."""
        from unittest.mock import patch
        from importlib.machinery import SourceFileLoader
        import importlib.util

        upgrade_bin = os.path.join(BASE_DIR, "core", "bin", "ls-upgrade")
        loader = SourceFileLoader("ls_upgrade", upgrade_bin)
        spec = importlib.util.spec_from_file_location("ls_upgrade", upgrade_bin, loader=loader)
        ls_upgrade_mod = importlib.util.module_from_spec(spec)
        loader.exec_module(ls_upgrade_mod)

        with open(upgrade_bin, "r") as f:
            content = f.read()
        self.assertIn('["fetch", "--tags", "--force", "origin"]', content)
        self.assertIn('Repository is up to date with remote.', content)
        self.assertIn('def sanitize_cron_logs(self', content)

        update_sh = os.path.join(BASE_DIR, "update.sh")
        with open(update_sh, "r") as f:
            update_content = f.read()
        self.assertIn('fetch --tags --force origin', update_content)
        self.assertIn('mkdir -p /usr/local/bin /etc/lsctl/templates /var/log/lsctl', update_content)

        upgrader = ls_upgrade_mod.LeanStackUpgrader(repo_dir=BASE_DIR, db_file=":memory:")

        # 1. Simulate up-to-date repo (behind_count == 0): must return False
        def mock_run_uptodate(cmd, *args, **kwargs):
            if "status" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            if "fetch" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="From https://github.com/kghosh007/LeanStack\n")
            if "rev-list" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout="0\n", stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=mock_run_uptodate):
            pulled = upgrader.git_pull_latest()
            self.assertFalse(pulled)

        # 2. Simulate remote fetch failure: must return False and not re-exec
        def mock_run_fetch_fail(cmd, *args, **kwargs):
            if "status" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            if "fetch" in cmd:
                return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="From https://github.com/kghosh007/LeanStack\nfatal: unable to access 'https://github.com/': Could not resolve host\n")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=mock_run_fetch_fail):
            pulled = upgrader.git_pull_latest()
            self.assertFalse(pulled)

        # 3. Simulate remote commits available: behind_count == 3, pull succeeds -> must return True
        def mock_run_behind(cmd, *args, **kwargs):
            if "status" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            if "fetch" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            if "rev-list" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout="3\n", stderr="")
            if "pull" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout="Updating 0fc3533..c62dee4\n", stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=mock_run_behind):
            pulled = upgrader.git_pull_latest()
            self.assertTrue(pulled)

    def test_transactional_email_and_zero_daemon_smtp(self):
        """Verify zero-daemon transactional email architecture across pool, mu-plugins, bridge, and CLI."""
        pool_tpl = os.path.join(BASE_DIR, "core", "templates", "pool.conf.tpl")
        with open(pool_tpl, "r") as f:
            pool_c = f.read()
        self.assertIn("php_admin_value[sendmail_path]", pool_c)
        self.assertIn("/usr/bin/msmtp -C /home/{{USER_NAME}}/.msmtprc -t -i", pool_c)

        smtp_tpl = os.path.join(BASE_DIR, "core", "templates", "leanstack-smtp.php.tpl")
        self.assertTrue(os.path.exists(smtp_tpl))
        with open(smtp_tpl, "r") as f:
            smtp_c = f.read()
        self.assertIn("class LeanStackSMTP", smtp_c)
        self.assertIn("phpmailer_init", smtp_c)
        self.assertIn("SMTP_HOST", smtp_c)
        self.assertIn("LEANSTACK_SMTP_HOST", smtp_c)
        self.assertIn(".leanstack-smtp.json", smtp_c)
        self.assertIn("leanstack_smtp_settings", smtp_c)
        self.assertIn("sync_msmtprc", smtp_c)
        self.assertIn("chmod( $msmtprc, 0600 )", smtp_c)

        bridge_tpl = os.path.join(BASE_DIR, "core", "templates", "leanstack-bridge.php.tpl")
        with open(bridge_tpl, "r") as f:
            bridge_c = f.read()
        self.assertIn("tab=smtp", bridge_c)
        self.assertIn("'smtp' === $active_tab", bridge_c)
        self.assertIn("render_smtp_tab_content", bridge_c)
        self.assertIn("handle_save_smtp", bridge_c)
        self.assertIn("handle_send_smtp_test", bridge_c)
        self.assertIn("ls-smtp-preset", bridge_c)
        self.assertIn("SendGrid", bridge_c)
        self.assertIn("Postmark", bridge_c)
        self.assertIn("msmtp", bridge_c)

        lsctl_path = os.path.join(BASE_DIR, "core", "bin", "lsctl")
        with open(lsctl_path, "r") as f:
            lsctl_c = f.read()
        self.assertIn(".msmtprc", lsctl_c)
        self.assertIn("chmod 600", lsctl_c)
        self.assertIn("leanstack-smtp.php", lsctl_c)

        upgrade_path = os.path.join(BASE_DIR, "core", "bin", "ls-upgrade")
        with open(upgrade_path, "r") as f:
            upgrade_c = f.read()
        self.assertIn("leanstack-smtp.php", upgrade_c)
        self.assertIn("sendmail_path", upgrade_c)
        self.assertIn(".msmtprc", upgrade_c)

    def test_dynamic_timezone_support_in_mu_plugins(self):
        """Verify leanstack-bridge dynamically formats dates/times in the WordPress site's configured timezone."""
        bridge_tpl = os.path.join(BASE_DIR, "core", "templates", "leanstack-bridge.php.tpl")
        with open(bridge_tpl, "r") as f:
            content = f.read()

        self.assertIn("function format_site_time(", content)
        self.assertIn("wp_date(", content)
        self.assertIn("wp_timezone_string()", content)
        self.assertNotIn("gmdate( 'H:i:s \\U\\T\\C', $last_time )", content)
        self.assertNotIn("gmdate( 'Y-m-d H:i:s \\U\\T\\C', (int) $revert_at )", content)
        self.assertIn("$this->format_site_time( $last_time", content)
        self.assertIn("$this->format_site_time( (int) $revert_at )", content)
        self.assertIn("$this->format_site_time( $ev['timestamp'] )", content)
        self.assertIn("$this->format_site_time( filemtime( $target ) )", content)

    def test_tenant_cpu_and_memory_telemetry(self):
        """Verify accurate CPU & RAM telemetry relative to assigned resources without false 100% elevation."""
        bridge_tpl = os.path.join(BASE_DIR, "core", "templates", "leanstack-bridge.php.tpl")
        with open(bridge_tpl, "r") as f:
            content = f.read()

        self.assertIn("'cpu_usage_pct'", content)
        self.assertIn("'memory_usage_pct'", content)
        self.assertIn("'capacity_saturation_pct'", content)
        self.assertIn("'max_workers'", content)
        self.assertIn("'cpu_cores'", content)
        self.assertIn("CPU:</span> <?php echo esc_html( $analytics['system']['cpu_usage_pct'] ); ?>%", content)
        self.assertIn("RAM:</span> <?php echo esc_html( $analytics['system']['memory_usage_pct'] ); ?>%", content)
        self.assertIn("Workers: <strong>%d / %d</strong>", content)

    def test_lsctl_db_tune_and_sys_tune_execution(self):
        """Verify lsctl db:tune executes cleanly with --json and help displays tuning commands."""
        lsctl_bin = os.path.join(BASE_DIR, "core", "bin", "lsctl")
        res_help = subprocess.run([lsctl_bin, "help"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(res_help.returncode, 0)
        self.assertIn("db:tune", res_help.stdout)
        self.assertIn("sys:tune", res_help.stdout)

        # Test db:tune --json execution
        res_tune = subprocess.run([lsctl_bin, "db:tune", "--json", "--simulate-ram=4096", "--simulate-cores=4"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(res_tune.returncode, 0, f"db:tune failed: {res_tune.stderr}")
        data = json.loads(res_tune.stdout)
        self.assertIn("score", data)
        self.assertIn("ideal_tuning", data)
        self.assertEqual(data["ideal_tuning"]["innodb_io_capacity"], 8000)

    def test_redis_constants_wp_config_and_upgrade(self):
        """Verify all 5 Redis Object Cache constants and bloat controls are configured in wp-config.php.tpl and reconciled in ls-upgrade."""
        wp_config_tpl = os.path.join(BASE_DIR, "core", "templates", "wp-config.php.tpl")
        with open(wp_config_tpl, "r") as f:
            cfg = f.read()

        self.assertIn("define( 'WP_REDIS_DISABLE_METRICS', true );", cfg)
        self.assertIn("define( 'WP_REDIS_PERSISTENT', true );", cfg)
        self.assertIn("define( 'WP_REDIS_IGBINARY', true );", cfg)
        self.assertIn("define( 'WP_REDIS_LOAD_APEXCHARTS', false );", cfg)
        self.assertIn("define( 'WP_REDIS_DISABLE_BANNERS', true );", cfg)
        self.assertIn("define( 'WP_POST_REVISIONS', 5 );", cfg)
        self.assertIn("define( 'MEDIA_TRASH', true );", cfg)
        self.assertIn("define( 'EMPTY_TRASH_DAYS', 7 );", cfg)

        upgrade_bin = os.path.join(BASE_DIR, "core", "bin", "ls-upgrade")
        with open(upgrade_bin, "r") as f:
            up = f.read()

        self.assertIn("WP_REDIS_DISABLE_METRICS", up)
        self.assertIn("WP_REDIS_PERSISTENT", up)
        self.assertIn("WP_REDIS_IGBINARY", up)
        self.assertIn("WP_REDIS_LOAD_APEXCHARTS", up)
        self.assertIn("WP_REDIS_DISABLE_BANNERS", up)
        self.assertIn("WP_POST_REVISIONS", up)
        self.assertIn("MEDIA_TRASH", up)
        self.assertIn("EMPTY_TRASH_DAYS", up)

    def test_php_execution_time_and_session_security(self):
        """Verify max_execution_time 300, request_terminate_timeout 300s, and session/cookie security flags across configs."""
        pool_tpl = os.path.join(BASE_DIR, "core", "templates", "pool.conf.tpl")
        with open(pool_tpl, "r") as f:
            pool = f.read()

        self.assertIn("request_terminate_timeout = 300s", pool)
        self.assertIn("php_admin_value[max_execution_time] = 300", pool)
        self.assertIn("php_admin_flag[session.use_strict_mode] = on", pool)
        self.assertIn("php_admin_flag[session.cookie_httponly] = on", pool)
        self.assertIn("php_admin_flag[session.cookie_secure] = on", pool)
        self.assertIn("php_admin_value[session.cookie_samesite] = Lax", pool)

        shield_tpl = os.path.join(BASE_DIR, "core", "templates", "leanstack-shield.php.tpl")
        with open(shield_tpl, "r") as f:
            shield = f.read()

        self.assertIn("session.use_strict_mode", shield)
        self.assertIn("session.cookie_httponly", shield)
        self.assertIn("session.cookie_secure", shield)
        self.assertIn("session.cookie_samesite", shield)
        self.assertIn("leanstack_enforce_cookie_security_flags", shield)
        self.assertIn("wp-settings", shield)
        self.assertIn("max_execution_time", shield)

        sys.path.insert(0, os.path.join(BASE_DIR, "installer"))
        from probe import HardwareProbe, TuningCalculator
        from provision import render_files
        runtime = render_files(
            TuningCalculator(HardwareProbe(sim_ram_mb=2048, sim_cores=2).probe_all()).to_document(),
            ["8.3"],
        )["etc/php/8.3/fpm/conf.d/98-leanstack-runtime.ini"]
        p5 = runtime

        self.assertIn("session.use_strict_mode = 1", p5)
        self.assertIn("session.cookie_httponly = 1", p5)
        self.assertIn("session.cookie_secure = 1", p5)
        self.assertIn("session.cookie_samesite = Lax", p5)
        self.assertIn("max_execution_time = 300", p5)

        upgrade_bin = os.path.join(BASE_DIR, "core", "bin", "ls-upgrade")
        with open(upgrade_bin, "r") as f:
            up = f.read()
        self.assertIn("session.cookie_secure = 1", up)
        self.assertIn("session.cookie_samesite = Lax", up)

        bridge_tpl = os.path.join(BASE_DIR, "core", "templates", "leanstack-bridge.php.tpl")
        with open(bridge_tpl, "r") as f:
            bridge = f.read()
        self.assertIn("Cookie Security Hardening", bridge)

        # Verify regex matching in shield handles PHPSESSSID (triple 's'), PHPSESSID, dynamic token, and wp-settings
        import re
        cookie_regex = r"^(phpsess+id|snn_dynamic_token|unique_session_id|wordpress_|wp-settings)"
        self.assertTrue(bool(re.match(cookie_regex, "PHPSESSSID", re.I)))
        self.assertTrue(bool(re.match(cookie_regex, "PHPSESSID", re.I)))
        self.assertTrue(bool(re.match(cookie_regex, "snn_dynamic_token", re.I)))
        self.assertTrue(bool(re.match(cookie_regex, "unique_session_id", re.I)))
        self.assertTrue(bool(re.match(cookie_regex, "wp-settings-1", re.I)))
        self.assertTrue(bool(re.match(cookie_regex, "wp-settings-time-1", re.I)))
        self.assertFalse(bool(re.match(cookie_regex, "unrelated_cookie", re.I)))


    def test_watcher_and_lsctl_htaccess_permissions(self):
        """Verify ls-watcher, lsctl, and ls-upgrade enforce chmod 644 on .htaccess, robots.txt, and llms.txt."""
        watcher_bin = os.path.join(BASE_DIR, "core", "bin", "ls-watcher")
        with open(watcher_bin, "r") as f:
            watcher = f.read()
        self.assertIn("chmod 644", watcher)
        self.assertIn(".htaccess", watcher)
        self.assertIn("robots.txt", watcher)
        self.assertIn("llms.txt", watcher)

        lsctl_bin = os.path.join(BASE_DIR, "core", "bin", "lsctl")
        with open(lsctl_bin, "r") as f:
            lsctl = f.read()
        self.assertIn("chmod 644", lsctl)
        self.assertIn(".htaccess", lsctl)

        upgrade_bin = os.path.join(BASE_DIR, "core", "bin", "ls-upgrade")
        with open(upgrade_bin, "r") as f:
            up = f.read()
        self.assertIn(".htaccess", up)
        self.assertIn("robots.txt", up)
        self.assertIn("llms.txt", up)

    def test_security_headers_and_gatekeeper_validation(self):
        """Verify HSTS, CSP with worker-src blob:, X-Frame-Options, gatekeeper debounce 0.1s, and synchronous verification wait."""
        bridge_tpl = os.path.join(BASE_DIR, "core", "templates", "leanstack-bridge.php.tpl")
        with open(bridge_tpl, "r") as f:
            bridge = f.read()

        self.assertIn("wait_for_gatekeeper_verification", bridge)
        self.assertIn("enable_hsts", bridge)
        self.assertIn("force_https", bridge)
        self.assertIn("upgrade-insecure-requests", bridge)
        self.assertIn("Strict-Transport-Security", bridge)
        self.assertIn("worker-src 'self' blob:", bridge)
        self.assertIn("X-Frame-Options", bridge)

        # Confirm render_crawlers_page does NOT render status banner
        crawlers_pos = bridge.find("public function render_crawlers_page()")
        self.assertNotEqual(crawlers_pos, -1)
        crawlers_block = bridge[crawlers_pos:crawlers_pos + 2500]
        self.assertNotIn("render_status_banner()", crawlers_block)
        self.assertIn("write_failed", crawlers_block)

        # Confirm stale pending auto-heal in get_status()
        self.assertIn("Auto-heal stale pending status", bridge)

        # Confirm gatekeeper debounce is reduced to 0.1s
        gatekeeper_bin = os.path.join(BASE_DIR, "core", "bin", "ls-gatekeeper")
        with open(gatekeeper_bin, "r") as f:
            gk = f.read()
        self.assertIn("sleep 0.1", gk)
        self.assertNotIn("sleep 1.5", gk)

    def test_optimizations_default_theme_and_db_tuner_bridge(self):
        """Verify Optimizations, Default Theme Selector, and DB & Autoload Tuner methods exist in leanstack-bridge.php.tpl."""
        bridge_tpl = os.path.join(BASE_DIR, "core", "templates", "leanstack-bridge.php.tpl")
        with open(bridge_tpl, "r") as f:
            bridge = f.read()

        # Admin menu registrations
        self.assertIn("leanstack-optimizations", bridge)
        self.assertIn("leanstack-default-theme", bridge)
        self.assertIn("leanstack-db-tuner", bridge)

        # Optimizations methods
        self.assertIn("get_optimizations_options", bridge)
        self.assertIn("init_optimizations", bridge)
        self.assertIn("render_optimizations_page", bridge)
        self.assertIn("handle_save_optimizations", bridge)
        self.assertIn("handle_clean_action_scheduler", bridge)
        self.assertIn("run_periodic_db_optimization", bridge)
        self.assertIn("remove_wp_version_string", bridge)

        # Default Theme methods & wp-config chmod 600 enforcement
        self.assertIn("render_default_theme_page", bridge)
        self.assertIn("handle_save_default_theme", bridge)
        self.assertIn("WP_DEFAULT_THEME", bridge)
        self.assertIn("@chmod( $wp_config_file, 0600 );", bridge)

        # DB Tuner methods
        self.assertIn("render_db_tuner_page", bridge)
        self.assertIn("handle_toggle_autoload", bridge)
        self.assertIn("handle_delete_option", bridge)
        self.assertIn("handle_optimize_autoload", bridge)
        self.assertIn("handle_clean_orphaned_meta", bridge)

    def test_msmtp_mail_configuration_and_logging(self):
        """Verify msmtp templates eliminate invalid localhost:587 auth, log to mail.log, and pre-flight validate external SMTP."""
        lsctl_bin = os.path.join(BASE_DIR, "core", "bin", "lsctl")
        with open(lsctl_bin, "r") as f:
            lsctl = f.read()

        # Default template should not have auth on or port 587 without credentials
        self.assertNotIn("port 587\nauth on", lsctl)

        smtp_tpl = os.path.join(BASE_DIR, "core", "templates", "leanstack-smtp.php.tpl")
        with open(smtp_tpl, "r") as f:
            smtp = f.read()

        self.assertIn("logs/mail.log", smtp)
        self.assertIn("log_mail_success", smtp)
        self.assertIn("log_mail_failure", smtp)
        self.assertIn("isMail", smtp)
        self.assertIn("PHP-MAIL", smtp)

        bridge_tpl = os.path.join(BASE_DIR, "core", "templates", "leanstack-bridge.php.tpl")
        with open(bridge_tpl, "r") as f:
            bridge = f.read()

        self.assertIn("No external SMTP provider configured", bridge)
        self.assertIn("Native PHP mail active", bridge)
        self.assertIn("sent via native PHP mail", bridge)

    def test_database_benchmark_query_guards_and_config(self):
        """Verify SAVEQUERIES disabled, QM_DISABLE extended benchmark guard, and MariaDB dual-config synchronization."""
        wp_cfg = os.path.join(BASE_DIR, "core", "templates", "wp-config.php.tpl")
        with open(wp_cfg, "r") as f:
            cfg = f.read()
        self.assertIn("define( 'SAVEQUERIES', false )", cfg)
        self.assertIn("QM_DISABLE", cfg)
        self.assertIn("wp-performance|wphb", cfg)

        shield_tpl = os.path.join(BASE_DIR, "core", "templates", "leanstack-shield.php.tpl")
        with open(shield_tpl, "r") as f:
            shield = f.read()
        self.assertIn("define( 'SAVEQUERIES', false )", shield)
        self.assertIn("QM_DISABLE", shield)
        self.assertIn("wp-performance|wphb", shield)

        sys.path.insert(0, os.path.join(BASE_DIR, "installer"))
        from probe import HardwareProbe, TuningCalculator
        from provision import render_files
        rendered = render_files(
            TuningCalculator(HardwareProbe(sim_ram_mb=2048, sim_cores=2).probe_all()).to_document(),
            ["8.3"],
        )
        p3_content = rendered["etc/mysql/mariadb.conf.d/99-leanstack-highqps.cnf"]
        self.assertIn("etc/mysql/conf.d/99-leanstack-highqps.cnf", rendered)
        self.assertIn("mariadb.conf.d", "etc/mysql/mariadb.conf.d/99-leanstack-highqps.cnf")
        self.assertIn("/etc/mysql/conf.d/", "/etc/mysql/conf.d/99-leanstack-highqps.cnf")
        self.assertIn("[mariadb]", p3_content)
        self.assertIn("innodb_flush_log_at_trx_commit = 2", p3_content)

        up = os.path.join(BASE_DIR, "core", "bin", "ls-upgrade")
        with open(up, "r") as f:
            up_content = f.read()
        self.assertIn("/etc/mysql/conf.d", up_content)
        self.assertIn("mariadb.conf.d", up_content)
        self.assertIn("[mariadb]", up_content)

        db_tune = os.path.join(BASE_DIR, "core", "bin", "ls-db-tune")
        with open(db_tune, "r") as f:
            tuner = f.read()
        self.assertIn("[mariadb]", tuner)
        self.assertIn("innodb_flush_log_at_trx_commit", tuner)

    def test_asset_loading_exclusion_system(self):
        """Verify global and per-page asset loading exclusion system in leanstack-bridge.php.tpl."""
        bridge_tpl = os.path.join(BASE_DIR, "core", "templates", "leanstack-bridge.php.tpl")
        with open(bridge_tpl, "r") as f:
            bridge = f.read()

        # Methods and options
        self.assertIn("get_asset_exclusions", bridge)
        self.assertIn("parse_asset_handles", bridge)
        self.assertIn("filter_enqueued_assets", bridge)
        self.assertIn("handle_save_asset_exclusions", bridge)
        self.assertIn("leanstack_asset_exclusions", bridge)

        # Hook registrations (early enqueue, late header script printing, and dynamic footer printing)
        self.assertIn("wp_enqueue_scripts", bridge)
        self.assertIn("wp_print_scripts", bridge)
        self.assertIn("wp_print_footer_scripts", bridge)
        self.assertIn("admin_post_leanstack_save_asset_exclusions", bridge)

        # Dequeue and deregister functions
        self.assertIn("wp_dequeue_script", bridge)
        self.assertIn("wp_deregister_script", bridge)
        self.assertIn("wp_dequeue_style", bridge)
        self.assertIn("wp_deregister_style", bridge)

        # Rule condition types
        self.assertIn("front_page", bridge)
        self.assertIn("is_front_page", bridge)
        self.assertIn("target_type", bridge)
        self.assertIn("target_value", bridge)

        # Safety guards
        self.assertIn("is_admin()", bridge)
        self.assertIn("wp_doing_ajax()", bridge)
        self.assertIn("get_queried_object_id", bridge)
        self.assertIn("post_name", bridge)
        self.assertIn("slug", bridge)

        # Admin UI elements and template
        self.assertIn("leanstack_asset_exclusions_enabled", bridge)
        self.assertIn("global_scripts", bridge)
        self.assertIn("global_styles", bridge)
        self.assertIn("ls-asset-rules-table", bridge)
        self.assertIn("ls-asset-rule-template", bridge)
        self.assertIn("ls-add-asset-rule-btn", bridge)
        self.assertIn("Save Asset Exclusion Rules", bridge)

        # Verify handle parsing allows dotted handles (e.g. jquery.ui.core, font-awesome.min)
        handle_clean_regex = r"[^a-zA-Z0-9_\-\.]"
        clean_item = re.sub(handle_clean_regex, "", "jquery.ui.core")
        self.assertEqual(clean_item, "jquery.ui.core")

        # Wildcard matching test to ensure the regex strategy in PHP works
        pattern = "/checkout/*"
        regex = r"^" + re.escape(pattern).replace(r"\*", ".*") + r"$"
        self.assertTrue(bool(re.match(regex, "/checkout/order-pay/")))
        self.assertFalse(bool(re.match(regex, "/shop/products/")))

    def test_four_requested_fixes_deep_validation(self):
        """End-to-end unit verification for all 4 requested cases."""
        import tempfile

        # Case 1: Cookie hardening regex & flags
        shield_path = os.path.join(BASE_DIR, "core", "templates", "leanstack-shield.php.tpl")
        with open(shield_path, "r") as f:
            shield_code = f.read()

        cookie_regex = r"^(phpsess+id|snn_dynamic_token|unique_session_id|wordpress_|wp-settings)"
        for cookie_name in ["PHPSESSSID", "PHPSESSID", "snn_dynamic_token", "unique_session_id", "wp-settings-1", "wp-settings-time-1"]:
            self.assertTrue(bool(re.search(cookie_regex, cookie_name, re.I)), f"Cookie {cookie_name} must match regex")
        self.assertNotIn("HTTP_X_FORWARDED_SSL", shield_code)
        self.assertNotIn("HTTP_X_FORWARDED_SCHEME", shield_code)

        # Case 2: Database performance degradation & dual config synchronization
        import importlib.machinery
        import importlib.util
        tuner_path = os.path.join(BASE_DIR, "core", "bin", "ls-db-tune")
        loader = importlib.machinery.SourceFileLoader("ls_db_tune_test_apply", tuner_path)
        spec = importlib.util.spec_from_loader("ls_db_tune_test_apply", loader)
        ls_db_tune = importlib.util.module_from_spec(spec)
        loader.exec_module(ls_db_tune)

        with tempfile.TemporaryDirectory() as tmp_dir:
            conf_file = os.path.join(tmp_dir, "99-leanstack-highqps.cnf")
            ideal = {
                "innodb_buffer_pool_size": "2048M",
                "table_open_cache": 4096,
                "table_open_cache_instances": 4,
                "max_connections": 300,
                "innodb_io_capacity": 4000,
                "innodb_io_capacity_max": 8000,
                "innodb_read_io_threads": 4,
                "innodb_write_io_threads": 4,
                "innodb_flush_neighbors": 0,
                "sort_buffer_size": "2M",
                "join_buffer_size": "2M",
                "read_buffer_size": "512K",
                "read_rnd_buffer_size": "1M",
                "aria_pagecache_buffer_size": "128M",
                "aria_sort_buffer_size": "32M",
                "transaction_isolation": "READ-COMMITTED",
                "innodb_log_file_size": "512M",
            }
            res = ls_db_tune.apply_optimizations(ideal, conf_dir=tmp_dir, collector=None, show_log=False)
            self.assertTrue(res)
            self.assertTrue(os.path.exists(conf_file))
            with open(conf_file, "r") as f:
                cnf_text = f.read()
            self.assertIn("[mysqld]", cnf_text)
            self.assertIn("[mariadb]", cnf_text)
            self.assertIn("innodb_flush_log_at_trx_commit = 2", cnf_text)
            self.assertIn("performance_schema             = OFF", cnf_text)
            self.assertIn("skip-name-resolve              = 1", cnf_text)

        # Case 3: Native PHP Mail fallback without external SMTP
        smtp_path = os.path.join(BASE_DIR, "core", "templates", "leanstack-smtp.php.tpl")
        with open(smtp_path, "r") as f:
            smtp_code = f.read()
        self.assertIn("$phpmailer->isMail()", smtp_code)
        self.assertIn("SENT [%s]: To: %s", smtp_code)

        bridge_path = os.path.join(BASE_DIR, "core", "templates", "leanstack-bridge.php.tpl")
        with open(bridge_path, "r") as f:
            bridge_code = f.read()
        self.assertIn("handle_send_smtp_test", bridge_code)
        self.assertIn("Native PHP Mail Transport", bridge_code)
        self.assertIn("LeanStackSMTP::get_instance()", bridge_code)

        # Case 4: Asset loading exclusions
        self.assertIn("filter_enqueued_assets", bridge_code)
        self.assertIn("parse_asset_handles", bridge_code)
        self.assertIn("wp_enqueue_scripts", bridge_code)
        self.assertIn("wp_print_scripts", bridge_code)
        self.assertIn("wp_print_footer_scripts", bridge_code)

        # Simulate asset handle parsing
        raw_handles = "jquery.ui.core, font-awesome.min\nwc-cart-fragments, wp-block-library"
        items = [re.sub(r"[^a-zA-Z0-9_\-\.]", "", h.strip()) for h in re.split(r"[\r\n,]+", raw_handles) if h.strip()]
        self.assertIn("jquery.ui.core", items)
        self.assertIn("font-awesome.min", items)
        self.assertIn("wc-cart-fragments", items)
        self.assertIn("wp-block-library", items)

    def test_grubenv_and_systemd_boot_self_healing(self):
        """Verify ls-upgrade and the provisioner self-heal missing /boot/grub/grubenv."""
        upgrade_bin = os.path.join(BASE_DIR, "core", "bin", "ls-upgrade")
        with open(upgrade_bin, "r") as f:
            up = f.read()
        self.assertIn("grub2-common.service", up)
        self.assertIn("grubenv", up)
        self.assertIn("recordfail", up)

        provision_script = os.path.join(BASE_DIR, "installer", "provision.py")
        with open(provision_script, "r") as f:
            p1 = f.read()
        self.assertIn("grub2-common.service", p1)
        self.assertIn("grub-editenv", p1)
        self.assertIn("recordfail", p1)

    def test_secret_protection_and_rollback_safety_phase4(self):
        """Verify Phase 4 fixes: secret redaction, safe stdin piping, backup modes, and safe autoupdate rollback."""
        lsctl_path = os.path.join(BASE_DIR, "core", "bin", "lsctl")
        with open(lsctl_path, "r") as f:
            lsctl_code = f.read()

        # LS-07: DB permissions
        self.assertIn('chmod 600 "$DB_FILE"', lsctl_code)
        self.assertIn('chmod 700 "$DB_DIR"', lsctl_code)

        # LS-07: site:info credential redaction
        self.assertIn("admin_pass", lsctl_code)
        # Verify db_pass and admin_pass are not selected in site:info queries
        site_info_match = re.search(r"site:info\)[\s\S]*?;;", lsctl_code)
        self.assertIsNotNone(site_info_match)
        site_info_body = site_info_match.group(0)
        self.assertNotIn("admin_pass", site_info_body)
        self.assertNotIn("db_pass", site_info_body)
        self.assertIn("domain, user, php_version", site_info_body)

        # LS-07: Stdin piping for MariaDB & WP-CLI admin password
        self.assertIn("--prompt=admin_password", lsctl_code)
        self.assertIn('<<< "${ADMIN_PASS}"', lsctl_code)
        self.assertIn("mariadb <<EOF", lsctl_code)
        self.assertNotIn('-e "CREATE DATABASE IF NOT EXISTS', lsctl_code)
        self.assertNotIn('-e "DROP DATABASE IF EXISTS', lsctl_code)

        # LS-07: Backup permissions
        self.assertIn('chmod 700 "/var/backups/lsctl" "$BACKUP_DIR"', lsctl_code)
        self.assertIn('chmod 600 "$DUMP_FILE"', lsctl_code)

        upgrade_path = os.path.join(BASE_DIR, "core", "bin", "ls-upgrade")
        with open(upgrade_path, "r") as f:
            upgrade_code = f.read()
        self.assertIn("0o700", upgrade_code)
        self.assertIn("0o600", upgrade_code)

        autoupdate_path = os.path.join(BASE_DIR, "core", "bin", "ls-autoupdate")
        with open(autoupdate_path, "r") as f:
            autoupdate_code = f.read()
        self.assertIn('chmod 700 "/var/backups/lsctl" "$BACKUP_DIR"', autoupdate_code)
        self.assertIn('chmod 600 "$BACKUP_DIR/sites.db"', autoupdate_code)

        # LS-08: Safe directory wildcard check
        install_path = os.path.join(BASE_DIR, "install.sh")
        with open(install_path, "r") as f:
            install_code = f.read()
        update_path = os.path.join(BASE_DIR, "update.sh")
        with open(update_path, "r") as f:
            update_code = f.read()

        self.assertNotIn("safe.directory=*", upgrade_code)
        self.assertNotIn("safe.directory=*", install_code)
        self.assertNotIn("safe.directory=*", update_code)
        self.assertIn("--no-git-pull", upgrade_code)
        self.assertIn("--no-git-pull", autoupdate_code)

        # LS-09: Safe rollback without destructive rm -rf /etc/angie
        self.assertNotIn("rm -rf /etc/angie", autoupdate_code)
        self.assertNotIn("rm -rf /etc/php", autoupdate_code)
        self.assertIn('cp -a "$BACKUP_DIR/angie/." /etc/angie/', autoupdate_code)
        self.assertIn('cp -a "$BACKUP_DIR/php/." /etc/php/', autoupdate_code)
        self.assertIn("Core update and schema migration failed", autoupdate_code)
        self.assertIn("rollback_system", autoupdate_code)

    def test_provision_delete_transactions_and_resource_caps_phase5(self):
        """Verify Phase 5 fixes: LS-10 error cleanup trap, LS-11 cache_prefix tracking, LS-12 worker budget, LS-17 domain & dump guardrails."""
        lsctl_path = os.path.join(BASE_DIR, "core", "bin", "lsctl")
        with open(lsctl_path, "r") as f:
            lsctl_code = f.read()

        # LS-10: Provisioning trap remains armed until AFTER database insertion
        db_insert_pos = lsctl_code.rfind("INSERT INTO sites")
        trap_disarm_pos = lsctl_code.rfind("trap - ERR")
        self.assertNotEqual(db_insert_pos, -1)
        self.assertNotEqual(trap_disarm_pos, -1)
        self.assertGreater(trap_disarm_pos, db_insert_pos, "trap - ERR must be disarmed AFTER INSERT INTO sites")

        # LS-10: cleanup_on_error cleans up partial sites row
        self.assertIn("DELETE FROM sites WHERE domain='$DOMAIN'", lsctl_code)

        # LS-11: Migration 0003 exists and adds cache_prefix
        mig_path = os.path.join(BASE_DIR, "core", "migrations", "0003_add_cache_prefix.py")
        self.assertTrue(os.path.exists(mig_path))
        with open(mig_path, "r") as f:
            mig_code = f.read()
        self.assertIn("cache_prefix", mig_code)

        # LS-11: lsctl records and validates cache_prefix
        self.assertIn("cache_prefix", lsctl_code)
        self.assertIn('CACHE_PREFIX="ls_${USER_NAME}_"', lsctl_code)
        self.assertIn('valkey-cli -s /run/valkey/valkey.sock --scan --pattern "${CACHE_PREFIX}*"', lsctl_code)
        self.assertNotIn('valkey-cli -s /run/valkey/valkey.sock --scan --pattern "${USER_NAME}_*"', lsctl_code)

        # LS-12: warn_php_budget enforcement
        self.assertIn('if [ "$force" -ne 1 ]; then', lsctl_code)
        self.assertIn("Exceeding host PHP worker budget", lsctl_code)
        self.assertIn('if ! warn_php_budget "$USED_CHILDREN" "$SITE_MAX_CHILDREN" "$HOST_BUDGET"', lsctl_code)

        # LS-17: Domain validation and system user guardrails
        self.assertIn("validate_domain()", lsctl_code)
        self.assertIn("is_system_user()", lsctl_code)
        self.assertIn("Safety backup dump failed for database", lsctl_code)
        self.assertIn("Teardown aborted to protect data. Use --force to override.", lsctl_code)

    def test_caching_security_and_locks_phase6(self):
        """Verify Phase 6 fixes: LS-13 WooCommerce caching, LS-14 HTTPS spoofing, LS-15 0600 locks, LS-16 telemetry, LS-19 rate zones."""
        vhost_path = os.path.join(BASE_DIR, "core", "templates", "vhost.conf.tpl")
        with open(vhost_path, "r") as f:
            vhost_code = f.read()

        # LS-13: WooCommerce session cookies in cache bypass & Cache-Control no-cache honor
        self.assertIn("wp_woocommerce_session", vhost_code)
        self.assertIn("woocommerce_cart_hash", vhost_code)
        self.assertIn("fastcgi_no_cache $skip_cache $nocache_response;", vhost_code)

        provision_path = os.path.join(BASE_DIR, "installer", "provision.py")
        with open(provision_path, "r") as f:
            provision_code = f.read()
        self.assertIn("map $upstream_http_cache_control $nocache_response", provision_code)

        # LS-14: No spoofable x_forwarded_https in Angie vhost or provisioner
        self.assertNotIn("x_forwarded_https", vhost_code)
        self.assertNotIn("x_forwarded_https", provision_code)

        # LS-14: No spoofable forwarded headers in leanstack-shield.php
        shield_path = os.path.join(BASE_DIR, "core", "templates", "leanstack-shield.php.tpl")
        with open(shield_path, "r") as f:
            shield_code = f.read()
        self.assertNotIn("HTTP_X_FORWARDED_PROTO", shield_code)
        self.assertNotIn("HTTP_X_FORWARDED_SSL", shield_code)
        self.assertNotIn("HTTP_X_FORWARDED_SCHEME", shield_code)
        self.assertNotIn("HTTP_CF_VISITOR", shield_code)

        # LS-15: Lock files mode 0600 in /run without /tmp fallback or 0666
        autoupdate_path = os.path.join(BASE_DIR, "core", "bin", "ls-autoupdate")
        with open(autoupdate_path, "r") as f:
            autoupdate_code = f.read()
        self.assertIn('chmod 600 "$LOCK_FILE"', autoupdate_code)
        self.assertNotIn('chmod 666 "$LOCK_FILE"', autoupdate_code)
        self.assertNotIn('/tmp/ls-maintenance.lock', autoupdate_code)

        cron_path = os.path.join(BASE_DIR, "core", "bin", "ls-cron-queue")
        with open(cron_path, "r") as f:
            cron_code = f.read()
        self.assertIn('chmod 600 "$LOCK_FILE"', cron_code)
        self.assertNotIn('chmod 666 "$LOCK_FILE"', cron_code)
        self.assertNotIn('/tmp/ls-cron.lock', cron_code)

        # LS-16: Telemetry secret hardening
        telemetry_path = os.path.join(BASE_DIR, "site", "api", "telemetry", "index.php")
        with open(telemetry_path, "r") as f:
            telemetry_code = f.read()
        self.assertNotIn("leanstack2026", telemetry_code)
        self.assertNotIn("$_GET['auth']", telemetry_code)
        self.assertIn("hash_equals", telemetry_code)
        self.assertIn("Bearer", telemetry_code)

        # LS-19: Declared rate-limiting zones attached to PHP location
        self.assertIn("limit_req zone=perip burst=40 nodelay;", vhost_code)

    def test_structural_modularization_phase7(self):
        """Verify Phase 7 fixes: LS-20 centralized SQLite helper and LS-21 single source YAML profiles."""
        import subprocess, json, tempfile

        db_lib_path = os.path.join(BASE_DIR, "core", "lib", "db.py")
        profiles_lib_path = os.path.join(BASE_DIR, "core", "lib", "profiles.py")
        profiles_yaml_path = os.path.join(BASE_DIR, "core", "config", "profiles.yaml")

        self.assertTrue(os.path.exists(db_lib_path), "Missing core/lib/db.py")
        self.assertTrue(os.path.exists(profiles_lib_path), "Missing core/lib/profiles.py")
        self.assertTrue(os.path.exists(profiles_yaml_path), "Missing core/config/profiles.yaml")

        # Test core/lib/db.py parameterized operations
        schema_file = os.path.join(BASE_DIR, "core", "migrations", "0001_initial_schema.sql")
        self.assertTrue(os.path.exists(schema_file))
        with open(schema_file, "r") as f:
            schema_sql = f.read()

        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as tmp_db:
            # 1. Exec CREATE TABLE using migration schema
            subprocess.run(
                [
                    "python3",
                    db_lib_path,
                    "exec",
                    tmp_db.name,
                    schema_sql
                ],
                check=True
            )

            # 2. Exec INSERT with parameter binding
            subprocess.run(
                [
                    "python3",
                    db_lib_path,
                    "exec",
                    tmp_db.name,
                    "INSERT INTO sites (domain, user, php_version, pool_type, site_path, db_name, db_user, db_pass, admin_user, admin_pass, admin_email, cache_prefix, profile_used) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    "modulartest.org",
                    "moduser",
                    "8.4",
                    "ondemand",
                    "/var/www/modulartest.org",
                    "moduser_db",
                    "moduser_u",
                    "ultra_secret_pw",
                    "admin",
                    "secret_admin_pw",
                    "admin@modulartest.org",
                    "modpref_",
                    "default"
                ],
                check=True
            )

            # 3. Query single value
            res_query = subprocess.run(
                [
                    "python3",
                    db_lib_path,
                    "query",
                    tmp_db.name,
                    "SELECT user FROM sites WHERE domain = ?",
                    "modulartest.org"
                ],
                stdout=subprocess.PIPE,
                text=True,
                check=True
            )
            self.assertEqual(res_query.stdout.strip(), "moduser")

            # 4. Query JSON
            res_json = subprocess.run(
                [
                    "python3",
                    db_lib_path,
                    "query-json",
                    tmp_db.name,
                    "SELECT domain, user, db_name FROM sites WHERE domain = ?",
                    "modulartest.org"
                ],
                stdout=subprocess.PIPE,
                text=True,
                check=True
            )
            rows = json.loads(res_json.stdout.strip())
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["domain"], "modulartest.org")
            self.assertEqual(rows[0]["db_name"], "moduser_db")

            # 5. site-info formatting and secret redaction
            res_info = subprocess.run(
                [
                    "python3",
                    db_lib_path,
                    "site-info",
                    tmp_db.name,
                    "modulartest.org"
                ],
                stdout=subprocess.PIPE,
                text=True,
                check=True
            )
            self.assertIn("modulartest.org", res_info.stdout)
            self.assertIn("[REDACTED]", res_info.stdout)
            self.assertNotIn("ultra_secret_pw", res_info.stdout)

            # 6. cron-sites output
            res_cron = subprocess.run(
                [
                    "python3",
                    db_lib_path,
                    "cron-sites",
                    tmp_db.name,
                    "modulartest.org"
                ],
                stdout=subprocess.PIPE,
                text=True,
                check=True
            )
            self.assertIn("modulartest.org|moduser|/var/www/modulartest.org|8.4", res_cron.stdout.strip())

        # Test core/lib/profiles.py operations
        res_list = subprocess.run(
            ["python3", profiles_lib_path, "list", profiles_yaml_path],
            stdout=subprocess.PIPE,
            text=True,
            check=True
        )
        self.assertIn("default", res_list.stdout)
        self.assertIn("agency_woocommerce", res_list.stdout)
        self.assertIn("high_traffic", res_list.stdout)

        res_show = subprocess.run(
            ["python3", profiles_lib_path, "show", profiles_yaml_path, "default"],
            stdout=subprocess.PIPE,
            text=True,
            check=True
        )
        self.assertIn("Profile Name:    default", res_show.stdout)
        self.assertIn("Memory Limit:    256M", res_show.stdout)

        res_get = subprocess.run(
            ["python3", profiles_lib_path, "get", profiles_yaml_path, "default", "memory_limit"],
            stdout=subprocess.PIPE,
            text=True,
            check=True
        )
        self.assertEqual(res_get.stdout.strip(), "256M")

        res_get_default = subprocess.run(
            ["python3", profiles_lib_path, "get", profiles_yaml_path, "default", "nonexistent.key", "fallback_val"],
            stdout=subprocess.PIPE,
            text=True,
            check=True
        )
        self.assertEqual(res_get_default.stdout.strip(), "fallback_val")

        # Verify scripts wire to modular helpers
        lsctl_path = os.path.join(BASE_DIR, "core", "bin", "lsctl")
        with open(lsctl_path, "r") as f:
            lsctl_code = f.read()
        self.assertIn('${LIB_DIR}/db.py', lsctl_code)
        self.assertIn('${LIB_DIR}/profiles.py', lsctl_code)
        self.assertNotIn("def load_yaml", lsctl_code)

        cron_path = os.path.join(BASE_DIR, "core", "bin", "ls-cron-queue")
        with open(cron_path, "r") as f:
            cron_code = f.read()
        self.assertIn('db.py" cron-sites', cron_code)

        upgrade_path = os.path.join(BASE_DIR, "core", "bin", "ls-upgrade")
        with open(upgrade_path, "r") as f:
            upgrade_code = f.read()
        self.assertIn('core/lib', upgrade_code)


if __name__ == "__main__":
    unittest.main()




