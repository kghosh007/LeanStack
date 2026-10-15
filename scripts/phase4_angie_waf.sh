#!/usr/bin/env bash
# ==============================================================================
# LeanStack Phase 4: Web Tier & Multi-Tier WAF (Angie + 8G WAF + CrowdSec)
# ==============================================================================
set -euo pipefail

if [ "$EUID" -ne 0 ]; then
    echo "❌ Error: Must be executed as root." >&2
    exit 1
fi

echo ">>> [Phase 4] Installing Angie Web Server & CrowdSec IPS..."
export DEBIAN_FRONTEND=noninteractive

# 1. Install Angie from Official Repository (Official Debian/Ubuntu Method)
if ! command -v angie &>/dev/null; then
    echo ">>> [Phase 4] Configuring official Angie repository..."
    rm -f /etc/apt/sources.list.d/*angie*.list /etc/apt/sources.list.d/*angie*.sources /etc/apt/trusted.gpg.d/*angie*.gpg
    apt-get update -qq
    apt-get install -y -qq ca-certificates curl

    # Download official signing key directly to trusted keyring (already binary OpenPGP)
    mkdir -p /etc/apt/trusted.gpg.d
    curl -fsSL -o /etc/apt/trusted.gpg.d/angie-signing.gpg https://angie.software/keys/angie-signing.gpg

    # Add official Angie repository using /etc/os-release ($ID/$VERSION_ID $VERSION_CODENAME)
    echo "deb https://download.en.angie.software/angie/$(. /etc/os-release && echo "$ID/$VERSION_ID $VERSION_CODENAME") main" \
        | tee /etc/apt/sources.list.d/angie.list > /dev/null

    echo ">>> [Phase 4] Updating package index & installing Angie..."
    apt-get update -qq
    apt-get install -y -qq angie angie-module-brotli 2>/dev/null || apt-get install -y -qq angie
fi

# 2. Prevent CrowdSec SSH Lockout: Whitelist Active SSH Connection & Local Subnets
mkdir -p /etc/crowdsec/parsers/s02-enrich
SSH_CLIENT_IP=$(echo "${SSH_CLIENT:-}" | awk '{print $1}')
echo ">>> [Phase 4] Configuring CrowdSec Whitelists (SSH Client IP: ${SSH_CLIENT_IP:-'none'})..."

cat << EOF > /etc/crowdsec/parsers/s02-enrich/whitelists.yaml
name: leanstack/whitelists
description: "LeanStack Trusted Whitelist (SSH Session, Local Subnets, Cloudflare)"
filter: "evt.Meta.service == 'sshd' || evt.Meta.service == 'http'"
whitelist:
  reason: "LeanStack Administrator and Infrastructure Protection"
  ip:
    - "127.0.0.1"
    - "::1"
EOF

if [ -n "$SSH_CLIENT_IP" ]; then
    echo "    - \"${SSH_CLIENT_IP}\"" >> /etc/crowdsec/parsers/s02-enrich/whitelists.yaml
fi

cat << 'EOF' >> /etc/crowdsec/parsers/s02-enrich/whitelists.yaml
  cidr:
    - "10.0.0.0/8"
    - "172.16.0.0/12"
    - "192.168.0.0/16"
    # Cloudflare IPv4 Ranges
    - "173.245.48.0/20"
    - "103.21.244.0/22"
    - "103.22.200.0/22"
    - "103.31.4.0/22"
    - "141.101.64.0/18"
    - "108.162.192.0/18"
    - "190.93.240.0/20"
    - "188.114.96.0/20"
    - "197.234.240.0/22"
    - "198.41.128.0/17"
    - "162.158.0.0/15"
    - "104.16.0.0/13"
    - "104.24.0.0/14"
    - "172.64.0.0/13"
    - "131.0.72.0/22"
EOF

# Install CrowdSec & Firewall Bouncer
if ! command -v cscli &>/dev/null; then
    curl -s https://install.crowdsec.net | bash >/dev/null 2>&1 || true
    apt-get install -y -qq crowdsec
    apt-get install -y -qq crowdsec-firewall-bouncer-nftables 2>/dev/null || \
    apt-get install -y -qq crowdsec-firewall-bouncer-iptables 2>/dev/null || true
fi

# Ensure firewall bouncer has an active API key registered with CrowdSec LAPI
if [ -f /etc/crowdsec/bouncers/crowdsec-firewall-bouncer.yaml ] && command -v cscli &>/dev/null; then
    if ! grep -qE 'api_key:\s+[a-zA-Z0-9]+' /etc/crowdsec/bouncers/crowdsec-firewall-bouncer.yaml 2>/dev/null; then
        BOUNCER_KEY=$(cscli bouncers add firewall-bouncer -o raw 2>/dev/null || true)
        if [ -n "$BOUNCER_KEY" ]; then
            sed -i "s/^api_key:.*/api_key: ${BOUNCER_KEY}/" /etc/crowdsec/bouncers/crowdsec-firewall-bouncer.yaml 2>/dev/null || true
            systemctl restart crowdsec-firewall-bouncer 2>/dev/null || true
        fi
    fi
fi

# Install CrowdSec WordPress Brute-Force & Attack Scenarios
if command -v cscli &>/dev/null; then
    cscli collections install crowdsecurity/wordpress 2>/dev/null || true
    systemctl reload crowdsec 2>/dev/null || true
fi

# 3. Generate Shared 80-Byte TLS Session Ticket Key (for Multi-Worker Resumption)
mkdir -p /etc/angie/snippets /etc/angie/http.d /var/cache/angie/fastcgi /var/lib/angie/acme
openssl rand 80 > /etc/angie/tls_session_ticket.key
chmod 600 /etc/angie/tls_session_ticket.key
chown www-data:www-data /etc/angie/tls_session_ticket.key
chown -R www-data:www-data /var/cache/angie /var/lib/angie

# Copy Snippets from LeanStack repository
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cp "${SCRIPT_DIR}/core/snippets/"*.conf /etc/angie/snippets/

# Dynamic Brotli Module Configuration (if installed)
mkdir -p /etc/angie/modules.d
if [ -f /usr/lib/angie/modules/ngx_http_brotli_filter_module.so ]; then
    cat << 'MODULE_EOF' > /etc/angie/modules.d/brotli.conf
load_module modules/ngx_http_brotli_filter_module.so;
load_module modules/ngx_http_brotli_static_module.so;
MODULE_EOF

    cat << 'SNIPPET_EOF' > /etc/angie/snippets/brotli.conf
brotli on;
brotli_comp_level 4;
brotli_static on;
brotli_types text/plain text/css application/javascript application/json application/xml image/svg+xml application/wasm;
SNIPPET_EOF
else
    rm -f /etc/angie/modules.d/brotli.conf /etc/angie/snippets/brotli.conf
fi

# 4. Deploy Global Master Angie Configuration
cat << 'EOF' > /etc/angie/angie.conf
user www-data;
pid /run/angie.pid;
worker_processes auto;
worker_cpu_affinity auto;
worker_rlimit_nofile 65535;

# Dynamic Module Includes
include /etc/angie/modules.d/*.conf;

events {
    worker_connections 8192;
    multi_accept on;
    use epoll;
}

http {
    # Basic Networking
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    keepalive_timeout 65;
    types_hash_max_size 2048;
    server_tokens off;

    include /etc/angie/mime.types;
    default_type application/octet-stream;

    # Logging
    access_log /var/log/angie/access.log combined buffer=64k flush=5m;
    error_log /var/log/angie/error.log warn;

    # FastCGI Microcache Storage
    fastcgi_cache_path /var/cache/angie/fastcgi levels=1:2 keys_zone=WORDPRESS:100m inactive=60m max_size=1g;
    fastcgi_cache_key "$scheme$request_method$host$request_uri";
    fastcgi_cache_use_stale error timeout updating invalid_header http_500 http_503;
    fastcgi_ignore_headers Cache-Control Expires Set-Cookie;

    # Soft Throttle Rate-Limiting Zones (Anti-Noisy-Neighbor)
    limit_req_zone $binary_remote_addr zone=perip:20m rate=20r/s;
    limit_req_zone $server_name zone=persite:20m rate=150r/s;
    limit_req_zone $binary_remote_addr zone=wplogin:10m rate=2r/s;
    limit_req_status 429;

    # Upload Limits & Security
    client_max_body_size 128M;
    client_body_buffer_size 128k;

    # Google Brotli Compression (dynamically enabled if module present)
    include /etc/angie/snippets/brotli.conf*;

    # Gzip Compression Fallback
    gzip on;
    gzip_vary on;
    gzip_proxied any;
    gzip_comp_level 6;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml application/xml+rss text/javascript application/wasm;

    # Universal Scheme Detection (Cloudflare Flexible/Full SSL & Standard HTTPS)
    map $http_cf_visitor $cf_proto_https {
        default 0;
        '~*"scheme":"https"' 1;
    }

    map $http_x_forwarded_proto $x_forwarded_https {
        default 0;
        'https' 1;
    }

    # ==============================================================================
    # SSL Labs A+ (100% Score) Global TLS Configuration
    # ==============================================================================
    # 1. Session Resumption (Shared Cache + Multi-Worker Ticket Key)
    ssl_session_timeout 1d;
    ssl_session_cache shared:SSL:50m;
    ssl_session_tickets on;
    ssl_session_ticket_key /etc/angie/tls_session_ticket.key;

    # 2. Maximum Cipher Strength: Pure 256-Bit AEAD Modern Ciphers
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers on;

    # 3. Post-Quantum Cryptography (PQC) Auto-Negotiation (X25519MLKEM768)
    ssl_ecdh_curve X25519MLKEM768:x25519:secp384r1;

    # 4. OCSP Stapling (Faster Handshakes & Enhanced Trust)
    ssl_stapling on;
    ssl_stapling_verify on;
    resolver 1.1.1.1 8.8.8.8 valid=300s;
    resolver_timeout 5s;

    # 5. Include Cloudflare Real IP Restoration
    include /etc/angie/snippets/cloudflare-realip.conf;

    # 6. Include Per-Site Dedicated FastCGI Cache Zones
    include /etc/angie/cache-zones/*.conf;

    # Virtual Hosts
    include /etc/angie/http.d/*.conf;
}
EOF

mkdir -p /etc/angie/cache-zones /var/cache/angie/sites

# Stop and disable competing web servers if present
systemctl stop apache2 2>/dev/null || true
systemctl disable apache2 2>/dev/null || true
systemctl stop nginx 2>/dev/null || true
systemctl disable nginx 2>/dev/null || true

# Validate syntax and reload
angie -t
systemctl restart angie 2>/dev/null || true
systemctl enable angie 2>/dev/null || true

echo "✅ [Phase 4] Angie Web Server, PQC TLS, 8G WAF & CrowdSec Configured Successfully!"
