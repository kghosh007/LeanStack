#!/usr/bin/env bash
# ==============================================================================
# LeanStack Phase 3: Database Tier (MariaDB High-QPS Engine & Dynamic Sizing)
# ==============================================================================
set -euo pipefail

if [ "$EUID" -ne 0 ]; then
    echo "❌ Error: Must be executed as root." >&2
    exit 1
fi

echo ">>> [Phase 3] Installing and configuring MariaDB Database Tier..."
export DEBIAN_FRONTEND=noninteractive

# Install MariaDB Server (Default: 12.3 LTS stable - 12.3.3)
TARGET_MARIADB_VER="${MARIADB_VERSION:-12.3.3}"
if [[ "$TARGET_MARIADB_VER" =~ ^([0-9]+\.[0-9]+) ]]; then
    MARIADB_SERIES="${BASH_REMATCH[1]}"
else
    MARIADB_SERIES="12.3"
fi

if ! command -v mariadb &>/dev/null || [ "${MARIADB_UPGRADE:-0}" == "1" ]; then
    echo ">>> [Phase 3] Configuring official MariaDB ${MARIADB_SERIES} repository via mariadb_repo_setup (Target: ${TARGET_MARIADB_VER})..."
    apt-get update -qq
    apt-get install -y -qq ca-certificates curl gnupg apt-transport-https >/dev/null 2>&1 || true

    # Clean up any stale or invalid manual keyrings/lists
    rm -f /etc/apt/keyrings/mariadb-keyring.pgp /etc/apt/sources.list.d/mariadb.list /etc/apt/sources.list.d/mariadb.list.save

    # Run official MariaDB Corporation repository setup tool
    curl -LsS https://r.mariadb.com/downloads/mariadb_repo_setup | bash -s -- --skip-maxscale --mariadb-server-version="mariadb-${MARIADB_SERIES}"

    apt-get update -qq
    apt-get install -y -qq -o Dpkg::Options::="--force-confold" -o Dpkg::Options::="--force-confdef" mariadb-server mariadb-client mysqltuner >/dev/null 2>&1 || \
    apt-get install -y -qq mariadb-server mariadb-client mysqltuner >/dev/null 2>&1 || \
    apt-get install -y -qq mariadb-server mariadb-client >/dev/null
fi

# Dynamic Hardware Probing
RAM_TOTAL_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo 2>/dev/null || echo 2048)
[ -z "$RAM_TOTAL_MB" ] || [ "$RAM_TOTAL_MB" -le 0 ] && RAM_TOTAL_MB=2048
CPU_CORES=$(nproc 2>/dev/null || echo 1)

# Sizing Formulas
if [ "$RAM_TOTAL_MB" -le 2048 ]; then
    BP_MB=512
    BP_INST=1
    SORT_BUF="1M"
    JOIN_BUF="1M"
    READ_RND="512K"
    ARIA_PAGE="64M"
elif [ "$RAM_TOTAL_MB" -le 4096 ]; then
    BP_MB=$(( RAM_TOTAL_MB * 35 / 100 ))
    BP_INST=2
    SORT_BUF="2M"
    JOIN_BUF="2M"
    READ_RND="1M"
    ARIA_PAGE="128M"
elif [ "$RAM_TOTAL_MB" -le 8192 ]; then
    if [ "$RAM_TOTAL_MB" -ge 6000 ]; then
        BP_MB=2800
    else
        BP_MB=$(( RAM_TOTAL_MB * 40 / 100 ))
    fi
    BP_INST=2
    SORT_BUF="2M"
    JOIN_BUF="2M"
    READ_RND="1M"
    ARIA_PAGE="128M"
else
    BP_MB=$(( RAM_TOTAL_MB * 55 / 100 ))
    BP_INST=$(( BP_MB / 1024 ))
    [ "$BP_INST" -gt "$CPU_CORES" ] && BP_INST=$CPU_CORES
    [ "$BP_INST" -lt 1 ] && BP_INST=1
    SORT_BUF="4M"
    JOIN_BUF="4M"
    READ_RND="2M"
    ARIA_PAGE="256M"
fi

TABLE_INST=$CPU_CORES
[ "$TABLE_INST" -gt 16 ] && TABLE_INST=16

LOG_MB=$(( BP_MB / 4 ))
[ "$LOG_MB" -gt 1024 ] && LOG_MB=1024

MAX_CONN=300
[ "$RAM_TOTAL_MB" -le 2048 ] && MAX_CONN=150
[ "$RAM_TOTAL_MB" -gt 8192 ] && MAX_CONN=500

# Dynamic Storage & I/O Capacity Probing
IS_NVME=0
IS_ROTATIONAL=0
ROOT_DEV=""
if [ -f /proc/mounts ]; then
    ROOT_DEV=$(awk '$2 == "/" {print $1}' /proc/mounts 2>/dev/null | xargs basename 2>/dev/null || true)
fi

if [[ "$ROOT_DEV" == *"nvme"* ]] || ls /dev/nvme* &>/dev/null; then
    IS_NVME=1
else
    BASE_ROOT_DEV=$(echo "$ROOT_DEV" | sed -E 's/p?[0-9]+$//')
    if [ -n "$BASE_ROOT_DEV" ] && [ -f "/sys/block/${BASE_ROOT_DEV}/queue/rotational" ]; then
        if [ "$(cat "/sys/block/${BASE_ROOT_DEV}/queue/rotational" 2>/dev/null)" == "1" ]; then
            IS_ROTATIONAL=1
        fi
    else
        for block_path in /sys/block/*/queue/rotational; do
            [ -f "$block_path" ] || continue
            dev=$(echo "$block_path" | cut -d '/' -f 4)
            case "$dev" in
                loop*|ram*) continue ;;
            esac
            rot=$(cat "$block_path" 2>/dev/null || echo "0")
            if [[ "$dev" == *"nvme"* ]]; then
                IS_NVME=1
                break
            elif [ "$rot" == "1" ]; then
                IS_ROTATIONAL=1
            fi
        done
    fi
fi

if [ "$IS_NVME" -eq 1 ]; then
    if [ "$CPU_CORES" -le 2 ]; then
        IO_CAPACITY=4000
    elif [ "$CPU_CORES" -le 8 ]; then
        IO_CAPACITY=8000
    else
        IO_CAPACITY=15000
    fi
    IO_CAPACITY_MAX=$(( IO_CAPACITY * 2 ))
    IO_THREADS=$CPU_CORES
    [ "$IO_THREADS" -gt 8 ] && IO_THREADS=8
    [ "$IO_THREADS" -lt 4 ] && IO_THREADS=4
    FLUSH_NEIGHBORS=0
elif [ "$IS_ROTATIONAL" -eq 0 ]; then
    # SATA SSD / Cloud SSD
    if [ "$CPU_CORES" -le 2 ]; then
        IO_CAPACITY=1000
    else
        IO_CAPACITY=2000
    fi
    IO_CAPACITY_MAX=$(( IO_CAPACITY * 2 ))
    IO_THREADS=$CPU_CORES
    [ "$IO_THREADS" -gt 4 ] && IO_THREADS=4
    [ "$IO_THREADS" -lt 2 ] && IO_THREADS=2
    FLUSH_NEIGHBORS=0
else
    # Rotational HDD
    IO_CAPACITY=200
    IO_CAPACITY_MAX=400
    IO_THREADS=2
    FLUSH_NEIGHBORS=1
fi

echo ">>> [Phase 3] MariaDB Buffer Pool: ${BP_MB}M (${BP_INST} inst), Sort: ${SORT_BUF}, IO: ${IO_CAPACITY}/${IO_CAPACITY_MAX} IOPS, Table Cache Inst: ${TABLE_INST}"

# Deploy the High-QPS Tuning Profile
mkdir -p /etc/mysql/mariadb.conf.d/
cat << EOF > /etc/mysql/mariadb.conf.d/99-leanstack-highqps.cnf
[mysqld]
# ==============================================================================
# LeanStack MariaDB High-QPS Tuning Profile
# Solves SELECT & UPDATE Bottlenecks (Eliminates L2 cache overflow & gap locks)
# ==============================================================================

# --- Security Hardening ---
bind-address                   = 127.0.0.1
local-infile                   = 0

# --- Connection & Thread Model ---
thread_handling                = one-thread-per-connection
thread_cache_size              = 128
max_connections                = ${MAX_CONN}
back_log                       = 512

# --- Eliminate Profiling, Binary Log & Query Cache Mutex Contention ---
performance_schema             = OFF
skip-log-bin
skip-name-resolve              = 1
query_cache_type               = 0
query_cache_size               = 0

# --- Transaction Concurrency & Gap Lock Elimination ---
# READ-COMMITTED eliminates next-key gap locks, accelerating concurrent UPDATEs & inventory checks
transaction_isolation          = READ-COMMITTED

# --- InnoDB Buffer Pool ---
innodb_buffer_pool_size        = ${BP_MB}M
innodb_buffer_pool_instances   = ${BP_INST}
innodb_buffer_pool_dump_at_shutdown = ON
innodb_buffer_pool_load_at_startup  = ON

# --- Redo Log & High-Throughput Transaction Writes ---
innodb_log_file_size           = ${LOG_MB}M
innodb_log_buffer_size         = 64M
innodb_flush_log_at_trx_commit = 2
# innodb_flush_method            = O_DIRECT
innodb_autoinc_lock_mode       = 2
innodb_adaptive_hash_index     = 1

# --- Storage & I/O Tuning (Hardware-Aware) ---
innodb_io_capacity             = ${IO_CAPACITY}
innodb_io_capacity_max         = ${IO_CAPACITY_MAX}
innodb_read_io_threads         = ${IO_THREADS}
innodb_write_io_threads        = ${IO_THREADS}
innodb_flush_neighbors         = ${FLUSH_NEIGHBORS}

# --- In-Memory Sorting & Query Buffers ---
# Dynamically sized (1M-4M) to keep filesort in RAM and eliminate on-disk sort merges
sort_buffer_size               = ${SORT_BUF}
join_buffer_size               = ${JOIN_BUF}
read_buffer_size               = 512K
read_rnd_buffer_size           = ${READ_RND}

# --- Query Optimizer: Cost-Based with MRR Acceleration & Subquery Cache ---
optimizer_switch               = mrr=on,mrr_cost_based=on,subquery_cache=on,semijoin=on,extended_keys=on,index_condition_pushdown=on

# --- In-Memory Temporary Tables & Aria Page Cache ---
# Aria pagecache prevents internal temporary tables with TEXT/BLOB from disk thrashing
tmp_table_size                 = 64M
max_heap_table_size            = 64M
aria_pagecache_buffer_size     = ${ARIA_PAGE}
aria_sort_buffer_size          = 32M

# --- Multi-vCPU Table Cache Partitioning ---
# Splitting table cache eliminates mutex lock contention across CPU cores
table_open_cache               = 4096
table_open_cache_instances     = ${TABLE_INST}
table_definition_cache         = 2048

# --- Character Sets ---
character-set-server           = utf8mb4
collation-server               = utf8mb4_unicode_520_ci

[mariadb]
# Explicit MariaDB server section to enforce High-QPS buffer pool precedence over distribution defaults
innodb_buffer_pool_size        = ${BP_MB}M
innodb_buffer_pool_instances   = ${BP_INST}
innodb_buffer_pool_dump_at_shutdown = ON
innodb_buffer_pool_load_at_startup  = ON
transaction_isolation          = READ-COMMITTED
aria_pagecache_buffer_size     = ${ARIA_PAGE}
aria_sort_buffer_size          = 32M
sort_buffer_size               = ${SORT_BUF}
join_buffer_size               = ${JOIN_BUF}
read_buffer_size               = 512K
read_rnd_buffer_size           = ${READ_RND}
max_connections                = ${MAX_CONN}
table_open_cache               = 4096
table_open_cache_instances     = ${TABLE_INST}
table_definition_cache         = 2048
innodb_io_capacity             = ${IO_CAPACITY}
innodb_io_capacity_max         = ${IO_CAPACITY_MAX}
innodb_read_io_threads         = ${IO_THREADS}
innodb_write_io_threads        = ${IO_THREADS}
innodb_flush_neighbors         = ${FLUSH_NEIGHBORS}
EOF

systemctl restart mariadb

# Run mariadb-upgrade to ensure internal system tables and catalogs are up-to-date
mariadb-upgrade -u root 2>/dev/null || mysql_upgrade -u root 2>/dev/null || true

# Verify connectivity
mariadb -e "SELECT 1;" >/dev/null

echo "✅ [Phase 3] MariaDB Database Tier Configured & Running at High-QPS!"
