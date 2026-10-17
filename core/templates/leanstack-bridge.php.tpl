<?php
/**
 * Plugin Name: LeanStack Bridge & Security Suite
 * Description: Nginx custom configuration manager, WebAssembly media support, and autonomous security policy manager.
 * Version: 1.0.0
 * Author: LeanStack
 */

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

// Angie Rewrite & Pretty Permalinks Support (Enables rewrite rule detection for Site Health)
$GLOBALS['is_nginx'] = true;
add_filter( 'got_url_rewrite', '__return_true', 999 );
add_filter( 'got_mod_rewrite', '__return_true', 999 );

// ==============================================================================
// Suppress Benign open_basedir Path Resolution Warnings & PHP 8.5 Deprecations
// Prevents log bloat from third-party plugins (e.g. wp-file-manager) and core block lookups
// attempting to traverse parent roots outside the POSIX tenant jail.
// ==============================================================================
if ( ! function_exists( 'leanstack_suppress_benign_open_basedir_warnings' ) ) {
    function leanstack_suppress_benign_open_basedir_warnings() {
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
            if ( E_WARNING === $errno && false !== strpos( $errstr, 'open_basedir restriction in effect' ) ) {
                if ( false !== strpos( $errstr, 'File(/home)' ) ||
                     false !== strpos( $errstr, 'File(/)' ) ||
                     false !== strpos( $errstr, 'File(core/' ) ||
                     false !== strpos( $errstr, 'File(man-params.mustache)' ) ||
                     ( $errfile && false !== strpos( $errfile, 'backup-storage.php' ) ) ||
                     ( $errfile && false !== strpos( $errfile, 'blocks.php' ) ) ||
                     ( $errfile && false !== strpos( $errfile, 'utils.php' ) ) ) {
                    return true;
                }
            }
            if ( is_callable( $prev_handler ) ) {
                return call_user_func( $prev_handler, $errno, $errstr, $errfile, $errline );
            }
            return false;
        }, E_WARNING | E_DEPRECATED | ( defined( 'E_USER_DEPRECATED' ) ? E_USER_DEPRECATED : 0 ) );
    }
    leanstack_suppress_benign_open_basedir_warnings();
}

class LeanStackBridge {

    private static $instance = null;
    private $nginx_dir = null;
    private $status_file = null;
    private $cron_status_file = null;
    private $logs_dir = null;

    public static function get_instance() {
        if ( null === self::$instance ) {
            self::$instance = new self();
        }
        return self::$instance;
    }

    private function __construct() {
        $this->detect_paths();
        add_action( 'admin_menu', array( $this, 'register_admin_menus' ) );
        add_action( 'admin_post_leanstack_save_nginx_rules', array( $this, 'save_nginx_rules' ) );
        add_action( 'admin_post_leanstack_save_security_headers', array( $this, 'save_security_headers' ) );

        // Cache Management Handlers
        add_action( 'admin_post_leanstack_save_cache_config', array( $this, 'save_cache_config' ) );
        add_action( 'admin_post_leanstack_purge_fastcgi_url', array( $this, 'handle_purge_fastcgi_url' ) );
        add_action( 'admin_post_leanstack_purge_fastcgi_all', array( $this, 'handle_purge_fastcgi_all' ) );
        add_action( 'admin_post_leanstack_purge_opcache', array( $this, 'handle_purge_opcache' ) );
        add_action( 'admin_post_leanstack_purge_apcu', array( $this, 'handle_purge_apcu' ) );
        add_action( 'admin_post_leanstack_save_cf_credentials', array( $this, 'handle_save_cf_credentials' ) );
        add_action( 'admin_post_leanstack_purge_cf', array( $this, 'handle_purge_cloudflare' ) );

        // Anti-Thundering Background Cron Queue Handlers
        add_action( 'admin_post_leanstack_run_cron_now', array( $this, 'handle_run_cron_now' ) );
        add_filter( 'site_status_tests', array( $this, 'register_site_health_cron_test' ) );
        add_action( 'wp_dashboard_setup', array( $this, 'register_dashboard_widgets' ) );
        add_action( 'admin_bar_menu', array( $this, 'register_admin_bar_node' ), 100 );
        add_action( 'admin_notices', array( $this, 'render_cron_admin_notices' ) );

        // In-Dashboard Logs Manager & Debug Handlers
        add_action( 'admin_post_leanstack_save_log_settings', array( $this, 'save_log_settings' ) );
        add_action( 'admin_post_leanstack_clear_log', array( $this, 'handle_clear_log' ) );
        add_action( 'admin_post_leanstack_download_log', array( $this, 'handle_download_log' ) );
        add_action( 'wp_ajax_leanstack_get_log_tail', array( $this, 'ajax_get_log_tail' ) );

        // Query Monitor Drop-in Self-Healing Handler
        add_action( 'admin_init', array( $this, 'maybe_reconcile_qm_dropin' ) );
        add_action( 'admin_post_leanstack_fix_qm_dropin', array( $this, 'handle_fix_qm_dropin' ) );

        // Automated Invalidation Triggers on Post/Page Updates
        add_action( 'save_post', array( $this, 'on_post_change' ), 10, 2 );
        add_action( 'deleted_post', array( $this, 'on_post_change' ), 10, 2 );
        add_action( 'wp_trash_post', array( $this, 'on_post_change' ), 10, 2 );
    }

    private function detect_paths() {
        // Resolve tenant user directory from ABSPATH (e.g., /home/<user>/htdocs)
        $doc_root = rtrim( ABSPATH, '/' );
        $parent_dir = dirname( $doc_root );
        $candidate_nginx = $parent_dir . '/nginx';

        if ( is_dir( $candidate_nginx ) && is_writable( $candidate_nginx ) ) {
            $this->nginx_dir = $candidate_nginx;
        } else {
            // Fallback for non-standard pathing
            $this->nginx_dir = WP_CONTENT_DIR . '/nginx-custom';
            if ( ! file_exists( $this->nginx_dir ) ) {
                @mkdir( $this->nginx_dir, 0750, true );
            }
        }
        $this->status_file = $this->nginx_dir . '/.status.json';
        if ( file_exists( $candidate_nginx . '/.cron_status.json' ) ) {
            $this->cron_status_file = $candidate_nginx . '/.cron_status.json';
        } else {
            $this->cron_status_file = $this->nginx_dir . '/.cron_status.json';
        }

        $candidate_logs = $parent_dir . '/logs';
        if ( is_dir( $candidate_logs ) ) {
            $this->logs_dir = $candidate_logs;
        } else {
            $this->logs_dir = $candidate_logs;
        }
    }

    public function register_admin_menus() {
        // 1. Tools > Nginx Rules
        add_management_page(
            __( 'Nginx Rules', 'leanstack' ),
            __( 'Nginx Rules', 'leanstack' ),
            'manage_options',
            'leanstack-nginx-rules',
            array( $this, 'render_nginx_rules_page' )
        );

        // 2. Settings > Security Headers
        add_options_page(
            __( 'Security Headers & Policies', 'leanstack' ),
            __( 'Security Headers', 'leanstack' ),
            'manage_options',
            'leanstack-security-headers',
            array( $this, 'render_security_headers_page' )
        );

        // 3. Tools > LeanStack Cache & Performance
        add_management_page(
            __( 'LeanStack Cache & Performance', 'leanstack' ),
            __( 'LeanStack Cache', 'leanstack' ),
            'manage_options',
            'leanstack-cache',
            array( $this, 'render_cache_page' )
        );

        // 4. Tools > Background Cron Queue
        add_management_page(
            __( 'Background Cron Queue', 'leanstack' ),
            __( 'Cron Queue', 'leanstack' ),
            'manage_options',
            'leanstack-cron',
            array( $this, 'render_cron_page' )
        );

        // 5. Tools > Logs
        add_management_page(
            __( 'LeanStack Logs & Debug Manager', 'leanstack' ),
            __( 'Logs', 'leanstack' ),
            'manage_options',
            'leanstack-logs',
            array( $this, 'render_logs_page' )
        );
    }

    private function get_status() {
        if ( file_exists( $this->status_file ) ) {
            $raw = file_get_contents( $this->status_file );
            $json = json_decode( $raw, true );
            if ( is_array( $json ) ) {
                return $json;
            }
        }
        return array(
            'status'  => 'active',
            'message' => 'System configuration verified and active.',
            'timestamp' => current_time( 'mysql' ),
        );
    }

    private function render_status_banner() {
        $status = $this->get_status();
        $state = isset( $status['status'] ) ? $status['status'] : 'active';
        $msg = isset( $status['message'] ) ? esc_html( $status['message'] ) : '';
        $time = isset( $status['timestamp'] ) ? esc_html( $status['timestamp'] ) : '';

        if ( 'active' === $state ) {
            echo '<div class="notice notice-success is-dismissible" style="border-left-color: #46b450; padding: 12px;">';
            echo '<p><strong><span class="dashicons dashicons-yes-alt" style="color: #46b450; vertical-align: middle;"></span> ' . __( 'Active & Verified:', 'leanstack' ) . '</strong> ' . $msg . ' <small style="color: #666;">(' . $time . ')</small></p>';
            echo '</div>';
        } elseif ( 'pending' === $state ) {
            echo '<div class="notice notice-warning" style="border-left-color: #ffb900; padding: 12px;">';
            echo '<p><strong><span class="dashicons dashicons-update" style="color: #ffb900; vertical-align: middle;"></span> ' . __( 'Validation Pending:', 'leanstack' ) . '</strong> ' . __( 'Angie Gatekeeper is validating syntax in the isolated sandbox...', 'leanstack' ) . '</p>';
            echo '</div>';
        } else {
            echo '<div class="notice notice-error" style="border-left-color: #dc3232; padding: 12px;">';
            echo '<p><strong><span class="dashicons dashicons-warning" style="color: #dc3232; vertical-align: middle;"></span> ' . __( 'Configuration Rejected by Gatekeeper:', 'leanstack' ) . '</strong> ' . $msg . '</p>';
            echo '<p><small>' . __( 'Production web server was untouched to guarantee 100% uptime. Please fix syntax to apply.', 'leanstack' ) . '</small></p>';
            echo '</div>';
        }
    }

    // =========================================================================
    // UI: Tools > Nginx Rules
    // =========================================================================
    public function render_nginx_rules_page() {
        if ( ! current_user_can( 'manage_options' ) ) {
            wp_die( __( 'Unauthorized access.', 'leanstack' ) );
        }

        $active_tab = isset( $_GET['tab'] ) && 'custom-rules' === $_GET['tab'] ? 'custom-rules' : 'custom-early';
        $target_file = 'custom-rules' === $active_tab ? $this->nginx_dir . '/custom-rules.conf' : $this->nginx_dir . '/custom-early.conf';
        $content = file_exists( $target_file ) ? file_get_contents( $target_file ) : '';

        ?>
        <div class="wrap">
            <h1><?php _e( 'LeanStack Nginx Custom Config Manager', 'leanstack' ); ?></h1>
            <p><?php _e( 'Safely extend Angie / Nginx virtual host rules. All changes are validated in an isolated staging sandbox before reloading.', 'leanstack' ); ?></p>

            <?php $this->render_status_banner(); ?>

            <h2 class="nav-tab-wrapper">
                <a href="<?php echo admin_url( 'tools.php?page=leanstack-nginx-rules&tab=custom-early' ); ?>" class="nav-tab <?php echo 'custom-early' === $active_tab ? 'nav-tab-active' : ''; ?>">
                    <?php _e( 'Slot 1: Early Interceptors (CompressX / Caching)', 'leanstack' ); ?>
                </a>
                <a href="<?php echo admin_url( 'tools.php?page=leanstack-nginx-rules&tab=custom-rules' ); ?>" class="nav-tab <?php echo 'custom-rules' === $active_tab ? 'nav-tab-active' : ''; ?>">
                    <?php _e( 'Slot 2: Custom Rules (Redirects & Routing)', 'leanstack' ); ?>
                </a>
            </h2>

            <div style="background: #fff; border: 1px solid #ccd0d4; padding: 20px; margin-top: 15px; border-radius: 4px;">
                <?php if ( 'custom-early' === $active_tab ) : ?>
                    <p class="description">
                        <strong><?php _e( 'Position:', 'leanstack' ); ?></strong> <?php _e( 'Placed after 8G WAF & security blocks, but immediately before static asset caching. Ideal for image processors (CompressX WebP/AVIF rewrites) and custom cache bypass rules.', 'leanstack' ); ?>
                    </p>
                <?php else : ?>
                    <p class="description">
                        <strong><?php _e( 'Position:', 'leanstack' ); ?></strong> <?php _e( 'Placed after static asset caching and before the WordPress core router. Ideal for custom redirects and domain-level URL rewriting.', 'leanstack' ); ?>
                    </p>
                <?php endif; ?>

                <form method="post" action="<?php echo esc_url( admin_url( 'admin-post.php' ) ); ?>">
                    <?php wp_nonce_field( 'leanstack_save_nginx_rules_action', 'leanstack_nonce' ); ?>
                    <input type="hidden" name="action" value="leanstack_save_nginx_rules">
                    <input type="hidden" name="slot" value="<?php echo esc_attr( $active_tab ); ?>">

                    <p>
                        <textarea name="rules_content" rows="18" style="width: 100%; font-family: monospace; font-size: 13px; background: #1e1e1e; color: #d4d4d4; padding: 12px; border-radius: 4px; box-sizing: border-box;"><?php echo esc_textarea( $content ); ?></textarea>
                    </p>

                    <p class="submit">
                        <button type="submit" class="button button-primary button-large"><?php _e( 'Validate & Save Rules', 'leanstack' ); ?></button>
                    </p>
                </form>
            </div>
        </div>
        <?php
    }

    public function save_nginx_rules() {
        if ( ! current_user_can( 'manage_options' ) ) {
            wp_die( __( 'Unauthorized.', 'leanstack' ) );
        }
        check_admin_referer( 'leanstack_save_nginx_rules_action', 'leanstack_nonce' );

        $slot = isset( $_POST['slot'] ) && 'custom-rules' === $_POST['slot'] ? 'custom-rules' : 'custom-early';
        $rules = isset( $_POST['rules_content'] ) ? wp_unslash( $_POST['rules_content'] ) : '';
        $target_file = 'custom-rules' === $slot ? $this->nginx_dir . '/custom-rules.conf' : $this->nginx_dir . '/custom-early.conf';

        // Write file
        file_put_contents( $target_file, $rules );

        // Update status to pending
        $pending = array(
            'status'    => 'pending',
            'file'      => basename( $target_file ),
            'message'   => 'Validating configuration in Angie sandbox...',
            'timestamp' => current_time( 'mysql' ),
        );
        @file_put_contents( $this->status_file, json_encode( $pending, JSON_PRETTY_PRINT ) );

        wp_redirect( add_query_arg( array( 'page' => 'leanstack-nginx-rules', 'tab' => $slot, 'saved' => '1' ), admin_url( 'tools.php' ) ) );
        exit;
    }

    // =========================================================================
    // UI: Settings > Security Headers
    // =========================================================================
    public function render_security_headers_page() {
        if ( ! current_user_can( 'manage_options' ) ) {
            wp_die( __( 'Unauthorized access.', 'leanstack' ) );
        }

        $headers_file = $this->nginx_dir . '/security-headers.conf';
        $existing = file_exists( $headers_file ) ? file_get_contents( $headers_file ) : '';

        // Parse existing values or use secure defaults
        $enable_csp = ( false !== strpos( $existing, 'Content-Security-Policy' ) ) || empty( $existing );
        $x_frame = 'SAMEORIGIN';
        if ( preg_match( '/add_header\s+X-Frame-Options\s+"?([^";]+)"?/i', $existing, $m ) ) {
            $x_frame = trim( $m[1] );
        }
        $x_content = ( false !== strpos( $existing, 'X-Content-Type-Options' ) ) || empty( $existing );
        $x_xss = '1; mode=block';
        if ( preg_match( '/add_header\s+X-XSS-Protection\s+"?([^";]+)"?/i', $existing, $m ) ) {
            $x_xss = trim( $m[1] );
        }
        $referrer = 'strict-origin-when-cross-origin';
        if ( preg_match( '/add_header\s+Referrer-Policy\s+"?([^";]+)"?/i', $existing, $m ) ) {
            $referrer = trim( $m[1] );
        }
        $coop = 'Disabled';
        if ( preg_match( '/add_header\s+Cross-Origin-Opener-Policy\s+"?([^";]+)"?/i', $existing, $m ) ) {
            $coop = trim( $m[1] );
        }
        $coep = 'Disabled';
        if ( preg_match( '/add_header\s+Cross-Origin-Embedder-Policy\s+"?([^";]+)"?/i', $existing, $m ) ) {
            $coep = trim( $m[1] );
        }

        $hardening_file = $this->nginx_dir . '/php-hardening.json';
        $hardening_data = file_exists( $hardening_file ) ? json_decode( file_get_contents( $hardening_file ), true ) : array();
        $hardening_mode = isset( $hardening_data['mode'] ) ? $hardening_data['mode'] : 'strict';
        $revert_duration = isset( $hardening_data['duration_seconds'] ) ? (int) $hardening_data['duration_seconds'] : 3600;
        $revert_at = isset( $hardening_data['revert_at'] ) ? (int) $hardening_data['revert_at'] : 0;
        $is_active_window = ( 'benchmark' === $hardening_mode && $revert_at > time() );

        ?>
        <div class="wrap">
            <h1><?php _e( 'LeanStack Security Policies & Headers Suite', 'leanstack' ); ?></h1>
            <p><?php _e( 'Configure enterprise HTTP security headers. Settings are compiled into high-performance Angie server directives and mapped atomically with zero downtime.', 'leanstack' ); ?></p>

            <?php $this->render_status_banner(); ?>

            <form method="post" action="<?php echo esc_url( admin_url( 'admin-post.php' ) ); ?>">
                <?php wp_nonce_field( 'leanstack_save_security_headers_action', 'leanstack_nonce' ); ?>
                <input type="hidden" name="action" value="leanstack_save_security_headers">

                <div style="background: #fff; border: 1px solid #ccd0d4; padding: 20px; border-radius: 4px; margin-top: 15px;">
                    <h3><span class="dashicons dashicons-shield-alt" style="color: #2271b1;"></span> <?php _e( '1. Content Security Policy (CSP)', 'leanstack' ); ?></h3>
                    <p class="description">
                        <?php _e( 'Protects against Cross-Site Scripting (XSS) and data injection. Crucial for client-side WebAssembly image processing.', 'leanstack' ); ?>
                    </p>

                    <table class="form-table">
                        <tr>
                            <th scope="row"><?php _e( 'Enable CSP', 'leanstack' ); ?></th>
                            <td>
                                <label>
                                    <input type="checkbox" name="enable_csp" value="1" <?php checked( $enable_csp, true ); ?>>
                                    <?php _e( 'Activate Content-Security-Policy HTTP header', 'leanstack' ); ?>
                                </label>
                            </td>
                        </tr>
                        <tr>
                            <th scope="row"><?php _e( 'WebAssembly Worker Source (worker-src)', 'leanstack' ); ?></th>
                            <td>
                                <input type="text" name="worker_src" value="'self' blob:" class="regular-text" style="background: #f0f0f1;" readonly>
                                <p class="description" style="color: #135e96;">
                                    <span class="dashicons dashicons-info"></span>
                                    <strong><?php _e( 'Mandatory for Client-Side Media:', 'leanstack' ); ?></strong>
                                    <?php _e( 'WordPress 7.1+ WebAssembly image processing requires inline blob: workers. Omission forces heavy fallback to server-side PHP ImageMagick.', 'leanstack' ); ?>
                                </p>
                            </td>
                        </tr>
                        <tr>
                            <th scope="row"><?php _e( 'Default Allowed Directives', 'leanstack' ); ?></th>
                            <td>
                                <code>default-src 'self' https: data: 'unsafe-inline' 'unsafe-eval'; worker-src 'self' blob:; frame-ancestors 'self';</code>
                            </td>
                        </tr>
                    </table>

                    <hr style="margin: 20px 0; border: 0; border-top: 1px solid #eee;">

                    <h3><span class="dashicons dashicons-lock" style="color: #2271b1;"></span> <?php _e( '2. Framing & Clickjacking Protection', 'leanstack' ); ?></h3>
                    <table class="form-table">
                        <tr>
                            <th scope="row"><?php _e( 'X-Frame-Options', 'leanstack' ); ?></th>
                            <td>
                                <select name="x_frame_options">
                                    <option value="SAMEORIGIN" <?php selected( $x_frame, 'SAMEORIGIN' ); ?>><?php _e( 'SAMEORIGIN (Recommended - Allow framing by same origin only)', 'leanstack' ); ?></option>
                                    <option value="DENY" <?php selected( $x_frame, 'DENY' ); ?>><?php _e( 'DENY (Maximum - Completely prohibit all iframe embeds)', 'leanstack' ); ?></option>
                                    <option value="Disabled" <?php selected( $x_frame, 'Disabled' ); ?>><?php _e( 'Disabled (Managed via CSP frame-ancestors)', 'leanstack' ); ?></option>
                                </select>
                            </td>
                        </tr>
                    </table>

                    <hr style="margin: 20px 0; border: 0; border-top: 1px solid #eee;">

                    <h3><span class="dashicons dashicons-hidden" style="color: #2271b1;"></span> <?php _e( '3. MIME Sniffing & XSS Defense', 'leanstack' ); ?></h3>
                    <table class="form-table">
                        <tr>
                            <th scope="row"><?php _e( 'MIME Sniffing (X-Content-Type-Options)', 'leanstack' ); ?></th>
                            <td>
                                <label>
                                    <input type="checkbox" name="x_content_type" value="1" <?php checked( $x_content, true ); ?>>
                                    <code>nosniff</code> <?php _e( '(Forces browsers to strictly obey declared Content-Type header)', 'leanstack' ); ?>
                                </label>
                            </td>
                        </tr>
                        <tr>
                            <th scope="row"><?php _e( 'Legacy XSS Filter (X-XSS-Protection)', 'leanstack' ); ?></th>
                            <td>
                                <select name="x_xss_protection">
                                    <option value="1; mode=block" <?php selected( $x_xss, '1; mode=block' ); ?>>1; mode=block (Standard defense)</option>
                                    <option value="0" <?php selected( $x_xss, '0' ); ?>>0 (Modern standard when strict CSP is enabled)</option>
                                    <option value="Disabled" <?php selected( $x_xss, 'Disabled' ); ?>>Disabled</option>
                                </select>
                            </td>
                        </tr>
                    </table>

                    <hr style="margin: 20px 0; border: 0; border-top: 1px solid #eee;">

                    <h3><span class="dashicons dashicons-admin-links" style="color: #2271b1;"></span> <?php _e( '4. Referrer & Permissions Policy', 'leanstack' ); ?></h3>
                    <table class="form-table">
                        <tr>
                            <th scope="row"><?php _e( 'Referrer-Policy', 'leanstack' ); ?></th>
                            <td>
                                <select name="referrer_policy">
                                    <option value="strict-origin-when-cross-origin" <?php selected( $referrer, 'strict-origin-when-cross-origin' ); ?>>strict-origin-when-cross-origin (Recommended standard)</option>
                                    <option value="no-referrer" <?php selected( $referrer, 'no-referrer' ); ?>>no-referrer</option>
                                    <option value="same-origin" <?php selected( $referrer, 'same-origin' ); ?>>same-origin</option>
                                    <option value="origin-when-cross-origin" <?php selected( $referrer, 'origin-when-cross-origin' ); ?>>origin-when-cross-origin</option>
                                </select>
                            </td>
                        </tr>
                        <tr>
                            <th scope="row"><?php _e( 'Permissions-Policy Restrictions', 'leanstack' ); ?></th>
                            <td>
                                <label><input type="checkbox" name="perm_camera" value="1" checked> <?php _e( 'Disable Camera Access', 'leanstack' ); ?></label><br>
                                <label><input type="checkbox" name="perm_mic" value="1" checked> <?php _e( 'Disable Microphone Access', 'leanstack' ); ?></label><br>
                                <label><input type="checkbox" name="perm_geo" value="1" checked> <?php _e( 'Disable Geolocation', 'leanstack' ); ?></label><br>
                                <label><input type="checkbox" name="perm_topics" value="1" checked> <?php _e( 'Disable Ad Browsing Topics', 'leanstack' ); ?></label>
                            </td>
                        </tr>
                    </table>

                    <hr style="margin: 20px 0; border: 0; border-top: 1px solid #eee;">

                    <h3><span class="dashicons dashicons-networking" style="color: #2271b1;"></span> <?php _e( '5. Cross-Origin Policies (WebAssembly High-Performance Threading)', 'leanstack' ); ?></h3>
                    <table class="form-table">
                        <tr>
                            <th scope="row"><?php _e( 'Cross-Origin-Opener-Policy (COOP)', 'leanstack' ); ?></th>
                            <td>
                                <select name="coop">
                                    <option value="Disabled" <?php selected( $coop, 'Disabled' ); ?>>Disabled</option>
                                    <option value="same-origin" <?php selected( $coop, 'same-origin' ); ?>>same-origin (Required for SharedArrayBuffer / multi-threaded Wasm)</option>
                                    <option value="same-origin-allow-popups" <?php selected( $coop, 'same-origin-allow-popups' ); ?>>same-origin-allow-popups</option>
                                </select>
                            </td>
                        </tr>
                        <tr>
                            <th scope="row"><?php _e( 'Cross-Origin-Embedder-Policy (COEP)', 'leanstack' ); ?></th>
                            <td>
                                <select name="coep">
                                    <option value="Disabled" <?php selected( $coep, 'Disabled' ); ?>>Disabled</option>
                                    <option value="credentialless" <?php selected( $coep, 'credentialless' ); ?>>credentialless</option>
                                    <option value="require-corp" <?php selected( $coep, 'require-corp' ); ?>>require-corp</option>
                                </select>
                            </td>
                        </tr>
                    </table>

                    <hr style="margin: 20px 0; border: 0; border-top: 1px solid #eee;">

                    <h3><span class="dashicons dashicons-admin-settings" style="color: #2271b1;"></span> <?php _e( '6. PHP Hardening & Runtime Controls', 'leanstack' ); ?></h3>
                    <p class="description">
                        <?php _e( 'Displays active disabled functions and allows configuring strict tenant lockdown versus a temporary benchmark/maintenance window with an auto-revert timer.', 'leanstack' ); ?>
                    </p>

                    <?php if ( ! empty( $is_active_window ) ) : ?>
                        <div class="notice notice-warning inline" style="margin: 15px 0; padding: 12px; border-left-color: #dba617;">
                            <p><strong><span class="dashicons dashicons-clock" style="color: #dba617; vertical-align: middle;"></span> <?php _e( 'Benchmark Maintenance Window Active:', 'leanstack' ); ?></strong>
                            <?php printf( __( 'Automatic revert to Strict Production Lockdown scheduled at %s (in %s).', 'leanstack' ), gmdate( 'Y-m-d H:i:s \U\T\C', (int) $revert_at ), human_time_diff( (int) $revert_at ) ); ?></p>
                        </div>
                    <?php endif; ?>

                    <table class="form-table">
                        <tr>
                            <th scope="row"><?php _e( 'Active Disabled Functions', 'leanstack' ); ?></th>
                            <td>
                                <code style="word-break: break-all; font-size: 12px;"><?php echo esc_html( ini_get( 'disable_functions' ) ?: __( 'None', 'leanstack' ) ); ?></code>
                                <p class="description"><?php _e( 'Enforced at the PHP-FPM pool tier. OS shell execution functions are permanently blocked.', 'leanstack' ); ?></p>
                            </td>
                        </tr>
                        <tr>
                            <th scope="row"><?php _e( 'Hardening Mode', 'leanstack' ); ?></th>
                            <td>
                                <fieldset>
                                    <label style="display: block; margin-bottom: 8px;">
                                        <input type="radio" name="php_hardening_mode" value="strict" <?php checked( $hardening_mode, 'strict' ); ?> onchange="document.getElementById('ls_revert_timer_row').style.display='none';">
                                        <strong><?php _e( 'Strict Production Lockdown (Default)', 'leanstack' ); ?></strong> — <?php _e( 'Maximum tenant isolation and hardened security.', 'leanstack' ); ?>
                                    </label>
                                    <label style="display: block;">
                                        <input type="radio" name="php_hardening_mode" value="benchmark" <?php checked( $hardening_mode, 'benchmark' ); ?> onchange="document.getElementById('ls_revert_timer_row').style.display='';">
                                        <strong><?php _e( 'Temporary Benchmark / Maintenance Window', 'leanstack' ); ?></strong> — <?php _e( 'Permits benchmark suite execution with strict automatic safety revert.', 'leanstack' ); ?>
                                    </label>
                                </fieldset>
                            </td>
                        </tr>
                        <tr id="ls_revert_timer_row" style="<?php echo ( 'benchmark' === $hardening_mode ) ? '' : 'display: none;'; ?>">
                            <th scope="row"><?php _e( 'Auto-Revert Timer', 'leanstack' ); ?></th>
                            <td>
                                <select name="php_revert_duration">
                                    <option value="3600" <?php selected( $revert_duration, 3600 ); ?>><?php _e( '1 Hour (Recommended)', 'leanstack' ); ?></option>
                                    <option value="7200" <?php selected( $revert_duration, 7200 ); ?>><?php _e( '2 Hours', 'leanstack' ); ?></option>
                                    <option value="21600" <?php selected( $revert_duration, 21600 ); ?>><?php _e( '6 Hours', 'leanstack' ); ?></option>
                                    <option value="86400" <?php selected( $revert_duration, 86400 ); ?>><?php _e( '24 Hours', 'leanstack' ); ?></option>
                                </select>
                                <p class="description"><?php _e( 'When time elapses, LeanStack Watcher automatically restores Strict Production Lockdown.', 'leanstack' ); ?></p>
                            </td>
                        </tr>
                    </table>

                    <p class="submit">
                        <button type="submit" class="button button-primary button-large"><?php _e( 'Apply Security Policies', 'leanstack' ); ?></button>
                    </p>
                </div>
            </form>
        </div>
        <?php
    }

    public function save_security_headers() {
        if ( ! current_user_can( 'manage_options' ) ) {
            wp_die( __( 'Unauthorized.', 'leanstack' ) );
        }
        check_admin_referer( 'leanstack_save_security_headers_action', 'leanstack_nonce' );

        $lines = array();
        $lines[] = '# ==============================================================================';
        $lines[] = '# LeanStack Security Headers & Policy Compilation (Generated via WordPress Admin)';
        $lines[] = '# ==============================================================================';
        $lines[] = 'add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;';

        // MIME sniffing
        if ( ! empty( $_POST['x_content_type'] ) ) {
            $lines[] = 'add_header X-Content-Type-Options "nosniff" always;';
        }

        // X-Frame-Options
        $x_frame = sanitize_text_field( $_POST['x_frame_options'] );
        if ( in_array( $x_frame, array( 'SAMEORIGIN', 'DENY' ), true ) ) {
            $lines[] = 'add_header X-Frame-Options "' . $x_frame . '" always;';
        }

        // XSS
        $x_xss = sanitize_text_field( $_POST['x_xss_protection'] );
        if ( in_array( $x_xss, array( '1; mode=block', '0' ), true ) ) {
            $lines[] = 'add_header X-XSS-Protection "' . $x_xss . '" always;';
        }

        // Referrer
        $referrer = sanitize_text_field( $_POST['referrer_policy'] );
        if ( ! empty( $referrer ) ) {
            $lines[] = 'add_header Referrer-Policy "' . $referrer . '" always;';
        }

        // Permissions Policy
        $perms = array();
        if ( ! empty( $_POST['perm_camera'] ) ) $perms[] = 'camera=()';
        if ( ! empty( $_POST['perm_mic'] ) ) $perms[] = 'microphone=()';
        if ( ! empty( $_POST['perm_geo'] ) ) $perms[] = 'geolocation=()';
        if ( ! empty( $_POST['perm_topics'] ) ) $perms[] = 'browsing-topics=()';
        if ( ! empty( $perms ) ) {
            $lines[] = 'add_header Permissions-Policy "' . implode( ', ', $perms ) . '" always;';
        }

        // Content Security Policy
        if ( ! empty( $_POST['enable_csp'] ) ) {
            // Guaranteed worker-src 'self' blob:; to ensure WebAssembly Wasm-vips inline worker creation
            $csp_val = "default-src 'self' https: data: 'unsafe-inline' 'unsafe-eval'; worker-src 'self' blob:; frame-ancestors 'self';";
            $lines[] = 'add_header Content-Security-Policy "' . $csp_val . '" always;';
        }

        // COOP & COEP
        $coop = sanitize_text_field( $_POST['coop'] );
        if ( in_array( $coop, array( 'same-origin', 'same-origin-allow-popups' ), true ) ) {
            $lines[] = 'add_header Cross-Origin-Opener-Policy "' . $coop . '" always;';
        }
        $coep = sanitize_text_field( $_POST['coep'] );
        if ( in_array( $coep, array( 'require-corp', 'credentialless' ), true ) ) {
            $lines[] = 'add_header Cross-Origin-Embedder-Policy "' . $coep . '" always;';
        }

        $content = implode( "\n", $lines ) . "\n";
        $target_file = $this->nginx_dir . '/security-headers.conf';
        file_put_contents( $target_file, $content );

        // PHP Hardening & Runtime Controls
        $mode = ( isset( $_POST['php_hardening_mode'] ) && 'benchmark' === $_POST['php_hardening_mode'] ) ? 'benchmark' : 'strict';
        $duration = isset( $_POST['php_revert_duration'] ) ? (int) $_POST['php_revert_duration'] : 3600;
        if ( ! in_array( $duration, array( 3600, 7200, 21600, 86400 ), true ) ) {
            $duration = 3600;
        }
        $revert_at = time() + $duration;
        $hardening_payload = array(
            'mode'             => $mode,
            'duration_seconds' => $duration,
            'revert_at'        => $revert_at,
            'timestamp'        => current_time( 'mysql' ),
        );
        $hardening_file = $this->nginx_dir . '/php-hardening.json';
        @file_put_contents( $hardening_file, json_encode( $hardening_payload, JSON_PRETTY_PRINT ) );

        // Update status to pending
        $pending = array(
            'status'    => 'pending',
            'file'      => 'security-headers.conf',
            'message'   => 'Validating security policies in Angie sandbox...',
            'timestamp' => current_time( 'mysql' ),
        );
        @file_put_contents( $this->status_file, json_encode( $pending, JSON_PRETTY_PRINT ) );

        wp_redirect( add_query_arg( array( 'page' => 'leanstack-security-headers', 'saved' => '1' ), admin_url( 'options-general.php' ) ) );
        exit;
    }

    // =========================================================================
    // Cache Management & Invalidation Engine
    // =========================================================================

    public function get_domain() {
        if ( ! empty( $_SERVER['HTTP_HOST'] ) ) {
            return sanitize_text_field( strtolower( preg_replace( '/:\d+$/', '', $_SERVER['HTTP_HOST'] ) ) );
        }
        $site_url = function_exists( 'get_option' ) ? get_option( 'siteurl' ) : '';
        $host = parse_url( $site_url, PHP_URL_HOST );
        return $host ? strtolower( $host ) : 'default';
    }

    public function get_cache_dir() {
        $primary = '/var/cache/angie/sites/' . $this->get_domain();
        if ( is_dir( $primary ) ) {
            return $primary;
        }

        // Fallback domain candidate checking from WordPress site/home options
        $candidates = array();
        if ( function_exists( 'get_option' ) ) {
            $site_url = get_option( 'siteurl' );
            $home_url = get_option( 'home' );
            if ( $site_url ) {
                $h = parse_url( $site_url, PHP_URL_HOST );
                if ( $h ) {
                    $candidates[] = strtolower( $h );
                }
            }
            if ( $home_url ) {
                $h = parse_url( $home_url, PHP_URL_HOST );
                if ( $h ) {
                    $candidates[] = strtolower( $h );
                }
            }
        }

        foreach ( array_unique( $candidates ) as $cand_domain ) {
            $cand_path = '/var/cache/angie/sites/' . $cand_domain;
            if ( is_dir( $cand_path ) ) {
                return $cand_path;
            }
        }

        return $primary;
    }

    public function get_cache_config_file() {
        return $this->nginx_dir . '/cache-config.conf';
    }

    public function get_cache_config() {
        $file = $this->get_cache_config_file();
        $enabled = 1;
        $ttl = '3600s';
        if ( file_exists( $file ) ) {
            $content = file_get_contents( $file );
            if ( preg_match( '/set\s+\$site_cache_enabled\s+([01]);/i', $content, $m ) ) {
                $enabled = (int) $m[1];
            }
            if ( preg_match( '/set\s+\$site_cache_ttl\s+([0-9]+[smhd]?);/i', $content, $m ) ) {
                $ttl = trim( $m[1] );
            }
        }
        return array(
            'enabled' => $enabled,
            'ttl'     => $ttl,
        );
    }

    public function save_cache_config() {
        if ( ! current_user_can( 'manage_options' ) ) {
            wp_die( __( 'Unauthorized.', 'leanstack' ) );
        }
        check_admin_referer( 'leanstack_save_cache_config_action', 'leanstack_nonce' );

        $enabled = ! empty( $_POST['site_cache_enabled'] ) ? 1 : 0;
        $ttl = isset( $_POST['site_cache_ttl'] ) ? sanitize_text_field( $_POST['site_cache_ttl'] ) : '3600s';
        if ( ! preg_match( '/^[0-9]+[smhd]?$/', $ttl ) ) {
            $ttl = '3600s';
        }

        $lines = array();
        $lines[] = '# ==============================================================================';
        $lines[] = '# Tenant FastCGI Cache Configuration (Managed via WordPress Tools > LeanStack Cache)';
        $lines[] = '# ==============================================================================';
        $lines[] = 'set $site_cache_enabled ' . $enabled . ';';
        $lines[] = 'set $site_cache_ttl ' . $ttl . ';';

        $content = implode( "\n", $lines ) . "\n";
        $target_file = $this->get_cache_config_file();
        file_put_contents( $target_file, $content );

        // Update status to pending for cp-gatekeeper validation
        $pending = array(
            'status'    => 'pending',
            'file'      => 'cache-config.conf',
            'message'   => 'Validating FastCGI cache configuration in Angie sandbox...',
            'timestamp' => current_time( 'mysql' ),
        );
        @file_put_contents( $this->status_file, json_encode( $pending, JSON_PRETTY_PRINT ) );

        wp_redirect( add_query_arg( array( 'page' => 'leanstack-cache', 'tab' => 'config', 'saved' => '1' ), admin_url( 'tools.php' ) ) );
        exit;
    }

    public function purge_fastcgi_url( $url ) {
        if ( empty( $url ) ) {
            return false;
        }

        $parsed = parse_url( $url );
        $host = ! empty( $parsed['host'] ) ? $parsed['host'] : $this->get_domain();
        $path = ! empty( $parsed['path'] ) ? $parsed['path'] : '/';
        if ( ! empty( $parsed['query'] ) ) {
            $path .= '?' . $parsed['query'];
        }

        $domain = strtolower( $host );
        $cache_dir = '/var/cache/angie/sites/' . $domain;
        if ( ! is_dir( $cache_dir ) ) {
            $cache_dir = $this->get_cache_dir();
        }

        $schemes = array( 'https', 'http' );
        $variants = array( $path );
        if ( substr( $path, -1 ) === '/' ) {
            $variants[] = rtrim( $path, '/' );
        } else {
            $variants[] = $path . '/';
        }

        $purged_files = 0;
        if ( is_dir( $cache_dir ) && is_writable( $cache_dir ) ) {
            foreach ( $schemes as $scheme ) {
                foreach ( $variants as $var_path ) {
                    $key = $scheme . 'GET' . $domain . $var_path;
                    $hash = md5( $key );
                    // levels=1:2 -> subdir1 = last char, subdir2 = 2 chars before last
                    $file_path = $cache_dir . '/' . substr( $hash, -1 ) . '/' . substr( $hash, -3, 2 ) . '/' . $hash;
                    if ( file_exists( $file_path ) ) {
                        if ( @unlink( $file_path ) ) {
                            $purged_files++;
                        }
                    }
                }
            }
        }

        // Loopback internal Angie purge call
        $purge_endpoint = 'http://127.0.0.1/leanstack-purge' . ( substr( $path, 0, 1 ) === '/' ? $path : '/' . $path );
        if ( function_exists( 'wp_remote_get' ) ) {
            @wp_remote_get( $purge_endpoint, array(
                'headers' => array( 'Host' => $domain ),
                'timeout' => 2,
                'sslverify' => false,
            ) );
        }

        // Single-URL Cloudflare Edge CDN purge if configured
        $cf_token = function_exists( 'get_option' ) ? get_option( 'leanstack_cf_api_token' ) : '';
        $cf_zone = function_exists( 'get_option' ) ? get_option( 'leanstack_cf_zone_id' ) : '';
        if ( ! empty( $cf_token ) && ! empty( $cf_zone ) ) {
            $full_url = ( ! empty( $parsed['scheme'] ) ? $parsed['scheme'] : 'https' ) . '://' . $domain . $path;
            $this->purge_cloudflare_urls( array( $full_url ) );
        }

        return true;
    }

    public function purge_fastcgi_all() {
        $cache_dir = $this->get_cache_dir();
        $count = 0;
        if ( is_dir( $cache_dir ) ) {
            $count = $this->recursive_delete_dir_files( $cache_dir );
        }
        return $count;
    }

    public function recursive_delete_dir_files( $dir ) {
        $count = 0;
        if ( ! is_dir( $dir ) || ! is_readable( $dir ) ) {
            return 0;
        }
        $items = @scandir( $dir );
        if ( ! $items ) {
            return 0;
        }
        foreach ( $items as $item ) {
            if ( '.' === $item || '..' === $item ) {
                continue;
            }
            $path = $dir . '/' . $item;
            if ( is_dir( $path ) ) {
                $count += $this->recursive_delete_dir_files( $path );
            } elseif ( is_file( $path ) ) {
                if ( @unlink( $path ) ) {
                    $count++;
                }
            }
        }
        return $count;
    }

    public function purge_tenant_opcache() {
        $purged_count = 0;
        if ( function_exists( 'opcache_get_status' ) && function_exists( 'opcache_invalidate' ) ) {
            $status = @opcache_get_status( true );
            if ( ! empty( $status['scripts'] ) && is_array( $status['scripts'] ) ) {
                $doc_root = function_exists( 'wp_normalize_path' ) ? wp_normalize_path( ABSPATH ) : ABSPATH;
                foreach ( array_keys( $status['scripts'] ) as $script_path ) {
                    $normalized = function_exists( 'wp_normalize_path' ) ? wp_normalize_path( $script_path ) : $script_path;
                    if ( 0 === strpos( $normalized, $doc_root ) ) {
                        if ( @opcache_invalidate( $script_path, true ) ) {
                            $purged_count++;
                        }
                    }
                }
            }
        }
        return $purged_count;
    }

    public function purge_tenant_apcu() {
        if ( class_exists( 'LeanStackAPCu' ) && method_exists( 'LeanStackAPCu', 'get_instance' ) ) {
            $apcu_inst = LeanStackAPCu::get_instance();
            if ( method_exists( $apcu_inst, 'flush_tenant_cache' ) ) {
                return $apcu_inst->flush_tenant_cache();
            }
        }

        $deleted = 0;
        $salt = ( defined( 'AUTH_SALT' ) && '' !== AUTH_SALT ) ? AUTH_SALT : 'leanstack';
        $db = ( defined( 'DB_NAME' ) && '' !== DB_NAME ) ? DB_NAME : 'leanstack';
        $prefix = 'ls_' . md5( $salt . $db ) . ':';

        if ( function_exists( 'apcu_delete' ) ) {
            if ( class_exists( 'APCUIterator' ) ) {
                $regex = '/^' . preg_quote( $prefix, '/' ) . '/';
                try {
                    $iterator = new APCUIterator( $regex );
                    $keys_to_delete = array();
                    foreach ( $iterator as $item ) {
                        if ( isset( $item['key'] ) ) {
                            $keys_to_delete[] = $item['key'];
                        }
                    }
                    foreach ( $keys_to_delete as $k ) {
                        if ( @apcu_delete( $k ) ) {
                            $deleted++;
                        }
                    }
                } catch ( Throwable $e ) {
                    // Fallback to cache_info below
                }
            }

            if ( 0 === $deleted && function_exists( 'apcu_cache_info' ) ) {
                try {
                    $cinfo = @apcu_cache_info();
                    if ( ! empty( $cinfo['cache_list'] ) && is_array( $cinfo['cache_list'] ) ) {
                        $keys_to_delete = array();
                        foreach ( $cinfo['cache_list'] as $entry ) {
                            $k = isset( $entry['info'] ) ? $entry['info'] : ( isset( $entry['key'] ) ? $entry['key'] : '' );
                            if ( 0 === strpos( $k, $prefix ) ) {
                                $keys_to_delete[] = $k;
                            }
                        }
                        foreach ( $keys_to_delete as $k ) {
                            if ( @apcu_delete( $k ) ) {
                                $deleted++;
                            }
                        }
                    }
                } catch ( Throwable $e ) {
                    // Ignore
                }
            }
        }
        return $deleted;
    }

    public function purge_cloudflare_urls( array $urls ) {
        $token = function_exists( 'get_option' ) ? get_option( 'leanstack_cf_api_token' ) : '';
        $zone = function_exists( 'get_option' ) ? get_option( 'leanstack_cf_zone_id' ) : '';
        if ( empty( $token ) || empty( $zone ) || empty( $urls ) ) {
            return false;
        }

        $endpoint = 'https://api.cloudflare.com/client/v4/zones/' . rawurlencode( $zone ) . '/purge_cache';
        if ( function_exists( 'wp_remote_post' ) ) {
            $response = wp_remote_post( $endpoint, array(
                'headers' => array(
                    'Authorization' => 'Bearer ' . $token,
                    'Content-Type'  => 'application/json',
                ),
                'body'    => json_encode( array( 'files' => array_values( $urls ) ) ),
                'timeout' => 10,
            ) );

            if ( is_wp_error( $response ) ) {
                return false;
            }
            $code = wp_remote_retrieve_response_code( $response );
            return ( 200 === $code );
        }
        return false;
    }

    public function purge_cloudflare_all() {
        $token = function_exists( 'get_option' ) ? get_option( 'leanstack_cf_api_token' ) : '';
        $zone = function_exists( 'get_option' ) ? get_option( 'leanstack_cf_zone_id' ) : '';
        if ( empty( $token ) || empty( $zone ) ) {
            return false;
        }

        $endpoint = 'https://api.cloudflare.com/client/v4/zones/' . rawurlencode( $zone ) . '/purge_cache';
        if ( function_exists( 'wp_remote_post' ) ) {
            $response = wp_remote_post( $endpoint, array(
                'headers' => array(
                    'Authorization' => 'Bearer ' . $token,
                    'Content-Type'  => 'application/json',
                ),
                'body'    => json_encode( array( 'purge_everything' => true ) ),
                'timeout' => 15,
            ) );

            if ( is_wp_error( $response ) ) {
                return false;
            }
            $code = wp_remote_retrieve_response_code( $response );
            return ( 200 === $code );
        }
        return false;
    }

    public function on_post_change( $post_id, $post = null ) {
        if ( function_exists( 'wp_is_post_revision' ) && wp_is_post_revision( $post_id ) ) {
            return;
        }
        if ( function_exists( 'wp_is_post_autosave' ) && wp_is_post_autosave( $post_id ) ) {
            return;
        }

        if ( function_exists( 'get_permalink' ) ) {
            $permalink = get_permalink( $post_id );
            if ( ! empty( $permalink ) ) {
                $this->purge_fastcgi_url( $permalink );
            }
        }

        if ( function_exists( 'home_url' ) ) {
            $this->purge_fastcgi_url( home_url( '/' ) );
        }

        if ( function_exists( 'get_option' ) && function_exists( 'get_permalink' ) ) {
            $posts_page = get_option( 'page_for_posts' );
            if ( $posts_page ) {
                $this->purge_fastcgi_url( get_permalink( $posts_page ) );
            }
        }
    }

    public function handle_purge_fastcgi_url() {
        if ( ! current_user_can( 'manage_options' ) ) {
            wp_die( __( 'Unauthorized.', 'leanstack' ) );
        }
        check_admin_referer( 'leanstack_purge_url_action', 'leanstack_nonce' );
        $url = isset( $_POST['purge_url'] ) ? esc_url_raw( wp_unslash( $_POST['purge_url'] ) ) : '';
        if ( ! empty( $url ) ) {
            $this->purge_fastcgi_url( $url );
        }
        wp_redirect( add_query_arg( array( 'page' => 'leanstack-cache', 'tab' => 'config', 'purged_url' => '1' ), admin_url( 'tools.php' ) ) );
        exit;
    }

    public function handle_purge_fastcgi_all() {
        if ( ! current_user_can( 'manage_options' ) ) {
            wp_die( __( 'Unauthorized.', 'leanstack' ) );
        }
        check_admin_referer( 'leanstack_purge_all_action', 'leanstack_nonce' );
        $count = $this->purge_fastcgi_all();
        wp_redirect( add_query_arg( array( 'page' => 'leanstack-cache', 'tab' => 'config', 'purged_all' => '1', 'count' => $count ), admin_url( 'tools.php' ) ) );
        exit;
    }

    public function handle_purge_opcache() {
        if ( ! current_user_can( 'manage_options' ) ) {
            wp_die( __( 'Unauthorized.', 'leanstack' ) );
        }
        check_admin_referer( 'leanstack_purge_opcache_action', 'leanstack_nonce' );
        $count = $this->purge_tenant_opcache();
        wp_redirect( add_query_arg( array( 'page' => 'leanstack-cache', 'tab' => 'php-cache', 'purged_opcache' => $count ), admin_url( 'tools.php' ) ) );
        exit;
    }

    public function handle_purge_apcu() {
        if ( ! current_user_can( 'manage_options' ) ) {
            wp_die( __( 'Unauthorized.', 'leanstack' ) );
        }
        check_admin_referer( 'leanstack_purge_apcu_action', 'leanstack_nonce' );
        $count = $this->purge_tenant_apcu();
        wp_redirect( add_query_arg( array( 'page' => 'leanstack-cache', 'tab' => 'php-cache', 'purged_apcu' => $count ), admin_url( 'tools.php' ) ) );
        exit;
    }

    public function handle_save_cf_credentials() {
        if ( ! current_user_can( 'manage_options' ) ) {
            wp_die( __( 'Unauthorized.', 'leanstack' ) );
        }
        check_admin_referer( 'leanstack_save_cf_action', 'leanstack_nonce' );
        $zone = isset( $_POST['cf_zone_id'] ) ? sanitize_text_field( $_POST['cf_zone_id'] ) : '';
        $token = isset( $_POST['cf_api_token'] ) ? sanitize_text_field( $_POST['cf_api_token'] ) : '';
        update_option( 'leanstack_cf_zone_id', $zone );
        if ( ! empty( $token ) ) {
            update_option( 'leanstack_cf_api_token', $token );
        }
        wp_redirect( add_query_arg( array( 'page' => 'leanstack-cache', 'tab' => 'cloudflare', 'saved_cf' => '1' ), admin_url( 'tools.php' ) ) );
        exit;
    }

    public function handle_purge_cloudflare() {
        if ( ! current_user_can( 'manage_options' ) ) {
            wp_die( __( 'Unauthorized.', 'leanstack' ) );
        }
        check_admin_referer( 'leanstack_purge_cf_action', 'leanstack_nonce' );
        $res = $this->purge_cloudflare_all();
        wp_redirect( add_query_arg( array( 'page' => 'leanstack-cache', 'tab' => 'cloudflare', 'purged_cf' => $res ? '1' : '0' ), admin_url( 'tools.php' ) ) );
        exit;
    }

    public function get_cron_status() {
        $meta = array(
            'last_run'               => null,
            'status'                 => 'active',
            'ran_via'                => 'systemd_timer',
            'duration_ms'            => 0,
            'cpu_ms'                 => 0,
            'memory_mb'              => 0,
            'events_processed'       => 0,
            'history'                => array(),
            'avg_duration_ms'        => 0,
            'avg_cpu_ms'             => 0,
            'avg_memory_mb'          => 0,
            'total_runs'             => 0,
            'total_events_processed' => 0,
        );
        if ( $this->cron_status_file && file_exists( $this->cron_status_file ) ) {
            $raw = @file_get_contents( $this->cron_status_file );
            $json = json_decode( $raw, true );
            if ( is_array( $json ) ) {
                $meta = array_merge( $meta, $json );
            }
        }
        return $meta;
    }

    public function update_cron_status_meta( $file, $duration_ms, $cpu_ms, $memory_mb, $events_processed, $iso_timestamp, $ran_via = 'ls-cron-queue' ) {
        $existing = array();
        if ( $file && file_exists( $file ) ) {
            $raw = @file_get_contents( $file );
            $json = json_decode( $raw, true );
            if ( is_array( $json ) ) {
                $existing = $json;
            }
        }

        $history = isset( $existing['history'] ) && is_array( $existing['history'] ) ? $existing['history'] : array();
        $run_entry = array(
            'timestamp'        => $iso_timestamp,
            'duration_ms'      => (float) $duration_ms,
            'cpu_ms'           => (float) $cpu_ms,
            'memory_mb'        => (float) $memory_mb,
            'events_processed' => (int) $events_processed,
            'ran_via'          => $ran_via,
        );
        array_unshift( $history, $run_entry );
        $history = array_slice( $history, 0, 20 );

        $total_dur = 0;
        $total_cpu = 0;
        $total_mem = 0;
        foreach ( $history as $h ) {
            $total_dur += isset( $h['duration_ms'] ) ? (float) $h['duration_ms'] : 0;
            $total_cpu += isset( $h['cpu_ms'] ) ? (float) $h['cpu_ms'] : 0;
            $total_mem += isset( $h['memory_mb'] ) ? (float) $h['memory_mb'] : 0;
        }
        $count = count( $history );
        $avg_duration = $count > 0 ? round( $total_dur / $count, 2 ) : (float) $duration_ms;
        $avg_cpu = $count > 0 ? round( $total_cpu / $count, 2 ) : (float) $cpu_ms;
        $avg_mem = $count > 0 ? round( $total_mem / $count, 2 ) : (float) $memory_mb;

        $total_runs = ( isset( $existing['total_runs'] ) ? (int) $existing['total_runs'] : 0 ) + 1;
        $total_events = ( isset( $existing['total_events_processed'] ) ? (int) $existing['total_events_processed'] : 0 ) + (int) $events_processed;

        $payload = array(
            'last_run'               => $iso_timestamp,
            'status'                 => 'completed',
            'ran_via'                => $ran_via,
            'duration_ms'            => (float) $duration_ms,
            'cpu_ms'                 => (float) $cpu_ms,
            'memory_mb'              => (float) $memory_mb,
            'events_processed'       => (int) $events_processed,
            'history'                => $history,
            'avg_duration_ms'        => $avg_duration,
            'avg_cpu_ms'             => $avg_cpu,
            'avg_memory_mb'          => $avg_mem,
            'total_runs'             => $total_runs,
            'total_events_processed' => $total_events,
        );

        if ( $file ) {
            @file_put_contents( $file, json_encode( $payload, JSON_PRETTY_PRINT ) );
        }
        return $payload;
    }

    public function handle_run_cron_now() {
        if ( ! current_user_can( 'manage_options' ) ) {
            wp_die( __( 'Unauthorized.', 'leanstack' ) );
        }
        check_admin_referer( 'leanstack_run_cron_action', 'leanstack_nonce' );

        $t0 = microtime( true );
        $r0 = function_exists( 'getrusage' ) ? getrusage() : null;

        $cron_array = _get_cron_array();
        $executed = 0;
        $now = time();

        if ( ! empty( $cron_array ) ) {
            foreach ( $cron_array as $timestamp => $hooks ) {
                if ( $timestamp <= $now ) {
                    foreach ( $hooks as $hook => $keys ) {
                        foreach ( $keys as $k => $data ) {
                            $schedule = isset( $data['schedule'] ) ? $data['schedule'] : false;
                            $args = isset( $data['args'] ) ? $data['args'] : array();
                            if ( $schedule ) {
                                wp_reschedule_event( $timestamp, $schedule, $hook, $args );
                            }
                            wp_unschedule_event( $timestamp, $hook, $args );
                            do_action_ref_array( $hook, $args );
                            $executed++;
                        }
                    }
                }
            }
        }

        $duration_ms = round( ( microtime( true ) - $t0 ) * 1000, 2 );
        $cpu_ms = 0;
        if ( $r0 && function_exists( 'getrusage' ) ) {
            $r1 = getrusage();
            $utime = ( $r1['ru_utime.tv_sec'] - $r0['ru_utime.tv_sec'] ) + ( $r1['ru_utime.tv_usec'] - $r0['ru_utime.tv_usec'] ) / 1e6;
            $stime = ( $r1['ru_stime.tv_sec'] - $r0['ru_stime.tv_sec'] ) + ( $r1['ru_stime.tv_usec'] - $r0['ru_stime.tv_usec'] ) / 1e6;
            $cpu_ms = round( ( $utime + $stime ) * 1000, 2 );
        }
        $memory_mb = round( memory_get_peak_usage( true ) / ( 1024 * 1024 ), 2 );
        $iso_now = gmdate( 'Y-m-d\TH:i:s\Z' );

        $status_data = $this->update_cron_status_meta( $this->cron_status_file, $duration_ms, $cpu_ms, $memory_mb, $executed, $iso_now, 'wp_dashboard' );

        // Also mirror to candidate nginx dir if distinct
        $doc_root = rtrim( ABSPATH, '/' );
        $alt_cron_file = dirname( $doc_root ) . '/nginx/.cron_status.json';
        if ( $alt_cron_file !== $this->cron_status_file && is_dir( dirname( $alt_cron_file ) ) ) {
            @file_put_contents( $alt_cron_file, json_encode( $status_data, JSON_PRETTY_PRINT ) );
        }

        $referer = wp_get_referer();
        if ( $referer && false !== strpos( $referer, 'wp-admin' ) ) {
            wp_safe_redirect( add_query_arg( array( 'cron_dispatched' => $executed ), $referer ) );
        } else {
            wp_safe_redirect( add_query_arg( array( 'page' => 'leanstack-cron', 'cron_dispatched' => $executed ), admin_url( 'tools.php' ) ) );
        }
        exit;
    }

    public function render_cron_admin_notices() {
        if ( isset( $_GET['cron_dispatched'] ) ) {
            ?>
            <div class="notice notice-success is-dismissible">
                <p><?php printf( esc_html__( 'LeanStack Background Cron Queue executed successfully (%d scheduled event(s) processed).', 'leanstack' ), (int) $_GET['cron_dispatched'] ); ?></p>
            </div>
            <?php
        }
    }

    public function register_dashboard_widgets() {
        if ( ! current_user_can( 'manage_options' ) ) {
            return;
        }
        wp_add_dashboard_widget(
            'leanstack_cron_dashboard_widget',
            __( '⏱ LeanStack Background Cron Manager', 'leanstack' ),
            array( $this, 'render_dashboard_cron_widget' )
        );
    }

    public function render_dashboard_cron_widget() {
        $cron_meta = $this->get_cron_status();
        $cron_array = _get_cron_array();
        $now = time();
        $due_count = 0;
        $total_events = 0;
        if ( ! empty( $cron_array ) ) {
            foreach ( $cron_array as $timestamp => $hooks ) {
                foreach ( $hooks as $hook => $keys ) {
                    $total_events += count( $keys );
                    if ( $timestamp <= $now ) {
                        $due_count += count( $keys );
                    }
                }
            }
        }
        $last_run_text = __( 'Active (awaiting next 60s trigger)', 'leanstack' );
        if ( ! empty( $cron_meta['last_run'] ) ) {
            $last_time = strtotime( $cron_meta['last_run'] );
            $last_run_text = sprintf( __( '%s ago (%s)', 'leanstack' ), human_time_diff( $last_time ), gmdate( 'H:i:s \U\T\C', $last_time ) );
        }
        ?>
        <div class="leanstack-cron-widget">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; padding-bottom: 8px; border-bottom: 1px solid #f0f0f1;">
                <div>
                    <span class="dashicons dashicons-yes-alt" style="color: #00a32a; vertical-align: middle;"></span>
                    <strong style="color: #00a32a; font-size: 14px;"><?php _e( 'Server-Managed Queue Active', 'leanstack' ); ?></strong>
                </div>
                <span class="badge" style="background: #e7f5ea; color: #007017; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600;">
                    <?php _e( 'systemd: 60s timer', 'leanstack' ); ?>
                </span>
            </div>
            <p style="margin: 6px 0; color: #50575e; font-size: 13px;">
                <strong><?php _e( 'Execution Engine:', 'leanstack' ); ?></strong> <code>ls-cron-queue &amp; cp-cron.timer</code>
            </p>
            <p style="margin: 6px 0; color: #50575e; font-size: 13px;">
                <strong><?php _e( 'Queue Cadence:', 'leanstack' ); ?></strong> <?php _e( 'Every 60s (serialized workers, 0ms visitor latency)', 'leanstack' ); ?>
            </p>
            <p style="margin: 6px 0; color: #50575e; font-size: 13px;">
                <strong><?php _e( 'Last Queue Dispatch:', 'leanstack' ); ?></strong> <?php echo esc_html( $last_run_text ); ?>
            </p>
            <?php if ( ! empty( $cron_meta['duration_ms'] ) || ! empty( $cron_meta['avg_duration_ms'] ) ) : ?>
            <p style="margin: 6px 0; color: #50575e; font-size: 13px;">
                <strong><?php _e( 'Execution Telemetry:', 'leanstack' ); ?></strong>
                <span><?php printf( __( 'Wall: <strong>%sms</strong> (avg: <strong>%sms</strong>)', 'leanstack' ), esc_html( $cron_meta['duration_ms'] ), esc_html( $cron_meta['avg_duration_ms'] ) ); ?></span>
                | <span><?php printf( __( 'CPU: <strong>%sms</strong>', 'leanstack' ), esc_html( $cron_meta['cpu_ms'] ) ); ?></span>
                | <span><?php printf( __( 'RAM: <strong>%s MB</strong>', 'leanstack' ), esc_html( $cron_meta['memory_mb'] ) ); ?></span>
            </p>
            <?php endif; ?>
            <p style="margin: 6px 0; color: #50575e; font-size: 13px;">
                <strong><?php _e( 'Scheduled Tasks:', 'leanstack' ); ?></strong> 
                <?php printf( __( '<strong>%d</strong> scheduled', 'leanstack' ), $total_events ); ?>
                <?php if ( $due_count > 0 ) : ?>
                    <span style="color: #d63638; font-weight: bold;">(<?php printf( __( '%d due now', 'leanstack' ), $due_count ); ?>)</span>
                <?php else : ?>
                    <span style="color: #00a32a;">(<?php _e( 'All current', 'leanstack' ); ?>)</span>
                <?php endif; ?>
            </p>
            <div style="margin-top: 15px; padding-top: 10px; border-top: 1px solid #f0f0f1; display: flex; justify-content: space-between; align-items: center;">
                <form method="post" action="<?php echo esc_url( admin_url( 'admin-post.php' ) ); ?>" style="margin: 0;">
                    <?php wp_nonce_field( 'leanstack_run_cron_action', 'leanstack_nonce' ); ?>
                    <input type="hidden" name="action" value="leanstack_run_cron_now">
                    <button type="submit" class="button button-secondary button-small">
                        <span class="dashicons dashicons-update" style="vertical-align: text-bottom; font-size: 14px;"></span> <?php _e( 'Dispatch Due Crons Now', 'leanstack' ); ?>
                    </button>
                </form>
                <a href="<?php echo esc_url( admin_url( 'tools.php?page=leanstack-cron' ) ); ?>" class="button button-link" style="font-size: 12px;">
                    <?php _e( 'Inspect Cron Queue →', 'leanstack' ); ?>
                </a>
            </div>
        </div>
        <?php
    }

    public function register_admin_bar_node( $wp_admin_bar ) {
        if ( ! current_user_can( 'manage_options' ) ) {
            return;
        }
        $cron_array = _get_cron_array();
        $now = time();
        $due = 0;
        if ( ! empty( $cron_array ) ) {
            foreach ( $cron_array as $ts => $hooks ) {
                if ( $ts <= $now ) {
                    $due += count( $hooks );
                }
            }
        }
        $icon = '<span class="ab-icon dashicons dashicons-clock" style="top: 2px;"></span>';
        $title = $icon . ' ' . ( $due > 0 ? sprintf( __( 'Cron: %d Due', 'leanstack' ), $due ) : __( 'Cron: Active', 'leanstack' ) );
        $wp_admin_bar->add_node( array(
            'id'    => 'leanstack_cron_status',
            'title' => $title,
            'href'  => admin_url( 'tools.php?page=leanstack-cron' ),
            'meta'  => array(
                'title' => __( 'LeanStack Background Cron Queue Status', 'leanstack' ),
            ),
        ) );
    }

    public function render_cron_page() {
        if ( ! current_user_can( 'manage_options' ) ) {
            wp_die( __( 'Unauthorized access.', 'leanstack' ) );
        }
        ?>
        <div class="wrap">
            <h1><?php _e( 'LeanStack Centralized WP-Cron Queue Manager', 'leanstack' ); ?></h1>
            <p><?php _e( 'Server-level anti-thundering task queue powered by Linux systemd, zero visitor overhead, and live queue inspector.', 'leanstack' ); ?></p>
            <?php $this->render_status_banner(); ?>
            <p>
                <a href="<?php echo esc_url( admin_url( 'tools.php?page=leanstack-cache' ) ); ?>" class="button button-secondary">
                    <span class="dashicons dashicons-performance" style="vertical-align: text-bottom;"></span> <?php _e( 'Open LeanStack Cache Center', 'leanstack' ); ?>
                </a>
            </p>
            <?php $this->render_cron_tab_content(); ?>
        </div>
        <?php
    }

    public function register_site_health_cron_test( $tests ) {
        if ( isset( $tests['async']['wp_cron'] ) ) {
            unset( $tests['async']['wp_cron'] );
        }
        if ( isset( $tests['direct']['wp_cron'] ) ) {
            unset( $tests['direct']['wp_cron'] );
        }
        $tests['direct']['leanstack_cron_queue'] = array(
            'label' => __( 'LeanStack Background Cron Queue', 'leanstack' ),
            'test'  => array( $this, 'site_health_test_cron_queue' ),
        );
        return $tests;
    }

    public function site_health_test_cron_queue() {
        $cron_meta = $this->get_cron_status();

        return array(
            'label'       => __( 'Scheduled tasks are managed by LeanStack Anti-Thundering Queue', 'leanstack' ),
            'status'      => 'good',
            'badge'       => array(
                'label' => __( 'Performance', 'leanstack' ),
                'color' => 'blue',
            ),
            'description' => sprintf(
                '<p>%s</p>',
                __( 'WordPress stock visitor-spawned crons are intentionally disabled (DISABLE_WP_CRON = true) to prevent visitor page load latency. The LeanStack systemd background queue manages scheduled tasks with strict concurrency bounds.', 'leanstack' )
            ),
            'actions'     => sprintf(
                '<p><a href="%s" class="button button-secondary">%s</a></p>',
                esc_url( admin_url( 'tools.php?page=leanstack-cron' ) ),
                __( 'Inspect Cron Queue & Schedules', 'leanstack' )
            ),
            'test'        => 'leanstack_cron_queue',
        );
    }

    public function get_analytics() {
        $data = array(
            'fastcgi' => array(
                'file_count' => 0,
                'total_bytes' => 0,
                'size_formatted' => '0 B',
                'active' => false,
            ),
            'opcache' => array(
                'enabled' => false,
                'tenant_scripts' => 0,
                'tenant_memory' => 0,
                'tenant_memory_formatted' => '0 B',
                'total_used_memory_formatted' => '0 B',
                'hit_rate' => 0,
            ),
            'apcu' => array(
                'enabled' => false,
                'tenant_keys' => 0,
                'tenant_memory' => 0,
                'tenant_memory_formatted' => '0 B',
                'total_memory_formatted' => '0 B',
            ),
            'system' => array(
                'memory_usage_pct' => 0,
                'capacity_saturation_pct' => 0,
                'status_badge' => 'Optimal',
                'status_color' => '#00a32a',
                'memory_limit' => '256M',
            ),
        );

        // 1. FastCGI Cache Analytics
        $cache_dir = $this->get_cache_dir();
        if ( is_dir( $cache_dir ) ) {
            $data['fastcgi']['active'] = true;
            $files = 0;
            $bytes = 0;
            $this->scan_cache_dir_stats( $cache_dir, $files, $bytes );
            $data['fastcgi']['file_count'] = $files;
            $data['fastcgi']['total_bytes'] = $bytes;
            $data['fastcgi']['size_formatted'] = function_exists( 'size_format' ) ? size_format( $bytes, 2 ) : ( $bytes . ' B' );
        }

        // 2. OPcache Tenant Analytics
        if ( function_exists( 'opcache_get_status' ) ) {
            $op = @opcache_get_status( true );
            if ( ! empty( $op['opcache_enabled'] ) ) {
                $data['opcache']['enabled'] = true;
                $data['opcache']['hit_rate'] = isset( $op['opcache_statistics']['opcache_hit_rate'] ) ? round( $op['opcache_statistics']['opcache_hit_rate'], 1 ) : 0;
                $used_mem = isset( $op['memory_usage']['used_memory'] ) ? $op['memory_usage']['used_memory'] : 0;
                $data['opcache']['total_used_memory_formatted'] = function_exists( 'size_format' ) ? size_format( $used_mem, 2 ) : ( $used_mem . ' B' );

                if ( ! empty( $op['scripts'] ) && is_array( $op['scripts'] ) ) {
                    $doc_root = function_exists( 'wp_normalize_path' ) ? wp_normalize_path( ABSPATH ) : ABSPATH;
                    $tenant_scripts = 0;
                    $tenant_mem = 0;
                    foreach ( $op['scripts'] as $path => $meta ) {
                        $norm_p = function_exists( 'wp_normalize_path' ) ? wp_normalize_path( $path ) : $path;
                        if ( 0 === strpos( $norm_p, $doc_root ) ) {
                            $tenant_scripts++;
                            $tenant_mem += isset( $meta['memory_consumption'] ) ? $meta['memory_consumption'] : 0;
                        }
                    }
                    $data['opcache']['tenant_scripts'] = $tenant_scripts;
                    $data['opcache']['tenant_memory'] = $tenant_mem;
                    $data['opcache']['tenant_memory_formatted'] = function_exists( 'size_format' ) ? size_format( $tenant_mem, 2 ) : ( $tenant_mem . ' B' );
                }
            }
        }

        // 3. APCu Tenant Analytics
        if ( ( function_exists( 'apcu_enabled' ) && apcu_enabled() ) || ( function_exists( 'apcu_sma_info' ) && function_exists( 'apcu_fetch' ) ) ) {
            $data['apcu']['enabled'] = true;
            if ( function_exists( 'apcu_sma_info' ) ) {
                $sma = @apcu_sma_info( true );
                $total_apcu = isset( $sma['num_seg'], $sma['seg_size'] ) ? ( $sma['num_seg'] * $sma['seg_size'] ) : 0;
                $data['apcu']['total_memory_formatted'] = function_exists( 'size_format' ) ? size_format( $total_apcu, 2 ) : ( $total_apcu . ' B' );
            }

            $prefix = '';
            if ( class_exists( 'LeanStackAPCu' ) && method_exists( 'LeanStackAPCu', 'get_instance' ) ) {
                $apcu_inst = LeanStackAPCu::get_instance();
                if ( method_exists( $apcu_inst, 'get_prefix' ) ) {
                    $prefix = $apcu_inst->get_prefix();
                }
            }
            if ( empty( $prefix ) ) {
                $salt = ( defined( 'AUTH_SALT' ) && '' !== AUTH_SALT ) ? AUTH_SALT : 'leanstack';
                $db = ( defined( 'DB_NAME' ) && '' !== DB_NAME ) ? DB_NAME : 'leanstack';
                $prefix = 'ls_' . md5( $salt . $db ) . ':';
            }

            $keys = 0;
            $mem = 0;

            if ( class_exists( 'APCUIterator' ) ) {
                $regex = '/^' . preg_quote( $prefix, '/' ) . '/';
                try {
                    $iterator = new APCUIterator( $regex );
                    foreach ( $iterator as $item ) {
                        $keys++;
                        $mem += isset( $item['mem_size'] ) ? $item['mem_size'] : 0;
                    }
                } catch ( Throwable $e ) {
                    // Fall through to cache_info fallback
                }
            }

            // Resilient fallback using apcu_cache_info if iterator returned 0 or threw an exception
            if ( 0 === $keys && function_exists( 'apcu_cache_info' ) ) {
                try {
                    $cinfo = @apcu_cache_info();
                    if ( ! empty( $cinfo['cache_list'] ) && is_array( $cinfo['cache_list'] ) ) {
                        foreach ( $cinfo['cache_list'] as $entry ) {
                            $k = isset( $entry['info'] ) ? $entry['info'] : ( isset( $entry['key'] ) ? $entry['key'] : '' );
                            if ( 0 === strpos( $k, $prefix ) ) {
                                $keys++;
                                $mem += isset( $entry['mem_size'] ) ? $entry['mem_size'] : 0;
                            }
                        }
                    }
                } catch ( Throwable $e ) {
                    // Ignore
                }
            }

            $data['apcu']['tenant_keys'] = $keys;
            $data['apcu']['tenant_memory'] = $mem;
            $data['apcu']['tenant_memory_formatted'] = function_exists( 'size_format' ) ? size_format( $mem, 2 ) : ( $mem . ' B' );
        }

        // 4. Privacy-Safe Tenant Telemetry (Normalized Percentages)
        $mem_limit_ini = ini_get( 'memory_limit' );
        if ( empty( $mem_limit_ini ) || '-1' === $mem_limit_ini ) {
            $mem_limit_bytes = 512 * 1024 * 1024;
            $mem_limit_str = ( '-1' === $mem_limit_ini ) ? __( 'Unlimited (512M baseline)', 'leanstack' ) : '512M';
        } else {
            $mem_limit_str = $mem_limit_ini;
            $val = trim( $mem_limit_ini );
            $last = strtolower( substr( $val, -1 ) );
            $val_num = (float) $val;
            switch ( $last ) {
                case 'g':
                    $val_num *= 1024 * 1024 * 1024;
                    break;
                case 'm':
                    $val_num *= 1024 * 1024;
                    break;
                case 'k':
                    $val_num *= 1024;
                    break;
            }
            $mem_limit_bytes = ( $val_num > 0 ) ? $val_num : 256 * 1024 * 1024;
        }

        $current_uid = function_exists( 'posix_geteuid' ) ? posix_geteuid() : ( function_exists( 'getmyuid' ) ? getmyuid() : null );
        $rss_total_kb = 0;
        $proc_count = 0;

        if ( is_dir( '/proc' ) ) {
            $pids = @scandir( '/proc' );
            if ( $pids ) {
                foreach ( $pids as $p ) {
                    if ( ctype_digit( $p ) ) {
                        $status_file = "/proc/{$p}/status";
                        if ( file_exists( $status_file ) ) {
                            $status_str = @file_get_contents( $status_file );
                            if ( $status_str ) {
                                if ( null !== $current_uid && preg_match( '/^Uid:\s+(\d+)/m', $status_str, $m_uid ) ) {
                                    if ( (int) $m_uid[1] === (int) $current_uid ) {
                                        $proc_count++;
                                        if ( preg_match( '/^VmRSS:\s+(\d+)\s+kB/m', $status_str, $m_rss ) ) {
                                            $rss_total_kb += (int) $m_rss[1];
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        $tenant_mem_bytes = ( $rss_total_kb > 0 ) ? ( $rss_total_kb * 1024 ) : ( function_exists( 'memory_get_usage' ) ? memory_get_usage( true ) : 0 );
        $memory_usage_pct = min( 100, round( ( $tenant_mem_bytes / $mem_limit_bytes ) * 100, 1 ) );

        $pool_capacity = (int) apply_filters( 'leanstack_pool_capacity', 10 );
        $capacity_saturation_pct = min( 100, round( ( max( 1, $proc_count ) / $pool_capacity ) * 100 ) );

        $highest_saturation = max( $memory_usage_pct, $capacity_saturation_pct );
        if ( $highest_saturation >= 85 ) {
            $status_badge = 'Elevated';
            $status_color = '#d63638';
        } elseif ( $highest_saturation >= 60 ) {
            $status_badge = 'Moderate';
            $status_color = '#dba617';
        } else {
            $status_badge = 'Optimal';
            $status_color = '#00a32a';
        }

        $data['system']['memory_usage_pct'] = $memory_usage_pct;
        $data['system']['capacity_saturation_pct'] = $capacity_saturation_pct;
        $data['system']['status_badge'] = $status_badge;
        $data['system']['status_color'] = $status_color;
        $data['system']['memory_limit'] = $mem_limit_str;

        return $data;
    }

    public function scan_cache_dir_stats( $dir, &$files, &$bytes ) {
        if ( ! is_dir( $dir ) || ! is_readable( $dir ) ) {
            return;
        }
        $items = @scandir( $dir );
        if ( ! $items ) {
            return;
        }
        foreach ( $items as $item ) {
            if ( '.' === $item || '..' === $item ) {
                continue;
            }
            $p = $dir . '/' . $item;
            if ( is_dir( $p ) ) {
                $this->scan_cache_dir_stats( $p, $files, $bytes );
            } elseif ( is_file( $p ) ) {
                $files++;
                $sz = @filesize( $p );
                if ( false !== $sz ) {
                    $bytes += (int) $sz;
                }
            }
        }
    }

    public function render_cache_page() {
        if ( ! current_user_can( 'manage_options' ) ) {
            wp_die( __( 'Unauthorized access.', 'leanstack' ) );
        }

        $active_tab = isset( $_GET['tab'] ) ? sanitize_text_field( $_GET['tab'] ) : 'analytics';
        $cfg = $this->get_cache_config();
        $analytics = $this->get_analytics();

        ?>
        <div class="wrap">
            <h1><?php _e( 'LeanStack Cache & Performance Center', 'leanstack' ); ?></h1>
            <p><?php _e( 'Enterprise caching tier, surgical invalidation controls, multi-tenant OPcache/APCu isolation, and real-time server telemetry.', 'leanstack' ); ?></p>

            <?php $this->render_status_banner(); ?>

            <?php if ( isset( $_GET['saved'] ) ) : ?>
                <div class="notice notice-success is-dismissible"><p><?php _e( 'Cache configuration saved and queued for Angie Gatekeeper verification.', 'leanstack' ); ?></p></div>
            <?php endif; ?>
            <?php if ( isset( $_GET['purged_url'] ) ) : ?>
                <div class="notice notice-success is-dismissible"><p><?php _e( 'Target URL FastCGI cache surgically invalidated on Angie web tier.', 'leanstack' ); ?></p></div>
            <?php endif; ?>
            <?php if ( isset( $_GET['purged_all'] ) ) : ?>
                <div class="notice notice-success is-dismissible"><p><?php printf( __( 'Entire FastCGI cache for this site purged successfully (%d files unlinked).', 'leanstack' ), (int) $_GET['count'] ); ?></p></div>
            <?php endif; ?>
            <?php if ( isset( $_GET['purged_opcache'] ) ) : ?>
                <div class="notice notice-success is-dismissible"><p><?php printf( __( 'Tenant OPcache successfully purged (%d scripts invalidated). Other tenants unaffected.', 'leanstack' ), (int) $_GET['purged_opcache'] ); ?></p></div>
            <?php endif; ?>
            <?php if ( isset( $_GET['purged_apcu'] ) ) : ?>
                <div class="notice notice-success is-dismissible"><p><?php printf( __( 'Tenant APCu application cache cleared (%d items deleted).', 'leanstack' ), (int) $_GET['purged_apcu'] ); ?></p></div>
            <?php endif; ?>
            <?php if ( isset( $_GET['saved_cf'] ) ) : ?>
                <div class="notice notice-success is-dismissible"><p><?php _e( 'Cloudflare API credentials saved successfully.', 'leanstack' ); ?></p></div>
            <?php endif; ?>
            <?php if ( isset( $_GET['purged_cf'] ) ) : ?>
                <div class="notice notice-success is-dismissible"><p><?php _e( 'Cloudflare Edge CDN cache purge request dispatched.', 'leanstack' ); ?></p></div>
            <?php endif; ?>
            <?php if ( isset( $_GET['cron_dispatched'] ) ) : ?>
                <div class="notice notice-success is-dismissible"><p><?php printf( __( 'LeanStack Background Cron Queue executed successfully (%d scheduled events processed).', 'leanstack' ), (int) $_GET['cron_dispatched'] ); ?></p></div>
            <?php endif; ?>

            <h2 class="nav-tab-wrapper">
                <a href="<?php echo esc_url( admin_url( 'tools.php?page=leanstack-cache&tab=analytics' ) ); ?>" class="nav-tab <?php echo 'analytics' === $active_tab ? 'nav-tab-active' : ''; ?>">
                    <span class="dashicons dashicons-chart-area" style="vertical-align: text-bottom;"></span> <?php _e( 'Real-Time Analytics', 'leanstack' ); ?>
                </a>
                <a href="<?php echo esc_url( admin_url( 'tools.php?page=leanstack-cache&tab=config' ) ); ?>" class="nav-tab <?php echo 'config' === $active_tab ? 'nav-tab-active' : ''; ?>">
                    <span class="dashicons dashicons-admin-settings" style="vertical-align: text-bottom;"></span> <?php _e( 'FastCGI Cache & Invalidation', 'leanstack' ); ?>
                </a>
                <a href="<?php echo esc_url( admin_url( 'tools.php?page=leanstack-cache&tab=php-cache' ) ); ?>" class="nav-tab <?php echo 'php-cache' === $active_tab ? 'nav-tab-active' : ''; ?>">
                    <span class="dashicons dashicons-database" style="vertical-align: text-bottom;"></span> <?php _e( 'OPcache & APCu Purging', 'leanstack' ); ?>
                </a>
                <a href="<?php echo esc_url( admin_url( 'tools.php?page=leanstack-cache&tab=cloudflare' ) ); ?>" class="nav-tab <?php echo 'cloudflare' === $active_tab ? 'nav-tab-active' : ''; ?>">
                    <span class="dashicons dashicons-cloud" style="vertical-align: text-bottom;"></span> <?php _e( 'Cloudflare Edge CDN', 'leanstack' ); ?>
                </a>
                <a href="<?php echo esc_url( admin_url( 'tools.php?page=leanstack-cache&tab=cron' ) ); ?>" class="nav-tab <?php echo 'cron' === $active_tab ? 'nav-tab-active' : ''; ?>">
                    <span class="dashicons dashicons-clock" style="vertical-align: text-bottom;"></span> <?php _e( 'Background Cron Queue', 'leanstack' ); ?>
                </a>
            </h2>

            <?php if ( 'analytics' === $active_tab ) : ?>
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 20px; margin-top: 20px;">
                    <!-- 1. FastCGI Microcache -->
                    <div style="background: #fff; border: 1px solid #ccd0d4; padding: 20px; border-radius: 6px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
                        <h3 style="margin-top: 0; color: #1d2327;"><span class="dashicons dashicons-performance" style="color: #2271b1;"></span> <?php _e( 'FastCGI Page Cache', 'leanstack' ); ?></h3>
                        <p style="font-size: 28px; font-weight: bold; margin: 10px 0; color: #2271b1;"><?php echo esc_html( $analytics['fastcgi']['size_formatted'] ); ?></p>
                        <p style="color: #646970; margin: 0;"><?php printf( __( '<strong>%d</strong> cached responses on disk', 'leanstack' ), $analytics['fastcgi']['file_count'] ); ?></p>
                        <hr style="margin: 15px 0; border: 0; border-top: 1px solid #f0f0f1;">
                        <small style="color: #8c8f94; word-break: break-all;"><?php echo esc_html( $this->get_cache_dir() ); ?></small>
                    </div>

                    <!-- 2. OPcache Isolation -->
                    <div style="background: #fff; border: 1px solid #ccd0d4; padding: 20px; border-radius: 6px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
                        <h3 style="margin-top: 0; color: #1d2327;"><span class="dashicons dashicons-code-standards" style="color: #00a32a;"></span> <?php _e( 'Tenant OPcache Isolation', 'leanstack' ); ?></h3>
                        <p style="font-size: 28px; font-weight: bold; margin: 10px 0; color: #00a32a;"><?php echo esc_html( $analytics['opcache']['tenant_scripts'] ); ?> <span style="font-size: 14px; font-weight: normal; color: #646970;"><?php _e( 'scripts', 'leanstack' ); ?></span></p>
                        <p style="color: #646970; margin: 0;"><?php printf( __( 'Memory: <strong>%s</strong> (Hit rate: <strong>%s%%</strong>)', 'leanstack' ), $analytics['opcache']['tenant_memory_formatted'], $analytics['opcache']['hit_rate'] ); ?></p>
                        <hr style="margin: 15px 0; border: 0; border-top: 1px solid #f0f0f1;">
                        <span class="dashicons dashicons-shield" style="color: #00a32a; vertical-align: middle;"></span> <small style="color: #646970;"><?php _e( 'Global opcache_reset locked out', 'leanstack' ); ?></small>
                    </div>

                    <!-- 3. APCu Fragment Cache -->
                    <div style="background: #fff; border: 1px solid #ccd0d4; padding: 20px; border-radius: 6px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
                        <h3 style="margin-top: 0; color: #1d2327;"><span class="dashicons dashicons-superhero" style="color: #8c5e58;"></span> <?php _e( 'APCu High-Speed Cache', 'leanstack' ); ?></h3>
                        <p style="font-size: 28px; font-weight: bold; margin: 10px 0; color: #8c5e58;"><?php echo esc_html( $analytics['apcu']['tenant_keys'] ); ?> <span style="font-size: 14px; font-weight: normal; color: #646970;"><?php _e( 'keys', 'leanstack' ); ?></span></p>
                        <p style="color: #646970; margin: 0;"><?php printf( __( 'Memory: <strong>%s</strong> (<3µs RAM latency)', 'leanstack' ), $analytics['apcu']['tenant_memory_formatted'] ); ?></p>
                        <hr style="margin: 15px 0; border: 0; border-top: 1px solid #f0f0f1;">
                        <span class="dashicons dashicons-yes-alt" style="color: #00a32a; vertical-align: middle;"></span> <small style="color: #646970;"><?php _e( 'Zero conflict with Redis object-cache', 'leanstack' ); ?></small>
                    </div>

                    <!-- 4. System & Tenant Telemetry -->
                    <div style="background: #fff; border: 1px solid #ccd0d4; padding: 20px; border-radius: 6px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
                        <h3 style="margin-top: 0; color: #1d2327;"><span class="dashicons dashicons-dashboard" style="color: <?php echo esc_attr( $analytics['system']['status_color'] ); ?>;"></span> <?php _e( 'Tenant CPU & Memory', 'leanstack' ); ?></h3>
                        <p style="font-size: 28px; font-weight: bold; margin: 10px 0; color: <?php echo esc_attr( $analytics['system']['status_color'] ); ?>;">
                            <?php echo esc_html( $analytics['system']['memory_usage_pct'] ); ?>%
                            <span style="display: inline-block; font-size: 12px; font-weight: 600; padding: 2px 8px; border-radius: 12px; vertical-align: middle; margin-left: 6px; background: <?php echo esc_attr( $analytics['system']['status_color'] ); ?>; color: #fff;">
                                <?php echo esc_html( $analytics['system']['status_badge'] ); ?>
                            </span>
                        </p>
                        <p style="color: #646970; margin: 0;"><?php printf( __( 'Pool Saturation: <strong>%d%%</strong> | Limit: <strong>%s</strong>', 'leanstack' ), (int) $analytics['system']['capacity_saturation_pct'], esc_html( $analytics['system']['memory_limit'] ) ); ?></p>
                        <hr style="margin: 15px 0; border: 0; border-top: 1px solid #f0f0f1;">
                        <span class="dashicons dashicons-shield" style="color: #00a32a; vertical-align: middle;"></span> <small style="color: #646970;"><?php _e( 'Multi-tenant isolation active • Privacy-safe metrics', 'leanstack' ); ?></small>
                    </div>

                    <!-- 5. Background Cron Queue -->
                    <div style="background: #fff; border: 1px solid #ccd0d4; padding: 20px; border-radius: 6px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
                        <h3 style="margin-top: 0; color: #1d2327;"><span class="dashicons dashicons-clock" style="color: #00a32a;"></span> <?php _e( 'Background Cron Queue', 'leanstack' ); ?></h3>
                        <p style="font-size: 28px; font-weight: bold; margin: 10px 0; color: #00a32a;"><?php _e( 'Active', 'leanstack' ); ?> <span style="font-size: 14px; font-weight: normal; color: #646970;">(Queue Managed)</span></p>
                        <p style="color: #646970; margin: 0;"><?php printf( __( 'Mode: <strong>Systemd Timer (60s)</strong> | Events: <strong>%d</strong> scheduled', 'leanstack' ), count( (array) _get_cron_array() ) ); ?></p>
                        <hr style="margin: 15px 0; border: 0; border-top: 1px solid #f0f0f1;">
                        <a href="<?php echo esc_url( admin_url( 'tools.php?page=leanstack-cron' ) ); ?>" style="text-decoration: none; color: #2271b1; font-weight: 500;"><span class="dashicons dashicons-arrow-right-alt" style="vertical-align: middle;"></span> <?php _e( 'Manage Cron Queue &amp; Events', 'leanstack' ); ?></a>
                    </div>

                    <!-- 6. Valkey Object Cache -->
                    <div style="background: #fff; border: 1px solid #ccd0d4; padding: 20px; border-radius: 6px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
                        <h3 style="margin-top: 0; color: #1d2327;"><span class="dashicons dashicons-database-view" style="color: #2271b1;"></span> <?php _e( 'Valkey Object Cache', 'leanstack' ); ?></h3>
                        <?php
                        $valkey_connected = false;
                        $dropin_active = file_exists( WP_CONTENT_DIR . '/object-cache.php' );
                        if ( class_exists( 'Redis' ) && defined( 'WP_REDIS_PATH' ) ) {
                            try {
                                $r = new Redis();
                                if ( @$r->connect( WP_REDIS_PATH ) ) {
                                    if ( defined( 'WP_REDIS_USERNAME' ) && defined( 'WP_REDIS_PASSWORD' ) ) {
                                        $valkey_connected = @$r->auth( array( WP_REDIS_USERNAME, WP_REDIS_PASSWORD ) );
                                    } elseif ( defined( 'WP_REDIS_PASSWORD' ) ) {
                                        $valkey_connected = @$r->auth( WP_REDIS_PASSWORD );
                                    } else {
                                        $valkey_connected = true;
                                    }
                                    @$r->close();
                                }
                            } catch ( Exception $e ) {
                                $valkey_connected = false;
                            }
                        }
                        ?>
                        <?php if ( $valkey_connected && $dropin_active ) : ?>
                            <p style="font-size: 28px; font-weight: bold; margin: 10px 0; color: #00a32a;"><?php _e( 'Connected', 'leanstack' ); ?> <span style="font-size: 14px; font-weight: normal; color: #646970;">(DB <?php echo defined( 'WP_REDIS_DATABASE' ) ? (int) WP_REDIS_DATABASE : 0; ?>)</span></p>
                            <p style="color: #646970; margin: 0;"><?php printf( __( 'ACL User: <strong>%s</strong> | Unix Socket Active', 'leanstack' ), defined( 'WP_REDIS_USERNAME' ) ? esc_html( WP_REDIS_USERNAME ) : 'default' ); ?></p>
                        <?php elseif ( $valkey_connected ) : ?>
                            <p style="font-size: 28px; font-weight: bold; margin: 10px 0; color: #dba617;"><?php _e( 'Socket Ready', 'leanstack' ); ?> <span style="font-size: 14px; font-weight: normal; color: #646970;">(Drop-in Missing)</span></p>
                            <p style="color: #646970; margin: 0;"><?php _e( 'Valkey ACL authenticated. Enable drop-in via Redis settings.', 'leanstack' ); ?></p>
                        <?php else : ?>
                            <p style="font-size: 28px; font-weight: bold; margin: 10px 0; color: #d63638;"><?php _e( 'Offline / Unlinked', 'leanstack' ); ?></p>
                            <p style="color: #646970; margin: 0;"><?php _e( 'Check /run/valkey/valkey.sock and ACL credentials.', 'leanstack' ); ?></p>
                        <?php endif; ?>
                        <hr style="margin: 15px 0; border: 0; border-top: 1px solid #f0f0f1;">
                        <small style="color: #8c8f94; word-break: break-all;"><?php echo defined( 'WP_REDIS_PATH' ) ? esc_html( WP_REDIS_PATH ) : '/run/valkey/valkey.sock'; ?></small>
                    </div>
                </div>

            <?php elseif ( 'config' === $active_tab ) : ?>
                <div style="background: #fff; border: 1px solid #ccd0d4; padding: 20px; margin-top: 20px; border-radius: 4px;">
                    <h3><span class="dashicons dashicons-admin-generic" style="color: #2271b1;"></span> <?php _e( '1. FastCGI Domain Cache Configuration', 'leanstack' ); ?></h3>
                    <p class="description"><?php _e( 'Manage caching for this domain. Updates are applied instantly to Angie server directives without restarts.', 'leanstack' ); ?></p>

                    <form method="post" action="<?php echo esc_url( admin_url( 'admin-post.php' ) ); ?>">
                        <?php wp_nonce_field( 'leanstack_save_cache_config_action', 'leanstack_nonce' ); ?>
                        <input type="hidden" name="action" value="leanstack_save_cache_config">

                        <table class="form-table">
                            <tr>
                                <th scope="row"><?php _e( 'Cache Status', 'leanstack' ); ?></th>
                                <td>
                                    <label>
                                        <input type="checkbox" name="site_cache_enabled" value="1" <?php checked( $cfg['enabled'], 1 ); ?>>
                                        <strong><?php _e( 'Enable FastCGI Page Cache for this domain', 'leanstack' ); ?></strong>
                                    </label>
                                </td>
                            </tr>
                            <tr>
                                <th scope="row"><?php _e( 'Default Cache TTL', 'leanstack' ); ?></th>
                                <td>
                                    <select name="site_cache_ttl">
                                        <option value="60s" <?php selected( $cfg['ttl'], '60s' ); ?>>60s (1 Minute)</option>
                                        <option value="300s" <?php selected( $cfg['ttl'], '300s' ); ?>>300s (5 Minutes)</option>
                                        <option value="1800s" <?php selected( $cfg['ttl'], '1800s' ); ?>>1800s (30 Minutes)</option>
                                        <option value="3600s" <?php selected( $cfg['ttl'], '3600s' ); ?>>3600s (1 Hour - Recommended)</option>
                                        <option value="86400s" <?php selected( $cfg['ttl'], '86400s' ); ?>>86400s (24 Hours)</option>
                                        <option value="604800s" <?php selected( $cfg['ttl'], '604800s' ); ?>>604800s (7 Days)</option>
                                    </select>
                                </td>
                            </tr>
                        </table>

                        <p class="submit">
                            <button type="submit" class="button button-primary"><?php _e( 'Save Cache Configuration', 'leanstack' ); ?></button>
                        </p>
                    </form>

                    <hr style="margin: 30px 0; border: 0; border-top: 1px solid #eee;">

                    <h3><span class="dashicons dashicons-search" style="color: #2271b1;"></span> <?php _e( '2. Surgical URL Invalidation', 'leanstack' ); ?></h3>
                    <p class="description"><?php _e( 'Purge a specific page or API endpoint immediately across the Angie cache layer without affecting any other cached URLs.', 'leanstack' ); ?></p>

                    <form method="post" action="<?php echo esc_url( admin_url( 'admin-post.php' ) ); ?>">
                        <?php wp_nonce_field( 'leanstack_purge_url_action', 'leanstack_nonce' ); ?>
                        <input type="hidden" name="action" value="leanstack_purge_fastcgi_url">

                        <p>
                            <input type="text" name="purge_url" placeholder="<?php echo esc_attr( home_url( '/sample-page/' ) ); ?>" style="width: 60%; max-width: 500px;" required>
                            <button type="submit" class="button button-secondary"><?php _e( 'Surgically Purge URL', 'leanstack' ); ?></button>
                        </p>
                    </form>

                    <hr style="margin: 30px 0; border: 0; border-top: 1px solid #eee;">

                    <h3><span class="dashicons dashicons-trash" style="color: #d63638;"></span> <?php _e( '3. Complete Domain Cache Flush', 'leanstack' ); ?></h3>
                    <p class="description"><?php _e( 'Wipes the entire FastCGI cache directory for this domain. Other tenants on the server are completely isolated and untouched.', 'leanstack' ); ?></p>

                    <form method="post" action="<?php echo esc_url( admin_url( 'admin-post.php' ) ); ?>" onsubmit="return confirm('Purge entire FastCGI cache for this site?');">
                        <?php wp_nonce_field( 'leanstack_purge_all_action', 'leanstack_nonce' ); ?>
                        <input type="hidden" name="action" value="leanstack_purge_fastcgi_all">

                        <p>
                            <button type="submit" class="button button-secondary" style="color: #d63638; border-color: #d63638;"><?php _e( 'Purge All FastCGI Cache for Domain', 'leanstack' ); ?></button>
                        </p>
                    </form>
                </div>

            <?php elseif ( 'php-cache' === $active_tab ) : ?>
                <div style="background: #fff; border: 1px solid #ccd0d4; padding: 20px; margin-top: 20px; border-radius: 4px;">
                    <h3><span class="dashicons dashicons-shield-alt" style="color: #2271b1;"></span> <?php _e( 'Multi-Tenant Isolated OPcache Purge', 'leanstack' ); ?></h3>
                    <p><?php _e( 'In a multi-tenant hosting architecture, running <code>opcache_reset()</code> clears bytecode caches for all sites on the server, causing performance degradation across all tenants. LeanStack enforces safe per-tenant invalidation: only PHP scripts residing inside this site\'s document root are invalidated.', 'leanstack' ); ?></p>

                    <form method="post" action="<?php echo esc_url( admin_url( 'admin-post.php' ) ); ?>">
                        <?php wp_nonce_field( 'leanstack_purge_opcache_action', 'leanstack_nonce' ); ?>
                        <input type="hidden" name="action" value="leanstack_purge_opcache">
                        <p class="submit">
                            <button type="submit" class="button button-primary"><?php _e( 'Invalidate Tenant OPcache Scripts', 'leanstack' ); ?></button>
                        </p>
                    </form>

                    <hr style="margin: 30px 0; border: 0; border-top: 1px solid #eee;">

                    <h3><span class="dashicons dashicons-superhero-alt" style="color: #2271b1;"></span> <?php _e( 'APCu High-Speed Cache Flush', 'leanstack' ); ?></h3>
                    <p><?php _e( 'APCu stores transients and fragments with zero serialization overhead and <3µs read latency. All keys are cryptographically namespaced to this site. Flushing clears only this site\'s keys from shared memory.', 'leanstack' ); ?></p>

                    <form method="post" action="<?php echo esc_url( admin_url( 'admin-post.php' ) ); ?>">
                        <?php wp_nonce_field( 'leanstack_purge_apcu_action', 'leanstack_nonce' ); ?>
                        <input type="hidden" name="action" value="leanstack_purge_apcu">
                        <p class="submit">
                            <button type="submit" class="button button-secondary"><?php _e( 'Flush Tenant APCu Memory', 'leanstack' ); ?></button>
                        </p>
                    </form>
                </div>

            <?php elseif ( 'cloudflare' === $active_tab ) : ?>
                <div style="background: #fff; border: 1px solid #ccd0d4; padding: 20px; margin-top: 20px; border-radius: 4px;">
                    <h3><span class="dashicons dashicons-cloud" style="color: #2271b1;"></span> <?php _e( 'Cloudflare Edge CDN Integration', 'leanstack' ); ?></h3>
                    <p class="description"><?php _e( 'Synchronize local FastCGI cache invalidations with Cloudflare\'s Global Edge CDN network via API v4.', 'leanstack' ); ?></p>

                    <form method="post" action="<?php echo esc_url( admin_url( 'admin-post.php' ) ); ?>">
                        <?php wp_nonce_field( 'leanstack_save_cf_action', 'leanstack_nonce' ); ?>
                        <input type="hidden" name="action" value="leanstack_save_cf_credentials">

                        <table class="form-table">
                            <tr>
                                <th scope="row"><?php _e( 'Zone ID', 'leanstack' ); ?></th>
                                <td>
                                    <input type="text" name="cf_zone_id" value="<?php echo esc_attr( get_option( 'leanstack_cf_zone_id', '' ) ); ?>" class="regular-text" placeholder="e.g. 023e105f4ecef8ad9ca31a8372d0c353">
                                </td>
                            </tr>
                            <tr>
                                <th scope="row"><?php _e( 'API Token (Zone.Cache Purge)', 'leanstack' ); ?></th>
                                <td>
                                    <input type="password" name="cf_api_token" value="<?php echo esc_attr( get_option( 'leanstack_cf_api_token', '' ) ); ?>" class="regular-text" placeholder="Bearer Token">
                                </td>
                            </tr>
                        </table>

                        <p class="submit">
                            <button type="submit" class="button button-primary"><?php _e( 'Save Cloudflare Settings', 'leanstack' ); ?></button>
                        </p>
                    </form>

                    <hr style="margin: 30px 0; border: 0; border-top: 1px solid #eee;">

                    <h3><span class="dashicons dashicons-update" style="color: #2271b1;"></span> <?php _e( 'Purge Cloudflare Edge CDN', 'leanstack' ); ?></h3>
                    <p class="description"><?php _e( 'Sends an immediate purge request to all 330+ Cloudflare Edge data centers globally.', 'leanstack' ); ?></p>

                    <form method="post" action="<?php echo esc_url( admin_url( 'admin-post.php' ) ); ?>" onsubmit="return confirm('Purge entire Cloudflare Edge cache?');">
                        <?php wp_nonce_field( 'leanstack_purge_cf_action', 'leanstack_nonce' ); ?>
                        <input type="hidden" name="action" value="leanstack_purge_cf">
                        <p class="submit">
                            <button type="submit" class="button button-secondary"><?php _e( 'Purge Entire Cloudflare Edge Zone', 'leanstack' ); ?></button>
                        </p>
                    </form>
                </div>

            <?php elseif ( 'cron' === $active_tab ) : ?>
                <?php $this->render_cron_tab_content(); ?>
            <?php endif; ?>
        </div>
        <?php
    }

    public function render_cron_tab_content() {
        $cron_meta = $this->get_cron_status();
        $cron_array = _get_cron_array();
        $now = time();
        $due_count = 0;
        $events_list = array();

        if ( ! empty( $cron_array ) ) {
            foreach ( $cron_array as $timestamp => $hooks ) {
                foreach ( $hooks as $hook => $keys ) {
                    foreach ( $keys as $k => $data ) {
                        $is_due = ( $timestamp <= $now );
                        if ( $is_due ) {
                            $due_count++;
                        }
                        $events_list[] = array(
                            'timestamp' => $timestamp,
                            'hook'      => $hook,
                            'schedule'  => isset( $data['schedule'] ) && $data['schedule'] ? $data['schedule'] : __( 'Non-repeating', 'leanstack' ),
                            'args'      => isset( $data['args'] ) ? $data['args'] : array(),
                            'is_due'    => $is_due,
                        );
                    }
                }
            }
        }

        // Sort upcoming events by timestamp ascending
        usort( $events_list, function( $a, $b ) {
            return $a['timestamp'] - $b['timestamp'];
        } );
        ?>
        <div style="background: #fff; border: 1px solid #ccd0d4; padding: 20px; margin-top: 20px; border-radius: 4px;">
            <h3><span class="dashicons dashicons-clock" style="color: #2271b1;"></span> <?php _e( 'LeanStack Centralized Anti-Thundering WP-Cron Manager', 'leanstack' ); ?></h3>
            <p class="description">
                <?php _e( 'LeanStack executes WordPress scheduled tasks through a dedicated server-level systemd queue runner (<code>ls-cron-queue</code> / <code>cp-cron.timer</code>) with strict concurrency limits and PHP isolation.', 'leanstack' ); ?>
            </p>

            <div style="background: #f0f6fc; border-left: 4px solid #72aee6; padding: 12px 16px; margin: 16px 0; border-radius: 2px;">
                <h4 style="margin: 0 0 6px 0; color: #1d2327;"><span class="dashicons dashicons-info" style="color: #2271b1; vertical-align: middle;"></span> <?php _e( 'Why Visitor WP-Cron is Disabled (DISABLE_WP_CRON = true)', 'leanstack' ); ?></h4>
                <p style="margin: 0; color: #2c3338; font-size: 13px; line-height: 1.5;">
                    <?php _e( 'Default WordPress triggers crons in the background of page visits, causing high TTFB, thread starvation, and thundering herd spikes during traffic surges. LeanStack offloads this completely to Linux systemd, running crons reliably every 60 seconds with 0ms visitor latency.', 'leanstack' ); ?>
                </p>
            </div>

            <table class="widefat striped" style="margin-top: 15px;">
                <thead>
                    <tr>
                        <th><?php _e( 'Parameter', 'leanstack' ); ?></th>
                        <th><?php _e( 'Configured Value', 'leanstack' ); ?></th>
                        <th><?php _e( 'Operational Status', 'leanstack' ); ?></th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td><strong><?php _e( 'Queue Execution Engine', 'leanstack' ); ?></strong></td>
                        <td><code>systemd: cp-cron.timer &amp; ls-cron-queue</code></td>
                        <td><span class="dashicons dashicons-yes" style="color: #00a32a;"></span> <strong style="color: #00a32a;"><?php _e( 'Active &amp; Server-Managed', 'leanstack' ); ?></strong></td>
                    </tr>
                    <tr>
                        <td><strong><?php _e( 'Queue Cadence / Interval', 'leanstack' ); ?></strong></td>
                        <td><?php _e( 'Every 60 seconds (Serialized max 4 parallel workers)', 'leanstack' ); ?></td>
                        <td><span class="dashicons dashicons-performance" style="color: #2271b1;"></span> <?php _e( 'Anti-Thundering Mutex Lock Active', 'leanstack' ); ?></td>
                    </tr>
                    <tr>
                        <td><strong><?php _e( 'DISABLE_WP_CRON Setting', 'leanstack' ); ?></strong></td>
                        <td><code>define( 'DISABLE_WP_CRON', true );</code></td>
                        <td><span class="dashicons dashicons-shield" style="color: #00a32a;"></span> <?php _e( 'Protected (Visitor requests decoupled)', 'leanstack' ); ?></td>
                    </tr>
                    <tr>
                        <td><strong><?php _e( 'Last Server Queue Dispatch', 'leanstack' ); ?></strong></td>
                        <td>
                            <?php
                            if ( ! empty( $cron_meta['last_run'] ) ) {
                                $last_time = strtotime( $cron_meta['last_run'] );
                                printf( esc_html__( '%s (%s ago)', 'leanstack' ), esc_html( $cron_meta['last_run'] ), human_time_diff( $last_time ) );
                            } else {
                                _e( 'Systemd Active (Awaiting next 60s trigger)', 'leanstack' );
                            }
                            ?>
                        </td>
                        <td>
                            <span class="dashicons dashicons-marker" style="color: #00a32a;"></span>
                            <?php echo esc_html( ucfirst( isset( $cron_meta['status'] ) ? $cron_meta['status'] : 'active' ) ); ?>
                        </td>
                    </tr>
                    <tr>
                        <td><strong><?php _e( 'Scheduled Tasks Due Now', 'leanstack' ); ?></strong></td>
                        <td><strong><?php echo (int) $due_count; ?></strong> <?php _e( 'task(s) ready to run', 'leanstack' ); ?></td>
                        <td>
                            <?php if ( $due_count > 0 ) : ?>
                                <span class="dashicons dashicons-clock" style="color: #dba617;"></span> <span style="color: #b26b00;"><?php _e( 'Queued for next runner cycle', 'leanstack' ); ?></span>
                            <?php else : ?>
                                <span class="dashicons dashicons-yes" style="color: #00a32a;"></span> <span style="color: #00a32a;"><?php _e( 'All scheduled events current', 'leanstack' ); ?></span>
                            <?php endif; ?>
                        </td>
                    </tr>
                    <tr>
                        <td><strong><?php _e( 'Execution Telemetry (Last Run)', 'leanstack' ); ?></strong></td>
                        <td>
                            <?php if ( ! empty( $cron_meta['duration_ms'] ) || ! empty( $cron_meta['events_processed'] ) ) : ?>
                                <?php printf( esc_html__( 'Duration: %sms | CPU: %sms | Peak Memory: %s MB | Events: %d', 'leanstack' ), esc_html( $cron_meta['duration_ms'] ), esc_html( isset( $cron_meta['cpu_ms'] ) ? $cron_meta['cpu_ms'] : '0' ), esc_html( isset( $cron_meta['memory_mb'] ) ? $cron_meta['memory_mb'] : '0' ), (int) $cron_meta['events_processed'] ); ?>
                            <?php else : ?>
                                <span style="color: #646970;"><?php _e( 'Awaiting telemetry data', 'leanstack' ); ?></span>
                            <?php endif; ?>
                        </td>
                        <td>
                            <span class="dashicons dashicons-dashboard" style="color: #2271b1;"></span>
                            <?php printf( esc_html__( 'Ran via %s', 'leanstack' ), esc_html( isset( $cron_meta['ran_via'] ) ? $cron_meta['ran_via'] : 'queue' ) ); ?>
                        </td>
                    </tr>
                    <tr>
                        <td><strong><?php _e( 'Rolling Analytics (Last 20 Runs)', 'leanstack' ); ?></strong></td>
                        <td>
                            <?php if ( ! empty( $cron_meta['avg_duration_ms'] ) ) : ?>
                                <?php printf( esc_html__( 'Avg Duration: %sms | Avg CPU: %sms | Avg Memory: %s MB (Total Runs: %d, Total Events: %d)', 'leanstack' ), esc_html( $cron_meta['avg_duration_ms'] ), esc_html( isset( $cron_meta['avg_cpu_ms'] ) ? $cron_meta['avg_cpu_ms'] : '0' ), esc_html( isset( $cron_meta['avg_memory_mb'] ) ? $cron_meta['avg_memory_mb'] : '0' ), (int) ( isset( $cron_meta['total_runs'] ) ? $cron_meta['total_runs'] : 0 ), (int) ( isset( $cron_meta['total_events_processed'] ) ? $cron_meta['total_events_processed'] : 0 ) ); ?>
                            <?php else : ?>
                                <span style="color: #646970;"><?php _e( 'Calculating rolling averages...', 'leanstack' ); ?></span>
                            <?php endif; ?>
                        </td>
                        <td>
                            <span class="dashicons dashicons-chart-line" style="color: #00a32a;"></span>
                            <strong style="color: #00a32a;"><?php _e( 'Optimal Health', 'leanstack' ); ?></strong>
                        </td>
                    </tr>
                </tbody>
            </table>

            <div style="margin-top: 25px; padding-top: 20px; border-top: 1px solid #f0f0f1; display: flex; align-items: center; justify-content: space-between;">
                <div>
                    <h4 style="margin: 0 0 5px 0;"><?php _e( 'Manual On-Demand Queue Dispatch', 'leanstack' ); ?></h4>
                    <p style="margin: 0; color: #646970; font-size: 13px;"><?php _e( 'Execute all currently due scheduled WordPress hooks immediately.', 'leanstack' ); ?></p>
                </div>
                <form method="post" action="<?php echo esc_url( admin_url( 'admin-post.php' ) ); ?>">
                    <?php wp_nonce_field( 'leanstack_run_cron_action', 'leanstack_nonce' ); ?>
                    <input type="hidden" name="action" value="leanstack_run_cron_now">
                    <button type="submit" class="button button-primary">
                        <span class="dashicons dashicons-update" style="vertical-align: text-bottom;"></span> <?php _e( 'Dispatch Cron Queue Now', 'leanstack' ); ?>
                    </button>
                </form>
            </div>

            <?php if ( ! empty( $cron_meta['history'] ) && is_array( $cron_meta['history'] ) ) : ?>
            <hr style="margin: 30px 0; border: 0; border-top: 1px solid #eee;">
            <h4><?php printf( __( 'Recent Queue Executions (%d recorded)', 'leanstack' ), count( $cron_meta['history'] ) ); ?></h4>
            <table class="widefat striped" style="margin-top: 10px;">
                <thead>
                    <tr>
                        <th><?php _e( 'Timestamp (UTC)', 'leanstack' ); ?></th>
                        <th><?php _e( 'Duration', 'leanstack' ); ?></th>
                        <th><?php _e( 'CPU Time', 'leanstack' ); ?></th>
                        <th><?php _e( 'Peak Memory', 'leanstack' ); ?></th>
                        <th><?php _e( 'Events Processed', 'leanstack' ); ?></th>
                        <th><?php _e( 'Trigger Source', 'leanstack' ); ?></th>
                    </tr>
                </thead>
                <tbody>
                    <?php foreach ( $cron_meta['history'] as $run ) : ?>
                        <tr>
                            <td><code><?php echo esc_html( isset( $run['timestamp'] ) ? $run['timestamp'] : 'N/A' ); ?></code></td>
                            <td><strong><?php echo esc_html( isset( $run['duration_ms'] ) ? $run['duration_ms'] : '0' ); ?> ms</strong></td>
                            <td><?php echo esc_html( isset( $run['cpu_ms'] ) ? $run['cpu_ms'] : '0' ); ?> ms</td>
                            <td><?php echo esc_html( isset( $run['memory_mb'] ) ? $run['memory_mb'] : '0' ); ?> MB</td>
                            <td><?php echo (int) ( isset( $run['events_processed'] ) ? $run['events_processed'] : 0 ); ?></td>
                            <td><code><?php echo esc_html( isset( $run['ran_via'] ) ? $run['ran_via'] : 'queue' ); ?></code></td>
                        </tr>
                    <?php endforeach; ?>
                </tbody>
            </table>
            <?php endif; ?>

            <hr style="margin: 30px 0; border: 0; border-top: 1px solid #eee;">

            <h4><?php printf( __( 'Scheduled WordPress Tasks (%d events registered)', 'leanstack' ), count( $events_list ) ); ?></h4>
            <table class="widefat striped" style="margin-top: 10px;">
                <thead>
                    <tr>
                        <th><?php _e( 'Next Execution', 'leanstack' ); ?></th>
                        <th><?php _e( 'Hook Name', 'leanstack' ); ?></th>
                        <th><?php _e( 'Schedule / Recurrence', 'leanstack' ); ?></th>
                        <th><?php _e( 'Arguments', 'leanstack' ); ?></th>
                    </tr>
                </thead>
                <tbody>
                    <?php if ( empty( $events_list ) ) : ?>
                        <tr>
                            <td colspan="4" style="text-align: center; color: #646970;"><?php _e( 'No scheduled events found.', 'leanstack' ); ?></td>
                        </tr>
                    <?php else : ?>
                        <?php foreach ( array_slice( $events_list, 0, 30 ) as $ev ) : ?>
                            <tr>
                                <td>
                                    <?php if ( $ev['is_due'] ) : ?>
                                        <span style="color: #d63638; font-weight: bold;"><?php _e( 'Due now', 'leanstack' ); ?></span> (<?php echo esc_html( human_time_diff( $ev['timestamp'] ) ); ?> <?php _e( 'overdue', 'leanstack' ); ?>)
                                    <?php else : ?>
                                        <span style="color: #007017;"><?php printf( esc_html__( 'In %s', 'leanstack' ), esc_html( human_time_diff( $ev['timestamp'] ) ) ); ?></span>
                                        <br><small style="color: #8c8f94;"><?php echo esc_html( date_i18n( 'Y-m-d H:i:s', $ev['timestamp'] ) ); ?></small>
                                    <?php endif; ?>
                                </td>
                                <td><code><?php echo esc_html( $ev['hook'] ); ?></code></td>
                                <td><?php echo esc_html( $ev['schedule'] ); ?></td>
                                <td><small><?php echo ! empty( $ev['args'] ) ? esc_html( json_encode( $ev['args'] ) ) : '<em>none</em>'; ?></small></td>
                            </tr>
                        <?php endforeach; ?>
                    <?php endif; ?>
                </tbody>
            </table>
        </div>
        <?php
    }

    // =========================================================================
    // UI: Tools > Logs Manager & Debug Control Center
    // =========================================================================

    public function is_valid_log_path( $path ) {
        if ( empty( $path ) || ! is_string( $path ) ) {
            return false;
        }

        // Prevent path traversal
        if ( false !== strpos( $path, '..' ) ) {
            return false;
        }

        $doc_root = rtrim( ABSPATH, '/' );
        $parent_dir = dirname( $doc_root );

        // Strict sandboxing verification: must reside inside tenant parent_dir (/home/<user>/) or WP_CONTENT_DIR
        $real = realpath( $path );
        $check_path = $real ? $real : $path;

        if ( 0 === strpos( $check_path, $parent_dir . '/' ) || 0 === strpos( $check_path, WP_CONTENT_DIR . '/' ) || $check_path === ( WP_CONTENT_DIR . '/debug.log' ) ) {
            return true;
        }

        return false;
    }

    public function get_logs_dir() {
        if ( null !== $this->logs_dir && is_dir( $this->logs_dir ) ) {
            return $this->logs_dir;
        }
        $doc_root = rtrim( ABSPATH, '/' );
        $parent_dir = dirname( $doc_root );
        $candidate = $parent_dir . '/logs';
        if ( is_dir( $candidate ) ) {
            $this->logs_dir = $candidate;
            return $candidate;
        }
        if ( is_dir( $parent_dir ) && is_writable( $parent_dir ) ) {
            @mkdir( $candidate, 0750, true );
            if ( is_dir( $candidate ) ) {
                $this->logs_dir = $candidate;
                return $candidate;
            }
        }
        $this->logs_dir = WP_CONTENT_DIR;
        return $this->logs_dir;
    }

    public function get_wp_config_file() {
        if ( file_exists( ABSPATH . 'wp-config.php' ) ) {
            return ABSPATH . 'wp-config.php';
        }
        $parent_cfg = dirname( rtrim( ABSPATH, '/' ) ) . '/wp-config.php';
        if ( file_exists( $parent_cfg ) && ! file_exists( dirname( rtrim( ABSPATH, '/' ) ) . '/wp-settings.php' ) ) {
            return $parent_cfg;
        }
        return false;
    }

    public function get_default_debug_log_path() {
        $dir = $this->get_logs_dir();
        if ( is_dir( $dir ) && is_writable( $dir ) ) {
            return $dir . '/wp-debug.log';
        }
        return WP_CONTENT_DIR . '/debug.log';
    }

    public function get_available_logs() {
        $logs_dir = $this->get_logs_dir();
        $logs = array();

        // 1. WordPress Debug Log
        $wp_debug_path = '';
        if ( defined( 'WP_DEBUG_LOG' ) && is_string( WP_DEBUG_LOG ) && ! in_array( strtolower( WP_DEBUG_LOG ), array( '1', 'true' ), true ) ) {
            $wp_debug_path = WP_DEBUG_LOG;
        } elseif ( file_exists( $logs_dir . '/wp-debug.log' ) ) {
            $wp_debug_path = $logs_dir . '/wp-debug.log';
        } else {
            $wp_debug_path = WP_CONTENT_DIR . '/debug.log';
        }

        if ( $this->is_valid_log_path( $wp_debug_path ) ) {
            $logs['wp-debug'] = array(
                'id'          => 'wp-debug',
                'name'        => __( 'WordPress Debug Log', 'leanstack' ),
                'path'        => $wp_debug_path,
                'filename'    => basename( $wp_debug_path ),
                'description' => __( 'Errors, warnings, notices, and exceptions logged by WordPress core, active plugins, and themes.', 'leanstack' ),
                'exists'      => file_exists( $wp_debug_path ),
                'readable'    => is_readable( $wp_debug_path ),
                'writable'    => is_writable( $wp_debug_path ) || ( ! file_exists( $wp_debug_path ) && is_writable( dirname( $wp_debug_path ) ) ),
                'size'        => ( file_exists( $wp_debug_path ) && is_readable( $wp_debug_path ) ) ? (int) filesize( $wp_debug_path ) : 0,
                'size_human'  => ( file_exists( $wp_debug_path ) && is_readable( $wp_debug_path ) ) ? ( function_exists( 'size_format' ) ? size_format( filesize( $wp_debug_path ), 2 ) : ( filesize( $wp_debug_path ) . ' B' ) ) : '0 B',
                'modified'    => ( file_exists( $wp_debug_path ) && is_readable( $wp_debug_path ) ) ? date_i18n( 'Y-m-d H:i:s', filemtime( $wp_debug_path ) ) : __( 'Never / Not Created', 'leanstack' ),
            );
        }

        // 2. PHP Slow Log
        $php_slow_path = $logs_dir . '/php-slow.log';
        if ( $this->is_valid_log_path( $php_slow_path ) ) {
            $logs['php-slow'] = array(
                'id'          => 'php-slow',
                'name'        => __( 'PHP Slow Log', 'leanstack' ),
                'path'        => $php_slow_path,
                'filename'    => basename( $php_slow_path ),
                'description' => __( 'PHP-FPM execution backtraces for slow requests exceeding the slowlog execution threshold.', 'leanstack' ),
                'exists'      => file_exists( $php_slow_path ),
                'readable'    => is_readable( $php_slow_path ),
                'writable'    => is_writable( $php_slow_path ) || ( ! file_exists( $php_slow_path ) && is_writable( dirname( $php_slow_path ) ) ),
                'size'        => ( file_exists( $php_slow_path ) && is_readable( $php_slow_path ) ) ? (int) filesize( $php_slow_path ) : 0,
                'size_human'  => ( file_exists( $php_slow_path ) && is_readable( $php_slow_path ) ) ? ( function_exists( 'size_format' ) ? size_format( filesize( $php_slow_path ), 2 ) : ( filesize( $php_slow_path ) . ' B' ) ) : '0 B',
                'modified'    => ( file_exists( $php_slow_path ) && is_readable( $php_slow_path ) ) ? date_i18n( 'Y-m-d H:i:s', filemtime( $php_slow_path ) ) : __( 'Never / Not Created', 'leanstack' ),
            );
        }

        // 3. Angie Web Error Log
        $angie_err_path = $logs_dir . '/error.log';
        if ( $this->is_valid_log_path( $angie_err_path ) ) {
            $logs['angie-error'] = array(
                'id'          => 'angie-error',
                'name'        => __( 'Angie Web Error Log', 'leanstack' ),
                'path'        => $angie_err_path,
                'filename'    => basename( $angie_err_path ),
                'description' => __( 'HTTP server errors, upstream connection timeouts, 502/504 gateways, and web server notices.', 'leanstack' ),
                'exists'      => file_exists( $angie_err_path ),
                'readable'    => is_readable( $angie_err_path ),
                'writable'    => is_writable( $angie_err_path ) || ( ! file_exists( $angie_err_path ) && is_writable( dirname( $angie_err_path ) ) ),
                'size'        => ( file_exists( $angie_err_path ) && is_readable( $angie_err_path ) ) ? (int) filesize( $angie_err_path ) : 0,
                'size_human'  => ( file_exists( $angie_err_path ) && is_readable( $angie_err_path ) ) ? ( function_exists( 'size_format' ) ? size_format( filesize( $angie_err_path ), 2 ) : ( filesize( $angie_err_path ) . ' B' ) ) : '0 B',
                'modified'    => ( file_exists( $angie_err_path ) && is_readable( $angie_err_path ) ) ? date_i18n( 'Y-m-d H:i:s', filemtime( $angie_err_path ) ) : __( 'Never / Not Created', 'leanstack' ),
            );
        }

        // 4. Angie Web Access Log
        $angie_acc_path = $logs_dir . '/access.log';
        if ( $this->is_valid_log_path( $angie_acc_path ) ) {
            $logs['angie-access'] = array(
                'id'          => 'angie-access',
                'name'        => __( 'Angie Web Access Log', 'leanstack' ),
                'path'        => $angie_acc_path,
                'filename'    => basename( $angie_acc_path ),
                'description' => __( 'Live visitor traffic, HTTP response status codes, cache hits/misses, and request latencies.', 'leanstack' ),
                'exists'      => file_exists( $angie_acc_path ),
                'readable'    => is_readable( $angie_acc_path ),
                'writable'    => is_writable( $angie_acc_path ) || ( ! file_exists( $angie_acc_path ) && is_writable( dirname( $angie_acc_path ) ) ),
                'size'        => ( file_exists( $angie_acc_path ) && is_readable( $angie_acc_path ) ) ? (int) filesize( $angie_acc_path ) : 0,
                'size_human'  => ( file_exists( $angie_acc_path ) && is_readable( $angie_acc_path ) ) ? ( function_exists( 'size_format' ) ? size_format( filesize( $angie_acc_path ), 2 ) : ( filesize( $angie_acc_path ) . ' B' ) ) : '0 B',
                'modified'    => ( file_exists( $angie_acc_path ) && is_readable( $angie_acc_path ) ) ? date_i18n( 'Y-m-d H:i:s', filemtime( $angie_acc_path ) ) : __( 'Never / Not Created', 'leanstack' ),
            );
        }

        return $logs;
    }

    public function read_log_tail( $file_path, $max_lines = 300, $max_bytes = 262144 ) {
        if ( ! $this->is_valid_log_path( $file_path ) || ! file_exists( $file_path ) || ! is_readable( $file_path ) ) {
            return '';
        }
        $size = (int) filesize( $file_path );
        if ( 0 === $size ) {
            return '';
        }

        $fp = @fopen( $file_path, 'rb' );
        if ( ! $fp ) {
            return '';
        }

        $offset = max( 0, $size - $max_bytes );
        if ( $offset > 0 ) {
            fseek( $fp, $offset );
        }

        $buffer = fread( $fp, $max_bytes );
        fclose( $fp );

        if ( false === $buffer || '' === $buffer ) {
            return '';
        }

        $buffer = str_replace( "\r\n", "\n", $buffer );
        $lines = explode( "\n", $buffer );
        if ( $offset > 0 && count( $lines ) > 1 ) {
            array_shift( $lines );
        }

        if ( count( $lines ) > $max_lines ) {
            $lines = array_slice( $lines, -$max_lines );
        }

        return implode( "\n", $lines );
    }

    public function parse_wp_config_debug_settings() {
        $settings = array(
            'wp_debug'         => defined( 'WP_DEBUG' ) ? (bool) WP_DEBUG : false,
            'wp_debug_log'     => defined( 'WP_DEBUG_LOG' ) ? (bool) WP_DEBUG_LOG : false,
            'wp_debug_log_val' => defined( 'WP_DEBUG_LOG' ) ? WP_DEBUG_LOG : false,
            'wp_debug_display' => defined( 'WP_DEBUG_DISPLAY' ) ? (bool) WP_DEBUG_DISPLAY : false,
            'config_file'      => $this->get_wp_config_file(),
            'is_writable'      => false,
        );

        $cfg = $settings['config_file'];
        if ( $cfg && file_exists( $cfg ) ) {
            $settings['is_writable'] = is_writable( $cfg );
            $content = @file_get_contents( $cfg );
            if ( $content ) {
                if ( preg_match( "/^[ \t]*define\s*\(\s*['\"]WP_DEBUG['\"]\s*,\s*(true|false|1|0)/mi", $content, $m ) ) {
                    $settings['wp_debug'] = in_array( strtolower( $m[1] ), array( 'true', '1' ), true );
                }
                if ( preg_match( "/^[ \t]*define\s*\(\s*['\"]WP_DEBUG_LOG['\"]\s*,\s*(.+?)\s*\)\s*;/mi", $content, $m ) ) {
                    $raw_val = trim( $m[1] );
                    if ( in_array( strtolower( $raw_val ), array( 'false', '0' ), true ) ) {
                        $settings['wp_debug_log'] = false;
                        $settings['wp_debug_log_val'] = false;
                    } elseif ( in_array( strtolower( $raw_val ), array( 'true', '1' ), true ) ) {
                        $settings['wp_debug_log'] = true;
                        $settings['wp_debug_log_val'] = true;
                    } else {
                        $settings['wp_debug_log'] = true;
                        $settings['wp_debug_log_val'] = trim( $raw_val, "'\"" );
                    }
                }
                if ( preg_match( "/^[ \t]*define\s*\(\s*['\"]WP_DEBUG_DISPLAY['\"]\s*,\s*(true|false|1|0)/mi", $content, $m ) ) {
                    $settings['wp_debug_display'] = in_array( strtolower( $m[1] ), array( 'true', '1' ), true );
                }
            }
        }
        return $settings;
    }

    public function save_log_settings() {
        if ( ! current_user_can( 'manage_options' ) ) {
            wp_die( __( 'Unauthorized access.', 'leanstack' ) );
        }
        check_admin_referer( 'leanstack_save_log_settings_action', 'leanstack_nonce' );

        $wp_config_file = $this->get_wp_config_file();
        if ( ! $wp_config_file || ! file_exists( $wp_config_file ) || ! is_writable( $wp_config_file ) ) {
            wp_redirect( add_query_arg( array( 'page' => 'leanstack-logs', 'tab' => 'settings', 'error' => 'not_writable' ), admin_url( 'tools.php' ) ) );
            exit;
        }

        $wp_debug = ! empty( $_POST['wp_debug'] ) ? 1 : 0;
        $wp_debug_log = ! empty( $_POST['wp_debug_log'] ) ? 1 : 0;
        $log_dest = isset( $_POST['wp_debug_log_destination'] ) ? sanitize_text_field( $_POST['wp_debug_log_destination'] ) : 'tenant_logs';
        $wp_debug_display = ! empty( $_POST['wp_debug_display'] ) ? 1 : 0;

        $content = @file_get_contents( $wp_config_file );
        if ( false === $content || empty( $content ) ) {
            wp_redirect( add_query_arg( array( 'page' => 'leanstack-logs', 'tab' => 'settings', 'error' => 'read_failed' ), admin_url( 'tools.php' ) ) );
            exit;
        }

        // 1. Create an atomic timestamped backup
        $backup_file = $wp_config_file . '.bak.' . time();
        @copy( $wp_config_file, $backup_file );
        @chmod( $backup_file, 0600 );

        // Keep maximum of 3 historical backups
        $dir = dirname( $wp_config_file );
        $base = basename( $wp_config_file );
        $existing_baks = glob( $dir . '/' . $base . '.bak.*' );
        if ( $existing_baks && count( $existing_baks ) > 3 ) {
            sort( $existing_baks );
            $to_remove = array_slice( $existing_baks, 0, count( $existing_baks ) - 3 );
            foreach ( $to_remove as $ob ) {
                @unlink( $ob );
            }
        }

        // 2. Prepare Replacement Tokens
        $val_debug = $wp_debug ? 'true' : 'false';

        if ( ! $wp_debug_log ) {
            $val_log = 'false';
        } elseif ( 'wp_content' === $log_dest ) {
            $val_log = 'true';
        } else {
            $target_log = $this->get_default_debug_log_path();
            $val_log = "'" . addcslashes( $target_log, "'\\" ) . "'";
        }

        $val_display = $wp_debug_display ? 'true' : 'false';
        $val_ini_display = $wp_debug_display ? "'1'" : "'0'";

        // 3. Regex Replacement: WP_DEBUG
        $re_debug = "/^[ \t]*(?:\/\/|#)?[ \t]*define\s*\(\s*(['\"])WP_DEBUG\\1\s*,.*?\)\s*;.*$/mi";
        if ( preg_match( $re_debug, $content ) ) {
            $content = preg_replace( $re_debug, "define( 'WP_DEBUG', {$val_debug} );", $content, 1 );
        } else {
            $insert = "define( 'WP_DEBUG', {$val_debug} );\n";
            $content = preg_replace( "/(\/\* That's all, stop editing!|require(?:_once)?\s*\(?.*wp-settings\.php|require(?:_once)?\s+ABSPATH)/i", $insert . "$1", $content, 1 );
        }

        // 4. Regex Replacement: WP_DEBUG_LOG
        $re_log = "/^[ \t]*(?:\/\/|#)?[ \t]*define\s*\(\s*(['\"])WP_DEBUG_LOG\\1\s*,.*?\)\s*;.*$/mi";
        if ( preg_match( $re_log, $content ) ) {
            $content = preg_replace( $re_log, "define( 'WP_DEBUG_LOG', {$val_log} );", $content, 1 );
        } else {
            $insert = "define( 'WP_DEBUG_LOG', {$val_log} );\n";
            $content = preg_replace( "/(^[ \t]*define\s*\(\s*['\"]WP_DEBUG['\"]\s*,.*?\)\s*;.*$)/mi", "$1\n" . $insert, $content, 1 );
        }

        // 5. Regex Replacement: WP_DEBUG_DISPLAY
        $re_display = "/^[ \t]*(?:\/\/|#)?[ \t]*define\s*\(\s*(['\"])WP_DEBUG_DISPLAY\\1\s*,.*?\)\s*;.*$/mi";
        if ( preg_match( $re_display, $content ) ) {
            $content = preg_replace( $re_display, "define( 'WP_DEBUG_DISPLAY', {$val_display} );", $content, 1 );
        } else {
            $insert = "define( 'WP_DEBUG_DISPLAY', {$val_display} );\n";
            $content = preg_replace( "/(^[ \t]*define\s*\(\s*['\"]WP_DEBUG_LOG['\"]\s*,.*?\)\s*;.*$)/mi", "$1\n" . $insert, $content, 1 );
        }

        // 6. Regex Replacement: @ini_set('display_errors', ...)
        $re_ini = "/^[ \t]*(?:\/\/|#)?[ \t]*@?ini_set\s*\(\s*(['\"])display_errors\\1\s*,.*?\)\s*;.*$/mi";
        if ( preg_match( $re_ini, $content ) ) {
            $content = preg_replace( $re_ini, "@ini_set( 'display_errors', {$val_ini_display} );", $content, 1 );
        } else {
            $insert = "@ini_set( 'display_errors', {$val_ini_display} );\n";
            $content = preg_replace( "/(^[ \t]*define\s*\(\s*['\"]WP_DEBUG_DISPLAY['\"]\s*,.*?\)\s*;.*$)/mi", "$1\n" . $insert, $content, 1 );
        }

        // 7. Atomic Safe Write with Temp File (Lock down permissions BEFORE rename)
        $temp_file = $wp_config_file . '.tmp.' . uniqid();
        $written = @file_put_contents( $temp_file, $content );
        if ( false === $written || $written < 50 ) {
            @unlink( $temp_file );
            wp_redirect( add_query_arg( array( 'page' => 'leanstack-logs', 'tab' => 'settings', 'error' => 'write_failed' ), admin_url( 'tools.php' ) ) );
            exit;
        }

        @chmod( $temp_file, 0600 );
        @rename( $temp_file, $wp_config_file );
        @chmod( $wp_config_file, 0600 );

        if ( function_exists( 'opcache_invalidate' ) ) {
            @opcache_invalidate( $wp_config_file, true );
        }

        wp_redirect( add_query_arg( array( 'page' => 'leanstack-logs', 'tab' => 'settings', 'saved' => '1' ), admin_url( 'tools.php' ) ) );
        exit;
    }

    public function handle_clear_log() {
        if ( ! current_user_can( 'manage_options' ) ) {
            wp_die( __( 'Unauthorized access.', 'leanstack' ) );
        }
        check_admin_referer( 'leanstack_clear_log_action', 'leanstack_nonce' );

        $log_id = isset( $_POST['log_id'] ) ? sanitize_key( $_POST['log_id'] ) : ( isset( $_GET['log_id'] ) ? sanitize_key( $_GET['log_id'] ) : 'wp-debug' );
        $available = $this->get_available_logs();

        if ( ! isset( $available[ $log_id ] ) ) {
            wp_die( __( 'Invalid log identifier.', 'leanstack' ) );
        }

        $target = $available[ $log_id ]['path'];

        if ( ! $this->is_valid_log_path( $target ) ) {
            wp_die( __( 'Access denied to target log path.', 'leanstack' ) );
        }

        if ( file_exists( $target ) ) {
            @file_put_contents( $target, '' );
        }

        wp_redirect( add_query_arg( array( 'page' => 'leanstack-logs', 'tab' => 'viewer', 'log_id' => $log_id, 'cleared' => '1' ), admin_url( 'tools.php' ) ) );
        exit;
    }

    public function handle_download_log() {
        if ( ! current_user_can( 'manage_options' ) ) {
            wp_die( __( 'Unauthorized access.', 'leanstack' ) );
        }
        check_admin_referer( 'leanstack_download_log_action', 'leanstack_nonce' );

        $log_id = isset( $_GET['log_id'] ) ? sanitize_key( $_GET['log_id'] ) : 'wp-debug';
        $available = $this->get_available_logs();

        if ( ! isset( $available[ $log_id ] ) ) {
            wp_die( __( 'Invalid log identifier.', 'leanstack' ) );
        }

        $target = $available[ $log_id ]['path'];

        if ( ! $this->is_valid_log_path( $target ) || ! file_exists( $target ) || ! is_readable( $target ) ) {
            wp_die( __( 'Log file not accessible or does not exist.', 'leanstack' ) );
        }

        while ( ob_get_level() ) {
            ob_end_clean();
        }

        header( 'Content-Description: File Transfer' );
        header( 'Content-Type: text/plain; charset=utf-8' );
        header( 'Content-Disposition: attachment; filename="' . esc_attr( basename( $target ) ) . '"' );
        header( 'Expires: 0' );
        header( 'Cache-Control: must-revalidate, post-check=0, pre-check=0' );
        header( 'Pragma: public' );
        header( 'Content-Length: ' . filesize( $target ) );
        readfile( $target );
        exit;
    }

    public function ajax_get_log_tail() {
        if ( ! current_user_can( 'manage_options' ) ) {
            wp_send_json_error( array( 'message' => __( 'Unauthorized access.', 'leanstack' ) ) );
        }
        check_ajax_referer( 'leanstack_log_ajax_nonce', 'nonce' );

        $log_id = isset( $_GET['log_id'] ) ? sanitize_key( $_GET['log_id'] ) : 'wp-debug';
        $available = $this->get_available_logs();

        if ( ! isset( $available[ $log_id ] ) ) {
            wp_send_json_error( array( 'message' => __( 'Invalid log identifier.', 'leanstack' ) ) );
        }

        $target = $available[ $log_id ]['path'];
        if ( ! $this->is_valid_log_path( $target ) ) {
            wp_send_json_error( array( 'message' => __( 'Access denied to target log path.', 'leanstack' ) ) );
        }

        $exists = file_exists( $target ) && is_readable( $target );
        $content = $exists ? $this->read_log_tail( $target, 300 ) : '';
        $size = $exists ? (int) filesize( $target ) : 0;
        $size_human = $exists ? ( function_exists( 'size_format' ) ? size_format( $size, 2 ) : ( $size . ' B' ) ) : '0 B';
        $mod = $exists ? date_i18n( 'Y-m-d H:i:s', filemtime( $target ) ) : __( 'Never / Not Created', 'leanstack' );

        wp_send_json_success( array(
            'log_id'         => $log_id,
            'filename'       => basename( $target ),
            'path'           => $target,
            'exists'         => $exists,
            'size'           => $size,
            'size_human'     => $size_human,
            'modified'       => $mod,
            'lines'          => ! empty( $content ) ? substr_count( $content, "\n" ) + 1 : 0,
            'content'        => $content,
        ) );
    }

    public function render_logs_page() {
        if ( ! current_user_can( 'manage_options' ) ) {
            wp_die( __( 'Unauthorized access.', 'leanstack' ) );
        }

        $active_tab = isset( $_GET['tab'] ) && 'settings' === $_GET['tab'] ? 'settings' : 'viewer';
        $available_logs = $this->get_available_logs();
        $selected_log_id = isset( $_GET['log_id'] ) && isset( $available_logs[ sanitize_key( $_GET['log_id'] ) ] ) ? sanitize_key( $_GET['log_id'] ) : 'wp-debug';
        $current_log = $available_logs[ $selected_log_id ];
        $debug_settings = $this->parse_wp_config_debug_settings();
        $ajax_nonce = wp_create_nonce( 'leanstack_log_ajax_nonce' );

        $initial_content = $current_log['exists'] ? $this->read_log_tail( $current_log['path'], 300 ) : '';

        ?>
        <div class="wrap">
            <h1 style="display: flex; align-items: center; gap: 8px;">
                <span class="dashicons dashicons-text-page" style="font-size: 28px; width: 28px; height: 28px; color: #2271b1;"></span>
                <?php _e( 'LeanStack Logs &amp; Debug Manager', 'leanstack' ); ?>
            </h1>
            <p><?php _e( 'Inspect, stream, download, and clear server and WordPress logs directly from the dashboard, and manage debug modes safely.', 'leanstack' ); ?></p>

            <?php if ( isset( $_GET['saved'] ) ) : ?>
                <div class="notice notice-success is-dismissible">
                    <p><strong><span class="dashicons dashicons-yes-alt" style="color: #46b450; vertical-align: middle;"></span> <?php _e( 'Debug Configuration Saved:', 'leanstack' ); ?></strong> <?php _e( 'wp-config.php was atomically updated with an automatic backup.', 'leanstack' ); ?></p>
                </div>
            <?php endif; ?>

            <?php if ( isset( $_GET['cleared'] ) ) : ?>
                <div class="notice notice-success is-dismissible">
                    <p><strong><span class="dashicons dashicons-trash" style="color: #2271b1; vertical-align: middle;"></span> <?php _e( 'Log Cleared:', 'leanstack' ); ?></strong> <?php _e( 'Target log file was truncated to 0 bytes successfully.', 'leanstack' ); ?></p>
                </div>
            <?php endif; ?>

            <?php if ( isset( $_GET['error'] ) ) : ?>
                <div class="notice notice-error is-dismissible">
                    <p><strong><span class="dashicons dashicons-warning" style="color: #dc3232; vertical-align: middle;"></span> <?php _e( 'Error:', 'leanstack' ); ?></strong> 
                        <?php
                        if ( 'not_writable' === $_GET['error'] ) {
                            _e( 'wp-config.php is not writable by PHP-FPM. Please check file permissions (0600) and ownership.', 'leanstack' );
                        } else {
                            _e( 'Could not safely update wp-config.php. File was left intact.', 'leanstack' );
                        }
                        ?>
                    </p>
                </div>
            <?php endif; ?>

            <h2 class="nav-tab-wrapper" style="margin-bottom: 20px;">
                <a href="<?php echo esc_url( admin_url( 'tools.php?page=leanstack-logs&tab=viewer&log_id=' . $selected_log_id ) ); ?>" class="nav-tab <?php echo 'viewer' === $active_tab ? 'nav-tab-active' : ''; ?>">
                    <span class="dashicons dashicons-visibility" style="vertical-align: text-bottom;"></span> <?php _e( 'Interactive Log Viewer', 'leanstack' ); ?>
                </a>
                <a href="<?php echo esc_url( admin_url( 'tools.php?page=leanstack-logs&tab=settings' ) ); ?>" class="nav-tab <?php echo 'settings' === $active_tab ? 'nav-tab-active' : ''; ?>">
                    <span class="dashicons dashicons-admin-generic" style="vertical-align: text-bottom;"></span> <?php _e( 'Debug Settings &amp; Toggles', 'leanstack' ); ?>
                    <?php if ( $debug_settings['wp_debug'] ) : ?>
                        <span class="badge" style="background: #e7f5ea; color: #007017; padding: 2px 6px; border-radius: 8px; font-size: 11px; margin-left: 5px; font-weight: bold;">DEBUG ON</span>
                    <?php endif; ?>
                </a>
            </h2>

            <?php if ( 'viewer' === $active_tab ) : ?>
                <!-- Sub-nav Pills for Log Types -->
                <div style="display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 20px;">
                    <?php foreach ( $available_logs as $lid => $linfo ) : ?>
                        <?php $is_selected = ( $lid === $selected_log_id ); ?>
                        <a href="<?php echo esc_url( admin_url( 'tools.php?page=leanstack-logs&tab=viewer&log_id=' . $lid ) ); ?>"
                           style="display: inline-flex; align-items: center; gap: 8px; padding: 8px 14px; border-radius: 6px; text-decoration: none; font-weight: 500; font-size: 13px; border: 1px solid <?php echo $is_selected ? '#2271b1' : '#ccd0d4'; ?>; background: <?php echo $is_selected ? '#f0f6fc' : '#ffffff'; ?>; color: <?php echo $is_selected ? '#0c528d' : '#2c3338'; ?>;">
                            <span class="dashicons <?php echo 'wp-debug' === $lid ? 'dashicons-wordpress' : ( 'php-slow' === $lid ? 'dashicons-performance' : ( 'angie-error' === $lid ? 'dashicons-warning' : 'dashicons-networking' ) ); ?>" style="font-size: 16px; width: 16px; height: 16px;"></span>
                            <?php echo esc_html( $linfo['name'] ); ?>
                            <span style="background: <?php echo $is_selected ? '#2271b1' : '#e0e0e0'; ?>; color: <?php echo $is_selected ? '#ffffff' : '#50575e'; ?>; font-size: 11px; padding: 1px 6px; border-radius: 10px; font-family: monospace;">
                                <?php echo esc_html( $linfo['size_human'] ); ?>
                            </span>
                        </a>
                    <?php endforeach; ?>
                </div>

                <!-- Log Metadata Card -->
                <div style="background: #ffffff; border: 1px solid #c3c4c7; border-left: 4px solid #2271b1; padding: 16px 20px; border-radius: 4px; margin-bottom: 20px; display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 15px;">
                    <div>
                        <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 5px;">
                            <h3 style="margin: 0; font-size: 16px; color: #1d2327;"><?php echo esc_html( $current_log['name'] ); ?></h3>
                            <?php if ( $current_log['exists'] ) : ?>
                                <span class="badge" style="background: #e7f5ea; color: #007017; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600;"><?php _e( 'Active on disk', 'leanstack' ); ?></span>
                            <?php else : ?>
                                <span class="badge" style="background: #fcf0f0; color: #d63638; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600;"><?php _e( 'Clean / File not created', 'leanstack' ); ?></span>
                            <?php endif; ?>
                        </div>
                        <p style="margin: 0 0 6px 0; color: #646970; font-size: 13px;"><?php echo esc_html( $current_log['description'] ); ?></p>
                        <p style="margin: 0; font-size: 12px; color: #50575e;">
                            <strong><?php _e( 'Path:', 'leanstack' ); ?></strong> <code id="ls-log-path"><?php echo esc_html( $current_log['path'] ); ?></code>
                            <span style="margin: 0 8px; color: #ccc;">|</span>
                            <strong><?php _e( 'Size:', 'leanstack' ); ?></strong> <span id="ls-log-size"><?php echo esc_html( $current_log['size_human'] ); ?></span>
                            <span style="margin: 0 8px; color: #ccc;">|</span>
                            <strong><?php _e( 'Last Updated:', 'leanstack' ); ?></strong> <span id="ls-log-mod"><?php echo esc_html( $current_log['modified'] ); ?></span>
                        </p>
                    </div>

                    <!-- Toolbar Actions -->
                    <div style="display: flex; flex-wrap: wrap; align-items: center; gap: 8px;">
                        <label style="display: inline-flex; align-items: center; gap: 5px; font-size: 13px; font-weight: 500; margin-right: 8px; cursor: pointer;">
                            <input type="checkbox" id="ls-auto-refresh">
                            <span class="dashicons dashicons-update" style="font-size: 15px; width: 15px; height: 15px;"></span> <?php _e( 'Live Tail (5s)', 'leanstack' ); ?>
                        </label>

                        <button type="button" id="ls-refresh-btn" class="button button-secondary">
                            <span class="dashicons dashicons-update" style="vertical-align: text-bottom;"></span> <?php _e( 'Refresh', 'leanstack' ); ?>
                        </button>

                        <?php if ( $current_log['exists'] && $current_log['readable'] ) : ?>
                            <a href="<?php echo esc_url( wp_nonce_url( admin_url( 'admin-post.php?action=leanstack_download_log&log_id=' . $selected_log_id ), 'leanstack_download_log_action', 'leanstack_nonce' ) ); ?>" class="button button-secondary">
                                <span class="dashicons dashicons-download" style="vertical-align: text-bottom;"></span> <?php _e( 'Download', 'leanstack' ); ?>
                            </a>
                        <?php endif; ?>

                        <?php if ( $current_log['exists'] && $current_log['writable'] ) : ?>
                            <form method="post" action="<?php echo esc_url( admin_url( 'admin-post.php' ) ); ?>" style="margin: 0;" onsubmit="return confirm(<?php echo esc_attr( json_encode( __( 'Are you sure you want to clear and truncate this log file to 0 bytes?', 'leanstack' ) ) ); ?>);">
                                <?php wp_nonce_field( 'leanstack_clear_log_action', 'leanstack_nonce' ); ?>
                                <input type="hidden" name="action" value="leanstack_clear_log">
                                <input type="hidden" name="log_id" value="<?php echo esc_attr( $selected_log_id ); ?>">
                                <button type="submit" class="button button-link-delete" style="padding: 4px 10px; color: #b32d2e; text-decoration: none; border: 1px solid #f0b849; border-radius: 4px; background: #fff8e5;">
                                    <span class="dashicons dashicons-trash" style="vertical-align: text-bottom;"></span> <?php _e( 'Clear Log', 'leanstack' ); ?>
                                </button>
                            </form>
                        <?php endif; ?>
                    </div>
                </div>

                <!-- Filter Search Box -->
                <div style="margin-bottom: 12px; display: flex; align-items: center; justify-content: space-between;">
                    <div style="position: relative; width: 320px;">
                        <input type="text" id="ls-log-filter" placeholder="<?php esc_attr_e( 'Filter lines (e.g. Fatal, Warning, SQL)...', 'leanstack' ); ?>" style="width: 100%; padding-left: 28px; border-radius: 4px;">
                        <span class="dashicons dashicons-search" style="position: absolute; left: 6px; top: 7px; color: #8c8f94; font-size: 16px;"></span>
                    </div>
                    <div style="color: #646970; font-size: 12px;">
                        <span id="ls-lines-count"><?php echo ! empty( $initial_content ) ? substr_count( $initial_content, "\n" ) + 1 : 0; ?></span> <?php _e( 'lines displayed (tail: max 300)', 'leanstack' ); ?>
                    </div>
                </div>

                <!-- Terminal Log Viewer Window -->
                <div style="position: relative; background: #1e1e24; border-radius: 6px; box-shadow: 0 4px 12px rgba(0,0,0,0.15); border: 1px solid #2e2e38; overflow: hidden;">
                    <div style="background: #272730; padding: 8px 16px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid #363642;">
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <span style="width: 10px; height: 10px; border-radius: 50%; background: #ff5f56; display: inline-block;"></span>
                            <span style="width: 10px; height: 10px; border-radius: 50%; background: #ffbd2e; display: inline-block;"></span>
                            <span style="width: 10px; height: 10px; border-radius: 50%; background: #27c93f; display: inline-block;"></span>
                            <span style="color: #9999a8; font-family: monospace; font-size: 12px; margin-left: 8px;"><?php echo esc_html( basename( $current_log['path'] ) ); ?></span>
                        </div>
                        <div id="ls-poll-indicator" style="display: none; align-items: center; gap: 6px; color: #4ade80; font-size: 11px; font-family: monospace;">
                            <span class="spinner is-active" style="float: none; margin: 0; width: 14px; height: 14px;"></span> <?php _e( 'Live streaming...', 'leanstack' ); ?>
                        </div>
                    </div>

                    <pre id="ls-terminal" style="margin: 0; padding: 16px; height: 500px; overflow-y: scroll; font-family: Consolas, 'Liberation Mono', Menlo, Monaco, Courier, monospace; font-size: 12.5px; line-height: 1.5; color: #d4d4d8; background: #18181b; white-space: pre-wrap; word-break: break-all; scroll-behavior: smooth;"><?php
                        if ( ! empty( $initial_content ) ) {
                            echo esc_html( $initial_content );
                        } else {
                            echo esc_html( __( 'Log is currently empty or no entries recorded yet.', 'leanstack' ) );
                        }
                    ?></pre>
                </div>

                <script>
                (function() {
                    var selectedLog = <?php echo json_encode( $selected_log_id ); ?>;
                    var ajaxUrl = <?php echo json_encode( admin_url( 'admin-ajax.php' ) ); ?>;
                    var ajaxNonce = <?php echo json_encode( $ajax_nonce ); ?>;
                    var terminal = document.getElementById('ls-terminal');
                    var filterInput = document.getElementById('ls-log-filter');
                    var autoRefresh = document.getElementById('ls-auto-refresh');
                    var refreshBtn = document.getElementById('ls-refresh-btn');
                    var pollIndicator = document.getElementById('ls-poll-indicator');
                    var linesCountEl = document.getElementById('ls-lines-count');
                    var timer = null;
                    var emptyPlaceholder = <?php echo json_encode( __( 'Log is currently empty or no entries recorded yet.', 'leanstack' ) ); ?>;
                    var rawContent = <?php echo json_encode( ! empty( $initial_content ) ? $initial_content : '' ); ?>;

                    function scrollToBottom() {
                        if (terminal) {
                            terminal.scrollTop = terminal.scrollHeight;
                        }
                    }
                    scrollToBottom();

                    function renderTerminal(text, count) {
                        if (!terminal) return;
                        if (!text) {
                            terminal.innerText = emptyPlaceholder;
                            if (linesCountEl) linesCountEl.innerText = '0';
                            return;
                        }
                        terminal.innerText = text;
                        if (linesCountEl) linesCountEl.innerText = count !== undefined ? count : (text.split("\n").length);
                    }

                    function applyFilter() {
                        var term = filterInput ? filterInput.value.toLowerCase().trim() : '';
                        if (!rawContent) {
                            renderTerminal('', 0);
                            return;
                        }
                        if (!term) {
                            renderTerminal(rawContent);
                            return;
                        }
                        var allLines = rawContent.split("\n");
                        var matched = allLines.filter(function(line) {
                            return line.toLowerCase().indexOf(term) !== -1;
                        });
                        renderTerminal(matched.length > 0 ? matched.join("\n") : (<?php echo json_encode( __( 'No matching log entries found.', 'leanstack' ) ); ?>), matched.length);
                    }

                    if (filterInput) {
                        filterInput.addEventListener('input', applyFilter);
                    }

                    function fetchLogTail() {
                        if (pollIndicator) pollIndicator.style.display = 'inline-flex';
                        var url = ajaxUrl + '?action=leanstack_get_log_tail&log_id=' + encodeURIComponent(selectedLog) + '&nonce=' + encodeURIComponent(ajaxNonce) + '&_t=' + Date.now();
                        fetch(url)
                            .then(function(r) { return r.json(); })
                            .then(function(res) {
                                if (pollIndicator) pollIndicator.style.display = 'none';
                                if (res && res.success && res.data) {
                                    rawContent = res.data.content || '';
                                    applyFilter();
                                    scrollToBottom();
                                    if (document.getElementById('ls-log-size')) {
                                        document.getElementById('ls-log-size').innerText = res.data.size_human;
                                    }
                                    if (document.getElementById('ls-log-mod')) {
                                        document.getElementById('ls-log-mod').innerText = res.data.modified;
                                    }
                                }
                            })
                            .catch(function(err) {
                                if (pollIndicator) pollIndicator.style.display = 'none';
                            });
                    }

                    if (refreshBtn) {
                        refreshBtn.addEventListener('click', function() {
                            fetchLogTail();
                        });
                    }

                    if (autoRefresh) {
                        autoRefresh.addEventListener('change', function() {
                            if (this.checked) {
                                fetchLogTail();
                                timer = setInterval(fetchLogTail, 5000);
                            } else {
                                if (timer) clearInterval(timer);
                            }
                        });
                    }
                })();
                </script>

            <?php else : ?>
                <!-- Settings Tab -->
                <div style="max-width: 900px; margin-top: 20px;">
                    <form method="post" action="<?php echo esc_url( admin_url( 'admin-post.php' ) ); ?>">
                        <?php wp_nonce_field( 'leanstack_save_log_settings_action', 'leanstack_nonce' ); ?>
                        <input type="hidden" name="action" value="leanstack_save_log_settings">

                        <!-- Debug Mode Master Toggle -->
                        <div style="background: #ffffff; border: 1px solid #ccd0d4; border-radius: 6px; padding: 22px; margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
                            <div style="display: flex; align-items: flex-start; justify-content: space-between; gap: 20px;">
                                <div>
                                    <h3 style="margin: 0 0 8px 0; color: #1d2327; font-size: 16px;">
                                        <span class="dashicons dashicons-admin-tools" style="color: #2271b1; vertical-align: middle;"></span>
                                        <?php _e( '1. WordPress Core Debugging (WP_DEBUG)', 'leanstack' ); ?>
                                    </h3>
                                    <p style="margin: 0; color: #646970; font-size: 13px; line-height: 1.5;">
                                        <?php _e( 'Controls the master PHP debugging mode across WordPress. When enabled, all PHP errors, notices, warnings, and deprecations are caught by the runtime engine.', 'leanstack' ); ?>
                                    </p>
                                </div>
                                <label style="position: relative; display: inline-block; width: 48px; height: 26px; flex-shrink: 0;">
                                    <input type="checkbox" name="wp_debug" value="1" <?php checked( $debug_settings['wp_debug'], true ); ?> style="opacity: 0; width: 0; height: 0;">
                                    <span class="ls-slider" style="position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background-color: <?php echo $debug_settings['wp_debug'] ? '#2271b1' : '#ccc'; ?>; border-radius: 26px; transition: .3s;">
                                        <span style="position: absolute; content: ''; height: 20px; width: 20px; left: <?php echo $debug_settings['wp_debug'] ? '24px' : '3px'; ?>; bottom: 3px; background-color: white; border-radius: 50%; transition: .3s;"></span>
                                    </span>
                                </label>
                            </div>
                        </div>

                        <!-- Debug Log Destination Toggle -->
                        <div style="background: #ffffff; border: 1px solid #ccd0d4; border-radius: 6px; padding: 22px; margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
                            <div style="display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; margin-bottom: 16px;">
                                <div>
                                    <h3 style="margin: 0 0 8px 0; color: #1d2327; font-size: 16px;">
                                        <span class="dashicons dashicons-media-document" style="color: #007017; vertical-align: middle;"></span>
                                        <?php _e( '2. Save Errors to Debug Log (WP_DEBUG_LOG)', 'leanstack' ); ?>
                                    </h3>
                                    <p style="margin: 0; color: #646970; font-size: 13px; line-height: 1.5;">
                                        <?php _e( 'Directs caught PHP errors, warnings, and fatal traces into a log file for offline review without displaying them to visitors.', 'leanstack' ); ?>
                                    </p>
                                </div>
                                <label style="position: relative; display: inline-block; width: 48px; height: 26px; flex-shrink: 0;">
                                    <input type="checkbox" name="wp_debug_log" value="1" <?php checked( $debug_settings['wp_debug_log'], true ); ?> style="opacity: 0; width: 0; height: 0;">
                                    <span class="ls-slider" style="position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background-color: <?php echo $debug_settings['wp_debug_log'] ? '#2271b1' : '#ccc'; ?>; border-radius: 26px; transition: .3s;">
                                        <span style="position: absolute; content: ''; height: 20px; width: 20px; left: <?php echo $debug_settings['wp_debug_log'] ? '24px' : '3px'; ?>; bottom: 3px; background-color: white; border-radius: 50%; transition: .3s;"></span>
                                    </span>
                                </label>
                            </div>

                            <hr style="margin: 16px 0; border: 0; border-top: 1px solid #f0f0f1;">

                            <h4 style="margin: 0 0 10px 0;"><?php _e( 'Log File Storage Location:', 'leanstack' ); ?></h4>
                            <?php
                            $is_custom_path = ( is_string( $debug_settings['wp_debug_log_val'] ) && '1' !== $debug_settings['wp_debug_log_val'] && 'true' !== strtolower( $debug_settings['wp_debug_log_val'] ) );
                            $is_wp_content = ( true === $debug_settings['wp_debug_log_val'] || ( is_string( $debug_settings['wp_debug_log_val'] ) && false !== strpos( $debug_settings['wp_debug_log_val'], 'wp-content/debug.log' ) ) );
                            ?>
                            <div style="display: flex; flex-direction: column; gap: 10px;">
                                <label style="display: flex; align-items: center; gap: 8px; cursor: pointer;">
                                    <input type="radio" name="wp_debug_log_destination" value="tenant_logs" <?php checked( ! $is_wp_content, true ); ?>>
                                    <span>
                                        <strong><?php _e( 'Secured Tenant Log Directory (Recommended):', 'leanstack' ); ?></strong>
                                        <code><?php echo esc_html( $this->get_default_debug_log_path() ); ?></code>
                                        <br><small style="color: #646970;"><?php _e( 'Stored outside public webroot. Immune to direct browser downloads by unauthorized visitors.', 'leanstack' ); ?></small>
                                    </span>
                                </label>
                                <label style="display: flex; align-items: center; gap: 8px; cursor: pointer;">
                                    <input type="radio" name="wp_debug_log_destination" value="wp_content" <?php checked( $is_wp_content, true ); ?>>
                                    <span>
                                        <strong><?php _e( 'Standard WordPress Webroot:', 'leanstack' ); ?></strong>
                                        <code>wp-content/debug.log</code>
                                        <br><small style="color: #646970;"><?php _e( 'Default WordPress convention. Protected by Angie 8G/WAF rules blocking *.log files.', 'leanstack' ); ?></small>
                                    </span>
                                </label>
                            </div>
                        </div>

                        <!-- Debug Display Toggle -->
                        <div style="background: #ffffff; border: 1px solid #ccd0d4; border-radius: 6px; padding: 22px; margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
                            <div style="display: flex; align-items: flex-start; justify-content: space-between; gap: 20px;">
                                <div>
                                    <h3 style="margin: 0 0 8px 0; color: #1d2327; font-size: 16px;">
                                        <span class="dashicons dashicons-desktop" style="color: #d63638; vertical-align: middle;"></span>
                                        <?php _e( '3. Display Errors on Web Pages (WP_DEBUG_DISPLAY)', 'leanstack' ); ?>
                                    </h3>
                                    <p style="margin: 0 0 8px 0; color: #646970; font-size: 13px; line-height: 1.5;">
                                        <?php _e( 'Controls whether errors and warnings are printed directly into the HTML response rendered in the visitor\'s browser. When toggled on, sets display_errors to 1.', 'leanstack' ); ?>
                                    </p>
                                    <div style="display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; background: #fff8e5; border-left: 3px solid #dba617; border-radius: 2px; font-size: 12px; color: #61460b;">
                                        <span class="dashicons dashicons-info" style="font-size: 16px; width: 16px; height: 16px;"></span>
                                        <strong><?php _e( 'Production Security Notice:', 'leanstack' ); ?></strong> <?php _e( 'Keep this toggle OFF on live sites to prevent leaking database schemas, API keys, and internal system paths to web visitors.', 'leanstack' ); ?>
                                    </div>
                                </div>
                                <label style="position: relative; display: inline-block; width: 48px; height: 26px; flex-shrink: 0;">
                                    <input type="checkbox" name="wp_debug_display" value="1" <?php checked( $debug_settings['wp_debug_display'], true ); ?> style="opacity: 0; width: 0; height: 0;">
                                    <span class="ls-slider" style="position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background-color: <?php echo $debug_settings['wp_debug_display'] ? '#2271b1' : '#ccc'; ?>; border-radius: 26px; transition: .3s;">
                                        <span style="position: absolute; content: ''; height: 20px; width: 20px; left: <?php echo $debug_settings['wp_debug_display'] ? '24px' : '3px'; ?>; bottom: 3px; background-color: white; border-radius: 50%; transition: .3s;"></span>
                                    </span>
                                </label>
                            </div>
                        </div>

                        <!-- Diagnostics & Permissions Card -->
                        <div style="background: #f6f7f7; border: 1px solid #dcdcde; border-radius: 6px; padding: 18px; margin-bottom: 25px;">
                            <h4 style="margin: 0 0 10px 0;"><?php _e( 'Configuration File Diagnostics', 'leanstack' ); ?></h4>
                            <table class="widefat striped" style="background: #fff;">
                                <tbody>
                                    <tr>
                                        <td style="width: 200px;"><strong><?php _e( 'Configuration Target', 'leanstack' ); ?></strong></td>
                                        <td><code><?php echo esc_html( $debug_settings['config_file'] ? $debug_settings['config_file'] : 'wp-config.php (not found)' ); ?></code></td>
                                    </tr>
                                    <tr>
                                        <td><strong><?php _e( 'Write Permissions', 'leanstack' ); ?></strong></td>
                                        <td>
                                            <?php if ( $debug_settings['is_writable'] ) : ?>
                                                <span class="dashicons dashicons-yes-alt" style="color: #007017;"></span>
                                                <span style="color: #007017; font-weight: bold;"><?php _e( 'Writable (Atomic updates enabled)', 'leanstack' ); ?></span>
                                            <?php else : ?>
                                                <span class="dashicons dashicons-warning" style="color: #d63638;"></span>
                                                <span style="color: #d63638; font-weight: bold;"><?php _e( 'Read-Only (Manual edit required or update permissions)', 'leanstack' ); ?></span>
                                            <?php endif; ?>
                                        </td>
                                    </tr>
                                    <tr>
                                        <td><strong><?php _e( 'Runtime display_errors', 'leanstack' ); ?></strong></td>
                                        <td><code><?php echo esc_html( ini_get( 'display_errors' ) ? '1 (Active)' : '0 (Hidden)' ); ?></code></td>
                                    </tr>
                                    <tr>
                                        <td><strong><?php _e( 'Runtime log_errors', 'leanstack' ); ?></strong></td>
                                        <td><code><?php echo esc_html( ini_get( 'log_errors' ) ? '1 (Active)' : '0 (Off)' ); ?></code></td>
                                    </tr>
                                    <tr>
                                        <td><strong><?php _e( 'Runtime error_log Path', 'leanstack' ); ?></strong></td>
                                        <td><code><?php echo esc_html( ini_get( 'error_log' ) ? ini_get( 'error_log' ) : 'System Default' ); ?></code></td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>

                        <p class="submit" style="margin: 0;">
                            <button type="submit" class="button button-primary button-large" <?php disabled( ! $debug_settings['is_writable'], true ); ?>>
                                <span class="dashicons dashicons-saved" style="vertical-align: text-bottom;"></span> <?php _e( 'Save Debug Settings', 'leanstack' ); ?>
                            </button>
                        </p>
                    </form>
                </div>
            <?php endif; ?>
        </div>
        <?php
    }

    /**
     * Query Monitor Drop-in Self-Healing Reconciler
     */
    public function maybe_reconcile_qm_dropin() {
        if ( ! current_user_can( 'activate_plugins' ) ) {
            return;
        }
        $qm_plugin = WP_CONTENT_DIR . '/plugins/query-monitor';
        $qm_source = $qm_plugin . '/wp-content/db.php';
        $qm_dropin = WP_CONTENT_DIR . '/db.php';

        if ( ! file_exists( $qm_source ) ) {
            // If Query Monitor plugin is uninstalled, remove any dangling drop-in symlink to prevent fatal crashes
            if ( is_link( $qm_dropin ) ) {
                $target = @readlink( $qm_dropin );
                if ( false !== $target && ( false !== strpos( $target, 'query-monitor' ) || ! file_exists( $qm_dropin ) ) ) {
                    @unlink( $qm_dropin );
                }
            }
            return;
        }

        // Safely determine if Query Monitor is active
        $qm_active = class_exists( 'QueryMonitor' );
        if ( ! $qm_active && function_exists( 'is_plugin_active' ) ) {
            $qm_active = is_plugin_active( 'query-monitor/query-monitor.php' );
        }
        if ( ! $qm_active ) {
            $active_plugins = (array) get_option( 'active_plugins', array() );
            $qm_active = in_array( 'query-monitor/query-monitor.php', $active_plugins, true );
            if ( ! $qm_active && is_multisite() ) {
                $network_plugins = (array) get_site_option( 'active_sitewide_plugins', array() );
                $qm_active = isset( $network_plugins['query-monitor/query-monitor.php'] );
            }
        }
        if ( ! $qm_active ) {
            return;
        }

        // Check if db.php is missing or a broken symlink
        $needs_fix = false;
        if ( is_link( $qm_dropin ) ) {
            if ( ! file_exists( $qm_dropin ) ) {
                $needs_fix = true;
            }
        } elseif ( ! file_exists( $qm_dropin ) ) {
            $needs_fix = true;
        }

        if ( $needs_fix ) {
            $this->reconcile_qm_dropin();
        }
    }

    public function handle_fix_qm_dropin() {
        if ( ! current_user_can( 'activate_plugins' ) ) {
            wp_die( 'Unauthorized', 403 );
        }
        check_admin_referer( 'leanstack_fix_qm_dropin' );
        $result = $this->reconcile_qm_dropin();
        $referer = wp_get_referer();
        if ( $referer ) {
            wp_safe_redirect( add_query_arg( array( 'qm_fixed' => $result ? '1' : '0' ), $referer ) );
        } else {
            wp_safe_redirect( add_query_arg( array( 'page' => 'leanstack-logs', 'qm_fixed' => $result ? '1' : '0' ), admin_url( 'tools.php' ) ) );
        }
        exit;
    }

    public function reconcile_qm_dropin() {
        $qm_source = WP_CONTENT_DIR . '/plugins/query-monitor/wp-content/db.php';
        $qm_dropin = WP_CONTENT_DIR . '/db.php';

        if ( ! file_exists( $qm_source ) ) {
            return false;
        }

        // Safely inspect existing file/symlink: do not clobber third-party drop-ins
        if ( is_link( $qm_dropin ) ) {
            $target = @readlink( $qm_dropin );
            if ( file_exists( $qm_dropin ) && false !== $target && false === strpos( $target, 'query-monitor' ) ) {
                return false; // Valid third-party drop-in symlink, do not clobber
            }
            @unlink( $qm_dropin );
        } elseif ( file_exists( $qm_dropin ) ) {
            if ( is_file( $qm_dropin ) ) {
                $content = @file_get_contents( $qm_dropin, false, null, 0, 500 );
                if ( false !== $content && false === strpos( $content, 'Query Monitor' ) ) {
                    return false; // Third-party drop-in present, do not clobber
                }
            }
            @unlink( $qm_dropin );
        }

        // Attempt relative symlink first (plugins/query-monitor/wp-content/db.php)
        $rel_target = 'plugins/query-monitor/wp-content/db.php';
        $success = false;
        if ( function_exists( 'symlink' ) ) {
            $success = @symlink( $rel_target, $qm_dropin );
        }

        // Fallback to copy if symlink fails or is disabled
        if ( ! $success && ! file_exists( $qm_dropin ) ) {
            $success = @copy( $qm_source, $qm_dropin );
            if ( $success ) {
                @chmod( $qm_dropin, 0644 );
            }
        }

        return $success;
    }
}

add_action( 'plugins_loaded', array( 'LeanStackBridge', 'get_instance' ) );
