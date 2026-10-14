#!/usr/bin/env bash
# ==============================================================================
# LeanStack Phase 2: Hardware SIMD In-Memory Store (Valkey via Unix Socket)
# ==============================================================================
set -euo pipefail

if [ "$EUID" -ne 0 ]; then
    echo "❌ Error: Must be executed as root." >&2
    exit 1
fi

echo ">>> [Phase 2] Installing Valkey In-Memory Object Store..."
export DEBIAN_FRONTEND=noninteractive

# Try official/snapless PPA or package, or compile from source
if ! command -v valkey-server &>/dev/null && ! command -v redis-server &>/dev/null; then
    # Try apt installation first
    apt-get update -qq
    apt-get install -y -qq build-essential pkg-config libjemalloc-dev tcl >/dev/null 2>&1 || true

    # Check if valkey package is available
    if apt-cache show valkey-server &>/dev/null; then
        apt-get install -y -qq valkey-server valkey-tools
    else
        echo ">>> [Phase 2] Compiling Valkey 8.0 LTS with jemalloc from source..."
        VALKEY_VER="8.0.2"
        TMP_DIR=$(mktemp -d)
        cd "$TMP_DIR"
        curl -fsSL "https://github.com/valkey-io/valkey/archive/refs/tags/8.0.2.tar.gz" -o valkey.tar.gz 2>/dev/null || \
        curl -fsSL "https://github.com/valkey-io/valkey/archive/refs/tags/8.0.1.tar.gz" -o valkey.tar.gz
        tar -xzf valkey.tar.gz
        cd valkey-*
        make USE_JEMALLOC=yes -j"$(nproc)"
        make install
        cd /
        rm -rf "$TMP_DIR"
    fi
fi

# User & Directory Setup
groupadd -f tenants
groupadd -f valkey
id -u valkey &>/dev/null || useradd -r -s /bin/false -g valkey -G tenants valkey

mkdir -p /etc/valkey /var/lib/valkey /run/valkey /var/log/valkey
chown -R valkey:valkey /var/lib/valkey /var/log/valkey
chown valkey:tenants /run/valkey
chmod 770 /run/valkey

# Dynamically Scale Valkey Memory (10% of total RAM, min 128MB, capped at 2048MB)
RAM_TOTAL_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
VALKEY_MEM_MB=$(( RAM_TOTAL_MB * 10 / 100 ))
[ "$VALKEY_MEM_MB" -lt 128 ] && VALKEY_MEM_MB=128
[ "$VALKEY_MEM_MB" -gt 2048 ] && VALKEY_MEM_MB=2048

echo ">>> [Phase 2] Valkey allocated: ${VALKEY_MEM_MB} MB (~10% RAM) on Unix Domain Socket"

cat << EOF > /etc/valkey/valkey.conf
# ==============================================================================
# LeanStack Valkey High-Performance Unix Socket Configuration
# ==============================================================================
# Disable TCP port completely (Zero network latency, Zero network attack surface)
port 0

# Unix Domain Socket configuration
unixsocket /run/valkey/valkey.sock
unixsocketperm 770

daemonize no
supervised systemd
pidfile /run/valkey/valkey.pid
loglevel notice
logfile /var/log/valkey/valkey.log
databases 128

# Native Valkey 8 ACL Security & Command Isolation
aclfile /etc/valkey/users.acl

# Disable server-wide destructive commands
rename-command FLUSHALL ""

# High-Performance In-Memory Settings
maxmemory ${VALKEY_MEM_MB}mb
maxmemory-policy allkeys-lru

# Disable RDB snapshots to prevent disk I/O stalls on high-traffic WordPress
save ""
stop-writes-on-bgsave-error no
rdbcompression no

# Append Only Mode disabled (pure volatile cache)
appendonly no

# Memory allocator optimizations
jemalloc-bg-thread yes
activedefrag yes
active-defrag-ignore-bytes 100mb
active-defrag-threshold-lower 10
active-defrag-threshold-upper 30

# Latency optimizations
tcp-backlog 511
timeout 0
tcp-keepalive 0
EOF

# Initialize empty ACL file if not present
touch /etc/valkey/users.acl
chown valkey:valkey /etc/valkey/valkey.conf /etc/valkey/users.acl
chmod 640 /etc/valkey/valkey.conf /etc/valkey/users.acl

# Deploy Systemd Unit
cat << 'EOF' > /etc/systemd/system/valkey.service
[Unit]
Description=Valkey High-Performance In-Memory Data Store
After=network.target disable-thp.service

[Service]
Type=notify
User=valkey
Group=valkey
SupplementaryGroups=tenants
ExecStart=/usr/local/bin/valkey-server /etc/valkey/valkey.conf
ExecStop=/bin/kill -s TERM $MAINPID
Restart=always
RestartSec=3
LimitNOFILE=65535
RuntimeDirectory=valkey
RuntimeDirectoryMode=0770

[Install]
WantedBy=multi-user.target
EOF

# If packaged valkey is used, link paths
if [ -f /usr/bin/valkey-server ] && [ ! -f /usr/local/bin/valkey-server ]; then
    ln -sf /usr/bin/valkey-server /usr/local/bin/valkey-server
    ln -sf /usr/bin/valkey-cli /usr/local/bin/valkey-cli
fi

systemctl daemon-reload
systemctl enable --now valkey.service || true

echo "✅ [Phase 2] Valkey In-Memory Cache Configured & Running via Unix Socket!"
