#!/usr/bin/env python3
"""Host-budget invariants for the tuning document."""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "installer")))

from probe import HardwareProbe, TuningCalculator


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


if __name__ == "__main__":
    unittest.main()
