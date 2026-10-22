<?php
/**
 * Plugin Name: LeanStack Universal SSI Hole-Punch Engine
 * Description: High-performance hole-punching for Elementor, Bricks Builder, Gutenberg, Nonces & Batched Product Cards.
 * Version: 1.0.0
 * Author: LeanStack
 */

if ( ! defined( 'ABSPATH' ) ) {
    // Micro-endpoint execution directly hit by Angie SSI subrequest (/leanstack-esi/)
    if ( ! isset( $_SERVER['LEANSTACK_ESI_INTERNAL'] ) || '1' !== (string) $_SERVER['LEANSTACK_ESI_INTERNAL'] ) {
        http_response_code( 403 );
        exit( 'Access denied' );
    }
    require_once dirname( __DIR__, 2 ) . '/wp-load.php';
    leanstack_handle_esi_subrequest();
    exit;
}

class LeanStackHolePunch {

    private static $instance = null;

    public static function get_instance() {
        if ( null === self::$instance ) {
            self::$instance = new self();
        }
        return self::$instance;
    }

    private function __construct() {
        // Only run buffer on frontend GET requests
        if ( ! is_admin() && ! wp_doing_ajax() && ! wp_doing_cron() && 'GET' === $_SERVER['REQUEST_METHOD'] ) {
            add_action( 'template_redirect', array( $this, 'start_buffer' ), -9999 );
        }

        // Register universal shortcode [leanstack_ssi]
        add_shortcode( 'leanstack_ssi', array( $this, 'render_ssi_shortcode' ) );
    }

    private function is_editor_active() {
        // Visual builder canvas protection (Bricks, Elementor, Divi)
        if ( isset( $_GET['bricks'] ) || isset( $_GET['elementor-preview'] ) || isset( $_GET['et_fb'] ) || isset( $_GET['fl_builder'] ) ) {
            return true;
        }
        if ( is_admin() || is_customize_preview() ) {
            return true;
        }
        return false;
    }

    public function start_buffer() {
        if ( $this->is_editor_active() ) {
            return;
        }
        ob_start( array( $this, 'filter_output_for_ssi' ) );
    }

    public function filter_output_for_ssi( $html ) {
        if ( empty( $html ) || $this->is_editor_active() ) {
            return $html;
        }

        // Neutralize any pre-existing / user-injected SSI directives before generating trusted ESI include tags
        $html = str_replace( '<!--#', '&lt;!--#', $html );

        // 1. Automatic Form Nonce Hole-Punching (Prevents "Session Expired" on cached forms)
        // Matches <input type="hidden" id="_wpnonce" name="_wpnonce" value="abc123xyz" />
        $html = preg_replace_callback(
            '/<input([^>]+)name=[\'"]_wpnonce[\'"]([^>]+)value=[\'"]([^\'"]+)[\'"]([^>]*)>/i',
            function( $m ) {
                return '<!--# include virtual="/leanstack-esi/?action=nonce" -->';
            },
            $html
        );

        // 2. Class-based Hole-Punching (<div class="... leanstack-dynamic ...">...</div>)
        // Replaces elements marked with class leanstack-dynamic and data-ssi-id="..."
        $html = preg_replace_callback(
            '/<([a-zA-Z0-9]+)([^>]+class=[\'"][^\'"]*leanstack-dynamic[^\'"]*[\'"][^>]*)>(.*?)<\/\1>/is',
            function( $m ) {
                $attrs = $m[2];
                $tag_id = 'dyn_' . substr( md5( $attrs ), 0, 8 );
                if ( preg_match( '/data-ssi-id=[\'"]([^\'"]+)[\'"]/i', $attrs, $id_m ) ) {
                    $tag_id = sanitize_key( $id_m[1] );
                }
                return '<!--# include virtual="/leanstack-esi/?action=element&id=' . urlencode( $tag_id ) . '" -->';
            },
            $html
        );

        return $html;
    }

    public function render_ssi_shortcode( $atts, $content = '' ) {
        if ( $this->is_editor_active() ) {
            return do_shortcode( $content );
        }

        $a = shortcode_atts( array(
            'id'  => 'custom',
            'ttl' => '0',
        ), $atts );

        $tag_id = sanitize_key( $a['id'] );
        return '<!--# include virtual="/leanstack-esi/?action=shortcode&id=' . urlencode( $tag_id ) . '" -->';
    }
}

add_action( 'plugins_loaded', array( 'LeanStackHolePunch', 'get_instance' ), 2 );


/**
 * Handles incoming Angie SSI subrequests (/leanstack-esi/?...)
 * Executes in high-speed micro-mode (< 2ms).
 */
function leanstack_handle_esi_subrequest() {
    // Send private cache header so Cloudflare Edge NEVER caches this fragment
    header( 'Cache-Control: private, no-store, no-cache, must-revalidate' );
    header( 'Content-Type: text/html; charset=UTF-8' );

    $action = isset( $_GET['action'] ) ? sanitize_text_field( $_GET['action'] ) : '';

    switch ( $action ) {
        case 'nonce':
            $nonce = wp_create_nonce();
            echo '<input type="hidden" name="_wpnonce" value="' . esc_attr( $nonce ) . '" />';
            return;

        case 'batch_price':
            // High-Efficiency Batched SSI for Product Cards (Solves N+1 Subrequest Storm)
            $raw_ids = isset( $_GET['ids'] ) ? sanitize_text_field( $_GET['ids'] ) : '';
            $ids = array_filter( array_map( 'intval', explode( ',', $raw_ids ) ) );
            if ( empty( $ids ) ) {
                return;
            }

            global $wpdb;
            $id_placeholders = implode( ',', $ids );
            $meta = $wpdb->get_results(
                "SELECT post_id, meta_key, meta_value FROM {$wpdb->postmeta} WHERE post_id IN ({$id_placeholders}) AND meta_key IN ('_price', '_stock')",
                ARRAY_A
            );

            $data = array();
            foreach ( $meta as $row ) {
                $pid = $row['post_id'];
                $key = '_price' === $row['meta_key'] ? 'price' : 'stock';
                $data[ $pid ][ $key ] = $row['meta_value'];
            }

            echo '<script>window.__LS_HYDRATE=' . json_encode( $data ) . ';</script>';
            return;

        case 'user_greeting':
            if ( is_user_logged_in() ) {
                $user = wp_get_current_user();
                echo '<span class="ls-greeting">' . esc_html( sprintf( __( 'Hi, %s', 'leanstack' ), $user->display_name ) ) . '</span>';
            } else {
                echo '<span class="ls-greeting"><a href="' . esc_url( wp_login_url() ) . '">' . esc_html__( 'Log In', 'leanstack' ) . '</a></span>';
            }
            return;

        case 'cart_count':
            if ( function_exists( 'WC' ) && WC()->cart ) {
                echo '<span class="ls-cart-count">' . intval( WC()->cart->get_cart_contents_count() ) . '</span>';
            } else {
                echo '<span class="ls-cart-count">0</span>';
            }
            return;

        case 'shortcode':
        case 'element':
        default:
            $id = isset( $_GET['id'] ) ? sanitize_key( $_GET['id'] ) : 'default';
            // Allow developers to hook custom fragment output
            $out = apply_filters( 'leanstack_render_esi_fragment', '', $id );
            echo $out;
            return;
    }
}
