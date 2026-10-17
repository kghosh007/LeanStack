#!/usr/bin/env bash
# ==============================================================================
# LeanStack Base Dependencies & Mail Relay Installer
# ==============================================================================
set -euo pipefail

if [ "$EUID" -ne 0 ]; then
    echo "❌ Error: Must be executed as root." >&2
    exit 1
fi

echo ">>> [Phase 1: Dependencies] Installing essential dependencies and mail relay (msmtp)..."
export DEBIAN_FRONTEND=noninteractive

apt-get update -qq
apt-get install -y -qq \
    curl ca-certificates gnupg lsb-release sqlite3 git \
    msmtp msmtp-mta \
    zram-tools cpufrequtils htop iotop iftop net-tools >/dev/null 2>&1 || true

echo "✔ Base dependencies and msmtp relay confirmed."
