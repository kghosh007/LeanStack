#!/usr/bin/env python3
"""
Unit Tests for LeanStack Hardware Probing & Tuning Engine
Verifies deterministic mathematical scaling across various VPS hardware tiers.
"""

import unittest
import os
import sys

# Add installer directory to module path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "installer")))

from probe import HardwareProbe, TuningCalculator

class TestHardwareTuning(unittest.TestCase):

    def get_profile_for(self, ram_mb: int, cores: int, has_avx2: bool = True):
        probe = HardwareProbe(sim_ram_mb=ram_mb, sim_cores=cores)
        hw = probe.probe_all()
        hw["cpu"]["features"]["avx2"] = has_avx2
        calc = TuningCalculator(hw)
        return calc.generate_full_profile()

    def test_tier_1gb_vps(self):
        """1GB RAM, 1 vCPU tier - Ultra low footprint."""
        p = self.get_profile_for(ram_mb=1024, cores=1)
        m = p["mariadb"]
        v = p["valkey"]
        php = p["php"]

        # MariaDB buffer pool capped safely at 512M
        self.assertEqual(m["innodb_buffer_pool_size"], "512M")
        self.assertEqual(m["innodb_buffer_pool_instances"], 1)
        self.assertEqual(m["sort_buffer_size"], "256K")
        self.assertEqual(m["transaction_isolation"], "READ-COMMITTED")
        self.assertEqual(m["mrr_cost_based"], "on")

        # Valkey 10% (min 128MB)
        self.assertEqual(v["maxmemory"], "128mb")
        self.assertEqual(v["port"], 0)

        # PHP min workers
        self.assertGreaterEqual(php["pm_max_children"], 5)

    def test_tier_6gb_vps(self):
        """6GB RAM, 4 vCPU tier - The perfectionist test from conversation-tuning.md."""
        p = self.get_profile_for(ram_mb=6144, cores=4)
        m = p["mariadb"]
        v = p["valkey"]
        php = p["php"]

        # Exactly 2800M buffer pool as proven in tuning teardown
        self.assertEqual(m["innodb_buffer_pool_size"], "2800M")
        self.assertEqual(m["innodb_buffer_pool_instances"], 2)
        self.assertEqual(m["sort_buffer_size"], "256K")
        self.assertEqual(m["table_open_cache_instances"], 4)
        self.assertEqual(m["transaction_isolation"], "READ-COMMITTED")

        # Valkey ~614MB
        self.assertEqual(v["maxmemory"], "614mb")

        # PHP workers ~47
        self.assertGreaterEqual(php["pm_max_children"], 30)
        self.assertEqual(php["opcache_jit"], "tracing")

    def test_tier_16gb_vps(self):
        """16GB RAM, 8 vCPU tier - Dedicated high-density server."""
        p = self.get_profile_for(ram_mb=16384, cores=8)
        m = p["mariadb"]
        v = p["valkey"]

        # 55% buffer pool (~9011M)
        self.assertGreaterEqual(m["innodb_buffer_pool_size_mb"], 8000)
        self.assertEqual(m["innodb_buffer_pool_instances"], 8)
        self.assertEqual(m["sort_buffer_size"], "512K")
        self.assertEqual(m["table_open_cache_instances"], 8)

        # Valkey capped at 10% (~1638MB)
        self.assertEqual(v["maxmemory_mb"], 1638)

    def test_cache_sized_per_query_buffers_never_16mb(self):
        """CRITICAL: Ensure sort_buffer_size is NEVER 16MB across any tier."""
        for ram in [1024, 2048, 4096, 6144, 16384, 65536]:
            for cores in [1, 2, 4, 8, 16, 32]:
                p = self.get_profile_for(ram_mb=ram, cores=cores)
                sort_buf = p["mariadb"]["sort_buffer_size"]
                self.assertIn(sort_buf, ["256K", "512K"])
                self.assertNotEqual(sort_buf, "16M")

if __name__ == "__main__":
    unittest.main()
