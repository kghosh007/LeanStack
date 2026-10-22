#!/usr/bin/env python3
"""
LeanStack Profiles Helper (core/lib/profiles.py)
Unified YAML profiles loader, validator, and formatter (LS-20).
Eliminates duplicated hand-rolled YAML parsers across the codebase.
"""

from __future__ import annotations
import sys
import os
import json
from typing import Dict, Any, Optional


def load_yaml(text: str) -> Dict[str, Any]:
    """Parse YAML with PyYAML if available, with robust indentation-aware fallback."""
    try:
        import yaml
        return yaml.safe_load(text) or {}
    except ImportError:
        pass

    profiles: Dict[str, Any] = {}
    current: Optional[str] = None
    curr_key: Optional[str] = None

    for line in text.splitlines():
        line = line.rstrip()
        if not line or line.startswith("#"):
            continue
        if not line.startswith(" "):
            if ":" in line:
                current = line.split(":", 1)[0].strip()
                profiles[current] = {}
                curr_key = None
        elif current is not None:
            s = line.strip()
            if s.startswith("- ") and curr_key:
                val = s[2:].strip().strip('"').strip("'")
                if not isinstance(profiles[current].get(curr_key), list):
                    profiles[current][curr_key] = []
                profiles[current][curr_key].append(val)
            elif ":" in s:
                k, v = s.split(":", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                curr_key = k
                if v == "true":
                    val_conv = True
                elif v == "false":
                    val_conv = False
                elif not v:
                    val_conv = []
                else:
                    val_conv = v
                profiles[current][k] = val_conv

    return profiles


def load_profiles(profiles_path: str) -> Dict[str, Any]:
    if not os.path.exists(profiles_path):
        raise FileNotFoundError(f"Profiles configuration file '{profiles_path}' not found.")
    with open(profiles_path, "r", encoding="utf-8") as f:
        return load_yaml(f.read())


def list_profiles(profiles_path: str, json_mode: bool = False) -> int:
    try:
        profiles = load_profiles(profiles_path)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if json_mode:
        print(json.dumps(profiles, indent=2))
    else:
        print("==========================================================================================")
        print("LEANSTACK OPERATIONAL WORDPRESS PROFILES")
        print("==========================================================================================")
        print(f"{'PROFILE':<22} {'PHP':<6} {'MEM':<7} {'POOL':<9} {'CF':<6} {'THEME':<16} {'DESCRIPTION'}")
        print("-" * 95)
        for name, p in profiles.items():
            desc = p.get("description", "")
            php = p.get("php", "8.5")
            mem = p.get("memory_limit", "256M")
            pool = p.get("pool_mode", "ondemand")
            cf = "yes" if p.get("cf", False) else "no"
            theme = p.get("theme", "none") or "none"
            print(f"{name:<22} {php:<6} {mem:<7} {pool:<9} {cf:<6} {str(theme)[:15]:<16} {desc}")
        print("==========================================================================================")
    return 0


def show_profile(profiles_path: str, name: str, json_mode: bool = False) -> int:
    try:
        profiles = load_profiles(profiles_path)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if name not in profiles:
        print(f"ERROR: Profile '{name}' does not exist.", file=sys.stderr)
        return 1

    p = profiles[name]
    if json_mode:
        print(json.dumps(p, indent=2))
    else:
        print("==========================================================")
        print(f"Profile Name:    {name}")
        print(f"Description:     {p.get('description', '')}")
        print(f"PHP Version:     {p.get('php', '8.5')}")
        print(f"Pool Mode:       {p.get('pool_mode', 'ondemand')}")
        print(f"Memory Limit:    {p.get('memory_limit', '256M')}")
        print(f"Admin User:      {p.get('admin_user', 'admin')}")
        print(f"Admin Email:     {p.get('admin_email', 'admin@example.com')}")
        print(f"Cache Enabled:   {p.get('cache', 'on')}")
        print(f"Cloudflare:      {'Enabled' if p.get('cf', False) else 'Disabled'}")
        print(f"Timezone:        {p.get('timezone', 'UTC')}")
        print(f"Theme:           {p.get('theme', 'none') or 'none'}")
        plugins = p.get("plugins", [])
        if plugins:
            print("Plugins:         " + ", ".join(plugins))
        else:
            print("Plugins:         none")
        print("==========================================================")
    return 0


def get_profile(profiles_path: str, name: str, key: Optional[str] = None, default: Optional[str] = None) -> int:
    try:
        profiles = load_profiles(profiles_path)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if name not in profiles:
        print(f"ERROR: Profile '{name}' not found in {profiles_path}", file=sys.stderr)
        return 2

    prof = profiles[name]
    if key:
        val = prof.get(key, default)
        if val is None:
            if default is not None:
                print(default)
            return 0
        if isinstance(val, (dict, list)):
            print(json.dumps(val))
        else:
            print(str(val))
    else:
        print(json.dumps(prof))
    return 0


def main():
    if len(sys.argv) < 3:
        print("Usage: profiles.py <list|show|get> <profiles_file> [name] [key/json_mode] [default]", file=sys.stderr)
        sys.exit(1)

    cmd = sys.argv[1]
    profiles_path = sys.argv[2]

    if cmd == "list":
        json_mode = len(sys.argv) > 3 and (sys.argv[3] == "1" or sys.argv[3] == "--json")
        sys.exit(list_profiles(profiles_path, json_mode))

    elif cmd == "show":
        name = sys.argv[3] if len(sys.argv) > 3 else ""
        json_mode = len(sys.argv) > 4 and (sys.argv[4] == "1" or sys.argv[4] == "--json")
        sys.exit(show_profile(profiles_path, name, json_mode))

    elif cmd == "get":
        name = sys.argv[3] if len(sys.argv) > 3 else ""
        key = sys.argv[4] if len(sys.argv) > 4 else None
        default = sys.argv[5] if len(sys.argv) > 5 else None
        sys.exit(get_profile(profiles_path, name, key, default))

    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
