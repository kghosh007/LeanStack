#!/usr/bin/env bash
# ==============================================================================
# LeanStack Single-Command Upgrade & Fleet Migration Tool
# Host Target: https://leanstack.kuntalghosh.dev/update.sh
# Repository:  https://github.com/kghosh007/LeanStack
# ==============================================================================
set -euo pipefail

INSTALL_DIR="/opt/leanstack"
SCRIPT_DIR=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
fi

# Detect installation root whether run from root, site/, or piped
if [ -n "${SCRIPT_DIR}" ] && ([ -f "${SCRIPT_DIR}/core/bin/lsctl" ] || [ -f "${SCRIPT_DIR}/core/bin/cpctl" ]); then
    INSTALL_DIR="$SCRIPT_DIR"
elif [ -n "${SCRIPT_DIR}" ] && ([ -f "${SCRIPT_DIR}/../core/bin/lsctl" ] || [ -f "${SCRIPT_DIR}/../core/bin/cpctl" ]); then
    INSTALL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
elif [ -d "/opt/leanstack/core" ]; then
    INSTALL_DIR="/opt/leanstack"
fi

DRY_RUN=0

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

for arg in "$@"; do
    if [ "$arg" == "--dry-run" ]; then
        DRY_RUN=1
    fi
done

echo -e "${CYAN}${BOLD}"
echo "  ██╗     ███████╗ █████╗ ███╗   ██╗███████╗████████╗ █████╗  ██████╗██╗  ██╗"
echo "  ██║     ██╔════╝██╔══██╗████╗  ██║██╔════╝╚══██╔══╝██╔══██╗██╔════╝██║ ██╔╝"
echo "  ██║     █████╗  ███████║██╔██╗ ██║███████╗   ██║   ███████║██║     █████╔╝ "
echo "  ██║     ██╔══╝  ██╔══██║██║╚██╗██║╚════██║   ██║   ██╔══██║██║     ██╔═██╗ "
echo "  ███████╗███████╗██║  ██║██║ ╚████║███████║   ██║   ██║  ██║╚██████╗██║  ██╗"
echo "  ╚══════╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═══╝╚══════╝   ╚═╝   ╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝"
echo -e "${NC}"
echo -e "${GREEN}>>> LeanStack Autonomous Upgrade Engine${NC}"
echo "------------------------------------------------------------------------------"

# Root validation
if [ "$EUID" -ne 0 ] && [ "$DRY_RUN" -eq 0 ]; then
    echo -e "${RED}❌ Error: LeanStack upgrade requires root privileges.${NC}" >&2
    echo -e "   Please execute: ${BOLD}curl -fsSL https://leanstack.kuntalghosh.dev/update.sh | sudo bash${NC}" >&2
    exit 1
fi

# 1. Update Git Repository Payload if installed as git clone
if [ "$DRY_RUN" -eq 0 ] && [ -d "${INSTALL_DIR}/.git" ]; then
    echo -e "${CYAN}🔄 Synchronizing LeanStack repository in ${INSTALL_DIR}...${NC}"
    git -C "$INSTALL_DIR" fetch --tags origin 2>/dev/null || true
    git -C "$INSTALL_DIR" pull --ff-only 2>/dev/null || true
fi

# 2. Deploy/Sync Control Plane Binaries & Templates directly to ensure freshest executables
if [ "$DRY_RUN" -eq 0 ] && [ -d "${INSTALL_DIR}/core/bin" ]; then
    mkdir -p /usr/local/bin /etc/lsctl/templates
    for b in "${INSTALL_DIR}/core/bin/"*; do
        if [ -f "$b" ]; then
            b_name=$(basename "$b")
            cp -f "$b" "/usr/local/bin/${b_name}"
            chmod 0755 "/usr/local/bin/${b_name}"
        fi
    done
    # Legacy compatibility links
    ln -sf lsctl /usr/local/bin/cpctl 2>/dev/null || true
    ln -sf ls-upgrade /usr/local/bin/cp-upgrade 2>/dev/null || true
    ln -sf ls-gatekeeper /usr/local/bin/cp-gatekeeper 2>/dev/null || true
    ln -sf ls-cron-queue /usr/local/bin/cp-cron-queue 2>/dev/null || true
    ln -sf ls-cf-sync /usr/local/bin/cp-cf-sync 2>/dev/null || true
    ln -sf ls-watcher /usr/local/bin/cp-watcher 2>/dev/null || true
    ln -sf ls-autoupdate /usr/local/bin/cp-autoupdate 2>/dev/null || true

    if [ -d "${INSTALL_DIR}/core/templates" ]; then
        cp -a "${INSTALL_DIR}/core/templates/"* /etc/lsctl/templates/ 2>/dev/null || true
    fi
    if [ -d "${INSTALL_DIR}/systemd" ] && [ -d "/etc/systemd/system" ]; then
        cp -f "${INSTALL_DIR}/systemd/"*.service "${INSTALL_DIR}/systemd/"*.timer /etc/systemd/system/ 2>/dev/null || true
        systemctl daemon-reload 2>/dev/null || true
    fi
fi

# 3. Execute Master Upgrade Orchestrator with the latest core/bin/ls-upgrade
if [ -f "${INSTALL_DIR}/core/bin/ls-upgrade" ]; then
    echo -e "${GREEN}✔ Executing upgrade via ${INSTALL_DIR}/core/bin/ls-upgrade...${NC}"
    exec python3 "${INSTALL_DIR}/core/bin/ls-upgrade" "$@"
elif command -v lsctl >/dev/null 2>&1; then
    echo -e "${GREEN}✔ Executing upgrade via lsctl...${NC}"
    exec lsctl update "$@"
elif command -v cpctl >/dev/null 2>&1; then
    echo -e "${GREEN}✔ Executing upgrade via cpctl alias...${NC}"
    exec cpctl update "$@"
else
    echo -e "${RED}❌ Error: LeanStack does not appear to be installed on this host.${NC}" >&2
    echo -e "To install LeanStack, run:" >&2
    echo -e "  ${BOLD}curl -fsSL https://leanstack.kuntalghosh.dev/install.sh | sudo bash${NC}" >&2
    exit 1
fi
