# Changelog

All notable changes to the **LeanStack** project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

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

### Changed
- Standardized CLI syntax around `lsctl` (with `cpctl` maintained as a backward-compatible alias).
- Updated repository remote endpoints from `okio/leanstack` to `kghosh007/LeanStack`.
- Expanded operating system support matrix to officially include Ubuntu 26.04 LTS alongside 22.04 LTS and 24.04 LTS.

### Fixed
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
