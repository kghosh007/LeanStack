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
        self.assertIn("php_admin_value[open_basedir] = /home/{{USER_NAME}}", content)
        self.assertNotIn(":/tmp", content)  # Global /tmp must not be in open_basedir
        self.assertIn("php_admin_value[disable_functions]", content)
        self.assertIn("dl,opcache_reset", content)
        self.assertNotIn("symlink", content)
        self.assertNotIn("link,", content)
        self.assertNotIn("curl_multi_exec", content)
        self.assertNotIn("parse_ini_file", content)
        self.assertIn("php_admin_value[upload_tmp_dir]", content)
        self.assertIn("listen.mode = 0660", content)
        self.assertIn("/run/valkey", content)
        self.assertIn("/run/mysqld", content)
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
        self.assertIn("DISABLE_WP_CRON", content)
        self.assertIn("HTTP_X_FORWARDED_PROTO", content)
        self.assertIn("HTTP_CF_VISITOR", content)

    def test_cron_queue_sandboxing(self):
        """Verify cp-cron-queue applies strict PHP open_basedir, proc_open retention, and flock lock."""
        cron_bin = os.path.join(BASE_DIR, "core", "bin", "ls-cron-queue")
        self.assertTrue(os.path.exists(cron_bin))
        with open(cron_bin, "r") as f:
            content = f.read()
        self.assertIn("-d open_basedir=", content)
        self.assertIn("-d disable_functions=", content)
        self.assertNotIn("proc_open,", content)  # proc_open must NOT be disabled for WP-CLI
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

        # Check phase4 and ls-upgrade module loader scaffolding
        phase4 = os.path.join(BASE_DIR, "scripts", "phase4_angie_waf.sh")
        with open(phase4, "r") as f:
            p4 = f.read()
        self.assertIn("angie-module-cache-purge", p4)
        self.assertIn("ngx_http_cache_purge_module.so", p4)
        self.assertIn("rm -f /etc/angie/modules.d/cache-purge.conf", p4)

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
        self.assertIn('--chdir="$site_path"', content)

        service_file = os.path.join(BASE_DIR, "systemd", "cp-cron.service")
        with open(service_file, "r") as f:
            svc_content = f.read()
        self.assertIn("WorkingDirectory=/tmp", svc_content)

    def test_open_basedir_benign_warning_suppressor(self):
        """Verify leanstack-shield and leanstack-bridge deploy benign open_basedir warning suppressor."""
        shield_tpl = os.path.join(BASE_DIR, "core", "templates", "leanstack-shield.php.tpl")
        bridge_tpl = os.path.join(BASE_DIR, "core", "templates", "leanstack-bridge.php.tpl")

        for tpl_path in [shield_tpl, bridge_tpl]:
            with open(tpl_path, "r") as f:
                content = f.read()
            self.assertIn("leanstack_suppress_benign_open_basedir_warnings", content)
            self.assertIn("open_basedir restriction in effect", content)
            self.assertIn("File(/home)", content)
            self.assertIn("File(/)", content)
            self.assertIn("backup-storage.php", content)
            self.assertIn("File(core/", content)
            self.assertIn("File(man-params.mustache)", content)

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

    def test_phase4_angie_tls_and_doctor_hardening(self):
        """Verify phase4_angie_waf.sh configures full TLS 1.2/1.3 ECDHE AEAD ciphers, prime256v1, http2 on, and lsctl doctor audits them."""
        import subprocess
        phase4_path = os.path.join(BASE_DIR, "scripts", "phase4_angie_waf.sh")
        with open(phase4_path, "r") as f:
            p4 = f.read()

        self.assertIn("ssl_protocols TLSv1.2 TLSv1.3;", p4)
        self.assertIn("ssl_prefer_server_ciphers on;", p4)
        self.assertIn("ssl_session_cache shared:SSL:50m;", p4)
        self.assertIn("ssl_session_timeout 1d;", p4)
        self.assertIn("ssl_session_tickets off;", p4)
        self.assertIn("ssl_ecdh_curve X25519MLKEM768:x25519:prime256v1:secp384r1;", p4)
        self.assertIn("ssl_ecdh_curve x25519:prime256v1:secp384r1;", p4)
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
        self.assertIn('local df_val="exec,passthru,shell_exec,system,proc_open,popen,curl_multi_exec,parse_ini_file,show_source,dl,opcache_reset"', gk_content)
        self.assertIn('if [ "$mode" == "benchmark" ]; then', gk_content)
        self.assertIn('df_val="exec,passthru,shell_exec,system,proc_open,popen,show_source,dl,opcache_reset"', gk_content)

        watcher_path = os.path.join(BASE_DIR, "core", "bin", "ls-watcher")
        with open(watcher_path, "r") as f:
            watcher_content = f.read()
        self.assertIn('local df_strict="exec,passthru,shell_exec,system,proc_open,popen,curl_multi_exec,parse_ini_file,show_source,dl,opcache_reset"', watcher_content)

    def test_ls_cron_queue_sudo_arguments_order(self):
        """Verify ls-cron-queue places options (--chdir) before environment variable assignments in sudo command."""
        cq_path = os.path.join(BASE_DIR, "core", "bin", "ls-cron-queue")
        with open(cq_path, "r") as f:
            cq_content = f.read()
        chdir_idx = cq_content.find('sudo_cmd+=(--chdir="$site_path")')
        home_idx = cq_content.find('sudo_cmd+=(HOME="/home/${user}")')
        self.assertNotEqual(chdir_idx, -1)
        self.assertNotEqual(home_idx, -1)
        self.assertLess(chdir_idx, home_idx, "--chdir must precede HOME=... in sudo command array")

    def test_apcu_stat_cache_clearing(self):
        """Verify leanstack-apcu.php.tpl invalidates PHP stat cache before reading cron status mtime."""
        apcu_path = os.path.join(BASE_DIR, "core", "templates", "leanstack-apcu.php.tpl")
        with open(apcu_path, "r") as f:
            apcu_content = f.read()
        self.assertIn("clearstatcache( true, $sf );", apcu_content)

if __name__ == "__main__":
    unittest.main()



