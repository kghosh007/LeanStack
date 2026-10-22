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
        for domain in domains:
            res = self.create(domain)
            self.assertEqual(res.returncode, 0, res.stderr + res.stdout)
            outputs.append(res.stdout)
        self.assertNotIn("host PHP budget exceeded", outputs[0])
        self.assertNotIn("host PHP budget exceeded", outputs[1])
        self.assertIn("host PHP budget exceeded", outputs[2])
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
        self.assertIn("/var/cache/angie/sites/shop.example", text)
        self.assertNotIn("/var/cache/angie/sites:", text)
        self.assertNotIn("/proc", text)
        basedir = text.split("open_basedir] = ", 1)[1].split("\n", 1)[0]
        self.assertNotIn("/usr/bin/msmtp", basedir)
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

    def test_create_uses_tenant_group_only(self):
        lsctl = pathlib.Path(LSCTL).read_text(encoding="utf-8")
        self.assertIn('useradd -m -s /bin/false -U -G tenants -d', lsctl)
        self.assertNotIn("-G tenants,valkey,www-data", lsctl)
        self.assertNotIn("usermod -a -G www-data", lsctl)
        self.assertIn("user default off", lsctl)
        self.assertNotIn("+select +flushdb", lsctl)
        self.assertIn("-select -flushdb", lsctl)


if __name__ == "__main__":
    unittest.main()
