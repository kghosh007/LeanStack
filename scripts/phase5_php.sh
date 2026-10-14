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

# Add Ondřej Surý PPA
if [ ! -f /etc/apt/sources.list.d/ondrej-ubuntu-php-*.list ]; then
    apt-get install -y -qq software-properties-common ca-certificates lsb-release apt-transport-https >/dev/null
    add-apt-repository -y ppa:ondrej/php >/dev/null 2>&1 || true
    apt-get update -qq
fi

# Primary versions to install
PHP_VERSIONS="8.2 8.3 8.4 8.5"

# Hardware Probing for JIT
HAS_AVX2=$(grep -q "avx2" /proc/cpuinfo && echo 1 || echo 0)
HAS_SSE4=$(grep -q "sse4_2" /proc/cpuinfo && echo 1 || echo 0)

for VER in $PHP_VERSIONS; do
    echo ">>> [Phase 5] Installing PHP ${VER} and extensions..."
    apt-get install -y -qq \
        "php${VER}-fpm" \
        "php${VER}-mysql" \
        "php${VER}-redis" \
        "php${VER}-curl" \
        "php${VER}-gd" \
        "php${VER}-mbstring" \
        "php${VER}-xml" \
        "php${VER}-zip" \
        "php${VER}-imagick" \
        "php${VER}-bcmath" \
        "php${VER}-intl" \
        "php${VER}-opcache" \
        "php${VER}-apcu" >/dev/null 2>&1 || true

    # Tune Master php.ini for this version if installed
    FPM_INI="/etc/php/${VER}/fpm/php.ini"
    if [ -f "$FPM_INI" ]; then
        sed -i 's/^expose_php = .*/expose_php = Off/' "$FPM_INI"
        sed -i 's/^memory_limit = .*/memory_limit = 256M/' "$FPM_INI"
        sed -i 's/^upload_max_filesize = .*/upload_max_filesize = 128M/' "$FPM_INI"
        sed -i 's/^post_max_size = .*/post_max_size = 128M/' "$FPM_INI"
        sed -i 's/^max_execution_time = .*/max_execution_time = 120/' "$FPM_INI"

        # OPcache Tuning
        cat << EOF >> "$FPM_INI"

; --- LeanStack High-Performance OPcache & JIT Profile ---
opcache.enable = 1
opcache.enable_cli = 0
opcache.memory_consumption = 256
opcache.interned_strings_buffer = 32
opcache.max_accelerated_files = 30000
opcache.revalidate_freq = 60
opcache.validate_timestamps = 1
opcache.save_comments = 1
opcache.fast_shutdown = 1
opcache.validate_permission = 1
opcache.validate_root = 1
EOF

        if [ "$HAS_AVX2" -eq 1 ] || [ "$HAS_SSE4" -eq 1 ]; then
            cat << 'EOF' >> "$FPM_INI"
opcache.jit = tracing
opcache.jit_buffer_size = 64M
EOF
        fi

        # Remove default www pool to prevent memory leaks / port conflicts
        rm -f "/etc/php/${VER}/fpm/pool.d/www.conf"

        systemctl restart "php${VER}-fpm" 2>/dev/null || true
        systemctl enable "php${VER}-fpm" 2>/dev/null || true
    fi
done

# Install WP-CLI globally
if ! command -v wp &>/dev/null; then
    echo ">>> [Phase 5] Installing WP-CLI..."
    curl -fsSL https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar -o /usr/local/bin/wp
    chmod +x /usr/local/bin/wp
fi

echo "✅ [Phase 5] PHP Multi-Version Engine & WP-CLI Installed Successfully!"
