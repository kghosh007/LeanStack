#!/usr/bin/env python3
"""
LeanStack Selective Tenant Database Restore Tool
Restores tenant application databases from full pre-upgrade backups
while strictly preserving clean, native MariaDB 12.3 system catalogs.
"""

import os
import sys
import glob
import gzip
import sqlite3
import subprocess

def log(msg, prefix="  ℹ"):
    print(f"{prefix} {msg}")

def main():
    print("\n==============================================================================")
    print("            LEANSTACK SELECTIVE TENANT DATABASE RESTORER                      ")
    print("==============================================================================\n")

    # 1. Locate latest backup
    backup_candidates = [
        "/var/backups/lsctl/stack_upgrades/mariadb_all_databases_*.sql.gz",
        "/var/backups/lsctl/pre_upgrade_*.sql.gz",
        "/var/backups/lsctl/stack_upgrades/*.sql.gz",
        "/var/backups/lsctl/*.sql.gz",
    ]
    dumps = []
    for pat in backup_candidates:
        dumps.extend(glob.glob(pat))
    dumps = sorted(list(set(dumps)), key=os.path.getmtime, reverse=True)

    if not dumps:
        print("❌ Error: No pre-upgrade database backup found in /var/backups/lsctl!")
        sys.exit(1)

    dump_path = dumps[0]
    log(f"Located pre-upgrade backup snapshot: {dump_path}", prefix="  📦")

    # 2. Query registered tenant databases from LeanStack SQLite database
    db_candidates = [
        os.environ.get("LEANSTACK_DB"),
        "/var/lib/lsctl/sites.db",
        "/var/lib/cpctl/sites.db",
    ]
    db_file = next((f for f in db_candidates if f and os.path.isfile(f)), None)
    if not db_file:
        print("❌ Error: sites.db database not found in /var/lib/lsctl/sites.db")
        sys.exit(1)

    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT domain, db_name, db_user, db_pass FROM sites;")
    sites = cur.fetchall()
    conn.close()

    if not sites:
        print("❌ Error: No tenant sites registered in sites.db")
        sys.exit(1)

    # 3. Recreate tenant databases and grants cleanly in MariaDB 12.3
    log(f"Registering schemas & credentials for {len(sites)} tenant site(s)...", prefix="  🔐")
    for s in sites:
        db = s["db_name"]
        u = s["db_user"]
        p = s["db_pass"]
        domain = s["domain"]
        if not db:
            continue

        sql = f"""
        CREATE DATABASE IF NOT EXISTS `{db}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_520_ci;
        CREATE USER IF NOT EXISTS '{u}'@'localhost' IDENTIFIED BY '{p}';
        ALTER USER '{u}'@'localhost' IDENTIFIED BY '{p}';
        GRANT ALL PRIVILEGES ON `{db}`.* TO '{u}'@'localhost';
        FLUSH PRIVILEGES;
        """
        res = subprocess.run(["mariadb", "-u", "root", "-e", sql], capture_output=True, text=True)
        if res.returncode != 0:
            log(f"Notice setting up {domain} ({db}): {res.stderr.strip()}", prefix="  ⚠️")
        else:
            log(f"Prepared database `{db}` and granted `{u}`@'localhost' for {domain}", prefix="  ✔")

    # 4. Stream and filter backup: include tenant databases, EXCLUDE 'mysql', 'information_schema', 'sys', 'performance_schema'
    log(f"Streaming application tables from backup (safely bypassing legacy system catalogs)...", prefix="  🔄")
    p_mariadb = subprocess.Popen(["mariadb", "-u", "root"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    in_excluded_db = False
    excluded_dbs = {"mysql", "information_schema", "performance_schema", "sys"}
    lines_streamed = 0

    opener = gzip.open if dump_path.endswith(".gz") else open
    with opener(dump_path, "rt", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if "Current Database:" in line or line.startswith("USE "):
                parts = line.strip().split()
                db_candidate = parts[-1].strip("`;")
                if db_candidate in excluded_dbs:
                    in_excluded_db = True
                else:
                    in_excluded_db = False

            if not in_excluded_db:
                p_mariadb.stdin.write(line)
                lines_streamed += 1

    stdout, stderr = p_mariadb.communicate()
    if p_mariadb.returncode != 0:
        log(f"Warning during SQL import: {stderr.strip()}", prefix="  ⚠️")
    else:
        log("Tenant application tables restored successfully into MariaDB 12.3!", prefix="  ✔")

    # 5. Verify WordPress tables
    print("\n------------------------------------------------------------------------------")
    print("                    TENANT CONNECTIVITY & HEALTH VERIFICATION                 ")
    print("------------------------------------------------------------------------------")
    for s in sites:
        db = s["db_name"]
        u = s["db_user"]
        p = s["db_pass"]
        domain = s["domain"]
        chk = subprocess.run(
            ["mariadb", f"-u{u}", f"-p{p}", db, "-e", "SHOW TABLES;"],
            capture_output=True, text=True
        )
        if chk.returncode == 0:
            tbl_count = len([t for t in chk.stdout.splitlines() if t and not t.startswith("Tables_in_")])
            log(f"[{domain}] Connection SUCCESS! Found {tbl_count} table(s) in `{db}`.", prefix="  ✅")
        else:
            log(f"[{domain}] Connection FAILED: {chk.stderr.strip()}", prefix="  ❌")

    print("\n==============================================================================")
    print("✔ RESTORE PROCEDURE COMPLETED.")
    print("==============================================================================\n")

if __name__ == "__main__":
    main()
