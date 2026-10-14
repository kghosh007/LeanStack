#!/usr/bin/env bash
# ==============================================================================
# LeanStack Single-Command Bootstrap Installer
# Ultra-Lightweight, High-Density WordPress Control Plane for Ubuntu 22.04/24.04/26.04 (x86_64)
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IS_LOCAL_DEV=0

# Detect if running locally from cloned repo
if [ -f "${SCRIPT_DIR}/installer/tui.py" ]; then
    IS_LOCAL_DEV=1
    INSTALL_DIR="$SCRIPT_DIR"
else
    INSTALL_DIR="/opt/leanstack"
fi

DRY_RUN=0
for arg in "$@"; do
    if [ "$arg" == "--dry-run" ]; then
        DRY_RUN=1
    fi
done

# Root privileges check (bypassable only in explicit --dry-run)
if [ "$EUID" -ne 0 ] && [ "$DRY_RUN" -eq 0 ]; then
    echo "❌ Error: LeanStack must be installed with root privileges." >&2
    echo "Please execute: sudo bash $0 $*" >&2
    exit 1
fi

# Operating System Validation
if [ -f /etc/os-release ]; then
    . /etc/os-release
    if [ "$ID" != "ubuntu" ]; then
        echo "⚠️ Warning: LeanStack is optimized for Ubuntu. Detected: $NAME" >&2
        if [ "$DRY_RUN" -eq 0 ]; then
            echo "❌ Error: Unsupported Linux distribution." >&2
            exit 1
        fi
    fi
    if [ "$VERSION_ID" != "22.04" ] && [ "$VERSION_ID" != "24.04" ] && [ "$VERSION_ID" != "26.04" ] && [ "$DRY_RUN" -eq 0 ]; then
        echo "⚠️ Warning: LeanStack is validated on Ubuntu 22.04, 24.04, and 26.04 LTS. Detected: $VERSION_ID" >&2
    fi
fi

# Install minimal base packages if not in dry-run
if [ "$DRY_RUN" -eq 0 ] && [ "$EUID" -eq 0 ]; then
    export DEBIAN_FRONTEND=noninteractive
    echo "📦 Checking and installing minimal prerequisites..."
    apt-get update -qq
    apt-get install -y -qq python3 python3-minimal curl ca-certificates git sqlite3 >/dev/null
fi

# Clone or prepare payload directory if not in local dev mode
if [ "$IS_LOCAL_DEV" -eq 0 ] && [ "$DRY_RUN" -eq 0 ]; then
    mkdir -p "$INSTALL_DIR"
    if [ ! -d "${INSTALL_DIR}/.git" ]; then
        echo "⬇️ Fetching LeanStack repository..."
        git clone --depth 1 https://github.com/okio/leanstack.git "$INSTALL_DIR" 2>/dev/null || true
    fi
fi

# Launch the interactive Antigravity-style TUI
exec python3 "${INSTALL_DIR}/installer/tui.py" "$@"
