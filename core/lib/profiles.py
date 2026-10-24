#!/usr/bin/env python3
"""
LeanStack Profiles Helper (core/lib/profiles.py)
Unified YAML profiles loader, validator, and formatter (LS-20).
Eliminates duplicated hand-rolled YAML parsers across the codebase.
Provides interactive TUI profile creation and deletion.
"""

from __future__ import annotations
import sys
import os
import re
import json
from typing import Dict, Any, Optional, List, Tuple, Callable

try:
    import yaml
except ImportError:
    yaml = None


def load_yaml(text: str) -> Dict[str, Any]:
    """Parse YAML with PyYAML if available, with robust indentation-aware fallback."""
    if yaml is not None:
        try:
            return yaml.safe_load(text) or {}
        except Exception:
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


def dump_yaml(profiles: Dict[str, Any]) -> str:
    """Serializes profiles dictionary to YAML format."""
    if yaml is not None:
        return yaml.dump(profiles, default_flow_style=False, sort_keys=False)

    lines = [
        "# ==============================================================================",
        "# LeanStack Agency WordPress Profiles",
        "# Selectable during provisioning via --profile=<name>",
        "# Manage via: lsctl profile:list, lsctl profile:show, lsctl profile:create",
        "# ==============================================================================",
        ""
    ]
    for name, p in profiles.items():
        lines.append(f"{name}:")
        for k, v in p.items():
            if isinstance(v, bool):
                lines.append(f"  {k}: {'true' if v else 'false'}")
            elif isinstance(v, list):
                lines.append(f"  {k}:")
                for item in v:
                    lines.append(f'    - "{item}"')
            else:
                lines.append(f'  {k}: "{v}"')
        lines.append("")
    return "\n".join(lines)


def load_profiles(profiles_path: str) -> Dict[str, Any]:
    if not os.path.exists(profiles_path):
        raise FileNotFoundError(f"Profiles configuration file '{profiles_path}' not found.")
    with open(profiles_path, "r", encoding="utf-8") as f:
        return load_yaml(f.read())


def save_profiles(profiles_path: str, profiles: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(profiles_path)), exist_ok=True)
    with open(profiles_path, "w", encoding="utf-8") as f:
        f.write(dump_yaml(profiles))


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
        admin_u = p.get("admin_user") or "Dynamic (autogenerated admin_<6chars> per site)"
        admin_e = p.get("admin_email") or "Dynamic (prompted during site creation)"
        print("==========================================================")
        print(f"Profile Name:    {name}")
        print(f"Description:     {p.get('description', '')}")
        print(f"PHP Version:     {p.get('php', '8.5')}")
        print(f"Pool Mode:       {p.get('pool_mode', 'ondemand')}")
        print(f"Memory Limit:    {p.get('memory_limit', '256M')}")
        print(f"Admin User:      {admin_u}")
        print(f"Admin Email:     {admin_e}")
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


# ==============================================================================
# Interactive TUI Wizard & Menu Selectors
# ==============================================================================

def _get_key_raw() -> str:
    """Reads raw keypresses using termios/tty if available."""
    import termios
    import tty
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == '\x1b':
            ch2 = sys.stdin.read(1)
            if ch2 == '[':
                ch3 = sys.stdin.read(1)
                if ch3 == 'A':
                    return 'UP'
                elif ch3 == 'B':
                    return 'DOWN'
            return 'ESC'
        elif ch in ('\r', '\n'):
            return 'ENTER'
        elif ch == '\x03':
            return 'CTRL_C'
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def interactive_select(title: str, options: List[Tuple[str, str, str]], default_idx: int = 0) -> str:
    """
    Renders an interactive selection menu.
    options is a list of tuples: (Value, Label, Description)
    Falls back gracefully to standard numbered input if raw mode is unavailable.
    """
    if not sys.stdin.isatty():
        return options[default_idx][0]

    # Try raw mode navigation
    can_raw = False
    try:
        import termios
        can_raw = True
    except ImportError:
        pass

    if can_raw:
        try:
            selected = default_idx
            sys.stdout.write("\033[?25l")  # Hide cursor
            while True:
                out_lines = [
                    f"\033[1;36m? {title}:\033[0m \033[2m(Use ↑/↓ arrow keys, Enter to confirm)\033[0m"
                ]
                for idx, (val, label, desc) in enumerate(options):
                    if idx == selected:
                        pointer = "\033[1;32m❯\033[0m"
                        item = f"\033[1;32m{label:<20}\033[0m"
                        d = f"\033[1;37m{desc}\033[0m"
                    else:
                        pointer = " "
                        item = f"\033[2m{label:<20}\033[0m"
                        d = f"\033[2m{desc}\033[0m"
                    out_lines.append(f"  {pointer} {item} {d}")

                sys.stdout.write("\n".join(out_lines) + "\n")
                sys.stdout.flush()

                key = _get_key_raw()
                if key == 'UP':
                    selected = (selected - 1) % len(options)
                elif key == 'DOWN':
                    selected = (selected + 1) % len(options)
                elif key == 'ENTER':
                    # Clear menu lines and show selection
                    sys.stdout.write(f"\033[{len(options) + 1}A\033[J")
                    sys.stdout.write(f"\033[1;32m✔ {title}:\033[0m \033[1m{options[selected][1]}\033[0m\n")
                    sys.stdout.flush()
                    return options[selected][0]
                elif key == 'CTRL_C':
                    sys.stdout.write("\033[?25h\nAborted.\n")
                    sys.exit(1)

                sys.stdout.write(f"\033[{len(options) + 1}A")
                sys.stdout.flush()
        except Exception:
            pass
        finally:
            sys.stdout.write("\033[?25h")  # Show cursor
            sys.stdout.flush()

    # Numbered fallback prompt
    print(f"\n? {title}:")
    for idx, (val, label, desc) in enumerate(options, 1):
        def_tag = " [Default]" if (idx - 1) == default_idx else ""
        print(f"  [{idx}] {label:<16} - {desc}{def_tag}")
    while True:
        try:
            choice = input(f"Enter choice [1-{len(options)}] (default: {default_idx + 1}): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            sys.exit(1)
        if not choice:
            return options[default_idx][0]
        if choice.isdigit() and 1 <= int(choice) <= len(options):
            return options[int(choice) - 1][0]
        print(f"Invalid option. Please enter a number between 1 and {len(options)}.")


def interactive_text(prompt: str, default: str = "", validator: Optional[Callable[[str], bool]] = None, err_msg: str = "") -> str:
    """Prompts for text input with an optional default and validator."""
    if not sys.stdin.isatty():
        return default

    def_hint = f" [{default}]" if default else ""
    while True:
        try:
            val = input(f"\033[1;33m? {prompt}{def_hint}:\033[0m ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            sys.exit(1)
        if not val:
            val = default
        if validator and not validator(val):
            print(f"\033[31m  ✖ {err_msg or 'Invalid input. Please try again.'}\033[0m")
            continue
        return val


def create_profile(profiles_path: str, args: List[str]) -> int:
    """
    Creates an operational profile either via interactive TUI menu or via CLI flags.
    """
    p_name = ""
    desc = ""
    php = ""
    mem = ""
    pool = ""
    cf: Optional[bool] = None
    cache = ""
    theme = ""
    admin_u = ""
    admin_e = ""
    non_interactive = False

    # Parse command line arguments
    for arg in args:
        if arg.startswith("--name="):
            p_name = arg.split("=", 1)[1]
        elif arg.startswith("--description="):
            desc = arg.split("=", 1)[1]
        elif arg.startswith("--php="):
            php = arg.split("=", 1)[1]
        elif arg.startswith("--mem=") or arg.startswith("--memory-limit="):
            mem = arg.split("=", 1)[1]
        elif arg.startswith("--pool-mode="):
            pool = arg.split("=", 1)[1]
        elif arg == "--cf":
            cf = True
        elif arg.startswith("--cf="):
            cf = arg.split("=", 1)[1].lower() in ("true", "1", "yes", "on")
        elif arg.startswith("--cache="):
            cache = arg.split("=", 1)[1]
        elif arg.startswith("--theme="):
            theme = arg.split("=", 1)[1]
        elif arg.startswith("--admin-user="):
            admin_u = arg.split("=", 1)[1]
        elif arg.startswith("--admin-email="):
            admin_e = arg.split("=", 1)[1]
        elif arg in ("--non-interactive", "--batch"):
            non_interactive = True
        elif not arg.startswith("-") and not p_name:
            p_name = arg

    # Load existing profiles
    try:
        profiles = load_profiles(profiles_path)
    except FileNotFoundError:
        profiles = {}
    except Exception as e:
        print(f"ERROR loading {profiles_path}: {e}", file=sys.stderr)
        return 1

    is_interactive = sys.stdin.isatty() and not non_interactive

    if is_interactive:
        print("\n==============================================================================")
        print("          LEANSTACK INTERACTIVE OPERATIONAL PROFILE CREATOR                   ")
        print("==============================================================================")
        print("Configure high-density, hardware-isolated WordPress execution profiles.\n")

        # 1. Profile Name
        if not p_name:
            p_name = interactive_text(
                "Profile Name (slug)",
                validator=lambda s: bool(re.match(r"^[a-zA-Z0-9_-]+$", s)) and s not in profiles,
                err_msg="Name must be alphanumeric/underscores/hyphens and must not already exist."
            )
        elif p_name in profiles:
            print(f"ERROR: Profile '{p_name}' already exists in {profiles_path}.", file=sys.stderr)
            return 1

        # 2. Description
        if not desc:
            desc = interactive_text(
                "Profile Description",
                default=f"Custom agency operational profile for {p_name}"
            )

        # 3. PHP Runtime Version (Fixed Choices)
        if not php:
            php_choices = [
                ("8.5", "PHP 8.5 (Recommended)", "Latest high-performance runtime with JIT & micro-optimizations"),
                ("8.4", "PHP 8.4", "Modern PHP runtime supporting property hooks and asymmetric visibility"),
                ("8.3", "PHP 8.3", "Long-Term Stable enterprise runtime"),
                ("8.2", "PHP 8.2", "Standard production enterprise runtime"),
                ("8.1", "PHP 8.1", "Legacy compatibility runtime"),
            ]
            php = interactive_select("Primary PHP Runtime Version", php_choices, default_idx=0)

        # 4. PHP-FPM Pool Mode (Fixed Choices)
        if not pool:
            pool_choices = [
                ("ondemand", "ondemand (Recommended)", "Workers scale to 0 when idle; maximum multi-tenant density"),
                ("dynamic", "dynamic", "Pre-forked spare workers; optimal for predictable, steady traffic"),
                ("static", "static", "Fixed worker allocation; reserved for high-throughput dedicated nodes"),
            ]
            pool = interactive_select("PHP-FPM Process Management Mode", pool_choices, default_idx=0)

        # 5. Memory Limit (Fixed Choices)
        if not mem:
            mem_choices = [
                ("256M", "256M (Standard)", "Lightweight blogs, portfolios, and typical business sites"),
                ("384M", "384M (Medium)", "High-traffic content publishing and news portals"),
                ("512M", "512M (High-Performance)", "WooCommerce, LearnDash, and complex dynamic applications"),
                ("1024M", "1024M (Enterprise)", "Large-scale headless APIs and heavy imports"),
                ("custom", "Custom Memory Limit", "Specify custom limit (e.g. 768M)"),
            ]
            mem_sel = interactive_select("Per-Tenant PHP Memory Limit", mem_choices, default_idx=0)
            if mem_sel == "custom":
                mem = interactive_text(
                    "Enter custom memory limit (e.g. 768M)",
                    default="512M",
                    validator=lambda s: bool(re.match(r"^[0-9]+[MG]$", s)),
                    err_msg="Must end in M or G (e.g., 512M, 1G)."
                )
            else:
                mem = mem_sel

        # 6. Angie FastCGI & Valkey Cache (Fixed Choices)
        if not cache:
            cache_choices = [
                ("on", "Enabled (Recommended)", "Angie edge FastCGI microcaching + Valkey socket object cache"),
                ("off", "Disabled", "Direct PHP-FPM execution without edge microcaching"),
            ]
            cache = interactive_select("Edge & Object Cache", cache_choices, default_idx=0)

        # 7. Cloudflare Edge Integration (Fixed Choices)
        if cf is None:
            cf_choices = [
                ("false", "Disabled (Recommended)", "Direct Angie TLS termination with Let's Encrypt"),
                ("true", "Enabled", "Cloudflare APO proxy and enterprise edge zone integration"),
            ]
            cf_sel = interactive_select("Cloudflare Edge Integration", cf_choices, default_idx=0)
            cf = (cf_sel == "true")

        # 8. Default WordPress Theme (Fixed Choices)
        if not theme:
            theme_choices = [
                ("twentytwentyfour", "twentytwentyfour (Default)", "Clean, modern full-site editing block theme"),
                ("storefront", "storefront", "High-performance WooCommerce e-commerce theme"),
                ("astra", "astra", "Fast, lightweight multipurpose foundation theme"),
                ("generatepress", "generatepress", "Speed and accessibility optimized theme"),
                ("none", "none", "Do not auto-install an additional theme"),
                ("custom", "Custom Theme Slug", "Specify custom WordPress theme slug"),
            ]
            theme_sel = interactive_select("Default WordPress Theme", theme_choices, default_idx=0)
            if theme_sel == "custom":
                theme = interactive_text("Enter WordPress theme slug", default="twentytwentyfour")
            elif theme_sel == "none":
                theme = ""
            else:
                theme = theme_sel

        # 9. Admin Credentials Strategy (Fixed Choices)
        cred_strategy = interactive_select(
            "WordPress Admin Credentials Strategy",
            [
                ("dynamic", "Dynamic (Recommended)", "Leave blank in profile; autogenerate unique admin_<6chars> per site & prompt for email"),
                ("static", "Pre-configured Static Credentials", "Hardcode specific admin username and email for all sites created with this profile")
            ],
            default_idx=0
        )

        if cred_strategy == "static":
            admin_u = interactive_text(
                "Pre-configured Admin Username",
                default="agency_admin",
                validator=lambda s: bool(re.match(r"^[a-zA-Z0-9_.-]+$", s)),
                err_msg="Username can only contain alphanumeric characters, underscores, and hyphens."
            )
            admin_e = interactive_text(
                "Pre-configured Admin Email",
                default="admin@example.com",
                validator=lambda s: bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", s)),
                err_msg="Please enter a valid email address."
            )
        else:
            admin_u = ""
            admin_e = ""

    else:
        # Non-interactive / CLI mode
        if not p_name:
            print("ERROR: Profile name is required. Usage: lsctl profile:create <name> [options]", file=sys.stderr)
            return 1
        if p_name in profiles:
            print(f"ERROR: Profile '{p_name}' already exists in {profiles_path}.", file=sys.stderr)
            return 1

        if not desc:
            desc = f"Custom agency operational profile for {p_name}"
        if not php:
            php = "8.5"
        if not pool:
            pool = "ondemand"
        if not mem:
            mem = "256M"
        if not cache:
            cache = "on"
        if cf is None:
            cf = False
        if not theme:
            theme = "twentytwentyfour"

    # Assemble profile dictionary
    profiles[p_name] = {
        "description": desc,
        "admin_user": admin_u,
        "admin_email": admin_e,
        "php": php,
        "pool_mode": pool,
        "memory_limit": mem,
        "timezone": "UTC",
        "cache": cache,
        "cf": cf if isinstance(cf, bool) else (str(cf).lower() == "true"),
        "plugins": ["redis-cache"],
        "theme": theme if theme != "none" else ""
    }

    try:
        save_profiles(profiles_path, profiles)
        print(f"\n✅ Created new operational profile: {p_name}")
        print(f"   PHP: {php} | Memory: {mem} | Pool: {pool} | Theme: {theme or 'none'} | Cloudflare: {'yes' if cf else 'no'}")
        if not admin_u:
            print("   Admin Credentials: Dynamic (unique admin_<6chars> autogenerated per site)")
        else:
            print(f"   Admin User: {admin_u} | Admin Email: {admin_e}")
        return 0
    except Exception as e:
        print(f"ERROR saving profile: {e}", file=sys.stderr)
        return 1


def delete_profile(profiles_path: str, name: str) -> int:
    """Deletes a custom operational profile."""
    if not name:
        print("ERROR: Profile name is required. Usage: lsctl profile:delete <name>", file=sys.stderr)
        return 1

    if name == "default":
        print("ERROR: Cannot delete the default core profile.", file=sys.stderr)
        return 1

    try:
        profiles = load_profiles(profiles_path)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if name not in profiles:
        print(f"ERROR: Profile '{name}' does not exist.", file=sys.stderr)
        return 1

    del profiles[name]

    try:
        save_profiles(profiles_path, profiles)
        print(f"🗑️ Removed profile: {name}")
        return 0
    except Exception as e:
        print(f"ERROR removing profile: {e}", file=sys.stderr)
        return 1


def main():
    if len(sys.argv) < 3:
        print("Usage: profiles.py <list|show|get|create|delete> <profiles_file> [args...]", file=sys.stderr)
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

    elif cmd == "create":
        args = sys.argv[3:]
        sys.exit(create_profile(profiles_path, args))

    elif cmd == "delete":
        name = sys.argv[3] if len(sys.argv) > 3 else ""
        sys.exit(delete_profile(profiles_path, name))

    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
