<?php
/**
 * LeanStack Hardened WordPress Configuration
 * Native Valkey Unix Socket • Reverse-Proxy SSL • Anti-Thundering Cron
 */

// --- Database Configuration ---
define( 'DB_NAME',     '{{DB_NAME}}' );
define( 'DB_USER',     '{{DB_USER}}' );
define( 'DB_PASSWORD', '{{DB_PASS}}' );
define( 'DB_HOST',     'localhost' );
define( 'DB_CHARSET',  'utf8mb4' );
define( 'DB_COLLATE',  'utf8mb4_unicode_520_ci' );

$table_prefix = '{{TABLE_PREFIX}}';

// --- Cryptographic Salts ---
{{SALT_KEYS}}

// --- Reverse Proxy & Cloudflare Universal SSL Detection ---
if ( isset( $_SERVER['HTTP_X_FORWARDED_PROTO'] ) && $_SERVER['HTTP_X_FORWARDED_PROTO'] === 'https' ) {
    $_SERVER['HTTPS'] = 'on';
}
if ( isset( $_SERVER['HTTP_CF_VISITOR'] ) ) {
    $cf_visitor = json_decode( $_SERVER['HTTP_CF_VISITOR'] );
    if ( isset( $cf_visitor->scheme ) && $cf_visitor->scheme === 'https' ) {
        $_SERVER['HTTPS'] = 'on';
    }
}

// --- High-Performance In-Memory Valkey / Redis Object Cache ---
{{CACHE_CONSTANTS}}
define( 'WP_REDIS_SCHEME', 'unix' );
define( 'WP_REDIS_PATH',   '/run/valkey/valkey.sock' );
define( 'WP_REDIS_USERNAME', '{{USER_NAME}}' );
define( 'WP_REDIS_USER',   '{{USER_NAME}}' );
define( 'WP_REDIS_PASSWORD', '{{VALKEY_PASSWORD}}' );
define( 'WP_REDIS_DATABASE', {{VALKEY_DATABASE}} );
define( 'WP_REDIS_PREFIX', '{{CACHE_KEY_SALT}}' );
define( 'WP_CACHE_KEY_SALT', '{{CACHE_KEY_SALT}}' );
define( 'WP_REDIS_TIMEOUT', 1 );
define( 'WP_REDIS_READ_TIMEOUT', 1 );
define( 'WP_REDIS_DISABLE_METRICS', true );
define( 'WP_REDIS_PERSISTENT', true );
define( 'WP_REDIS_IGBINARY', true );
define( 'WP_REDIS_LOAD_APEXCHARTS', false );
define( 'WP_REDIS_DISABLE_BANNERS', true );

// --- Disable Stock WP-Cron (Driven by LeanStack Anti-Thundering Systemd Queue) ---
define( 'DISABLE_WP_CRON', true );

// --- Security Hardening ---
define( 'DISALLOW_FILE_EDIT', true );
define( 'WP_AUTO_UPDATE_CORE', 'minor' );
define( 'FORCE_SSL_ADMIN', true );

// --- Error Logging ---
define( 'WP_DEBUG', false );
define( 'WP_DEBUG_LOG', '/home/{{USER_NAME}}/logs/wp-debug.log' );
define( 'WP_DEBUG_DISPLAY', false );
@ini_set( 'display_errors', '0' );

// --- Post Revisions & Media Trash Retention ---
define( 'WP_POST_REVISIONS', 5 );
define( 'MEDIA_TRASH', true );
define( 'EMPTY_TRASH_DAYS', 7 );


// Auto-disable Query Monitor backtrace profiling on benchmark requests
if ( ! defined( 'QM_DISABLE' ) ) {
    if ( ( isset( $_REQUEST['action'] ) && preg_match( '/benchmark|divewp/i', (string) $_REQUEST['action'] ) ) ||
         ( isset( $_SERVER['HTTP_X_BENCHMARK'] ) ) ) {
        define( 'QM_DISABLE', true );
    }
}

// Absolute path to the WordPress directory
if ( ! defined( 'ABSPATH' ) ) {
    define( 'ABSPATH', __DIR__ . '/' );
}

// Sets up WordPress vars and included files
require_once ABSPATH . 'wp-settings.php';
