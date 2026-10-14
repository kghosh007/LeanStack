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

    public static function get_instance() {
        if ( null === self::$instance ) {
            self::$instance = new self();
        }
        return self::$instance;
    }

    private function __construct() {
        $this->enabled = function_exists( 'apcu_enabled' ) && apcu_enabled();
        if ( ! $this->enabled ) {
            return;
        }

        // Cryptographically unique tenant namespace
        $salt = defined( 'AUTH_SALT' ) ? AUTH_SALT : 'leanstack';
        $db = defined( 'DB_NAME' ) ? DB_NAME : 'wp';
        $this->prefix = 'ls_' . substr( md5( $salt . $db ), 0, 12 ) . ':';

        // 1. Hook into Transients for sub-3µs in-memory reads
        add_filter( 'pre_transient', array( $this, 'get_transient' ), 10, 2 );
        add_filter( 'pre_site_transient', array( $this, 'get_transient' ), 10, 2 );
        add_action( 'set_transient', array( $this, 'set_transient' ), 10, 3 );
        add_action( 'set_site_transient', array( $this, 'set_transient' ), 10, 3 );
        add_action( 'deleted_transient', array( $this, 'delete_transient' ), 10, 1 );
        add_action( 'deleted_site_transient', array( $this, 'delete_transient' ), 10, 1 );

        // 2. Fast Option Acceleration for alloptions
        add_filter( 'pre_option_alloptions', array( $this, 'get_alloptions' ) );
        add_action( 'updated_option', array( $this, 'invalidate_alloptions' ) );
        add_action( 'added_option', array( $this, 'invalidate_alloptions' ) );
        add_action( 'deleted_option', array( $this, 'invalidate_alloptions' ) );
    }

    public function is_enabled() {
        return $this->enabled;
    }

    private function key( $group, $key ) {
        return $this->prefix . $group . ':' . $key;
    }

    // --- Transients Interception ---
    public function get_transient( $pre, $transient ) {
        if ( ! $this->enabled ) {
            return false;
        }
        $success = false;
        $val = apcu_fetch( $this->key( 'tr', $transient ), $success );
        return $success ? $val : false;
    }

    public function set_transient( $transient, $value, $expiration ) {
        if ( ! $this->enabled ) {
            return;
        }
        $ttl = (int) $expiration > 0 ? (int) $expiration : 86400;
        apcu_store( $this->key( 'tr', $transient ), $value, $ttl );
    }

    public function delete_transient( $transient ) {
        if ( ! $this->enabled ) {
            return;
        }
        apcu_delete( $this->key( 'tr', $transient ) );
    }

    // --- Alloptions Interception ---
    public function get_alloptions( $pre ) {
        if ( ! $this->enabled ) {
            return false;
        }
        $success = false;
        $val = apcu_fetch( $this->key( 'opt', 'alloptions' ), $success );
        return $success ? $val : false;
    }

    public function invalidate_alloptions() {
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
        if ( ! $this->enabled || ! class_exists( 'APCUIterator' ) ) {
            return 0;
        }
        $iter = new APCUIterator( '/^' . preg_quote( $this->prefix, '/' ) . '/' );
        $count = 0;
        foreach ( $iter as $item ) {
            apcu_delete( $item['key'] );
            $count++;
        }
        return $count;
    }

    public function get_stats() {
        if ( ! $this->enabled ) {
            return array( 'enabled' => false );
        }
        $info = apcu_sma_info( true );
        $cache = apcu_cache_info( true );
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

add_action( 'plugins_loaded', array( 'LeanStackAPCu', 'get_instance' ), 1 );

// Global helper functions
function leanstack_apcu_get( $id ) {
    return LeanStackAPCu::get_instance()->get_fragment( $id );
}

function leanstack_apcu_set( $id, $content, $ttl = 60 ) {
    return LeanStackAPCu::get_instance()->set_fragment( $id, $content, $ttl );
}
