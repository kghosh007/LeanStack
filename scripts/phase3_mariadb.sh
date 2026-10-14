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

# Install MariaDB Server
if ! command -v mariadb &>/dev/null; then
    apt-get update -qq
    apt-get install -y -qq mariadb-server mariadb-client >/dev/null
fi

# Dynamic Hardware Probing
RAM_TOTAL_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
CPU_CORES=$(nproc)

# Sizing Formulas
if [ "$RAM_TOTAL_MB" -le 2048 ]; then
    BP_MB=512
    BP_INST=1
elif [ "$RAM_TOTAL_MB" -le 4096 ]; then
    BP_MB=$(( RAM_TOTAL_MB * 35 / 100 ))
    BP_INST=2
elif [ "$RAM_TOTAL_MB" -le 8192 ]; then
    BP_MB=2800
    BP_INST=2
else
    BP_MB=$(( RAM_TOTAL_MB * 55 / 100 ))
    BP_INST=$(( BP_MB / 1024 ))
    [ "$BP_INST" -gt "$CPU_CORES" ] && BP_INST=$CPU_CORES
    [ "$BP_INST" -lt 1 ] && BP_INST=1
fi

TABLE_INST=$CPU_CORES
[ "$TABLE_INST" -gt 16 ] && TABLE_INST=16

LOG_MB=$(( BP_MB / 4 ))
[ "$LOG_MB" -gt 1024 ] && LOG_MB=1024

SORT_BUF="256K"
[ "$CPU_CORES" -ge 8 ] && SORT_BUF="512K"

MAX_CONN=300
[ "$RAM_TOTAL_MB" -le 2048 ] && MAX_CONN=150
[ "$RAM_TOTAL_MB" -gt 8192 ] && MAX_CONN=500

echo ">>> [Phase 3] MariaDB Buffer Pool: ${BP_MB}M (${BP_INST} inst), Sort Buffer: ${SORT_BUF}, Table Cache Inst: ${TABLE_INST}"

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

# --- Eliminate Profiling & Binary Log Overhead ---
performance_schema             = OFF
skip-log-bin
skip-name-resolve              = 1

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
innodb_flush_method            = O_DIRECT
innodb_autoinc_lock_mode       = 2

# --- NVMe Storage & I/O Tuning ---
innodb_io_capacity             = 4000
innodb_io_capacity_max         = 8000
innodb_read_io_threads         = 4
innodb_write_io_threads        = 4

# --- Cache-Sized Per-Query Buffers (Fits inside CPU L2/L3 Cache) ---
# Small buffers prevent malloc() overhead on simple SELECT/UPDATE lookups
sort_buffer_size               = ${SORT_BUF}
join_buffer_size               = ${SORT_BUF}
read_buffer_size               = 128K
read_rnd_buffer_size           = 256K

# --- Query Optimizer: Cost-Based with MRR Acceleration ---
# Keeps MRR active but allows the optimizer to use direct index point lookups
optimizer_switch               = 'mrr=on,mrr_cost_based=on'

# --- In-Memory Temporary Tables ---
tmp_table_size                 = 64M
max_heap_table_size            = 64M

# --- Multi-vCPU Table Cache Partitioning ---
# Splitting table cache eliminates mutex lock contention across CPU cores
table_open_cache               = 4096
table_open_cache_instances     = ${TABLE_INST}
table_definition_cache         = 2048

# --- Character Sets ---
character-set-server           = utf8mb4
collation-server               = utf8mb4_unicode_520_ci
EOF

systemctl restart mariadb

# Verify connectivity
mariadb -e "SELECT 1;" >/dev/null

echo "✅ [Phase 3] MariaDB Database Tier Configured & Running at High-QPS!"
