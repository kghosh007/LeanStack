#!/usr/bin/env bash
# ==============================================================================
# LeanStack Phase 1: Base OS Cleanup, THP Lockout & Hardware Kernel Tuning
# ==============================================================================
set -euo pipefail

if [ "$EUID" -ne 0 ]; then
    echo "❌ Error: Must be executed as root." >&2
    exit 1
fi

echo ">>> [Phase 1] Purging snapd and bloatware..."
export DEBIAN_FRONTEND=noninteractive
apt-get purge -y snapd modemmanager 2>/dev/null || true
apt-get autoremove -y --purge 2>/dev/null || true

# Retain and configure unattended-upgrades for automated OS security CVE patches
if command -v unattended-upgrades &>/dev/null || apt-get install -y -qq unattended-upgrades >/dev/null 2>&1; then
    mkdir -p /etc/apt/apt.conf.d
    cat << 'EOF' > /etc/apt/apt.conf.d/50unattended-upgrades
Unattended-Upgrade::Allowed-Origins {
    "${distro_id}:${distro_codename}-security";
};
Unattended-Upgrade::Package-Blacklist {
};
Unattended-Upgrade::Automatic-Reboot "false";
EOF
    cat << 'EOF' > /etc/apt/apt.conf.d/20auto-upgrades
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
fi

# APT Pinning: permanently lock out snapd from ever re-installing
mkdir -p /etc/apt/preferences.d
cat << 'EOF' > /etc/apt/preferences.d/nosnap.pref
Package: snapd
Pin: release *
Pin-Priority: -10
EOF

# Permanently Disable Transparent Huge Pages (THP)
echo ">>> [Phase 1] Disabling Transparent Huge Pages (THP)..."
cat << 'EOF' > /etc/systemd/system/disable-thp.service
[Unit]
Description=Disable Transparent Huge Pages (THP) for MariaDB & Valkey Performance
DefaultDependencies=no
After=sysinit.target local-fs.target
Before=mongod.service mariadb.service mysql.service valkey.service

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'echo never > /sys/kernel/mm/transparent_hugepage/enabled && echo never > /sys/kernel/mm/transparent_hugepage/defrag'

[Install]
WantedBy=basic.target
EOF

systemctl daemon-reload
systemctl enable --now disable-thp.service || true

# Dynamic Hardware Probing
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RAM_TOTAL_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
CPU_CORES=$(nproc)

echo ">>> [Phase 1] Probed: ${CPU_CORES} vCPUs, ${RAM_TOTAL_MB} MB RAM"

# Kernel Sysctl Network & Memory Tuning
echo ">>> [Phase 1] Applying high-throughput sysctl parameters..."
cat << EOF > /etc/sysctl.d/99-leanstack.conf
# File & Socket Limits
fs.file-max = 2097152
fs.inotify.max_user_watches = 524288
fs.inotify.max_user_instances = 1024

# Network Backlog & Fast Connection Recycling
net.core.somaxconn = 65535
net.core.netdev_max_backlog = 16384
net.ipv4.tcp_max_syn_backlog = 8192
net.ipv4.tcp_fin_timeout = 15
net.ipv4.tcp_tw_reuse = 1
net.ipv4.ip_local_port_range = 1024 65535

# TCP Fast Open (3 = Client & Server enabled)
net.ipv4.tcp_fastopen = 3

# Buffer memory scaling for 10Gbps / Cloud VPS networks
net.core.rmem_default = 262144
net.core.rmem_max = 16777216
net.core.wmem_default = 262144
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216

# TCP Congestion Control: BBR
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr

# Memory & I/O management
vm.swappiness = 10
vm.dirty_ratio = 10
vm.dirty_background_ratio = 5
vm.vfs_cache_pressure = 50
vm.overcommit_memory = 1
EOF

sysctl --system >/dev/null 2>&1 || true

# Open File Limits
cat << 'EOF' > /etc/security/limits.d/99-leanstack.conf
* soft nofile 65535
* hard nofile 65535
root soft nofile 65535
root hard nofile 65535
www-data soft nofile 65535
www-data hard nofile 65535
EOF

# Install Utilities & ZRAM
echo ">>> [Phase 1] Installing core performance tools & ZRAM..."
apt-get install -y -qq zram-tools cpufrequtils htop iotop iftop net-tools >/dev/null 2>&1 || true

# Configure ZRAM (50% of RAM, zstd compression)
cat << 'EOF' > /etc/default/zramswap
ALGO=zstd
PERCENT=50
PRIORITY=100
EOF

systemctl restart zramswap 2>/dev/null || true

# Fallback 2GB Swapfile if none exists
if [ ! -f /swapfile ] && [ "$(swapon --show | wc -l)" -le 1 ]; then
    echo ">>> [Phase 1] Creating 2GB emergency swap safety file..."
    fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048
    chmod 600 /swapfile
    mkswap /swapfile >/dev/null
    swapon /swapfile || true
    grep -q "/swapfile" /etc/fstab || echo "/swapfile none swap sw 0 0" >> /etc/fstab
fi

# Cap Systemd Journals (prevent SSD exhaustion)
mkdir -p /etc/systemd/journald.conf.d
cat << 'EOF' > /etc/systemd/journald.conf.d/99-limit.conf
[Journal]
SystemMaxUse=100M
RuntimeMaxUse=50M
EOF
systemctl restart systemd-journald 2>/dev/null || true

# CPU Governor: Performance
for cpu in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
    [ -f "$cpu" ] && echo "performance" > "$cpu" 2>/dev/null || true
done

echo "✅ [Phase 1] Base OS Cleanup, THP Lockout & Sysctl Tuning Complete!"
