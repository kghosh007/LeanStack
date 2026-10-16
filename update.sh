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

# 2. Terminate any hung or looping background processes from previous corrupted installations
if [ "$DRY_RUN" -eq 0 ]; then
    echo -e "${CYAN}🧹 Clearing any hung watcher or gatekeeper processes...${NC}"
    if command -v systemctl &>/dev/null && [ -d "/run/systemd/system" ]; then
        systemctl stop ls-watcher.service cp-gatekeeper.service ls-gatekeeper.service 2>/dev/null || true
        systemctl reset-failed ls-watcher.service 2>/dev/null || true
    fi
    # Terminate any hung looping processes running stale recursive wrappers
    pkill -9 -f "(/usr/local/bin|/opt/leanstack/core/bin)/(ls-watcher|cp-watcher|ls-gatekeeper|cp-gatekeeper|lsctl|cpctl)" 2>/dev/null || true
fi

# 3. Deploy/Sync Control Plane Binaries & Templates directly to ensure freshest executables
if [ "$DRY_RUN" -eq 0 ] && [ -d "${INSTALL_DIR}/core/bin" ]; then
    mkdir -p /usr/local/bin /etc/lsctl/templates
    for b in "${INSTALL_DIR}/core/bin/"*; do
        if [ -f "$b" ]; then
            b_name=$(basename "$b")
            # Do not copy legacy wrappers as files to /usr/local/bin; they must strictly be symlinks
            case "$b_name" in
                cpctl|cp-*) continue ;;
            esac
            rm -f "/usr/local/bin/${b_name}"
            cp -f "$b" "/usr/local/bin/${b_name}"
            chmod 0755 "/usr/local/bin/${b_name}"
        fi
    done
    # Legacy compatibility links: safely unlink before creating fresh symlinks
    for leg in cpctl:lsctl cp-upgrade:ls-upgrade cp-gatekeeper:ls-gatekeeper \
               cp-nginx-linter:ls-nginx-linter cp-cron-queue:ls-cron-queue \
               cp-cf-sync:ls-cf-sync cp-watcher:ls-watcher cp-autoupdate:ls-autoupdate; do
        leg_name="${leg%%:*}"
        target_name="${leg##*:}"
        rm -f "/usr/local/bin/${leg_name}"
        ln -sf "$target_name" "/usr/local/bin/${leg_name}" 2>/dev/null || true
    done

    if [ -d "${INSTALL_DIR}/core/templates" ]; then
        cp -a "${INSTALL_DIR}/core/templates/"* /etc/lsctl/templates/ 2>/dev/null || true
    fi
    if [ -d "${INSTALL_DIR}/core/snippets" ] && [ -d "/etc/angie" ]; then
        mkdir -p /etc/angie/snippets
        cp -a "${INSTALL_DIR}/core/snippets/"*.conf /etc/angie/snippets/ 2>/dev/null || true
    fi
    if [ -d "${INSTALL_DIR}/systemd" ] && [ -d "/etc/systemd/system" ]; then
        for u in "${INSTALL_DIR}/systemd/"*.service "${INSTALL_DIR}/systemd/"*.timer; do
            [ -f "$u" ] || continue
            u_name=$(basename "$u")
            if [ "$u_name" == "cp-gatekeeper.service" ]; then
                continue
            fi
            rm -f "/etc/systemd/system/${u_name}"
            cp -f "$u" "/etc/systemd/system/${u_name}"
        done
        rm -f /etc/systemd/system/cp-gatekeeper.service
        ln -sf ls-gatekeeper.service /etc/systemd/system/cp-gatekeeper.service 2>/dev/null || true
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
