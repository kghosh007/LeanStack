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
from typing import Dict, Any

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

    def run(self):
        clear_screen()
        print(render_banner())

        # Step 1: Hardware Probing
        print(f"{Style.BOLD}{Style.BRIGHT_CYAN}>>> Step 1/3: Probing Host Hardware & Calculating Optimal Tuning Profiles...{Style.RESET}")
        time.sleep(0.3)
        probe = HardwareProbe()
        hw = probe.probe_all()
        calculator = TuningCalculator(hw)
        profile_data = calculator.generate_full_profile()
        
        print(format_summary_card(profile_data))
        print("")

        # Step 2: System Configuration (unless non-interactive)
        if not self.non_interactive:
            print(f"{Style.BOLD}{Style.BRIGHT_CYAN}>>> Step 2/3: Core System Configuration{Style.RESET}\n")
            
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

        # Step 3: Execution Pipeline
        print(f"\n{Style.BOLD}{Style.BRIGHT_CYAN}>>> Step 3/3: Executing LeanStack Provisioning Pipeline...{Style.RESET}\n")
        self.execute_pipeline(profile_data)

    def execute_pipeline(self, tuning_data: Dict[str, Any]):
        phases = [
            ("Phase 1: Base OS Cleanup, THP Lockout & Sysctl Tuning", self._run_phase1),
            ("Phase 2: In-Memory Cache Tier (Valkey on Unix Domain Socket)", self._run_phase2),
            ("Phase 3: Database Tier (MariaDB High-QPS Tuning)", self._run_phase3),
            ("Phase 4: Web Tier & WAF (Angie HTTP/3, PQC TLS, 8G WAF, CrowdSec)", self._run_phase4),
            ("Phase 5: Application Tier (PHP Multi-Version Engine & WP-CLI)", self._run_phase5),
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

    def _run_phase1(self, tuning: Dict[str, Any], spinner: ProgressSpinner):
        script = os.path.join(self.base_dir, "scripts", "phase1_os_tune.sh")
        if self.dry_run:
            time.sleep(0.4)
            return
        self._run_bash_script(script)

    def _run_phase2(self, tuning: Dict[str, Any], spinner: ProgressSpinner):
        script = os.path.join(self.base_dir, "scripts", "phase2_valkey.sh")
        if self.dry_run:
            time.sleep(0.4)
            return
        self._run_bash_script(script)

    def _run_phase3(self, tuning: Dict[str, Any], spinner: ProgressSpinner):
        script = os.path.join(self.base_dir, "scripts", "phase3_mariadb.sh")
        if self.dry_run:
            time.sleep(0.4)
            return
        self._run_bash_script(script)

    def _run_phase4(self, tuning: Dict[str, Any], spinner: ProgressSpinner):
        script = os.path.join(self.base_dir, "scripts", "phase4_angie_waf.sh")
        if self.dry_run:
            time.sleep(0.4)
            return
        self._run_bash_script(script)

    def _run_phase5(self, tuning: Dict[str, Any], spinner: ProgressSpinner):
        script = os.path.join(self.base_dir, "scripts", "phase5_php.sh")
        if self.dry_run:
            time.sleep(0.4)
            return
        self._run_bash_script(script)

    def _run_phase6(self, tuning: Dict[str, Any], spinner: ProgressSpinner):
        if self.dry_run:
            time.sleep(0.3)
            return
        # Install all control plane binaries into /usr/local/bin
        bin_dir = os.path.join(self.base_dir, "core", "bin")
        if os.path.exists(bin_dir):
            for b in os.listdir(bin_dir):
                src = os.path.join(bin_dir, b)
                if os.path.isfile(src):
                    subprocess.run(["install", "-m", "0755", src, f"/usr/local/bin/{b}"], check=True)

        # Populate /etc/lsctl/templates and baseline profiles
        os.makedirs("/etc/lsctl/templates", exist_ok=True)
        os.makedirs("/etc/leanstack", exist_ok=True)
        os.makedirs("/var/lib/lsctl", mode=0o700, exist_ok=True)
        
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

        tpl_dir = os.path.join(self.base_dir, "core", "templates")
        if os.path.exists(tpl_dir):
            for t in os.listdir(tpl_dir):
                shutil.copy2(os.path.join(tpl_dir, t), os.path.join("/etc/lsctl/templates", t))

        prof_src = os.path.join(self.base_dir, "core", "config", "profiles.yaml")
        if os.path.exists(prof_src) and not os.path.exists("/etc/lsctl/profiles.yaml"):
            shutil.copy2(prof_src, "/etc/lsctl/profiles.yaml")

        # Load centralized version configuration
        v_file = os.path.join(self.base_dir, "core", "version.json")
        v_num = "1.2.0"
        if os.path.exists(v_file):
            try:
                with open(v_file, "r") as f_v:
                    v_num = json.load(f_v).get("version", "1.2.0")
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
        # Copy systemd units
        systemd_dir = os.path.join(self.base_dir, "systemd")
        for f in os.listdir(systemd_dir):
            if f.endswith(".service") or f.endswith(".timer"):
                src = os.path.join(systemd_dir, f)
                subprocess.run(["cp", src, f"/etc/systemd/system/{f}"], check=True)
        subprocess.run(["systemctl", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "enable", "--now", "cp-cron.timer", "cp-cf-sync.timer", "cp-gatekeeper.service"], check=False)

    def _run_bash_script(self, script_path: str):
        if not os.path.exists(script_path):
            raise FileNotFoundError(f"Missing script: {script_path}")
        res = subprocess.run(["bash", script_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"Script failed with exit code {res.returncode}: {res.stderr[:200]}")

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
