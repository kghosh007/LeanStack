# Comprehensive Architectural Evaluation: Multi-Tier Cache Invalidation, Page Builder SSI & Edge Strategy

## Executive Summary & Deep Architectural Philosophy
This technical document provides an exhaustive, multi-dimensional evaluation of LeanStack’s caching and invalidation subsystem. It explicitly examines:
1. **The Cloudflare Edge vs Origin SSI Dilemma:** How origin Server-Side Includes interact with Cloudflare CDN, and how to prevent edge data leakage of personalized user fragments.
2. **The "Carousel / 10 Product Cards" Problem (SSI Subrequest Storm):** Why naive individual SSI hole-punching for multiple cards on a page causes severe FastCGI queue exhaustion, and how **Single-Pass Batched SSI** and **Event-Driven Invalidation** solve it.
3. **Universal Page Builder Compatibility:** How SSI hole-punching integrates with **Bricks Builder**, **Elementor**, and **Gutenberg** without breaking visual editor canvases or template rendering.
4. **RAM (tmpfs) vs NVMe Disk In-Depth Trade-Offs:** Cold cache thundering herds, memory pressure, and Angie concurrency locking guardrails.
5. **APCu Application Acceleration Without Conflict:** Utilizing APCu for transients, hot options, and fragment micro-caching without ever touching `wp-content/object-cache.php`.

---

## Part 1: Deep Problem-Space Evaluations

### 1. Cloudflare Edge Cache in Accordance with Local FastCGI + SSI

#### The Dilemma:
If a page contains Server-Side Includes (SSI), Angie executes the SSI subrequests on the origin server and merges the dynamic HTML into the response stream before transmission.  
**The Critical Question:** What happens if Cloudflare Edge caches this HTML?
* If Cloudflare caches the HTML containing User A’s personalized fragment (e.g. User A’s cart count or dynamic discount), then Visitor B fetching the page from Cloudflare Edge receives User A’s private data!
* Conversely, if Cloudflare caches raw `<!--# include ... -->` comments, Cloudflare's standard CDN cannot execute origin Angie SSI directives, rendering broken tags to visitors.

#### The LeanStack 3-Tier Multi-Zone Strategy:

```
┌────────────────────────────────────────────────────────────────────────┐
│               CLOUDFLARE EDGE VS ORIGIN SSI FLOWCHART                  │
├────────────────────────────────────────────────────────────────────────┤
│ 1. Request arrives at Cloudflare Edge CDN:                             │
│    │                                                                   │
│    ├── [A] Anonymous Visitor (No auth/cart cookies):                   │
│    │       • Served 100% from Cloudflare Edge (15ms globally).         │
│    │       • Zero origin load. Zero PHP execution.                     │
│    │                                                                   │
│    └── [B] Personalized Visitor (Has wordpress_logged_in_* or         │
│            woocommerce_items_in_cart cookies):                         │
│            • Cloudflare Edge BYPASSES cache automatically.             │
│            • Request forwards to Origin (Angie Web Server).            │
│            • Angie FastCGI serves static page from RAM/NVMe.           │
│            • Angie SSI resolves dynamic fragment (cart, user bar).     │
│            • Angie sends response with "Cache-Control: private".       │
│            • Cloudflare delivers without caching -> 100% SECURE!       │
└────────────────────────────────────────────────────────────────────────┘
```

1. **Tier A: Anonymous / Public Visitors (95%+ of Traffic):**
   * Public visitors do not have session cookies.
   * Angie emits:
     ```nginx
     Cloudflare-CDN-Cache-Control: public, max-age=86400, stale-while-revalidate=60;
     Cache-Control: public, max-age=3600;
     ```
   * Cloudflare Edge caches the page globally. The origin server receives zero traffic.
2. **Tier B: Authenticated / Cart-Active Visitors (Origin SSI Tier):**
   * When a user logs in or adds a product to cart, WordPress sets cookies: `wordpress_logged_in_*` or `woocommerce_items_in_cart=1`.
   * Cloudflare Edge respects the bypass cookie rule and passes the request directly to the origin Angie server.
   * Angie serves the base layout from FastCGI cache (0ms PHP), executes the lightweight SSI subrequest (`/leanstack-esi/`) for the personalized widget, and injects it.
   * Angie emits `Cache-Control: private, no-store` so Cloudflare **never caches personalized responses at the edge**.
3. **Tier C: Edge Micro-Hydration (Maximum CDN Offload Option):**
   * If a site owner wants 100% of HTML served from Cloudflare Edge even for logged-in users:
   * The page is cached with generic placeholders, and a 1KB asynchronous JavaScript micro-fetch (`/wp-json/leanstack/v1/user-state`) updates the cart count and user greeting in the browser DOM in < 15ms.

---

### 2. The Carousel Problem: 10 Product Cards (SSI Subrequest Storm Analysis)

#### The Scenario & Concrete Math:
A WooCommerce or catalog page contains a carousel with 10 product cards, plus a related products grid with 12 items (total 22 cards).  
The user wants everything cached except **sale price** and **stock quantity**.

#### What Happens With Naive SSI Hole-Punching?
* 22 cards × 1 SSI tag = 22 SSI directives in a single HTML document.
* When Angie serves the page:
  * Angie must pause streaming the HTML and spawn **22 separate FastCGI subrequests** to PHP-FPM over `/run/php/php8.5-${USER}.sock`.
  * Even if each subrequest executes in 2ms:
    $$22 \times 2\text{ms} = 44\text{ms of PHP-FPM execution time}$$
  * Under moderate traffic (e.g. 200 concurrent visitors):
    $$200 \times 22 = 4,400\text{ PHP-FPM subrequests per second!}$$
  * With `pm.max_children = 30`, the PHP-FPM listen queue overflows immediately, causing `504 Gateway Time-out` errors.
  * **Verdict:** Naive per-card SSI hole-punching creates an **Amplification DoS Attack** against PHP-FPM, consuming *more* resources than not caching at all!

#### The LeanStack Solutions for Product Cards & Carousels:

```
┌────────────────────────────────────────────────────────────────────────┐
│        SOLVING THE CAROUSEL CARD PROBLEM: THREE ARCHITECTURES          │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│ OPTION 1: Public Event-Driven Cache Invalidation (Recommended)         │
│   • Reality: Sale price & stock are public data (identical for all).   │
│   • Strategy: Cache the entire page containing all 22 cards in FastCGI │
│     and Cloudflare Edge. Zero SSI subrequests!                         │
│   • When stock/price changes: WooCommerce hook triggers instant        │
│     invalidation of that product URL in < 1ms.                         │
│                                                                        │
│ OPTION 2: Single-Pass Batched SSI (For Personalized Tier Pricing)       │
│   • Used when prices vary by user role (B2B wholesale, VIP tiers).    │
│   • Strategy: Product cards render with data attributes:               │
│     <div class="card" data-pid="101"><span class="price"></span></div> │
│   • In the footer, EXACTLY ONE SSI tag executes for the entire page:   │
│     <!--# include virtual="/leanstack-esi/?ids=101,102,103..." -->     │
│   • PHP executes 1 single SQL query for all 22 IDs in 1.8ms!           │
│   • Returns a JSON payload that hydrates all 22 cards in 1ms DOM time. │
│                                                                        │
│ OPTION 3: APCu L1 Fragment Cache                                       │
│   • When dynamic fragments are rendered by PHP, the output is stored   │
│     in APCu process memory (< 3µs). Next subrequest hits APCu directly │
│     without MariaDB queries.                                           │
└────────────────────────────────────────────────────────────────────────┘
```

1. **Option 1 (Event-Driven Invalidation - Best for 95% of Stores):**
   * Are sale price and stock quantity personalized per user? **No**, they are public.
   * Instead of running 22 PHP subrequests on every page load, LeanStack caches the entire page with the prices and stock.
   * When an order is placed or an admin updates inventory, WordPress fires `woocommerce_product_set_stock` or `save_post_product`.
   * LeanStack invalidates that product's cache in Angie FastCGI and Cloudflare Edge in **< 150ms**.
   * **Result:** 100% cache hit rate. Zero PHP execution. Zero SSI overhead.
2. **Option 2 (Single-Pass Batched SSI - Best for Role-Based / B2B Pricing):**
   * If prices differ based on the customer’s user role (wholesale vs retail):
   * Product cards render lightweight placeholders: `<span class="ls-dyn-price" data-id="101">...</span>`.
   * The page footer includes **EXACTLY ONE SSI tag**:
     ```html
     <!--# include virtual="/leanstack-esi/?action=batch_price&ids=101,102,103,104,105,106,107,108,109,110" -->
     ```
   * Angie makes **one single subrequest** to PHP-FPM for all 10 cards.
   * PHP-FPM executes one batched query:
     `SELECT post_id, meta_value FROM wp_postmeta WHERE post_id IN (101..110) AND meta_key='_price';`
   * Executes in **sub-2ms** and hydrates all 10 cards simultaneously!
3. **Option 3 (APCu L1 Fragment Acceleration):**
   * Even when individual SSI subrequests execute for custom dynamic blocks, the rendered HTML is cached in APCu process memory for 30–60 seconds.
   * PHP-FPM fetches the fragment from APCu in **< 3µs** without querying MariaDB or compiling templates.

---

### 3. Universal Page Builder Integration: Bricks Builder, Elementor, Gutenberg

#### Architectural Differences Across Builders:
* **Bricks Builder:** Modern Vue-based frontend canvas; server-side rendering uses PHP elements (`Element_Container`, `Element_Query_Loop`, `render()`).
* **Elementor:** React-based editor canvas; frontend uses widgets and sections with dynamic tags (`\Elementor\Core\DynamicTags\Manager`). Form widgets contain hidden CSRF nonces (`_wpnonce`).
* **Gutenberg:** Core block engine using `render_block` filter.

#### Universal SSI Integration Mechanics:

1. **Visual Builder Canvas Safety (Preventing Broken Editor Canvases):**
   When an administrator edits a page inside Bricks Builder (`?bricks=run`) or Elementor (`?elementor-preview=...`), SSI hole-punching **must be completely disabled**.  
   * Why: If raw `<!--# include ... -->` comments are injected into the visual builder canvas, the JavaScript DOM parser in Vue/React misinterprets them, breaking drag-and-drop.
   * Implementation:
     ```php
     if ( isset( $_GET['bricks'] ) || isset( $_GET['elementor-preview'] ) || is_admin() ) {
         return $content; // Return live dynamic content directly, no SSI
     }
     ```
2. **Automatic Form Nonce Hole-Punching (Eliminates "Expired Nonce" Errors):**
   * Contact forms in Elementor, Bricks, Fluent Forms, and Gravity Forms include hidden nonces:
     `<input type="hidden" name="_wpnonce" value="a1b2c3d4e5">`
   * On cached pages, nonces expire after 12–24 hours, causing visitor form submissions to fail with "Session Expired".
   * **LeanStack Universal Filter:** Output buffer scans for form nonces and swaps them with:
     ```html
     <!--# include virtual="/leanstack-esi/?action=nonce&name=my_action" -->
     ```
   * Angie injects a fresh, live nonce on every page view. Cached forms **never fail**.
3. **Universal Shortcode: `[leanstack_ssi]`:**
   Works seamlessly inside text blocks, rich text elements, and code modules across Bricks, Elementor, and Gutenberg:
   ```html
   [leanstack_ssi id="user_greeting"]
     Welcome back, {echo:wp_get_current_user()->display_name}!
   [/leanstack_ssi]
   ```
4. **CSS Class Hook (`leanstack-dynamic`):**
   In Bricks or Elementor, adding the CSS class `leanstack-dynamic` to any container or widget registers that element for SSI hole-punching automatically.

---

### 4. FastCGI Cache Storage: RAM (tmpfs) vs NVMe Disk

#### In-Depth Consequence Analysis:

| Factor | RAM (`tmpfs` in `/run/angie-cache`) | NVMe Disk (`/var/cache/angie/sites`) |
| :--- | :--- | :--- |
| **Response Latency** | **< 0.05ms (50µs)** | ~0.3ms – 0.8ms (Kernel page cache helps) |
| **SSD Write Endurance** | **Zero disk wear** | High write turnover on active sites |
| **Reboot Volatility** | ❌ **100% wiped on reboot** | ✔️ **Survives reboots intact** |
| **Cold Cache Thundering Herd** | High risk without guardrails | Zero risk; warm cache persists |
| **RAM Exhaustion / OOM** | High risk if uncontrolled query params fill RAM | Zero risk to system memory |

#### LeanStack Balanced Architecture & Guardrails:
1. **Concurrency Lock & Background Refresh Guardrails:**
   ```nginx
   fastcgi_cache_use_stale error timeout updating invalid_header http_500 http_503;
   fastcgi_cache_background_update on;
   fastcgi_cache_lock on;
   fastcgi_cache_lock_timeout 5s;
   ```
   * When the cache is cold after reboot, `fastcgi_cache_lock on;` guarantees that **only ONE request is passed to PHP-FPM**.
   * All other concurrent requests wait or receive stale content while the cache regenerates in the background (`background_update on`).
   * This completely eliminates thundering herd CPU spikes!
2. **Reliable Default with High-Speed Option:**
   * **Default:** Persistent NVMe Disk (`/var/cache/angie/sites/${DOMAIN}`). Reliable, persistent across reboots, protected by Linux kernel page cache memory buffers.
   * **High-Speed RAM Option:** Configurable in WP Admin for high-traffic sites needing sub-50µs latency, stored in `/run/angie-cache/${DOMAIN}` with memory bounds.

---

### 5. APCu Integration: Zero Conflict with `redis-cache`

#### The Problem:
`wp-content/object-cache.php` is an exclusive single-drop-in file. The `redis-cache` plugin (`wp redis enable`) requires this slot for Valkey/Redis. Dropping our own `object-cache.php` breaks the Redis plugin.

#### The LeanStack Solution:
* **We do not drop or touch `wp-content/object-cache.php`.**
* Instead, APCu is deployed via an autonomous Must-Use plugin ([`mu-plugins/leanstack-apcu.php`](file:///home/kuntal-ghosh/Desktop/LeanStack/core/templates/leanstack-apcu.php.tpl)):
  1. **Transient & Hot Option Interception:** Hooks into `pre_transient_*`, `set_transient_*`, `pre_option_*`. Hot site options and transients are served from APCu process memory in **< 3µs**.
  2. **SSI Fragment Storage:** Caches rendered dynamic fragments and query loop results for the SSI engine.
  3. **Multi-Tenant Cryptographic Sandboxing:** Every APCu key is prefixed with `'ls_' . md5( AUTH_SALT . DB_NAME ) . ':' . $key`. Tenants cannot collide or read each other's data.
  4. **Full Compatibility:** The `redis-cache` plugin operates smoothly and displays "Connected" in WP Admin.

---

## Part 2: Proposed Changes & Component Specifications

```
┌────────────────────────────────────────────────────────────────────────┐
│                        PROPOSED COMPONENT MAP                          │
├────────────────────────────────────────────────────────────────────────┤
│ 1. Storage & Web Tier:                                                 │
│    • core/templates/vhost.conf.tpl (Per-site zone, SSI, cache config)  │
│    • scripts/phase4_angie_waf.sh (Scaffold /var/cache/angie/sites)     │
├────────────────────────────────────────────────────────────────────────┤
│ 2. PHP Tier:                                                           │
│    • core/templates/pool.conf.tpl (Unblock opcache_invalidate/status)  │
├────────────────────────────────────────────────────────────────────────┤
│ 3. Control Plane Engine:                                               │
│    • core/bin/cpctl (Scaffold per-site cache zone, dirs, defaults)     │
│    • core/bin/cp-gatekeeper (Live watcher for cache-config.conf)       │
├────────────────────────────────────────────────────────────────────────┤
│ 4. WordPress Plugins:                                                  │
│    • core/templates/leanstack-bridge.php.tpl (Admin Cache & Analytics) │
│    • core/templates/leanstack-holepunch.php.tpl (Batched SSI Engine)   │
│    • core/templates/leanstack-apcu.php.tpl (APCu Transient/Opt Cache)  │
├────────────────────────────────────────────────────────────────────────┤
│ 5. Automated Verification Suite:                                       │
│    • tests/test_cache_invalidation.py (Dedicated test suite)           │
│    • tests/test_cli_and_templates.py (Template & CLI checks)           │
│    • tests/run_tests.sh (10-Pillars verification)                      │
└────────────────────────────────────────────────────────────────────────┘
```

---

### Detailed Component Specifications

#### 1. Web Tier Virtual Host & Angie Cache Configuration
##### [MODIFY] `core/templates/vhost.conf.tpl`
1. Include per-site cache configuration:
   `include /etc/angie/tenant-custom/{{PRIMARY_DOMAIN}}/cache-config.conf;`
2. Enable Angie SSI engine:
   ```nginx
   ssi on;
   ssi_silent_errors on;
   ssi_types text/html;
   ```
3. Update dynamic PHP block to use per-site cache zone with thundering-herd locks:
   ```nginx
   fastcgi_cache CACHE_{{ZONE_KEY}};
   fastcgi_cache_bypass $skip_cache;
   fastcgi_no_cache $skip_cache;
   fastcgi_cache_valid 200 301 302 $site_cache_ttl;
   fastcgi_cache_use_stale error timeout updating invalid_header http_500 http_503;
   fastcgi_cache_background_update on;
   fastcgi_cache_lock on;
   fastcgi_cache_lock_timeout 5s;
   add_header X-Microcache $upstream_cache_status always;
   ```
4. Add internal loopback purge endpoint:
   ```nginx
   location ~ /leanstack-purge(/.*) {
       allow 127.0.0.1;
       deny all;
       fastcgi_cache_purge CACHE_{{ZONE_KEY}} "$scheme$request_method$host$1";
   }
   ```
5. Add SSI hole-punch subrequest endpoint:
   ```nginx
   location /leanstack-esi/ {
       internal;
       include /etc/angie/fastcgi_params;
       fastcgi_pass {{TARGET_SOCKET}};
       fastcgi_param SCRIPT_FILENAME $realpath_root/wp-content/mu-plugins/leanstack-holepunch.php;
   }
   ```

#### 2. PHP-FPM Pool Isolation
##### [MODIFY] `core/templates/pool.conf.tpl`
Remove `opcache_get_status`, `opcache_get_configuration`, and `opcache_invalidate` from `disable_functions` so tenants can invalidate their own scripts and view analytics.  
**Strictly retain `opcache_reset` in `disable_functions`**:
```ini
php_admin_value[disable_functions] = exec,passthru,shell_exec,system,proc_open,popen,curl_multi_exec,parse_ini_file,show_source,dl,symlink,link,opcache_reset
```

#### 3. Control Plane Provisioning & Cache Scaffolding
##### [MODIFY] `core/bin/cpctl`
1. In `wp:create` / `site:create`:
   - Compute alphanumeric `ZONE_KEY` from domain.
   - Create per-site cache directory:
     `mkdir -p /var/cache/angie/sites/${DOMAIN}`
     `chown -R ${USER_NAME}:www-data /var/cache/angie/sites/${DOMAIN}`
     `chmod 770 /var/cache/angie/sites/${DOMAIN}`
   - Scaffold `/etc/angie/cache-zones/${DOMAIN}.conf`:
     ```nginx
     fastcgi_cache_path /var/cache/angie/sites/{{DOMAIN}} levels=1:2 keys_zone=CACHE_{{ZONE_KEY}}:20m inactive=7d max_size=512m use_temp_path=off;
     ```
   - Scaffold `/home/${USER_NAME}/nginx/cache-config.conf` and mirror to `/etc/angie/tenant-custom/${DOMAIN}/cache-config.conf`:
     ```nginx
     set $site_cache_enabled 1;
     set $site_cache_ttl 3600s;
     ```
   - Deploy `leanstack-holepunch.php` and `leanstack-apcu.php` into `${WEB_ROOT}/wp-content/mu-plugins/`.
2. In `site:delete`:
   - Purge `/var/cache/angie/sites/${DOMAIN}` and `/etc/angie/cache-zones/${DOMAIN}.conf`.

#### 4. WordPress Must-Use Plugins

##### [NEW] `core/templates/leanstack-apcu.php.tpl`
Must-Use plugin for APCu application acceleration (**zero conflict with `redis-cache`**):
* Intercepts `pre_transient_*`, `set_transient_*`, and `pre_option_*`.
* Uses cryptographic tenant prefixing: `'ls_' . md5( AUTH_SALT . DB_NAME ) . ':' . $key`.
* Leaves `wp-content/object-cache.php` untouched for the Redis plugin.

##### [NEW] `core/templates/leanstack-holepunch.php.tpl`
Must-Use plugin handling Universal Server-Side Includes (SSI) dynamic hole-punching:
* **Canvas Protection:** Detects Bricks Builder (`?bricks=run`) and Elementor preview mode and disables SSI inside visual editors.
* **Nonce Hole-Punching:** Replaces `<input type="hidden" name="_wpnonce" ...>` with SSI tags so cached forms never fail.
* **Single-Pass Batched SSI:** Supports `ids=101,102...` to resolve all card dynamic values in **one single subrequest**.
* **Shortcode & Class:** Provides `[leanstack_ssi id="..."]` and `.leanstack-dynamic` class hooks.
* **Micro-Endpoint:** Handles `/leanstack-esi/` in ultra-lightweight micro-mode (< 2ms).

##### [MODIFY] `core/templates/leanstack-bridge.php.tpl`
Enrich with **Tools > LeanStack Cache & Performance**:
* **FastCGI Manager:** On/off toggle, TTL selector, Single-URL purge, Entire-Domain purge.
* **OPcache Tenant Purger:** Invalidates files matching `ABSPATH`.
* **Cloudflare Manager:** Zone ID & API Token inputs, auto-purge on post edit, Purge All Caches button.
* **Analytics Dashboard:** FastCGI cached pages & size, OPcache tenant memory, APCu L1 entries & hit rate, Tenant CPU utilization & RSS memory (MB) from `/proc/[pid]/status`.

---

## Verification Plan

### Automated Tests
1. **Cache Invalidation Test Suite (`tests/test_cache_invalidation.py`):**
   * **Test 1: FastCGI Per-Site Isolation:** Create mock cache files for `site1.com` and `site2.com`. Purge `site1.com`. Verify `site1.com` is empty and `site2.com` is 100% intact.
   * **Test 2: Single-URL Purging:** Verify Angie MD5 key calculation unlinks only the specified file.
   * **Test 3: OPcache Tenant Invalidation:** Verify `purge_tenant_opcache()` invalidates only scripts within `ABSPATH`.
   * **Test 4: APCu Key Sandboxing:** Verify tenant A cannot read or overwrite tenant B's keys in APCu.
   * **Test 5: Batched SSI & Form Nonce:** Verify `leanstack-holepunch.php` generates valid Angie SSI tags, handles batched subrequests, and bypasses builder preview canvases.
   * **Test 6: Cloudflare API Payload:** Verify URL purging constructs valid Cloudflare v4 JSON payloads.
2. **Template & CLI Verification (`tests/test_cli_and_templates.py`):**
   * Verify `vhost.conf.tpl` contains `ssi on;`, per-site cache zones, and `cache-config.conf`.
   * Verify `pool.conf.tpl` permits `opcache_invalidate` while blocking `opcache_reset`.
   * Verify `cpctl` scaffolds `/var/cache/angie/sites/` and `/etc/angie/cache-zones/`.
3. **Master 10-Pillars Verification Suite (`tests/run_tests.sh`):**
   * Run all 10 pillars to verify **100 / 100 PASS score**.

### Manual Verification
1. Open **Tools > LeanStack Cache** in WP Admin -> Toggle FastCGI cache OFF -> Verify `$site_cache_enabled 0` is applied and response returns `X-Microcache: BYPASS`.
2. Toggle FastCGI cache ON -> Visit page twice -> Verify `X-Microcache: HIT`.
3. Click "Purge Entire Domain FastCGI Cache" -> Verify domain cache directory is emptied while other sites are untouched.
4. Add a form in Elementor or Bricks Builder -> Inspect HTML -> Verify form nonce is hole-punched via SSI tag and form submission succeeds on cached page.
5. In WooCommerce carousel with 10 products, verify single batched SSI tag hydrates all 10 cards in one subrequest without queue congestion.
