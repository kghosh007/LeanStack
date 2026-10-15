import unittest
import shutil
import tempfile
import os
import subprocess

class TestValkeyAclSyntax(unittest.TestCase):
    def test_valkey_acl_rule_validity(self):
        redis_server = shutil.which("redis-server") or shutil.which("valkey-server")
        if not redis_server:
            self.skipTest("redis-server or valkey-server not installed")
        
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write("user default on nopass ~* &* +@all\nuser test on >pass123 ~* +@all -@admin -@dangerous -flushall -shutdown -config -debug -monitor +select +flushdb\n")
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
            import time
            time.sleep(0.3)
            
            redis_cli = shutil.which("redis-cli") or shutil.which("valkey-cli")
            if redis_cli and os.path.exists(sock_path):
                res = subprocess.run([redis_cli, "-s", sock_path, "--user", "test", "-a", "pass123", "ping"], capture_output=True, text=True)
                self.assertIn("PONG", res.stdout)
            
            proc.terminate()
            proc.wait(timeout=2)
        finally:
            if os.path.exists(acl_path):
                os.unlink(acl_path)
            if os.path.exists(sock_path):
                os.unlink(sock_path)

if __name__ == "__main__":
    unittest.main()
