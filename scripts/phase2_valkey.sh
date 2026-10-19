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
usermod -aG valkey,tenants www-data 2>/dev/null || true

mkdir -p /etc/valkey /var/lib/valkey /run/valkey /var/log/valkey
chown -R valkey:valkey /var/lib/valkey /var/log/valkey
chown valkey:tenants /run/valkey
chmod 775 /run/valkey

# Dynamically Scale Valkey Memory (10% of total RAM, min 128MB, capped at 2048MB)
RAM_TOTAL_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo 2>/dev/null || echo 2048)
[ -z "$RAM_TOTAL_MB" ] || [ "$RAM_TOTAL_MB" -le 0 ] && RAM_TOTAL_MB=2048
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

# Latency optimizations
tcp-backlog 511
timeout 0
tcp-keepalive 0
EOF

# Initialize ACL file with default user if not present
if [ ! -f /etc/valkey/users.acl ] || [ ! -s /etc/valkey/users.acl ]; then
    echo "user default on nopass ~* &* +@all" > /etc/valkey/users.acl
fi
chown valkey:valkey /etc/valkey/valkey.conf /etc/valkey/users.acl
chmod 640 /etc/valkey/valkey.conf /etc/valkey/users.acl

# Locate Valkey binaries and ensure symlinks exist in both /usr/bin and /usr/local/bin
VALKEY_BIN="$(command -v valkey-server 2>/dev/null || true)"
[ -z "$VALKEY_BIN" ] && [ -x "/usr/bin/valkey-server" ] && VALKEY_BIN="/usr/bin/valkey-server"
[ -z "$VALKEY_BIN" ] && [ -x "/usr/local/bin/valkey-server" ] && VALKEY_BIN="/usr/local/bin/valkey-server"

VALKEY_CLI="$(command -v valkey-cli 2>/dev/null || true)"
[ -z "$VALKEY_CLI" ] && [ -x "/usr/bin/valkey-cli" ] && VALKEY_CLI="/usr/bin/valkey-cli"
[ -z "$VALKEY_CLI" ] && [ -x "/usr/local/bin/valkey-cli" ] && VALKEY_CLI="/usr/local/bin/valkey-cli"

if [ -n "$VALKEY_BIN" ]; then
    [ ! -f /usr/local/bin/valkey-server ] && ln -sf "$VALKEY_BIN" /usr/local/bin/valkey-server
    [ ! -f /usr/bin/valkey-server ] && ln -sf "$VALKEY_BIN" /usr/bin/valkey-server
fi
if [ -n "$VALKEY_CLI" ]; then
    [ ! -f /usr/local/bin/valkey-cli ] && ln -sf "$VALKEY_CLI" /usr/local/bin/valkey-cli
    [ ! -f /usr/bin/valkey-cli ] && ln -sf "$VALKEY_CLI" /usr/bin/valkey-cli
fi

# Stop existing services and remove unit symlinks to prevent 'linked unit file' conflicts
systemctl stop valkey valkey-server redis-server redis 2>/dev/null || true
systemctl disable valkey valkey-server 2>/dev/null || true
rm -f /etc/systemd/system/valkey.service /etc/systemd/system/valkey-server.service

# Deploy Systemd Unit
cat << EOF > /etc/systemd/system/valkey.service
[Unit]
Description=Valkey High-Performance In-Memory Data Store
After=network.target disable-thp.service

[Service]
Type=notify
User=valkey
Group=valkey
SupplementaryGroups=tenants
ExecStart=${VALKEY_BIN:-/usr/bin/valkey-server} /etc/valkey/valkey.conf
ExecStop=/bin/kill -s TERM \$MAINPID
Restart=always
RestartSec=3
LimitNOFILE=65535
RuntimeDirectory=valkey
RuntimeDirectoryMode=0775
UMask=007

[Install]
WantedBy=multi-user.target
Alias=valkey-server.service
EOF

# Ensure valkey-server.service points to valkey.service to prevent alias conflicts
ln -sf /etc/systemd/system/valkey.service /etc/systemd/system/valkey-server.service

systemctl daemon-reload
systemctl unmask valkey valkey-server 2>/dev/null || true
systemctl enable valkey.service 2>/dev/null || true
systemctl restart valkey.service

echo "✅ [Phase 2] Valkey In-Memory Cache Configured & Running via Unix Socket!"
