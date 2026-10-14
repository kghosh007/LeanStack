#!/usr/bin/env python3
"""
LeanStack Telemetry & ANSI Visual UI Engine
Provides zero-dependency ANSI / 24-bit TrueColor styling, interactive menus,
spinners, progress bars, and terminal widgets reminiscent of Antigravity CLI.
"""

import sys
import os
import time
import shutil
import termios
import tty
from typing import List, Tuple, Optional, Callable

# ANSI Color Codes & Helpers
class Style:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"
    
    # Standard Foregrounds
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    
    # Bright Foregrounds
    BRIGHT_BLACK = "\033[90m"
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_WHITE = "\033[97m"

    # Backgrounds
    BG_DARK = "\033[48;5;234m"
    BG_CYAN = "\033[48;5;24m"
    BG_GREEN = "\033[48;5;22m"

    @staticmethod
    def rgb(r: int, g: int, b: int) -> str:
        return f"\033[38;2;{r};{g};{b}m"

    @staticmethod
    def bg_rgb(r: int, g: int, b: int) -> str:
        return f"\033[48;2;{r};{g};{b}m"

def term_width() -> int:
    try:
        return shutil.get_terminal_size((80, 24)).columns
    except Exception:
        return 80

def clear_screen():
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()

def hide_cursor():
    sys.stdout.write("\033[?25l")
    sys.stdout.flush()

def show_cursor():
    sys.stdout.write("\033[?25h")
    sys.stdout.flush()

class KeyReader:
    """Reads non-blocking raw keypresses from the terminal."""
    @staticmethod
    def get_key() -> str:
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            if ch == '\x1b':
                # Escape sequence
                ch2 = sys.stdin.read(1)
                if ch2 == '[':
                    ch3 = sys.stdin.read(1)
                    if ch3 == 'A':
                        return 'UP'
                    elif ch3 == 'B':
                        return 'DOWN'
                    elif ch3 == 'C':
                        return 'RIGHT'
                    elif ch3 == 'D':
                        return 'LEFT'
                return 'ESC'
            elif ch == '\r' or ch == '\n':
                return 'ENTER'
            elif ch == ' ':
                return 'SPACE'
            elif ch == '\x03':
                return 'CTRL_C'
            return ch
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

def render_banner() -> str:
    brand_color = Style.rgb(0, 220, 180)
    sub_color = Style.rgb(130, 160, 255)
    dim_color = Style.BRIGHT_BLACK
    banner = f"""{brand_color}{Style.BOLD}""" + r"""
   __                          _____  __               __  
  / /   ___  ____ _____       / ___/ / /_____ _ _____ / /__
 / /   / _ \/ __ `/ __ \     \__ \ / __/ __ `// ___// //_/
/ /___/  __/ /_/ / / / /    ___/ // /_/ /_/ // /__ / ,<   
/_____/\___/\__,_/_/ /_/    /____/ \__/\__,_/ \___//_/|_|  
""" + f"""{Style.RESET}   {sub_color}⚡ Ultra-Lightweight • High-Density • WordPress Control Plane ⚡{Style.RESET}
   {dim_color}Version 2.0 • Native Angie • Socket Valkey • High-QPS MariaDB • PQC TLS{Style.RESET}
"""
    return banner

def render_card(title: str, content_lines: List[str], width: int = 76, color: str = Style.CYAN) -> str:
    """Renders a rounded-corner container card with a stylized title."""
    header = f"{color}╭─ {Style.BOLD}{title}{Style.RESET}{color} " + "─" * max(0, width - len(title) - 5) + f"╮{Style.RESET}"
    footer = f"{color}╰" + "─" * (width - 2) + f"╯{Style.RESET}"
    
    body = []
    for line in content_lines:
        # Strip ANSI to measure visual width
        raw_len = len(strip_ansi(line))
        pad = " " * max(0, width - 4 - raw_len)
        body.append(f"{color}│{Style.RESET} {line}{pad} {color}│{Style.RESET}")
    
    return "\n".join([header] + body + [footer])

def strip_ansi(text: str) -> str:
    import re
    return re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)

def interactive_select(title: str, options: List[Tuple[str, str]], default_idx: int = 0) -> int:
    """
    Renders an interactive menu allowing the user to select an option using UP/DOWN/ENTER.
    options is a list of tuples: (Label, Description).
    """
    selected = default_idx
    hide_cursor()
    try:
        while True:
            # Move cursor up or redraw
            lines = [
                f"{Style.BOLD}{Style.BRIGHT_CYAN}? {title}:{Style.RESET} {Style.DIM}(Use arrow keys, press Enter to select){Style.RESET}\n"
            ]
            for idx, (label, desc) in enumerate(options):
                if idx == selected:
                    pointer = f"{Style.BRIGHT_GREEN}❯{Style.RESET}"
                    item = f"{Style.BOLD}{Style.BRIGHT_GREEN}{label:<22}{Style.RESET}"
                    d = f"{Style.BRIGHT_WHITE}{desc}{Style.RESET}"
                else:
                    pointer = " "
                    item = f"{Style.DIM}{label:<22}{Style.RESET}"
                    d = f"{Style.DIM}{desc}{Style.RESET}"
                lines.append(f"  {pointer} {item} {d}")
            
            # Print menu block
            out = "\n".join(lines)
            sys.stdout.write(out + "\n")
            sys.stdout.flush()

            key = KeyReader.get_key()
            if key == 'UP':
                selected = (selected - 1) % len(options)
            elif key == 'DOWN':
                selected = (selected + 1) % len(options)
            elif key == 'ENTER':
                # Clear menu lines
                sys.stdout.write(f"\033[{len(options) + 2}A\033[J")
                sys.stdout.write(f"{Style.BRIGHT_GREEN}✔ {title}:{Style.RESET} {Style.BOLD}{options[selected][0]}{Style.RESET}\n")
                sys.stdout.flush()
                return selected
            elif key == 'CTRL_C':
                show_cursor()
                sys.stdout.write("\nAborted.\n")
                sys.exit(1)
            
            # Move back up to redraw
            sys.stdout.write(f"\033[{len(options) + 2}A")
            sys.stdout.flush()
    finally:
        show_cursor()

def interactive_confirm(prompt: str, default: bool = True) -> bool:
    """Interactive Y/N confirmation."""
    def_str = "[Y/n]" if default else "[y/N]"
    sys.stdout.write(f"{Style.BOLD}{Style.BRIGHT_YELLOW}? {prompt} {def_str}: {Style.RESET}")
    sys.stdout.flush()
    key = KeyReader.get_key()
    if key in ('ENTER', ' '):
        res = default
    elif key in ('y', 'Y'):
        res = True
    else:
        res = False
    sys.stdout.write(f"{'Yes' if res else 'No'}\n")
    return res

class ProgressSpinner:
    """An animated modern spinner widget."""
    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, message: str):
        self.message = message
        self.idx = 0

    def step(self, extra: str = ""):
        frame = f"{Style.BRIGHT_CYAN}{self.FRAMES[self.idx % len(self.FRAMES)]}{Style.RESET}"
        sys.stdout.write(f"\r  {frame} {self.message} {Style.DIM}{extra}{Style.RESET}\033[K")
        sys.stdout.flush()
        self.idx += 1

    def success(self, finish_msg: Optional[str] = None):
        msg = finish_msg or self.message
        sys.stdout.write(f"\r  {Style.BRIGHT_GREEN}✔{Style.RESET} {msg}\033[K\n")
        sys.stdout.flush()

    def fail(self, fail_msg: Optional[str] = None):
        msg = fail_msg or self.message
        sys.stdout.write(f"\r  {Style.BRIGHT_RED}✖{Style.RESET} {msg}\033[K\n")
        sys.stdout.flush()
