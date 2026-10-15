#!/usr/bin/env bash
# ==============================================================================
# LeanStack Master Automated Verification Test Suite
# Validates all 10 Pillars of the Master Implementation Plan
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

GREEN="\033[32m"
CYAN="\033[36m"
BOLD="\033[1m"
RESET="\033[0m"

echo -e "${BOLD}${CYAN}==============================================================================${RESET}"
echo -e "${BOLD}${CYAN}       LEANSTACK MASTER AUTOMATED VERIFICATION SUITE (10 PILLARS)             ${RESET}"
echo -e "${BOLD}${CYAN}==============================================================================${RESET}"

TOTAL_SCORE=0

run_pillar() {
    local num="$1"
    local name="$2"
    local cmd="$3"
    
    echo -n "  Pillar ${num}: ${name}... "
    if eval "$cmd" >/dev/null 2>&1; then
        echo -e "${GREEN}${BOLD}[10/10 PASS]${RESET}"
        TOTAL_SCORE=$((TOTAL_SCORE + 10))
    else
        echo -e "\033[31m${BOLD}[FAILED]${RESET}"
    fi
}

# Pillar 1: Architecture & Component Decoupling
run_pillar 1 "Architecture & Decoupling" "
    [ -f '${BASE_DIR}/core/bin/lsctl' ] && \
    [ -f '${BASE_DIR}/core/bin/cpctl' ] && \
    [ -f '${BASE_DIR}/core/config/profiles.yaml' ] && \
    python3 -c 'import sqlite3; conn = sqlite3.connect(\":memory:\"); conn.execute(\"PRAGMA journal_mode=WAL;\")'
"

# Pillar 2: Installation & TUI Experience
run_pillar 2 "Installation & TUI Experience" "
    python3 '${BASE_DIR}/installer/tui.py' --dry-run --non-interactive
"

# Pillar 3: Hardware-Aware Auto-Tuning
run_pillar 3 "Hardware-Aware Auto-Tuning" "
    python3 '${BASE_DIR}/tests/test_tuning.py'
"

# Pillar 4: Web & Caching Tier (Angie, HTTP/3, Valkey Unix Socket, FastCGI & SSI)
run_pillar 4 "Web & Caching Tier" "
    grep -q 'listen 443 quic;' '${BASE_DIR}/core/templates/vhost.conf.tpl' && \
    grep -q 'quic default_server reuseport' '${BASE_DIR}/scripts/phase4_angie_waf.sh' && \
    grep -q 'angie-module-cache-purge' '${BASE_DIR}/scripts/phase4_angie_waf.sh' && \
    grep -q '{{PURGE_DIRECTIVE}}' '${BASE_DIR}/core/templates/vhost.conf.tpl' && \
    grep -q 'unixsocket /run/valkey/valkey.sock' '${BASE_DIR}/scripts/phase2_valkey.sh' && \
    grep -q 'port 0' '${BASE_DIR}/scripts/phase2_valkey.sh' && \
    python3 '${BASE_DIR}/tests/test_cache_invalidation.py'
"

# Pillar 5: Database Tier (High-QPS, Gap-Lock Elimination)
run_pillar 5 "Database Tier High-QPS Tuning" "
    grep -q 'transaction_isolation.*READ-COMMITTED' '${BASE_DIR}/scripts/phase3_mariadb.sh' && \
    grep -q 'mrr_cost_based=on' '${BASE_DIR}/scripts/phase3_mariadb.sh' && \
    grep -q 'table_open_cache_instances' '${BASE_DIR}/scripts/phase3_mariadb.sh'
"

# Pillar 6: PHP Multi-Tenant Isolation
run_pillar 6 "PHP Multi-Tenant Isolation" "
    grep -q 'php_admin_value\[open_basedir\]' '${BASE_DIR}/core/templates/pool.conf.tpl' && \
    grep -q 'php_admin_value\[disable_functions\]' '${BASE_DIR}/core/templates/pool.conf.tpl' && \
    grep -q 'chown \"\${USER_NAME}:www-data\" \"/home/\${USER_NAME}\"' '${BASE_DIR}/core/bin/lsctl' && \
    grep -q 'chmod 750 \"/home/\${USER_NAME}\"' '${BASE_DIR}/core/bin/lsctl'
"

# Pillar 7: Multi-Layer Security & Hardening (8G WAF, CrowdSec, Upload PHP Block)
run_pillar 7 "Multi-Layer Security & Hardening" "
    [ -f '${BASE_DIR}/core/snippets/8g-firewall.conf' ] && \
    grep -q 'PURGE' '${BASE_DIR}/core/snippets/8g-firewall.conf' && \
    [ -f '${BASE_DIR}/core/snippets/ssl-headers.conf' ] && \
    grep -q 'wp-content/uploads' '${BASE_DIR}/core/templates/vhost.conf.tpl'
"

# Pillar 8: CLI Engine & Profiles
run_pillar 8 "CLI Engine & Profiles System" "
    '${BASE_DIR}/core/bin/lsctl' help >/dev/null && \
    '${BASE_DIR}/core/bin/cpctl' help >/dev/null && \
    '${BASE_DIR}/core/bin/lsctl' watcher:status --json >/dev/null && \
    python3 '${BASE_DIR}/tests/test_cli_and_templates.py'
"

# Pillar 9: Resilience & Automation (Cron Queue, Sync, Gatekeeper, Linter, Upgrade, Watcher, Autoupdate)
run_pillar 9 "Resilience & Automation" "
    [ -x '${BASE_DIR}/core/bin/ls-upgrade' ] && \
    [ -x '${BASE_DIR}/core/bin/ls-cf-sync' ] && \
    grep -q 'chmod 644' '${BASE_DIR}/core/bin/ls-cf-sync' && \
    [ -x '${BASE_DIR}/core/bin/ls-cron-queue' ] && \
    [ -x '${BASE_DIR}/core/bin/ls-gatekeeper' ] && \
    [ -x '${BASE_DIR}/core/bin/ls-nginx-linter' ] && \
    [ -x '${BASE_DIR}/core/bin/ls-watcher' ] && \
    [ -x '${BASE_DIR}/core/bin/ls-autoupdate' ] && \
    [ -f '${BASE_DIR}/systemd/ls-watcher.service' ] && \
    [ -f '${BASE_DIR}/systemd/ls-watcher.timer' ] && \
    [ -f '${BASE_DIR}/systemd/ls-autoupdate.service' ] && \
    [ -f '${BASE_DIR}/systemd/ls-autoupdate.timer' ] && \
    [ -d '${BASE_DIR}/systemd/overrides' ] && \
    python3 '${BASE_DIR}/tests/test_nginx_linter.py' && \
    python3 '${BASE_DIR}/tests/test_upgrade_and_migration.py' && \
    [ -f '${BASE_DIR}/systemd/cp-cron.timer' ]
"

# Pillar 10: Verification & Edge Cases
run_pillar 10 "Edge Case Guardrails & Verifications" "
    grep -q 'cf_proto_https' '${BASE_DIR}/core/templates/vhost.conf.tpl' && \
    grep -q 'security-headers.conf' '${BASE_DIR}/core/templates/vhost.conf.tpl' && \
    grep -q 'whitelists.yaml' '${BASE_DIR}/scripts/phase4_angie_waf.sh'
"

echo -e "${BOLD}${CYAN}==============================================================================${RESET}"
echo -e "${BOLD}FINAL READINESS SCORE: ${GREEN}${TOTAL_SCORE} / 100 (${TOTAL_SCORE}% READINESS)${RESET}"
echo -e "${BOLD}${CYAN}==============================================================================${RESET}"

if [ "$TOTAL_SCORE" -eq 100 ]; then
    echo -e "${GREEN}${BOLD}✔ 100% IMPLEMENTATION READINESS CONFIRMED. ALL PILLARS VERIFIED.${RESET}"
    exit 0
else
    echo -e "\033[31m${BOLD}✖ READINESS SCORE DID NOT REACH 100%. REVIEW FAILED PILLARS.${RESET}"
    exit 1
fi
