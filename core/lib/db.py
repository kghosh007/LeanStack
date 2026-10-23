#!/usr/bin/env python3
"""
LeanStack Database Helper (core/lib/db.py)
Unified, parameterized SQLite interface for LeanStack control plane operations.
Eliminates bash SQL concatenation and SQL injection vectors (LS-20).
"""

from __future__ import annotations
import sys
import os
import sqlite3
import json
from typing import List, Any, Optional


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def execute(db_path: str, sql: str, params: List[Any] = None) -> int:
    conn = get_connection(db_path)
    cur = conn.cursor()
    try:
        if params:
            cur.execute(sql, params)
        else:
            for stmt in sql.strip().split(";"):
                if stmt.strip():
                    cur.execute(stmt)
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def query(db_path: str, sql: str, params: List[Any] = None) -> List[sqlite3.Row]:
    conn = get_connection(db_path)
    cur = conn.cursor()
    try:
        if params:
            cur.execute(sql, params)
        else:
            cur.execute(sql)
        return cur.fetchall()
    finally:
        conn.close()


def site_info(db_path: str, domain: str, json_mode: bool = False, show_credentials: bool = False) -> int:
    if not os.path.exists(db_path):
        if json_mode:
            print(json.dumps({"error": "Database not initialized"}, indent=2))
        else:
            print("ERROR: Database not initialized.", file=sys.stderr)
        return 1

    conn = get_connection(db_path)
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM sites WHERE domain = ?", (domain,))
        row = cur.fetchone()
        if not row:
            if json_mode:
                print(json.dumps({"error": "Site not found"}, indent=2))
            else:
                print(f"ERROR: Site '{domain}' not found.", file=sys.stderr)
            return 1

        d = dict(row)
        # Redact secrets strictly by default (LS-07), reveal only when explicitly requested
        if not show_credentials:
            if "db_pass" in d:
                d["db_pass"] = "[REDACTED]"
            if "admin_pass" in d:
                d["admin_pass"] = "[REDACTED]"

        if json_mode:
            print(json.dumps(d, indent=2))
        else:
            print("==========================================================")
            print(f"Domain:          https://{d.get('domain', '')}")
            print(f"Tenant User:     {d.get('user', '')}")
            print(f"PHP Version:     {d.get('php_version', '')} ({d.get('pool_mode', '')}, {d.get('memory_limit', '')})")
            print(f"Profile Used:    {d.get('profile_used', '')}")
            print(f"Site Root:       {d.get('site_path', '')}")
            print(f"Database:        {d.get('db_name', '')} (User: {d.get('db_user', '')})")
            print(f"DB Pass:         {d.get('db_pass', '[REDACTED]')}")
            print(f"Table Prefix:    {d.get('table_prefix', '')}")
            print(f"Cache Prefix:    {d.get('cache_prefix', '')}")
            print(f"Admin Email:     {d.get('admin_email', '')}")
            print(f"Admin User:      {d.get('admin_user', '')}")
            if show_credentials:
                print(f"Admin Pass:      {d.get('admin_pass', '')}")
            print(f"Cloudflare:      {'Enabled' if d.get('is_cf') else 'Disabled'}")
            print(f"Created At:      {d.get('created_at', '')}")
            if not show_credentials:
                print("Tip: Use --show-credentials to reveal DB and WordPress admin passwords.")
            print("==========================================================")
        return 0
    finally:
        conn.close()


def cron_sites(db_path: str, domain_filter: Optional[str] = None) -> int:
    if not os.path.exists(db_path):
        return 0

    conn = get_connection(db_path)
    cur = conn.cursor()
    try:
        if domain_filter:
            cur.execute("SELECT domain, user, site_path, php_version FROM sites WHERE domain = ?", (domain_filter,))
        else:
            cur.execute("SELECT domain, user, site_path, php_version FROM sites")
        for r in cur.fetchall():
            print(f"{r['domain']}|{r['user']}|{r['site_path']}|{r['php_version']}")
        return 0
    finally:
        conn.close()


def main():
    if len(sys.argv) < 3:
        print("Usage: db.py <exec|query|query-json|site-info|cron-sites> <db_path> [args...]", file=sys.stderr)
        sys.exit(1)

    cmd = sys.argv[1]
    db_path = sys.argv[2]

    if cmd == "exec":
        sql = sys.argv[3] if len(sys.argv) > 3 else ""
        params = sys.argv[4:] if len(sys.argv) > 4 else None
        execute(db_path, sql, params)
        sys.exit(0)

    elif cmd == "query":
        sql = sys.argv[3] if len(sys.argv) > 3 else ""
        params = sys.argv[4:] if len(sys.argv) > 4 else None
        rows = query(db_path, sql, params)
        for r in rows:
            print("|".join(str(x) if x is not None else "" for x in tuple(r)))
        sys.exit(0)

    elif cmd == "query-json":
        sql = sys.argv[3] if len(sys.argv) > 3 else ""
        params = sys.argv[4:] if len(sys.argv) > 4 else None
        rows = query(db_path, sql, params)
        print(json.dumps([dict(r) for r in rows], indent=2))
        sys.exit(0)

    elif cmd == "site-info":
        domain = sys.argv[3] if len(sys.argv) > 3 else ""
        args = sys.argv[4:]
        json_mode = "--json" in args or (len(args) > 0 and args[0] == "1")
        show_creds = "--show-credentials" in args or "--show-passwords" in args or "--reveal" in args or (len(args) > 1 and args[1] == "1")
        code = site_info(db_path, domain, json_mode, show_creds)
        sys.exit(code)

    elif cmd == "cron-sites":
        domain_filter = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] else None
        code = cron_sites(db_path, domain_filter)
        sys.exit(code)

    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
