import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "installer")))

class TestValkeyAclSyntax(unittest.TestCase):
    def test_valkey_acl_rule_validity(self):
        redis_server = shutil.which("redis-server") or shutil.which("valkey-server")
        if not redis_server:
            self.skipTest("redis-server or valkey-server not installed")
        
        from provision import TENANT_ACL_COMMANDS
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write(
                "user default off\n"
                f"user test on >pass123 ~siteprefix_* {TENANT_ACL_COMMANDS}\n"
                "user other on >pass456 ~otherprefix_* "
                f"{TENANT_ACL_COMMANDS}\n"
            )
            acl_path = f.name
            
        try:
            sock_path = os.path.join(tempfile.gettempdir(), f"test_valkey_{os.getpid()}.sock")
            if os.path.exists(sock_path):
                os.unlink(sock_path)
            proc = subprocess.Popen(
                [redis_server, "--port", "0", "--unixsocket", sock_path, "--unixsocketperm", "777", "--aclfile", acl_path, "--daemonize", "no"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            for _ in range(20):
                if os.path.exists(sock_path):
                    break
                time.sleep(0.1)
            if not os.path.exists(sock_path):
                proc.terminate()
                err = ""
                if proc.stderr:
                    err = proc.stderr.read()
                self.fail(f"valkey did not accept the tenant ACL: {err}")

            redis_cli = shutil.which("redis-cli") or shutil.which("valkey-cli")
            if redis_cli:
                # 1. Verify ping works
                res_ping = subprocess.run([redis_cli, "-s", sock_path, "--user", "test", "-a", "pass123", "ping"], capture_output=True, text=True)
                self.assertIn("PONG", res_ping.stdout)

                # 2. Verify info command succeeds without NOPERM error (required for WordPress Redis Object Cache)
                res_info = subprocess.run([redis_cli, "-s", sock_path, "--user", "test", "-a", "pass123", "info"], capture_output=True, text=True)
                self.assertNotIn("NOPERM", res_info.stdout + res_info.stderr)
                self.assertTrue("redis_version" in res_info.stdout or "valkey_version" in res_info.stdout or "Server" in res_info.stdout)

                # 3. Verify dangerous/admin commands remain strictly forbidden
                res_config = subprocess.run([redis_cli, "-s", sock_path, "--user", "test", "-a", "pass123", "config", "get", "dir"], capture_output=True, text=True)
                self.assertIn("NOPERM", res_config.stdout + res_config.stderr)

                res_shutdown = subprocess.run([redis_cli, "-s", sock_path, "--user", "test", "-a", "pass123", "shutdown"], capture_output=True, text=True)
                self.assertIn("NOPERM", res_shutdown.stdout + res_shutdown.stderr)

                own = subprocess.run([redis_cli, "-s", sock_path, "--user", "test", "-a", "pass123", "set", "siteprefix_page", "1"], capture_output=True, text=True)
                self.assertIn("OK", own.stdout)
                foreign = subprocess.run([redis_cli, "-s", sock_path, "--user", "test", "-a", "pass123", "get", "otherprefix_page"], capture_output=True, text=True)
                self.assertIn("NOPERM", foreign.stdout + foreign.stderr)
                selected = subprocess.run([redis_cli, "-s", sock_path, "--user", "test", "-a", "pass123", "select", "1"], capture_output=True, text=True)
                self.assertIn("NOPERM", selected.stdout + selected.stderr)
                flushed = subprocess.run([redis_cli, "-s", sock_path, "--user", "test", "-a", "pass123", "flushdb"], capture_output=True, text=True)
                self.assertIn("NOPERM", flushed.stdout + flushed.stderr)
            
            proc.terminate()
            proc.wait(timeout=2)
        finally:
            if os.path.exists(acl_path):
                os.unlink(acl_path)
            if os.path.exists(sock_path):
                os.unlink(sock_path)

if __name__ == "__main__":
    unittest.main()
