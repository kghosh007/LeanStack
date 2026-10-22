-- ==============================================================================
-- LeanStack Migration 0001: Initial Sites Schema
-- ==============================================================================

CREATE TABLE IF NOT EXISTS sites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT UNIQUE NOT NULL,
    user TEXT NOT NULL,
    php_version TEXT NOT NULL,
    pool_type TEXT NOT NULL,
    pool_mode TEXT DEFAULT 'dynamic',
    memory_limit TEXT DEFAULT '256M',
    table_prefix TEXT DEFAULT 'wp_',
    is_cf INTEGER DEFAULT 0,
    profile_used TEXT DEFAULT 'default',
    site_path TEXT NOT NULL,
    db_name TEXT NOT NULL,
    db_user TEXT NOT NULL,
    db_pass TEXT NOT NULL,
    admin_user TEXT NOT NULL,
    admin_pass TEXT NOT NULL,
    admin_email TEXT NOT NULL,
    wp_version TEXT DEFAULT 'latest',
    cache_prefix TEXT DEFAULT '',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
