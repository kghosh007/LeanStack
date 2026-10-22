#!/usr/bin/env python3
"""
LeanStack Migration 0003: Add Cache Prefix Column
"""

import os
import re

def migrate(conn):
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(sites)")
    existing_cols = [row[1] for row in cur.fetchall()]

    if "cache_prefix" not in existing_cols:
        cur.execute("ALTER TABLE sites ADD COLUMN cache_prefix TEXT DEFAULT ''")

    # Backfill existing rows if cache_prefix is empty
    cur.execute("SELECT id, user, site_path FROM sites WHERE cache_prefix IS NULL OR cache_prefix = ''")
    rows = cur.fetchall()
    for row_id, user, site_path in rows:
        prefix = f"ls_{user}_"
        if site_path and os.path.isdir(site_path):
            wp_config = os.path.join(site_path, "wp-config.php")
            if not os.path.isfile(wp_config):
                wp_config = os.path.join(os.path.dirname(site_path), "wp-config.php")
            if os.path.isfile(wp_config):
                try:
                    with open(wp_config, "r", encoding="utf-8", errors="ignore") as f:
                        text = f.read()
                    m = re.search(r"define\s*\(\s*['\"](?:WP_REDIS_PREFIX|WP_CACHE_KEY_SALT)['\"]\s*,\s*['\"]([^'\"]+)['\"]", text)
                    if m and re.fullmatch(r"[A-Za-z0-9_.:-]{3,64}", m.group(1)):
                        prefix = m.group(1)
                except Exception:
                    pass
        cur.execute("UPDATE sites SET cache_prefix = ? WHERE id = ?", (prefix, row_id))

    conn.commit()
