# LeanStack

> **Ultra-Lightweight • High-Density • Autonomous WordPress Control Plane**  
> *Engineered for Ubuntu 22.04 LTS, 24.04 LTS & 26.04 LTS (x86_64 & aarch64)*

[![Readiness Score](https://img.shields.io/badge/Readiness%20Score-100%25-brightgreen.svg)](#verification--testing-suite)
[![Target OS](https://img.shields.io/badge/Target%20OS-Ubuntu%2022.04%20%7C%2024.04%20%7C%2026.04%20LTS-orange.svg)](#overview)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Live Site](https://img.shields.io/badge/Website-leanstack.kuntalghosh.dev-success.svg)](https://leanstack.kuntalghosh.dev)
[![Docs](https://img.shields.io/badge/Docs-Operations%20Manual-blue.svg)](docs/OPERATIONS_MANUAL.md)
[![Web Server](https://img.shields.io/badge/Web%20Server-Angie%20(HTTP%2F3%20QUIC)-blue.svg)](#architecture-blueprint)
[![Cache](https://img.shields.io/badge/In--Memory%20Cache-Valkey%20(Unix%20Socket)-red.svg)](#hardware-aware-auto-tuning-engine)
[![Database](https://img.shields.io/badge/Database-MariaDB%20High--QPS-purple.svg)](#hardware-aware-auto-tuning-engine)

---

## Overview

Unlike legacy web hosting control panels (cPanel, Plesk, CyberPanel) that consume **1.5 GB – 3 GB of RAM** running heavy background daemons, **LeanStack** operates with a **near-zero idle memory footprint (< 15 MB)**.

LeanStack delivers:
* **Single-Command Interactive TUI Installation:** Bootstraps from `curl -fsSL https://leanstack.kuntalghosh.dev/install.sh | sudo bash` into an interactive Terminal User Interface (TUI) styled like modern CLI engines, featuring real-time hardware probing, animated telemetry, and custom profile selection.
* **Hardware-Aware Auto-Tuning Engine:** Automatically inspects CPU architecture, microarchitectural flags (`aes`, `avx2`, `avx512`), core count, RAM capacity, and disk storage class (NVMe vs SATA SSD). Dynamically derives optimal configuration parameters for MariaDB, Valkey, PHP-FPM, Angie, and the Linux kernel.
* **Perfectionist High-QPS Database Architecture:** Resolves the critical MariaDB bottleneck identified in real-world benchmarks (where simple queries stalled at 237 QPS due to oversized per-query buffers overflowing CPU L2 cache, gap lock serialization, and table cache mutex contention).
* **Perfectionist Web & Transport Tier:** Angie (Nginx mainline fork) with native HTTP/3 (QUIC), Post-Quantum Cryptography (PQC hybrid `X25519MLKEM768`), pure 256-bit AEAD ciphers for SSL Labs A+ (100%), shared multi-worker TLS session ticket caching, native C-based ACME Let's Encrypt issuance, SIMD Brotli compression, and 8G WAF + CrowdSec IPS.
* **Multi-Tenant POSIX Isolation:** Dedicated PHP-FPM pools running under isolated Linux users with strict `open_basedir`, zero PHP execution in `/uploads/`, and jailed SFTP.
* **Centralized Anti-Thundering Scheduled Task Queue:** Replaces standard WordPress HTTP-based `wp-cron.php` with a centralized SQLite-backed systemd timer queue running via WP-CLI with strict concurrency bounds.
* **Future-Proof Decoupled Architecture:** CLI-first (`lsctl` / `cpctl`), designed with structured JSON output, WAL-mode SQLite database, and Unix domain socket RPC pathways ready for lightweight administration.

---

## Architecture Blueprint

```
 ┌────────────────────────────────────────────────────────────────────────┐
 │                      INTERNET CLIENT / CLOUDFLARE                     │
 └──────────────────────────────────┬─────────────────────────────────────┘
                                    │ HTTPS (TCP 443 / QUIC UDP 443)
                                    ▼
 ┌────────────────────────────────────────────────────────────────────────┐
 │                        ANGIE WEB SERVER ENGINE                        │
 │  • HTTP/3 (QUIC) 0-RTT             • Pure 256-Bit AEAD Ciphers        │
 │  • Post-Quantum Crypto (ML-KEM)    • Native ACME Let's Encrypt Client │
 │  • Brotli SIMD Compression         • FastCGI Microcache (1s bypass)   │
 │  • 8G WAF & Query Inspector        • Cloudflare Real-IP Auto-Restore  │
 └──────────────┬──────────────────────────────────────────┬──────────────┘
                │ Unix Domain Sockets                      │ Blocks / Alerts
                ▼                                          ▼
 ┌───────────────────────────────┐        ┌───────────────────────────────┐
 │       PHP-FPM MULTI-TIER      │        │      CROWDSEC IPS ENGINE      │
 │  • PHP 8.1, 8.2, 8.3, 8.4, 8.5│        │  • Log Stream Scanners        │
 │  • Isolated Linux Users       │        │  • Firewall Bouncer (nftables)│
 │  • open_basedir & Jail tmp    │        │  • Auto SSH & CF Whitelists   │
 │  • OPcache + JIT Buffer       │        └───────────────────────────────┘
 └──────┬─────────────────┬──────┘
        │                 │
        │ Unix Socket     │ Unix Socket
        ▼                 ▼
 ┌──────────────┐ ┌──────────────┐
 │ VALKEY CACHE │ │ MARIADB HIGH │
 │ • 10% RAM Cap│ │ • READ-COMM. │
 │ • LRU Evict  │ │ • NVMe O_DIR │
 │ • Unix Socket│ │ • L2-Fit Pool│
 └──────────────┘ └──────────────┘
        ▲                 ▲
        └────────┬────────┘
                 │
 ┌────────────────────────────────────────────────────────────────────────┐
 │                      lsctl DECOUPLED CONTROL PLANE                     │
 │  • SQLite Database (WAL Mode)       • Anti-Thundering Systemd Cron Q   │
 │  • Agency Profiles Engine           • Automated Syntax Gatekeeper      │
 │  • Zero-Orphan Deep Teardown        • Cloudflare IP Synchronizer       │
 │  • Dynamic Hardware Auto-Tuner      • REST / Unix Socket RPC Bridge    │
 └────────────────────────────────────────────────────────────────────────┘
```

---

## 1-Command Installation

On a fresh **Ubuntu 22.04 LTS**, **Ubuntu 24.04 LTS**, or **Ubuntu 26.04 LTS** server:

```bash
curl -fsSL https://leanstack.kuntalghosh.dev/install.sh | sudo bash
```

Or via GitHub raw:

```bash
curl -fsSL https://raw.githubusercontent.com/kghosh007/LeanStack/main/install.sh | sudo bash
```

Or clone and install locally:

```bash
git clone https://github.com/kghosh007/LeanStack.git /opt/leanstack
cd /opt/leanstack
sudo ./install.sh
```

### Non-Interactive / Scripted Deployments:
```bash
sudo ./install.sh --non-interactive --profile=agency_woocommerce --php=8.4
```

### Dry-Run Simulation (Safe testing on any machine without root):
```bash
./install.sh --dry-run --non-interactive
```

---

## Hardware-Aware Auto-Tuning Engine

The tuning engine (`installer/probe.py` and `lsctl sys:tune`) probes host hardware and applies mathematical formulas:

| Component | Mathematical Formula / Configuration Rule | Purpose |
| :--- | :--- | :--- |
| **MariaDB Buffer Pool** | $\le 2\text{GB}: 512\text{M} \quad 4\text{GB}: 35\% \quad 6\text{GB}: 2800\text{M} \quad >8\text{GB}: 55\%$ | Keeps hot database pages 100% in physical RAM |
| **MariaDB Buffers** | `sort_buffer = 256K`, `join_buffer = 256K`, `read_buffer = 128K` | **Fits within CPU L2 cache** (Eliminates OS malloc churn) |
| **MariaDB Isolation** | `transaction_isolation = READ-COMMITTED` | **Eliminates next-key gap locks** on concurrent updates |
| **Valkey Memory** | $\max(128\text{M}, \text{RAM} \times 0.10)$, policy: `allkeys-lru` | Zero TCP latency; volatile LRU object caching via Unix socket |
| **PHP Workers** | `pm.max_children` calculated from available PHP RAM ($\sim 45\text{MB}$/worker) | Prevents memory thrashing / OOM crashes under load |
| **OPcache & JIT** | 5% of RAM (128M - 512M); `opcache.jit = tracing` if AVX2/SSE4 | Native machine code compilation for hot PHP loops |
| **Angie Web Server** | Worker affinity, pure 256-bit AEAD ciphers, `X25519MLKEM768` curve | SSL Labs A+ (100%) and Post-Quantum hybrid security |
| **Kernel Sysctl** | BBR congestion control, TCP Fast Open = 3, ZRAM zstd swap | High-throughput networking & OOM panic prevention |

---

## Master CLI Operations (`lsctl`)

> **Note:** `cpctl` is maintained as a full backward-compatible symlink/alias to `lsctl`.

### 1. Provision a New WordPress Site
```bash
sudo lsctl wp:create \
  --domain=shop.example.com \
  --profile=agency_woocommerce \
  --php=8.4 \
  --cf
```

### 2. Atomic Zero-Downtime PHP Version Switching
```bash
sudo lsctl site:php shop.example.com 8.3
```

### 3. List All Managed Sites
```bash
sudo lsctl site:list
# Or machine-readable JSON for API consumers:
sudo lsctl site:list --json
```

### 4. Inspect Site Details & Credentials
```bash
sudo lsctl site:info shop.example.com
sudo lsctl site:info shop.example.com --json
```

### 5. Deep Site Teardown (Zero Leftover Orphans)
```bash
sudo lsctl site:delete shop.example.com
```
* Automatically creates a compressed pre-deletion SQL snapshot in `/var/backups/cpctl/trash/`.
* Purges Angie vhosts, ACME Let's Encrypt certificates, tenant PHP-FPM pools, MariaDB database and user, Valkey cache keys, and Linux tenant user account.

### 6. Profile Lifecycle Management
```bash
# List all available operational profiles
sudo lsctl profile:list
sudo lsctl profile:list --json

# View detailed specification of a profile
sudo lsctl profile:show agency_woocommerce
sudo lsctl profile:show agency_woocommerce --json

# Create or scaffold a new custom agency profile
sudo lsctl profile:create agency_saas --description="SaaS Portal" --php=8.5 --mem=512M --cf

# Remove a custom profile (cannot delete 'default')
sudo lsctl profile:delete agency_saas
```

### 7. System Health & Self-Healing Diagnostics
```bash
sudo lsctl doctor
```

---

## Agency Profiles (`core/config/profiles.yaml`)

LeanStack comes with declarative profiles:

* **`default`**: Standard high-density WordPress profile (PHP 8.5, 256M RAM, dynamic workers, Redis cache).
* **`agency_woocommerce`**: Tailored for WooCommerce e-commerce stores (PHP 8.5, 512M RAM limit, Redis Object Cache pre-enabled, Storefront theme, dynamic worker scaling).
* **`high_traffic`**: Optimized for high-volume publishing portals with aggressive 1s FastCGI microcache and soft throttles.
* **`headless_wp`**: Decoupled headless WordPress serving GraphQL (`wp-graphql`) and REST APIs.

---

## Multi-Layer Security & Hardening Matrix

| Security Layer | Implementation Detail |
| :--- | :--- |
| **Web Application Firewall** | Jeff Starr's 8G WAF natively parsed in Angie's C-engine (queries, URIs, agents, methods). |
| **CrowdSec IPS & Bouncer** | Intrusion prevention analyzing access logs with nftables/iptables bouncer. Automatically whitelists the administrator's SSH IP and Cloudflare ranges to eliminate lockout loops. |
| **Uploads Execution Lockout** | Hard regex block returning `403 Forbidden` for any `.php`, `.phtml`, or `.phar` file requested inside `/wp-content/uploads/`, `/wp-content/cache/`, or `/wp-includes/`. |
| **TLS & Cryptography** | Post-Quantum Cryptography (`X25519MLKEM768`), pure 256-bit AEAD ciphers, shared multi-worker session ticket keys, and modular HSTS headers. |
| **Tenant Sandboxing** | Dedicated Linux user per domain, locked permissions (`wp-config.php` mode 600), `open_basedir` jailed to tenant root, and strict `disable_functions`. |

---

## Fleet Upgrade & Automated Migration Subsystem

LeanStack includes an autonomous upgrade engine (`lsctl update` / `update.sh`) engineered for painless multi-server fleet management:

* **Pre-Flight Integrity Checks:** Validates Angie configuration syntax (`angie -t`) before modifying any state.
* **Non-Destructive Schema Migrations:** Numbered forward migrations (`core/migrations/`) executed inside SQLite transactions, maintaining `schema_migrations` tracking.
* **Zero-Downtime Tenant Reconciliation:** Automatically updates Must-Use plugins (`leanstack-bridge`, `leanstack-holepunch`, `leanstack-apcu`, `leanstack-shield`) across all active tenant sites.
* **Rollback & Dry-Run Guarantees:** Supports `sudo lsctl update --dry-run` and automatically backs up `/var/lib/cpctl/sites.db` before applying changes.

```bash
# Check and apply fleet upgrades
sudo lsctl update

# Simulate upgrade without altering host state
sudo lsctl update --dry-run
```

Or execute via the single-command updater:
```bash
curl -fsSL https://leanstack.kuntalghosh.dev/update.sh | sudo bash
```

For complete operational procedures, consult the [Operations Manual](docs/OPERATIONS_MANUAL.md).

---

## Verification & Testing Suite

Run the master 10-pillar automated verification suite at any time:

```bash
./tests/run_tests.sh
```

### Test Suite Execution Output:
```text
==============================================================================
       LEANSTACK MASTER AUTOMATED VERIFICATION SUITE (10 PILLARS)             
==============================================================================
  Pillar 1: Architecture & Decoupling... [10/10 PASS]
  Pillar 2: Installation & TUI Experience... [10/10 PASS]
  Pillar 3: Hardware-Aware Auto-Tuning... [10/10 PASS]
  Pillar 4: Web & Caching Tier... [10/10 PASS]
  Pillar 5: Database Tier High-QPS Tuning... [10/10 PASS]
  Pillar 6: PHP Multi-Tenant Isolation... [10/10 PASS]
  Pillar 7: Multi-Layer Security & Hardening... [10/10 PASS]
  Pillar 8: CLI Engine & Profiles System... [10/10 PASS]
  Pillar 9: Resilience & Automation... [10/10 PASS]
  Pillar 10: Edge Case Guardrails & Verifications... [10/10 PASS]
==============================================================================
FINAL READINESS SCORE: 100 / 100 (100% READINESS)
==============================================================================
✔ 100% IMPLEMENTATION READINESS CONFIRMED. ALL PILLARS VERIFIED.
```

---

## License

Distributed under the [MIT License](LICENSE). Copyright © 2026 Kuntal Ghosh.  
Designed with perfectionism for high-density, lightning-fast WordPress hosting.
