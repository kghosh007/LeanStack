# ==============================================================================
# LeanStack Virtual Host Configuration for: {{DOMAIN}}
# Angie Web Server • HTTP/3 (QUIC) • Native ACME • 8G WAF • Hardened Tenant
# ==============================================================================

# Native C-based Angie ACME Client
acme_client acme_{{ZONE_KEY}} https://acme-v02.api.letsencrypt.org/directory challenge=http;

# Fallback to default self-signed SSL cert while ACME certificate is pending
map $acme_cert_acme_{{ZONE_KEY}} $ssl_cert_{{ZONE_KEY}} {
    "" /etc/angie/ssl/default.crt;
    default $acme_cert_acme_{{ZONE_KEY}};
}
map $acme_cert_key_acme_{{ZONE_KEY}} $ssl_key_{{ZONE_KEY}} {
    "" /etc/angie/ssl/default.key;
    default $acme_cert_key_acme_{{ZONE_KEY}};
}

# HTTP Port 80 -> HTTPS Port 443 Permanent Redirect
server {
    listen 80;
    listen [::]:80;
    server_name {{DOMAIN}};
    root {{WEB_ROOT}};

    acme acme_{{ZONE_KEY}};

    # Internal Loopback Surgical Cache Purge Endpoint (Port 80 Loopback)
    location ~ /leanstack-purge(/.*) {
        allow 127.0.0.1;
        deny all;
        {{PURGE_DIRECTIVE}}
    }

    location / {
        return 301 https://$host$request_uri;
    }
}

# HTTPS Port 443 (HTTP/1.1, HTTP/2 & HTTP/3 QUIC)
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    listen 443 quic;
    listen [::]:443 quic;
    http2 on;

    server_name {{DOMAIN}};
    root {{WEB_ROOT}};
    index index.php index.html;
    charset utf-8;

    # Logs
    access_log {{LOG_DIR}}/access.log combined buffer=32k flush=1m;
    error_log {{LOG_DIR}}/error.log warn;

    # Native Angie ACME Let's Encrypt Client with Seamless Fallback
    acme acme_{{ZONE_KEY}};
    ssl_certificate     $ssl_cert_{{ZONE_KEY}};
    ssl_certificate_key $ssl_key_{{ZONE_KEY}};

    # Tenant Security Headers & Policies
    include /etc/angie/tenant-custom/{{PRIMARY_DOMAIN}}/security-headers.conf;

    # 8G Web Application Firewall
    include /etc/angie/snippets/8g-firewall.conf;

    # Tenant FastCGI Cache Configuration
    include /etc/angie/tenant-custom/{{PRIMARY_DOMAIN}}/cache-config.conf;

    # Universal Protocol Detection (TLS on native socket or verified Cloudflare edge)
    set $custom_https $https;
    if ($cf_proto_https = 1) {
        set $custom_https on;
    }

    # ==========================================================================
    # SECURITY HARDENING: Zero-Tolerance Execution Blockers & Rate Limiting
    # ==========================================================================
    # 1. Native WordPress Brute-Force Rate Limiting (/wp-login.php)
    location = /wp-login.php {
        limit_req zone=wplogin burst=5 nodelay;
        limit_req_status 429;

        include /etc/angie/fastcgi_params;
        fastcgi_pass {{TARGET_SOCKET}};
        fastcgi_index index.php;
        fastcgi_buffers 16 16k;
        fastcgi_buffer_size 32k;
        fastcgi_read_timeout 120s;
        fastcgi_param SCRIPT_FILENAME $realpath_root$fastcgi_script_name;
        fastcgi_param DOCUMENT_ROOT $realpath_root;
        fastcgi_param HTTPS $custom_https;
        include /etc/angie/tenant-custom/{{PRIMARY_DOMAIN}}/security-headers.conf;
    }

    # 2. Hard Block: No PHP execution in Uploads / Cache / Media
    location ~* /(?:uploads|files|wp-content/uploads|wp-content/cache)/.*\.php$ {
        deny all;
        access_log off;
        log_not_found off;
        return 403;
    }
    location ~* /(?:uploads|files|wp-content/uploads|wp-content/cache)/.*\.(?:phtml|phar|inc|pl|py|cgi|sh|bash)$ {
        deny all;
        access_log off;
        log_not_found off;
        return 403;
    }

    # 3. Hard Block: No PHP execution in wp-includes
    location ~* /wp-includes/.*\.php$ {
        deny all;
        access_log off;
        log_not_found off;
        return 403;
    }

    # 3b. Hard Block: No direct execution of mu-plugins via HTTP
    location ~* /wp-content/mu-plugins/.*\.php$ {
        deny all;
        access_log off;
        log_not_found off;
        return 403;
    }

    # 4. Mask & Block Sensitive Files with 404
    location ~* (?:wp-config\.php.*|wp-config-sample\.php|\.user\.ini|readme\.html|readme\.txt|license\.txt|licence\.txt|composer\.(?:json|lock)|package(?:-lock)?\.json|\.(?:bak|sql|log|env|orig|save|swp|swo|dist|old|temp|tmp)(?:~)?)$ {
        deny all;
        access_log off;
        log_not_found off;
        return 404;
    }

    # 5. Block Hidden Files & Dotfiles (.git, .env, .htaccess)
    location ~ /\.(?!well-known) {
        deny all;
        access_log off;
        log_not_found off;
        return 404;
    }

    # 6. Block XML-RPC (Eliminates Pingback & Brute-Force DDoS)
    location = /xmlrpc.php {
        deny all;
        access_log off;
        log_not_found off;
        return 403;
    }

    # ==========================================================================
    # TENANT CUSTOM SLOT 1: Pre-Static Interceptor (CompressX, Caching, AVIF/WebP)
    # Strictly positioned after 8G WAF & security blocks to prevent bypass
    # ==========================================================================
    include /etc/angie/tenant-custom/{{PRIMARY_DOMAIN}}/custom-early.conf;

    # ==========================================================================
    # Static Asset Caching (Images, CSS, JS, Fonts, AVIF, WebP, WebAssembly)
    # ==========================================================================
    location ~* \.(jpg|jpeg|gif|png|webp|avif|svg|ico|css|js|woff2|woff|ttf|otf|eot|wasm)$ {
        expires 365d;
        access_log off;
        log_not_found off;
        add_header Cache-Control "public, no-transform";
        include /etc/angie/tenant-custom/{{PRIMARY_DOMAIN}}/security-headers.conf;
        try_files $uri =404;
    }

    # ==========================================================================
    # TENANT CUSTOM SLOT 2: Custom Redirects & Application Rules
    # ==========================================================================
    include /etc/angie/tenant-custom/{{PRIMARY_DOMAIN}}/custom-rules.conf;

    # ==========================================================================
    # Crawlers & AI Agents Studio Endpoints (robots.txt & llms.txt)
    # ==========================================================================
    location = /robots.txt {
        try_files $uri /index.php?$args;
        access_log off;
        log_not_found off;
    }

    location = /llms.txt {
        try_files $uri /index.php?$args;
        access_log off;
        log_not_found off;
    }

    # ==========================================================================
    # WordPress Core Router
    # ==========================================================================
    location / {
        try_files $uri $uri/ /index.php?$args;
    }

    # ==========================================================================
    # Dynamic PHP-FPM Execution Tier & FastCGI Microcaching
    # ==========================================================================
    location ~ \.php$ {
        try_files $uri =404;
        fastcgi_split_path_info ^(.+\.php)(/.+)$;

        # Server-Side Includes (SSI) Engine for Hole-Punching (Scoped to PHP execution)
        ssi on;

        # Dynamic Execution Rate Limiting (LS-19)
        limit_req zone=perip burst=40 nodelay;

        # Microcache / Page Cache Bypass Logic
        set $skip_cache 0;
        if ($site_cache_enabled = 0) {
            set $skip_cache 1;
        }
        if ($request_method = POST) {
            set $skip_cache 1;
        }
        if ($query_string != "") {
            set $skip_cache 1;
        }
        if ($http_cookie ~* "comment_author|wordpress_[a-f0-9]+|wp-postpass|wordpress_no_cache|wordpress_logged_in|woocommerce_items_in_cart|woocommerce_cart_hash|wp_woocommerce_session") {
            set $skip_cache 1;
        }
        if ($request_uri ~* "/wp-admin/|/wp-json/|/xmlrpc.php|wp-.*.php|/feed/|index.php|sitemap(_index)?.xml|/cart.*|/checkout.*|/my-account.*") {
            set $skip_cache 1;
        }

        # FastCGI Dedicated Cache Tier with Anti-Thundering Locks & Background Update
        fastcgi_cache CACHE_{{ZONE_KEY}};
        fastcgi_cache_bypass $skip_cache;
        fastcgi_no_cache $skip_cache $nocache_response;
        fastcgi_cache_valid 200 60m;
        fastcgi_cache_use_stale error timeout updating invalid_header http_500 http_503;
        fastcgi_cache_background_update on;
        fastcgi_cache_lock on;
        fastcgi_cache_lock_timeout 5s;
        add_header X-Microcache $upstream_cache_status always;

        # Upstream Unix Socket
        fastcgi_pass {{TARGET_SOCKET}};
        fastcgi_index index.php;
        fastcgi_buffers 16 16k;
        fastcgi_buffer_size 32k;
        fastcgi_read_timeout 120s;

        include /etc/angie/fastcgi_params;
        fastcgi_param SCRIPT_FILENAME $realpath_root$fastcgi_script_name;
        fastcgi_param DOCUMENT_ROOT $realpath_root;
        fastcgi_param HTTPS $custom_https;

        # Modular Security Headers (Prevents add_header inheritance wipeout)
        include /etc/angie/tenant-custom/{{PRIMARY_DOMAIN}}/security-headers.conf;
    }

    # Internal Loopback Surgical Cache Purge Endpoint
    location ~ /leanstack-purge(/.*) {
        allow 127.0.0.1;
        deny all;
        {{PURGE_DIRECTIVE}}
    }

    # Internal SSI / ESI Hole-Punching Subrequest Handler
    location /leanstack-esi/ {
        internal;
        include /etc/angie/fastcgi_params;
        fastcgi_pass {{TARGET_SOCKET}};
        fastcgi_param SCRIPT_FILENAME $realpath_root/wp-content/mu-plugins/leanstack-holepunch.php;
        fastcgi_param DOCUMENT_ROOT $realpath_root;
        fastcgi_param HTTPS $custom_https;
        fastcgi_param LEANSTACK_ESI_INTERNAL 1;
    }
}
