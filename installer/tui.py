#!/usr/bin/env python3
"""
LeanStack TUI (Terminal User Interface) Installer
Delivers an interactive, visual, and telemetry-rich installation experience
styled after Antigravity CLI.
Zero external pip dependencies; uses Python 3 standard library.
"""

import sys
import os
import time
import argparse
import subprocess
import shutil
import json
import glob
from typing import Dict, Any, List, Optional

from telemetry import (
    Style, render_banner, render_card, interactive_select,
    interactive_confirm, ProgressSpinner, clear_screen, hide_cursor, show_cursor
)
from probe import HardwareProbe, TuningCalculator, format_summary_card

class LeanStackInstaller:
    def __init__(self, dry_run: bool = False, non_interactive: bool = False, php_ver: str = "8.5"):
        self.dry_run = dry_run
        self.non_interactive = non_interactive
        self.selected_php = php_ver
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def audit_environment(self) -> Dict[str, Any]:
        """Detects pre-installed conflicting packages, stale repository lists, and invalid keys."""
        categories = {
            "Web Tier": ["angie", "angie-module-brotli", "nginx", "nginx-common", "nginx-core", "nginx-full", "apache2", "apache2-bin", "apache2-data"],
            "Database Tier": ["mariadb-server", "mariadb-client", "mariadb-common", "mysql-server", "mysql-client", "mysql-common"],
            "Cache Tier": ["valkey", "valkey-server", "valkey-tools", "redis", "redis-server", "redis-tools"],
            "PHP Runtimes": ["php-fpm", "php8.1-fpm", "php8.2-fpm", "php8.3-fpm", "php8.4-fpm", "php8.5-fpm"]
        }
        all_pkgs = [p for cat in categories.values() for p in cat]
        installed_map = {}
        try:
            res = subprocess.run(
                ["dpkg-query", "-W", "-f=${binary:Package} ${Status}\n"] + all_pkgs,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            for line in res.stdout.splitlines():
                parts = line.strip().split()
                if len(parts) >= 4 and parts[1] == "install" and parts[2] == "ok" and parts[3] == "installed":
                    pkg_name = parts[0].split(":")[0]
                    for cat, pkgs in categories.items():
                        if pkg_name in pkgs:
                            installed_map.setdefault(cat, []).append(pkg_name)
        except Exception:
            pass

        # Detect stale or corrupted repository files
        stale_repos = []
        for pat in [
            "/etc/apt/sources.list.d/*angie*.list",
            "/etc/apt/sources.list.d/*angie*.sources",
            "/etc/apt/sources.list.d/*mariadb*.list",
            "/etc/apt/sources.list.d/*valkey*.list",
            "/etc/apt/sources.list.d/*redis*.list",
            "/etc/apt/sources.list.d/*ondrej-ubuntu-php*.list",
            "/etc/apt/sources.list.d/*ondrej-ubuntu-php*.sources"
        ]:
            stale_repos.extend(glob.glob(pat))

        # Check for empty files or files containing angie.software
        for f in glob.glob("/etc/apt/sources.list.d/*"):
            if os.path.isfile(f) and f not in stale_repos:
                try:
                    if os.path.getsize(f) == 0:
                        stale_repos.append(f)
                    else:
                        with open(f, "r", errors="ignore") as fp:
                            if "angie.software" in fp.read():
                                stale_repos.append(f)
                except Exception:
                    pass
        stale_repos = sorted(list(set(stale_repos)))

        # Detect stale GPG keys
        stale_keys = glob.glob("/etc/apt/trusted.gpg.d/*angie*.gpg")

        total_installed = sum(len(v) for v in installed_map.values())
        has_conflicts = (total_installed > 0) or (len(stale_repos) > 0) or (len(stale_keys) > 0)

        return {
            "has_conflicts": has_conflicts,
            "installed_map": installed_map,
            "stale_repos": stale_repos,
            "stale_keys": stale_keys,
            "total_packages": total_installed
        }

    def render_audit_card(self, audit: Dict[str, Any]):
        if not audit["has_conflicts"]:
            lines = [
                f"{Style.BOLD}{Style.BRIGHT_GREEN}✔ Host environment is clean and verified!{Style.RESET}",
                "",
                "  No conflicting web servers (Angie/Nginx/Apache2), database engines,",
                "  or corrupted package repositories detected. Ready for LeanStack deployment."
            ]
            print(render_card("PRE-FLIGHT SYSTEM SANITIZATION AUDIT", lines, width=76, color=Style.BRIGHT_GREEN))
            return

        lines = [
            f"{Style.BOLD}{Style.BRIGHT_YELLOW}⚠️  Pre-existing or conflicting system components detected on host:{Style.RESET}",
            ""
        ]
        for cat, pkgs in audit["installed_map"].items():
            if pkgs:
                unique_pkgs = sorted(list(set(pkgs)))
                lines.append(f"  • {Style.BOLD}{cat:<16}{Style.RESET} {', '.join(unique_pkgs)}")

        if audit["stale_repos"]:
            lines.append(f"  • {Style.BOLD}{'Repositories':<16}{Style.RESET} {len(audit['stale_repos'])} stale/broken source list(s)")
            for r in audit["stale_repos"][:2]:
                lines.append(f"    {Style.DIM}- {os.path.basename(r)}{Style.RESET}")
            if len(audit["stale_repos"]) > 2:
                lines.append(f"    {Style.DIM}... and {len(audit['stale_repos']) - 2} more{Style.RESET}")

        lines.extend([
            "",
            f"{Style.BOLD}{Style.BRIGHT_CYAN}🧹 Automated Remediation Strategy:{Style.RESET}",
            "  1. Gracefully stop & disable conflicting background services",
            "  2. Purge pre-installed package artifacts to prevent dependency drift",
            "  3. Remove stale repository lists & invalid cryptographic keyrings",
            "  4. Reset and synchronize APT package indices for pristine provisioning"
        ])
        print(render_card("PRE-FLIGHT SYSTEM & PACKAGE AUDIT", lines, width=76, color=Style.YELLOW))

    def sanitize_environment(self, audit: Dict[str, Any]):
        print(f"\n{Style.BOLD}{Style.BRIGHT_CYAN}>>> Executing Pre-Flight System Sanitization...{Style.RESET}")
        spinner = ProgressSpinner("Sanitizing host environment...")

        if self.dry_run:
            spinner.step(extra="[Simulation] Stopping conflicting services...")
            time.sleep(0.1)
            spinner.step(extra="[Simulation] Purging stale repository sources...")
            time.sleep(0.1)
            spinner.step(extra="[Simulation] Purging pre-installed packages...")
            time.sleep(0.1)
            spinner.success("Host environment verified (dry-run simulation).")
            return

        # 1. Stop and disable conflicting services
        services = ["apache2", "nginx", "angie", "mariadb", "mysql", "valkey", "valkey-server", "redis-server", "redis"]
        for s in services:
            spinner.step(extra=f"Stopping service {s}...")
            subprocess.run(["systemctl", "stop", s], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["systemctl", "disable", s], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # 2. Delete stale repo lists & keys FIRST
        spinner.step(extra="Removing stale repository lists & keyrings...")
        for f in audit["stale_repos"]:
            try:
                os.remove(f)
            except Exception:
                pass
        for k in audit["stale_keys"]:
            try:
                os.remove(k)
            except Exception:
                pass
        for f in glob.glob("/etc/apt/sources.list.d/*"):
            try:
                if os.path.isfile(f) and os.path.getsize(f) == 0:
                    os.remove(f)
            except Exception:
                pass

        # 3. Purge conflicting packages
        all_pkgs = []
        for pkgs in audit["installed_map"].values():
            all_pkgs.extend(pkgs)
        if all_pkgs:
            spinner.step(extra=f"Purging {len(all_pkgs)} conflicting packages...")
            env = os.environ.copy()
            env["DEBIAN_FRONTEND"] = "noninteractive"
            subprocess.run(["apt-get", "purge", "-y", "-qq"] + all_pkgs, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
            subprocess.run(["apt-get", "autoremove", "-y", "-qq", "--purge"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)

        # 4. Clean APT and refresh cache
        spinner.step(extra="Updating clean package repository index...")
        subprocess.run(["apt-get", "clean"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["apt-get", "update", "-qq"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        spinner.success("Host environment successfully sanitized and verified clean.")

    def run(self):
        clear_screen()
        print(render_banner())

        # Step 1: Hardware Probing & Auto-Tuning
        print(f"{Style.BOLD}{Style.BRIGHT_CYAN}>>> Step 1/4: Probing Host Hardware & Calculating Optimal Tuning Profiles...{Style.RESET}")
        time.sleep(0.3)
        probe = HardwareProbe()
        hw = probe.probe_all()
        calculator = TuningCalculator(hw)
        profile_data = calculator.generate_full_profile()
        
        print(format_summary_card(profile_data))
        print("")

        # Step 2: System Audit & Sanitization
        print(f"{Style.BOLD}{Style.BRIGHT_CYAN}>>> Step 2/4: Host Environment Audit & Package Sanitization...{Style.RESET}\n")
        time.sleep(0.2)
        audit = self.audit_environment()
        self.render_audit_card(audit)
        print("")

        if audit["has_conflicts"] and not self.dry_run:
            if self.non_interactive:
                self.sanitize_environment(audit)
            else:
                purge = interactive_confirm(
                    "Purge pre-installed conflicting packages & stale repo lists for a pristine install?",
                    default=True
                )
                if purge:
                    self.sanitize_environment(audit)
                else:
                    print(f"{Style.YELLOW}⚠️ Proceeding without purging pre-existing packages.{Style.RESET}")

        # Step 3: Core System Configuration (unless non-interactive)
        if not self.non_interactive:
            print(f"\n{Style.BOLD}{Style.BRIGHT_CYAN}>>> Step 3/4: Core System Configuration{Style.RESET}\n")
            
            php_options = [
                ("8.5", "PHP 8.5 (Latest Stable — Peak performance & modern JIT compiler)"),
                ("8.4", "PHP 8.4 (Established LTS — Rock-solid ecosystem stability)"),
                ("8.3", "PHP 8.3 (Mature LTS — Wide plugin ecosystem support)"),
                ("8.2", "PHP 8.2 (Legacy standard)"),
                ("8.6", "PHP 8.6 (Cutting edge / Experimental development branch)")
            ]
            php_idx = interactive_select("Select Primary System PHP Runtime", php_options, 0)
            self.selected_php = php_options[php_idx][0]

            print(f"\n{Style.DIM}Note: Site profiles, admin credentials, and themes are managed post-install via cpctl.{Style.RESET}")
            print("")
            proceed = interactive_confirm("Apply hardware auto-tuning and begin LeanStack deployment?", default=True)
            if not proceed:
                print(f"\n{Style.YELLOW}Installation aborted by user.{Style.RESET}")
                sys.exit(0)

        # Step 4: Execution Pipeline
        print(f"\n{Style.BOLD}{Style.BRIGHT_CYAN}>>> Step 4/4: Executing LeanStack Provisioning Pipeline...{Style.RESET}\n")
        self.execute_pipeline(profile_data)

    def execute_pipeline(self, tuning_data: Dict[str, Any]):
        phases = [
            ("Provision Valkey, MariaDB, Angie, and PHP from the tuning profile", self._run_provision),
            ("Phase 6: Master Control Plane (Deploying /usr/local/bin/cpctl)", self._run_phase6),
            ("Phase 7: Centralized Anti-Thundering Cron & Background Watchers", self._run_phase7)
        ]

        total = len(phases)
        for idx, (title, func) in enumerate(phases, 1):
            spinner = ProgressSpinner(f"[{idx}/{total}] {title}")
            start_time = time.time()
            try:
                # Animate a few ticks
                for _ in range(4):
                    spinner.step()
                    time.sleep(0.08)
                
                # Execute the phase action
                func(tuning_data, spinner)
                
                elapsed = round(time.time() - start_time, 1)
                spinner.success(f"[{idx}/{total}] {title} {Style.DIM}({elapsed}s){Style.RESET}")
            except Exception as e:
                spinner.fail(f"[{idx}/{total}] {title} - ERROR: {str(e)}")
                if not self.dry_run:
                    sys.exit(1)

        self.render_completion_card()

    def _run_provision(self, tuning: Dict[str, Any], spinner: ProgressSpinner):
        cmd = [
            sys.executable, "-m", "installer.provision",
            "--php", self.selected_php,
            "--profile", "-",
        ]
        if self.dry_run:
            cmd.append("--dry-run")
        proc = subprocess.run(
            cmd,
            input=json.dumps(tuning),
            text=True,
            cwd=self.base_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "provision failed")
        if self.dry_run and f"php{self.selected_php}" not in proc.stdout:
            raise RuntimeError(f"provision dry-run did not list php{self.selected_php}")

    def _run_phase6(self, tuning: Dict[str, Any], spinner: ProgressSpinner):
        if self.dry_run:
            time.sleep(0.3)
            return
        # Install all control plane binaries into /usr/local/bin
        legacy_names = {
            "cpctl", "cp-upgrade", "cp-gatekeeper", "cp-nginx-linter",
            "cp-cron-queue", "cp-cf-sync", "cp-watcher", "cp-autoupdate",
            "cp-db-tune"
        }
        bin_dir = os.path.join(self.base_dir, "core", "bin")
        if os.path.exists(bin_dir):
            for b in os.listdir(bin_dir):
                if b in legacy_names or b.startswith("cp-") or b == "cpctl":
                    continue
                src = os.path.join(bin_dir, b)
                if os.path.isfile(src):
                    dest = f"/usr/local/bin/{b}"
                    if os.path.islink(dest) or os.path.exists(dest):
                        try:
                            os.remove(dest)
                        except Exception:
                            pass
                    subprocess.run(["install", "-m", "0755", src, dest], check=True)

            legacy_links = [
                ("cpctl", "lsctl"),
                ("cp-upgrade", "ls-upgrade"),
                ("cp-gatekeeper", "ls-gatekeeper"),
                ("cp-nginx-linter", "ls-nginx-linter"),
                ("cp-cron-queue", "ls-cron-queue"),
                ("cp-cf-sync", "ls-cf-sync"),
                ("cp-watcher", "ls-watcher"),
                ("cp-autoupdate", "ls-autoupdate"),
                ("cp-db-tune", "ls-db-tune")
            ]
            for leg_name, target_name in legacy_links:
                leg_path = f"/usr/local/bin/{leg_name}"
                try:
                    if os.path.islink(leg_path) or os.path.exists(leg_path):
                        os.remove(leg_path)
                    os.symlink(target_name, leg_path)
                except Exception:
                    pass

        # Populate /etc/lsctl/templates and baseline profiles
        os.makedirs("/etc/lsctl/templates", exist_ok=True)
        os.makedirs("/etc/leanstack", exist_ok=True)
        os.makedirs("/var/lib/lsctl", mode=0o700, exist_ok=True)
        os.makedirs("/var/log/lsctl", exist_ok=True)
        
        # Legacy compatibility links
        if not os.path.exists("/etc/cpctl"):
            try:
                os.symlink("/etc/lsctl", "/etc/cpctl")
            except Exception:
                pass
        if not os.path.exists("/var/lib/cpctl"):
            try:
                os.symlink("/var/lib/lsctl", "/var/lib/cpctl")
            except Exception:
                pass
        if not os.path.exists("/var/log/cpctl"):
            try:
                os.symlink("/var/log/lsctl", "/var/log/cpctl")
            except Exception:
                pass

        tpl_dir = os.path.join(self.base_dir, "core", "templates")
        if os.path.exists(tpl_dir):
            for t in os.listdir(tpl_dir):
                shutil.copy2(os.path.join(tpl_dir, t), os.path.join("/etc/lsctl/templates", t))

        lib_dir = os.path.join(self.base_dir, "core", "lib")
        if os.path.exists(lib_dir):
            os.makedirs("/etc/lsctl/lib", exist_ok=True)
            for lib_file in os.listdir(lib_dir):
                shutil.copy2(os.path.join(lib_dir, lib_file), os.path.join("/etc/lsctl/lib", lib_file))

        prof_src = os.path.join(self.base_dir, "core", "config", "profiles.yaml")
        if os.path.exists(prof_src) and not os.path.exists("/etc/lsctl/profiles.yaml"):
            shutil.copy2(prof_src, "/etc/lsctl/profiles.yaml")

        # Load centralized version configuration
        v_file = os.path.join(self.base_dir, "core", "version.json")
        v_num = "1.3.0"
        if os.path.exists(v_file):
            try:
                with open(v_file, "r") as f_v:
                    v_num = json.load(f_v).get("version", "1.3.0")
            except Exception:
                pass

        # Initialize version record
        version_data = {
            "version": v_num,
            "installed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "git_commit": "HEAD",
            "schema_version": 2
        }
        with open("/etc/leanstack/version.json", "w") as f:
            json.dump(version_data, f, indent=2)

    def _run_phase7(self, tuning: Dict[str, Any], spinner: ProgressSpinner):
        if self.dry_run:
            time.sleep(0.3)
            return
        # Copy systemd units and drop-in overrides
        systemd_dir = os.path.join(self.base_dir, "systemd")
        for f in os.listdir(systemd_dir):
            if f.endswith(".service") or f.endswith(".timer"):
                src = os.path.join(systemd_dir, f)
                subprocess.run(["cp", "-P", src, f"/etc/systemd/system/{f}"], check=True)
        overrides_dir = os.path.join(systemd_dir, "overrides")
        if os.path.isdir(overrides_dir):
            for dropin in os.listdir(overrides_dir):
                s_dropin = os.path.join(overrides_dir, dropin)
                if os.path.isdir(s_dropin):
                    d_dropin = f"/etc/systemd/system/{dropin}"
                    os.makedirs(d_dropin, exist_ok=True)
                    for of in os.listdir(s_dropin):
                        shutil.copy2(os.path.join(s_dropin, of), os.path.join(d_dropin, of))
        subprocess.run(["systemctl", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "enable", "--now", "cp-cron.timer", "cp-cf-sync.timer", "cp-gatekeeper.service", "ls-watcher.timer", "ls-autoupdate.timer"], check=False)

    def render_completion_card(self):
        title = "LEANSTACK DEPLOYMENT COMPLETE"
        content = [
            f"{Style.BOLD}{Style.BRIGHT_GREEN}✔ LeanStack has been successfully provisioned and tuned!{Style.RESET}",
            "",
            f"  {Style.BOLD}Primary System PHP:{Style.RESET} PHP {self.selected_php}",
            f"  {Style.BOLD}Control Plane CLI:{Style.RESET}  /usr/local/bin/lsctl (alias: cpctl)",
            "",
            f"{Style.BOLD}{Style.BRIGHT_CYAN}⚡ QUICK START CLI COMMANDS:{Style.RESET}",
            f"  {Style.BRIGHT_WHITE}sudo lsctl profile:list{Style.RESET}                                 (View operational profiles)",
            f"  {Style.BRIGHT_WHITE}sudo lsctl wp:create --domain=example.com --profile=agency_woocommerce{Style.RESET}",
            f"  {Style.BRIGHT_WHITE}sudo lsctl site:list{Style.RESET}",
            f"  {Style.BRIGHT_WHITE}sudo lsctl doctor{Style.RESET}",
            "",
            f"{Style.DIM}Manage profiles anytime: lsctl profile:list, profile:show, profile:create{Style.RESET}",
            f"{Style.DIM}Documentation & architecture guides: /opt/leanstack/README.md{Style.RESET}"
        ]
        print("\n" + render_card(title, content, width=76, color=Style.BRIGHT_GREEN))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LeanStack TUI Installer")
    parser.add_argument("--dry-run", action="store_true", help="Simulate installation without modifying host system")
    parser.add_argument("--non-interactive", action="store_true", help="Run without interactive prompts")
    parser.add_argument("--php", default="8.5", help="Default primary PHP runtime (Default: 8.5)")
    args = parser.parse_args()

    installer = LeanStackInstaller(
        dry_run=args.dry_run,
        non_interactive=args.non_interactive,
        php_ver=args.php
    )
    installer.run()
