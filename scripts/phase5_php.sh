#!/usr/bin/env bash
# ==============================================================================
# LeanStack Phase 5: Application Tier (PHP Multi-Version Engine & WP-CLI)
# ==============================================================================
set -euo pipefail

if [ "$EUID" -ne 0 ]; then
    echo "❌ Error: Must be executed as root." >&2
    exit 1
fi

echo ">>> [Phase 5] Installing PHP Multi-Version Engine (8.1 - 8.5) & WP-CLI..."
export DEBIAN_FRONTEND=noninteractive

# 1. Clean stale/corrupted PPA entries and test PPA compatibility
CODENAME=""
if [ -f /etc/os-release ]; then
    . /etc/os-release
    CODENAME="${VERSION_CODENAME:-}"
fi

# Clean any broken PPA list files first
rm -f /etc/apt/sources.list.d/*ondrej-ubuntu-php*.list /etc/apt/sources.list.d/*ondrej-ubuntu-php*.sources

PPA_SUPPORTED=0
if [ -n "$CODENAME" ]; then
    # Test if Ondřej Surý PPA has an active Release file for this codename
    if curl -fsIL --connect-timeout 5 "https://ppa.launchpadcontent.net/ondrej/php/ubuntu/dists/${CODENAME}/Release" &>/dev/null; then
        PPA_SUPPORTED=1
    fi
fi

if [ "$PPA_SUPPORTED" -eq 1 ]; then
    echo ">>> [Phase 5] Adding Ondřej Surý PHP repository for Ubuntu ${CODENAME}..."
    apt-get install -y -qq software-properties-common ca-certificates lsb-release apt-transport-https >/dev/null 2>&1 || true
    add-apt-repository -y ppa:ondrej/php >/dev/null 2>&1 || true
    apt-get update -qq -o Acquire::Retries=3 2>/dev/null || true
else
    echo ">>> [Phase 5] Native Ubuntu ${CODENAME:-system} repositories provide modern PHP; using official repositories."
    apt-get update -qq -o Acquire::Retries=3 2>/dev/null || true
fi

# 2. Probe available PHP versions in APT
TARGET_VERSIONS="8.2 8.3 8.4 8.5"
AVAILABLE_VERSIONS=()

for ver in $TARGET_VERSIONS; do
    if apt-cache show "php${ver}-fpm" &>/dev/null; then
        AVAILABLE_VERSIONS+=("$ver")
    fi
done

# If no specific version package was found, check default php-fpm
if [ ${#AVAILABLE_VERSIONS[@]} -eq 0 ]; then
    echo ">>> [Phase 5] Installing default distribution PHP-FPM runtime..."
    apt-get install -y -qq php-fpm php-mysql php-redis php-curl php-gd php-mbstring php-xml php-zip php-imagick php-bcmath php-intl php-apcu msmtp msmtp-mta 2>/dev/null || true
    DEF_VER=$(php -r 'echo PHP_MAJOR_VERSION . "." . PHP_MINOR_VERSION;' 2>/dev/null || echo "8.5")
    AVAILABLE_VERSIONS+=("$DEF_VER")
fi

echo ">>> [Phase 5] Provisioning PHP versions: ${AVAILABLE_VERSIONS[*]}..."

# Hardware Probing for JIT and Memory Sizing
HAS_AVX2=$(grep -q "avx2" /proc/cpuinfo 2>/dev/null && echo 1 || echo 0)
HAS_SSE4=$(grep -q "sse4_2" /proc/cpuinfo 2>/dev/null && echo 1 || echo 0)
RAM_TOTAL_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo 2>/dev/null || echo 2048)
OPCACHE_MEM=$(( RAM_TOTAL_MB * 5 / 100 ))
[ "$OPCACHE_MEM" -lt 128 ] && OPCACHE_MEM=128
[ "$OPCACHE_MEM" -gt 512 ] && OPCACHE_MEM=512

for VER in "${AVAILABLE_VERSIONS[@]}"; do
    echo ">>> [Phase 5] Installing PHP ${VER} and extensions..."
    
    # Resolve package names
    PKGS="php${VER}-fpm"
    EXTS="mysql redis curl gd mbstring xml zip imagick bcmath intl apcu"
    for ext in $EXTS; do
        if apt-cache show "php${VER}-${ext}" &>/dev/null; then
            PKGS="${PKGS} php${VER}-${ext}"
        elif apt-cache show "php-${ext}" &>/dev/null; then
            PKGS="${PKGS} php-${ext}"
        fi
    done

    apt-get install -y -qq $PKGS msmtp msmtp-mta 2>/dev/null || apt-get install -y -qq "php${VER}-fpm" msmtp msmtp-mta 2>/dev/null || true

    # Tune Master php.ini for this version if installed
    FPM_INI="/etc/php/${VER}/fpm/php.ini"
    if [ -f "$FPM_INI" ]; then
        sed -i 's/^expose_php = .*/expose_php = Off/' "$FPM_INI"
        sed -i 's/^memory_limit = .*/memory_limit = 256M/' "$FPM_INI"
        sed -i 's/^upload_max_filesize = .*/upload_max_filesize = 128M/' "$FPM_INI"
        sed -i 's/^post_max_size = .*/post_max_size = 128M/' "$FPM_INI"
        sed -i 's/^max_execution_time = .*/max_execution_time = 120/' "$FPM_INI"
        sed -i 's/^;*session\.use_strict_mode\s*=.*/session.use_strict_mode = 1/' "$FPM_INI"
        grep -q "^session.use_strict_mode" "$FPM_INI" || echo "session.use_strict_mode = 1" >> "$FPM_INI"
        sed -i 's/^;*max_input_vars = .*/max_input_vars = 5000/' "$FPM_INI"
        grep -q "^max_input_vars" "$FPM_INI" || echo "max_input_vars = 5000" >> "$FPM_INI"
        sed -i 's/^;*disable_functions\s*=.*/disable_functions = exec,passthru,shell_exec,system,proc_open,popen,dl,show_source,opcache_reset/' "$FPM_INI"

        CLI_INI="/etc/php/${VER}/cli/php.ini"
        if [ -f "$CLI_INI" ]; then
            sed -i 's/^;*session\.use_strict_mode\s*=.*/session.use_strict_mode = 1/' "$CLI_INI"
            grep -q "^session.use_strict_mode" "$CLI_INI" || echo "session.use_strict_mode = 1" >> "$CLI_INI"
            sed -i 's/^;*max_input_vars = .*/max_input_vars = 5000/' "$CLI_INI"
            grep -q "^max_input_vars" "$CLI_INI" || echo "max_input_vars = 5000" >> "$CLI_INI"
        fi

        # Global Timezone Configuration (eliminates /etc/localtime stat() syscalls)
        for ini_file in "$FPM_INI" "$CLI_INI"; do
            if [ -f "$ini_file" ]; then
                sed -i 's/^;*date\.timezone\s*=.*/date.timezone = UTC/' "$ini_file"
                grep -q "^date.timezone" "$ini_file" || echo "date.timezone = UTC" >> "$ini_file"
            fi
        done

        # Deploy High-Priority LeanStack OPcache & JIT Configuration Drop-in
        mkdir -p "/etc/php/${VER}/fpm/conf.d" "/etc/php/${VER}/cli/conf.d"
        cat << EOF > "/etc/php/${VER}/fpm/conf.d/99-leanstack-opcache.ini"
; --- LeanStack High-Performance OPcache & JIT Profile ---
opcache.enable = 1
opcache.enable_cli = 0
opcache.memory_consumption = ${OPCACHE_MEM}
opcache.interned_strings_buffer = 32
opcache.max_accelerated_files = 30000
opcache.revalidate_freq = 60
opcache.validate_timestamps = 1
opcache.save_comments = 1
opcache.fast_shutdown = 1
opcache.validate_permission = 1
opcache.validate_root = 1
opcache.jit = tracing
opcache.jit_buffer_size = 64M
opcache.jit_max_root_traces = 5000
opcache.jit_max_side_traces = 5000
opcache.jit_hot_loop = 1
EOF
        cp "/etc/php/${VER}/fpm/conf.d/99-leanstack-opcache.ini" "/etc/php/${VER}/cli/conf.d/99-leanstack-opcache.ini" 2>/dev/null || true

        # APCu High-Speed In-Memory Cache Tuning (64MB SHM, enable_cli=0)
        APCU_INI="/etc/php/${VER}/mods-available/apcu.ini"
        if [ -f "$APCU_INI" ]; then
            grep -q "^apc.enabled" "$APCU_INI" || echo "apc.enabled = 1" >> "$APCU_INI"
            grep -q "^apc.shm_size" "$APCU_INI" || echo "apc.shm_size = 64M" >> "$APCU_INI"
            grep -q "^apc.enable_cli" "$APCU_INI" || echo "apc.enable_cli = 0" >> "$APCU_INI"
            sed -i 's/^;*apc.enabled\s*=.*/apc.enabled = 1/' "$APCU_INI"
            sed -i 's/^;*apc.shm_size\s*=.*/apc.shm_size = 64M/' "$APCU_INI"
            sed -i 's/^;*apc.enable_cli\s*=.*/apc.enable_cli = 0/' "$APCU_INI"
        fi
        phpenmod -v "${VER}" apcu 2>/dev/null || true

        # Remove default www pool to prevent memory leaks / port conflicts
        mkdir -p "/etc/php/${VER}/fpm/pool.d"
        rm -f "/etc/php/${VER}/fpm/pool.d/www.conf"

        # Create lightweight system pool so the PHP-FPM service starts cleanly
        cat << POOL_EOF > "/etc/php/${VER}/fpm/pool.d/system.conf"
[system]
user = www-data
group = www-data
listen = /run/php/php${VER}-fpm-system.sock
listen.owner = www-data
listen.group = www-data
listen.mode = 0660
pm = ondemand
pm.max_children = 2
pm.process_idle_timeout = 10s
POOL_EOF

        systemctl restart "php${VER}-fpm" 2>/dev/null || true
        systemctl enable "php${VER}-fpm" 2>/dev/null || true
    fi
done

# Install WP-CLI globally
if ! command -v wp &>/dev/null; then
    echo ">>> [Phase 5] Installing WP-CLI..."
    curl -fsSL --connect-timeout 10 --retry 3 https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar -o /usr/local/bin/wp 2>/dev/null || true
    if [ -f /usr/local/bin/wp ]; then
        chmod +x /usr/local/bin/wp
    fi
fi

echo "✅ [Phase 5] PHP Multi-Version Engine & WP-CLI Installed Successfully!"
