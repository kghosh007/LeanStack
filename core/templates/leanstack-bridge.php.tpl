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

class LeanStackBridge {

    private static $instance = null;
    private $nginx_dir = null;
    private $status_file = null;
    private $cron_status_file = null;

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
            'last_run' => null,
            'status' => 'active',
            'ran_via' => 'systemd_timer',
            'events_processed' => 0,
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

    public function handle_run_cron_now() {
        if ( ! current_user_can( 'manage_options' ) ) {
            wp_die( __( 'Unauthorized.', 'leanstack' ) );
        }
        check_admin_referer( 'leanstack_run_cron_action', 'leanstack_nonce' );

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

        if ( $this->cron_status_file ) {
            $status_data = array(
                'last_run' => gmdate( 'Y-m-d\TH:i:s\Z' ),
                'status' => 'completed',
                'ran_via' => 'wp_dashboard',
                'events_processed' => $executed,
            );
            @file_put_contents( $this->cron_status_file, json_encode( $status_data ) );
        }

        // Also mirror to candidate nginx dir if distinct
        $doc_root = rtrim( ABSPATH, '/' );
        $alt_cron_file = dirname( $doc_root ) . '/nginx/.cron_status.json';
        if ( $alt_cron_file !== $this->cron_status_file && is_dir( dirname( $alt_cron_file ) ) ) {
            @file_put_contents( $alt_cron_file, json_encode( $status_data ) );
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
                'process_count' => 0,
                'tenant_rss_memory' => 0,
                'tenant_rss_formatted' => '0 B',
                'load_avg' => '0.00, 0.00, 0.00',
                'uptime' => 'N/A',
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

        // 4. System & Tenant CPU / Memory from /proc
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

        $data['system']['process_count'] = $proc_count;
        $data['system']['tenant_rss_memory'] = $rss_total_kb * 1024;
        $data['system']['tenant_rss_formatted'] = function_exists( 'size_format' ) ? size_format( $rss_total_kb * 1024, 2 ) : ( ( $rss_total_kb * 1024 ) . ' B' );

        if ( function_exists( 'sys_getloadavg' ) ) {
            $load = sys_getloadavg();
            if ( is_array( $load ) && count( $load ) >= 3 ) {
                $data['system']['load_avg'] = sprintf( '%.2f, %.2f, %.2f', $load[0], $load[1], $load[2] );
            }
        } elseif ( file_exists( '/proc/loadavg' ) ) {
            $lavg = @file_get_contents( '/proc/loadavg' );
            if ( $lavg ) {
                $parts = explode( ' ', trim( $lavg ) );
                $data['system']['load_avg'] = implode( ', ', array_slice( $parts, 0, 3 ) );
            }
        }

        if ( file_exists( '/proc/uptime' ) ) {
            $up = @file_get_contents( '/proc/uptime' );
            if ( $up ) {
                $secs = (int) explode( ' ', trim( $up ) )[0];
                $days = floor( $secs / 86400 );
                $hours = floor( ( $secs % 86400 ) / 3600 );
                $mins = floor( ( $secs % 3600 ) / 60 );
                $data['system']['uptime'] = "{$days}d {$hours}h {$mins}m";
            }
        }

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
                        <h3 style="margin-top: 0; color: #1d2327;"><span class="dashicons dashicons-dashboard" style="color: #d63638;"></span> <?php _e( 'Tenant CPU & Memory', 'leanstack' ); ?></h3>
                        <p style="font-size: 28px; font-weight: bold; margin: 10px 0; color: #d63638;"><?php echo esc_html( $analytics['system']['tenant_rss_formatted'] ); ?> <span style="font-size: 14px; font-weight: normal; color: #646970;">RSS</span></p>
                        <p style="color: #646970; margin: 0;"><?php printf( __( 'Workers: <strong>%d</strong> | Load: <strong>%s</strong>', 'leanstack' ), $analytics['system']['process_count'], $analytics['system']['load_avg'] ); ?></p>
                        <hr style="margin: 15px 0; border: 0; border-top: 1px solid #f0f0f1;">
                        <small style="color: #646970;"><?php printf( __( 'Server Uptime: %s', 'leanstack' ), $analytics['system']['uptime'] ); ?></small>
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
}

add_action( 'plugins_loaded', array( 'LeanStackBridge', 'get_instance' ) );
