#!/usr/bin/env python3
"""
Unit Tests for LeanStack Hardware Probing & Tuning Engine
Verifies deterministic mathematical scaling across various VPS hardware tiers.
"""

import unittest
import os
import sys
import json
import subprocess

# Add installer directory to module path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "installer")))

from probe import HardwareProbe, TuningCalculator, format_summary_card

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

        # Host budget uses 128 MB per worker and never drops below 2.
        self.assertGreaterEqual(php["pm_max_children"], 2)
        self.assertEqual(php["host_budget_children"], php["pm_max_children"])
        self.assertEqual(php["pm_max_children"], max(2, php["php_available_ram_mb"] // 128))

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

        self.assertEqual(php["pm_max_children"], max(2, php["php_available_ram_mb"] // 128))
        self.assertEqual(php["host_budget_children"], php["pm_max_children"])
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

    def test_card_and_document_share_worker_count(self):
        """The printed card and to_document() name the same pm_max_children."""
        probe = HardwareProbe(sim_ram_mb=2048, sim_cores=2)
        calc = TuningCalculator(probe.probe_all())
        doc = calc.to_document()
        card = format_summary_card(doc)
        self.assertEqual(doc, calc.generate_full_profile())
        self.assertIn(f"{doc['php']['pm_max_children']} max workers", card)
        self.assertEqual(doc["php"]["host_budget_children"], doc["php"]["pm_max_children"])

    def test_provision_dry_run_lists_one_php(self):
        """A 2048 MB dry-run requests one PHP version and writes nothing."""
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        proc = subprocess.run(
            [sys.executable, "-m", "installer.provision", "--dry-run", "--php=8.3",
             "--simulate-ram=2048", "--simulate-cores=2"],
            cwd=root, capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("php8.3", proc.stdout)
        self.assertNotIn("php8.2", proc.stdout)
        self.assertNotIn("php8.4", proc.stdout)
        again = subprocess.run(
            [sys.executable, "-m", "installer.provision", "--dry-run", "--php=8.3", "--php=8.4",
             "--simulate-ram=2048", "--simulate-cores=2"],
            cwd=root, capture_output=True, text=True,
        )
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(again.stdout.count("php8.3"), 1)
        self.assertEqual(again.stdout.count("php8.4"), 1)
        self.assertNotIn("php8.2", again.stdout)
        self.assertEqual(proc.stdout, subprocess.run(
            [sys.executable, "-m", "installer.provision", "--dry-run", "--php=8.3",
             "--simulate-ram=2048", "--simulate-cores=2"],
            cwd=root, capture_output=True, text=True,
        ).stdout)

    def test_provision_writes_profile_jit_under_root(self):
        import tempfile
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run(
                [sys.executable, "-m", "installer.provision", "--php=8.3",
                 "--simulate-ram=2048", "--simulate-cores=2", "--simulate-avx2=0",
                 "--root", tmp],
                cwd=root, capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            ini = os.path.join(tmp, "etc/php/8.3/fpm/conf.d/99-leanstack-opcache.ini")
            self.assertTrue(os.path.isfile(ini))
            with open(ini, encoding="utf-8") as handle:
                body = handle.read()
            self.assertIn("opcache.jit = disable", body)
            self.assertFalse(os.path.exists(os.path.join(tmp, "etc/php/8.2")))

    def test_rendered_stack_contains_platform_directives(self):
        from provision import render_files
        doc = self.get_profile_for(2048, 2)
        files = render_files(doc, ["8.3"])
        blob = "\n".join(files.values())
        names = "\n".join(files)
        for needle in (
            "http2 on;",
            "quic default_server reuseport",
            "unixsocket /run/valkey/valkey.sock",
            "\nport 0\n",
            "transaction_isolation          = READ-COMMITTED",
            "mrr_cost_based=on",
            "table_open_cache_instances",
            "prime256v1",
            "ECDHE-ECDSA-AES128-GCM-SHA256",
            "session.use_strict_mode = 1",
            "session.cookie_httponly = 1",
            "session.cookie_secure = 1",
            "session.cookie_samesite = Lax",
            "max_execution_time = 300",
            "[mariadb]",
            "innodb_flush_log_at_trx_commit = 2",
        ):
            self.assertIn(needle, blob)
        self.assertIn("whitelists.yaml", names)
        self.assertIn("etc/mysql/mariadb.conf.d/99-leanstack-highqps.cnf", names)
        self.assertIn("etc/mysql/conf.d/99-leanstack-highqps.cnf", names)
        self.assertIn(str(doc["angie"]["worker_connections"]), files["etc/angie/angie.conf"])
        self.assertIn(doc["valkey"]["maxmemory"], files["etc/valkey/valkey.conf"])
        self.assertIn(f"opcache.jit = {doc['php']['opcache_jit']}", files["etc/php/8.3/fpm/conf.d/99-leanstack-opcache.ini"])
        with open(os.path.join(os.path.dirname(__file__), "..", "installer", "provision.py"), encoding="utf-8") as handle:
            source = handle.read()
        for needle in (
            "angie-module-cache-purge",
            "ngx_http_cache_purge_module.so",
            "os.remove(purge_conf)",
            "grub-editenv",
            "recordfail",
            "grub2-common.service",
            "ssl_ecdh_curve x25519:prime256v1:secp384r1;",
        ):
            self.assertIn(needle, source)

    def test_cpu_flags_are_stable_across_probes(self):
        a = HardwareProbe(sim_ram_mb=4096, sim_cores=4).probe_all()["cpu"]["flags"]
        b = HardwareProbe(sim_ram_mb=4096, sim_cores=4).probe_all()["cpu"]["flags"]
        self.assertEqual(a, b)
        self.assertEqual(a, sorted(a))

    def test_jit_disable_when_avx2_sse_and_neon_are_off(self):
        probe = HardwareProbe(sim_ram_mb=4096, sim_cores=4)
        hw = probe.probe_all()
        hw["cpu"]["features"]["avx2"] = False
        hw["cpu"]["features"]["sse4_2"] = False
        hw["cpu"]["features"]["neon"] = False
        php = TuningCalculator(hw).to_document()["php"]
        self.assertEqual(php["opcache_jit"], "disable")
        self.assertEqual(php["opcache_jit_buffer_size"], "0M")

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

            # Verify innodb_buffer_pool_instances is purged to prevent MariaDB 12 deprecation warnings
            self.assertNotIn("innodb_buffer_pool_instances", content)
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

        # Zero recommendations when optimal parameters and MariaDB table cache instances are active
        self.assertEqual(len(report["recommendations"]), 0)
        self.assertEqual(report["score"], 100)
        self.assertEqual(report["ideal_tuning"]["table_open_cache_instances"], 3)
        table_inst_check = next((c for c in report["checks"] if c["name"] == "Table Cache Instances"), None)
        self.assertIsNotNone(table_inst_check)
        self.assertEqual(table_inst_check["status"], "PASS")
        self.assertIn("3 instances", table_inst_check["value"])

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

    def test_render_report_visual_width_alignment(self):
        """Verify that render_report produces pixel-perfect aligned rectangular borders (74 chars total width)."""
        import importlib.machinery
        import importlib.util
        import re
        tuner_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "core", "bin", "ls-db-tune"))
        loader = importlib.machinery.SourceFileLoader("ls_db_tune", tuner_path)
        spec = importlib.util.spec_from_loader("ls_db_tune", loader)
        ls_db_tune = importlib.util.module_from_spec(spec)
        loader.exec_module(ls_db_tune)

        hw = {"ram_mb": 15986, "cores": 4, "is_nvme": False, "is_rotational": False, "disk_type": "SATA SSD"}
        mock_status = {
            "Uptime": "56",
            "Innodb_buffer_pool_read_requests": "4100",
            "Innodb_buffer_pool_reads": "2301",
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
            "table_open_cache_instances": "3",
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
        report = analyzer.render_report(analyzer.analyze())
        lines = report.strip().splitlines()
        for idx, line in enumerate(lines):
            # Strip ANSI escape sequences
            vis_line = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', line)
            self.assertEqual(len(vis_line), 74, f"Line {idx+1} visual width is {len(vis_line)} (expected 74): '{vis_line}'")

    def test_no_duplicate_buffer_pool_recommendations(self):
        """Verify that undersized buffer pool creates exactly one increase recommendation, and optimal sizing never recommends increase."""
        import importlib.machinery
        import importlib.util
        tuner_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "core", "bin", "ls-db-tune"))
        loader = importlib.machinery.SourceFileLoader("ls_db_tune", tuner_path)
        spec = importlib.util.spec_from_loader("ls_db_tune", loader)
        ls_db_tune = importlib.util.module_from_spec(spec)
        loader.exec_module(ls_db_tune)

        hw = {"ram_mb": 15986, "cores": 4, "is_nvme": True, "is_rotational": False, "disk_type": "NVMe SSD"}
        # Case 1: Undersized buffer pool on warmed up server
        undersized_status = {
            "Uptime": "100000",
            "Innodb_buffer_pool_read_requests": "50000",
            "Innodb_buffer_pool_reads": "10000",  # Low hit rate (80%)
            "Sort_merge_passes": "0",
            "Created_tmp_disk_tables": "0",
            "Created_tmp_tables": "10",
            "Open_tables": "50",
            "Opened_tables": "60",
            "Threads_created": "2",
            "Connections": "100"
        }
        undersized_vars = {
            "version": "12.3.3-MariaDB",
            "innodb_buffer_pool_size": "2048M",  # Way below optimal 8792M
            "transaction_isolation": "READ-COMMITTED",
            "sort_buffer_size": "4M",
            "table_open_cache": "4096",
            "table_open_cache_instances": "4",
            "innodb_io_capacity": "8000"
        }
        analyzer = ls_db_tune.DatabaseTuningAnalyzer(
            hardware=hw,
            is_live=True,
            status=undersized_status,
            variables=undersized_vars,
            fragmented_tables=[]
        )
        report = analyzer.analyze()
        bp_recs = [r for r in report["recommendations"] if "innodb_buffer_pool_size" in r]
        self.assertEqual(len(bp_recs), 1, f"Expected exactly 1 buffer pool recommendation, found: {bp_recs}")

    def test_table_open_cache_instances_zero_triggers_tune(self):
        """Verify that 0 or disabled table_open_cache_instances flags as TUNE and recommends setting it."""
        import importlib.machinery
        import importlib.util
        tuner_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "core", "bin", "ls-db-tune"))
        loader = importlib.machinery.SourceFileLoader("ls_db_tune", tuner_path)
        spec = importlib.util.spec_from_loader("ls_db_tune", loader)
        ls_db_tune = importlib.util.module_from_spec(spec)
        loader.exec_module(ls_db_tune)

        hw = {"ram_mb": 8192, "cores": 4, "is_nvme": False, "is_rotational": False, "disk_type": "SATA SSD"}
        mock_status = {"Uptime": "100000", "Open_tables": "50", "Opened_tables": "60"}
        mock_vars = {
            "version": "12.3.3-MariaDB",
            "table_open_cache": "4096",
            "table_open_cache_instances": "0",
            "innodb_buffer_pool_size": "2800M",
            "transaction_isolation": "READ-COMMITTED",
            "sort_buffer_size": "2M",
            "innodb_io_capacity": "2000"
        }
        analyzer = ls_db_tune.DatabaseTuningAnalyzer(
            hardware=hw,
            is_live=True,
            status=mock_status,
            variables=mock_vars,
            fragmented_tables=[]
        )
        report = analyzer.analyze()
        check = next((c for c in report["checks"] if c["name"] == "Table Cache Instances"), None)
        self.assertIsNotNone(check)
        self.assertEqual(check["status"], "TUNE")
        self.assertTrue(any("table_open_cache_instances" in r for r in report["recommendations"]))

    def test_apply_optimizations_no_static_restart_for_mariadb_managed_instances(self):
        """Verify apply_optimizations does not add restart reasons when table_open_cache_instances is already active (e.g. 3 on 4 vCPUs)."""
        import tempfile
        import importlib.machinery
        import importlib.util
        tuner_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "core", "bin", "ls-db-tune"))
        loader = importlib.machinery.SourceFileLoader("ls_db_tune", tuner_path)
        spec = importlib.util.spec_from_loader("ls_db_tune", loader)
        ls_db_tune = importlib.util.module_from_spec(spec)
        loader.exec_module(ls_db_tune)

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

        current = {
            "table_open_cache_instances": "3",
            "innodb_log_file_size": "1073741824",
            "innodb_read_io_threads": "4",
            "innodb_write_io_threads": "4",
            "aria_pagecache_buffer_size": "268435456",
            "performance_schema": "OFF",
            "query_cache_type": "0"
        }

        class MockCollector:
            cli_cmd = "/usr/bin/mariadb"
            def query(self, sql: str):
                return [["1"]]

        with tempfile.TemporaryDirectory() as tmp_dir:
            calls = []
            orig_run = ls_db_tune.subprocess.run
            orig_geteuid = getattr(ls_db_tune.os, "geteuid", None)
            def fake_run(cmd, *a, **kw):
                calls.append(cmd)
                class Ret:
                    returncode = 0
                return Ret()

            ls_db_tune.subprocess.run = fake_run
            ls_db_tune.os.geteuid = lambda: 0
            try:
                res = ls_db_tune.apply_optimizations(
                    ideal=ideal,
                    conf_dir=tmp_dir,
                    collector=MockCollector(),
                    current_vars=current,
                    show_log=False
                )
                self.assertTrue(res)
                restart_cmds = [c for c in calls if "restart" in c]
                self.assertEqual(len(restart_cmds), 0, f"Expected zero restarts, got: {restart_cmds}")
                reload_cmds = [c for c in calls if "reload" in c]
                self.assertEqual(len(reload_cmds), 1, f"Expected reload command, got: {calls}")
            finally:
                ls_db_tune.subprocess.run = orig_run
                if orig_geteuid:
                    ls_db_tune.os.geteuid = orig_geteuid

    def test_wp_autoload_analyzer_thresholds(self):
        """Verify WPAutoloadAnalyzer correctly classifies autoload health into optimal (<800KB), warning (800-1200KB), and critical (>1200KB)."""
        import importlib.machinery
        import importlib.util
        tuner_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "core", "bin", "ls-db-tune"))
        loader = importlib.machinery.SourceFileLoader("ls_db_tune", tuner_path)
        spec = importlib.util.spec_from_loader("ls_db_tune", loader)
        ls_db_tune = importlib.util.module_from_spec(spec)
        loader.exec_module(ls_db_tune)

        mock_optimal = [{
            "schema": "tenant_site1",
            "table": "wp_options",
            "autoload_bytes": 450 * 1024, # 450 KB < 800 KB
            "autoload_count": 350,
            "total_bytes": 2048 * 1024,
            "total_count": 1200,
            "top_options": [{"option_name": "active_plugins", "bytes": 12000}]
        }]
        analyzer_opt = ls_db_tune.WPAutoloadAnalyzer(mock_data=mock_optimal)
        res_opt = analyzer_opt.analyze()
        self.assertEqual(len(res_opt), 1)
        self.assertEqual(res_opt[0]["health"], "optimal")
        self.assertIn("OPTIMAL", res_opt[0]["health_label"])
        report_opt = analyzer_opt.render_report(res_opt)
        self.assertIn("OPTIMAL", report_opt)

        mock_warning = [{
            "schema": "tenant_site2",
            "table": "wp_options",
            "autoload_bytes": 950 * 1024, # 950 KB (800-1200 KB)
            "autoload_count": 800,
            "total_bytes": 4096 * 1024,
            "total_count": 3000,
            "top_options": [{"option_name": "woocommerce_cart", "bytes": 85000}]
        }]
        analyzer_warn = ls_db_tune.WPAutoloadAnalyzer(mock_data=mock_warning)
        res_warn = analyzer_warn.analyze()
        self.assertEqual(res_warn[0]["health"], "warning")
        self.assertIn("WARNING", res_warn[0]["health_label"])
        report_warn = analyzer_warn.render_report(res_warn)
        self.assertIn("WARNING", report_warn)

        mock_critical = [{
            "schema": "tenant_site3",
            "table": "wp_options",
            "autoload_bytes": 1500 * 1024, # 1.5 MB > 1200 KB
            "autoload_count": 1500,
            "total_bytes": 10240 * 1024,
            "total_count": 6500,
            "top_options": [{"option_name": "heavy_unserialized_blob", "bytes": 600000}]
        }]
        analyzer_crit = ls_db_tune.WPAutoloadAnalyzer(mock_data=mock_critical)
        res_crit = analyzer_crit.analyze()
        self.assertEqual(res_crit[0]["health"], "critical")
        self.assertIn("CRITICAL", res_crit[0]["health_label"])
        report_crit = analyzer_crit.render_report(res_crit)
        self.assertIn("CRITICAL", report_crit)

    def test_wp_autoload_cli_execution(self):
        """Verify ls-db-tune --wp-autoload and --wp-autoload --json execute cleanly without error."""
        tuner_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "core", "bin", "ls-db-tune"))
        res = subprocess.run([sys.executable, tuner_path, "--wp-autoload"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        self.assertIn("WORDPRESS AUTOLOAD OPTIONS HEALTH & BLOAT AUDITOR", res.stdout)

    def test_innodb_flush_log_at_trx_commit_audit_and_apply(self):
        """Verify ls-db-tune detects and penalizes flush_log_at_trx_commit=1 and applies=2 live."""
        import importlib.machinery
        import importlib.util
        tuner_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "core", "bin", "ls-db-tune"))
        loader = importlib.machinery.SourceFileLoader("ls_db_tune_test", tuner_path)
        spec = importlib.util.spec_from_loader("ls_db_tune_test", loader)
        ls_db_tune = importlib.util.module_from_spec(spec)
        loader.exec_module(ls_db_tune)

        hw = {"ram_mb": 4096, "cores": 4, "is_nvme": True, "is_rotational": False, "disk_type": "NVMe SSD"}
        mock_status = {"Uptime": "86400", "Innodb_buffer_pool_read_requests": "10000", "Innodb_buffer_pool_reads": "10"}
        mock_vars = {
            "version": "12.3.3-MariaDB",
            "innodb_buffer_pool_size": "1433M",
            "transaction_isolation": "READ-COMMITTED",
            "innodb_flush_log_at_trx_commit": "1",  # Sync disk fsync bottleneck
            "table_open_cache": "4096",
            "table_open_cache_instances": "4",
            "query_cache_type": "0",
            "performance_schema": "OFF",
        }

        analyzer = ls_db_tune.DatabaseTuningAnalyzer(
            hardware=hw,
            is_live=True,
            status=mock_status,
            variables=mock_vars,
            fragmented_tables=[]
        )
        report = analyzer.analyze()

        flush_check = next((c for c in report["checks"] if c["name"] == "Transaction Commit Flushing"), None)
        self.assertIsNotNone(flush_check)
        self.assertEqual(flush_check["status"], "WARN")
        self.assertIn("flush_log_at_trx_commit = 1", flush_check["value"])
        self.assertTrue(any("innodb_flush_log_at_trx_commit = 2" in r for r in report["recommendations"]))
        self.assertLess(report["score"], 100)

    def test_cron_queue_and_valkey_resilience(self):
        """Verify ls-cron-queue registers shutdown telemetry, defines WP_REDIS_GRACEFUL, and traps hook errors."""
        cron_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "core", "bin", "ls-cron-queue"))
        with open(cron_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("register_shutdown_function", content)
        self.assertIn("WP_REDIS_GRACEFUL", content)
        self.assertIn("try {", content)
        self.assertIn("catch (\\Throwable", content)
        self.assertIn("LS_TELEMETRY:", content)

    def test_valkey_watcher_noauth_handling(self):
        """Verify ls-watcher treats NOAUTH as a healthy, running Valkey instance without triggering false restarts."""
        watcher_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "core", "bin", "ls-watcher"))
        with open(watcher_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn('[ "$ping_res" != "PONG" ] && [[ ! "$ping_res" =~ NOAUTH ]]', content)
        self.assertIn("groupadd -f tenants", content)
        self.assertIn("groupadd -f valkey", content)

    def test_installer_phase7_and_provision_php_c_extensions(self):
        """Verify phase 7 enables canonical ls-gatekeeper with force, and provision installs full PHP C extensions."""
        tui_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "installer", "tui.py"))
        with open(tui_path, "r", encoding="utf-8") as f:
            tui_content = f.read()
        self.assertIn('["systemctl", "enable", "--force", "--now", "cp-cron.timer", "cp-cf-sync.timer", "ls-gatekeeper.service"', tui_content)

        provision_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "installer", "provision.py"))
        with open(provision_path, "r", encoding="utf-8") as f:
            prov_content = f.read()
        for ext in ["redis", "igbinary", "apcu", "imagick", "gd", "intl", "bcmath", "soap"]:
            self.assertIn(f"php{{ver}}-{ext}", prov_content)

        from provision import _php_runtime_ini
        cli_ini = _php_runtime_ini(is_cli=True)
        fpm_ini = _php_runtime_ini(is_cli=False)
        self.assertNotIn("proc_open", cli_ini)
        self.assertNotIn("popen", cli_ini)
        self.assertIn("proc_open", fpm_ini)
        self.assertIn("popen", fpm_ini)
        self.assertIn("apc.enabled = 1", fpm_ini)
        self.assertIn("apc.shm_size = 64M", fpm_ini)
        self.assertIn("apc.enable_cli = 0", cli_ini)

    def test_apcu_store_on_miss_and_query_monitor_bypass(self):
        """Verify LeanStackAPCu only stores alloptions on cache miss and guards cron status invalidation to once per request."""
        apcu_tpl = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "core", "templates", "leanstack-apcu.php.tpl"))
        with open(apcu_tpl, "r", encoding="utf-8") as f:
            apcu_content = f.read()
        self.assertIn("private $cron_checked = false;", apcu_content)
        self.assertIn("private $loaded_from_apcu = false;", apcu_content)
        self.assertIn("if ( $this->loaded_from_apcu ) {", apcu_content)

        wp_config_tpl = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "core", "templates", "wp-config.php.tpl"))
        with open(wp_config_tpl, "r", encoding="utf-8") as f:
            wpc_content = f.read()
        self.assertIn("define( 'QM_DISABLED', true );", wpc_content)
        self.assertIn("define( 'QM_DISABLE', true );", wpc_content)
        self.assertIn("define( 'WP_REDIS_GRACEFUL', true );", wpc_content)

        shield_tpl = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "core", "templates", "leanstack-shield.php.tpl"))
        with open(shield_tpl, "r", encoding="utf-8") as f:
            shield_content = f.read()
        self.assertIn("define( 'QM_DISABLED', true );", shield_content)
        self.assertIn("define( 'QM_DISABLE', true );", shield_content)
        self.assertIn("do_action( 'qm/cease' );", shield_content)


if __name__ == "__main__":
    unittest.main()


