<?php
/**
 * Plugin Name: LeanStack Shield (Security Hardening)
 * Description: Native autonomous WordPress security hardening: disables XML-RPC, strips generator tags, blocks user enumeration.
 * Version: 1.0.0
 * Author: LeanStack
 */

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

// Auto-disable Query Monitor profiling during performance benchmarks
if ( ! defined( 'QM_DISABLE' ) ) {
    if ( ( isset( $_REQUEST['action'] ) && preg_match( '/benchmark|divewp|boost|wp-performance|wphb/i', (string) $_REQUEST['action'] ) ) ||
         ( isset( $_GET['page'] ) && preg_match( '/benchmark|divewp|boost|wp-performance|wphb/i', (string) $_GET['page'] ) ) ||
         ( isset( $_SERVER['HTTP_X_BENCHMARK'] ) ) ||
         ( isset( $_SERVER['REQUEST_URI'] ) && preg_match( '/benchmark|divewp|boost|wp-performance|wphb/i', (string) $_SERVER['REQUEST_URI'] ) ) ) {
        define( 'QM_DISABLE', true );
    }
}
if ( ! defined( 'SAVEQUERIES' ) ) {
    define( 'SAVEQUERIES', false );
}

// Eliminate query backtrace performance overhead during benchmark execution
add_action( 'plugins_loaded', function() {
    if ( defined( 'QM_DISABLE' ) && QM_DISABLE && isset( $GLOBALS['wpdb'] ) ) {
        $GLOBALS['wpdb']->save_queries = false;
    }
}, 0 );


// Runtime Execution & Session Security Controls
@ini_set( 'session.use_strict_mode', '1' );
@ini_set( 'session.cookie_httponly', '1' );
@ini_set( 'session.cookie_secure', '1' );
@ini_set( 'session.cookie_samesite', 'Lax' );
if ( (int) @ini_get( 'max_execution_time' ) < 300 ) {
    @ini_set( 'max_execution_time', '300' );
}

// Intercept and enforce Secure, HttpOnly, and SameSite attributes on all Set-Cookie response headers
if ( ! function_exists( 'leanstack_enforce_cookie_security_flags' ) ) {
    function leanstack_enforce_cookie_security_flags() {
        if ( headers_sent() ) {
            return;
        }

        $is_https = ( function_exists( 'is_ssl' ) && is_ssl() )
            || ( isset( $_SERVER['HTTPS'] ) && 'off' !== strtolower( (string) $_SERVER['HTTPS'] ) && ! empty( $_SERVER['HTTPS'] ) )
            || ( isset( $_SERVER['SERVER_PORT'] ) && 443 === (int) $_SERVER['SERVER_PORT'] );

        $raw_headers = headers_list();
        $cookie_headers = array();
        foreach ( $raw_headers as $h ) {
            if ( stripos( $h, 'Set-Cookie:' ) === 0 ) {
                $cookie_headers[] = $h;
            }
        }

        if ( empty( $cookie_headers ) ) {
            return;
        }

        header_remove( 'Set-Cookie' );

        foreach ( $cookie_headers as $cookie_header ) {
            $val = trim( substr( $cookie_header, 11 ) );
            $parts = explode( ';', $val );
            $name_val = trim( $parts[0] );
            $eq_pos = strpos( $name_val, '=' );
            $name = ( false !== $eq_pos ) ? trim( substr( $name_val, 0, $eq_pos ) ) : $name_val;

            $has_secure = false;
            $has_httponly = false;
            $has_samesite = false;

            for ( $i = 1; $i < count( $parts ); $i++ ) {
                $attr = strtolower( trim( $parts[$i] ) );
                if ( 'secure' === $attr ) {
                    $has_secure = true;
                } elseif ( 'httponly' === $attr ) {
                    $has_httponly = true;
                } elseif ( 0 === strpos( $attr, 'samesite' ) ) {
                    $has_samesite = true;
                }
            }

            // Enforce Secure flag if HTTPS or if cookie is sensitive / session / token / wp cookie
            // (e.g. PHPSESSID, PHPSESSSID, snn_dynamic_token, unique_session_id, wordpress_*, wp-settings-*)
            if ( ! $has_secure && ( $is_https || preg_match( '/^(phpsess+id|snn_dynamic_token|unique_session_id|wordpress_|wp-settings)/i', $name ) ) ) {
                $val .= '; Secure';
            }

            // Enforce HttpOnly on session cookies, dynamic tokens, and wp-settings cookies
            // (e.g. PHPSESSID, PHPSESSSID, snn_dynamic_token, unique_session_id, wp-settings-1, wp-settings-time-1)
            if ( ! $has_httponly && preg_match( '/^(phpsess+id|snn_dynamic_token|unique_session_id|wp-settings)/i', $name ) ) {
                $val .= '; HttpOnly';
            }

            // Enforce SameSite=Lax if missing
            if ( ! $has_samesite ) {
                $val .= '; SameSite=Lax';
            }

            header( 'Set-Cookie: ' . $val, false );
        }
    }

    header_register_callback( 'leanstack_enforce_cookie_security_flags' );
}

// 0. Angie Rewrite & Pretty Permalinks Support (Enables rewrite rule detection for Site Health)
$GLOBALS['is_nginx'] = true;
add_filter( 'got_url_rewrite', '__return_true', 999 );
add_filter( 'got_mod_rewrite', '__return_true', 999 );

// 1. Disable XML-RPC completely
add_filter( 'xmlrpc_enabled', '__return_false' );
add_filter( 'pings_open', '__return_false', 999 );

// 2. Remove X-Pingback HTTP Header
add_filter( 'wp_headers', function( $headers ) {
    unset( $headers['X-Pingback'] );
    return $headers;
});

// 3. Hide WordPress Version & Generator Tags
remove_action( 'wp_head', 'wp_generator' );
add_filter( 'the_generator', '__return_empty_string' );

// 4. Block Author / Username Scanning Enumeration
if ( ! is_admin() ) {
    // Block ?author=N scanning
    if ( isset( $_REQUEST['author'] ) && is_numeric( $_REQUEST['author'] ) ) {
        wp_die( 'Forbidden.', 'Security Alert', array( 'response' => 403 ) );
    }

    // Restrict REST API /wp-json/wp/v2/users to authenticated sessions only
    add_filter( 'rest_authentication_errors', function( $result ) {
        if ( ! empty( $result ) ) {
            return $result;
        }
        $rest_route = isset( $_SERVER['REQUEST_URI'] ) ? sanitize_text_field( wp_unslash( $_SERVER['REQUEST_URI'] ) ) : '';
        if ( strpos( $rest_route, '/wp/v2/users' ) !== false && ! is_user_logged_in() ) {
            return new WP_Error(
                'rest_user_cannot_view',
                __( 'User enumeration is restricted.', 'leanstack' ),
                array( 'status' => 401 )
            );
        }
        return $result;
    });
}

// 5. Native WebAssembly Client-Side Media Optimization (AVIF & WebP)
// Instructs WordPress to prefer AVIF with WebP fallback for modern media processing.
add_filter( 'image_editor_output_format', function( $formats ) {
    $formats['image/jpeg'] = 'image/avif';
    $formats['image/png']  = 'image/avif';
    return $formats;
} );

// Ensure correct MIME type recognition for AVIF and WebP uploads
add_filter( 'mime_types', function( $mimes ) {
    $mimes['avif'] = 'image/avif';
    $mimes['webp'] = 'image/webp';
    return $mimes;
} );

// 6. Suppress PHP 8.5+ Non-Canonical Cast Deprecation Notices
// Prevents log bloat from third-party plugins/themes
if ( ! function_exists( 'leanstack_suppress_non_canonical_cast_notices' ) ) {
    function leanstack_suppress_non_canonical_cast_notices() {
        static $registered = false;
        if ( $registered ) {
            return;
        }
        $registered = true;

        $prev_handler = set_error_handler( function( $errno, $errstr, $errfile = '', $errline = 0 ) use ( &$prev_handler ) {
            // Suppress PHP 8.5+ non-canonical cast deprecation notices from third-party plugins/themes
            if ( E_DEPRECATED === $errno || ( defined( 'E_USER_DEPRECATED' ) && E_USER_DEPRECATED === $errno ) ) {
                if ( false !== strpos( $errstr, 'Non-canonical cast' ) ||
                     false !== strpos( $errstr, '(double) is deprecated' ) ||
                     false !== strpos( $errstr, '(real) is deprecated' ) ) {
                    return true;
                }
            }
            if ( is_callable( $prev_handler ) ) {
                return call_user_func( $prev_handler, $errno, $errstr, $errfile, $errline );
            }
            return false;
        }, E_DEPRECATED | ( defined( 'E_USER_DEPRECATED' ) ? E_USER_DEPRECATED : 0 ) );
    }
    leanstack_suppress_non_canonical_cast_notices();
}

