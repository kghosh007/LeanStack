#!/usr/bin/env python3
"""Host-budget invariants for the tuning document and lsctl pool writes."""

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "installer")))

from probe import HardwareProbe, TuningCalculator

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LSCTL = os.path.join(BASE_DIR, "core", "bin", "lsctl")


def site_children(memory_limit, budget):
    raw = memory_limit[:-1] if memory_limit[-1:] in "MmGg" else memory_limit
    mb = int(raw)
    if memory_limit[-1:] in "Gg":
        mb *= 1024
    if mb < 1:
        mb = 256
    return max(2, budget * 128 // mb)


class TestHostBudget(unittest.TestCase):
    def test_2048mb_two_cores_budget_at_least_two(self):
        probe = HardwareProbe(sim_ram_mb=2048, sim_cores=2)
        php = TuningCalculator(probe.probe_all()).to_document()["php"]
        self.assertIsInstance(php["host_budget_children"], int)
        self.assertGreaterEqual(php["host_budget_children"], 2)
        self.assertEqual(php["host_budget_children"], php["pm_max_children"])
        self.assertLessEqual(php["pm_start_servers"], php["pm_max_children"])
        self.assertLessEqual(php["pm_min_spare_servers"], php["pm_start_servers"])
        self.assertLessEqual(php["pm_max_spare_servers"], php["pm_max_children"])


class TestPoolBudgetFixture(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="ls-pool-")
        self.env = os.environ.copy()
        self.env.update({
            "LEANSTACK_ROOT": self.root,
            "LEANSTACK_SIMULATE_RAM": "2048",
            "LEANSTACK_SIMULATE_CORES": "2",
            "_LEANSTACK_LSCTL_DELEGATED": "1",
        })
        self.budget = TuningCalculator(
            HardwareProbe(sim_ram_mb=2048, sim_cores=2).probe_all()
        ).to_document()["php"]["host_budget_children"]
        self.per_site = site_children("256M", self.budget)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def create(self, domain, *extra):
        return subprocess.run(
            [LSCTL, "wp:create", f"--domain={domain}", *extra],
            env=self.env,
            text=True,
            capture_output=True,
            check=False,
        )

    def pools(self):
        found = []
        php = os.path.join(self.root, "etc", "php")
        for dirpath, _, files in os.walk(php):
            for name in files:
                if name.endswith(".conf"):
                    found.append(os.path.join(dirpath, name))
        return found

    def test_third_site_warns_and_keeps_requested_workers(self):
        domains = ["one.example", "two.example", "three.example"]
        outputs = []
        for domain in domains[:2]:
            res = self.create(domain)
            self.assertEqual(res.returncode, 0, res.stderr + res.stdout)
            outputs.append(res.stdout)
        self.assertNotIn("host PHP budget exceeded", outputs[0])
        self.assertNotIn("host PHP budget exceeded", outputs[1])

        # Third site exceeds host PHP worker budget and must be blocked without --force (LS-12)
        unforced = self.create(domains[2])
        self.assertNotEqual(unforced.returncode, 0)
        self.assertIn("host PHP budget exceeded", unforced.stdout + unforced.stderr)

        # Overriding with --force allows creating the site and keeps requested workers
        res = self.create(domains[2], "--force")
        self.assertEqual(res.returncode, 0, res.stderr + res.stdout)
        self.assertIn("host PHP budget exceeded", res.stdout)

        files = self.pools()
        self.assertEqual(len(files), 3)
        total = 0
        for path in files:
            text = pathlib.Path(path).read_text(encoding="utf-8")
            self.assertIn("pm = ondemand", text)
            self.assertNotIn("pm.start_servers", text)
            self.assertIn(f"pm.max_children = {self.per_site}", text)
            disabled = text.split("disable_functions] = ", 1)[1].split("\n", 1)[0]
            self.assertIn("opcache_reset", disabled)
            self.assertIn("apcu_clear_cache", disabled)
            self.assertNotIn("opcache_invalidate", disabled)
            total += self.per_site
        self.assertGreater(total, self.budget)

    def test_dynamic_spares_and_invalid_mode(self):
        good = self.create("shop.example", "--pool-mode=dynamic")
        self.assertEqual(good.returncode, 0, good.stderr)
        text = pathlib.Path(self.pools()[0]).read_text(encoding="utf-8")
        self.assertIn("pm = dynamic", text)
        self.assertIn("pm.start_servers", text)
        self.assertIn("pm.min_spare_servers", text)
        self.assertIn("pm.max_spare_servers", text)
        before = list(self.pools())
        bad = self.create("typo.example", "--pool-mode=typo")
        self.assertNotEqual(bad.returncode, 0)
        self.assertEqual(self.pools(), before)

    def test_site_pool_is_idempotent_and_listed(self):
        created = self.create("edit.example", "--pool-mode=ondemand")
        self.assertEqual(created.returncode, 0, created.stderr)
        first = subprocess.run(
            [LSCTL, "site:pool", "edit.example", "--mode=static", "--max-children=4"],
            env=self.env, text=True, capture_output=True, check=False,
        )
        self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
        path = self.pools()[0]
        body = pathlib.Path(path).read_text(encoding="utf-8")
        self.assertIn("pm = static", body)
        self.assertIn("pm.max_children = 4", body)
        self.assertNotIn("pm.start_servers", body)
        second = subprocess.run(
            [LSCTL, "site:pool", "edit.example", "--mode=static", "--max-children=4"],
            env=self.env, text=True, capture_output=True, check=False,
        )
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(pathlib.Path(path).read_text(encoding="utf-8"), body)
        self.assertFalse(os.path.exists(path + ".bak"))
        listed = subprocess.run(
            [LSCTL, "site:list", "--json"],
            env=self.env, text=True, capture_output=True, check=False,
        )
        self.assertEqual(listed.returncode, 0, listed.stderr)
        rows = json.loads(listed.stdout)
        self.assertEqual(rows[0]["domain"], "edit.example")
        self.assertEqual(rows[0]["pool_mode"], "static")
        refused = subprocess.run(
            [LSCTL, "site:pool", "edit.example", "--max-children=1"],
            env=self.env, text=True, capture_output=True, check=False,
        )
        self.assertNotEqual(refused.returncode, 0)
        self.assertEqual(pathlib.Path(path).read_text(encoding="utf-8"), body)

    def test_help_lists_site_pool(self):
        res = subprocess.run(
            [LSCTL], env=self.env, text=True, capture_output=True, check=False,
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("site:pool", res.stdout)

    def test_pool_file_is_scoped_to_the_site(self):
        res = self.create("shop.example")
        self.assertEqual(res.returncode, 0, res.stderr + res.stdout)
        text = pathlib.Path(self.pools()[0]).read_text(encoding="utf-8")
        self.assertIn("listen.group = ", text)
        self.assertNotIn("listen.group = www-data", text)
        self.assertIn("/var/cache/angie/sites/shop.example/", text)
        self.assertNotIn("/var/cache/angie/sites:", text)
        self.assertNotIn("/proc", text)
        basedir = text.split("open_basedir] = ", 1)[1].split("\n", 1)[0]
        self.assertNotIn("/usr/bin/msmtp", basedir)
        # Ensure all directory entries in open_basedir end with trailing slash to prevent prefix collision (LS-05)
        for entry in basedir.split(":"):
            if not entry.endswith(".sock"):
                self.assertTrue(entry.endswith("/"), f"Directory entry in open_basedir must end with '/': {entry}")
        disabled = text.split("disable_functions] = ", 1)[1].split("\n", 1)[0]
        self.assertIn("proc_open", disabled)


class TestTenantIsolation(unittest.TestCase):
    def test_rendered_host_has_no_shared_pool_or_open_valkey(self):
        from provision import render_files
        doc = TuningCalculator(HardwareProbe(sim_ram_mb=2048, sim_cores=2).probe_all()).to_document()
        files = render_files(doc, ["8.3"])
        names = "\n".join(files)
        self.assertNotIn("pool.d/system.conf", names)
        self.assertEqual(files["etc/valkey/users.acl"].strip(), "user default off")
        angie = files["etc/angie/angie.conf"]
        self.assertIn("fastcgi_ignore_headers Cache-Control Expires;", angie)
        self.assertNotIn("Set-Cookie", angie)
        self.assertIn("RuntimeDirectoryMode=0750", files["etc/systemd/system/valkey.service"])
        self.assertIn("unixsocketperm 660", files["etc/valkey/valkey.conf"])
        self.assertIn("lua-time-limit 500", files["etc/valkey/valkey.conf"])

    def test_create_uses_tenant_group_only(self):
        lsctl = pathlib.Path(LSCTL).read_text(encoding="utf-8")
        self.assertIn('useradd -m -s /bin/false -U -G tenants -d', lsctl)
        self.assertNotIn("-G tenants,valkey,www-data", lsctl)
        self.assertNotIn("usermod -a -G www-data", lsctl)
        self.assertIn("user default off", lsctl)
        self.assertNotIn("+select +flushdb", lsctl)
        self.assertNotIn("-select -flushdb", lsctl)
        acl_fn = lsctl.split("valkey_tenant_acl_line()", 1)[1].split("grant_valkey_socket()", 1)[0]
        self.assertIn("+eval +evalsha +select -flushdb -flushall", acl_fn)
        self.assertNotIn("+flushdb", acl_fn)
        self.assertNotIn("+flushall", acl_fn)
        self.assertIn(
            'Valkey tenant ACL can still flush a database or read every key',
            lsctl,
        )
        self.assertNotIn("can still select a database", lsctl)

    def test_valkey_selective_flush_eval_and_tenant_isolation(self):
        from provision import tenant_acl_line
        import socket
        import time

        server_bin = shutil.which("valkey-server") or shutil.which("redis-server") or "/usr/bin/redis-server"
        if not os.path.exists(server_bin):
            self.skipTest("valkey-server / redis-server not available")

        with tempfile.TemporaryDirectory() as d:
            sock = os.path.join(d, "valkey.sock")
            acl = os.path.join(d, "users.acl")
            conf = os.path.join(d, "valkey.conf")
            with open(acl, "w", encoding="utf-8") as f:
                f.write("user default on nopass ~* &* +@all\n")
                f.write(tenant_acl_line("staging_mfeasy_4809", "SecretPass123", "379cf5_") + "\n")
                f.write(tenant_acl_line("other_tenant_1001", "OtherPass456", "999999_") + "\n")
            with open(conf, "w", encoding="utf-8") as f:
                f.write(f"port 0\nunixsocket {sock}\naclfile {acl}\nlua-time-limit 500\ndir {d}\n")

            proc = subprocess.Popen([server_bin, conf], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                for _ in range(30):
                    if os.path.exists(sock):
                        break
                    time.sleep(0.05)
                self.assertTrue(os.path.exists(sock), "Valkey/Redis test socket failed to start")

                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.connect(sock)

                def send(*args):
                    payload = f"*{len(args)}\r\n" + "".join(f"${len(str(a))}\r\n{a}\r\n" for a in args)
                    s.sendall(payload.encode("utf-8"))
                    return s.recv(4096).decode("utf-8", errors="replace")

                # Seed another tenant's key as default before switching to tenant user
                self.assertIn("+OK", send("SET", "999999_wp:secret", "isolated_value"))

                # Authenticate as staging_mfeasy_4809
                self.assertIn("+OK", send("AUTH", "staging_mfeasy_4809", "SecretPass123"))
                self.assertIn("+OK", send("SET", "379cf5_wp:key1", "v1"))
                self.assertIn("+OK", send("SET", "379cf5_wp:key2", "v2"))

                # Verify WP_REDIS_SELECTIVE_FLUSH Lua script via EVAL succeeds on tenant prefix
                lua_selective_flush = (
                    'local cur = 0 local i = 0 local tmp '
                    'repeat tmp = redis.call("SCAN", cur, "MATCH", ARGV[1]) '
                    'cur = tonumber(tmp[1]) '
                    'if tmp[2] then for _, v in pairs(tmp[2]) do redis.call("DEL", v) i = i + 1 end end '
                    'until 0 == cur return i'
                )
                self.assertEqual(send("EVAL", lua_selective_flush, "0", "379cf5_*"), ":2\r\n")

                # Verify cross-tenant key access inside EVAL is strictly blocked by ACL
                self.assertIn("No permissions to access a key", send("EVAL", lua_selective_flush, "0", "*"))
                self.assertIn("No permissions to access a key", send("EVAL", 'return redis.call("GET", "999999_wp:secret")', "0"))

                # Verify FLUSHDB and SCRIPT FLUSH remain blocked
                self.assertIn("NOPERM", send("FLUSHDB"))
                self.assertIn("NOPERM", send("SCRIPT", "FLUSH"))
                s.close()
            finally:
                proc.terminate()
                proc.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
