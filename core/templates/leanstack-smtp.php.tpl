<?php
/**
 * Plugin Name: LeanStack Transactional Email & SMTP
 * Description: Zero-daemon authenticated transactional email delivery via PHPMailer integration and OS msmtp relay sync.
 * Version: 1.0.0
 * Author: LeanStack
 */

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

class LeanStackSMTP {

    private static $instance = null;
    private $config = null;

    public static function get_instance() {
        if ( null === self::$instance ) {
            self::$instance = new self();
        }
        return self::$instance;
    }

    private function __construct() {
        add_action( 'phpmailer_init', array( $this, 'configure_phpmailer' ), 999 );
        add_action( 'wp_mail_failed', array( $this, 'log_mail_failure' ) );
        add_action( 'wp_mail_succeeded', array( $this, 'log_mail_success' ) );
    }

    /**
     * Resolves SMTP configuration across Environment Variables, wp-config constants,
     * protected tenant JSON config, and WordPress options.
     *
     * @return array
     */
    public function get_config() {
        if ( null !== $this->config ) {
            return $this->config;
        }

        $cfg = array(
            'enabled'    => false,
            'source'     => 'none',
            'host'       => '',
            'port'       => 587,
            'encryption' => 'tls',
            'auth'       => true,
            'user'       => '',
            'pass'       => '',
            'from_email' => '',
            'from_name'  => '',
        );

        // 1. Environment Variables Override
        $env_host = getenv( 'SMTP_HOST' );
        if ( ! empty( $env_host ) ) {
            $cfg['enabled']    = true;
            $cfg['source']     = 'environment';
            $cfg['host']       = sanitize_text_field( $env_host );
            $cfg['port']       = getenv( 'SMTP_PORT' ) ? (int) getenv( 'SMTP_PORT' ) : 587;
            $cfg['encryption'] = getenv( 'SMTP_SECURE' ) ? sanitize_key( getenv( 'SMTP_SECURE' ) ) : 'tls';
            $cfg['user']       = getenv( 'SMTP_USER' ) ? sanitize_text_field( getenv( 'SMTP_USER' ) ) : '';
            $cfg['pass']       = getenv( 'SMTP_PASS' ) ? (string) getenv( 'SMTP_PASS' ) : '';
            $cfg['auth']       = ( '' !== $cfg['user'] );
            $cfg['from_email'] = getenv( 'SMTP_FROM' ) ? sanitize_email( getenv( 'SMTP_FROM' ) ) : '';
            $cfg['from_name']  = getenv( 'SMTP_NAME' ) ? sanitize_text_field( getenv( 'SMTP_NAME' ) ) : '';
            $this->config = $cfg;
            return $cfg;
        }

        // 2. wp-config.php Constants Override
        if ( defined( 'LEANSTACK_SMTP_HOST' ) && '' !== LEANSTACK_SMTP_HOST ) {
            $cfg['enabled']    = ! defined( 'LEANSTACK_SMTP_ENABLED' ) || LEANSTACK_SMTP_ENABLED;
            $cfg['source']     = 'constant';
            $cfg['host']       = sanitize_text_field( LEANSTACK_SMTP_HOST );
            $cfg['port']       = defined( 'LEANSTACK_SMTP_PORT' ) ? (int) LEANSTACK_SMTP_PORT : 587;
            $cfg['encryption'] = defined( 'LEANSTACK_SMTP_SECURE' ) ? sanitize_key( LEANSTACK_SMTP_SECURE ) : 'tls';
            $cfg['user']       = defined( 'LEANSTACK_SMTP_USER' ) ? sanitize_text_field( LEANSTACK_SMTP_USER ) : '';
            $cfg['pass']       = defined( 'LEANSTACK_SMTP_PASS' ) ? (string) LEANSTACK_SMTP_PASS : '';
            $cfg['auth']       = defined( 'LEANSTACK_SMTP_AUTH' ) ? (bool) LEANSTACK_SMTP_AUTH : ( '' !== $cfg['user'] );
            $cfg['from_email'] = defined( 'LEANSTACK_SMTP_FROM' ) ? sanitize_email( LEANSTACK_SMTP_FROM ) : '';
            $cfg['from_name']  = defined( 'LEANSTACK_SMTP_NAME' ) ? sanitize_text_field( LEANSTACK_SMTP_NAME ) : '';
            $this->config = $cfg;
            return $cfg;
        }

        // 3. Local JSON Config (/home/{user}/.leanstack-smtp.json or config/smtp.json)
        $home_dir = dirname( ABSPATH );
        $json_candidates = array(
            $home_dir . '/.leanstack-smtp.json',
            $home_dir . '/config/smtp.json',
            WP_CONTENT_DIR . '/smtp.json',
        );

        foreach ( $json_candidates as $jfile ) {
            if ( @file_exists( $jfile ) && @is_readable( $jfile ) ) {
                $raw = @file_get_contents( $jfile );
                $data = json_decode( $raw, true );
                if ( is_array( $data ) && ! empty( $data['host'] ) ) {
                    $cfg['enabled']    = isset( $data['enabled'] ) ? (bool) $data['enabled'] : true;
                    $cfg['source']     = 'json';
                    $cfg['host']       = sanitize_text_field( $data['host'] );
                    $cfg['port']       = isset( $data['port'] ) ? (int) $data['port'] : 587;
                    $cfg['encryption'] = isset( $data['encryption'] ) ? sanitize_key( $data['encryption'] ) : 'tls';
                    $cfg['user']       = isset( $data['user'] ) ? sanitize_text_field( $data['user'] ) : '';
                    $cfg['pass']       = isset( $data['pass'] ) ? (string) $data['pass'] : '';
                    $cfg['auth']       = isset( $data['auth'] ) ? (bool) $data['auth'] : ( '' !== $cfg['user'] );
                    $cfg['from_email'] = isset( $data['from_email'] ) ? sanitize_email( $data['from_email'] ) : '';
                    $cfg['from_name']  = isset( $data['from_name'] ) ? sanitize_text_field( $data['from_name'] ) : '';
                    $this->config = $cfg;
                    return $cfg;
                }
            }
        }

        // 4. WordPress Database Option
        $opt = get_option( 'leanstack_smtp_settings' );
        if ( is_array( $opt ) && ! empty( $opt['host'] ) ) {
            $cfg['enabled']    = ! empty( $opt['enabled'] );
            $cfg['source']     = 'option';
            $cfg['host']       = sanitize_text_field( $opt['host'] );
            $cfg['port']       = isset( $opt['port'] ) ? (int) $opt['port'] : 587;
            $cfg['encryption'] = isset( $opt['encryption'] ) ? sanitize_key( $opt['encryption'] ) : 'tls';
            $cfg['user']       = isset( $opt['user'] ) ? sanitize_text_field( $opt['user'] ) : '';
            $cfg['pass']       = isset( $opt['pass'] ) ? (string) $opt['pass'] : '';
            $cfg['auth']       = isset( $opt['auth'] ) ? (bool) $opt['auth'] : ( '' !== $cfg['user'] );
            $cfg['from_email'] = isset( $opt['from_email'] ) ? sanitize_email( $opt['from_email'] ) : '';
            $cfg['from_name']  = isset( $opt['from_name'] ) ? sanitize_text_field( $opt['from_name'] ) : '';
            $this->config = $cfg;
            return $cfg;
        }

        $this->config = $cfg;
        return $cfg;
    }

    /**
     * In-process socket configuration for PHPMailer.
     * Zero daemon overhead, zero fork/exec.
     */
    public function configure_phpmailer( $phpmailer ) {
        $cfg = $this->get_config();
        if ( empty( $cfg['enabled'] ) || empty( $cfg['host'] ) ) {
            return;
        }

        $phpmailer->isSMTP();
        $phpmailer->Host       = $cfg['host'];
        $phpmailer->Port       = (int) $cfg['port'];
        $phpmailer->SMTPAuth   = ! empty( $cfg['auth'] );

        if ( $phpmailer->SMTPAuth ) {
            $phpmailer->Username = $cfg['user'];
            $phpmailer->Password = $cfg['pass'];
        }

        if ( 'ssl' === $cfg['encryption'] ) {
            $phpmailer->SMTPSecure = 'ssl';
        } elseif ( 'tls' === $cfg['encryption'] ) {
            $phpmailer->SMTPSecure = 'tls';
        } else {
            $phpmailer->SMTPSecure = '';
            $phpmailer->SMTPAutoTLS = false;
        }

        $from_email = ! empty( $cfg['from_email'] ) ? $cfg['from_email'] : get_option( 'admin_email' );
        if ( ! empty( $from_email ) && is_email( $from_email ) ) {
            $from_name = ! empty( $cfg['from_name'] ) ? $cfg['from_name'] : get_bloginfo( 'name' );
            $phpmailer->setFrom( $from_email, $from_name );
        }
    }

    /**
     * Traps and logs delivery failures with actionable details.
     */
    public function log_mail_failure( $wp_error ) {
        if ( is_wp_error( $wp_error ) ) {
            $msg = $wp_error->get_error_message();
            if ( false !== strpos( $msg, 'Connection refused' ) || false !== strpos( $msg, 'connect() failed' ) ) {
                $msg .= ' ' . __( '(Outbound mail port blocked or external SMTP not configured. Configure authenticated SMTP in Tools > LeanStack Cache > SMTP.)', 'leanstack' );
            }
            set_transient( 'leanstack_last_mail_error', $msg, 3600 );

            $home_dir = dirname( ABSPATH );
            $mail_log = $home_dir . '/logs/mail.log';
            if ( is_dir( $home_dir . '/logs' ) ) {
                $entry = sprintf( "[%s] FAILED: %s\n", current_time( 'mysql' ), $msg );
                @file_put_contents( $mail_log, $entry, FILE_APPEND );
            }
        }
    }

    /**
     * Logs successful email dispatches to logs/mail.log.
     */
    public function log_mail_success( $mail_data ) {
        $home_dir = dirname( ABSPATH );
        $mail_log = $home_dir . '/logs/mail.log';
        if ( is_dir( $home_dir . '/logs' ) ) {
            $to = isset( $mail_data['to'] ) ? ( is_array( $mail_data['to'] ) ? implode( ', ', $mail_data['to'] ) : $mail_data['to'] ) : 'unknown';
            $subj = isset( $mail_data['subject'] ) ? $mail_data['subject'] : '';
            $entry = sprintf( "[%s] SENT: To: %s | Subject: %s\n", current_time( 'mysql' ), $to, $subj );
            @file_put_contents( $mail_log, $entry, FILE_APPEND );
        }
    }

    /**
     * Synchronizes tenant credentials with OS msmtp relay configuration (/home/{user}/.msmtprc)
     * Enforces strict 0600 permissions as required by msmtp security policy.
     *
     * @param array|null $cfg
     * @return bool
     */
    public function sync_msmtprc( $cfg = null ) {
        if ( null === $cfg ) {
            $cfg = $this->get_config();
        }

        $home_dir = dirname( ABSPATH );
        $msmtprc = $home_dir . '/.msmtprc';
        $log_dir = $home_dir . '/logs';

        if ( ! is_dir( $home_dir ) || ( ! is_writable( $home_dir ) && ! file_exists( $msmtprc ) ) ) {
            return false;
        }

        $is_custom_smtp = ( ! empty( $cfg['enabled'] ) && ! empty( $cfg['host'] ) );
        $host     = $is_custom_smtp ? $cfg['host'] : '127.0.0.1';
        $port     = $is_custom_smtp ? (int) $cfg['port'] : 25;
        $user     = $is_custom_smtp ? ( ! empty( $cfg['user'] ) ? $cfg['user'] : 'none' ) : 'none';
        $pass     = $is_custom_smtp ? ( ! empty( $cfg['pass'] ) ? $cfg['pass'] : 'none' ) : 'none';
        $from     = ! empty( $cfg['from_email'] ) ? $cfg['from_email'] : get_option( 'admin_email' );
        $auth     = $is_custom_smtp ? ( ! empty( $cfg['auth'] ) ? 'on' : 'off' ) : 'off';
        $tls_mode = $is_custom_smtp ? ( ( 'ssl' === $cfg['encryption'] || 'tls' === $cfg['encryption'] ) ? 'on' : 'off' ) : 'off';
        $tls_starttls = $is_custom_smtp ? ( ( 'tls' === $cfg['encryption'] ) ? 'on' : 'off' ) : 'off';

        $msmtp_content  = "# LeanStack Lightweight OS Mail Relay Configuration (msmtp)\n";
        $msmtp_content .= "# Strict permissions enforced: chmod 600\n";
        $msmtp_content .= "defaults\n";
        $msmtp_content .= "auth           " . $auth . "\n";
        $msmtp_content .= "tls            " . $tls_mode . "\n";
        if ( 'on' === $tls_mode ) {
            $msmtp_content .= "tls_starttls   " . $tls_starttls . "\n";
            $msmtp_content .= "tls_trust_file /etc/ssl/certs/ca-certificates.crt\n";
        }
        if ( is_dir( $log_dir ) ) {
            $msmtp_content .= "logfile        " . $log_dir . "/msmtp.log\n";
        }
        $msmtp_content .= "\n";
        $msmtp_content .= "account        default\n";
        $msmtp_content .= "host           " . $host . "\n";
        $msmtp_content .= "port           " . $port . "\n";
        $msmtp_content .= "from           " . $from . "\n";
        if ( 'on' === $auth ) {
            $msmtp_content .= "user           " . $user . "\n";
            $msmtp_content .= "password       " . $pass . "\n";
        }

        $res = @file_put_contents( $msmtprc, $msmtp_content );
        if ( false !== $res ) {
            @chmod( $msmtprc, 0600 );
            return true;
        }
        return false;
    }
}

add_action( 'plugins_loaded', array( 'LeanStackSMTP', 'get_instance' ), 1 );

if ( ! function_exists( 'leanstack_get_smtp_config' ) ) {
    function leanstack_get_smtp_config() {
        return LeanStackSMTP::get_instance()->get_config();
    }
}

if ( ! function_exists( 'leanstack_sync_msmtprc' ) ) {
    function leanstack_sync_msmtprc( $cfg = null ) {
        return LeanStackSMTP::get_instance()->sync_msmtprc( $cfg );
    }
}
