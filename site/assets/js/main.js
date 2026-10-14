/**
 * LeanStack Editorial & Interactive Engine (Vanilla JS)
 * Inspired by https://wp.cloud/ aesthetic and precision tooling
 */

document.addEventListener('DOMContentLoaded', () => {
  initAmbientOrbitalLattice();
  initClipboard();
  initCommandTabs();
  initTerminalTabs();
  initBenchmarkToggle();
  initDocSearch();
  initMobileNav();
  initCollapsibleFaq();
  initPipelineInspector();
  initConcurrencySimulator();
  initCacheArchitectureSimulator();
  initSsiAnatomySimulator();
  initRoiCalculator();
  initCliWorkflowTabs();
  initDynamicNginxInspector();
  initSharedInfraIsolationInspector();
});

/**
 * 1. Ambient Global Edge Lattice & Orbital Geometry
 * Refined, calm, high-precision architectural canvas inspired by wp.cloud.
 * Minimalist concentric orbital tracks, floating beacon nodes, and gentle particle telemetry.
 * Reacts smoothly to mouse movement with spring physics; click sends an expanding harmonic resonance wave.
 */
function initAmbientOrbitalLattice() {
  const canvas = document.getElementById('hero-canvas');
  if (!canvas) return;

  const ctx = canvas.getContext('2d');
  let width, height;

  // Camera & Mouse tracking with smooth spring lerp
  let mouseX = 0, mouseY = 0;
  let targetMouseX = 0, targetMouseY = 0;

  // Expanding harmonic ripple waves from clicks
  const ripples = [];

  function resize() {
    width = canvas.width = window.innerWidth;
    height = canvas.height = canvas.parentElement ? canvas.parentElement.offsetHeight : window.innerHeight;
  }

  window.addEventListener('resize', resize);
  resize();

  window.addEventListener('mousemove', (e) => {
    targetMouseX = (e.clientX - width / 2) * 0.15;
    targetMouseY = (e.clientY - height / 2) * 0.10;
  });

  // Clicking anywhere creates a calm harmonic ripple that illuminates beacon nodes
  window.addEventListener('click', (e) => {
    if (e.target.closest('button, a, input, [data-copy], .pipeline-node, input[type=range]')) return;
    const rect = canvas.getBoundingClientRect();
    ripples.push({
      x: e.clientX - rect.left,
      y: e.clientY - rect.top,
      radius: 5,
      maxRadius: Math.max(width, height) * 0.85,
      alpha: 0.35,
      speed: 8
    });
  });

  // Orbital Tracks Configuration
  const ringRadii = [140, 260, 420, 600, 820];

  // Geodesic Beacon Nodes (~24 nodes placed on mathematical orbit intervals)
  const nodes = [];
  ringRadii.forEach((r, ringIdx) => {
    const count = 4 + ringIdx * 2;
    for (let i = 0; i < count; i++) {
      const angle = (i / count) * Math.PI * 2 + (ringIdx * 0.35);
      nodes.push({
        ringIdx,
        radius: r,
        baseAngle: angle,
        angularSpeed: (0.0006 / (ringIdx + 1)) * (ringIdx % 2 === 0 ? 1 : -1),
        currentAngle: angle,
        pulseOffset: Math.random() * Math.PI * 2,
        isHub: Math.random() > 0.65,
        litAlpha: 0
      });
    }
  });

  // Telemetry Packets gliding along orbital rails
  const packets = [];
  for (let i = 0; i < 16; i++) {
    const ringIdx = i % ringRadii.length;
    packets.push({
      ringIdx,
      radius: ringRadii[ringIdx],
      angle: Math.random() * Math.PI * 2,
      speed: 0.002 + Math.random() * 0.003,
      size: 2.0 + Math.random() * 1.5,
      hue: Math.random() > 0.4 ? 'vermilion' : 'amber'
    });
  }

  let time = 0;

  function render() {
    ctx.clearRect(0, 0, width, height);

    time += 0.016;

    // Smooth camera inertia lerp
    mouseX += (targetMouseX - mouseX) * 0.04;
    mouseY += (targetMouseY - mouseY) * 0.04;

    const centerX = width / 2 + mouseX;
    const centerY = height * 0.48 + mouseY;

    // Update and draw ripples
    for (let rIdx = ripples.length - 1; rIdx >= 0; rIdx--) {
      const rip = ripples[rIdx];
      rip.radius += rip.speed;
      rip.alpha *= 0.96;

      ctx.save();
      ctx.beginPath();
      ctx.arc(rip.x, rip.y, rip.radius, 0, Math.PI * 2);
      ctx.strokeStyle = `rgba(247, 43, 0, ${rip.alpha * 0.7})`;
      ctx.lineWidth = 1.5;
      ctx.stroke();
      ctx.restore();

      if (rip.alpha < 0.01 || rip.radius > rip.maxRadius) {
        ripples.splice(rIdx, 1);
      }
    }

    // Draw concentric orbital rings with dashed styling
    ringRadii.forEach((r, idx) => {
      ctx.save();
      ctx.beginPath();
      ctx.arc(centerX, centerY, r, 0, Math.PI * 2);

      // Fine dashed or solid styling
      if (idx % 2 === 1) {
        ctx.setLineDash([4, 8]);
      } else {
        ctx.setLineDash([2, 14]);
      }

      ctx.lineWidth = 1;
      const ringAlpha = 0.07 - idx * 0.01;
      ctx.strokeStyle = idx === 1 ? `rgba(247, 43, 0, ${ringAlpha * 1.8})` : `rgba(247, 243, 242, ${ringAlpha})`;
      ctx.stroke();
      ctx.restore();
    });

    // Update & Render Beacon Nodes
    nodes.forEach(n => {
      n.currentAngle += n.angularSpeed;
      const nx = centerX + Math.cos(n.currentAngle) * n.radius;
      const ny = centerY + Math.sin(n.currentAngle) * n.radius * 0.72; // slight perspective tilt

      // Check for ripple intersection
      ripples.forEach(rip => {
        const dx = nx - rip.x;
        const dy = ny - rip.y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (Math.abs(dist - rip.radius) < 30) {
          n.litAlpha = 1.0;
        }
      });

      if (n.litAlpha > 0) n.litAlpha *= 0.94;

      const breathing = Math.sin(time * 2 + n.pulseOffset) * 0.5 + 0.5;
      const baseAlpha = 0.25 + breathing * 0.35 + n.litAlpha * 0.6;

      // Glow halo
      ctx.beginPath();
      const haloRadius = (n.isHub ? 12 : 7) + n.litAlpha * 8;
      ctx.arc(nx, ny, haloRadius, 0, Math.PI * 2);
      ctx.fillStyle = n.isHub || n.litAlpha > 0.2
        ? `rgba(247, 43, 0, ${baseAlpha * 0.18})`
        : `rgba(255, 105, 0, ${baseAlpha * 0.10})`;
      ctx.fill();

      // Node core
      ctx.beginPath();
      const coreRadius = (n.isHub ? 2.5 : 1.5) + (n.litAlpha > 0.1 ? 1 : 0);
      ctx.arc(nx, ny, coreRadius, 0, Math.PI * 2);
      ctx.fillStyle = n.isHub || n.litAlpha > 0.3
        ? `rgba(247, 43, 0, ${baseAlpha})`
        : `rgba(247, 243, 242, ${baseAlpha * 0.8})`;
      ctx.fill();
    });

    // Update & Render Telemetry Packets
    packets.forEach(p => {
      p.angle += p.speed;
      const px = centerX + Math.cos(p.angle) * p.radius;
      const py = centerY + Math.sin(p.angle) * p.radius * 0.72;

      ctx.beginPath();
      ctx.arc(px, py, p.size, 0, Math.PI * 2);
      ctx.fillStyle = p.hue === 'vermilion' ? 'rgba(247, 43, 0, 0.75)' : 'rgba(255, 105, 0, 0.75)';
      ctx.shadowColor = p.hue === 'vermilion' ? '#F72B00' : '#FF6900';
      ctx.shadowBlur = 6;
      ctx.fill();
      ctx.shadowBlur = 0; // reset
    });

    requestAnimationFrame(render);
  }

  requestAnimationFrame(render);
}

/**
 * 2. Clipboard Copy Helper with Toast Notification
 */
function initClipboard() {
  const copyButtons = document.querySelectorAll('[data-copy]');
  const toast = document.getElementById('copy-toast');
  const toastMsg = document.getElementById('toast-message');

  function showToast(text) {
    if (!toast) return;
    if (toastMsg) toastMsg.textContent = text || 'Copied to clipboard!';
    toast.classList.remove('opacity-0', 'pointer-events-none', '-translate-y-2');
    toast.classList.add('opacity-100', 'translate-y-0');

    setTimeout(() => {
      toast.classList.remove('opacity-100', 'translate-y-0');
      toast.classList.add('opacity-0', 'pointer-events-none', '-translate-y-2');
    }, 2200);
  }

  copyButtons.forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.preventDefault();
      const textToCopy = btn.getAttribute('data-copy');
      if (!textToCopy) return;

      try {
        await navigator.clipboard.writeText(textToCopy);
        const originalText = btn.innerHTML;
        btn.innerHTML = '<span>Copied!</span> <span class="font-bold">✓</span>';
        showToast('Command copied to clipboard!');
        setTimeout(() => {
          btn.innerHTML = originalText;
        }, 1800);
      } catch (err) {
        showToast('Failed to copy. Please copy manually.');
      }
    });
  });
}

/**
 * 3. Quick-Start Command Tabs (Install / Update / CLI Provision)
 */
function initCommandTabs() {
  const tabButtons = document.querySelectorAll('[data-install-tab]');
  const cmdText = document.getElementById('hero-cmd-text');
  const copyBtn = document.getElementById('hero-copy-btn');
  const hintEl = document.getElementById('hero-cmd-hint');

  const tabCommands = {
    install: {
      cmd: 'curl -fsSL https://leanstack.kuntalghosh.dev/install.sh | sudo bash',
      hint: '✨ Interactive Antigravity TUI probes CPU, L2 cache & derives optimal configuration.'
    },
    update: {
      cmd: 'curl -fsSL https://leanstack.kuntalghosh.dev/update.sh | sudo bash',
      hint: '⚡ Automated pre-flight snapshot, zero-downtime schema migration & tenant reconciliation.'
    },
    selfhost: {
      cmd: 'sudo lsctl wp:create --domain=example.com --profile=agency_woocommerce',
      hint: '🚀 Provision high-density WordPress site with wire-speed Angie microcaching in 3 seconds.'
    }
  };

  if (!tabButtons.length || !cmdText) return;

  tabButtons.forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const tabKey = btn.getAttribute('data-install-tab');
      const data = tabCommands[tabKey];
      if (!data) return;

      tabButtons.forEach(b => {
        b.classList.remove('bg-[#F72B00]', 'text-[#F7F3F2]', 'font-semibold');
        b.classList.add('text-[#A9A6A5]');
      });
      btn.classList.add('bg-[#F72B00]', 'text-[#F7F3F2]', 'font-semibold');
      btn.classList.remove('text-[#A9A6A5]');

      cmdText.textContent = data.cmd;
      if (copyBtn) copyBtn.setAttribute('data-copy', data.cmd);
      if (hintEl) hintEl.textContent = data.hint;
    });
  });
}

/**
 * 4. Terminal Interactive Tabs
 */
function initTerminalTabs() {
  const termButtons = document.querySelectorAll('[data-term-tab]');
  const termCode = document.getElementById('terminal-snippet-code');

  const snippets = {
    install: `# Automated Silicon-Aware Bootstrapper
curl -fsSL https://leanstack.kuntalghosh.dev/install.sh | sudo bash

# Output:
[1/7] Host Probing: 8 vCPUs (x86_64), 16GB RAM, NVMe SSD
[2/7] MariaDB Tuning: 8,192M Buffer Pool, 256KB sort/join buffers (L2 Cache Fitted)
[3/7] Angie Engine: Native HTTP/3 QUIC, 8G WAF & Post-Quantum ML-KEM TLS
✔ LeanStack Engine deployed in 48s. Active idle RAM: 14.8 MB.`,

    profile: `# Create high-performance agency profile
sudo lsctl profile:create --name=woocommerce_extreme \\
  --php=8.5 \\
  --workers=64 \\
  --fastcgi-cache=true \\
  --ssi=true \\
  --apcu=true

# Deploy tenant site using custom profile
sudo lsctl wp:create --domain=shop.example.com --profile=woocommerce_extreme`,

    doctor: `# Diagnostic Health & Memory Verification
sudo lsctl doctor

[CHECK] Linux Kernel: 6.8.0-45-generic (BBR Active, THP Disabled)
[CHECK] MariaDB QPS: 4,812 QPS (L2 Miss Rate: 0.04%, Locks: 0.18ms)
[CHECK] In-Memory Valkey: Socket /run/valkey/valkey.sock (<3µs latency)
[CHECK] Web Tier: Angie 1.7.0 (HTTP/3 QUIC 0-RTT Active)
[CHECK] Background Cron: ls-cron-queue timer healthy (0 lock collisions)
✔ System 100% operational. Zero degradation detected.`,

    update: `# Fleet-Wide Autonomous Zero-Downtime Upgrade
sudo lsctl update

>>> Step 1: Pre-flight Angie & PHP syntax integrity test... [PASS]
>>> Step 2: Atomic database snapshot capture... [PASS]
>>> Step 3: Git fast-forward & incremental schema migrations... [PASS]
>>> Step 4: Reconcile tenant MU-plugins & reload Angie gracefully... [PASS]
✔ Upgraded successfully with ZERO downtime.`
  };

  if (!termButtons.length || !termCode) return;

  termButtons.forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const tabKey = btn.getAttribute('data-term-tab');
      const snippet = snippets[tabKey];
      if (!snippet) return;

      termButtons.forEach(b => {
        b.classList.remove('bg-[#282422]', 'text-[#F7F3F2]');
        b.classList.add('text-[#A9A6A5]');
      });
      btn.classList.add('bg-[#282422]', 'text-[#F7F3F2]');
      btn.classList.remove('text-[#A9A6A5]');

      termCode.textContent = snippet;
    });
  });
}

/**
 * 5. Interactive Benchmark Matrix Switcher
 */
function initBenchmarkToggle() {
  const buttons = document.querySelectorAll('[data-bench-metric]');
  const container = document.getElementById('benchmark-chart-container');
  if (!buttons.length || !container) return;

  const benchmarkData = {
    memory: {
      title: 'Control Plane Idle Memory Footprint (Lower is Better)',
      subtitle: 'Physical RAM consumed when idle before running any customer sites.',
      items: [
        { name: 'LeanStack Control Plane', value: '14.8 MB', percent: 2, isLean: true, note: 'Decoupled event-driven CLI. Zero resident background bloat.' },
        { name: 'RunCloud Agent', value: '380 MB', percent: 21, isLean: false, note: 'Persistent Go/Python background telemetry agents.' },
        { name: 'CyberPanel (LiteSpeed Open)', value: '890 MB', percent: 48, isLean: false, note: 'Python Django daemon + background gunicorn processes.' },
        { name: 'CloudPanel v2', value: '1,420 MB', percent: 76, isLean: false, note: 'Persistent Node.js & Java memory stack.' },
        { name: 'Standard cPanel / WHM', value: '1,850 MB', percent: 100, isLean: false, note: 'Heavy multi-tier background services and legacy daemons.' }
      ]
    },
    qps: {
      title: 'Concurrent Database Query Throughput (Higher is Better)',
      subtitle: 'Sysbench MariaDB OLTP read/write benchmark under 256 parallel worker threads.',
      items: [
        { name: 'LeanStack (Silicon-Aligned MariaDB)', value: '4,812 QPS', percent: 100, isLean: true, note: '256KB CPU L2 cache fitted buffers + READ-COMMITTED isolation.' },
        { name: 'CloudPanel v2', value: '1,420 QPS', percent: 30, isLean: false, note: 'REPEATABLE-READ default causes next-key lock serialization.' },
        { name: 'RunCloud', value: '610 QPS', percent: 13, isLean: false, note: 'Stock MariaDB config without hardware cache alignment.' },
        { name: 'CyberPanel', value: '480 QPS', percent: 10, isLean: false, note: 'Lock wait contention under multi-user concurrency.' },
        { name: 'Standard cPanel', value: '237 QPS', percent: 5, isLean: false, note: '16MB sort buffers trash CPU L2 cache into slow RAM malloc churn.' }
      ]
    },
    ttfb: {
      title: 'Time to First Byte with Dynamic Cart (Lower is Better)',
      subtitle: 'Response latency for personalized page requests with live WooCommerce items in cart.',
      items: [
        { name: 'LeanStack (Universal SSI Hole-Punch)', value: '12 ms', percent: 8, isLean: true, note: '98% cached shell from RAM + 1.4ms micro-PHP cart hole-punch.' },
        { name: 'CyberPanel (LSCache ESI)', value: '85 ms', percent: 52, isLean: false, note: 'LiteSpeed ESI subrequest with partial PHP stack reload.' },
        { name: 'CloudPanel (Bypass Cache for Cart)', value: '145 ms', percent: 90, isLean: false, note: 'Bypasses page cache completely. Full WordPress theme/plugin boot.' },
        { name: 'RunCloud (Uncached Storefront)', value: '160 ms', percent: 96, isLean: false, note: 'Full PHP-FPM execution with 120+ WooCommerce DB queries.' },
        { name: 'Standard cPanel (No Microcache)', value: '190 ms', percent: 100, isLean: false, note: 'Apache prefork worker execution under concurrency.' }
      ]
    }
  };

  function renderBenchmark(metricKey) {
    const data = benchmarkData[metricKey];
    if (!data) return;

    let html = `
      <div class="mb-6">
        <h3 class="text-xl font-serif text-[#F7F3F2]">${data.title}</h3>
        <p class="text-xs text-[#A9A6A5] mt-1">${data.subtitle}</p>
      </div>
      <div class="space-y-4">
    `;

    data.items.forEach(item => {
      const fillClass = item.isLean ? 'benchmark-fill-lean' : 'benchmark-fill-other';
      const labelColor = item.isLean ? 'text-[#F7F3F2] font-semibold' : 'text-[#A9A6A5]';
      const valColor = item.isLean ? 'text-[#F72B00] font-bold font-mono' : 'text-[#A9A6A5] font-mono';
      const badge = item.isLean ? '<span class="badge-pill badge-vermilion ml-2 py-0.5 px-2">Fastest</span>' : '';

      html += `
        <div class="p-3.5 rounded-lg bg-[#1E1B19]/80 border border-[#332F2C] hover:border-[#4D4744] transition">
          <div class="flex flex-wrap items-center justify-between text-sm mb-1.5 gap-2">
            <span class="${labelColor} flex items-center">${item.name} ${badge}</span>
            <span class="${valColor} text-base">${item.value}</span>
          </div>
          <div class="benchmark-track mb-1.5">
            <div class="${fillClass}" style="width: ${item.percent}%"></div>
          </div>
          <p class="text-xs text-[#7A7674]">${item.note}</p>
        </div>
      `;
    });

    html += `</div>`;
    container.innerHTML = html;
  }

  buttons.forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const metric = btn.getAttribute('data-bench-metric');
      buttons.forEach(b => {
        b.classList.remove('bg-[#F72B00]/15', 'text-[#F7F3F2]', 'border-[#F72B00]');
        b.classList.add('text-[#A9A6A5]', 'border-[#332F2C]');
      });
      btn.classList.add('bg-[#F72B00]/15', 'text-[#F7F3F2]', 'border-[#F72B00]');
      btn.classList.remove('text-[#A9A6A5]', 'border-[#332F2C]');
      renderBenchmark(metric);
      if (window.LeanStackAnalytics) {
        window.LeanStackAnalytics.track('switch_benchmark_metric', { metric: metric }, 'interaction');
      }
    });
  });

  renderBenchmark('memory');
}

/**
 * 6. Interactive Documentation Instant Search
 */
function initDocSearch() {
  const searchInput = document.getElementById('doc-search');
  const docSections = document.querySelectorAll('.doc-section');
  const sidebarLinks = document.querySelectorAll('.doc-sidebar-link');
  if (!searchInput) return;

  let searchTimer = null;
  searchInput.addEventListener('input', () => {
    const query = searchInput.value.toLowerCase().trim();

    clearTimeout(searchTimer);
    if (query.length >= 3 && window.LeanStackAnalytics) {
      searchTimer = setTimeout(() => {
        window.LeanStackAnalytics.track('search_docs', { query: query }, 'search');
      }, 600);
    }

    if (!query) {
      docSections.forEach(sec => sec.style.display = 'block');
      sidebarLinks.forEach(link => link.style.display = 'flex');
      return;
    }

    docSections.forEach(section => {
      const text = section.textContent.toLowerCase();
      const match = text.includes(query);
      section.style.display = match ? 'block' : 'none';
    });

    sidebarLinks.forEach(link => {
      const text = link.textContent.toLowerCase();
      const match = text.includes(query);
      link.style.display = match ? 'flex' : 'none';
    });
  });
}

/**
 * 7. Mobile Navigation Drawer
 */
function initMobileNav() {
  const menuToggle = document.getElementById('mobile-menu-toggle');
  const mobileMenu = document.getElementById('mobile-menu');
  if (!menuToggle || !mobileMenu) return;

  menuToggle.addEventListener('click', () => {
    mobileMenu.classList.toggle('hidden');
  });
}

/**
 * 8. Collapsible FAQ & Transparency Accordion
 */
function initCollapsibleFaq() {
  const accordions = document.querySelectorAll('.faq-accordion-header');
  accordions.forEach(header => {
    header.addEventListener('click', () => {
      const content = header.nextElementSibling;
      const icon = header.querySelector('.faq-icon');
      if (!content) return;

      const isHidden = content.classList.contains('hidden');
      content.classList.toggle('hidden');

      if (icon) {
        icon.style.transform = isHidden ? 'rotate(180deg)' : 'rotate(0deg)';
      }
    });
  });
}

/**
 * 9. Interactive Request Pipeline & Architecture Inspector
 */
const pipelineData = {
  edge: {
    title: 'Layer 1: Cloudflare Edge Mesh & Real-IP Sync',
    badge: '0-RTT Transport',
    latency: '0.8 ms',
    desc: 'Automated daily synchronization of Cloudflare IPv4 & IPv6 CIDRs via ls-cf-sync.timer. Angie transparently restores real visitor IPs for rate limiting and audit logging.',
    code: `# Daily CIDR sync via /etc/systemd/system/ls-cf-sync.timer
set_real_ip_from 173.245.48.0/20;
set_real_ip_from 103.21.244.0/22;
real_ip_header CF-Connecting-IP;`
  },
  angie: {
    title: 'Layer 2: Angie HTTP/3 Server with PQC TLS',
    badge: 'Wire-Speed Transport',
    latency: '1.2 ms',
    desc: 'Mainline-derived Angie engine with native HTTP/3 QUIC 0-RTT over UDP 443, eliminating TCP head-of-line blocking. Armed with X25519MLKEM768 hybrid post-quantum key exchange and Jeff Starr 8G WAF.',
    code: `ssl_protocols TLSv1.3 TLSv1.2;
ssl_ecdh_curve X25519MLKEM768:X25519:secp384r1;
include /etc/angie/waf/8g.conf;
brotli on; brotli_comp_level 5;`
  },
  microcache: {
    title: 'Layer 3: Zero-Worker FastCGI Microcache',
    badge: '95% Traffic Offload',
    latency: '3.5 ms',
    desc: 'Each domain is provisioned with an isolated cache zone (CACHE_domain). Invalidation computes the exact MD5 levels=1:2 path for surgical unlinking on post updates without touching other pages.',
    code: `fastcgi_cache_path /var/cache/angie/sites/example.com levels=1:2 
  keys_zone=CACHE_examplecom:20m inactive=7d max_size=512m;
fastcgi_cache_background_update on;
fastcgi_cache_use_stale error timeout updating;`
  },
  ssi: {
    title: 'Layer 4: Universal SSI Hole-Punching Engine',
    badge: 'Dynamic Hole-Punch',
    latency: '12 ms TTFB',
    desc: 'Angie native SSI hole-punches dynamic cart counts, user greetings, and CSRF nonces into cached shells. Bypassed automatically during visual page builder canvas editing (Bricks, Elementor, Divi).',
    code: `<!--# include virtual="/leanstack-esi/?action=cart_count" -->
<!--# include virtual="/leanstack-esi/?action=nonce" -->
<!--# include virtual="/leanstack-esi/?action=batch_price&ids=10,20" -->`
  },
  php: {
    title: 'Layer 5: Multi-Tenant POSIX Sandboxed PHP-FPM',
    badge: 'Zero-Trust Isolation',
    latency: '8.4 ms execution',
    desc: 'Every site runs as a separate POSIX user with strict open_basedir, chmod 600 wp-config.php, and complete PHP execution lockout in /wp-content/uploads/. Global opcache_reset() is blocked in disable_functions.',
    code: `[tenant_shop]
user = wp_shop
listen = /run/php/php8.5-fpm-shop.sock
php_admin_value[open_basedir] = /home/wp_shop/htdocs:/home/wp_shop/tmp:/tmp
php_admin_value[disable_functions] = exec,passthru,shell_exec,opcache_reset`
  },
  valkey: {
    title: 'Layer 6: Valkey Object Cache & Isolated APCu',
    badge: '<3µs In-Memory RAM',
    latency: '0.003 ms',
    desc: 'Valkey runs with a strict 10% RAM ceiling and volatile-lru eviction. APCu micro-caching deploys via leanstack-apcu.php with tenant cryptographic key prefixes, avoiding any conflict with Redis Object Cache.',
    code: `# Valkey Memory Constraint
maxmemory 10%
maxmemory-policy volatile-lru
# APCu Tenant Prefix: ls_<md5(AUTH_SALT.DB_NAME)>:`
  },
  mariadb: {
    title: 'Layer 7: Silicon-Aligned MariaDB High-QPS Engine',
    badge: '4,812 QPS Benchmark',
    latency: '0.21 ms query',
    desc: 'Thread buffers sized to 256KB to fit 100% inside CPU L2 cache lines, stopping malloc churn. Transaction isolation set to READ-COMMITTED, permanently killing InnoDB next-key gap locks.',
    code: `sort_buffer_size = 256K
join_buffer_size = 256K
transaction_isolation = READ-COMMITTED
innodb_flush_method = O_DIRECT
table_definition_cache = 4096`
  },
  cron: {
    title: 'Layer 8: In-House Anti-Thundering Cron Queue (ls-cron-queue)',
    badge: 'Zero-Visitor Latency',
    latency: 'Serialized 60s Timer',
    desc: 'Visitor-triggered wp-cron.php is permanently killed. Centralized systemd timer dispatches serialized WP-CLI jobs with execution timeouts and lock acquisition, eliminating race-condition lock storms.',
    code: `# /etc/systemd/system/ls-cron.timer
[Timer]
OnCalendar=*:*:00
AccuracySec=1s
# ExecStart=/usr/local/bin/ls-cron-queue --all`
  }
};

function initPipelineInspector() {
  const nodes = document.querySelectorAll('.pipeline-node');
  const titleEl = document.getElementById('pipeline-detail-title');
  const badgeEl = document.getElementById('pipeline-detail-badge');
  const latencyEl = document.getElementById('pipeline-detail-latency');
  const descEl = document.getElementById('pipeline-detail-desc');
  const codeEl = document.getElementById('pipeline-detail-code');

  if (!nodes.length || !titleEl || !descEl || !codeEl) return;

  nodes.forEach(node => {
    node.addEventListener('click', (e) => {
      e.preventDefault();
      const stageKey = node.getAttribute('data-stage');
      const data = pipelineData[stageKey];
      if (!data) return;

      nodes.forEach(n => n.classList.remove('active'));
      node.classList.add('active');

      titleEl.textContent = data.title;
      if (badgeEl) badgeEl.textContent = data.badge;
      if (latencyEl) latencyEl.textContent = data.latency;
      descEl.textContent = data.desc;
      codeEl.textContent = data.code;
    });
  });
}

/**
 * 10. Intuitive Concurrency Traffic Flow & Thread Saturation Simulator
 * Shows side-by-side visual lanes: Standard Hosting choking with workers saturated vs LeanStack running wire-speed.
 */
function initConcurrencySimulator() {
  const slider = document.getElementById('concurrency-slider');
  const threadsVal = document.getElementById('concurrency-val-threads');
  const presetBtns = document.querySelectorAll('[data-concurrency-preset]');

  // Traditional Lane Elements
  const tradWorkersContainer = document.getElementById('trad-workers-grid');
  const tradWorkerLabel = document.getElementById('trad-worker-status-label');
  const tradQueueBar = document.getElementById('trad-queue-bar');
  const tradQueueCount = document.getElementById('trad-queue-count');
  const tradLatency = document.getElementById('trad-latency-val');
  const tradStatusBadge = document.getElementById('trad-status-badge');
  const tradQps = document.getElementById('trad-qps-val');

  // LeanStack Lane Elements
  const leanWorkersContainer = document.getElementById('lean-workers-grid');
  const leanWorkerLabel = document.getElementById('lean-worker-status-label');
  const leanCacheSplit = document.getElementById('lean-cache-split-val');
  const leanLatency = document.getElementById('lean-latency-val');
  const leanQps = document.getElementById('lean-qps-val');

  if (!slider) return;

  function updateLanes(threads) {
    if (threadsVal) threadsVal.textContent = threads;

    // --- Traditional Stack Calculations ---
    const tradMaxWorkers = 16;
    const tradActive = Math.min(threads, tradMaxWorkers);
    const tradBacklog = Math.max(0, threads - tradMaxWorkers);

    if (tradWorkerLabel) {
      if (threads >= tradMaxWorkers) {
        tradWorkerLabel.innerHTML = `<span class="text-[#F72B00] font-bold">16/16 Saturated (100% Choked)</span>`;
      } else {
        tradWorkerLabel.innerHTML = `<span class="text-[#FFA04D] font-medium">${tradActive}/16 Active</span>`;
      }
    }

    if (tradWorkersContainer) {
      let slotsHtml = '';
      for (let i = 0; i < tradMaxWorkers; i++) {
        const isBusy = i < tradActive;
        const colorClass = isBusy ? 'worker-slot active-red' : 'worker-slot';
        slotsHtml += `<div class="${colorClass}"></div>`;
      }
      tradWorkersContainer.innerHTML = slotsHtml;
    }

    if (tradQueueBar && tradQueueCount) {
      const queuePct = Math.min(100, Math.round((tradBacklog / 240) * 100));
      tradQueueBar.style.width = `${Math.max(4, queuePct)}%`;
      if (tradBacklog > 0) {
        tradQueueCount.innerHTML = `<span class="text-[#F72B00] font-bold">${tradBacklog} requests stalled in backlog queue</span>`;
        tradQueueBar.className = 'h-full bg-[#F72B00] transition-all duration-200';
      } else {
        tradQueueCount.innerHTML = `<span class="text-[#7A7674]">0 requests queued (pool holding)</span>`;
        tradQueueBar.className = 'h-full bg-[#00D084] transition-all duration-200';
      }
    }

    if (tradLatency) {
      if (threads <= 16) tradLatency.textContent = '85 ms';
      else if (threads <= 64) tradLatency.textContent = '420 ms';
      else if (threads <= 128) tradLatency.textContent = '1,250 ms (Stalled)';
      else tradLatency.textContent = '2,480 ms (Timeout)';
    }

    if (tradStatusBadge) {
      if (threads > 48) {
        tradStatusBadge.className = 'badge-pill badge-vermilion py-0.5 px-2';
        tradStatusBadge.textContent = '504 GATEWAY TIMEOUT';
      } else {
        tradStatusBadge.className = 'badge-pill badge-amber py-0.5 px-2';
        tradStatusBadge.textContent = 'Degraded';
      }
    }

    if (tradQps) {
      const qps = threads > 32 ? Math.max(160, Math.round(330 - (threads - 32) * 1.4)) : Math.round(237 + threads * 3);
      tradQps.textContent = `${qps.toLocaleString()} QPS`;
    }

    // --- LeanStack Engine Calculations ---
    const cachedRequests = Math.round(threads * 0.95);
    const dynamicHits = Math.max(1, threads - cachedRequests);
    const leanActiveWorkers = Math.min(6, Math.max(1, Math.round(dynamicHits * 0.5)));

    if (leanWorkerLabel) {
      leanWorkerLabel.innerHTML = `<span class="text-[#00D084] font-medium">${leanActiveWorkers}/104 Active (Pool Free)</span>`;
    }

    if (leanWorkersContainer) {
      let leanSlotsHtml = '';
      for (let i = 0; i < 16; i++) {
        const isBusy = i < leanActiveWorkers;
        const colorClass = isBusy ? 'worker-slot active-green' : 'worker-slot';
        leanSlotsHtml += `<div class="${colorClass}"></div>`;
      }
      leanWorkersContainer.innerHTML = leanSlotsHtml;
    }

    if (leanCacheSplit) {
      leanCacheSplit.innerHTML = `<strong>${cachedRequests}</strong> requests (${Math.round((cachedRequests / threads) * 100)}%) served instantly from Angie FastCGI RAM in 2ms. Only <strong>${dynamicHits}</strong> dynamic requests touched PHP!`;
    }

    if (leanLatency) leanLatency.textContent = '12 ms TTFB';
    if (leanQps) leanQps.textContent = '4,812 QPS';
  }

  let sliderTrackTimer = null;
  slider.addEventListener('input', () => {
    const val = parseInt(slider.value, 10);
    updateLanes(val);
    clearTimeout(sliderTrackTimer);
    if (window.LeanStackAnalytics) {
      sliderTrackTimer = setTimeout(() => {
        window.LeanStackAnalytics.track('simulate_concurrency_slider', { threads: val }, 'interaction');
      }, 500);
    }
  });

  presetBtns.forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const val = parseInt(btn.getAttribute('data-concurrency-preset'), 10);
      slider.value = val;
      presetBtns.forEach(b => {
        b.classList.remove('bg-[#F72B00]', 'text-[#F7F3F2]', 'font-semibold');
        b.classList.add('bg-[#282422]', 'text-[#A9A6A5]');
      });
      btn.classList.add('bg-[#F72B00]', 'text-[#F7F3F2]', 'font-semibold');
      btn.classList.remove('bg-[#282422]', 'text-[#A9A6A5]');
      updateLanes(val);
      if (window.LeanStackAnalytics) {
        window.LeanStackAnalytics.track('select_concurrency_preset', { threads: val }, 'interaction');
      }
    });
  });

  updateLanes(128);
}

/**
 * 11. Intuitive Caching Architecture & Surgical Purge Simulator
 * Visually shows a 4-page website and contrasts standard blunt purge vs LeanStack single-URL invalidation.
 */
function initCacheArchitectureSimulator() {
  const globalFlushBtn = document.getElementById('cache-sim-global-flush-btn');
  const surgicalPurgeBtn = document.getElementById('cache-sim-surgical-btn');
  const resetBtn = document.getElementById('cache-sim-reset-btn');
  const logEl = document.getElementById('cache-sim-log-text');
  const pageCards = document.querySelectorAll('.cache-page-card');

  if (!globalFlushBtn || !surgicalPurgeBtn || !logEl) return;

  function resetAllCards() {
    pageCards.forEach(card => {
      card.className = 'cache-page-card warm p-4 rounded-xl';
      const badge = card.querySelector('.cache-status-pill');
      if (badge) {
        badge.className = 'cache-status-pill text-[11px] font-mono text-[#00D084] font-semibold';
        badge.textContent = '● WARM IN RAM (1.8ms)';
      }
    });
  }

  // 1. Standard Flush (The Thundering Herd Trap)
  globalFlushBtn.addEventListener('click', (e) => {
    e.preventDefault();
    pageCards.forEach(card => {
      card.className = 'cache-page-card purging p-4 rounded-xl';
      const badge = card.querySelector('.cache-status-pill');
      if (badge) {
        badge.className = 'cache-status-pill text-[11px] font-mono text-[#F72B00] font-semibold';
        badge.textContent = '✖ FLUSHED (0 KB)';
      }
    });

    setTimeout(() => {
      pageCards.forEach(card => {
        card.className = 'cache-page-card cold p-4 rounded-xl';
      });
    }, 600);

    logEl.innerHTML = `
<span class="text-[#F72B00] font-bold">[CATASTROPHIC CACHE STAMPEDE]</span>
1. Traditional plugin or panel executed: <code class="text-[#F7F3F2]">rm -rf /var/cache/*</code>
2. All 10,000 cached pages on the server were wiped simultaneously.
3. The next 500 incoming visitors hit PHP-FPM at the exact same millisecond.
4. Result: 100% PHP worker exhaustion, MySQL lock storm, and 504 Gateway Timeouts!
    `.trim();

    if (window.LeanStackAnalytics) {
      window.LeanStackAnalytics.track('simulate_cache_purge', { type: 'global_flush_stampede' }, 'interaction');
    }
  });

  // 2. LeanStack Surgical Invalidation (Zero-Worker Precision)
  surgicalPurgeBtn.addEventListener('click', (e) => {
    e.preventDefault();
    resetAllCards();

    const targetCard = document.getElementById('cache-card-product');
    if (!targetCard) return;

    targetCard.className = 'cache-page-card purging p-4 rounded-xl';
    const badge = targetCard.querySelector('.cache-status-pill');
    if (badge) {
      badge.className = 'cache-status-pill text-[11px] font-mono text-[#FF6900] font-semibold';
      badge.textContent = '⚡ UNLINKING MD5 HASH (0.18ms)';
    }

    logEl.innerHTML = `
<span class="text-[#00D084] font-bold">[SURGICAL FASTCGI INVALIDATION]</span>
1. WordPress hook <code class="text-[#F7F3F2]">save_post</code> triggered for post_id=1492 (/product/sneakers/).
2. leanstack-bridge.php calculated exact Angie FastCGI MD5 key: <code class="text-[#F7F3F2]">c4ca4238a0b9238...</code>
3. Level 1:2 cache file <code class="text-[#F7F3F2]">/var/cache/angie/sites/.../8/38/c4ca4238...</code> unlinked in 0.18ms!
4. ZERO THUNDERING HERD: Homepage, Catalog, and About pages stayed 100% warm in memory!
    `.trim();

    setTimeout(() => {
      targetCard.className = 'cache-page-card warm p-4 rounded-xl';
      if (badge) {
        badge.className = 'cache-status-pill text-[11px] font-mono text-[#00D084] font-semibold';
        badge.textContent = '● REWARMED IN RAM (1.8ms)';
      }
    }, 1200);

    if (window.LeanStackAnalytics) {
      window.LeanStackAnalytics.track('simulate_cache_purge', { type: 'surgical_invalidation_md5' }, 'interaction');
    }
  });

  if (resetBtn) {
    resetBtn.addEventListener('click', (e) => {
      e.preventDefault();
      resetAllCards();
      logEl.innerHTML = `[READY] Click either button above to contrast a traditional cache wipe against LeanStack's surgical single-URL unlinking.`;
    });
  }
}

/**
 * 12. Intuitive Universal SSI Dynamic Hole-Punching Anatomy
 * Visually shows a webpage split into 98% cached shell vs 2% dynamic holes.
 */
function initSsiAnatomySimulator() {
  const tradBtn = document.getElementById('ssi-mode-traditional-btn');
  const leanBtn = document.getElementById('ssi-mode-leanstack-btn');
  const simAddBtn = document.getElementById('ssi-sim-cart-add-btn');
  const resetBtn = document.getElementById('ssi-sim-reset-btn');

  const shellFrame = document.getElementById('ssi-shell-frame');
  const shellCallout = document.getElementById('ssi-shell-callout');
  const timelineBar = document.getElementById('ssi-timeline-bar');
  const ttfbVal = document.getElementById('ssi-ttfb-val');
  const explanationText = document.getElementById('ssi-explanation-text');

  const cartHole = document.getElementById('ssi-hole-cart');
  const cartBadge = document.getElementById('ssi-cart-counter');
  const stockBadge = document.getElementById('ssi-stock-counter');

  let currentMode = 'leanstack';
  const totalInventory = 10;
  let cartCount = 3;
  let stockCount = 7; // 3 in cart + 7 in stock = 10 total items

  if (!tradBtn || !leanBtn || !shellFrame) return;

  function updateInventoryDisplay() {
    if (cartBadge) cartBadge.textContent = cartCount;
    if (stockBadge) {
      if (stockCount === 0) {
        stockBadge.innerHTML = `<span class="text-[#F72B00] font-bold">Out of Stock (0 remaining)</span>`;
      } else {
        stockBadge.textContent = `${stockCount} units remaining`;
      }
    }
  }

  function setMode(mode) {
    currentMode = mode;
    if (window.LeanStackAnalytics) {
      window.LeanStackAnalytics.track('toggle_ssi_mode', { mode: mode }, 'interaction');
    }
    if (mode === 'traditional') {
      tradBtn.className = 'btn-vermilion text-xs py-2 px-3 font-semibold';
      leanBtn.className = 'btn-editorial-outline text-xs py-2 px-3 text-[#A9A6A5]';

      shellFrame.className = 'ssi-shell-frame uncached-alert p-6 transition-all';
      if (shellCallout) {
        shellCallout.innerHTML = `<span class="text-[#F72B00] font-bold">⚠ 100% UNCACHED PAYLOAD • 160ms TTFB (CACHE BYPASSED FOR USERS WITH CART)</span>`;
      }

      if (timelineBar) {
        timelineBar.innerHTML = `
          <div class="h-3 bg-[#F72B00] rounded-l" style="width: 55%" title="WP Core Boot: 85ms"></div>
          <div class="h-3 bg-[#FF6900]" style="width: 25%" title="35 Plugins: 40ms"></div>
          <div class="h-3 bg-[#FFA04D] rounded-r" style="width: 20%" title="112 DB Queries: 35ms"></div>
        `;
      }

      if (ttfbVal) ttfbVal.innerHTML = `<span class="text-[#F72B00]">160 ms TTFB</span>`;

      if (explanationText) {
        explanationText.innerHTML = `
          <span class="text-[#F72B00] font-bold">The Traditional Flaw:</span> Because the visitor has an item in cart, Nginx/CloudPanel completely bypasses the page cache. Every page reload forces WordPress to boot from scratch, load 35 plugins, and execute 112 SQL queries, locking a PHP-FPM worker for 160ms.
        `;
      }
    } else {
      leanBtn.className = 'btn-vermilion text-xs py-2 px-3 font-semibold';
      tradBtn.className = 'btn-editorial-outline text-xs py-2 px-3 text-[#A9A6A5]';

      shellFrame.className = 'ssi-shell-frame p-6 transition-all';
      if (shellCallout) {
        shellCallout.innerHTML = `<span class="text-[#00D084] font-bold">98% CACHED SHELL SERVED FROM ANGIE RAM (2ms) • ZERO PHP THEME OVERHEAD</span>`;
      }

      if (timelineBar) {
        timelineBar.innerHTML = `
          <div class="h-3 bg-[#00D084] rounded-l" style="width: 40%" title="Angie RAM Shell: 2ms"></div>
          <div class="h-3 bg-[#F72B00] rounded-r" style="width: 60%" title="Micro-PHP Hole-Punch: 3ms"></div>
        `;
      }

      if (ttfbVal) ttfbVal.innerHTML = `<span class="text-[#00D084]">5 ms TTFB</span>`;

      if (explanationText) {
        explanationText.innerHTML = `
          <span class="text-[#00D084] font-bold">The LeanStack Advantage:</span> Angie streams 98% of the page (480KB) directly from memory in 2ms. Only the tiny vermilion cutouts execute a 2KB micro-PHP script (<code class="text-[#F7F3F2]">leanstack-holepunch.php</code>) reading session tokens from Valkey in 3ms. Total TTFB: <strong>5ms</strong> with 95% PHP worker savings!
        `;
      }
    }
  }

  tradBtn.addEventListener('click', (e) => {
    e.preventDefault();
    setMode('traditional');
  });

  leanBtn.addEventListener('click', (e) => {
    e.preventDefault();
    setMode('leanstack');
  });

  if (simAddBtn) {
    simAddBtn.addEventListener('click', (e) => {
      e.preventDefault();

      if (stockCount <= 0) {
        if (explanationText) {
          explanationText.innerHTML = `
            <span class="text-[#FFA04D] font-bold">⚠ Inventory Limit Reached:</span> All ${totalInventory} units are already in the customer cart. Click <strong>"Reset Demo"</strong> to restock and test again.
          `;
        }
        return;
      }

      cartCount++;
      stockCount--;
      updateInventoryDisplay();

      if (cartHole) {
        cartHole.classList.add('pulsing');
        setTimeout(() => cartHole.classList.remove('pulsing'), 500);
      }

      if (currentMode === 'traditional') {
        shellFrame.className = 'ssi-shell-frame uncached-alert p-6 transition-all';
        if (ttfbVal) ttfbVal.innerHTML = `<span class="text-[#F72B00]">175 ms TTFB</span>`;
        if (timelineBar) {
          timelineBar.innerHTML = `
            <div class="h-3 bg-[#F72B00] rounded-l" style="width: 50%" title="WP Core Boot: 90ms"></div>
            <div class="h-3 bg-[#FF6900]" style="width: 25%" title="Plugins & Session: 45ms"></div>
            <div class="h-3 bg-[#FFA04D] rounded-r" style="width: 25%" title="124 DB Queries: 40ms"></div>
          `;
        }
        if (explanationText) {
          explanationText.innerHTML = `
            <span class="text-[#F72B00] font-bold">⚠ Traditional Cache Drop (175ms):</span> Adding an item to cart triggered a full uncached AJAX/page request. Entire 480KB HTML page was re-rendered from scratch via PHP-FPM, loading 35 plugins and running 124 database queries. 1 PHP worker locked for 175ms.
          `;
        }
      } else {
        shellFrame.className = 'ssi-shell-frame p-6 transition-all';
        if (ttfbVal) ttfbVal.innerHTML = `<span class="text-[#00D084]">5 ms TTFB</span>`;
        if (timelineBar) {
          timelineBar.innerHTML = `
            <div class="h-3 bg-[#00D084] rounded-l" style="width: 40%" title="Angie RAM Shell: 2ms"></div>
            <div class="h-3 bg-[#F72B00] rounded-r" style="width: 60%" title="Micro-PHP Hole-Punch: 3ms"></div>
          `;
        }
        if (explanationText) {
          explanationText.innerHTML = `
            <span class="text-[#00D084] font-bold">✔ Wire-Speed SSI Hole-Punch (1.4ms):</span> The cart badge incremented to <strong>${cartCount}</strong> and stock decremented to <strong>${stockCount}</strong>. The 480KB HTML shell stayed 100% warm in memory without being dropped or purged! Angie executed an isolated 2KB micro-PHP fragment in 1.4ms.
          `;
        }
      }

      if (window.LeanStackAnalytics) {
        window.LeanStackAnalytics.track('simulate_add_to_cart', {
          mode: currentMode,
          cartCount: cartCount,
          stockRemaining: stockCount,
          latencyMs: currentMode === 'traditional' ? 175 : 1.4
        }, 'conversion');
      }
    });
  }

  if (resetBtn) {
    resetBtn.addEventListener('click', (e) => {
      e.preventDefault();
      cartCount = 3;
      stockCount = 7;
      updateInventoryDisplay();
      setMode(currentMode);
    });
  }
}

/**
 * 13. Server Density Multiplier & Cloud Hosting ROI Calculator
 */
function initRoiCalculator() {
  const ramButtons = document.querySelectorAll('[data-roi-ram]');
  const tradSitesEl = document.getElementById('roi-trad-sites');
  const leanSitesEl = document.getElementById('roi-lean-sites');
  const multiplierEl = document.getElementById('roi-density-multiplier');
  const savingsEl = document.getElementById('roi-annual-savings');

  const plans = {
    '4': { trad: 8, lean: 35, mult: '4.3x', savings: '$1,440' },
    '8': { trad: 18, lean: 65, mult: '3.6x', savings: '$2,400' },
    '16': { trad: 36, lean: 130, mult: '3.6x', savings: '$4,800' },
    '32': { trad: 72, lean: 260, mult: '3.6x', savings: '$9,600' }
  };

  if (!ramButtons.length || !tradSitesEl || !leanSitesEl) return;

  ramButtons.forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const ramKey = btn.getAttribute('data-roi-ram');
      const data = plans[ramKey];
      if (!data) return;

      ramButtons.forEach(b => {
        b.classList.remove('bg-[#F72B00]', 'text-[#F7F3F2]', 'font-semibold');
        b.classList.add('bg-[#282422]', 'text-[#A9A6A5]');
      });
      btn.classList.add('bg-[#F72B00]', 'text-[#F7F3F2]', 'font-semibold');
      btn.classList.remove('bg-[#282422]', 'text-[#A9A6A5]');

      tradSitesEl.textContent = `${data.trad} Sites`;
      leanSitesEl.textContent = `${data.lean} Sites`;
      if (multiplierEl) multiplierEl.textContent = data.mult;
      if (savingsEl) savingsEl.textContent = `${data.savings} / yr`;

      if (window.LeanStackAnalytics) {
        window.LeanStackAnalytics.track('calculate_roi', {
          ramGB: parseInt(ramKey, 10),
          tradSites: data.trad,
          leanSites: data.lean,
          multiplier: data.mult,
          savings: data.savings
        }, 'conversion');
      }
    });
  });
}

/**
 * 14. Modern Developer Experience & Production CLI Workflow Tabs
 */
function initCliWorkflowTabs() {
  const tabs = document.querySelectorAll('[data-workflow-tab]');
  const terminalText = document.getElementById('workflow-terminal-text');

  const workflows = {
    create: `# Provision isolated agency site in 3 seconds
sudo lsctl wp:create \\
  --domain=shop.example.com \\
  --profile=agency_woocommerce \\
  --php=8.5 \\
  --ssl=letsencrypt

[INFO] Creating POSIX user wp_shop (UID 1042)...
[INFO] Sizing FastCGI cache zone: CACHE_shop (512MB RAM cap)...
[INFO] Generating Let's Encrypt certificate with automated ACME renewal...
[INFO] Deploying LeanStack Performance MU-plugins (bridge, holepunch, apcu)...
✔ Site deployed in 2.8s: https://shop.example.com`,

    nginx: `# Per-tenant custom rules with ZERO sudo privileges
# Tenant user: wp_shop
echo "client_max_body_size 64M;" > /home/wp_shop/nginx/custom-early.conf

# Inotify Gatekeeper Output (/var/log/lsctl/gatekeeper.log):
[INOTIFY] Detected modification on /home/wp_shop/nginx/custom-early.conf
[LINTER] Validating syntax via ls-nginx-linter...
[OK] angie syntax is valid. Executing zero-downtime graceful reload.
✔ Rule applied in 12ms. Zero manual service restart required.`,

    doctor: `# Comprehensive hardware telemetry & silicon audit
sudo lsctl doctor

Hardware Architecture:
  CPU: 8 vCPUs (x86_64) | L2 Cache: 512KB | L3 Cache: 16MB
  Storage: NVMe Block Device (O_DIRECT Active, double-buffering bypassed)
  Kernel: BBR Active, TCP Fast Open: 3, Transparent Huge Pages: DISABLED

Operational Tiers:
  MariaDB: 4,812 QPS (L2 Miss Rate: 0.04%, InnoDB Lock Wait: 0.18ms)
  Valkey: Socket connected at /run/valkey/valkey.sock (<3µs latency)
  Angie: HTTP/3 QUIC 0-RTT Active (PQC ML-KEM TLS Handshake enabled)
✔ System status: 100% HEALTHY. Zero bottleneck detected.`,

    upgrade: `# Fleet-wide autonomous zero-downtime upgrade
sudo lsctl update

>>> Step 1/4: Pre-flight Angie and PHP syntax check... [PASS]
>>> Step 2/4: Atomic snapshot capture -> /var/backups/lsctl/sites_pre_upgrade.db [PASS]
>>> Step 3/4: Git fast-forward & incremental schema migrations... [PASS]
>>> Step 4/4: Reconcile tenant MU-plugins & reload Angie gracefully... [PASS]
✔ Upgraded successfully with ZERO downtime.`
  };

  if (!tabs.length || !terminalText) return;

  tabs.forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const tabKey = btn.getAttribute('data-workflow-tab');
      const text = workflows[tabKey];
      if (!text) return;

      tabs.forEach(b => {
        b.classList.remove('bg-[#F72B00]', 'text-[#F7F3F2]', 'font-semibold');
        b.classList.add('bg-[#1E1B19]', 'text-[#A9A6A5]');
      });
      btn.classList.add('bg-[#F72B00]', 'text-[#F7F3F2]', 'font-semibold');
      btn.classList.remove('bg-[#1E1B19]', 'text-[#A9A6A5]');

      terminalText.textContent = text;
      if (window.LeanStackAnalytics) {
        window.LeanStackAnalytics.track('select_cli_workflow', { workflow: tabKey }, 'interaction');
      }
    });
  });
}

/**
 * 15. Interactive Dynamic Nginx & Inotify Gatekeeper Inspector
 */
const nginxSlotData = {
  early: {
    file: '/home/wp_shop/nginx/custom-early.conf',
    purpose: 'Evaluated before static asset caching. Ideal for image processors (WebP/AVIF rewrites) and maintenance locks.',
    code: `# WebP / AVIF Rewrites for Next-Gen Media
location ~* ^/wp-content/uploads/(.+)\.(png|jpe?g)$ {
    add_header Vary Accept;
    try_files $uri$webp_suffix $uri$avif_suffix $uri =404;
}`
  },
  rules: {
    file: '/home/wp_shop/nginx/custom-rules.conf',
    purpose: 'Evaluated before the WordPress router. Ideal for custom micro-proxies, vanity URLs, and 301 redirects.',
    code: `# Custom Agency Redirects & Reverse Proxies
location = /special-offer {
    return 301 https://shop.example.com/promo-2026/;
}
location /api/external/ {
    proxy_pass https://backend.internal:8080/;
}`
  },
  headers: {
    file: '/home/wp_shop/nginx/security-headers.conf',
    purpose: 'HTTP security headers and Content Security Policies, pre-configured for WebAssembly wasm-vips.',
    code: `# Modern Content Security Policy with Wasm Support
add_header X-Frame-Options "SAMEORIGIN" always;
add_header X-Content-Type-Options "nosniff" always;
add_header Content-Security-Policy "worker-src 'self' blob:; default-src 'self' 'unsafe-inline';" always;`
  }
};

function initDynamicNginxInspector() {
  const slotBtns = document.querySelectorAll('[data-nginx-slot]');
  const fileEl = document.getElementById('nginx-slot-file');
  const descEl = document.getElementById('nginx-slot-desc');
  const codeEl = document.getElementById('nginx-slot-code');
  const simulateBtn = document.getElementById('nginx-simulate-reload-btn');
  const liveLogEl = document.getElementById('nginx-gatekeeper-log');

  if (!slotBtns.length || !codeEl) return;

  slotBtns.forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const slotKey = btn.getAttribute('data-nginx-slot');
      const data = nginxSlotData[slotKey];
      if (!data) return;

      slotBtns.forEach(b => {
        b.classList.remove('bg-[#F72B00]', 'text-[#F7F3F2]');
        b.classList.add('bg-[#1E1B19]', 'text-[#A9A6A5]');
      });
      btn.classList.add('bg-[#F72B00]', 'text-[#F7F3F2]');
      btn.classList.remove('bg-[#1E1B19]', 'text-[#A9A6A5]');

      if (fileEl) fileEl.textContent = data.file;
      if (descEl) descEl.textContent = data.purpose;
      codeEl.textContent = data.code;
    });
  });

  if (simulateBtn && liveLogEl) {
    simulateBtn.addEventListener('click', (e) => {
      e.preventDefault();
      liveLogEl.innerHTML = `
<span class="text-[#FF6900]">[INOTIFY]</span> Detected write on /home/wp_shop/nginx/custom-early.conf
<span class="text-[#FF6900]">[LINTER]</span> Running ls-nginx-linter: staging test configuration...
<span class="text-[#00D084]">[SYNTAX]</span> ✔ angie syntax ok: test is successful.
<span class="text-[#00D084]">[RELOAD]</span> Executing graceful systemctl reload angie (0 dropped connections)...
<span class="text-[#00D084]">✔ RELOAD SUCCESSFUL IN 14ms. Zero manual Nginx restart required.</span>
      `.trim();
    });
  }
}

/**
 * 16. Interactive Multi-Tenant Shared Infrastructure Isolation Inspector
 */
function initSharedInfraIsolationInspector() {
  const purgeBtn = document.getElementById('isolation-test-purge-btn');
  const alphaStatus = document.getElementById('isolation-alpha-status');
  const betaStatus = document.getElementById('isolation-beta-status');
  const isolationLog = document.getElementById('isolation-log-output');

  if (!purgeBtn || !alphaStatus || !betaStatus) return;

  purgeBtn.addEventListener('click', (e) => {
    e.preventDefault();
    alphaStatus.innerHTML = '<span class="text-[#F72B00] animate-pulse">Bytecode Invalidated (0.2ms)</span>';
    betaStatus.innerHTML = '<span class="text-[#00D084] font-bold">100% WARM (Unaffected)</span>';

    if (isolationLog) {
      isolationLog.innerHTML = `
<span class="text-[#FF6900]">[OPCACHE]</span> opcache_reset() blocked (forbidden).
<span class="text-[#FF6900]">[FILTER]</span> Scoped to /home/wp_alpha/htdocs/: invalidated 14 scripts via opcache_invalidate().
<span class="text-[#00D084]">[APCU]</span> Deleted keys matching regex '^ls_9a4f...': Site Beta keys untouched.
<span class="text-[#00D084]">✔ Multi-tenant isolation verified: Site Beta suffered ZERO performance penalty.</span>
      `.trim();
    }
  });
}
