<?php
/**
 * LeanStack Telemetry & Visitor Intelligence Engine
 * High-performance, zero-cookie, privacy-first server collector & analytics API.
 * Endpoint: /api/telemetry or /api/telemetry/index.php or /api/telemetry.php
 */

// 1. HTTP & CORS Headers
$origin = $_SERVER['HTTP_ORIGIN'] ?? '';
$host = $_SERVER['HTTP_HOST'] ?? '';
if (!empty($origin)) {
    $parsed = parse_url($origin, PHP_URL_HOST);
    if ($parsed && ($parsed === $host || $parsed === 'localhost' || $parsed === '127.0.0.1')) {
        header('Access-Control-Allow-Origin: ' . $origin);
    }
}
header('Access-Control-Allow-Methods: GET, POST, OPTIONS, DELETE');
header('Access-Control-Allow-Headers: Content-Type, Authorization, X-Requested-With');
header('X-Content-Type-Options: nosniff');
header('Cache-Control: private, no-cache, no-store, must-revalidate');
header('Pragma: no-cache');
header('Expires: 0');

if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') {
    http_response_code(204);
    exit;
}

// 2. Storage Setup (Resilient Multi-Tier Storage Directory, Mode 0700)
$storageDir = dirname(__DIR__, 2) . '/data';
if (!is_dir($storageDir) || !is_writable($storageDir)) {
    $storageDir = __DIR__ . '/data';
    if (!is_dir($storageDir)) {
        @mkdir($storageDir, 0700, true);
    }
}
if (!is_writable($storageDir)) {
    $fallbackTmp = sys_get_temp_dir() . '/leanstack_telemetry';
    if (!is_dir($fallbackTmp)) {
        @mkdir($fallbackTmp, 0700, true);
    }
    if (is_writable($fallbackTmp)) {
        $storageDir = $fallbackTmp;
    }
}

$dbPath = $storageDir . '/telemetry.sqlite';
$jsonFallbackPath = $storageDir . '/events.json';
$passPath = $storageDir . '/passcode.hash';

// Master Passcode Verification (LS-16: No plaintext default, Bearer header only, timing-safe)
function verifyAuth($passPath) {
    // 1. Resolve stored secret / hash
    $storedHash = '';
    if (file_exists($passPath)) {
        $storedHash = trim((string) @file_get_contents($passPath));
    }
    if (empty($storedHash) && !empty($_ENV['LEANSTACK_TELEMETRY_SECRET'])) {
        $storedHash = (string) $_ENV['LEANSTACK_TELEMETRY_SECRET'];
    } elseif (empty($storedHash) && !empty(getenv('LEANSTACK_TELEMETRY_SECRET'))) {
        $storedHash = (string) getenv('LEANSTACK_TELEMETRY_SECRET');
    }

    if (empty($storedHash)) {
        return false;
    }

    // 2. Extract Authorization Bearer header only (reject query param ?auth=)
    $authHeader = $_SERVER['HTTP_AUTHORIZATION'] ?? $_SERVER['REDIRECT_HTTP_AUTHORIZATION'] ?? '';
    if (empty($authHeader) && function_exists('getallheaders')) {
        $headers = getallheaders();
        $authHeader = $headers['Authorization'] ?? $headers['authorization'] ?? '';
    }
    if (!preg_match('/Bearer\s+(\S+)$/i', trim($authHeader), $matches)) {
        return false;
    }
    $provided = $matches[1];

    // 3. Constant-time comparison
    if (str_starts_with($storedHash, '$2y$') || str_starts_with($storedHash, '$argon2')) {
        return password_verify($provided, $storedHash);
    }

    return hash_equals(hash('sha256', $storedHash), hash('sha256', $provided));
}

// SQLite Database Connection
function getDb($dbPath) {
    if (!class_exists('SQLite3')) {
        return null;
    }
    try {
        $db = new SQLite3($dbPath);
        $db->busyTimeout(3000);
        $db->exec('PRAGMA journal_mode = WAL;');
        $db->exec('CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            visitor_id TEXT,
            session_id TEXT,
            is_returning INTEGER,
            visit_count INTEGER,
            event_type TEXT,
            event_name TEXT,
            category TEXT,
            page_path TEXT,
            dwell_seconds INTEGER,
            scroll_max INTEGER,
            ip_masked TEXT,
            user_agent TEXT,
            device_type TEXT,
            os TEXT,
            browser TEXT,
            referrer_domain TEXT,
            utm_source TEXT,
            utm_campaign TEXT,
            ttfb_ms INTEGER,
            protocol TEXT,
            payload_json TEXT,
            created_at TEXT
        );');
        $db->exec('CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at DESC);');
        $db->exec('CREATE INDEX IF NOT EXISTS idx_events_vid ON events(visitor_id);');
        return $db;
    } catch (Exception $e) {
        return null;
    }
}

// Client IP Anonymization for GDPR/Privacy
function getAnonymizedIp() {
    $ip = $_SERVER['HTTP_CF_CONNECTING_IP'] 
        ?? $_SERVER['HTTP_X_FORWARDED_FOR'] 
        ?? $_SERVER['REMOTE_ADDR'] 
        ?? '127.0.0.1';
    
    $ip = trim(explode(',', $ip)[0]);
    if (filter_var($ip, FILTER_VALIDATE_IP, FILTER_FLAG_IPV4)) {
        $parts = explode('.', $ip);
        return $parts[0] . '.' . $parts[1] . '.' . $parts[2] . '.xxx';
    } elseif (filter_var($ip, FILTER_VALIDATE_IP, FILTER_FLAG_IPV6)) {
        $parts = explode(':', $ip);
        return implode(':', array_slice($parts, 0, 3)) . ':*:*:*';
    }
    return 'anonymous';
}

$method = $_SERVER['REQUEST_METHOD'];

// =============================================================================
// ROUTE 1: POST /api/telemetry (Record Visitor Events)
// =============================================================================
if ($method === 'POST') {
    $rawInput = file_get_contents('php://input');
    if (empty($rawInput)) {
        http_response_code(400);
        header('Content-Type: application/json');
        echo json_encode(['ok' => false, 'error' => 'Empty payload']);
        exit;
    }

    $event = json_decode($rawInput, true);
    if (!is_array($event)) {
        http_response_code(400);
        header('Content-Type: application/json');
        echo json_encode(['ok' => false, 'error' => 'Invalid JSON']);
        exit;
    }

    $visitorId = $event['visitorId'] ?? 'ls_vid_anon';
    $sessionId = $event['sessionId'] ?? 'ls_sid_anon';
    $isReturning = !empty($event['isReturning']) ? 1 : 0;
    $visitCount = intval($event['visitCount'] ?? 1);
    $eventType = $event['eventType'] ?? 'custom_event';
    $eventName = $event['name'] ?? ($event['eventType'] ?? 'unknown');
    $category = $event['category'] ?? 'engagement';
    $pagePath = $event['page']['pathname'] ?? ($event['page']['path'] ?? '/');
    $dwellSeconds = intval($event['dwellTimeSeconds'] ?? 0);
    $scrollMax = intval($event['scrollDepthMax'] ?? 0);
    $ipMasked = getAnonymizedIp();
    $userAgent = substr($_SERVER['HTTP_USER_AGENT'] ?? '', 0, 250);

    // Platform & Acquisition context
    $env = $event['environment'] ?? [];
    $acq = $event['acquisition'] ?? [];
    $perf = $event['performance'] ?? [];

    $deviceType = $env['deviceType'] ?? 'desktop';
    $os = $env['os'] ?? 'Unknown';
    $browser = $env['browser'] ?? 'Unknown';
    $refDomain = $acq['referrerDomain'] ?? 'Direct';
    $utmSource = $acq['utm']['source'] ?? '';
    $utmCampaign = $acq['utm']['campaign'] ?? '';
    $ttfbMs = isset($perf['ttfbMs']) ? intval($perf['ttfbMs']) : null;
    $protocol = $perf['protocol'] ?? '';
    $createdAt = date('Y-m-d H:i:s');

    $db = getDb($dbPath);
    if ($db) {
        $stmt = $db->prepare('INSERT INTO events (
            visitor_id, session_id, is_returning, visit_count, event_type, event_name, category,
            page_path, dwell_seconds, scroll_max, ip_masked, user_agent, device_type, os, browser,
            referrer_domain, utm_source, utm_campaign, ttfb_ms, protocol, payload_json, created_at
        ) VALUES (
            :vid, :sid, :returning, :vcount, :etype, :ename, :cat,
            :path, :dwell, :scroll, :ip, :ua, :dtype, :os, :browser,
            :ref, :usource, :ucampaign, :ttfb, :proto, :pjson, :cat_time
        );');

        $stmt->bindValue(':vid', $visitorId, SQLITE3_TEXT);
        $stmt->bindValue(':sid', $sessionId, SQLITE3_TEXT);
        $stmt->bindValue(':returning', $isReturning, SQLITE3_INTEGER);
        $stmt->bindValue(':vcount', $visitCount, SQLITE3_INTEGER);
        $stmt->bindValue(':etype', $eventType, SQLITE3_TEXT);
        $stmt->bindValue(':ename', $eventName, SQLITE3_TEXT);
        $stmt->bindValue(':cat', $category, SQLITE3_TEXT);
        $stmt->bindValue(':path', $pagePath, SQLITE3_TEXT);
        $stmt->bindValue(':dwell', $dwellSeconds, SQLITE3_INTEGER);
        $stmt->bindValue(':scroll', $scrollMax, SQLITE3_INTEGER);
        $stmt->bindValue(':ip', $ipMasked, SQLITE3_TEXT);
        $stmt->bindValue(':ua', $userAgent, SQLITE3_TEXT);
        $stmt->bindValue(':dtype', $deviceType, SQLITE3_TEXT);
        $stmt->bindValue(':os', $os, SQLITE3_TEXT);
        $stmt->bindValue(':browser', $browser, SQLITE3_TEXT);
        $stmt->bindValue(':ref', $refDomain, SQLITE3_TEXT);
        $stmt->bindValue(':usource', $utmSource, SQLITE3_TEXT);
        $stmt->bindValue(':ucampaign', $utmCampaign, SQLITE3_TEXT);
        $stmt->bindValue(':ttfb', $ttfbMs, SQLITE3_INTEGER);
        $stmt->bindValue(':proto', $protocol, SQLITE3_TEXT);
        $stmt->bindValue(':pjson', json_encode($event['data'] ?? []), SQLITE3_TEXT);
        $stmt->bindValue(':cat_time', $createdAt, SQLITE3_TEXT);
        $stmt->execute();

        // Prune older than 3000 events to maintain bounded footprint
        if (mt_rand(1, 50) === 1) {
            $db->exec('DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT 3000);');
        }
    } else {
        // Fallback to JSON rolling log
        $existing = file_exists($jsonFallbackPath) ? json_decode(file_get_contents($jsonFallbackPath), true) : [];
        if (!is_array($existing)) $existing = [];

        $record = [
            'visitorId' => $visitorId,
            'sessionId' => $sessionId,
            'isReturning' => (bool)$isReturning,
            'visitCount' => $visitCount,
            'eventType' => $eventType,
            'name' => $eventName,
            'category' => $category,
            'page' => ['pathname' => $pagePath],
            'dwellTimeSeconds' => $dwellSeconds,
            'scrollDepthMax' => $scrollMax,
            'ipMasked' => $ipMasked,
            'deviceType' => $deviceType,
            'os' => $os,
            'browser' => $browser,
            'referrerDomain' => $refDomain,
            'utmSource' => $utmSource,
            'utmCampaign' => $utmCampaign,
            'ttfbMs' => $ttfbMs,
            'protocol' => $protocol,
            'data' => $event['data'] ?? [],
            'timestamp' => $createdAt
        ];

        $existing[] = $record;
        if (count($existing) > 1000) {
            $existing = array_slice($existing, -1000);
        }
        @file_put_contents($jsonFallbackPath, json_encode($existing), LOCK_EX);
    }

    header('Content-Type: application/json');
    echo json_encode(['ok' => true, 'status' => 'recorded']);
    exit;
}

// =============================================================================
// ROUTE 2: GET /api/telemetry (Aggregate Analytics & Real-Time Event Stream)
// =============================================================================
if ($method === 'GET') {
    if (!verifyAuth($passPath)) {
        http_response_code(401);
        header('Content-Type: application/json');
        echo json_encode([
            'ok' => false, 
            'error' => 'Unauthorized',
            'api' => 'LeanStack Telemetry Engine'
        ]);
        exit;
    }

    $db = getDb($dbPath);
    if ($db) {
        // Compute aggregates via SQLite
        $totalEvents = intval($db->querySingle('SELECT COUNT(*) FROM events;') ?: 0);
        $totalVisitors = intval($db->querySingle('SELECT COUNT(DISTINCT visitor_id) FROM events;') ?: 0);
        $totalSessions = intval($db->querySingle('SELECT COUNT(DISTINCT session_id) FROM events;') ?: 0);
        $returningVisitors = intval($db->querySingle('SELECT COUNT(DISTINCT visitor_id) FROM events WHERE is_returning = 1;') ?: 0);
        
        $copies = intval($db->querySingle("SELECT COUNT(*) FROM events WHERE event_name = 'copy_install_command';") ?: 0);
        $sims = intval($db->querySingle("SELECT COUNT(*) FROM events WHERE event_name LIKE 'simulate_%' OR event_name = 'toggle_ssi_mode';") ?: 0);
        
        $avgDwell = intval($db->querySingle('SELECT MAX(dwell_seconds) FROM events;') ?: 0);
        $maxScroll = intval($db->querySingle('SELECT MAX(scroll_max) FROM events;') ?: 0);

        // Distributions
        $deviceQuery = $db->query('SELECT device_type, COUNT(*) as cnt FROM events GROUP BY device_type ORDER BY cnt DESC LIMIT 5;');
        $devices = [];
        while ($row = $deviceQuery->fetchArray(SQLITE3_ASSOC)) {
            $devices[$row['device_type'] ?: 'desktop'] = $row['cnt'];
        }

        $osQuery = $db->query('SELECT os, COUNT(*) as cnt FROM events WHERE os != "" GROUP BY os ORDER BY cnt DESC LIMIT 6;');
        $oses = [];
        while ($row = $osQuery->fetchArray(SQLITE3_ASSOC)) {
            $oses[$row['os']] = $row['cnt'];
        }

        $browserQuery = $db->query('SELECT browser, COUNT(*) as cnt FROM events WHERE browser != "" GROUP BY browser ORDER BY cnt DESC LIMIT 6;');
        $browsers = [];
        while ($row = $browserQuery->fetchArray(SQLITE3_ASSOC)) {
            $browsers[$row['browser']] = $row['cnt'];
        }

        $refQuery = $db->query('SELECT referrer_domain, COUNT(*) as cnt FROM events WHERE referrer_domain != "" GROUP BY referrer_domain ORDER BY cnt DESC LIMIT 6;');
        $referrers = [];
        while ($row = $refQuery->fetchArray(SQLITE3_ASSOC)) {
            $referrers[$row['referrer_domain']] = $row['cnt'];
        }

        // Recent 100 Events
        $recentQuery = $db->query('SELECT * FROM events ORDER BY id DESC LIMIT 100;');
        $recentEvents = [];
        while ($r = $recentQuery->fetchArray(SQLITE3_ASSOC)) {
            $recentEvents[] = [
                'id' => $r['id'],
                'visitorId' => $r['visitor_id'],
                'sessionId' => $r['session_id'],
                'isReturning' => (bool)$r['is_returning'],
                'visitCount' => $r['visit_count'],
                'eventType' => $r['event_type'],
                'name' => $r['event_name'],
                'category' => $r['category'],
                'page' => ['pathname' => $r['page_path']],
                'dwellTimeSeconds' => $r['dwell_seconds'],
                'scrollDepthMax' => $r['scroll_max'],
                'ipMasked' => $r['ip_masked'],
                'deviceType' => $r['device_type'],
                'os' => $r['os'],
                'browser' => $r['browser'],
                'referrerDomain' => $r['referrer_domain'],
                'utmSource' => $r['utm_source'],
                'utmCampaign' => $r['utm_campaign'],
                'ttfbMs' => $r['ttfb_ms'],
                'protocol' => $r['protocol'],
                'data' => json_decode($r['payload_json'] ?: '{}', true),
                'timestamp' => $r['created_at']
            ];
        }

        $response = [
            'ok' => true,
            'source' => 'sqlite',
            'summary' => [
                'totalVisitors' => $totalVisitors,
                'totalSessions' => $totalSessions,
                'totalEvents' => $totalEvents,
                'returningVisitors' => $returningVisitors,
                'cliCopies' => $copies,
                'benchmarkSims' => $sims,
                'activeDwellSeconds' => $avgDwell,
                'maxScrollDepth' => $maxScroll
            ],
            'distribution' => [
                'devices' => $devices,
                'os' => $oses,
                'browsers' => $browsers,
                'referrers' => $referrers
            ],
            'events' => $recentEvents
        ];
    } else {
        // Fallback from JSON
        $existing = file_exists($jsonFallbackPath) ? json_decode(file_get_contents($jsonFallbackPath), true) : [];
        if (!is_array($existing)) $existing = [];

        $vids = [];
        $sids = [];
        $copies = 0;
        $sims = 0;
        $maxDwell = 0;
        $maxScroll = 0;
        $devices = [];
        $oses = [];
        $browsers = [];
        $referrers = [];

        foreach ($existing as $e) {
            if (!empty($e['visitorId'])) $vids[$e['visitorId']] = true;
            if (!empty($e['sessionId'])) $sids[$e['sessionId']] = true;
            if (($e['name'] ?? '') === 'copy_install_command') $copies++;
            
            $ename = $e['name'] ?? '';
            if (strpos($ename, 'simulate_') === 0 || $ename === 'toggle_ssi_mode') {
                $sims++;
            }
            if (!empty($e['dwellTimeSeconds']) && $e['dwellTimeSeconds'] > $maxDwell) {
                $maxDwell = $e['dwellTimeSeconds'];
            }
            if (!empty($e['scrollDepthMax']) && $e['scrollDepthMax'] > $maxScroll) {
                $maxScroll = $e['scrollDepthMax'];
            }

            $d = $e['deviceType'] ?? 'desktop';
            $devices[$d] = ($devices[$d] ?? 0) + 1;
            if (!empty($e['os'])) $oses[$e['os']] = ($oses[$e['os']] ?? 0) + 1;
            if (!empty($e['browser'])) $browsers[$e['browser']] = ($browsers[$e['browser']] ?? 0) + 1;
            if (!empty($e['referrerDomain'])) $referrers[$e['referrerDomain']] = ($referrers[$e['referrerDomain']] ?? 0) + 1;
        }

        $response = [
            'ok' => true,
            'source' => 'json_fallback',
            'summary' => [
                'totalVisitors' => count($vids),
                'totalSessions' => count($sids),
                'totalEvents' => count($existing),
                'returningVisitors' => 0,
                'cliCopies' => $copies,
                'benchmarkSims' => $sims,
                'activeDwellSeconds' => $maxDwell,
                'maxScrollDepth' => $maxScroll
            ],
            'distribution' => [
                'devices' => $devices,
                'os' => $oses,
                'browsers' => $browsers,
                'referrers' => $referrers
            ],
            'events' => array_reverse(array_slice($existing, -100))
        ];
    }

    header('Content-Type: application/json');
    echo json_encode($response, JSON_PRETTY_PRINT);
    exit;
}

// =============================================================================
// ROUTE 3: DELETE /api/telemetry (Clear Telemetry Records)
// =============================================================================
if ($method === 'DELETE') {
    if (!verifyAuth($passPath)) {
        http_response_code(401);
        header('Content-Type: application/json');
        echo json_encode(['ok' => false, 'error' => 'Unauthorized']);
        exit;
    }

    $db = getDb($dbPath);
    if ($db) {
        $db->exec('DELETE FROM events;');
    }
    if (file_exists($jsonFallbackPath)) {
        @unlink($jsonFallbackPath);
    }

    header('Content-Type: application/json');
    echo json_encode(['ok' => true, 'message' => 'Telemetry records cleared.']);
    exit;
}
