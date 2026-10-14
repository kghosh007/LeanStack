# LeanStack Production Operations & Administration Manual

> **Ultra-Lightweight • High-Density • Autonomous WordPress Control Plane**  
> *Target Environments: Ubuntu 22.04 LTS & 24.04 LTS (x86_64 & aarch64)*  
> *Documentation Version: 1.1.0*

---

## Table of Contents
1. [Architecture Overview](#1-architecture-overview)
2. [Multi-Server Deployment from Private GitHub Repo](#2-multi-server-deployment-from-private-github-repo)
3. [Master Control Plane (`cpctl`) Operational Guide](#3-master-control-plane-cpctl-operational-guide)
4. [Caching & Performance Tier Operations](#4-caching--performance-tier-operations)
5. [Tenant Custom Configurations & Security Policies](#5-tenant-custom-configurations--security-policies)
6. [Scheduled Tasks & Background Watchers](#6-scheduled-tasks--background-watchers)
7. [Fleet Upgrade & Migration Subsystem](#7-fleet-upgrade--migration-subsystem)
8. [Backups, Disaster Recovery & Restores](#8-backups-disaster-recovery--restores)
9. [Troubleshooting & Emergency Reference](#9-troubleshooting--emergency-reference)

---

## 1. Architecture Overview

LeanStack replaces bloated hosting panels with a decoupled, event-driven, minimal-overhead control plane. It operates with a **near-zero idle memory footprint (< 15 MB RAM)** while hosting dozens of isolated WordPress sites per server.

```
┌────────────────────────────────────────────────────────────────────────┐
│                      INTERNET CLIENT / CLOUDFLARE                      │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │ HTTPS (TCP 443 / QUIC UDP 443)
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        ANGIE WEB SERVER ENGINE                         │
│  • HTTP/3 (QUIC 0-RTT)             • Pure 256-Bit AEAD Ciphers (A+)    │
│  • Post-Quantum Crypto (ML-KEM)    • Native ACME Let's Encrypt Client  │
│  • Server-Side Includes (SSI Engine)• Per-Tenant FastCGI Microcache    │
│  • 8G WAF & CrowdSec IPS Bouncer   • Cloudflare Real-IP Auto-Restore   │
└──────────────┬──────────────────────────────────────────┬──────────────┘
               │ Unix Domain Sockets                      │ Blocks / Alerts
               ▼                                          ▼
┌───────────────────────────────┐        ┌───────────────────────────────┐
│       PHP-FPM MULTI-TIER      │        │      CROWDSEC IPS ENGINE      │
│  • PHP 8.1, 8.2, 8.3, 8.4, 8.5│        │  • Log Stream Scanners        │
│  • Isolated Linux Users       │        │  • Firewall Bouncer (nftables)│
│  • Sandboxed open_basedir     │        │  • Auto SSH & CF Whitelists   │
│  • OPcache (Per-Tenant Purge) │        └───────────────────────────────┘
│  • APCu Tenant Microcache     │
└──────┬─────────────────┬──────┘
       │                 │
       │ Unix Socket     │ Unix Socket
       ▼                 ▼
┌──────────────┐ ┌──────────────┐
│ VALKEY CACHE │ │ MARIADB HIGH │
│ • 10% RAM Cap│ │ • READ-COMM. │
│ • LRU Evict  │ │ • NVMe O_DIR │
└──────────────┘ └──────────────┘
       ▲                 ▲
       └────────┬────────┘
                │
┌────────────────────────────────────────────────────────────────────────┐
│                      cpctl DECOUPLED CONTROL PLANE                     │
│  • SQLite Database (WAL Mode)       • Anti-Thundering Systemd Cron Q   │
│  • Agency Profiles Engine           • Automated Syntax Gatekeeper      │
│  • Zero-Orphan Deep Teardown        • Autonomous cp-upgrade Engine     │
│  • Hardware-Aware Auto-Tuner        • REST / Unix Socket RPC Bridge    │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Multi-Server Deployment from Private GitHub Repo

### 2.1 Server Prerequisites
Ensure your fresh target server meets these minimum requirements:
* **Operating System:** Clean Ubuntu 22.04 LTS or 24.04 LTS (Server Minimal or Standard).
* **CPU:** 1 vCPU minimum (2+ vCPUs recommended).
* **RAM:** 1 GB minimum (2+ GB recommended).
* **Network / Firewall:** Ports `22` (SSH), `80` (HTTP), and `443` (HTTPS TCP & UDP for HTTP/3 QUIC) open in cloud security groups (AWS, Hetzner, DigitalOcean, Linode, GCP, Vultr).

### 2.2 GitHub Authentication Setup on Target VPS

To deploy from your private GitHub repository on production VPS instances without embedding user passwords:

#### Method A: SSH Deploy Key (Recommended)
1. SSH into the fresh server as root:
   ```bash
   ssh root@your-server-ip
   ```
2. Generate an isolated ED25519 deploy key:
   ```bash
   ssh-keygen -t ed25519 -C "leanstack-deploy@$(hostname)" -f /root/.ssh/id_leanstack -N ""
   ```
3. Display the public key:
   ```bash
   cat /root/.ssh/id_leanstack.pub
   ```
4. In your GitHub repository:
   - Navigate to **Settings > Deploy keys > Add deploy key**.
   - Paste the public key, title it `Server: <hostname>`, and leave "Allow write access" **unchecked** (read-only is safest).
5. Configure SSH on the VPS to use this key for GitHub:
   ```bash
   cat >> /root/.ssh/config << 'EOF'
   Host github.com
       IdentityFile /root/.ssh/id_leanstack
       StrictHostKeyChecking accept-new
   EOF
   chmod 600 /root/.ssh/config
   ```
6. Clone the repository into `/opt/leanstack`:
   ```bash
   git clone git@github.com:<your-org-or-user>/<your-repo-name>.git /opt/leanstack
   ```

#### Method B: HTTPS with Fine-Grained Personal Access Token (PAT)
1. Create a fine-grained GitHub PAT with `Contents: Read-only` on the repository.
2. Clone the repository:
   ```bash
   git clone https://x-access-token:<YOUR_GITHUB_TOKEN>@github.com/<your-org-or-user>/<your-repo-name>.git /opt/leanstack
   ```

---

### 2.3 Running the Bootstrap Installer

Navigate into `/opt/leanstack` and launch the installer:

```bash
cd /opt/leanstack
sudo ./install.sh
```

#### Interactive Terminal Experience (TUI):
The installer probes host hardware, calculates optimal database/cache/PHP buffers, and presents an interactive runtime selector.

#### Unattended / Headless Cloud-Init Automation:
For scripted multi-server deployment (via Cloud-Init, Ansible, Terraform):
```bash
sudo /opt/leanstack/install.sh --non-interactive --php=8.5
```

#### Safe Dry-Run Validation:
Simulate the installation pipeline on any test machine without altering the system:
```bash
/opt/leanstack/install.sh --dry-run --non-interactive
```

---

## 3. Master Control Plane (`cpctl`) Operational Guide

The `cpctl` command-line utility controls all operational tasks. It is installed at `/usr/local/bin/cpctl`.

### 3.1 Agency Operational Profiles
LeanStack includes hardware-fitted profiles defined in `/etc/cpctl/profiles.yaml`:

```bash
# List all available operational profiles
sudo cpctl profile:list

# View profile details in JSON (for scripting/integrations)
sudo cpctl profile:list --json

# Inspect a specific profile
sudo cpctl profile:show agency_woocommerce
```

| Profile Name | Target Workload | PHP | Memory Limit | Pool Mode | Redis/Valkey | Cloudflare Ready |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `default` | General Agency Sites & Blogs | 8.5 | 256M | dynamic | Yes | Optional |
| `agency_woocommerce` | High-Throughput E-Commerce | 8.5 | 512M | dynamic | Yes | Yes |
| `high_traffic` | Media, Publishing & High-QPS | 8.5 | 512M | dynamic | Yes | Yes |
| `headless_wp` | Decoupled WP GraphQL / REST API | 8.5 | 256M | dynamic | Yes | Yes |

---

### 3.2 Site Provisioning (`wp:create` / `site:create`)

Provisioning a site is atomic: it creates an isolated POSIX Linux user, builds a dedicated PHP-FPM pool, provisions a MariaDB database and user, configures Valkey ACL credentials, generates cryptographic WordPress salts, issues Let's Encrypt SSL certificates, and compiles Angie vhost directives.

```bash
# 1. Standard agency site with default profile
sudo cpctl wp:create --domain=example.com

# 2. WooCommerce store with WooCommerce profile and Cloudflare Edge optimizations
sudo cpctl wp:create \
  --domain=shop.example.com \
  --profile=agency_woocommerce \
  --php=8.5 \
  --memory-limit=512M \
  --admin-user=storeadmin \
  --admin-email=ops@example.com \
  --site-title="Flagship Store" \
  --cf

# 3. Custom PHP version & custom memory limit
sudo cpctl wp:create \
  --domain=app.example.com \
  --php=8.4 \
  --memory-limit=384M \
  --admin-user=sysadmin
```

---

### 3.3 Site Inventory & Configuration Inspection

```bash
# List all registered sites with runtime details
sudo cpctl site:list

# Output site list in JSON
sudo cpctl site:list --json

# View complete site metadata, database credentials, table prefix, and paths
sudo cpctl site:info example.com

# Output site credentials in JSON
sudo cpctl site:info example.com --json
```

---

### 3.4 Zero-Downtime PHP Migration (`site:php`)

Switch a live site from one PHP runtime to another instantly (e.g., PHP 8.4 to 8.5) with atomic socket migration:

```bash
sudo cpctl site:php example.com 8.5
```
* **Process:** Stages new PHP-FPM pool, validates syntax via `php-fpm8.5 -t`, reloads pool, swaps Angie socket binding, and tests response. Zero requests are dropped.

---

### 3.5 Deep Site Teardown (`site:delete`)

Removes a site completely without leaving orphan databases, users, or cache directories:

```bash
sudo cpctl site:delete example.com
```
* **Teardown Process:**
  1. Creates safety backup of WordPress database in `/var/backups/cpctl/trash/`.
  2. Drops MariaDB database and user.
  3. Deletes Valkey ACL user credentials.
  4. Removes PHP-FPM pool and reloads PHP service.
  5. Purges Angie virtual host, SSL certificates, and tenant custom folders.
  6. Wipes per-site FastCGI cache directory `/var/cache/angie/sites/example.com`.
  7. Deletes POSIX user and home directory `/home/<user>`.
  8. Unregisters record from SQLite `sites.db`.

---

### 3.6 System Diagnostics (`doctor`)

Runs a deep audit across all core services, sockets, and storage tiers:

```bash
sudo cpctl doctor
```
Verifies:
* Angie web server, MariaDB, and Valkey service states.
* Core Unix domain sockets (`/run/valkey/valkey.sock`, `/run/mysqld/mysqld.sock`).
* Angie syntax validation (`angie -t`).
* Filesystem disk usage and available memory.

---

## 4. Caching & Performance Tier Operations

LeanStack implements a multi-tier caching architecture designed to eliminate bottlenecks from page generation to edge delivery.

### 4.1 FastCGI Page Cache (Angie Web Tier)
* **Storage Location:** `/var/cache/angie/sites/${DOMAIN}/`
* **Angie Cache Zone:** `CACHE_<sanitized_domain>`
* **Features:**
  - Dedicated zone per site: Purging Site A never clears Site B.
  - Anti-Thundering Locks (`fastcgi_cache_lock on;`): Protects database under traffic spikes.
  - Background Cache Updates (`fastcgi_cache_background_update on;`): Serves stale response while refreshing cache in background.
  - Automatic Bypass: Bypasses cache on `POST` requests, query parameters, logged-in cookies (`wordpress_logged_in_*`), WooCommerce cart cookies (`woocommerce_items_in_cart`), and checkout/admin URLs.

#### Managing FastCGI Cache from WordPress Admin:
Navigate to **Tools > LeanStack Cache**:
1. **Enable / Disable Cache**: Toggle caching On or Off instantly without server reload.
2. **TTL Selector**: Set default cache lifetime (60s, 300s, 1800s, 3600s, 86400s, 7 days).
3. **Surgical URL Invalidation**: Enter a URL (e.g. `https://example.com/products/item-1`) to calculate its MD5 `levels=1:2` path and delete only that cache entry.
4. **Flush Domain Cache**: Purge all cached files for the current site.

#### Automatic Invalidation Triggers:
The Must-Use plugin automatically purges the single-URL cache, homepage, and blog archives whenever a post or page is published, updated, or trashed (`save_post`, `deleted_post`, `wp_trash_post`).

---

### 4.2 Multi-Tenant PHP OPcache Safe Invalidation
* **Security Lockout:** `opcache_reset()` is permanently disabled in `pool.conf.tpl` `disable_functions` to prevent noisy-neighbor attacks where one site invalidates bytecode for the entire server.
* **Tenant-Scoped Invalidation:** In **Tools > LeanStack Cache > OPcache & APCu Purging**, click **Invalidate Tenant OPcache Scripts**.
* **Engine:** Loops through `opcache_get_status(true)`, matches only scripts whose file path starts with the requesting tenant's `ABSPATH`, and invalidates each script with `opcache_invalidate($path, true)`.

---

### 4.3 APCu Application Cache (<3µs RAM Latency)
* **Zero Conflict with Redis:** LeanStack deploys APCu acceleration via `wp-content/mu-plugins/leanstack-apcu.php` rather than dropping `object-cache.php`. This preserves full compatibility with Valkey and the `redis-cache` plugin.
* **Cryptographic Tenant Isolation:** Keys are automatically prefixed with `'ls_' . md5(AUTH_SALT . DB_NAME) . ':'`.
* **Tenant Flush:** In **Tools > LeanStack Cache**, click **Flush Tenant APCu Memory**. Uses `APCUIterator` with regex matching on the site prefix to delete only the requesting site's keys.

---

### 4.4 Universal Server-Side Includes (SSI) Hole-Punching
Dynamic elements on cached pages (e.g., nonces, customer names, cart counts) are refreshed on the server side using Angie's native `ssi on;` engine.

* **Engine:** `wp-content/mu-plugins/leanstack-holepunch.php`.
* **Page Builder Canvas Protection:** SSI tags are automatically bypassed when an editor is active (`?bricks=run`, `?elementor-preview=`, `?et_fb=`, `?fl_builder=`), preventing raw SSI tags from breaking visual builders.
* **Automatic Form Nonce Protection:** Automatically replaces WordPress `_wpnonce` hidden inputs with:
  ```html
  <!--# include virtual="/leanstack-esi/?action=nonce" -->
  ```
  Prevents "Session Expired" errors on cached contact forms and search bars.
* **Batched SSI Queries:** To prevent subrequest storms on product carousels (e.g., 20 cards per page), use the batched endpoint:
  ```html
  <!--# include virtual="/leanstack-esi/?action=batch_price&ids=101,102,103" -->
  ```
* **Custom Shortcode:**
  ```php
  [leanstack_ssi id="user_greeting"]
  ```

---

### 4.5 Cloudflare Edge CDN Integration
* **Credentials:** In **Tools > LeanStack Cache > Cloudflare Edge CDN**, enter your Cloudflare **Zone ID** and **API Token** (with `Zone.Cache Purge` permission).
* **Automatic Single-URL Sync:** Post updates automatically purge Cloudflare Edge CDN alongside local FastCGI cache.
* **Full Zone Flush:** Dispatches `{"purge_everything": true}` via Cloudflare API v4.

---

## 5. Tenant Custom Configurations & Security Policies

LeanStack eliminates monolithic Nginx configurations by providing safe, isolated slots per tenant under `/home/<user>/nginx/`:

### 5.1 Configuration Slots
1. **Slot 1 (`custom-early.conf`):** Evaluated immediately after 8G WAF and before static asset caching. Ideal for image processors (CompressX WebP/AVIF rewrites) and custom early intercepts.
2. **Slot 2 (`custom-rules.conf`):** Evaluated after static asset caching and before the WordPress core router. Ideal for custom URL redirects, reverse proxies, and rewrite rules.
3. **Cache Config (`cache-config.conf`):** Contains `$site_cache_enabled` and `$site_cache_ttl`.
4. **Security Headers (`security-headers.conf`):** HTTP security headers compiled directly into Angie directives.

### 5.2 Security Headers & WebAssembly Media Support
Configured via WordPress Admin under **Settings > Security Headers**:
* **Content Security Policy (CSP):** Automatically includes `worker-src 'self' blob:;`, required for client-side WebAssembly media processing (Wasm-vips in WordPress 7.1+) to prevent fallback to heavy server-side ImageMagick.
* **Framing & Clickjacking:** `X-Frame-Options SAMEORIGIN` or `DENY`.
* **MIME Sniffing:** `X-Content-Type-Options nosniff`.
* **XSS Defense:** `X-XSS-Protection 1; mode=block`.
* **Referrer Policy:** `strict-origin-when-cross-origin`.
* **Permissions Policy:** Prohibits unauthorized camera, microphone, and geolocation access.
* **Cross-Origin Policies (COOP & COEP):** Supports `Cross-Origin-Opener-Policy: same-origin` and `Cross-Origin-Embedder-Policy: require-corp` for multi-threaded WebAssembly `SharedArrayBuffer`.

### 5.3 Automated Syntax Gatekeeper
When a tenant edits rules in WordPress:
1. File is saved to `/home/<user>/nginx/`.
2. Status is set to `"pending"` in `.status.json`.
3. Background service `cp-gatekeeper.service` detects change and runs `cp-nginx-linter`.
4. If syntax is valid: atomic copy to `/etc/angie/tenant-custom/<domain>/` and graceful `angie -t && systemctl reload angie`.
5. If syntax is invalid: rejected immediately, production remains untouched, and error is displayed in WordPress Admin banner. 100% server uptime guaranteed.

---

## 6. Scheduled Tasks & Background Watchers

LeanStack uses native Linux systemd timers instead of visitor-triggered WordPress cron (`DISABLE_WP_CRON = true`).

| Service / Timer | Schedule | Description |
| :--- | :--- | :--- |
| `cp-cron.timer` | Every 60s | Executes `cp-cron-queue`. Dispatches serialized WP-CLI crons across all sites, eliminating CPU spikes. |
| `cp-cf-sync.timer` | Daily (03:00) | Executes `cp-cf-sync`. Fetches current Cloudflare IPv4 & IPv6 CIDR blocks, updates `cloudflare-realip.conf`, and reloads Angie. |
| `cp-gatekeeper.service` | Continuous Daemon | Inotify watcher that validates tenant custom rules and security headers via `cp-nginx-linter`. |

### Managing Services:
```bash
# Check cron timer status
systemctl status cp-cron.timer

# Manually trigger WP-Cron queue
sudo cpctl cron:run

# Manually trigger Cloudflare IP sync
sudo cpctl cf:sync

# Inspect Gatekeeper log stream
journalctl -u cp-gatekeeper -f
```

---

## 7. Fleet Upgrade & Migration Subsystem

The autonomous upgrade engine (`cp-upgrade`) ensures all future updates can be pulled from your private GitHub repository and applied across servers with zero downtime and automatic schema migration.

### 7.1 Running an Upgrade
```bash
# 1. Simulate upgrade steps (dry-run)
sudo cpctl update --dry-run

# 2. Execute full production upgrade
sudo cpctl update

# 3. Force re-run of migrations and template synchronization
sudo cpctl update --force
```

### 7.2 Upgrade Pipeline Actions
1. **Pre-Flight Health Audit:** Runs `angie -t` and tests database connectivity.
2. **Snapshot Backup:** Creates `/var/backups/cpctl/sites_pre_upgrade_<timestamp>.db`.
3. **Git Synchronization:** Performs `git fetch` and `git pull --ff-only` from origin.
4. **Forward Schema Migrations:** Inspects `core/migrations/` and executes unapplied migrations within transactions, updating the `schema_migrations` tracking table.
5. **Binary Deployment:** Installs updated executables into `/usr/local/bin/`.
6. **Template & Profile Sync:** Updates `/etc/cpctl/templates/` and merges profile definitions.
7. **Tenant Reconciliation (`sync-tenants`):**
   - Copies latest Must-Use plugins to all registered sites in `sites.db`.
   - Scaffolds any newly introduced configuration files (`cache-config.conf`, cache directories).
8. **Syntax Verification & Reload:** Runs `angie -t`. On success, reloads Angie and restarts Gatekeeper. On failure, triggers automatic rollback.
9. **Version Record:** Updates `/etc/leanstack/version.json`.

---

## 8. Backups, Disaster Recovery & Restores

### 8.1 SQLite Control Plane Database
The SQLite database stores all registered sites and credentials:
```bash
# Database location
/var/lib/cpctl/sites.db

# Manual backup
sqlite3 /var/lib/cpctl/sites.db ".backup '/var/backups/cpctl/manual_backup_$(date +%F).db'"
```

### 8.2 Per-Site Database & Filesystem Backups
```bash
# Export single WordPress database via WP-CLI
cd /home/<user>/htdocs
sudo -u <user> wp db export /home/<user>/backup.sql

# Create compressed archive of site files and database
tar -czf /var/backups/site_backup.tar.gz -C /home/<user> htdocs backup.sql
```

---

## 9. Troubleshooting & Emergency Reference

### 9.1 Essential Log Files
| Component | Log Path |
| :--- | :--- |
| **Angie Global Access** | `/var/log/angie/access.log` |
| **Angie Global Error** | `/var/log/angie/error.log` |
| **Tenant Access Log** | `/home/<user>/logs/access.log` |
| **Tenant Error Log** | `/home/<user>/logs/error.log` |
| **PHP Slow Log** | `/home/<user>/logs/php-slow.log` |
| **MariaDB Error Log** | `/var/log/mysql/error.log` |
| **Valkey Log** | `/var/log/valkey/valkey-server.log` |
| **CrowdSec Log** | `/var/log/crowdsec.log` |

### 9.2 Emergency Commands
```bash
# 1. Test Angie syntax
angie -t

# 2. Reload Angie
systemctl reload angie

# 3. Restart PHP-FPM pools
systemctl restart php8.5-fpm

# 4. Check CrowdSec blocked IPs
cscli decisions list

# 5. Whitelist an IP in CrowdSec
cscli decisions delete --ip <your-ip>

# 6. Reconcile all tenant MU-plugins
sudo cpctl sync-tenants

# 7. Comprehensive diagnostic check
sudo cpctl doctor
```
