#!/usr/bin/env python3
"""
Unit Tests for LeanStack Nginx Configuration & Security Headers Linter (cp-nginx-linter)
"""

import unittest
import os
import subprocess
import json
import sqlite3
import tempfile
import shutil
import hashlib

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LINTER_BIN = os.path.join(BASE_DIR, "core", "bin", "cp-nginx-linter")
GATEKEEPER_BIN = os.path.join(BASE_DIR, "core", "bin", "cp-gatekeeper")

class TestNginxLinter(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def run_linter(self, content, mode="auto", user=None, strict_csp=False, filename="test.conf", extra_env=None):
        fpath = os.path.join(self.test_dir, filename)
        with open(fpath, "w") as f:
            f.write(content)

        cmd = [LINTER_BIN, fpath, f"--mode={mode}"]
        if user:
            cmd.append(f"--user={user}")
        if strict_csp:
            cmd.append("--strict-csp")

        env = os.environ.copy()
        if extra_env:
            env.update(extra_env)
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        try:
            data = json.loads(res.stdout)
        except Exception:
            data = {"valid": False, "raw": res.stdout, "stderr": res.stderr}
        return res.returncode, data

    def test_valid_compressx_webp_rules(self):
        """Verify valid CompressX / WebP rewrite rules pass linter inspection."""
        rules = """
        # CompressX WebP Rewrites
        location ~* ^/wp-content/uploads/(.+)\\.(png|jpe?g)$ {
            add_header Vary Accept;
            try_files $uri$webp_suffix $uri =404;
        }
        """
        code, data = self.run_linter(rules, mode="rules")
        self.assertEqual(code, 0)
        self.assertTrue(data.get("valid"))

    def test_prohibited_include_directive(self):
        """Verify that 'include' directives are blocked for tenant safety."""
        rules = "include /etc/shadow;"
        code, data = self.run_linter(rules, mode="rules")
        self.assertNotEqual(code, 0)
        self.assertFalse(data.get("valid"))
        self.assertIn("strictly prohibited", data.get("error", ""))

    def test_prohibited_listen_directive(self):
        """Verify that 'listen' port hijacking directives are blocked."""
        rules = "listen 8080;"
        code, data = self.run_linter(rules, mode="rules")
        self.assertNotEqual(code, 0)
        self.assertFalse(data.get("valid"))
        self.assertIn("listen", data.get("error", ""))

    def test_prohibited_lua_directives(self):
        """Verify that dangerous Lua execution directives are blocked."""
        rules = "access_by_lua 'os.execute(\"id\")';"
        code, data = self.run_linter(rules, mode="rules")
        self.assertNotEqual(code, 0)
        self.assertFalse(data.get("valid"))

    def test_path_traversal_in_root(self):
        """Verify directory traversal in root is rejected."""
        rules = "root /home/tenant/htdocs/../../etc;"
        code, data = self.run_linter(rules, mode="rules")
        self.assertNotEqual(code, 0)
        self.assertFalse(data.get("valid"))
        self.assertIn("traversal", data.get("error", "").lower())

    def test_system_path_in_root(self):
        """Verify system paths targeting /etc or /var are rejected."""
        rules = "root /etc/nginx;"
        code, data = self.run_linter(rules, mode="rules")
        self.assertNotEqual(code, 0)
        self.assertFalse(data.get("valid"))

    def test_forbidden_proxy_target(self):
        """Verify proxying to localhost or cloud metadata is rejected."""
        rules = "location /meta { proxy_pass http://169.254.169.254/latest/; }"
        code, data = self.run_linter(rules, mode="rules")
        self.assertNotEqual(code, 0)
        self.assertFalse(data.get("valid"))

    def test_variable_proxy_and_fastcgi_targets(self):
        """A dollar sign in proxy_pass or fastcgi_pass is rejected before DNS."""
        for rules in (
            "proxy_pass http://$upstream;",
            "fastcgi_pass $php_upstream;",
        ):
            code, data = self.run_linter(rules, mode="rules")
            self.assertNotEqual(code, 0, rules)
            self.assertIn("variable proxy target", data.get("error", ""))

    def test_loopback_and_private_proxy_targets(self):
        """Literal loopback, private, and userinfo-hidden loopback targets are rejected."""
        for rules in (
            "proxy_pass http://127.0.0.1;",
            "proxy_pass http://10.1.2.3:8080/admin;",
            "proxy_pass http://public@127.0.0.1/latest;",
            "fastcgi_pass 127.0.0.1:9000;",
            "proxy_pass unix:/run/angie.sock;",
        ):
            code, data = self.run_linter(rules, mode="rules")
            self.assertNotEqual(code, 0, rules)
            self.assertFalse(data.get("valid"), rules)

    def test_resolved_loopback_proxy_target(self):
        """A public name that the fixture maps to loopback is rejected."""
        rules = "proxy_pass http://example.com/latest;"
        code, data = self.run_linter(
            rules,
            mode="rules",
            extra_env={"LEANSTACK_RESOLVE": "example.com=127.0.0.1"},
        )
        self.assertNotEqual(code, 0)
        self.assertFalse(data.get("valid"))
        self.assertIn("public address", data.get("error", ""))

    def test_public_literal_proxy_and_legal_redirect(self):
        """A public literal proxy and a redirect variable stay legal."""
        code, data = self.run_linter("proxy_pass http://1.1.1.1/status;", mode="rules")
        self.assertEqual(code, 0)
        self.assertTrue(data.get("valid"))

        code, data = self.run_linter(
            "return 301 https://example.com$request_uri;",
            mode="rules",
        )
        self.assertEqual(code, 0)
        self.assertTrue(data.get("valid"))

        code, data = self.run_linter(
            "fastcgi_pass unix:/run/php/php8.5-fpm-demo.sock;",
            mode="rules",
        )
        self.assertEqual(code, 0)
        self.assertTrue(data.get("valid"))

    def test_prohibited_ssi_and_alias(self):
        """Tenant files cannot enable SSI or retarget the URI with alias."""
        for rules in ("ssi on;", "alias /var/www/html;"):
            code, data = self.run_linter(rules, mode="rules")
            self.assertNotEqual(code, 0, rules)
            self.assertIn("strictly prohibited", data.get("error", ""))

    def test_unbalanced_braces(self):
        """Verify unbalanced braces syntax error is detected."""
        rules = "location /test { try_files $uri =404;"
        code, data = self.run_linter(rules, mode="rules")
        self.assertNotEqual(code, 0)
        self.assertFalse(data.get("valid"))

    def test_valid_security_headers_with_wasm_csp(self):
        """Verify valid security headers with WebAssembly blob: worker-src pass."""
        headers = """
        add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header X-Frame-Options "SAMEORIGIN" always;
        add_header Referrer-Policy "strict-origin-when-cross-origin" always;
        add_header Content-Security-Policy "default-src 'self' https:; worker-src 'self' blob:;" always;
        """
        code, data = self.run_linter(headers, mode="headers", strict_csp=True, filename="security-headers.conf")
        self.assertEqual(code, 0)
        self.assertTrue(data.get("valid"))

    def test_security_headers_missing_semicolon(self):
        """Verify missing semicolon in security headers triggers syntax error."""
        headers = 'add_header X-Frame-Options "SAMEORIGIN"'
        code, data = self.run_linter(headers, mode="headers", filename="security-headers.conf")
        self.assertNotEqual(code, 0)
        self.assertFalse(data.get("valid"))
        self.assertIn("semicolon", data.get("error", "").lower())

    def test_security_headers_unauthorized_directive(self):
        """Verify non-header directive in security-headers.conf is rejected."""
        headers = """
        add_header X-Frame-Options "SAMEORIGIN" always;
        root /tmp/bad;
        """
        code, data = self.run_linter(headers, mode="headers", filename="security-headers.conf")
        self.assertNotEqual(code, 0)
        self.assertFalse(data.get("valid"))
        self.assertIn("Unauthorized directive", data.get("error", ""))

    def test_csp_missing_wasm_worker_blob(self):
        """Verify strict CSP rejects policies missing blob: worker-src for WebAssembly."""
        headers = 'add_header Content-Security-Policy "default-src \'self\'; worker-src \'self\';" always;'
        code, data = self.run_linter(headers, mode="headers", strict_csp=True, filename="security-headers.conf")
        self.assertNotEqual(code, 0)
        self.assertFalse(data.get("valid"))
        self.assertIn("worker-src", data.get("error", ""))

    def _sites_db(self, rows):
        db_path = os.path.join(self.test_dir, "sites.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE sites (domain TEXT, user TEXT)")
        conn.executemany("INSERT INTO sites (domain, user) VALUES (?, ?)", rows)
        conn.commit()
        conn.close()
        return db_path

    def _gate_env(self, db_path):
        custom = os.path.join(self.test_dir, "tenant-custom")
        os.makedirs(custom, exist_ok=True)
        env = os.environ.copy()
        env["LEANSTACK_DB"] = db_path
        env["LEANSTACK_TENANT_CUSTOM"] = custom
        return env, custom

    def _write_tenant_conf(self, user, body):
        user_dir = os.path.join(self.test_dir, "home", user, "nginx")
        os.makedirs(user_dir, exist_ok=True)
        conf_file = os.path.join(user_dir, "custom-early.conf")
        with open(conf_file, "w") as handle:
            handle.write(body)
        return user_dir, conf_file

    def _run_gate(self, conf_file, env):
        return subprocess.run(
            [GATEKEEPER_BIN, "--process", conf_file],
            text=True,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def test_gatekeeper_requires_registered_site(self):
        """A missing sites row writes an error and leaves tenant-custom untouched."""
        db_path = self._sites_db([("other.example", "other_usr")])
        env, custom = self._gate_env(db_path)
        sentinel_dir = os.path.join(custom, "other.example")
        os.makedirs(sentinel_dir, exist_ok=True)
        sentinel = os.path.join(sentinel_dir, "custom-early.conf")
        with open(sentinel, "w") as handle:
            handle.write("SENTINEL\n")
        with open(sentinel, "rb") as handle:
            before = handle.read()

        _user_dir, conf_file = self._write_tenant_conf(
            "demo_usr",
            "# Valid rule\nlocation /valid { try_files $uri =404; }\n",
        )
        res = self._run_gate(conf_file, env)
        self.assertNotEqual(res.returncode, 0, res.stderr)

        status_file = os.path.join(os.path.dirname(conf_file), ".status.json")
        with open(status_file, "r") as handle:
            status = json.load(handle)
        self.assertEqual(status.get("status"), "error")
        self.assertEqual(status.get("message"), "No site is registered for this user.")
        with open(sentinel, "rb") as handle:
            self.assertEqual(handle.read(), before)
        self.assertEqual(sorted(os.listdir(custom)), ["other.example"])

    def test_gatekeeper_process_mode(self):
        """A registered site is copied only into that domain, and a second run keeps the bytes."""
        db_path = self._sites_db([
            ("shop.example", "demo_usr"),
            ("other.example", "other_usr"),
        ])
        env, custom = self._gate_env(db_path)
        sentinel = os.path.join(custom, "other.example", "custom-early.conf")
        os.makedirs(os.path.dirname(sentinel), exist_ok=True)
        with open(sentinel, "w") as handle:
            handle.write("SENTINEL\n")

        body = "# Valid rule\nlocation /valid { try_files $uri =404; }\n"
        _user_dir, conf_file = self._write_tenant_conf("demo_usr", body)
        res = self._run_gate(conf_file, env)
        self.assertEqual(res.returncode, 0, res.stderr + res.stdout)

        status_file = os.path.join(os.path.dirname(conf_file), ".status.json")
        with open(status_file, "r") as handle:
            status = json.load(handle)
        self.assertEqual(status.get("status"), "active")

        prod = os.path.join(custom, "shop.example", "custom-early.conf")
        self.assertTrue(os.path.isfile(prod))
        with open(prod, "rb") as handle:
            first = handle.read()
        self.assertEqual(first, body.encode())
        with open(sentinel, "rb") as handle:
            self.assertEqual(handle.read(), b"SENTINEL\n")

        res = self._run_gate(conf_file, env)
        self.assertEqual(res.returncode, 0, res.stderr + res.stdout)
        with open(prod, "rb") as handle:
            second = handle.read()
        self.assertEqual(second, first)
        self.assertEqual(hashlib.sha256(second).hexdigest(), hashlib.sha256(first).hexdigest())

    def test_multiline_split_directives(self):
        """Directives split across lines are tokenized and inspected correctly."""
        code, data = self.run_linter("proxy_pass\n    http://127.0.0.1;\n", mode="rules")
        self.assertNotEqual(code, 0)
        self.assertFalse(data.get("valid"))
        self.assertIn("internal or metadata host", data.get("error", ""))

        code, data = self.run_linter("include\n    /etc/passwd;\n", mode="rules")
        self.assertNotEqual(code, 0)
        self.assertFalse(data.get("valid"))
        self.assertIn("strictly prohibited", data.get("error", ""))

    def test_multiple_statements_per_line(self):
        """Multiple statements on a single line are individually validated."""
        code, data = self.run_linter("try_files $uri =404; proxy_pass http://127.0.0.1;", mode="rules")
        self.assertNotEqual(code, 0)
        self.assertFalse(data.get("valid"))
        self.assertIn("internal or metadata host", data.get("error", ""))

    def test_comments_within_directives(self):
        """Comments interspersed in statements do not hide prohibited directives or targets."""
        code, data = self.run_linter("proxy_pass # inline comment\n    http://127.0.0.1;\n", mode="rules")
        self.assertNotEqual(code, 0)
        self.assertFalse(data.get("valid"))
        self.assertIn("internal or metadata host", data.get("error", ""))

    def test_prohibited_pass_family_directives(self):
        """uwsgi_pass, scgi_pass, grpc_pass, memcached_pass, resolver and any unknown *_pass are blocked."""
        prohibited_samples = [
            ("uwsgi_pass 127.0.0.1:8000;", "uwsgi_pass"),
            ("scgi_pass 127.0.0.1:9000;", "scgi_pass"),
            ("grpc_pass grpc://127.0.0.1:50051;", "grpc_pass"),
            ("memcached_pass 127.0.0.1:11211;", "memcached_pass"),
            ("resolver 1.1.1.1 8.8.8.8;", "resolver"),
            ("custom_pass 1.1.1.1:80;", "custom_pass"),
        ]
        for snippet, d_name in prohibited_samples:
            code, data = self.run_linter(snippet, mode="rules")
            self.assertNotEqual(code, 0, f"Snippet '{snippet}' should be rejected")
            self.assertFalse(data.get("valid"))
            self.assertIn("strictly prohibited", data.get("error", ""))

    def test_dns_rebinding_rejection_for_hostnames(self):
        """Hostnames requiring runtime resolution in proxy_pass are rejected to eliminate DNS rebinding."""
        code, data = self.run_linter("proxy_pass http://dynamic-rebind.org/api;", mode="rules")
        self.assertNotEqual(code, 0)
        self.assertFalse(data.get("valid"))
        self.assertIn("public address", data.get("error", ""))

    def test_root_prefix_boundary_strictness(self):
        """Root directive must strictly match directory boundary (/htdocs or /htdocs/)."""
        code, data = self.run_linter("root /home/alice/htdocs_evil;", mode="rules", user="alice")
        self.assertNotEqual(code, 0)
        self.assertFalse(data.get("valid"))
        self.assertIn("must stay within", data.get("error", ""))

        code, data = self.run_linter("root /home/alice/htdocs;", mode="rules", user="alice")
        self.assertEqual(code, 0)
        self.assertTrue(data.get("valid"))

        code, data = self.run_linter("root /home/alice/htdocs/subfolder;", mode="rules", user="alice")
        self.assertEqual(code, 0)
        self.assertTrue(data.get("valid"))

        code, data = self.run_linter("root /home/alice/htdocs/../htdocs_evil;", mode="rules", user="alice")
        self.assertNotEqual(code, 0)
        self.assertFalse(data.get("valid"))
        self.assertIn("traversal", data.get("error", "").lower())

    def test_fastcgi_pass_socket_isolation(self):
        """fastcgi_pass must use Unix socket in /run/php/ matching the tenant user."""
        code, data = self.run_linter("fastcgi_pass unix:/run/php/php8.3-fpm-alice.sock;", mode="rules", user="alice")
        self.assertEqual(code, 0)
        self.assertTrue(data.get("valid"))

        code, data = self.run_linter("fastcgi_pass unix:/run/php/php8.3-fpm-bob.sock;", mode="rules", user="alice")
        self.assertNotEqual(code, 0)
        self.assertFalse(data.get("valid"))
        self.assertIn("can only reference Unix socket for tenant 'alice'", data.get("error", ""))

        code, data = self.run_linter("fastcgi_pass unix:/run/angie.sock;", mode="rules", user="alice")
        self.assertNotEqual(code, 0)
        self.assertFalse(data.get("valid"))
        self.assertIn("must reside in /run/php/", data.get("error", ""))


if __name__ == "__main__":
    unittest.main()
