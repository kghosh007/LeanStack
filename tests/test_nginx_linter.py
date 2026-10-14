#!/usr/bin/env python3
"""
Unit Tests for LeanStack Nginx Configuration & Security Headers Linter (cp-nginx-linter)
"""

import unittest
import os
import subprocess
import json
import tempfile
import shutil

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LINTER_BIN = os.path.join(BASE_DIR, "core", "bin", "cp-nginx-linter")
GATEKEEPER_BIN = os.path.join(BASE_DIR, "core", "bin", "cp-gatekeeper")

class TestNginxLinter(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def run_linter(self, content, mode="auto", user=None, strict_csp=False, filename="test.conf"):
        fpath = os.path.join(self.test_dir, filename)
        with open(fpath, "w") as f:
            f.write(content)

        cmd = [LINTER_BIN, fpath, f"--mode={mode}"]
        if user:
            cmd.append(f"--user={user}")
        if strict_csp:
            cmd.append("--strict-csp")

        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
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
        """Verify directory traversal in root/alias is rejected."""
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

    def test_gatekeeper_process_mode(self):
        """Verify cp-gatekeeper --process synchronously evaluates and records status."""
        user_dir = os.path.join(self.test_dir, "home", "demo_usr", "nginx")
        os.makedirs(user_dir, exist_ok=True)
        conf_file = os.path.join(user_dir, "custom-early.conf")
        with open(conf_file, "w") as f:
            f.write("# Valid rule\nlocation /valid { try_files $uri =404; }\n")

        res = subprocess.run([GATEKEEPER_BIN, "--process", conf_file], text=True)
        self.assertEqual(res.returncode, 0)

        status_file = os.path.join(user_dir, ".status.json")
        self.assertTrue(os.path.exists(status_file))
        with open(status_file, "r") as f:
            status = json.load(f)
        self.assertEqual(status.get("status"), "active")


if __name__ == "__main__":
    unittest.main()
