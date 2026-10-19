#!/usr/bin/env bash
# ==============================================================================
# LeanStack Single-Command Bootstrap Installer
# Ultra-Lightweight, High-Density WordPress Control Plane
# Host Target: https://leanstack.kuntalghosh.dev/install.sh
# Repository:  https://github.com/kghosh007/LeanStack
# Supported OS: Ubuntu 22.04 LTS, 24.04 LTS & 26.04 LTS (x86_64)
# ==============================================================================
set -euo pipefail

LEANSTACK_VERSION="1.3.0"
DEFAULT_REPO_URL="${LEANSTACK_REPO_URL:-https://github.com/kghosh007/LeanStack.git}"

# Auto-detect local development clone vs default production target (pipe-safe)
INSTALL_DIR="/opt/leanstack"
SCRIPT_DIR=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
fi

if [ -n "${SCRIPT_DIR}" ] && [ -f "${SCRIPT_DIR}/installer/tui.py" ]; then
    INSTALL_DIR="$SCRIPT_DIR"
elif [ -n "${SCRIPT_DIR}" ] && [ -f "${SCRIPT_DIR}/../installer/tui.py" ]; then
    INSTALL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
elif [ -d "/opt/leanstack/installer" ]; then
    INSTALL_DIR="/opt/leanstack"
fi

# Load centralized version if repository clone exists
if [ -f "${INSTALL_DIR}/core/version.json" ] && command -v python3 >/dev/null 2>&1; then
    LEANSTACK_VERSION="$(python3 -c "import json; print(json.load(open('${INSTALL_DIR}/core/version.json')).get('version', '1.3.0'))" 2>/dev/null || echo "1.3.0")"
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

# 2b. Hardware Resource Probing & Telemetry Calculation
TOTAL_RAM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo 2>/dev/null || echo 2048)
[ -z "$TOTAL_RAM_MB" ] || [ "$TOTAL_RAM_MB" -le 0 ] && TOTAL_RAM_MB=2048
TOTAL_CORES=$(nproc 2>/dev/null || echo 1)
DISK_TYPE="SATA SSD"
ROOT_DEV=""
if [ -f /proc/mounts ]; then
    ROOT_DEV=$(awk '$2 == "/" {print $1}' /proc/mounts 2>/dev/null | xargs basename 2>/dev/null || true)
fi
if [[ "$ROOT_DEV" == *"nvme"* ]] || ls /dev/nvme* &>/dev/null; then
    DISK_TYPE="NVMe SSD"
elif [ -n "$ROOT_DEV" ] && [ -f "/sys/block/$(echo "$ROOT_DEV" | sed -E 's/p?[0-9]+$//')/queue/rotational" ]; then
    if [ "$(cat "/sys/block/$(echo "$ROOT_DEV" | sed -E 's/p?[0-9]+$//')/queue/rotational" 2>/dev/null)" == "1" ]; then
        DISK_TYPE="HDD (Rotational)"
    fi
elif ls /sys/block/*/queue/rotational &>/dev/null; then
    for bp in /sys/block/*/queue/rotational; do
        bdev=$(basename "$(dirname "$(dirname "$bp")")")
        case "$bdev" in loop*|ram*) continue ;; esac
        if [[ "$bdev" == *"nvme"* ]]; then
            DISK_TYPE="NVMe SSD"
            break
        elif [ "$(cat "$bp" 2>/dev/null)" == "1" ]; then
            DISK_TYPE="HDD (Rotational)"
        fi
    done
fi

# Resource Calculations
if [ "$TOTAL_RAM_MB" -le 2048 ]; then
    CALC_BP="512M"
    CALC_VALKEY="128MB"
elif [ "$TOTAL_RAM_MB" -le 4096 ]; then
    CALC_BP="$(( TOTAL_RAM_MB * 35 / 100 ))M"
    CALC_VALKEY="$(( TOTAL_RAM_MB * 10 / 100 ))MB"
elif [ "$TOTAL_RAM_MB" -le 8192 ]; then
    CALC_BP="2800M"
    CALC_VALKEY="$(( TOTAL_RAM_MB * 10 / 100 ))MB"
else
    CALC_BP="$(( TOTAL_RAM_MB * 55 / 100 ))M"
    CALC_VALKEY="2048MB"
fi
echo -e "${GREEN}✔ Probed Resources:${NC} ${TOTAL_CORES} vCPUs, ${TOTAL_RAM_MB} MB RAM (~$(( (TOTAL_RAM_MB + 512) / 1024 )) GB), Storage: ${DISK_TYPE}"
echo -e "${CYAN}  Auto-calculated Baseline:${NC} MariaDB Buffer Pool: ${CALC_BP} | Valkey Cache: ${CALC_VALKEY}"

# 3. Prerequisites Installation & Pre-Flight APT Sanitization
if [ "$DRY_RUN" -eq 0 ] && [ "$EUID" -eq 0 ]; then
    export DEBIAN_FRONTEND=noninteractive

    # Pre-flight: Remove broken/stale third-party repo lists that choke apt-get update
    echo -e "${CYAN}🧹 Pre-flight: Sanitizing repository sources & clearing APT locks...${NC}"
    rm -f /etc/apt/sources.list.d/*angie*.list /etc/apt/sources.list.d/*angie*.sources /etc/apt/trusted.gpg.d/*angie*.gpg
    rm -f /etc/apt/sources.list.d/*ondrej-ubuntu-php*.list /etc/apt/sources.list.d/*ondrej-ubuntu-php*.sources
    find /etc/apt/sources.list.d/ -type f -empty -delete 2>/dev/null || true
    dpkg --configure -a 2>/dev/null || true

    # Audit core prerequisites
    MISSING_PKGS=()
    for pkg in python3 python3-minimal curl ca-certificates git sqlite3; do
        if ! dpkg -s "$pkg" >/dev/null 2>&1; then
            MISSING_PKGS+=("$pkg")
        fi
    done

    if [ ${#MISSING_PKGS[@]} -gt 0 ]; then
        echo -e "${CYAN}📦 Installing missing bootstrap prerequisites (${MISSING_PKGS[*]})...${NC}"
        apt-get update -qq -o Acquire::Retries=3 2>/dev/null || true
        apt-get install -y -qq "${MISSING_PKGS[@]}" >/dev/null 2>&1 || apt-get install -y "${MISSING_PKGS[@]}"
        echo -e "${GREEN}✔ Base prerequisites confirmed.${NC}"
    else
        echo -e "${GREEN}✔ Base prerequisites confirmed (python3, curl, git, sqlite3).${NC}"
    fi
fi

# 4. Fetch or Update Repository Payload
if [ "$DRY_RUN" -eq 0 ]; then
    mkdir -p "$INSTALL_DIR"
    if [ -d "${INSTALL_DIR}/.git" ]; then
        echo -e "${CYAN}🔄 Updating existing LeanStack payload in ${INSTALL_DIR}...${NC}"
        git -c safe.directory=* -C "$INSTALL_DIR" fetch --tags --force origin 2>/dev/null || true
        git -c safe.directory=* -C "$INSTALL_DIR" pull --ff-only 2>/dev/null || true
    else
        echo -e "${CYAN}⬇️ Fetching LeanStack repository into ${INSTALL_DIR}...${NC}"
        if ! git clone --depth 1 "$DEFAULT_REPO_URL" "$INSTALL_DIR" 2>/dev/null; then
            echo -e "${YELLOW}⚠️ Notice: Public git clone did not complete.${NC}"
            if [ ! -f "${INSTALL_DIR}/installer/tui.py" ]; then
                echo -e "${RED}❌ Unable to download LeanStack payload.${NC}"
                echo -e "If using a private repository, please ensure an SSH deploy key or PAT is active, or run:"
                echo -e "  git clone ${DEFAULT_REPO_URL} ${INSTALL_DIR}"
                echo -e "  cd ${INSTALL_DIR} && sudo ./install.sh"
                exit 1
            fi
        fi
    fi
else
    # In dry-run via pipe on a system where /opt/leanstack does not exist yet
    if [ ! -f "${INSTALL_DIR}/installer/tui.py" ]; then
        TMP_PAYLOAD="/tmp/leanstack_dryrun_$$"
        echo -e "${CYAN}⬇️ Fetching LeanStack payload for dry-run simulation...${NC}"
        git clone --depth 1 "$DEFAULT_REPO_URL" "$TMP_PAYLOAD" 2>/dev/null || true
        if [ -f "${TMP_PAYLOAD}/installer/tui.py" ]; then
            INSTALL_DIR="$TMP_PAYLOAD"
        fi
    fi
fi

# 5. Launch Interactive Antigravity-Style TUI Engine
if [ -f "${INSTALL_DIR}/installer/tui.py" ]; then
    echo -e "${GREEN}🚀 Initializing LeanStack Hardware Prober & Installer TUI...${NC}\n"
    if [ ! -t 0 ] && [ -c /dev/tty ]; then
        exec python3 "${INSTALL_DIR}/installer/tui.py" "$@" </dev/tty
    else
        exec python3 "${INSTALL_DIR}/installer/tui.py" "$@"
    fi
else
    echo -e "${RED}❌ Fatal: Installer entrypoint (${INSTALL_DIR}/installer/tui.py) not found.${NC}" >&2
    exit 1
fi
