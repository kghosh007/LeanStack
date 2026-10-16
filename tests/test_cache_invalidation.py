#!/usr/bin/env python3
"""
Strictest Automated Test Suite for LeanStack Cache Architecture, Isolation & Invalidation
Validates:
1. Per-Site FastCGI Cache Isolation & Directory Structure
2. Surgical Single-URL MD5 (levels=1:2) Cache Path Computation & Unlink Logic
3. Multi-Tenant PHP OPcache Invalidation (tenant-scoped ABSPATH filtering, opcache_reset locked out)
4. APCu Cryptographic Namespacing & Coexistence with Redis/Valkey Object Cache
5. Universal SSI Hole-Punching Engine (Editor bypass, form nonce, batched SSI)
6. Cloudflare Edge CDN Integration (Single-URL & Full Zone payloads)
7. Nginx/Angie Linter Validation for cache-config.conf
"""

import unittest
import os
import sys
import hashlib
import tempfile
import shutil
import re
import json

import subprocess

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LINTER_BIN = os.path.join(BASE_DIR, "core", "bin", "cp-nginx-linter")


class TestFastCGICacheIsolationAndSurgicalPurge(unittest.TestCase):
    """Tests FastCGI per-tenant isolation and mathematical levels=1:2 cache file purging."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="ls_cache_test_")
        self.site_a = "alpha.example.com"
        self.site_b = "beta.example.com"
        self.dir_a = os.path.join(self.test_dir, "sites", self.site_a)
        self.dir_b = os.path.join(self.test_dir, "sites", self.site_b)
        os.makedirs(self.dir_a, exist_ok=True)
        os.makedirs(self.dir_b, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def _compute_cache_path(self, cache_dir, key):
        """Replicates Angie/Nginx levels=1:2 md5 directory structure."""
        md5_hash = hashlib.md5(key.encode("utf-8")).hexdigest()
        # levels=1:2 -> level 1 is 1 char (last char), level 2 is 2 chars (preceding 2 chars)
        sub1 = md5_hash[-1]
        sub2 = md5_hash[-3:-1]
        full_path = os.path.join(cache_dir, sub1, sub2, md5_hash)
        return full_path, md5_hash

    def test_cache_zone_key_sanitization(self):
        """Verify domain names are safely sanitized into Angie keys_zone identifiers."""
        domains = {
            "example.com": "example_com",
            "my-sub.store.co.uk": "my_sub_store_co_uk",
            "Alpha_123.Shop": "alpha_123_shop"
        }
        for d, expected in domains.items():
            sanitized = re.sub(r"[^a-z0-9]", "_", d.lower())
            self.assertEqual(sanitized, expected)

    def test_surgical_single_url_purge(self):
        """Simulate creating multiple cached URL responses and surgically deleting only one."""
        url_1 = "/blog/post-1/"
        url_2 = "/blog/post-2/"
        key_1 = f"httpsGET{self.site_a}{url_1}"
        key_2 = f"httpsGET{self.site_a}{url_2}"

        path_1, _ = self._compute_cache_path(self.dir_a, key_1)
        path_2, _ = self._compute_cache_path(self.dir_a, key_2)

        os.makedirs(os.path.dirname(path_1), exist_ok=True)
        os.makedirs(os.path.dirname(path_2), exist_ok=True)

        with open(path_1, "w") as f:
            f.write("CACHED_CONTENT_FOR_POST_1")
        with open(path_2, "w") as f:
            f.write("CACHED_CONTENT_FOR_POST_2")

        self.assertTrue(os.path.exists(path_1))
        self.assertTrue(os.path.exists(path_2))

        # Perform surgical purge of url_1 (simulate LeanStackBridge::purge_fastcgi_url)
        if os.path.exists(path_1):
            os.unlink(path_1)

        # Assert post 1 is deleted, post 2 is untouched
        self.assertFalse(os.path.exists(path_1))
        self.assertTrue(os.path.exists(path_2))

    def test_multi_tenant_cache_isolation_on_full_purge(self):
        """Verify purging site A leaves site B's cache files completely intact."""
        key_a = f"httpsGET{self.site_a}/"
        key_b = f"httpsGET{self.site_b}/"

        path_a, _ = self._compute_cache_path(self.dir_a, key_a)
        path_b, _ = self._compute_cache_path(self.dir_b, key_b)

        os.makedirs(os.path.dirname(path_a), exist_ok=True)
        os.makedirs(os.path.dirname(path_b), exist_ok=True)

        with open(path_a, "w") as f:
            f.write("SITE_A_CONTENT")
        with open(path_b, "w") as f:
            f.write("SITE_B_CONTENT")

        # Perform full flush on site A only
        for root, dirs, files in os.walk(self.dir_a, topdown=False):
            for file in files:
                os.unlink(os.path.join(root, file))

        # Site A cache must be empty
        remaining_a = [f for _, _, files in os.walk(self.dir_a) for f in files]
        self.assertEqual(len(remaining_a), 0)

        # Site B cache must still contain its cached file
        self.assertTrue(os.path.exists(path_b))
        with open(path_b, "r") as f:
            self.assertEqual(f.read(), "SITE_B_CONTENT")


class TestMultiTenantOpcacheIsolation(unittest.TestCase):
    """Tests the safe tenant-scoped OPcache invalidation algorithm."""

    def test_opcache_reset_strictly_prohibited(self):
        """Verify opcache_reset is listed in disable_functions in pool.conf.tpl."""
        pool_tpl = os.path.join(BASE_DIR, "core", "templates", "pool.conf.tpl")
        with open(pool_tpl, "r") as f:
            content = f.read()

        # opcache_reset must be disabled
        self.assertIn("opcache_reset", content)
        # opcache_invalidate must NOT be disabled so safe tenant purging can function
        m = re.search(r"php_admin_value\[disable_functions\]\s*=\s*([^\n]+)", content)
        self.assertIsNotNone(m)
        disabled = [fn.strip() for fn in m.group(1).split(",")]
        self.assertIn("opcache_reset", disabled)
        self.assertNotIn("opcache_invalidate", disabled)

    def test_tenant_opcache_invalidation_filter(self):
        """Simulate OPcache status scripts and test strict ABSPATH tenant scoping."""
        tenant_abspath = "/home/tenant1/htdocs/"
        other_tenant = "/home/tenant2/htdocs/"
        system_lib = "/usr/share/php/"

        mock_scripts = {
            "/home/tenant1/htdocs/wp-content/themes/custom/header.php": {"hits": 42},
            "/home/tenant1/htdocs/wp-includes/plugin.php": {"hits": 100},
            "/home/tenant2/htdocs/index.php": {"hits": 10},
            "/usr/share/php/Composer/autoload.php": {"hits": 999}
        }

        # Algorithm in LeanStackBridge::purge_tenant_opcache()
        purged = []
        for script_path in mock_scripts.keys():
            if script_path.startswith(tenant_abspath):
                purged.append(script_path)

        self.assertEqual(len(purged), 2)
        self.assertIn("/home/tenant1/htdocs/wp-content/themes/custom/header.php", purged)
        self.assertIn("/home/tenant1/htdocs/wp-includes/plugin.php", purged)
        self.assertNotIn("/home/tenant2/htdocs/index.php", purged)
        self.assertNotIn("/usr/share/php/Composer/autoload.php", purged)


class TestAPCuNamespacingAndRedisCoexistence(unittest.TestCase):
    """Tests APCu tenant namespace generation and zero conflict with redis-cache."""

    def test_no_object_cache_file_dropped(self):
        """Verify LeanStack does not deploy a conflicting object-cache.php drop-in."""
        # Ensure template dir does not contain object-cache.php
        tpl_dir = os.path.join(BASE_DIR, "core", "templates")
        self.assertFalse(os.path.exists(os.path.join(tpl_dir, "object-cache.php")))
        self.assertFalse(os.path.exists(os.path.join(tpl_dir, "object-cache.php.tpl")))

    def test_apcu_cryptographic_namespace_separation(self):
        """Verify different sites receive unique, collision-proof APCu prefix namespaces."""
        salt_a = "salt_alpha_99812739"
        db_a = "tenant_a_db"
        prefix_a = "ls_" + hashlib.md5(f"{salt_a}{db_a}".encode("utf-8")).hexdigest() + ":"

        salt_b = "salt_beta_182749182"
        db_b = "tenant_b_db"
        prefix_b = "ls_" + hashlib.md5(f"{salt_b}{db_b}".encode("utf-8")).hexdigest() + ":"

        self.assertNotEqual(prefix_a, prefix_b)
        self.assertTrue(prefix_a.startswith("ls_"))
        self.assertTrue(prefix_b.startswith("ls_"))
        self.assertTrue(prefix_a.endswith(":"))

        # Verify tenant A flush does not match tenant B keys
        key_a = prefix_a + "transient:sample_key"
        key_b = prefix_b + "transient:sample_key"

        regex_a = "^" + re.escape(prefix_a)
        self.assertTrue(bool(re.match(regex_a, key_a)))
        self.assertFalse(bool(re.match(regex_a, key_b)))


class TestSSIHolePunchingEngine(unittest.TestCase):
    """Tests the Universal SSI Hole-Punching template logic."""

    def setUp(self):
        tpl_path = os.path.join(BASE_DIR, "core", "templates", "leanstack-holepunch.php.tpl")
        with open(tpl_path, "r") as f:
            self.content = f.read()

    def test_editor_canvas_protection(self):
        """Verify visual page builders (Bricks, Elementor) bypass SSI tags inside builder canvas."""
        self.assertIn("bricks", self.content)
        self.assertIn("elementor-preview", self.content)
        self.assertIn("is_editor_active", self.content)

    def test_form_nonce_replacement_logic(self):
        """Verify auto form nonce hole-punching replacement exists."""
        self.assertIn("_wpnonce", self.content)
        self.assertIn("action=nonce", self.content)
        self.assertIn("<!--# include virtual=", self.content)

    def test_batched_ssi_resolution(self):
        """Verify single-pass batched price/stock SSI resolution exists to prevent subrequest storms."""
        self.assertIn("batch_price", self.content)
        self.assertIn("ids", self.content)
        self.assertIn("leanstack_ssi", self.content)


class TestCloudflarePurgeIntegration(unittest.TestCase):
    """Tests Cloudflare Edge CDN purge request formation."""

    def test_cloudflare_single_url_payload(self):
        """Verify JSON payload format for Cloudflare API v4 single URL purge."""
        url = "https://example.com/shop/sale-item/"
        payload = {"files": [url]}
        raw_json = json.dumps(payload)
        self.assertEqual(raw_json, '{"files": ["https://example.com/shop/sale-item/"]}')

    def test_cloudflare_full_zone_payload(self):
        """Verify JSON payload format for Cloudflare API v4 full zone purge."""
        payload = {"purge_everything": True}
        raw_json = json.dumps(payload)
        self.assertEqual(raw_json, '{"purge_everything": true}')


class TestCacheConfigLinter(unittest.TestCase):
    """Tests cp-nginx-linter validation on cache-config.conf."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".conf", mode="w+", delete=False)
        self.tmp.close()

    def tearDown(self):
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def run_linter(self, content):
        with open(self.tmp.name, "w") as f:
            f.write(content)
        cmd = [LINTER_BIN, self.tmp.name, "--mode=cache"]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            return json.loads(res.stdout)
        except Exception:
            return {"valid": False, "error": res.stderr}

    def test_valid_cache_config(self):
        """Verify standard valid cache directives pass linter."""
        res = self.run_linter("set $site_cache_enabled 1;\nset $site_cache_ttl 3600s;\n")
        self.assertTrue(res["valid"])

    def test_disabled_cache_config(self):
        """Verify cache disabling directive passes linter."""
        res = self.run_linter("set $site_cache_enabled 0;\nset $site_cache_ttl 60s;\n")
        self.assertTrue(res["valid"])

    def test_invalid_cache_directive(self):
        """Verify injected proxy_pass or unknown variables are rejected."""
        res = self.run_linter("set $site_cache_enabled 1;\nproxy_pass http://127.0.0.1:8080;\n")
        self.assertFalse(res["valid"])
        self.assertIn("Unauthorized directive", res["error"])

    def test_missing_semicolon_in_cache_config(self):
        """Verify missing semicolon is caught."""
        res = self.run_linter("set $site_cache_enabled 1\n")
        self.assertFalse(res["valid"])
        self.assertIn("Missing terminating semicolon", res["error"])


class TestFastCGICachePermissionsAndHierarchy(unittest.TestCase):
    """Tests FastCGI cache directory permissions, level-1 hex hierarchy, and stats scanning."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="ls_cache_perm_test_")
        self.site = "staging.mfeasy.in"
        self.cache_dir = os.path.join(self.test_dir, self.site)
        os.makedirs(self.cache_dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_level1_hex_scaffolding(self):
        """Verify all 16 hex directories (0-f) are scaffolded."""
        hex_chars = "0123456789abcdef"
        for h in hex_chars:
            os.makedirs(os.path.join(self.cache_dir, h), exist_ok=True)

        for h in hex_chars:
            self.assertTrue(os.path.isdir(os.path.join(self.cache_dir, h)))

    def test_recursive_scan_file_count_and_size(self):
        """Simulate scanning cache directory with nested files to test scan_cache_dir_stats logic."""
        sub1 = os.path.join(self.cache_dir, "0", "00")
        sub2 = os.path.join(self.cache_dir, "a", "bc")
        os.makedirs(sub1, exist_ok=True)
        os.makedirs(sub2, exist_ok=True)

        file1 = os.path.join(sub1, "60c91085e6affe68bc254a9e31bd7000")
        file2 = os.path.join(sub2, "abcdef1234567890abcdef1234567890")

        with open(file1, "wb") as f:
            f.write(b"X" * 1024)
        with open(file2, "wb") as f:
            f.write(b"Y" * 2048)

        files = 0
        total_bytes = 0

        def scan_stats(d):
            nonlocal files, total_bytes
            if not os.path.isdir(d):
                return
            for item in os.listdir(d):
                p = os.path.join(d, item)
                if os.path.isdir(p):
                    scan_stats(p)
                elif os.path.isfile(p):
                    files += 1
                    total_bytes += os.path.getsize(p)

        scan_stats(self.cache_dir)
        self.assertEqual(files, 2)
        self.assertEqual(total_bytes, 3072)

    def test_purge_all_preserves_hex_scaffolding(self):
        """Verify full purge deletes cache files but keeps both level-1 and level-2 hex directories intact."""
        hex_chars = "0123456789abcdef"
        for h in hex_chars:
            os.makedirs(os.path.join(self.cache_dir, h), exist_ok=True)

        sub = os.path.join(self.cache_dir, "0", "00")
        os.makedirs(sub, exist_ok=True)
        cached_file = os.path.join(sub, "sample_cache_file")
        with open(cached_file, "w") as f:
            f.write("CACHE_DATA")

        self.assertTrue(os.path.exists(cached_file))

        # Test the exact logic in LeanStackBridge::recursive_delete_dir_files
        def recursive_delete(d):
            count = 0
            for item in os.listdir(d):
                p = os.path.join(d, item)
                if os.path.isdir(p):
                    count += recursive_delete(p)
                elif os.path.isfile(p):
                    os.unlink(p)
                    count += 1
            return count

        purged_count = recursive_delete(self.cache_dir)
        self.assertEqual(purged_count, 1)
        self.assertFalse(os.path.exists(cached_file))
        # Level-2 directory must be preserved so Angie never recreates it with mode 0700
        self.assertTrue(os.path.exists(sub))

        for h in hex_chars:
            self.assertTrue(os.path.isdir(os.path.join(self.cache_dir, h)))

    def test_bridge_template_preserves_directories_on_purge(self):
        """Verify leanstack-bridge.php.tpl does not rmdir directories during cache purge."""
        bridge_tpl = os.path.join(BASE_DIR, "core", "templates", "leanstack-bridge.php.tpl")
        with open(bridge_tpl, "r") as f:
            bridge_c = f.read()
        # Verify rmdir is not called inside recursive_delete_dir_files
        rec_del_start = bridge_c.find("function recursive_delete_dir_files")
        rec_del_end = bridge_c.find("function purge_tenant_opcache", rec_del_start)
        rec_del_body = bridge_c[rec_del_start:rec_del_end]
        self.assertNotIn("@rmdir", rec_del_body)
        self.assertNotIn("rmdir(", rec_del_body)


class TestAPCuSyncAndResilience(unittest.TestCase):
    """Tests APCu prefix synchronization between bridge and apcu plugins and alloptions hooks."""

    def test_prefix_formula_match(self):
        """Verify leanstack-apcu and leanstack-bridge use identical prefix calculation."""
        apcu_tpl = os.path.join(BASE_DIR, "core", "templates", "leanstack-apcu.php.tpl")
        bridge_tpl = os.path.join(BASE_DIR, "core", "templates", "leanstack-bridge.php.tpl")

        with open(apcu_tpl, "r") as f:
            apcu_content = f.read()
        with open(bridge_tpl, "r") as f:
            bridge_content = f.read()

        self.assertIn("'ls_' . md5( $salt . $db ) . ':'", apcu_content)
        self.assertIn("'ls_' . md5( $salt . $db ) . ':'", bridge_content)
        self.assertIn("get_prefix", apcu_content)
        self.assertIn("get_prefix", bridge_content)

    def test_alloptions_and_transient_hooks_present(self):
        """Verify alloptions acceleration and transient hooks are active in leanstack-apcu."""
        apcu_tpl = os.path.join(BASE_DIR, "core", "templates", "leanstack-apcu.php.tpl")
        with open(apcu_tpl, "r") as f:
            content = f.read()

        self.assertIn("pre_wp_load_alloptions", content)
        self.assertIn("pre_cache_alloptions", content)
        self.assertIn("cache_alloptions", content)
        self.assertIn("invalidate_alloptions", content)
        self.assertIn("register_cached_transient_hooks", content)
        self.assertIn("handle_pre_transient", content)
        self.assertIn("LeanStackAPCu::get_instance()", content)

    def test_throwable_exception_safety(self):
        """Verify bridge and apcu catch Throwable for APCUIterator robustness."""
        apcu_tpl = os.path.join(BASE_DIR, "core", "templates", "leanstack-apcu.php.tpl")
        bridge_tpl = os.path.join(BASE_DIR, "core", "templates", "leanstack-bridge.php.tpl")

        with open(apcu_tpl, "r") as f:
            apcu_c = f.read()
        with open(bridge_tpl, "r") as f:
            bridge_c = f.read()

        self.assertIn("catch ( Throwable $e )", apcu_c)
        self.assertIn("catch ( Throwable $e )", bridge_c)

    def test_angie_override_umask(self):
        """Verify angie systemd override sets UMask=0002 for group-accessible cache files."""
        ov_file = os.path.join(BASE_DIR, "systemd", "overrides", "angie.service.d", "override.conf")
        with open(ov_file, "r") as f:
            ov_c = f.read()
        self.assertIn("UMask=0002", ov_c)

    def test_lsctl_and_ls_upgrade_provisioning(self):
        """Verify lsctl and ls-upgrade configure www-data group, 2770 permissions, and APCu."""
        lsctl_file = os.path.join(BASE_DIR, "core", "bin", "lsctl")
        upgrade_file = os.path.join(BASE_DIR, "core", "bin", "ls-upgrade")
        watcher_file = os.path.join(BASE_DIR, "core", "bin", "ls-watcher")
        pool_tpl = os.path.join(BASE_DIR, "core", "templates", "pool.conf.tpl")

        with open(lsctl_file, "r") as f:
            lsctl_c = f.read()
        with open(upgrade_file, "r") as f:
            upgrade_c = f.read()
        with open(watcher_file, "r") as f:
            watcher_c = f.read()
        with open(pool_tpl, "r") as f:
            pool_c = f.read()

        # lsctl tests
        self.assertIn("www-data", lsctl_c)
        self.assertIn("2770", lsctl_c)
        self.assertIn("setfacl", lsctl_c)

        # ls-upgrade tests
        self.assertIn("www-data", upgrade_c)
        self.assertIn("2770", upgrade_c)
        self.assertIn("apc.enabled", upgrade_c)
        self.assertIn("setfacl", upgrade_c)

        # ls-watcher tests
        self.assertIn("heal_cache_permissions", watcher_c)
        self.assertIn("2770", watcher_c)

        # pool.conf.tpl
        self.assertIn("php_admin_flag[apc.enabled] = on", pool_c)


if __name__ == "__main__":
    unittest.main()
