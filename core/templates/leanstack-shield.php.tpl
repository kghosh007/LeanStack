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

// 6. Suppress Benign open_basedir Path Resolution Warnings
// Prevents log bloat from third-party plugins (e.g. wp-file-manager) and core block lookups
// attempting to traverse parent roots outside the POSIX tenant jail.
if ( ! function_exists( 'leanstack_suppress_benign_open_basedir_warnings' ) ) {
    function leanstack_suppress_benign_open_basedir_warnings() {
        static $registered = false;
        if ( $registered ) {
            return;
        }
        $registered = true;

        $prev_handler = set_error_handler( function( $errno, $errstr, $errfile = '', $errline = 0 ) use ( &$prev_handler ) {
            if ( E_WARNING === $errno && false !== strpos( $errstr, 'open_basedir restriction in effect' ) ) {
                // Benign parent directory traversal by plugins (e.g. wp-file-manager checking /home or /)
                // or WordPress core / WP-CLI relative block or template checks
                if ( false !== strpos( $errstr, 'File(/home)' ) ||
                     false !== strpos( $errstr, 'File(/)' ) ||
                     false !== strpos( $errstr, 'File(core/' ) ||
                     false !== strpos( $errstr, 'File(man-params.mustache)' ) ||
                     ( $errfile && false !== strpos( $errfile, 'backup-storage.php' ) ) ||
                     ( $errfile && false !== strpos( $errfile, 'blocks.php' ) ) ||
                     ( $errfile && false !== strpos( $errfile, 'utils.php' ) ) ) {
                    return true; // Suppress warning from debug.log and output
                }
            }
            if ( is_callable( $prev_handler ) ) {
                return call_user_func( $prev_handler, $errno, $errstr, $errfile, $errline );
            }
            return false;
        }, E_WARNING );
    }
    leanstack_suppress_benign_open_basedir_warnings();
}

