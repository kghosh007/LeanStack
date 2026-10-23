<?php
/**
 * Plugin Name: LeanStack APCu Application Accelerator
 * Description: In-process RAM caching for transients, options, and dynamic fragments without object-cache.php collision.
 * Version: 1.0.0
 * Author: LeanStack
 */

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

class LeanStackAPCu {

    private static $instance = null;
    private $enabled = false;
    private $prefix = '';
    private $cron_checked = false;
    private $loaded_from_apcu = false;

    public static function get_instance() {
        if ( null === self::$instance ) {
            self::$instance = new self();
        }
        return self::$instance;
    }

    private function __construct() {
        $this->enabled = ( function_exists( 'apcu_enabled' ) && apcu_enabled() )
            || ( extension_loaded( 'apcu' ) && ( 'cli' !== PHP_SAPI || ini_get( 'apc.enable_cli' ) ) );
        if ( ! $this->enabled ) {
            return;
        }

        // Cryptographically unique tenant namespace (matching LeanStackBridge and test suite)
        $salt = ( defined( 'AUTH_SALT' ) && '' !== AUTH_SALT ) ? AUTH_SALT : 'leanstack';
        $db = ( defined( 'DB_NAME' ) && '' !== DB_NAME ) ? DB_NAME : 'leanstack';
        $this->prefix = 'ls_' . md5( $salt . $db ) . ':';

        // 1. Hook into Transients for sub-3µs in-memory reads
        $this->register_cached_transient_hooks();
        add_action( 'set_transient', array( $this, 'set_transient' ), 10, 3 );
        add_action( 'set_site_transient', array( $this, 'set_site_transient' ), 10, 3 );
        add_action( 'deleted_transient', array( $this, 'delete_transient' ), 10, 1 );
        add_action( 'deleted_site_transient', array( $this, 'delete_site_transient' ), 10, 1 );

        // 2. Fast Option Acceleration for alloptions
        add_filter( 'pre_wp_load_alloptions', array( $this, 'get_alloptions' ), 10, 2 );
        add_filter( 'pre_cache_alloptions', array( $this, 'get_alloptions' ) );
        add_filter( 'pre_option_alloptions', array( $this, 'get_alloptions' ) );
        add_filter( 'alloptions', array( $this, 'cache_alloptions' ) );
        add_action( 'updated_option', array( $this, 'invalidate_alloptions' ) );
        add_action( 'added_option', array( $this, 'invalidate_alloptions' ) );
        add_action( 'deleted_option', array( $this, 'invalidate_alloptions' ) );
        add_action( 'update_option_alloptions', array( $this, 'invalidate_alloptions' ) );
    }

    public function is_enabled() {
        return $this->enabled;
    }

    public function get_prefix() {
        return $this->prefix;
    }

    private function key( $group, $key ) {
        return $this->prefix . $group . ':' . $key;
    }

    // --- Dynamic Transients Interception & Indexing ---
    private function get_indexed_transients() {
        if ( ! $this->enabled ) {
            return array( 'tr' => array(), 'site_tr' => array() );
        }
        $success = false;
        $keys = apcu_fetch( $this->key( 'meta', 'transient_index' ), $success );
        return ( $success && is_array( $keys ) ) ? $keys : array( 'tr' => array(), 'site_tr' => array() );
    }

    private function add_indexed_transient( $type, $transient, $ttl ) {
        if ( ! $this->enabled ) {
            return;
        }
        $keys = $this->get_indexed_transients();
        $keys[ $type ][ $transient ] = time() + (int) $ttl;
        // Keep max 200 hot transients in index to maintain lean memory footprint
        if ( count( $keys[ $type ] ) > 200 ) {
            $keys[ $type ] = array_slice( $keys[ $type ], -200, 200, true );
        }
        apcu_store( $this->key( 'meta', 'transient_index' ), $keys, 86400 );
    }

    private function remove_indexed_transient( $type, $transient ) {
        if ( ! $this->enabled ) {
            return;
        }
        $keys = $this->get_indexed_transients();
        if ( isset( $keys[ $type ][ $transient ] ) ) {
            unset( $keys[ $type ][ $transient ] );
            apcu_store( $this->key( 'meta', 'transient_index' ), $keys, 86400 );
        }
    }

    private function register_cached_transient_hooks() {
        $keys = $this->get_indexed_transients();
        if ( ! empty( $keys['tr'] ) && is_array( $keys['tr'] ) ) {
            foreach ( array_keys( $keys['tr'] ) as $tr ) {
                add_filter( 'pre_transient_' . $tr, array( $this, 'handle_pre_transient' ), 10, 2 );
            }
        }
        if ( ! empty( $keys['site_tr'] ) && is_array( $keys['site_tr'] ) ) {
            foreach ( array_keys( $keys['site_tr'] ) as $tr ) {
                add_filter( 'pre_site_transient_' . $tr, array( $this, 'handle_pre_site_transient' ), 10, 2 );
            }
        }
    }

    public function handle_pre_transient( $pre, $transient = '' ) {
        if ( false !== $pre || ! $this->enabled ) {
            return $pre;
        }
        if ( empty( $transient ) && function_exists( 'current_filter' ) ) {
            $current_filter = current_filter();
            if ( 0 === strpos( $current_filter, 'pre_transient_' ) ) {
                $transient = substr( $current_filter, strlen( 'pre_transient_' ) );
            }
        }
        if ( empty( $transient ) ) {
            return $pre;
        }
        $success = false;
        $val = apcu_fetch( $this->key( 'tr', $transient ), $success );
        if ( $success ) {
            return $val;
        }
        $this->remove_indexed_transient( 'tr', $transient );
        return $pre;
    }

    public function handle_pre_site_transient( $pre, $transient = '' ) {
        if ( false !== $pre || ! $this->enabled ) {
            return $pre;
        }
        if ( empty( $transient ) && function_exists( 'current_filter' ) ) {
            $current_filter = current_filter();
            if ( 0 === strpos( $current_filter, 'pre_site_transient_' ) ) {
                $transient = substr( $current_filter, strlen( 'pre_site_transient_' ) );
            }
        }
        if ( empty( $transient ) ) {
            return $pre;
        }
        $success = false;
        $val = apcu_fetch( $this->key( 'site_tr', $transient ), $success );
        if ( $success ) {
            return $val;
        }
        $this->remove_indexed_transient( 'site_tr', $transient );
        return $pre;
    }

    public function get_transient( $pre, $transient = '' ) {
        return $this->handle_pre_transient( $pre, $transient );
    }

    public function set_transient( $transient, $value, $expiration ) {
        if ( ! $this->enabled ) {
            return;
        }
        $ttl = (int) $expiration > 0 ? (int) $expiration : 86400;
        apcu_store( $this->key( 'tr', $transient ), $value, $ttl );
        $this->add_indexed_transient( 'tr', $transient, $ttl );
        add_filter( 'pre_transient_' . $transient, array( $this, 'handle_pre_transient' ), 10, 2 );
    }

    public function set_site_transient( $transient, $value, $expiration ) {
        if ( ! $this->enabled ) {
            return;
        }
        $ttl = (int) $expiration > 0 ? (int) $expiration : 86400;
        apcu_store( $this->key( 'site_tr', $transient ), $value, $ttl );
        $this->add_indexed_transient( 'site_tr', $transient, $ttl );
        add_filter( 'pre_site_transient_' . $transient, array( $this, 'handle_pre_site_transient' ), 10, 2 );
    }

    public function delete_transient( $transient ) {
        if ( ! $this->enabled ) {
            return;
        }
        apcu_delete( $this->key( 'tr', $transient ) );
        $this->remove_indexed_transient( 'tr', $transient );
    }

    public function delete_site_transient( $transient ) {
        if ( ! $this->enabled ) {
            return;
        }
        apcu_delete( $this->key( 'site_tr', $transient ) );
        $this->remove_indexed_transient( 'site_tr', $transient );
    }

    // --- Alloptions Interception ---
    public function check_cron_status_invalidation() {
        if ( ! $this->enabled || $this->cron_checked ) {
            return;
        }
        $this->cron_checked = true;
        $status_files = array();
        if ( defined( 'ABSPATH' ) ) {
            $doc_root = rtrim( ABSPATH, '/' );
            $status_files[] = dirname( $doc_root ) . '/nginx/.cron_status.json';
        }
        if ( defined( 'WP_CONTENT_DIR' ) ) {
            $status_files[] = WP_CONTENT_DIR . '/nginx-custom/.cron_status.json';
        }
        foreach ( $status_files as $sf ) {
            if ( file_exists( $sf ) ) {
                clearstatcache( true, $sf );
                $mtime = filemtime( $sf );
                $last_mtime_key = $this->key( 'meta', 'cron_mtime' );
                $success = false;
                $prev_mtime = apcu_fetch( $last_mtime_key, $success );
                if ( ! $success || (int) $mtime > (int) $prev_mtime ) {
                    apcu_store( $last_mtime_key, (int) $mtime, 86400 );
                    if ( $success ) {
                        // Background runner updated crons; invalidate alloptions immediately
                        $this->invalidate_alloptions();
                    }
                }
                break;
            }
        }
    }

    public function get_alloptions( $pre = null, $force_cache = false ) {
        if ( ! $this->enabled || $force_cache ) {
            return $pre;
        }
        $this->check_cron_status_invalidation();
        $success = false;
        $val = apcu_fetch( $this->key( 'opt', 'alloptions' ), $success );
        if ( $success && is_array( $val ) && ! empty( $val ) ) {
            $this->loaded_from_apcu = true;
            return $val;
        }
        $this->loaded_from_apcu = false;
        return $pre;
    }

    public function cache_alloptions( $alloptions ) {
        if ( ! $this->enabled || ! is_array( $alloptions ) || empty( $alloptions ) ) {
            return $alloptions;
        }
        // Only store into APCu if this request did NOT already load alloptions from APCu,
        // preventing costly write-lock thrashing and re-serialization on every get_option() call.
        if ( $this->loaded_from_apcu ) {
            return $alloptions;
        }
        $cached_options = $alloptions;
        // Strictly exclude volatile 'cron' option so get_option('cron') never reads stale data from APCu
        unset( $cached_options['cron'] );
        apcu_store( $this->key( 'opt', 'alloptions' ), $cached_options, 3600 );
        $this->loaded_from_apcu = true;
        return $alloptions;
    }

    public function invalidate_alloptions() {
        $this->loaded_from_apcu = false;
        if ( ! $this->enabled ) {
            return;
        }
        apcu_delete( $this->key( 'opt', 'alloptions' ) );
    }

    // --- Public API for Fragments & Query Loops ---
    public function get_fragment( $id ) {
        if ( ! $this->enabled ) {
            return false;
        }
        $success = false;
        $val = apcu_fetch( $this->key( 'frag', $id ), $success );
        return $success ? $val : false;
    }

    public function set_fragment( $id, $content, $ttl = 60 ) {
        if ( ! $this->enabled ) {
            return false;
        }
        return apcu_store( $this->key( 'frag', $id ), $content, (int) $ttl );
    }

    public function flush_tenant_cache() {
        if ( ! $this->enabled ) {
            return 0;
        }
        $count = 0;
        if ( class_exists( 'APCUIterator' ) ) {
            try {
                $iter = new APCUIterator( '/^' . preg_quote( $this->prefix, '/' ) . '/' );
                $keys_to_delete = array();
                foreach ( $iter as $item ) {
                    if ( isset( $item['key'] ) ) {
                        $keys_to_delete[] = $item['key'];
                    }
                }
                foreach ( $keys_to_delete as $k ) {
                    if ( apcu_delete( $k ) ) {
                        $count++;
                    }
                }
            } catch ( Throwable $e ) {
                // Fall back to cache_info below
            }
        }
        if ( 0 === $count && function_exists( 'apcu_cache_info' ) ) {
            try {
                $cinfo = @apcu_cache_info();
                if ( ! empty( $cinfo['cache_list'] ) && is_array( $cinfo['cache_list'] ) ) {
                    $keys_to_delete = array();
                    foreach ( $cinfo['cache_list'] as $entry ) {
                        $k = isset( $entry['info'] ) ? $entry['info'] : ( isset( $entry['key'] ) ? $entry['key'] : '' );
                        if ( 0 === strpos( $k, $this->prefix ) ) {
                            $keys_to_delete[] = $k;
                        }
                    }
                    foreach ( $keys_to_delete as $k ) {
                        if ( apcu_delete( $k ) ) {
                            $count++;
                        }
                    }
                }
            } catch ( Throwable $e ) {
                // Ignore
            }
        }
        return $count;
    }

    public function get_stats() {
        if ( ! $this->enabled ) {
            return array( 'enabled' => false );
        }
        $info = function_exists( 'apcu_sma_info' ) ? apcu_sma_info( true ) : array();
        $cache = function_exists( 'apcu_cache_info' ) ? apcu_cache_info( true ) : array();
        return array(
            'enabled'    => true,
            'num_slots'  => isset( $cache['num_slots'] ) ? $cache['num_slots'] : 0,
            'num_hits'   => isset( $cache['num_hits'] ) ? $cache['num_hits'] : 0,
            'num_misses' => isset( $cache['num_misses'] ) ? $cache['num_misses'] : 0,
            'mem_used'   => isset( $info['seg_size'], $info['avail_mem'] ) ? ( $info['seg_size'] - $info['avail_mem'] ) : 0,
            'mem_avail'  => isset( $info['avail_mem'] ) ? $info['avail_mem'] : 0,
        );
    }
}

// Immediate early bootstrap for MU-Plugin lifecycle
LeanStackAPCu::get_instance();
add_action( 'plugins_loaded', array( 'LeanStackAPCu', 'get_instance' ), 1 );

// Global helper functions
function leanstack_apcu_get( $id ) {
    return LeanStackAPCu::get_instance()->get_fragment( $id );
}

function leanstack_apcu_set( $id, $content, $ttl = 60 ) {
    return LeanStackAPCu::get_instance()->set_fragment( $id, $content, $ttl );
}
