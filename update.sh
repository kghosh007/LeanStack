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

# Locate upgrade executable
if command -v lsctl >/dev/null 2>&1; then
    echo -e "${GREEN}✔ Detected lsctl control plane.${NC}"
    exec lsctl update "$@"
elif command -v cpctl >/dev/null 2>&1; then
    echo -e "${GREEN}✔ Detected control plane (cpctl alias).${NC}"
    exec cpctl update "$@"
elif [ -f "${INSTALL_DIR}/core/bin/ls-upgrade" ]; then
    echo -e "${GREEN}✔ Executing directly via ${INSTALL_DIR}/core/bin/ls-upgrade...${NC}"
    exec python3 "${INSTALL_DIR}/core/bin/ls-upgrade" "$@"
elif [ -f "${INSTALL_DIR}/core/bin/cp-upgrade" ]; then
    echo -e "${GREEN}✔ Executing directly via ${INSTALL_DIR}/core/bin/cp-upgrade...${NC}"
    exec python3 "${INSTALL_DIR}/core/bin/cp-upgrade" "$@"
else
    echo -e "${RED}❌ Error: LeanStack does not appear to be installed on this host.${NC}" >&2
    echo -e "To install LeanStack, run:" >&2
    echo -e "  ${BOLD}curl -fsSL https://leanstack.kuntalghosh.dev/install.sh | sudo bash${NC}" >&2
    exit 1
fi
