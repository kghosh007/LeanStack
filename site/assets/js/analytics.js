/**
 * LeanStack Privacy-First Visitor Intelligence & Telemetry Engine
 * Zero external tracking cookies. High-fidelity systems & visitor telemetry.
 * 
 * Captures visitor hardware/OS profiles, referral sources, engagement milestones,
 * and high-intent conversion actions (CLI copy, simulators, ROI calculator).
 * 
 * Accessible via `window.LeanStackAnalytics` with interactive console reporting,
 * exportable JSON logs, and a built-in telemetry viewer (`Alt + A`).
 */

(function (window, document) {
  'use strict';

  // Configuration
  const CONFIG = {
    endpoint: window.LEANSTACK_ANALYTICS_ENDPOINT || (typeof window !== 'undefined' && window.location && window.location.origin ? window.location.origin + '/api/telemetry' : 'https://leanstack.kuntalghosh.dev/api/telemetry'),
    storageKeyVid: 'ls_vid_v1',
    storageKeySid: 'ls_sid_v1',
    storageKeyHistory: 'ls_telemetry_history',
    maxStoredEvents: 80,
    sessionTimeoutMs: 30 * 60 * 1000, // 30 minutes
    heartbeatIntervalMs: 25000 // 25s engagement heartbeat
  };

  // State
  let visitorId = null;
  let sessionId = null;
  let isReturning = false;
  let visitCount = 1;
  let sessionStartTime = Date.now();
  let activeDwellSeconds = 0;
  let isTabActive = !document.hidden;
  let lastActiveTimestamp = Date.now();
  let highestScrollDepth = 0;
  const reachedScrollMilestones = new Set();
  const eventQueue = [];

  /**
   * Generates a high-entropy cryptographically random UUID v4
   */
  function generateUUID() {
    if (typeof crypto !== 'undefined' && crypto.randomUUID) {
      return crypto.randomUUID();
    }
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
      const r = (Math.random() * 16) | 0;
      const v = c === 'x' ? r : (r & 0x3) | 0x8;
      return v.toString(16);
    });
  }

  /**
   * Initializes or recovers persistent anonymous visitor ID and session ID
   */
  function initIdentity() {
    try {
      const storedVid = localStorage.getItem(CONFIG.storageKeyVid);
      const storedVisits = parseInt(localStorage.getItem('ls_visit_count') || '0', 10);
      const lastVisitTime = parseInt(localStorage.getItem('ls_last_seen') || '0', 10);
      const now = Date.now();

      if (storedVid) {
        visitorId = storedVid;
        isReturning = true;
        // Count as new visit if > 30 minutes since last seen
        if (now - lastVisitTime > CONFIG.sessionTimeoutMs) {
          visitCount = storedVisits + 1;
        } else {
          visitCount = storedVisits || 1;
        }
      } else {
        visitorId = 'ls_vid_' + generateUUID().slice(0, 16);
        isReturning = false;
        visitCount = 1;
        localStorage.setItem(CONFIG.storageKeyVid, visitorId);
        localStorage.setItem('ls_first_seen', now.toString());
      }

      localStorage.setItem('ls_visit_count', visitCount.toString());
      localStorage.setItem('ls_last_seen', now.toString());

      // Session ID (persists across page reloads in same tab, expires on close)
      const currentSid = sessionStorage.getItem(CONFIG.storageKeySid);
      if (currentSid) {
        sessionId = currentSid;
      } else {
        sessionId = 'ls_sid_' + generateUUID().slice(0, 16);
        sessionStorage.setItem(CONFIG.storageKeySid, sessionId);
        sessionStorage.setItem('ls_session_start', now.toString());
      }
    } catch (e) {
      // Fallback for restricted storage environments
      visitorId = visitorId || 'ls_vid_mem_' + Math.random().toString(36).slice(2, 10);
      sessionId = sessionId || 'ls_sid_mem_' + Math.random().toString(36).slice(2, 10);
    }
  }

  /**
   * Extracts clean acquisition channels and UTM parameters
   */
  function getAcquisitionContext() {
    const referrer = document.referrer || '';
    let referrerDomain = 'direct';
    if (referrer) {
      try {
        const parsed = new URL(referrer);
        referrerDomain = parsed.hostname.replace(/^www\./, '');
        if (referrerDomain === window.location.hostname) {
          referrerDomain = 'internal';
        }
      } catch (e) {
        referrerDomain = 'unknown';
      }
    }

    const searchParams = new URLSearchParams(window.location.search);
    const utm = {
      source: searchParams.get('utm_source') || null,
      medium: searchParams.get('utm_medium') || null,
      campaign: searchParams.get('utm_campaign') || null,
      term: searchParams.get('utm_term') || null,
      content: searchParams.get('utm_content') || null
    };

    return {
      referrerRaw: referrer || 'direct',
      referrerDomain: referrerDomain,
      isOrganicSearch: /google|bing|yahoo|duckduckgo|ecosia|yandex/i.test(referrerDomain),
      isSocial: /twitter|t\.co|x\.com|linkedin|reddit|facebook|hacker-news|ycombinator/i.test(referrerDomain),
      isDevCommunity: /github|gitlab|stackoverflow|dev\.to|medium/i.test(referrerDomain),
      utm: utm
    };
  }

  /**
   * Extracts detailed hardware, platform, and browser telemetry
   */
  function getEnvironmentContext() {
    const ua = navigator.userAgent || '';
    
    // Operating System detection
    let os = 'Unknown';
    if (/Android/i.test(ua)) os = 'Android';
    else if (/iPhone|iPad|iPod/i.test(ua)) os = 'iOS';
    else if (/Macintosh|Mac OS X/i.test(ua)) os = 'macOS';
    else if (/Windows NT/i.test(ua)) os = 'Windows';
    else if (/Linux/i.test(ua)) os = 'Linux';
    else if (/CrOS/i.test(ua)) os = 'ChromeOS';

    // Browser detection
    let browser = 'Unknown';
    if (/Brave/i.test(navigator.brave ? 'Brave' : '') || (navigator.userAgentData && navigator.userAgentData.brands && navigator.userAgentData.brands.some(b => b.brand === 'Brave'))) {
      browser = 'Brave';
    } else if (/Edg\//i.test(ua)) {
      browser = 'Edge';
    } else if (/OPR\/|Opera/i.test(ua)) {
      browser = 'Opera';
    } else if (/Chrome\/|CriOS\//i.test(ua) && !/Edg/i.test(ua)) {
      browser = 'Chrome';
    } else if (/Firefox\/|FxiOS\//i.test(ua)) {
      browser = 'Firefox';
    } else if (/Safari/i.test(ua) && !/Chrome|CriOS/i.test(ua)) {
      browser = 'Safari';
    }

    // Device classification
    let deviceType = 'desktop';
    const isTouch = ('ontouchstart' in window) || (navigator.maxTouchPoints > 0);
    const screenWidth = window.screen.width || 0;
    if (/Mobile|Android|iPhone|iPod/i.test(ua) || (isTouch && screenWidth < 768)) {
      deviceType = 'mobile';
    } else if (/iPad|Tablet/i.test(ua) || (isTouch && screenWidth >= 768 && screenWidth <= 1024)) {
      deviceType = 'tablet';
    }

    // Network connection telemetry (if supported)
    let connectionInfo = null;
    if (navigator.connection) {
      connectionInfo = {
        effectiveType: navigator.connection.effectiveType || 'unknown',
        downlink: navigator.connection.downlink || null,
        rtt: navigator.connection.rtt || null,
        saveData: !!navigator.connection.saveData
      };
    }

    // Locale & Timezone
    let timezone = 'UTC';
    try {
      timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
    } catch (e) {}

    return {
      os: os,
      browser: browser,
      deviceType: deviceType,
      isTouch: isTouch,
      cpuCores: navigator.hardwareConcurrency || null,
      deviceMemoryGB: navigator.deviceMemory || null,
      screenWidth: window.screen.width,
      screenHeight: window.screen.height,
      viewportWidth: window.innerWidth,
      viewportHeight: window.innerHeight,
      pixelRatio: window.devicePixelRatio || 1,
      colorDepth: window.screen.colorDepth || 24,
      prefersDark: window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches,
      reducedMotion: window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches,
      language: navigator.language || navigator.languages?.[0] || 'en-US',
      timezone: timezone,
      timezoneOffsetMinutes: new Date().getTimezoneOffset(),
      connection: connectionInfo
    };
  }

  /**
   * Calculates performance navigation timings
   */
  function getPerformanceMetrics() {
    const perf = window.performance;
    if (!perf || !perf.getEntriesByType) return null;

    const nav = perf.getEntriesByType('navigation')[0];
    if (!nav) return null;

    return {
      dnsTimeMs: Math.round(nav.domainLookupEnd - nav.domainLookupStart),
      tcpHandshakeMs: Math.round(nav.connectEnd - nav.connectStart),
      ttfbMs: Math.round(nav.responseStart - nav.requestStart),
      responseTransferMs: Math.round(nav.responseEnd - nav.responseStart),
      domContentLoadedMs: Math.round(nav.domContentLoadedEventEnd - nav.startTime),
      completeLoadMs: Math.round(nav.loadEventEnd - nav.startTime),
      protocol: nav.nextHopProtocol || 'unknown'
    };
  }

  /**
   * Persists an event in the local storage circular buffer for console viewing
   */
  function recordLocalEvent(payload) {
    try {
      const historyStr = localStorage.getItem(CONFIG.storageKeyHistory);
      let history = historyStr ? JSON.parse(historyStr) : [];
      if (!Array.isArray(history)) history = [];
      
      history.push(payload);
      if (history.length > CONFIG.maxStoredEvents) {
        history = history.slice(history.length - CONFIG.maxStoredEvents);
      }
      localStorage.setItem(CONFIG.storageKeyHistory, JSON.stringify(history));
    } catch (e) {
      // Storage might be full or private browsing active
    }
  }

  /**
   * Dispatches telemetry data via Beacon or Keepalive Fetch
   */
  function dispatchPayload(payload) {
    recordLocalEvent(payload);

    // Optional third-party forwarders
    if (typeof window.gtag === 'function') {
      try {
        window.gtag('event', payload.eventType, {
          event_category: payload.category || 'LeanStack',
          event_label: payload.label || payload.name,
          value: payload.value || 1,
          ...payload.data
        });
      } catch (e) {}
    }

    if (typeof window.plausible === 'function') {
      try {
        window.plausible(payload.name || payload.eventType, { props: payload.data });
      } catch (e) {}
    }

    const payloadJson = JSON.stringify(payload);

    // Try Beacon API first (safest during page unload)
    if (typeof navigator.sendBeacon === 'function') {
      try {
        const blob = new Blob([payloadJson], { type: 'application/json' });
        if (navigator.sendBeacon(CONFIG.endpoint, blob)) return;
      } catch (e) {}
    }

    // Fallback to fetch with keepalive
    if (typeof fetch === 'function') {
      try {
        fetch(CONFIG.endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: payloadJson,
          keepalive: true
        }).then(res => {
          if (!res.ok && res.status === 404 && !CONFIG.endpoint.endsWith('/index.php')) {
            // Auto-fallback to direct script path if rewrite is not enabled
            const directScript = CONFIG.endpoint.replace(/\/+$/, '') + '/index.php';
            fetch(directScript, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: payloadJson,
              keepalive: true
            }).then(r => {
              if (r.ok) CONFIG.endpoint = directScript;
            }).catch(() => {});
          }
        }).catch(() => {});
      } catch (e) {}
    }
  }

  /**
   * Core telemetry emitter
   */
  function trackEvent(name, data = {}, category = 'engagement') {
    const payload = {
      visitorId: visitorId,
      sessionId: sessionId,
      isReturning: isReturning,
      visitCount: visitCount,
      timestamp: new Date().toISOString(),
      eventType: 'custom_event',
      name: name,
      category: category,
      page: {
        path: window.location.pathname,
        search: window.location.search,
        hash: window.location.hash,
        title: document.title
      },
      dwellTimeSeconds: activeDwellSeconds,
      scrollDepthMax: highestScrollDepth,
      data: data
    };

    dispatchPayload(payload);
  }

  /**
   * Track Initial Pageview
   */
  function trackPageview() {
    setTimeout(() => {
      const acquisition = getAcquisitionContext();
      const environment = getEnvironmentContext();
      const perfMetrics = getPerformanceMetrics();

      const pageviewPayload = {
        visitorId: visitorId,
        sessionId: sessionId,
        isReturning: isReturning,
        visitCount: visitCount,
        timestamp: new Date().toISOString(),
        eventType: 'pageview',
        page: {
          url: window.location.href,
          pathname: window.location.pathname,
          referrer: acquisition.referrerRaw,
          title: document.title
        },
        acquisition: acquisition,
        environment: environment,
        performance: perfMetrics
      };

      dispatchPayload(pageviewPayload);

      // Log welcome banner in developer console
      console.log(
        '%c⚡ LeanStack Telemetry Engine Active%c\n' +
        'Autonomous visitor intelligence & high-density event tracking initialized.\n' +
        `• Visitor ID: ${visitorId} (${isReturning ? 'Returning ×' + visitCount : 'First visit'})\n` +
        `• Device: ${environment.os} • ${environment.browser} • ${environment.deviceType} (${environment.viewportWidth}×${environment.viewportHeight})\n` +
        `• Channel: ${acquisition.referrerDomain} | UTM Source: ${acquisition.utm.source || 'none'}\n` +
        'Type %cLeanStackAnalytics.getReport()%c or visit %c/analytics.html%c for owner telemetry.',
        'background: #F72B00; color: #FFFFFF; font-weight: bold; padding: 3px 8px; border-radius: 4px;',
        'color: #A9A6A5;',
        'color: #00D084; font-weight: bold;',
        'color: #A9A6A5;',
        'color: #FF6900; font-weight: bold;',
        'color: #A9A6A5;'
      );
    }, 400);
  }

  /**
   * Tracks active dwell time and tab focus transitions
   */
  function setupDwellTimeTracker() {
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) {
        if (isTabActive) {
          activeDwellSeconds += Math.round((Date.now() - lastActiveTimestamp) / 1000);
        }
        isTabActive = false;
      } else {
        isTabActive = true;
        lastActiveTimestamp = Date.now();
      }
    });

    window.addEventListener('focus', () => {
      if (!isTabActive) {
        isTabActive = true;
        lastActiveTimestamp = Date.now();
      }
    });

    window.addEventListener('blur', () => {
      if (isTabActive) {
        activeDwellSeconds += Math.round((Date.now() - lastActiveTimestamp) / 1000);
        isTabActive = false;
      }
    });

    // Periodic Heartbeat
    setInterval(() => {
      if (isTabActive) {
        activeDwellSeconds += Math.round((Date.now() - lastActiveTimestamp) / 1000);
        lastActiveTimestamp = Date.now();
      }
    }, 5000);

    // Dwell Time summary on unload
    window.addEventListener('beforeunload', () => {
      if (isTabActive) {
        activeDwellSeconds += Math.round((Date.now() - lastActiveTimestamp) / 1000);
      }
      dispatchPayload({
        visitorId: visitorId,
        sessionId: sessionId,
        eventType: 'session_heartbeat',
        totalDwellSeconds: activeDwellSeconds,
        finalScrollDepth: highestScrollDepth,
        timestamp: new Date().toISOString()
      });
    });
  }

  /**
   * Tracks scroll depth milestones (25%, 50%, 75%, 100%)
   */
  function setupScrollTracking() {
    let ticking = false;

    function checkScroll() {
      const docHeight = Math.max(
        document.body.scrollHeight,
        document.documentElement.scrollHeight
      );
      const winHeight = window.innerHeight;
      const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
      const scrollable = docHeight - winHeight;

      if (scrollable <= 0) return;

      const currentPercent = Math.min(100, Math.round((scrollTop / scrollable) * 100));
      if (currentPercent > highestScrollDepth) {
        highestScrollDepth = currentPercent;
      }

      [25, 50, 75, 100].forEach(milestone => {
        if (currentPercent >= milestone && !reachedScrollMilestones.has(milestone)) {
          reachedScrollMilestones.add(milestone);
          trackEvent(`scroll_depth_${milestone}`, {
            milestone: milestone,
            actualPercent: currentPercent
          }, 'engagement');
        }
      });

      ticking = false;
    }

    window.addEventListener('scroll', () => {
      if (!ticking) {
        window.requestAnimationFrame(checkScroll);
        ticking = true;
      }
    }, { passive: true });
  }

  /**
   * Section Visibility Tracking via IntersectionObserver
   */
  function setupSectionObserver() {
    if (!('IntersectionObserver' in window)) return;

    const sections = document.querySelectorAll('section[id], header[id], #transparency, #benchmarks, #features, #architecture, #roadmap');
    const viewedSections = new Set();

    const observer = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting && entry.intersectionRatio >= 0.4) {
          const sectionId = entry.target.id;
          if (sectionId && !viewedSections.has(sectionId)) {
            viewedSections.add(sectionId);
            trackEvent('section_view', {
              sectionId: sectionId,
              sectionHeading: entry.target.querySelector('h1, h2, h3')?.textContent?.trim() || sectionId
            }, 'navigation');
          }
        }
      });
    }, { threshold: [0.4] });

    sections.forEach(sec => observer.observe(sec));
  }

  /**
   * Global Delegated Event Listeners for High-Intent User Actions
   */
  function setupEventDelegation() {
    document.addEventListener('click', (e) => {
      // 1. Copy Buttons (Install / Update / CLI Commands)
      const copyBtn = e.target.closest('[data-copy]');
      if (copyBtn) {
        const text = copyBtn.getAttribute('data-copy') || '';
        const context = copyBtn.getAttribute('data-install-tab') || copyBtn.id || 'button';
        trackEvent('copy_install_command', {
          command: text,
          context: context,
          isHero: !!copyBtn.closest('#hero-cmd-text, #hero-copy-btn')
        }, 'conversion');
        return;
      }

      // 2. Command Tabs (Install vs Update vs Self-Host)
      const tabBtn = e.target.closest('[data-install-tab]');
      if (tabBtn) {
        const tabKey = tabBtn.getAttribute('data-install-tab');
        trackEvent('select_command_tab', { tab: tabKey }, 'interaction');
        return;
      }

      // 3. Outbound links (GitHub, external references, docs links)
      const link = e.target.closest('a[href]');
      if (link) {
        const href = link.getAttribute('href');
        if (href && (href.startsWith('http') || href.startsWith('mailto'))) {
          try {
            const url = new URL(href);
            if (url.hostname !== window.location.hostname) {
              trackEvent('outbound_click', {
                destination: href,
                domain: url.hostname,
                linkText: link.textContent?.trim()?.slice(0, 50)
              }, 'navigation');
            }
          } catch (err) {}
        }
      }
    });
  }

  /**
   * In-Browser Telemetry Dashboard Modal (HUD)
   * Toggle with Alt+A or LeanStackAnalytics.showDashboard()
   */
  function toggleDashboard() {
    let hud = document.getElementById('ls-analytics-hud');
    if (hud) {
      if (hud.classList.contains('hidden')) {
        hud.classList.remove('hidden');
        renderHudContent();
      } else {
        hud.classList.add('hidden');
      }
      return;
    }

    hud = document.createElement('div');
    hud.id = 'ls-analytics-hud';
    hud.className = 'fixed inset-0 z-[9999] flex items-center justify-center bg-black/80 backdrop-blur-md p-4 transition-opacity';
    hud.innerHTML = `
      <div class="bg-[#1E1B19] border border-[#332F2C] rounded-2xl w-full max-w-4xl max-h-[85vh] flex flex-col shadow-2xl overflow-hidden font-sans text-xs text-[#A9A6A5]">
        
        <!-- Header -->
        <div class="px-6 py-4 bg-[#161413] border-b border-[#332F2C] flex items-center justify-between">
          <div class="flex items-center gap-3">
            <div class="w-6 h-6 rounded bg-[#F72B00] text-white flex items-center justify-center font-bold text-[10px]">LS</div>
            <div>
              <h2 class="text-sm font-semibold text-[#F7F3F2]">LeanStack Visitor Intelligence HUD</h2>
              <p class="text-[10px] text-[#7A7674]">Privacy-First Zero-Cookie Client Telemetry Engine</p>
            </div>
          </div>
          <div class="flex items-center gap-2">
            <button id="ls-hud-export" class="px-2.5 py-1 rounded bg-[#282422] hover:bg-[#332F2C] text-[#F7F3F2] border border-[#332F2C] transition">Export JSON</button>
            <button id="ls-hud-close" class="p-1 rounded text-[#7A7674] hover:text-[#F7F3F2] transition text-base">✕</button>
          </div>
        </div>

        <!-- Scrollable Body -->
        <div id="ls-hud-body" class="p-6 overflow-y-auto space-y-6">
          <!-- Dynamic Content Loaded Here -->
        </div>

        <!-- Footer -->
        <div class="px-6 py-3 bg-[#110F0E] border-t border-[#332F2C] flex items-center justify-between text-[10px] text-[#7A7674]">
          <span>Shortcut: Press <kbd class="px-1.5 py-0.5 rounded bg-[#282422] text-[#F7F3F2]">Alt + A</kbd> anywhere to toggle this panel</span>
          <span>Endpoint: ${CONFIG.endpoint}</span>
        </div>

      </div>
    `;

    document.body.appendChild(hud);

    hud.querySelector('#ls-hud-close').addEventListener('click', () => hud.classList.add('hidden'));
    hud.querySelector('#ls-hud-export').addEventListener('click', () => exportLogs());
    hud.addEventListener('click', (e) => {
      if (e.target === hud) hud.classList.add('hidden');
    });

    renderHudContent();
  }

  function renderHudContent() {
    const body = document.getElementById('ls-hud-body');
    if (!body) return;

    const env = getEnvironmentContext();
    const acq = getAcquisitionContext();
    const perf = getPerformanceMetrics();
    const history = JSON.parse(localStorage.getItem(CONFIG.storageKeyHistory) || '[]');

    const totalEvents = history.length;
    const copies = history.filter(e => e.name === 'copy_install_command').length;
    const sims = history.filter(e => e.name && e.name.startsWith('simulate_')).length;

    body.innerHTML = `
      <!-- Top Metrics Cards -->
      <div class="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div class="p-3 rounded-xl bg-[#161413] border border-[#332F2C]">
          <span class="text-[10px] uppercase tracking-wider text-[#7A7674] block">Visitor Status</span>
          <span class="text-sm font-semibold text-[#00D084] mt-0.5 block">${isReturning ? 'Returning (' + visitCount + ' visits)' : 'First-Time Visitor'}</span>
          <span class="text-[10px] text-[#7A7674] font-mono truncate block mt-0.5">${visitorId}</span>
        </div>
        <div class="p-3 rounded-xl bg-[#161413] border border-[#332F2C]">
          <span class="text-[10px] uppercase tracking-wider text-[#7A7674] block">Active Dwell Time</span>
          <span class="text-sm font-semibold text-[#F72B00] mt-0.5 block">${activeDwellSeconds}s active</span>
          <span class="text-[10px] text-[#7A7674] block mt-0.5">Max Scroll: ${highestScrollDepth}%</span>
        </div>
        <div class="p-3 rounded-xl bg-[#161413] border border-[#332F2C]">
          <span class="text-[10px] uppercase tracking-wider text-[#7A7674] block">High-Intent Actions</span>
          <span class="text-sm font-semibold text-[#FF6900] mt-0.5 block">${copies} CLI Copies</span>
          <span class="text-[10px] text-[#7A7674] block mt-0.5">${sims} Benchmark Runs</span>
        </div>
        <div class="p-3 rounded-xl bg-[#161413] border border-[#332F2C]">
          <span class="text-[10px] uppercase tracking-wider text-[#7A7674] block">Wire Latency</span>
          <span class="text-sm font-semibold text-[#F7F3F2] mt-0.5 block">${perf ? perf.ttfbMs + 'ms TTFB' : 'N/A'}</span>
          <span class="text-[10px] text-[#7A7674] block mt-0.5">${perf ? perf.protocol : 'HTTP/3'}</span>
        </div>
      </div>

      <!-- Environment & Acquisition Grids -->
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        
        <!-- Hardware & Browser -->
        <div class="p-4 rounded-xl bg-[#161413] border border-[#332F2C] space-y-2">
          <h3 class="text-xs font-semibold text-[#F7F3F2] flex items-center gap-2">
            <span class="w-2 h-2 rounded-full bg-[#00D084]"></span>
            Hardware & Platform Profile
          </h3>
          <div class="grid grid-cols-2 gap-y-1.5 text-[11px]">
            <span class="text-[#7A7674]">Operating System:</span>
            <span class="text-[#F7F3F2] font-mono">${env.os}</span>
            <span class="text-[#7A7674]">Browser Engine:</span>
            <span class="text-[#F7F3F2] font-mono">${env.browser}</span>
            <span class="text-[#7A7674]">Device Category:</span>
            <span class="text-[#F7F3F2] font-mono capitalize">${env.deviceType}</span>
            <span class="text-[#7A7674]">Screen Dimensions:</span>
            <span class="text-[#F7F3F2] font-mono">${env.screenWidth}×${env.screenHeight} (${env.pixelRatio}x)</span>
            <span class="text-[#7A7674]">Timezone & Locale:</span>
            <span class="text-[#F7F3F2] font-mono">${env.timezone} (${env.language})</span>
            <span class="text-[#7A7674]">CPU Cores / RAM:</span>
            <span class="text-[#F7F3F2] font-mono">${env.cpuCores || '?'} cores / ${env.deviceMemoryGB ? env.deviceMemoryGB + 'GB' : 'N/A'}</span>
          </div>
        </div>

        <!-- Acquisition & Campaign -->
        <div class="p-4 rounded-xl bg-[#161413] border border-[#332F2C] space-y-2">
          <h3 class="text-xs font-semibold text-[#F7F3F2] flex items-center gap-2">
            <span class="w-2 h-2 rounded-full bg-[#F72B00]"></span>
            Acquisition & Referral Channel
          </h3>
          <div class="grid grid-cols-2 gap-y-1.5 text-[11px]">
            <span class="text-[#7A7674]">Referrer Domain:</span>
            <span class="text-[#F7F3F2] font-mono font-semibold">${acq.referrerDomain}</span>
            <span class="text-[#7A7674]">Organic / Social:</span>
            <span class="text-[#F7F3F2] font-mono">${acq.isOrganicSearch ? 'Search Engine' : acq.isSocial ? 'Social Media' : acq.isDevCommunity ? 'Developer Hub' : 'Direct'}</span>
            <span class="text-[#7A7674]">UTM Source:</span>
            <span class="text-[#F7F3F2] font-mono">${acq.utm.source || 'None'}</span>
            <span class="text-[#7A7674]">UTM Campaign:</span>
            <span class="text-[#F7F3F2] font-mono">${acq.utm.campaign || 'None'}</span>
            <span class="text-[#7A7674]">Raw Referrer:</span>
            <span class="text-[#7A7674] font-mono truncate text-[10px] col-span-2">${acq.referrerRaw}</span>
          </div>
        </div>

      </div>

      <!-- Realtime Event Stream -->
      <div class="space-y-2">
        <div class="flex items-center justify-between">
          <h3 class="text-xs font-semibold text-[#F7F3F2]">Session Activity Stream (Last ${Math.min(15, totalEvents)} Events)</h3>
          <span class="text-[10px] text-[#7A7674]">${totalEvents} events logged in localStorage</span>
        </div>
        <div class="rounded-xl border border-[#332F2C] bg-[#161413] divide-y divide-[#332F2C]/60 overflow-hidden font-mono text-[11px]">
          ${history.slice(-15).reverse().map(ev => `
            <div class="px-3 py-2 flex items-center justify-between gap-2 hover:bg-[#1E1B19]">
              <div class="flex items-center gap-2 truncate">
                <span class="text-[9px] px-1.5 py-0.5 rounded bg-[#282422] text-[#F72B00] font-sans font-bold uppercase">${ev.eventType === 'pageview' ? 'PAGE' : 'EVENT'}</span>
                <span class="text-[#F7F3F2] font-semibold">${ev.name || ev.page?.pathname || ev.eventType}</span>
                <span class="text-[#7A7674] text-[10px] truncate">${JSON.stringify(ev.data || {}).slice(0, 50)}</span>
              </div>
              <span class="text-[#7A7674] text-[10px] shrink-0">${new Date(ev.timestamp).toLocaleTimeString()}</span>
            </div>
          `).join('') || '<div class="p-4 text-center text-[#7A7674]">No events recorded yet. Interact with the page to populate telemetry.</div>'}
        </div>
      </div>
    `;
  }

  /**
   * Console report generator
   */
  function printConsoleReport() {
    const env = getEnvironmentContext();
    const acq = getAcquisitionContext();
    const history = JSON.parse(localStorage.getItem(CONFIG.storageKeyHistory) || '[]');

    console.group('%c📊 LeanStack Visitor & Telemetry Audit Report', 'color: #F72B00; font-weight: bold; font-size: 14px;');
    console.table({
      'Visitor ID': visitorId,
      'Session ID': sessionId,
      'Returning': isReturning ? `Yes (${visitCount} visits)` : 'No (First Visit)',
      'Active Dwell': `${activeDwellSeconds} seconds`,
      'Max Scroll': `${highestScrollDepth}%`,
      'Device Type': env.deviceType,
      'OS': env.os,
      'Browser': env.browser,
      'Resolution': `${env.screenWidth}×${env.screenHeight} (${env.viewportWidth}×${env.viewportHeight})`,
      'Referrer': acq.referrerDomain,
      'UTM Source': acq.utm.source || 'N/A',
      'Total Events': history.length
    });
    console.log('Recorded Telemetry Stream:', history);
    console.groupEnd();
  }

  /**
   * Export JSON log file
   */
  function exportLogs() {
    const history = JSON.parse(localStorage.getItem(CONFIG.storageKeyHistory) || '[]');
    const exportData = {
      exportTimestamp: new Date().toISOString(),
      visitorId: visitorId,
      sessionId: sessionId,
      environment: getEnvironmentContext(),
      acquisition: getAcquisitionContext(),
      events: history
    };

    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `leanstack-telemetry-${visitorId}-${Date.now()}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  // Dashboard shortcut listener removed per owner request.
  // Telemetry is now viewed securely at /analytics.html (password protected).

  // Self Initialization
  function init() {
    initIdentity();
    setupDwellTimeTracker();
    setupScrollTracking();
    setupSectionObserver();
    setupEventDelegation();
    trackPageview();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // Public API exposed on window.LeanStackAnalytics
  window.LeanStackAnalytics = {
    track: trackEvent,
    getVisitorId: () => visitorId,
    getSessionId: () => sessionId,
    getEnvironment: getEnvironmentContext,
    getAcquisition: getAcquisitionContext,
    getReport: printConsoleReport,
    getLogs: () => JSON.parse(localStorage.getItem(CONFIG.storageKeyHistory) || '[]'),
    exportLogs: exportLogs,
    getEndpoint: () => CONFIG.endpoint,
    fetchServerData: async (authKey) => {
      const origin = (typeof window !== 'undefined' && window.location && window.location.origin) ? window.location.origin : 'https://leanstack.kuntalghosh.dev';
      const endpointsToTry = [
        CONFIG.endpoint,
        `${origin}/api/telemetry`,
        `${origin}/api/telemetry/`,
        `${origin}/api/telemetry/index.php`,
        `${origin}/api/telemetry.php`
      ];
      const uniqueEndpoints = Array.from(new Set(endpointsToTry));
      let lastErr = null;

      for (const ep of uniqueEndpoints) {
        try {
          const sep = ep.includes('?') ? '&' : '?';
          const url = `${ep}${sep}auth=${encodeURIComponent(authKey || '')}`;
          const res = await fetch(url, {
            headers: { 'Accept': 'application/json' },
            cache: 'no-store'
          });
          if (res.status === 401) {
            throw new Error('Unauthorized');
          }
          if (res.ok) {
            CONFIG.endpoint = ep;
            return await res.json();
          }
          lastErr = new Error(`HTTP ${res.status}`);
        } catch (err) {
          if (err.message === 'Unauthorized') throw err;
          lastErr = err;
        }
      }
      throw lastErr || new Error('Endpoint unreachable');
    },
    clearServerData: async (authKey) => {
      const origin = (typeof window !== 'undefined' && window.location && window.location.origin) ? window.location.origin : 'https://leanstack.kuntalghosh.dev';
      const endpointsToTry = [
        CONFIG.endpoint,
        `${origin}/api/telemetry`,
        `${origin}/api/telemetry/`,
        `${origin}/api/telemetry/index.php`,
        `${origin}/api/telemetry.php`
      ];
      const uniqueEndpoints = Array.from(new Set(endpointsToTry));
      let lastErr = null;

      for (const ep of uniqueEndpoints) {
        try {
          const sep = ep.includes('?') ? '&' : '?';
          const url = `${ep}${sep}auth=${encodeURIComponent(authKey || '')}`;
          const res = await fetch(url, {
            method: 'DELETE',
            headers: { 'Accept': 'application/json' }
          });
          if (res.status === 401) {
            throw new Error('Unauthorized');
          }
          if (res.ok) {
            CONFIG.endpoint = ep;
            return await res.json();
          }
          lastErr = new Error(`HTTP ${res.status}`);
        } catch (err) {
          if (err.message === 'Unauthorized') throw err;
          lastErr = err;
        }
      }
      throw lastErr || new Error('Endpoint unreachable');
    }
  };

})(window, document);
