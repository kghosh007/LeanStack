#!/usr/bin/env bash
# ==============================================================================
# LeanStack Single-Command Bootstrap Installer
# Ultra-Lightweight, High-Density WordPress Control Plane
# Host Target: https://leanstack.kuntalghosh.dev/install.sh
# Repository:  https://github.com/kghosh007/LeanStack
# Supported OS: Ubuntu 22.04 LTS, 24.04 LTS & 26.04 LTS (x86_64)
# ==============================================================================
set -euo pipefail

LEANSTACK_VERSION="1.2.0"
DEFAULT_REPO_URL="${LEANSTACK_REPO_URL:-https://github.com/kghosh007/LeanStack.git}"

# Auto-detect local development clone vs default production target
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "${SCRIPT_DIR}/installer/tui.py" ]; then
    INSTALL_DIR="$SCRIPT_DIR"
elif [ -f "${SCRIPT_DIR}/../installer/tui.py" ]; then
    INSTALL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
elif [ -d "/opt/leanstack/installer" ]; then
    INSTALL_DIR="/opt/leanstack"
else
    INSTALL_DIR="/opt/leanstack"
fi

# Load centralized version if repository clone exists
if [ -f "${INSTALL_DIR}/core/version.json" ]; then
    LEANSTACK_VERSION="$(python3 -c "import json; print(json.load(open('${INSTALL_DIR}/core/version.json')).get('version', '1.2.0'))" 2>/dev/null || echo "1.2.0")"
fi

DRY_RUN=0

# ANSI Color Codes
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
echo -e "${GREEN}>>> LeanStack Bootstrapper v${LEANSTACK_VERSION}${NC}"
echo -e "${CYAN}    Engineered for Ubuntu 22.04, 24.04 & 26.04 LTS (<15MB RAM Idle Footprint)${NC}"
echo "------------------------------------------------------------------------------"

# 1. Root Privileges Check
if [ "$EUID" -ne 0 ] && [ "$DRY_RUN" -eq 0 ]; then
    echo -e "${RED}❌ Error: LeanStack must be installed with root privileges.${NC}" >&2
    echo -e "   Please re-run as root: ${BOLD}curl -fsSL https://leanstack.kuntalghosh.dev/install.sh | sudo bash${NC}" >&2
    exit 1
fi

# 2. Operating System Validation
if [ -f /etc/os-release ]; then
    . /etc/os-release
    if [ "$ID" != "ubuntu" ]; then
        echo -e "${YELLOW}⚠️ Warning: LeanStack is optimized strictly for Ubuntu. Detected: $NAME ($ID)${NC}" >&2
        if [ "$DRY_RUN" -eq 0 ]; then
            echo -e "${RED}❌ Error: Unsupported Linux distribution.${NC}" >&2
            exit 1
        fi
    fi
    if [ "$VERSION_ID" != "22.04" ] && [ "$VERSION_ID" != "24.04" ] && [ "$VERSION_ID" != "26.04" ]; then
        echo -e "${YELLOW}⚠️ Warning: LeanStack is validated on Ubuntu 22.04, 24.04, and 26.04 LTS. Detected: $VERSION_ID${NC}" >&2
    else
        echo -e "${GREEN}✔ Validated Operating System: Ubuntu ${VERSION_ID} LTS${NC}"
    fi
fi

# 3. Prerequisites Installation
if [ "$DRY_RUN" -eq 0 ] && [ "$EUID" -eq 0 ]; then
    export DEBIAN_FRONTEND=noninteractive
    echo -e "${CYAN}📦 Inspecting minimal prerequisites (python3, curl, git, sqlite3)...${NC}"
    apt-get update -qq
    apt-get install -y -qq python3 python3-minimal curl ca-certificates git sqlite3 >/dev/null
    echo -e "${GREEN}✔ Base prerequisites confirmed.${NC}"
fi

# 4. Fetch or Update Repository Payload
if [ "$DRY_RUN" -eq 0 ]; then
    mkdir -p "$INSTALL_DIR"
    if [ -d "${INSTALL_DIR}/.git" ]; then
        echo -e "${CYAN}🔄 Updating existing LeanStack payload in ${INSTALL_DIR}...${NC}"
        git -C "$INSTALL_DIR" pull --ff-only 2>/dev/null || true
    else
        echo -e "${CYAN}⬇️ Fetching LeanStack repository into ${INSTALL_DIR}...${NC}"
        if ! git clone --depth 1 "$DEFAULT_REPO_URL" "$INSTALL_DIR" 2>/dev/null; then
            echo -e "${YELLOW}⚠️ Notice: Public git clone did not complete.${NC}"
            if [ ! -f "${INSTALL_DIR}/installer/tui.py" ]; then
                echo -e "${RED}❌ Unable to download LeanStack payload.${NC}"
                echo -e "If using a private repository, please ensure an SSH deploy key or PAT is active, or run:"
                echo -e "  git clone <your-repo> ${INSTALL_DIR}"
                echo -e "  cd ${INSTALL_DIR} && sudo ./install.sh"
                exit 1
            fi
        fi
    fi
fi

# 5. Launch Interactive Antigravity-Style TUI Engine
if [ -f "${INSTALL_DIR}/installer/tui.py" ]; then
    echo -e "${GREEN}🚀 Initializing LeanStack Hardware Prober & Installer TUI...${NC}\n"
    exec python3 "${INSTALL_DIR}/installer/tui.py" "$@"
else
    echo -e "${RED}❌ Fatal: Installer entrypoint (${INSTALL_DIR}/installer/tui.py) not found.${NC}" >&2
    exit 1
fi
