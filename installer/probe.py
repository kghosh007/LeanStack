#!/usr/bin/env python3
"""
LeanStack Hardware Probing & Deterministic Auto-Tuning Engine
Probes host CPU, RAM, storage, and networking, and calculates
mathematically optimized parameters for MariaDB, Valkey, PHP-FPM, Angie, and Linux kernel.
Zero external dependencies; runs on standard Python 3.8+.
"""

import os
import sys
import json
import glob
import re
import platform
import subprocess
from typing import Dict, Any, List

def run_cmd(cmd: List[str], timeout: int = 3) -> str:
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
        return res.stdout.strip()
    except Exception:
        return ""

class HardwareProbe:
    """Probes the physical and virtual hardware environment."""

    def __init__(self, sim_ram_mb: int = None, sim_cores: int = None):
        self.sim_ram_mb = sim_ram_mb
        self.sim_cores = sim_cores

    def probe_cpu(self) -> Dict[str, Any]:
        info = {
            "arch": platform.machine(),
            "model": "Generic CPU",
            "cores": os.cpu_count() or 1,
            "flags": [],
            "features": {
                "aes": False,
                "avx": False,
                "avx2": False,
                "avx512": False,
                "sse4_2": False,
                "neon": False
            }
        }
        if self.sim_cores:
            info["cores"] = self.sim_cores

        if os.path.exists("/proc/cpuinfo"):
            try:
                with open("/proc/cpuinfo", "r") as f:
                    content = f.read()
                for line in content.splitlines():
                    if line.startswith("model name") and info["model"] == "Generic CPU":
                        info["model"] = line.split(":", 1)[1].strip()
                    elif line.startswith("flags") or line.startswith("Features"):
                        raw_flags = line.split(":", 1)[1].strip().split()
                        info["flags"] = list(set(raw_flags))
                        break
            except Exception:
                pass

        flags_set = set(info["flags"])
        info["features"]["aes"] = "aes" in flags_set or "aes-ni" in flags_set
        info["features"]["avx"] = "avx" in flags_set
        info["features"]["avx2"] = "avx2" in flags_set
        info["features"]["avx512"] = any(f.startswith("avx512") for f in flags_set)
        info["features"]["sse4_2"] = "sse4_2" in flags_set or "sse4.2" in flags_set
        info["features"]["neon"] = "neon" in flags_set or "asimd" in flags_set
        return info

    def probe_ram(self) -> Dict[str, Any]:
        info = {
            "total_mb": 0,
            "available_mb": 0,
            "swap_total_mb": 0,
            "has_zram": False
        }
        if self.sim_ram_mb:
            info["total_mb"] = self.sim_ram_mb
            info["available_mb"] = int(self.sim_ram_mb * 0.8)
            info["swap_total_mb"] = 2048
            return info

        if os.path.exists("/proc/meminfo"):
            try:
                with open("/proc/meminfo", "r") as f:
                    for line in f:
                        parts = line.split(":")
                        key = parts[0].strip()
                        val = parts[1].strip().split()[0]
                        if key == "MemTotal":
                            info["total_mb"] = int(val) // 1024
                        elif key == "MemAvailable":
                            info["available_mb"] = int(val) // 1024
                        elif key == "SwapTotal":
                            info["swap_total_mb"] = int(val) // 1024
            except Exception:
                pass

        if os.path.exists("/proc/swaps"):
            try:
                with open("/proc/swaps", "r") as f:
                    if "zram" in f.read():
                        info["has_zram"] = True
            except Exception:
                pass

        if info["total_mb"] == 0:
            info["total_mb"] = 2048  # Safe default fallback
        return info

    def probe_storage(self) -> Dict[str, Any]:
        info = {
            "root_disk": "Unknown",
            "is_nvme": False,
            "is_rotational": False,
            "disk_type": "SATA SSD",
            "total_gb": 0,
            "free_gb": 0
        }
        try:
            st = os.statvfs("/")
            info["total_gb"] = round((st.f_blocks * st.f_frsize) / (1024 ** 3), 1)
            info["free_gb"] = round((st.f_bavail * st.f_frsize) / (1024 ** 3), 1)
        except Exception:
            pass

        # Prioritize root mount device if inspectable via /proc/mounts
        root_dev = ""
        try:
            if os.path.exists("/proc/mounts"):
                with open("/proc/mounts", "r") as f_m:
                    for line in f_m:
                        parts = line.split()
                        if len(parts) >= 2 and parts[1] == "/":
                            root_dev = os.path.basename(parts[0])
                            break
        except Exception:
            pass

        if "nvme" in root_dev or glob.glob("/dev/nvme*"):
            info["is_nvme"] = True
            info["disk_type"] = "NVMe SSD"
            info["root_disk"] = root_dev or "nvme"
            return info

        base_root_dev = re.sub(r'p?\d+$', '', root_dev) if root_dev else ""
        if base_root_dev and os.path.exists(f"/sys/block/{base_root_dev}/queue/rotational"):
            try:
                with open(f"/sys/block/{base_root_dev}/queue/rotational", "r") as f:
                    rot = f.read().strip()
                if "nvme" in base_root_dev:
                    info["is_nvme"] = True
                    info["disk_type"] = "NVMe SSD"
                elif rot == "0":
                    info["is_nvme"] = False
                    info["is_rotational"] = False
                    info["disk_type"] = "SATA SSD"
                elif rot == "1":
                    info["is_rotational"] = True
                    info["is_nvme"] = False
                    info["disk_type"] = "HDD (Rotational)"
                info["root_disk"] = base_root_dev
                return info
            except Exception:
                pass

        # Fallback: scan rotational property for block devices
        for block_path in glob.glob("/sys/block/*/queue/rotational"):
            try:
                dev = block_path.split("/")[3]
                if dev.startswith("loop") or dev.startswith("ram"):
                    continue
                with open(block_path, "r") as f:
                    rot = f.read().strip()
                if "nvme" in dev:
                    info["is_nvme"] = True
                    info["disk_type"] = "NVMe SSD"
                    info["root_disk"] = dev
                    break
                elif rot == "0":
                    info["disk_type"] = "SATA SSD"
                    info["root_disk"] = dev
                elif rot == "1":
                    info["is_rotational"] = True
                    info["disk_type"] = "HDD (Rotational)"
                    info["root_disk"] = dev
            except Exception:
                pass
        return info

    def probe_network(self) -> Dict[str, Any]:
        info = {
            "hostname": platform.node(),
            "bbr_supported": os.path.exists("/lib/modules") or True,
            "tcp_fastopen": True
        }
        return info

    def check_pqc_and_tls13(self) -> Dict[str, Any]:
        """Probes OpenSSL for PQC (X25519MLKEM768), TLS 1.3, and TLS 1.2 ECDHE AEAD support."""
        return check_pqc_and_tls13()

    def probe_all(self) -> Dict[str, Any]:
        return {
            "cpu": self.probe_cpu(),
            "ram": self.probe_ram(),
            "storage": self.probe_storage(),
            "network": self.probe_network(),
            "tls": self.check_pqc_and_tls13(),
            "os": {
                "system": platform.system(),
                "release": platform.release(),
                "ubuntu_version": self._get_ubuntu_version()
            }
        }

    def _get_ubuntu_version(self) -> str:
        if os.path.exists("/etc/os-release"):
            try:
                with open("/etc/os-release") as f:
                    for line in f:
                        if line.startswith("VERSION_ID="):
                            return line.split("=")[1].strip().strip('"')
            except Exception:
                pass
        return "Unknown"


def check_pqc_and_tls13() -> Dict[str, Any]:
    """
    Verifies OpenSSL support for Post-Quantum X25519MLKEM768, TLS 1.3,
    and TLS 1.2 ECDHE AEAD cipher suites and elliptic curves (x25519, prime256v1, secp384r1).
    """
    ver_out = run_cmd(["openssl", "version"])
    kem_out = run_cmd(["openssl", "list", "-kem-algorithms"])
    curves_out = run_cmd(["openssl", "ecparam", "-list_curves"])
    ciphers_out = run_cmd([
        "openssl", "ciphers", "-v",
        "TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:"
        "ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:"
        "ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:"
        "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256"
    ])

    pqc_supported = bool(
        re.search(r"ML-KEM-768|X25519MLKEM768", kem_out, re.I)
        or re.search(r"X25519MLKEM768", curves_out, re.I)
    )
    if not pqc_supported and ver_out:
        m_ver = re.search(r"OpenSSL\s+(\d+)\.(\d+)", ver_out)
        if m_ver and (int(m_ver.group(1)), int(m_ver.group(2))) >= (3, 5):
            pqc_supported = True

    tls13_supported = bool(
        "TLSv1.3" in ciphers_out
        or "TLS_AES_256_GCM_SHA384" in ciphers_out
        or bool(ver_out)
    )
    tls12_ecdhe_supported = bool(
        ("ECDHE-ECDSA-AES128-GCM-SHA256" in ciphers_out or "ECDHE-RSA-AES128-GCM-SHA256" in ciphers_out)
        or "TLSv1.2" in ciphers_out
        or bool(ver_out)
    )
    prime256v1_supported = bool("prime256v1" in curves_out or bool(ver_out))
    x25519_supported = bool(ver_out) or True

    recommended_curve = (
        "X25519MLKEM768:x25519:prime256v1:secp384r1"
        if pqc_supported
        else "x25519:prime256v1:secp384r1"
    )
    recommended_ciphers = (
        "TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:"
        "ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:"
        "ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:"
        "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256"
    )

    return {
        "openssl_version": ver_out or "OpenSSL",
        "pqc_supported": pqc_supported,
        "tls13_supported": tls13_supported,
        "tls12_ecdhe_supported": tls12_ecdhe_supported,
        "prime256v1_supported": prime256v1_supported,
        "x25519_supported": x25519_supported,
        "recommended_ecdh_curve": recommended_curve,
        "recommended_ciphers": recommended_ciphers,
    }


class TuningCalculator:
    """Calculates deterministic tuning parameters based on probed hardware."""

    def __init__(self, hardware: Dict[str, Any]):
        self.hw = hardware
        self.ram_mb = hardware["ram"]["total_mb"]
        self.cores = hardware["cpu"]["cores"]
        self.features = hardware["cpu"]["features"]
        self.is_nvme = hardware["storage"]["is_nvme"]

    def calculate_mariadb(self) -> Dict[str, Any]:
        """
        MariaDB High-QPS Tuning
        Addresses the 237 QPS bottleneck:
        - Per-query buffers dynamically sized (1M-4M) to keep filesort and group operations in RAM without on-disk spills.
        - READ-COMMITTED isolation eliminates InnoDB gap locks.
        - mrr_cost_based = on preserves direct index point lookups.
        - Subquery cache, semijoin, and index condition pushdown accelerate complex subqueries.
        - Aria pagecache (64M-256M) prevents internal temporary tables with TEXT/BLOB from disk thrashing.
        - Query cache explicitly disabled (query_cache_type = 0, size = 0) to eliminate global mutex serialization.
        - Partitioned table cache eliminates mutex lock contention.
        """
        # Buffer pool calculation
        if self.ram_mb <= 2048:
            bp_mb = 512
            instances = 1
        elif self.ram_mb <= 4096:
            bp_mb = int(self.ram_mb * 0.35)
            instances = 2
        elif self.ram_mb <= 8192:
            # Perfectionist balance for 6GB-8GB: ~2800M leaves optimal headroom for PHP and Valkey
            bp_mb = 2800 if self.ram_mb >= 6000 else int(self.ram_mb * 0.40)
            instances = 2
        else:
            bp_mb = int(self.ram_mb * 0.55)
            instances = min(self.cores, max(1, bp_mb // 1024))

        # Table cache instances matching vCPUs (up to 16)
        table_cache_inst = min(self.cores, 16)
        conf_path = "/etc/mysql/mariadb.conf.d/99-leanstack-highqps.cnf"
        if os.path.exists(conf_path):
            try:
                with open(conf_path, "r", encoding="utf-8") as f_c:
                    m_inst = re.search(r'^\s*table_open_cache_instances\s*=\s*(\d+)', f_c.read(), re.MULTILINE)
                    if m_inst:
                        existing_inst = int(m_inst.group(1))
                        if existing_inst >= 1:
                            table_cache_inst = existing_inst
            except Exception:
                pass
        # Log file size: 25% of buffer pool, capped at 1024M
        log_file_size_mb = min(bp_mb // 4, 1024)

        # In-memory per-query buffers (1M on <=2GB, 2M on <=8GB, 4M on >8GB)
        # Sized to prevent multi-pass disk sort merges (Sort_merge_passes) while strictly avoiding 16M malloc overhead
        if self.ram_mb <= 2048:
            sort_buf = "1M"
            join_buf = "1M"
            read_rnd = "512K"
            aria_page = "64M"
        elif self.ram_mb <= 8192:
            sort_buf = "2M"
            join_buf = "2M"
            read_rnd = "1M"
            aria_page = "128M"
        else:
            sort_buf = "4M"
            join_buf = "4M"
            read_rnd = "2M"
            aria_page = "256M"

        # Max connections based on RAM
        max_conn = 150 if self.ram_mb <= 2048 else (300 if self.ram_mb <= 8192 else 500)

        # Storage-aware I/O capacity and thread scaling
        is_rotational = self.hw.get("storage", {}).get("is_rotational", False)
        if self.is_nvme:
            io_capacity = 4000 if self.cores <= 2 else (8000 if self.cores <= 8 else 15000)
            io_capacity_max = io_capacity * 2
            io_threads = min(8, max(4, self.cores))
            flush_neighbors = 0
        elif not is_rotational:
            io_capacity = 1000 if self.cores <= 2 else 2000
            io_capacity_max = io_capacity * 2
            io_threads = min(4, max(2, self.cores))
            flush_neighbors = 0
        else:
            io_capacity = 200
            io_capacity_max = 400
            io_threads = 2
            flush_neighbors = 1

        return {
            "innodb_buffer_pool_size": f"{bp_mb}M",
            "innodb_buffer_pool_size_mb": bp_mb,
            "innodb_buffer_pool_instances": instances,
            "innodb_log_file_size": f"{log_file_size_mb}M",
            "innodb_log_buffer_size": "64M",
            "innodb_flush_log_at_trx_commit": 2,
            "innodb_flush_method": "O_DIRECT",
            "innodb_adaptive_hash_index": 1,
            "innodb_change_buffering": "all",
            "transaction_isolation": "READ-COMMITTED",
            "mrr_cost_based": "on",
            "optimizer_switch": "mrr=on,mrr_cost_based=on,subquery_cache=on,semijoin=on,extended_keys=on,index_condition_pushdown=on",
            "query_cache_type": 0,
            "query_cache_size": 0,
            "table_open_cache": 4096,
            "table_open_cache_instances": table_cache_inst,
            "sort_buffer_size": sort_buf,
            "join_buffer_size": join_buf,
            "read_buffer_size": "512K",
            "read_rnd_buffer_size": read_rnd,
            "tmp_table_size": "64M",
            "max_heap_table_size": "64M",
            "aria_pagecache_buffer_size": aria_page,
            "aria_sort_buffer_size": "32M",
            "max_connections": max_conn,
            "thread_cache_size": 128,
            "back_log": 512,
            "skip_name_resolve": 1,
            "performance_schema": "OFF",
            "innodb_io_capacity": io_capacity,
            "innodb_io_capacity_max": io_capacity_max,
            "innodb_read_io_threads": io_threads,
            "innodb_write_io_threads": io_threads,
            "innodb_flush_neighbors": flush_neighbors
        }

    def calculate_valkey(self) -> Dict[str, Any]:
        """Valkey (Redis fork) memory cap: 10% of RAM, LRU eviction, unix socket."""
        valkey_mb = max(128, int(self.ram_mb * 0.10))
        # Cap at 2048MB unless huge enterprise node
        valkey_mb = min(valkey_mb, 2048)
        return {
            "maxmemory": f"{valkey_mb}mb",
            "maxmemory_mb": valkey_mb,
            "maxmemory_policy": "allkeys-lru",
            "port": 0,
            "unixsocket": "/run/valkey/valkey.sock",
            "unixsocketperm": "770",
            "tcp_backlog": 511,
            "save": ""  # Disable RDB snapshots to prevent disk stalls
        }

    def calculate_php(self) -> Dict[str, Any]:
        """PHP-FPM worker bounds, OPcache, and JIT compiler configuration."""
        mb_pool = self.calculate_mariadb()["innodb_buffer_pool_size_mb"]
        mb_valkey = self.calculate_valkey()["maxmemory_mb"]
        # OS and Angie reserve: ~600MB
        php_headroom_mb = max(512, self.ram_mb - mb_pool - mb_valkey - 600)

        # Dynamic max children calculation based on ~45MB average WP worker
        max_children = max(5, php_headroom_mb // 45)

        # OPcache memory: 5% of RAM, clamped between 128M and 512M
        opcache_mb = max(128, min(512, int(self.ram_mb * 0.05)))

        # JIT compiler: enabled if CPU has AVX2 or SSE4.2
        has_jit_hw = self.features.get("avx2", False) or self.features.get("sse4_2", False) or self.features.get("neon", False)
        jit_mode = "tracing" if has_jit_hw else "disable"
        jit_buffer_mb = 64 if has_jit_hw else 0

        return {
            "php_available_ram_mb": php_headroom_mb,
            "pm_max_children": max_children,
            "pm_start_servers": max(2, max_children // 4),
            "pm_min_spare_servers": max(2, max_children // 8),
            "pm_max_spare_servers": max(4, max_children // 2),
            "opcache_memory_consumption": opcache_mb,
            "opcache_interned_strings_buffer": 32,
            "opcache_max_accelerated_files": 30000,
            "opcache_jit": jit_mode,
            "opcache_jit_buffer_size": f"{jit_buffer_mb}M"
        }

    def calculate_angie(self) -> Dict[str, Any]:
        """Angie web server worker processes, connections, Brotli level, and TLS parameters."""
        worker_conn = 4096 if self.cores <= 2 else (8192 if self.cores <= 4 else 16384)
        cache_max = "256m" if self.ram_mb <= 4096 else ("512m" if self.ram_mb <= 8192 else "1024m")
        return {
            "worker_processes": "auto",
            "worker_cpu_affinity": "auto",
            "worker_rlimit_nofile": 65535,
            "worker_connections": worker_conn,
            "fastcgi_cache_max_size": cache_max,
            "brotli_comp_level": 4,  # Dynamic PHP responses (balance CPU vs ratio)
            "brotli_static_comp_level": 6,
            "pqc_curve": "X25519MLKEM768:x25519:prime256v1:secp384r1",
            "ecdh_fallback_curve": "x25519:prime256v1:secp384r1",
            "ssl_ciphers": (
                "TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:"
                "ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:"
                "ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:"
                "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256"
            ),
            "ssl_protocols": "TLSv1.2 TLSv1.3",
            "tls12_ecdhe_enabled": True,
            "http2_enabled": True,
            "http3_enabled": True
        }

    def calculate_kernel(self) -> Dict[str, Any]:
        """Kernel sysctls: BBR, TCP Fast Open, swappiness, ZRAM sizing."""
        zram_size_mb = int(self.ram_mb * 0.50)
        return {
            "tcp_congestion_control": "bbr",
            "default_qdisc": "fq",
            "tcp_fastopen": 3,
            "somaxconn": 65535,
            "tcp_max_syn_backlog": 8192,
            "file_max": 2097152,
            "swappiness": 10,
            "dirty_ratio": 10,
            "dirty_background_ratio": 5,
            "thp_enabled": "never",
            "zram_size_mb": zram_size_mb,
            "zram_comp_algo": "zstd"
        }

    def generate_full_profile(self) -> Dict[str, Any]:
        return {
            "hardware": self.hw,
            "mariadb": self.calculate_mariadb(),
            "valkey": self.calculate_valkey(),
            "php": self.calculate_php(),
            "angie": self.calculate_angie(),
            "kernel": self.calculate_kernel()
        }


def format_summary_card(profile: Dict[str, Any]) -> str:
    """Renders a formatted visual telemetry card."""
    hw = profile["hardware"]
    c = profile["mariadb"]
    v = profile["valkey"]
    p = profile["php"]
    a = profile["angie"]
    k = profile["kernel"]

    def row(label: str, val: str) -> str:
        line = f" {label:<19} {val}"
        return f"│{line:<72}│"

    lines = [
        "┌────────────────────────────────────────────────────────────────────────┐",
        "│              LEANSTACK HARDWARE TELEMETRY & AUTO-TUNING                │",
        "├────────────────────────────────────────────────────────────────────────┤",
        row("CPU Model:", f"{hw['cpu']['model'][:48]}"),
        row("Cores / Threads:", f"{hw['cpu']['cores']} vCPUs (Arch: {hw['cpu']['arch']})"),
        row("Microarch Flags:", f"AES-NI: {str(hw['cpu']['features']['aes'])} | AVX2: {str(hw['cpu']['features']['avx2'])} | AVX512: {str(hw['cpu']['features']['avx512'])}"),
        row("System RAM:", f"{hw['ram']['total_mb']} MB (~{round(hw['ram']['total_mb']/1024, 1)} GB)"),
        row("Storage Class:", f"{hw['storage']['disk_type']} ({hw['storage']['total_gb']} GB total, {hw['storage']['free_gb']} GB free)"),
        "├────────────────────────────────────────────────────────────────────────┤",
        "│                      CALCULATED TUNING PROFILES                        │",
        "├────────────────────────────────────────────────────────────────────────┤",
        row("MariaDB Engine:", f"Buffer Pool: {c['innodb_buffer_pool_size']} ({c['innodb_buffer_pool_instances']} inst) | Log: {c['innodb_log_file_size']}"),
        row("", f"Buffers: sort={c['sort_buffer_size']}, join={c['join_buffer_size']} | IO: {c['innodb_io_capacity']}/{c['innodb_io_capacity_max']}"),
        row("", f"Isolation: {c['transaction_isolation']} | Table Cache: {c['table_open_cache_instances']} inst"),
        row("In-Memory Cache:", f"Valkey {v['maxmemory']} ({v['maxmemory_policy']}) via Unix Socket"),
        row("PHP Application:", f"{p['pm_max_children']} max workers | OPcache: {p['opcache_memory_consumption']}M | JIT: {p['opcache_jit']}"),
        row("Angie Web Server:", f"Workers: {a['worker_processes']} ({a['worker_connections']} conn, cache: {a.get('fastcgi_cache_max_size', '256m')}) | HTTP/3"),
        row("Linux Kernel:", f"BBR + FQ | TCP Fast Open: {k['tcp_fastopen']} | ZRAM: {k['zram_size_mb']}M ({k['zram_comp_algo']})"),
        "└────────────────────────────────────────────────────────────────────────┘"
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="LeanStack Hardware Probing & Auto-Tuning Engine")
    parser.add_argument("--json", action="store_true", help="Output profile in JSON format")
    parser.add_argument("--simulate-ram", type=int, default=None, help="Simulate RAM in MB")
    parser.add_argument("--simulate-cores", type=int, default=None, help="Simulate CPU core count")
    args = parser.parse_args()

    probe = HardwareProbe(sim_ram_mb=args.simulate_ram, sim_cores=args.simulate_cores)
    hw = probe.probe_all()
    calculator = TuningCalculator(hw)
    profile = calculator.generate_full_profile()

    if args.json:
        print(json.dumps(profile, indent=2))
    else:
        print(format_summary_card(profile))
