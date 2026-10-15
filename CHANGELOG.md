# Changelog

All notable changes to the **LeanStack** project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added
- **Ultra-Lightweight Autonomous Watcher & Health Recovery Engine (`ls-watcher`)**: Introduced `core/bin/ls-watcher` (<3MB peak RAM, 0MB idle via systemd timer `ls-watcher.timer` every 60s) providing dual-tier autonomous health checks: Angie syntax check with automated quarantine of broken tenant virtual hosts (`/etc/angie/quarantine/`) and HTTP loopback probe; MariaDB and Valkey socket connectivity, ping probes, and stale socket/PID file cleanup; multi-version PHP-FPM pool socket verification against `sites.db`; automated self-healing of tenant filesystem permission drift; and emergency disk/inode vacuum (`journalctl` and temporary session cleanup when usage exceeds 90%). Governed by mutual-exclusion lock `/run/ls-maintenance.lock`.
- **Systemd Drop-In Overrides for Instant Crash Recovery**: Scaffolded systemd drop-in override configurations in `systemd/overrides/` (`angie.service.d`, `mariadb.service.d`, `valkey.service.d`, `php*-fpm.service.d`) enforcing `Restart=on-failure` and `RestartSec=2s` for instant sub-2s PID 1 crash recovery.
- **Zero-Downtime Autonomous Software & Security Updater (`ls-autoupdate`)**: Introduced `core/bin/ls-autoupdate` executed via `ls-autoupdate.timer` nightly at 03:30 with randomized delays: performs pre-flight syntax checks, atomic snapshot of database and configuration state (`/var/backups/lsctl/pre_upgrade_*`), non-interactive APT package upgrades targeting Angie, PHP, MariaDB, Valkey, and CrowdSec (`--force-confdef`, `--force-confold`), CrowdSec hub updates, WP-CLI binary update, LeanStack core migration, post-upgrade syntax verification with automated rollback on failure, and zero-downtime graceful reloads.
- **CLI Management Commands**: Added `watcher:status` (with `--json` support), `watcher:run`, and `update:auto` to `core/bin/lsctl`, exposing real-time timer status, service states, and maintenance locks. Integrated binary, service, timer, and drop-in override installation across `core/bin/ls-upgrade`, `scripts/phase4_angie_waf.sh`, and `installer/tui.py`.

### Fixed
- **Tenant Home Traversal Permissions & 404 Resolution**: Updated ownership and permission scaffolding in `core/bin/lsctl wp:create` to `chown "${USER_NAME}:www-data" "/home/${USER_NAME}"` with mode `750`, granting `www-data` group directory execution/traversal access into tenant homes without granting `others` any access. Eliminated 404 / 403 errors when Angie serves WordPress root and static assets. Added a 10-second polling check for Angie native ACME certificates (`/var/lib/angie/acme/${DOMAIN}*`) in `lsctl wp:create`, alerting administrators if Let's Encrypt certificates are actively issued vs finalizing in the background with self-signed fallback.
- **Angie Dynamic Cache-Purge Module & Resilient Purge Fallback**: Added `angie-module-cache-purge` package installation alongside `angie` and `angie-module-brotli` in `scripts/phase4_angie_waf.sh`. Automated dynamic module loader scaffolding (`/etc/angie/modules.d/cache-purge.conf`) and `include /etc/angie/modules.d/*.conf;` verification in `angie.conf` across `phase4_angie_waf.sh`, `core/bin/lsctl`, and `core/bin/ls-upgrade`. Introduced `{{PURGE_DIRECTIVE}}` placeholder in `vhost.conf.tpl`, allowing `lsctl` to dynamically substitute `fastcgi_cache_purge` when the module is present with automatic runtime fallback to `return 204;` if Angie syntax validation fails. Cleaned up orphaned module loaders when shared objects are absent. Added loopback surgical purge endpoint to Port 80 server block before redirecting to avoid 301 HTTPS interception on local WP cache purge requests.
- **8G Firewall HTTP PURGE Method Support**: Updated request method whitelist regex in `core/snippets/8g-firewall.conf` to explicitly permit the `PURGE` HTTP method (`GET|POST|HEAD|PUT|DELETE|OPTIONS|PURGE`), preventing 8G WAF from blocking legitimate cache invalidation requests with 405 Method Not Allowed.
- **Security Headers Deduplication in Virtual Host Template**: Eliminated duplicate inclusions of `ssl-headers.conf` in `core/templates/vhost.conf.tpl` across server block, `/wp-login.php`, static assets, and PHP execution blocks. All security headers (HSTS, nosniff, SAMEORIGIN, CSP, Permissions-Policy, Alt-Svc) are now exclusively managed through per-tenant `/etc/angie/tenant-custom/{{PRIMARY_DOMAIN}}/security-headers.conf`, eliminating duplicate response headers and maintaining tenant customizability. Added automatic reconciliation of missing tenant `security-headers.conf` files in `ls-upgrade`.
- **Correct Path Traversal in Holepunch SSI Endpoint**: Fixed fatal path resolution error in `core/templates/leanstack-holepunch.php.tpl` when handling `/leanstack-esi/` subrequests. Corrected directory traversal from `dirname( dirname( dirname( __DIR__ ) ) )` to `dirname( __DIR__, 2 ) . '/wp-load.php'`, ensuring proper resolution to `/home/<user>/htdocs/wp-load.php`.
- **SQLite Database Path Harmonization in Helper Scripts**: Harmonized SQLite database resolution in `core/bin/ls-gatekeeper` and `core/bin/ls-cron-queue`. Helper tools now sequentially evaluate `$LEANSTACK_DB` environment override, `/var/lib/lsctl/sites.db`, and fallback to `/var/lib/cpctl/sites.db`, eliminating silent execution exits when operating under modern `lsctl` filesystem layouts.
- **Cloudflare Real-IP Snippet File Permissions**: Explicitly enforced readable file permissions (`chmod 644 "$TARGET_SNIPPET"`) in `core/bin/ls-cf-sync` upon moving the temporary file generated by `mktemp`, preventing restrictive `0600` default permissions from blocking Angie worker access. Ensured snippet directory creation if missing.

### Planned
- Lightweight Go/Rust Unix socket RPC daemon for optional administrative dashboard.
- Automated multi-server fleet health telemetry aggregation.

---

## [1.2.0] - 2026-10-15 - *Codename: Hyperion*

### Added
- **Canonical Script Architecture**: Unified root `install.sh` and `update.sh` as primary repository entrypoints, with `site/install.sh` and `site/update.sh` maintained as web server symlinks.
- **Privacy-First Server Telemetry API (`/api/telemetry`)**:
  - Resilient backend supporting both SQLite (WAL mode) and automatic rolling JSON fallback.
  - Multi-endpoint client failover in `site/assets/js/analytics.js` (`/api/telemetry`, `/api/telemetry/`, `/api/telemetry/index.php`, `/api/telemetry.php`).
  - Cache-busting headers (`Cache-Control: private, no-store, no-cache`) to prevent LiteSpeed and Cloudflare from serving stale analytics.
  - Anonymized client IP logging conforming to GDPR standards.
- **Cryptographic Access Control**:
  - Replaced all plaintext password references in client JavaScript with SHA-256 cryptographic verification (`crypto.subtle.digest`).
  - Passcode validation against live server API on unlock with secure session persistence.
- **Mobile-First Responsive Analytics (`🔒 Analytics`)**:
  - Fluid 2-column mobile grid layout (`grid-cols-2 lg:grid-cols-4`) for audience metrics.
  - Responsive stacked key-value rows for hardware fingerprints and acquisition sources with `min-w-0` overflow prevention.
  - Dedicated mobile card stream (`md:hidden`) for real-time activity events.
- **Tailwind CSS Optimization & Purging**:
  - Integrated local Tailwind CLI build step compiling input CSS into a minified, standalone 38KB production stylesheet (`site/assets/css/styles.min.css`).
  - Completely eliminated runtime Tailwind CDN script (`cdn.tailwindcss.com`).
- **SEO & Accessibility Compliance**:
  - Added semantic `<main role="main">` landmark and skip-to-content accessibility navigation across all pages.
  - Strict descending heading hierarchy (`h1` → `h2` → `h3`) with zero skipped levels.
  - Deduplicated anchor texts across desktop, mobile navigation, and footers.
  - Page title lengths optimized to `< 55 characters` (`< 580px`).
  - Form input accessibility with explicit ARIA labelling on all controls.
  - Dedicated SVG and PNG favicon suite (16x16, 32x32, 180x180 Apple touch icon).
- **Automated Verification Test Suite**:
  - 10-Pillar Master Verification Suite (`tests/run_tests.sh`) validating architecture decoupling, hardware auto-tuning, Angie HTTP/3, Valkey Unix sockets, MariaDB QPS parameters, PHP multi-tenant isolation, 8G WAF, and CLI engine integrity.
  - GitHub Actions CI workflow (`.github/workflows/ci.yml`) executing on all pushes and pull requests.
- **Repository Health & Community Standards**:
  - Added [LICENSE](LICENSE) (MIT License), [SECURITY.md](SECURITY.md), [CONTRIBUTING.md](CONTRIBUTING.md), and structured GitHub issue form templates (`.github/ISSUE_TEMPLATE/`).

### Added
- **Pre-Flight System Environment Audit & Package Sanitization**: Visual 4-step wizard detecting pre-installed conflicting web servers (Angie, Nginx, Apache2), database engines (MariaDB, MySQL), cache tiers (Valkey, Redis), and PHP runtimes. Interactively or autonomously purges conflicting packages and stale repository lists (`/etc/apt/sources.list.d/*`) to guarantee a clean provisioning foundation.
- **Semi-Verbose Real-Time Process Streaming & Logging**: Real-time streaming of script execution milestones (`↳ sub-action`) inside the TUI progress spinner, paired with full persistent logging to `/var/log/leanstack-install.log`.

### Changed
- Standardized CLI syntax around `lsctl` (with `cpctl` maintained as a backward-compatible alias).
- Updated repository remote endpoints from `okio/leanstack` to `kghosh007/LeanStack`.
- Expanded operating system support matrix to officially include Ubuntu 26.04 LTS alongside 22.04 LTS and 24.04 LTS.

### Fixed
- **FastCGI Cache TTL Duration & SSI MIME Harmonization**: Fixed Angie compilation error `invalid time value "$site_cache_ttl"` in `core/templates/vhost.conf.tpl`. Angie and Nginx evaluate `fastcgi_cache_valid` at configuration compile-time and strictly reject runtime variables; configured literal baseline durations (`fastcgi_cache_valid 200 301 302 60m; fastcgi_cache_valid 404 1m;`), allowing granular per-response overrides via standard `X-Accel-Expires` headers. Removed redundant `ssi_types text/html;` to eliminate `[warn] duplicate MIME type "text/html"`.
- **8G WAF PCRE2 Regex Syntax & Tokenizer Fixes**: Fixed PCRE2 compilation errors in `core/snippets/8g-firewall.conf`. Corrected unescaped backslash that caused PCRE2 `missing closing parenthesis` error on directory traversal pattern (`"(\.\./|\.\.\\\\)"`) and added enclosing quotes around HTTP request method regex (`!~ "^(GET|POST|HEAD|PUT|DELETE|OPTIONS)$"`) to prevent Angie's `if (...)` tokenizer from treating regex parentheses as conditional delimiters. Added automated `test_pcre2_regex_syntax` test to the master test suite and automated `/etc/angie/snippets/` synchronization across `lsctl` and `ls-upgrade`.
- **Native Angie ACME Directives & Dynamic Certificate Mapping**: Replaced non-existent `acme_certificate` directive in `core/templates/vhost.conf.tpl` with Angie's official C-module syntax (`acme_client` in `http` context, `acme` directive in both port 80 and 443 server blocks). Implemented dynamic variable certificate mapping (`$acme_cert_<name>`, `$acme_cert_key_<name>`) with automatic self-signed fallback certificates (`/etc/angie/ssl/default.crt` and `default.key`), guaranteeing error-free virtual host compilation and immediate TLS operation without waiting for ACME domain challenge verification.
- **Port 443 / QUIC `reuseport` Conflict Resolution**: Relocated `reuseport` directive exclusively to the default catch-all server block in `scripts/phase4_angie_waf.sh` (`listen 443 ssl default_server reuseport; listen 443 quic default_server reuseport;`) and removed it from individual virtual host templates, preventing Angie syntax errors (`duplicate listen options for 0.0.0.0:443`) when provisioning multiple sites.
- **Alphanumeric Zone Key Normalization**: Fixed `ZONE_KEY` shell computation in `core/bin/lsctl` using `sed 's/[^a-z0-9]/_/g'` instead of `tr`, eliminating an accidental trailing underscore caused by shell newline translation (`staging_mfeasy_in_` → `staging_mfeasy_in`).
- **Automated Fallback SSL Generation & Recovery**: Added automatic generation of `/etc/angie/ssl/default.crt` and `default.key` across `scripts/phase4_angie_waf.sh`, `core/bin/lsctl`, and `core/bin/ls-upgrade`, ensuring self-healing on upgraded and freshly installed hosts.
- **Hardened Atomic Rollback**: Added `/etc/hosts` cleanup and automatic Angie reload on `wp:create` rollback traps, preventing orphaned hosts entries and stale virtual host configurations.
- **Eliminated SIGPIPE 141 Crash in `lsctl wp:create`**: Replaced fragile `tr < /dev/urandom | head` stream pipes with non-piped `openssl rand -hex` commands for tenant slugs, table prefixes, and salts. Under bash `set -eo pipefail`, `head` closing the pipe caused `tr` to receive `SIGPIPE` (exit code 141), terminating `lsctl wp:create` silently with zero error output.
- **Valkey Active Defragmentation Fatal Startup Crash**: Removed `activedefrag yes` and defrag threshold directives from `/etc/valkey/valkey.conf`. Packaged Valkey on Ubuntu/Debian is linked against distro `libjemalloc.so.2`, which does not support active defragmentation and triggered a fatal configuration parse crash on boot.
- **Valkey Service & Socket Permissions Harmonization**: Unified `valkey.service` and `valkey-server.service` systemd units via clean drop-in symlinks and aliases, adjusted `/run/valkey` `RuntimeDirectoryMode` to `0775`, and enrolled `www-data` in the `valkey` group to guarantee socket access without permission denial.
- **Zero-Dependency YAML Parser Fallback**: Embedded a native Python standard-library parser fallback for `core/config/profiles.yaml` across `lsctl` (`profile:list`, `profile:show`, `wp:create`), guaranteeing profile loading even on bare hosts without `python3-yaml`.
- **Resilient Binary Discovery & Multi-Service Doctor**: Updated `core/bin/lsctl` to dynamically resolve `php-fpm`, `php`, and `wp` across `/usr/bin`, `/usr/sbin`, and `/usr/local/bin`, and extended `lsctl doctor` to verify both `valkey` and `valkey-server` service names.
- **Distribution-Aware PHP Engine**: `scripts/phase5_php.sh` now probes Launchpad PPA availability against the host distribution codename (`$VERSION_CODENAME`) before adding `ppa:ondrej/php`. On Ubuntu 26.04 (Resolute), it automatically leverages official distribution repositories delivering native PHP 8.5 packages and removes broken PPA files.
- **Valkey Unit Link Conflict Resolution**: Cleans pre-existing package symlinks in `scripts/phase2_valkey.sh` prior to unit installation, preventing systemd `Refusing to operate on linked unit file` errors.
- **CrowdSec LAPI Bouncer Synchronization**: Staged CrowdSec daemon setup prior to firewall bouncer installation in `scripts/phase4_angie_waf.sh`, guaranteeing valid LAPI API key registration.
- Added pre-flight APT sanitization in `install.sh` prior to dependency checks to purge broken third-party and legacy Angie `.list` and `.sources` files, preventing fatal `apt-get update` errors on systems recovering from previous failed runs.
- Fixed Angie web server repository configuration and package installation failure by strictly adhering to the official Debian/Ubuntu procedure (direct binary OpenPGP signing key download without corrupted dearmor pass, `/etc/os-release` dynamically resolved repository path `${ID}/${VERSION_ID} ${VERSION_CODENAME}`, modular dynamic Brotli module loading, and conflicting port 80/443 service eviction).
- Fixed pipe execution crash (`BASH_SOURCE[0]: unbound variable` and `cd: null directory`) when running `install.sh` or `update.sh` via `curl | sudo bash` under `set -u`.
- Added interactive `/dev/tty` redirection so Python TUI can read terminal keystrokes when bootstrapped through a pipe.
- Fixed MariaDB query serialization bottleneck by switching default `transaction_isolation` to `READ-COMMITTED` and right-sizing buffers to fit within CPU L2 cache.
- Corrected typographical error (`vermillion` → `vermilion`).
- Resolved missing charset encoding header and meta tags across site templates.

### Security
- Locked data store access with server directives (`Require all denied` on `site/data/.htaccess`).
- Restricted direct access to `.sqlite`, `.db`, `.json`, and `.hash` files in `.htaccess`.
- Hard PHP execution lockout in `/wp-content/uploads/`, `/wp-content/cache/`, and `/wp-includes/`.

---

## [1.1.0] - 2026-10-13

### Added
- Angie (Nginx mainline fork) with native HTTP/3 (QUIC), Post-Quantum Cryptography (`X25519MLKEM768`), and SIMD Brotli compression.
- CrowdSec IPS integration with automatic IP whitelisting for administrator SSH sessions and Cloudflare IP blocks.
- Jeff Starr's 8G WAF natively parsed in Angie's C-engine.
- Valkey in-memory caching via low-latency Unix domain socket (`/run/valkey/valkey.sock`).
- Zero-downtime atomic PHP version switching (`lsctl site:php <domain> <version>`).

---

## [1.0.0] - 2026-10-10

### Added
- Initial release of LeanStack decoupled control plane.
- Multi-tenant POSIX isolation with dedicated PHP-FPM pools and Linux user sandboxing.
- Interactive Antigravity-style Terminal User Interface (TUI) installer (`installer/tui.py`).
- SQLite-backed central scheduled task queue replacing standard HTTP `wp-cron.php`.
- Declarative agency profiles (`default`, `agency_woocommerce`, `high_traffic`, `headless_wp`).
