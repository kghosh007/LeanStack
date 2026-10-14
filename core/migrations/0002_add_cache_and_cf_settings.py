#!/usr/bin/env python3
"""
LeanStack Migration 0002: Add Cache and Cloudflare Configuration Columns
"""

def migrate(conn):
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(sites)")
    existing_cols = [row[1] for row in cur.fetchall()]

    if "cache_enabled" not in existing_cols:
        cur.execute("ALTER TABLE sites ADD COLUMN cache_enabled INTEGER DEFAULT 1")

    if "cache_ttl" not in existing_cols:
        cur.execute("ALTER TABLE sites ADD COLUMN cache_ttl TEXT DEFAULT '3600s'")

    if "cf_zone_id" not in existing_cols:
        cur.execute("ALTER TABLE sites ADD COLUMN cf_zone_id TEXT DEFAULT ''")

    conn.commit()
