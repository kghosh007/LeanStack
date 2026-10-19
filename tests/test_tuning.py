#!/usr/bin/env python3
"""
Unit Tests for LeanStack Hardware Probing & Tuning Engine
Verifies deterministic mathematical scaling across various VPS hardware tiers.
"""

import unittest
import os
import sys
import json

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
        self.assertEqual(m["sort_buffer_size"], "1M")
        self.assertEqual(m["transaction_isolation"], "READ-COMMITTED")
        self.assertEqual(m["mrr_cost_based"], "on")
        self.assertEqual(m["query_cache_type"], 0)
        self.assertEqual(m["aria_pagecache_buffer_size"], "64M")

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
        self.assertEqual(m["sort_buffer_size"], "2M")
        self.assertEqual(m["table_open_cache_instances"], 4)
        self.assertEqual(m["transaction_isolation"], "READ-COMMITTED")
        self.assertEqual(m["query_cache_type"], 0)
        self.assertEqual(m["aria_pagecache_buffer_size"], "128M")

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
        self.assertEqual(m["sort_buffer_size"], "4M")
        self.assertEqual(m["table_open_cache_instances"], 8)
        self.assertEqual(m["aria_pagecache_buffer_size"], "256M")

        # Valkey capped at 10% (~1638MB)
        self.assertEqual(v["maxmemory_mb"], 1638)

    def test_cache_sized_per_query_buffers_never_16mb(self):
        """CRITICAL: Ensure sort_buffer_size is NEVER 16MB across any tier."""
        for ram in [1024, 2048, 4096, 6144, 16384, 65536]:
            for cores in [1, 2, 4, 8, 16, 32]:
                p = self.get_profile_for(ram_mb=ram, cores=cores)
                sort_buf = p["mariadb"]["sort_buffer_size"]
                self.assertIn(sort_buf, ["1M", "2M", "4M"])
                self.assertNotEqual(sort_buf, "16M")

    def test_angie_tls_ecdhe_and_pqc_probing(self):
        """Verify Angie tuning profile and check_pqc_and_tls13 include TLS 1.2 ECDHE AEAD ciphers, prime256v1, and HTTP/2."""
        from probe import check_pqc_and_tls13
        p = self.get_profile_for(ram_mb=4096, cores=4)
        a = p["angie"]

        self.assertEqual(a["pqc_curve"], "X25519MLKEM768:x25519:prime256v1:secp384r1")
        self.assertEqual(a["ecdh_fallback_curve"], "x25519:prime256v1:secp384r1")
        self.assertIn("prime256v1", a["pqc_curve"])
        self.assertIn("TLS_AES_256_GCM_SHA384", a["ssl_ciphers"])
        self.assertIn("TLS_CHACHA20_POLY1305_SHA256", a["ssl_ciphers"])
        self.assertIn("ECDHE-ECDSA-AES256-GCM-SHA384", a["ssl_ciphers"])
        self.assertIn("ECDHE-RSA-AES256-GCM-SHA384", a["ssl_ciphers"])
        self.assertIn("ECDHE-ECDSA-CHACHA20-POLY1305", a["ssl_ciphers"])
        self.assertIn("ECDHE-RSA-CHACHA20-POLY1305", a["ssl_ciphers"])
        self.assertIn("ECDHE-ECDSA-AES128-GCM-SHA256", a["ssl_ciphers"])
        self.assertIn("ECDHE-RSA-AES128-GCM-SHA256", a["ssl_ciphers"])
        self.assertEqual(a["ssl_protocols"], "TLSv1.2 TLSv1.3")
        self.assertTrue(a["tls12_ecdhe_enabled"])
        self.assertTrue(a["http2_enabled"])
        self.assertTrue(a["http3_enabled"])

        tls_info = check_pqc_and_tls13()
        self.assertTrue(tls_info["tls13_supported"])
        self.assertTrue(tls_info["tls12_ecdhe_supported"])
        self.assertTrue(tls_info["prime256v1_supported"])
        self.assertTrue(tls_info["x25519_supported"])
        self.assertIn("prime256v1", tls_info["recommended_ecdh_curve"])
        self.assertIn("ECDHE-ECDSA-AES128-GCM-SHA256", tls_info["recommended_ciphers"])

    def test_storage_aware_io_capacity(self):
        """Verify dynamic storage IO capacity and thread scaling for NVMe vs SATA SSD vs HDD."""
        # 1. NVMe SSD on 4-core VPS
        p_nvme = self.get_profile_for(ram_mb=4096, cores=4)
        p_nvme["hardware"]["storage"]["is_nvme"] = True
        p_nvme["hardware"]["storage"]["is_rotational"] = False
        calc_nvme = TuningCalculator(p_nvme["hardware"])
        m_nvme = calc_nvme.calculate_mariadb()
        self.assertEqual(m_nvme["innodb_io_capacity"], 8000)
        self.assertEqual(m_nvme["innodb_io_capacity_max"], 16000)
        self.assertEqual(m_nvme["innodb_read_io_threads"], 4)
        self.assertEqual(m_nvme["innodb_flush_neighbors"], 0)

        # 2. SATA SSD on 2-core VPS
        p_ssd = self.get_profile_for(ram_mb=2048, cores=2)
        p_ssd["hardware"]["storage"]["is_nvme"] = False
        p_ssd["hardware"]["storage"]["is_rotational"] = False
        calc_ssd = TuningCalculator(p_ssd["hardware"])
        m_ssd = calc_ssd.calculate_mariadb()
        self.assertEqual(m_ssd["innodb_io_capacity"], 1000)
        self.assertEqual(m_ssd["innodb_io_capacity_max"], 2000)
        self.assertEqual(m_ssd["innodb_flush_neighbors"], 0)

        # 3. Rotational HDD
        p_hdd = self.get_profile_for(ram_mb=4096, cores=4)
        p_hdd["hardware"]["storage"]["is_nvme"] = False
        p_hdd["hardware"]["storage"]["is_rotational"] = True
        calc_hdd = TuningCalculator(p_hdd["hardware"])
        m_hdd = calc_hdd.calculate_mariadb()
        self.assertEqual(m_hdd["innodb_io_capacity"], 200)
        self.assertEqual(m_hdd["innodb_io_capacity_max"], 400)
        self.assertEqual(m_hdd["innodb_read_io_threads"], 2)
        self.assertEqual(m_hdd["innodb_flush_neighbors"], 1)

    def test_angie_cache_and_connections_scaling(self):
        """Verify Angie worker connections and FastCGI microcache max size scaling."""
        p_small = self.get_profile_for(ram_mb=2048, cores=2)
        self.assertEqual(p_small["angie"]["worker_connections"], 4096)
        self.assertEqual(p_small["angie"]["fastcgi_cache_max_size"], "256m")

        p_med = self.get_profile_for(ram_mb=8192, cores=4)
        self.assertEqual(p_med["angie"]["worker_connections"], 8192)
        self.assertEqual(p_med["angie"]["fastcgi_cache_max_size"], "512m")

        p_large = self.get_profile_for(ram_mb=16384, cores=8)
        self.assertEqual(p_large["angie"]["worker_connections"], 16384)
        self.assertEqual(p_large["angie"]["fastcgi_cache_max_size"], "1024m")

    def test_autonomous_db_tuner_analyzer(self):
        """Verify ls-db-tune performance analyzer scoring and recommendations."""
        sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "core", "bin")))
        # Import directly by path
        import importlib.machinery
        import importlib.util
        tuner_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "core", "bin", "ls-db-tune"))
        loader = importlib.machinery.SourceFileLoader("ls_db_tune", tuner_path)
        spec = importlib.util.spec_from_loader("ls_db_tune", loader)
        ls_db_tune = importlib.util.module_from_spec(spec)
        loader.exec_module(ls_db_tune)


        hw = {
            "ram_mb": 4096,
            "cores": 4,
            "is_nvme": True,
            "is_rotational": False,
            "disk_type": "NVMe SSD"
        }
        # Simulate clean, high-performance database state
        mock_status = {
            "Uptime": "100000",
            "Innodb_buffer_pool_read_requests": "1000000",
            "Innodb_buffer_pool_reads": "100",
            "Sort_merge_passes": "0",
            "Created_tmp_disk_tables": "5",
            "Created_tmp_tables": "100",
            "Open_tables": "500",
            "Opened_tables": "520",
            "Threads_created": "10",
            "Connections": "1000"
        }
        mock_vars = {
            "version": "12.3.3-MariaDB",
            "innodb_buffer_pool_size": "1433M",
            "transaction_isolation": "READ-COMMITTED",
            "sort_buffer_size": "2M",
            "table_open_cache": "4096",
            "table_open_cache_instances": "4",
            "innodb_io_capacity": "8000",
            "query_cache_type": "0",
            "performance_schema": "OFF"
        }

        analyzer = ls_db_tune.DatabaseTuningAnalyzer(
            hardware=hw,
            is_live=True,
            status=mock_status,
            variables=mock_vars,
            fragmented_tables=[]
        )
        report = analyzer.analyze()
        self.assertEqual(report["score"], 100)
        self.assertEqual(report["ideal_tuning"]["innodb_io_capacity"], 8000)
        self.assertEqual(report["ideal_tuning"]["innodb_io_capacity_max"], 16000)
        self.assertEqual(report["ideal_tuning"]["transaction_isolation"], "READ-COMMITTED")
        check_names = [c["name"] for c in report["checks"]]
        self.assertIn("Thread Cache Efficiency", check_names)
        self.assertIn("InnoDB Lock Contention", check_names)

        # Test sub-optimal case (Sort merge passes, REPEATABLE-READ, low buffer pool hit rate, lock waits, high dirty pages)
        bad_status = dict(mock_status)
        bad_status["Sort_merge_passes"] = "45"
        bad_status["Innodb_buffer_pool_reads"] = "200000"
        bad_status["Threads_created"] = "150"  # 85% hit rate
        bad_status["Innodb_row_lock_waits"] = "40"
        bad_status["Innodb_row_lock_time_avg"] = "1200"
        bad_status["Innodb_buffer_pool_pages_dirty"] = "500"
        bad_status["Innodb_buffer_pool_pages_total"] = "1000"
        bad_vars = dict(mock_vars)
        bad_vars["transaction_isolation"] = "REPEATABLE-READ"
        bad_vars["sort_buffer_size"] = "16M"  # Over allocation risk

        bad_analyzer = ls_db_tune.DatabaseTuningAnalyzer(
            hardware=hw,
            is_live=True,
            status=bad_status,
            variables=bad_vars,
            fragmented_tables=[]
        )
        bad_report = bad_analyzer.analyze()
        self.assertLess(bad_report["score"], 70)
        self.assertTrue(len(bad_report["recommendations"]) >= 3)

    def test_apply_tuning_profile_includes_instances_and_live_set_global(self):
        """Verify apply_tuning_profile writes buffer pool instances and executes SET GLOBAL on live collector."""
        import tempfile
        import importlib.machinery
        import importlib.util
        tuner_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "core", "bin", "ls-db-tune"))
        loader = importlib.machinery.SourceFileLoader("ls_db_tune", tuner_path)
        spec = importlib.util.spec_from_loader("ls_db_tune", loader)
        ls_db_tune = importlib.util.module_from_spec(spec)
        loader.exec_module(ls_db_tune)

        ideal = {
            "innodb_buffer_pool_size": "2800M",
            "innodb_buffer_pool_instances": 2,
            "innodb_log_file_size": "700M",
            "innodb_io_capacity": 8000,
            "innodb_io_capacity_max": 16000,
            "innodb_read_io_threads": 4,
            "innodb_write_io_threads": 4,
            "innodb_flush_neighbors": 0,
            "sort_buffer_size": "2M",
            "join_buffer_size": "2M",
            "read_rnd_buffer_size": "1M",
            "aria_pagecache_buffer_size": "128M",
            "aria_sort_buffer_size": "32M",
            "table_open_cache": 4096,
            "table_open_cache_instances": 4,
            "max_connections": 300,
            "transaction_isolation": "READ-COMMITTED"
        }

        # Mock collector recording SET GLOBAL queries
        class MockCollector:
            cli_cmd = "/usr/bin/mariadb"
            executed = []
            def query(self, sql: str):
                self.executed.append(sql)
                return [["1"]]

        collector = MockCollector()
        with tempfile.TemporaryDirectory() as tmp_dir:
            res = ls_db_tune.apply_tuning_profile(ideal, conf_dir=tmp_dir, collector=collector)
            self.assertTrue(res)

            cnf_path = os.path.join(tmp_dir, "99-leanstack-highqps.cnf")
            self.assertTrue(os.path.isfile(cnf_path))
            with open(cnf_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Verify innodb_buffer_pool_instances is written to [mysqld] and [mariadb]
            self.assertIn("innodb_buffer_pool_instances   = 2", content)
            self.assertIn("innodb_io_capacity             = 8000", content)
            self.assertIn("table_open_cache_instances     = 4", content)

            # Verify SET GLOBAL executed for dynamic variables
            set_globals = [q for q in collector.executed if q.startswith("SET GLOBAL")]
            self.assertTrue(len(set_globals) >= 5)
            self.assertTrue(any("max_connections" in q for q in set_globals))
            self.assertTrue(any("innodb_io_capacity" in q for q in set_globals))
            self.assertTrue(any("innodb_buffer_pool_size" in q for q in set_globals))

    def test_cold_cache_warmup_no_bogus_buffer_pool_recommendation(self):
        """Verify low uptime (<2h) recognizes cold cache warmup and never recommends increasing buffer pool when current >= optimal."""
        import importlib.machinery
        import importlib.util
        tuner_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "core", "bin", "ls-db-tune"))
        loader = importlib.machinery.SourceFileLoader("ls_db_tune", tuner_path)
        spec = importlib.util.spec_from_loader("ls_db_tune", loader)
        ls_db_tune = importlib.util.module_from_spec(spec)
        loader.exec_module(ls_db_tune)

        hw = {
            "ram_mb": 15986,
            "cores": 4,
            "is_nvme": False,
            "is_rotational": False,
            "disk_type": "SATA SSD"
        }
        # Simulate exact scenario reported by user: uptime 56s, hit rate 43.86%, current pool 8792M
        mock_status = {
            "Uptime": "56",
            "Innodb_buffer_pool_read_requests": "4100",
            "Innodb_buffer_pool_reads": "2301",  # 43.86% hit rate
            "Sort_merge_passes": "0",
            "Created_tmp_disk_tables": "2",
            "Created_tmp_tables": "60",
            "Open_tables": "100",
            "Opened_tables": "110",
            "Threads_created": "5",
            "Connections": "150",
            "Innodb_row_lock_waits": "0",
            "Innodb_buffer_pool_pages_dirty": "0",
            "Innodb_buffer_pool_pages_total": "1000"
        }
        mock_vars = {
            "version": "12.3.3-MariaDB-ubu2604",
            "innodb_buffer_pool_size": "8792M",
            "transaction_isolation": "READ-COMMITTED",
            "sort_buffer_size": "4194304",
            "table_open_cache": "4096",
            "table_open_cache_instances": "3",  # Needs tune to 4
            "innodb_io_capacity": "2000",
            "query_cache_type": "0",
            "query_cache_size": "0",
            "performance_schema": "OFF",
            "thread_cache_size": "128"
        }

        analyzer = ls_db_tune.DatabaseTuningAnalyzer(
            hardware=hw,
            is_live=True,
            status=mock_status,
            variables=mock_vars,
            fragmented_tables=[]
        )
        report = analyzer.analyze()

        # Check that hit rate is marked INFO / Warming up rather than WARN
        hit_rate_check = next((c for c in report["checks"] if c["name"] == "InnoDB Buffer Pool Hit Rate"), None)
        self.assertIsNotNone(hit_rate_check)
        self.assertEqual(hit_rate_check["status"], "INFO")
        self.assertIn("Warming", hit_rate_check["value"])
        self.assertIn("warming up", hit_rate_check["desc"])

        # Sizing check should be PASS because 8792MB is optimal for ~16GB RAM
        sizing_check = next((c for c in report["checks"] if c["name"] == "InnoDB Buffer Pool Sizing"), None)
        self.assertIsNotNone(sizing_check)
        self.assertEqual(sizing_check["status"], "PASS")

        # Must NOT recommend increasing buffer pool from 8792M to 8792M
        for rec in report["recommendations"]:
            self.assertNotIn("from 8792M to 8792M", rec)
            self.assertNotIn("Increase innodb_buffer_pool_size from 8792M", rec)

        # Only recommendation should be table_open_cache_instances = 4
        self.assertEqual(len(report["recommendations"]), 1)
        self.assertIn("table_open_cache_instances = 4", report["recommendations"][0])

    def test_apply_optimizations_alias_and_innodb_buffer_pool_size_set_global(self):
        """Verify apply_optimizations alias works and executes SET GLOBAL for innodb_buffer_pool_size."""
        import tempfile
        import importlib.machinery
        import importlib.util
        tuner_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "core", "bin", "ls-db-tune"))
        loader = importlib.machinery.SourceFileLoader("ls_db_tune", tuner_path)
        spec = importlib.util.spec_from_loader("ls_db_tune", loader)
        ls_db_tune = importlib.util.module_from_spec(spec)
        loader.exec_module(ls_db_tune)

        self.assertTrue(hasattr(ls_db_tune, "apply_optimizations"))
        self.assertEqual(ls_db_tune.apply_optimizations, ls_db_tune.apply_tuning_profile)

        ideal = {
            "innodb_buffer_pool_size": "8792M",
            "innodb_buffer_pool_instances": 4,
            "innodb_log_file_size": "1024M",
            "innodb_io_capacity": 2000,
            "innodb_io_capacity_max": 4000,
            "innodb_read_io_threads": 4,
            "innodb_write_io_threads": 4,
            "innodb_flush_neighbors": 0,
            "sort_buffer_size": "4M",
            "join_buffer_size": "4M",
            "read_rnd_buffer_size": "2M",
            "aria_pagecache_buffer_size": "256M",
            "aria_sort_buffer_size": "32M",
            "table_open_cache": 4096,
            "table_open_cache_instances": 4,
            "max_connections": 500,
            "transaction_isolation": "READ-COMMITTED"
        }

        class MockCollector:
            cli_cmd = "/usr/bin/mariadb"
            executed = []
            def query(self, sql: str):
                self.executed.append(sql)
                return [["1"]]

        collector = MockCollector()
        with tempfile.TemporaryDirectory() as tmp_dir:
            res = ls_db_tune.apply_optimizations(
                ideal,
                conf_dir=tmp_dir,
                collector=collector,
                current_vars={"table_open_cache_instances": "3"},
                show_log=False
            )
            self.assertTrue(res)

            set_globals = [q for q in collector.executed if q.startswith("SET GLOBAL")]
            self.assertTrue(any("innodb_buffer_pool_size" in q for q in set_globals))
            self.assertTrue(any("table_open_cache" in q for q in set_globals))
            self.assertTrue(any("max_connections" in q for q in set_globals))

    def test_lsctl_db_optimize_passes_apply_and_optimize(self):
        """Verify lsctl db:optimize passes both --apply and --optimize to database tuner."""
        import subprocess
        lsctl_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "core", "bin", "lsctl"))
        res = subprocess.run(
            [lsctl_path, "db:optimize", "--dry-run", "--json", "--simulate-ram=4096", "--simulate-cores=4"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        self.assertEqual(res.returncode, 0, f"lsctl db:optimize failed: {res.stderr}")
        data = json.loads(res.stdout)
        self.assertIn("score", data)
        self.assertIn("ideal_tuning", data)


if __name__ == "__main__":
    unittest.main()

