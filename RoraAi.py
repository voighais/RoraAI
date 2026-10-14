#!/usr/bin/env python3
# rora v1.7.3 — perf + QuickEdit fix + focus-aware output
# commands:
#   /new  /sessions  /switch <n>  /delete <n>  /purge  /rename <title>
#   /models  /model [<n>]  /reload-prompt  /config
#   /theme [<name>|bg <c>|edit <k> <v>|reset|save <n>]
#   /cd <path>  /ls [path]  /open <path>  /sh <cmd>
#   /reset  /help  /exit

import os
import sys
import re
import time
import json
import shutil
import platform
import argparse
import subprocess
import webbrowser
import urllib.parse
import threading
import inspect
import ctypes
from pathlib import Path
from datetime import datetime


def _maybe_relaunch_in_cmd():
    if os.name != "nt":
        return False
    if os.environ.get("RORA_IN_CMD") == "1":
        return False
    if "--no-relaunch" in sys.argv:
        return False
    try:
        script = os.path.abspath(__file__)
        py = sys.executable
        forward = [a for a in sys.argv[1:] if a != "--no-relaunch"]
        env = os.environ.copy()
        env["RORA_IN_CMD"] = "1"
        subprocess.Popen(
            [py, script] + forward + ["--no-relaunch"],
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
            env=env, close_fds=True,
        )
        return True
    except Exception:
        return False


# ---------- Windows console setup ----------
def _setup_windows_console():
    """Включает VT, отключает QuickEdit (главный фикс зависаний)."""
    if os.name != "nt":
        return
    try:
        k = ctypes.windll.kernel32
        # output handle: включить виртуальный терминал (цвета/ANSI)
        h_out = k.GetStdHandle(-11)
        m_out = ctypes.c_ulong()
        k.GetConsoleMode(h_out, ctypes.byref(m_out))
        # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        k.SetConsoleMode(h_out, m_out.value | 0x0004)

        # input handle: выключить QuickEdit (иначе cmd замерзает при клике)
        h_in = k.GetStdHandle(-10)
        m_in = ctypes.c_ulong()
        k.GetConsoleMode(h_in, ctypes.byref(m_in))
        # ENABLE_EXTENDED_FLAGS = 0x0080 -> включает явное управление
        # ENABLE_QUICK_EDIT_MODE = 0x0040 -> выключить
        new_mode = (m_in.value | 0x0080) & ~0x0040
        k.SetConsoleMode(h_in, new_mode)
    except Exception:
        pass


def _is_console_visible():
    """True если окно консоли не свёрнуто и видимо."""
    if os.name != "nt":
        return True
    try:
        k = ctypes.windll.kernel32
        u = ctypes.windll.user32
        hwnd = k.GetConsoleWindow()
        if not hwnd:
            return True
        if u.IsIconic(hwnd):
            return False
        return bool(u.IsWindowVisible(hwnd))
    except Exception:
        return True


_vis_state = True
_vis_last_check = 0.0


def is_visible_cached():
    """Кэшируем проверку видимости — раз в 200мс."""
    global _vis_state, _vis_last_check
    now = time.time()
    if now - _vis_last_check < 0.2:
        return _vis_state
    _vis_last_check = now
    _vis_state = _is_console_visible()
    return _vis_state


_setup_windows_console()

if os.name == "nt":
    try:
        os.system("chcp 65001 >nul 2>&1")
    except Exception:
        pass

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    from llama_cpp import Llama
except ImportError:
    print("pip install llama-cpp-python")
    sys.exit(1)


R = "\033[0m"
B = "\033[1m"


def rgb(r, g, b):
    return f"\033[38;2;{r};{g};{b}m"


def lerp(c1, c2, t):
    return (
        int(c1[0] + (c2[0] - c1[0]) * t),
        int(c1[1] + (c2[1] - c1[1]) * t),
        int(c1[2] + (c2[2] - c1[2]) * t),
    )


# ---- базовые цвета. Заполняются apply_theme() ----
C_ACCENT = rgb(100, 170, 255)
C_LIGHT = rgb(150, 210, 255)
C_DEEP = rgb(35, 75, 180)
C_DIM = rgb(110, 125, 155)
C_DIMMER = rgb(75, 85, 110)
C_GRN = rgb(120, 220, 150)
C_RED = rgb(240, 130, 130)
C_YEL = rgb(240, 210, 120)
C_WHITE = rgb(230, 235, 245)
C_CYAN = rgb(120, 200, 220)
C_MAG = rgb(200, 150, 255)
C_PURP = rgb(170, 90, 220)
C_PURP_D = rgb(100, 40, 150)
LOGO_COLORS = ((200, 235, 255), (90, 160, 255), (80, 150, 230), (30, 60, 150))
BG_RGB = None

NAMED_COLORS = {
    "black": (0, 0, 0), "white": (255, 255, 255),
    "red": (255, 80, 80), "green": (80, 255, 80),
    "blue": (80, 140, 255), "yellow": (255, 220, 80),
    "cyan": (80, 240, 240), "magenta": (240, 80, 240),
    "orange": (255, 160, 60), "purple": (170, 90, 220),
    "pink": (255, 150, 200), "gray": (128, 128, 128),
    "grey": (128, 128, 128), "none": None,
}

THEMES = {
    "basic": {
        "accent": (100, 170, 255), "light": (150, 210, 255), "deep": (35, 75, 180),
        "dim": (110, 125, 155), "dimmer": (75, 85, 110),
        "green": (120, 220, 150), "red": (240, 130, 130),
        "yellow": (240, 210, 120), "white": (230, 235, 245),
        "cyan": (120, 200, 220), "magenta": (200, 150, 255),
        "purple": (170, 90, 220), "purple_d": (100, 40, 150),
        "logo_tl": (200, 235, 255), "logo_tr": (90, 160, 255),
        "logo_bl": (80, 150, 230), "logo_br": (30, 60, 150),
        "bg": None,
    },
    "halloween": {
        "accent": (255, 140, 60), "light": (255, 180, 100), "deep": (200, 90, 30),
        "dim": (150, 120, 130), "dimmer": (90, 70, 90),
        "green": (140, 230, 150), "red": (230, 70, 70),
        "yellow": (255, 210, 100), "white": (235, 220, 220),
        "cyan": (180, 140, 220), "magenta": (220, 140, 220),
        "purple": (170, 90, 220), "purple_d": (100, 40, 150),
        "logo_tl": (255, 190, 100), "logo_tr": (255, 130, 40),
        "logo_bl": (180, 100, 230), "logo_br": (100, 40, 150),
        "bg": (30, 15, 25),
    },
    "christmas": {
        "accent": (200, 30, 40), "light": (255, 90, 90), "deep": (140, 15, 25),
        "dim": (170, 150, 150), "dimmer": (100, 80, 80),
        "green": (60, 180, 90), "red": (240, 70, 70),
        "yellow": (250, 220, 110), "white": (250, 240, 235),
        "cyan": (180, 220, 220), "magenta": (230, 130, 130),
        "purple": (160, 80, 100), "purple_d": (90, 30, 40),
        "logo_tl": (255, 240, 220), "logo_tr": (220, 50, 50),
        "logo_bl": (255, 240, 220), "logo_br": (40, 150, 70),
        "bg": (20, 10, 10),
    },
    "neon": {
        "accent": (255, 60, 200), "light": (255, 140, 230), "deep": (180, 20, 130),
        "dim": (170, 130, 180), "dimmer": (110, 80, 130),
        "green": (90, 255, 200), "red": (255, 80, 130),
        "yellow": (255, 230, 100), "white": (250, 240, 250),
        "cyan": (60, 240, 240), "magenta": (255, 60, 200),
        "purple": (180, 90, 255), "purple_d": (110, 40, 180),
        "logo_tl": (255, 240, 250), "logo_tr": (60, 240, 240),
        "logo_bl": (255, 60, 200), "logo_br": (120, 30, 200),
        "bg": (15, 10, 25),
    },
    "ocean": {
        "accent": (60, 190, 220), "light": (130, 230, 250), "deep": (20, 100, 130),
        "dim": (120, 150, 170), "dimmer": (70, 95, 115),
        "green": (90, 220, 180), "red": (230, 110, 110),
        "yellow": (240, 200, 120), "white": (225, 240, 250),
        "cyan": (100, 220, 240), "magenta": (180, 140, 220),
        "purple": (130, 110, 200), "purple_d": (60, 50, 120),
        "logo_tl": (200, 240, 255), "logo_tr": (60, 190, 220),
        "logo_bl": (100, 220, 220), "logo_br": (20, 80, 130),
        "bg": (5, 15, 30),
    },
    "matrix": {
        "accent": (60, 255, 100), "light": (140, 255, 160), "deep": (10, 120, 40),
        "dim": (110, 160, 120), "dimmer": (60, 100, 70),
        "green": (60, 255, 100), "red": (200, 80, 80),
        "yellow": (200, 240, 100), "white": (200, 240, 210),
        "cyan": (100, 240, 200), "magenta": (140, 200, 120),
        "purple": (100, 180, 130), "purple_d": (40, 90, 60),
        "logo_tl": (220, 255, 220), "logo_tr": (60, 255, 100),
        "logo_bl": (140, 255, 160), "logo_br": (10, 80, 30),
        "bg": (0, 10, 0),
    },
    "sunset": {
        "accent": (255, 120, 80), "light": (255, 180, 130), "deep": (180, 60, 40),
        "dim": (180, 130, 140), "dimmer": (120, 80, 95),
        "green": (200, 200, 120), "red": (255, 100, 100),
        "yellow": (255, 220, 130), "white": (250, 230, 225),
        "cyan": (200, 160, 210), "magenta": (255, 130, 180),
        "purple": (200, 100, 180), "purple_d": (120, 50, 120),
        "logo_tl": (255, 240, 200), "logo_tr": (255, 120, 80),
        "logo_bl": (255, 160, 200), "logo_br": (140, 50, 130),
        "bg": (25, 10, 20),
    },
    "dracula": {
        "accent": (189, 147, 249), "light": (220, 190, 255), "deep": (140, 100, 200),
        "dim": (150, 145, 175), "dimmer": (98, 114, 164),
        "green": (80, 250, 123), "red": (255, 85, 85),
        "yellow": (241, 250, 140), "white": (248, 248, 242),
        "cyan": (139, 233, 253), "magenta": (255, 121, 198),
        "purple": (189, 147, 249), "purple_d": (110, 70, 170),
        "logo_tl": (255, 190, 230), "logo_tr": (189, 147, 249),
        "logo_bl": (139, 233, 253), "logo_br": (110, 70, 170),
        "bg": (40, 42, 54),
    },
    "nord": {
        "accent": (136, 192, 208), "light": (180, 220, 230), "deep": (70, 110, 130),
        "dim": (140, 160, 175), "dimmer": (76, 86, 106),
        "green": (163, 190, 140), "red": (191, 97, 106),
        "yellow": (235, 203, 139), "white": (236, 239, 244),
        "cyan": (143, 188, 187), "magenta": (180, 142, 173),
        "purple": (180, 142, 173), "purple_d": (110, 90, 120),
        "logo_tl": (236, 239, 244), "logo_tr": (136, 192, 208),
        "logo_bl": (143, 188, 187), "logo_br": (60, 90, 110),
        "bg": (46, 52, 64),
    },
    "gruvbox": {
        "accent": (254, 128, 25), "light": (250, 189, 47), "deep": (175, 60, 20),
        "dim": (168, 153, 132), "dimmer": (102, 92, 84),
        "green": (184, 187, 38), "red": (251, 73, 52),
        "yellow": (250, 189, 47), "white": (235, 219, 178),
        "cyan": (104, 157, 106), "magenta": (211, 134, 155),
        "purple": (177, 98, 134), "purple_d": (120, 60, 90),
        "logo_tl": (250, 220, 150), "logo_tr": (254, 128, 25),
        "logo_bl": (211, 134, 155), "logo_br": (140, 60, 30),
        "bg": (40, 40, 40),
    },
    "tokyo": {
        "accent": (122, 162, 247), "light": (170, 200, 255), "deep": (70, 100, 180),
        "dim": (130, 140, 180), "dimmer": (65, 72, 104),
        "green": (158, 206, 106), "red": (247, 118, 142),
        "yellow": (224, 175, 104), "white": (192, 202, 245),
        "cyan": (125, 207, 255), "magenta": (187, 154, 247),
        "purple": (187, 154, 247), "purple_d": (110, 90, 180),
        "logo_tl": (200, 220, 255), "logo_tr": (122, 162, 247),
        "logo_bl": (187, 154, 247), "logo_br": (60, 70, 130),
        "bg": (26, 27, 38),
    },
    "mono": {
        "accent": (200, 200, 200), "light": (240, 240, 240), "deep": (110, 110, 110),
        "dim": (150, 150, 150), "dimmer": (90, 90, 90),
        "green": (200, 200, 200), "red": (230, 230, 230),
        "yellow": (220, 220, 220), "white": (245, 245, 245),
        "cyan": (200, 200, 200), "magenta": (200, 200, 200),
        "purple": (180, 180, 180), "purple_d": (110, 110, 110),
        "logo_tl": (255, 255, 255), "logo_tr": (200, 200, 200),
        "logo_bl": (160, 160, 160), "logo_br": (80, 80, 80),
        "bg": None,
    },
}

THEME_KEYS = [
    "accent", "light", "deep", "dim", "dimmer",
    "green", "red", "yellow", "white", "cyan", "magenta",
    "purple", "purple_d",
    "logo_tl", "logo_tr", "logo_bl", "logo_br", "bg",
]


def parse_color(s):
    if s is None:
        return None
    s = str(s).strip().lower()
    if s in ("", "none", "null", "-"):
        return None
    if s in NAMED_COLORS:
        return NAMED_COLORS[s]
    if s.startswith("#") and len(s) == 7:
        try:
            return (int(s[1:3], 16), int(s[3:5], 16), int(s[5:7], 16))
        except Exception:
            return None
    if "," in s:
        try:
            parts = [int(x.strip()) for x in s.split(",")]
            if len(parts) == 3 and all(0 <= p <= 255 for p in parts):
                return tuple(parts)
        except Exception:
            return None
    return None


def color_to_hex(c):
    return f"#{c[0]:02x}{c[1]:02x}{c[2]:02x}" if c else "none"


def apply_theme(name, overrides=None):
    global C_ACCENT, C_LIGHT, C_DEEP, C_DIM, C_DIMMER
    global C_GRN, C_RED, C_YEL, C_WHITE, C_CYAN, C_MAG, C_PURP, C_PURP_D
    global LOGO_COLORS, BG_RGB

    base = dict(THEMES.get(name, THEMES["basic"]))
    if overrides:
        for k, v in overrides.items():
            if k in THEME_KEYS:
                base[k] = v

    C_ACCENT = rgb(*base["accent"])
    C_LIGHT = rgb(*base["light"])
    C_DEEP = rgb(*base["deep"])
    C_DIM = rgb(*base["dim"])
    C_DIMMER = rgb(*base["dimmer"])
    C_GRN = rgb(*base["green"])
    C_RED = rgb(*base["red"])
    C_YEL = rgb(*base["yellow"])
    C_WHITE = rgb(*base["white"])
    C_CYAN = rgb(*base["cyan"])
    C_MAG = rgb(*base["magenta"])
    C_PURP = rgb(*base["purple"])
    C_PURP_D = rgb(*base["purple_d"])
    LOGO_COLORS = (base["logo_tl"], base["logo_tr"], base["logo_bl"], base["logo_br"])
    BG_RGB = base.get("bg")


def supports_bg():
    if os.environ.get("WT_SESSION"):
        return True
    if os.environ.get("TERM_PROGRAM"):
        return True
    term = os.environ.get("TERM", "")
    if term and term != "dumb":
        return True
    if os.name != "nt":
        return True
    return False


def apply_bg():
    if not supports_bg():
        return
    try:
        if BG_RGB:
            r, g, b = BG_RGB
            sys.stdout.write(f"\033]11;#{r:02x}{g:02x}{b:02x}\007")
        else:
            sys.stdout.write("\033]111\007")
        sys.stdout.flush()
    except Exception:
        pass


def clear_screen():
    try:
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()
    except Exception:
        pass


def vis_len(s):
    return len(re.sub(r"\x1b\[[0-9;]*m", "", s))


def pad_to(s, w):
    return s + " " * max(0, w - vis_len(s))


def center(s, w):
    n = max(0, (w - vis_len(s)) // 2)
    return " " * n + s


HOME_DIR = str(Path.home())
USER_ENV = (os.environ.get("USERNAME") or os.environ.get("USER") or "").strip()


def _sanitize(text):
    if not isinstance(text, str):
        return text
    out = text.replace(HOME_DIR, "<home>")
    out = out.replace(HOME_DIR.replace("\\", "/"), "<home>")
    if USER_ENV and len(USER_ENV) >= 2:
        out = re.sub(r"([Uu]sers[\\/])" + re.escape(USER_ENV), r"\1<user>", out)
    return out


def _expand(text):
    if not isinstance(text, str):
        return text
    return text.replace("<home>", HOME_DIR).replace("<user>", USER_ENV)


def _expand_args(args):
    if isinstance(args, dict):
        return {k: _expand_args(v) for k, v in args.items()}
    if isinstance(args, list):
        return [_expand_args(v) for v in args]
    return _expand(args)


CONFIG_DIR = Path.home() / ".rora"
CONFIG_FILE = CONFIG_DIR / "config.json"
PROMPT_FILE = CONFIG_DIR / "system_prompt.txt"
SESSIONS_DIR = CONFIG_DIR / "sessions"
THEMES_FILE = CONFIG_DIR / "themes.json"


def _default_threads():
    """Физические ядра (обычно половина от логических)."""
    n = os.cpu_count() or 4
    if n >= 8:
        return n // 2
    return max(1, n // 2) if n >= 4 else n


DEFAULT_CONFIG = {
    "model": None, "models_dir": "~/models", "ctx": 4096, "gpu_layers": -1,
    "threads": None, "temp": 0.2, "max_tokens": 1536, "chat_format": None,
    "confirm": False, "theme": "basic", "theme_overrides": {},
}

DEFAULT_SYSTEM_PROMPT = """You are Rora, a terminal coding agent running on the user's own computer.
Working directory: {cwd}
Current date/time: {now}

You have broad access to this machine. You can inspect, create, edit, move and
delete files, run shell commands (optionally in a specific directory), open
files/folders in the OS file manager, launch browsers, check disk usage,
list and kill processes, set timers, show notifications, and read the clock.

PATHS: the user's home directory is written as <home>. Use <home>/Desktop/...
or ~/Desktop/... in your tool calls. The system will expand them. Never print
the real path, it contains private info.

USER IDENTITY: You do NOT know the user's name and you must NEVER say it, guess
it, or infer it from file paths, usernames in directories, environment
variables, or anything else. If the user asks "what is my name" or "do you
know my name", reply exactly: "I don't know your name." Do not invent a name.
Do not say "you told me" or "I remember". Do not repeat any name you may have
seen. This rule is absolute.

SAFETY: A denylist is enforced. Commands touching /, /etc, C:/Windows, ~/.ssh, etc.,
or doing rm -rf /, mkfs, dd of=/dev/..., shutdown, curl|bash, will be REJECTED with
"BLOCKED". Killing critical system processes is also blocked. Do not try to
bypass it. If a task needs a blocked path, ask the user.

TOOL PROTOCOL
-------------
To call a tool, output EXACTLY this block:

<tool_call>
{"name": "TOOL_NAME", "arguments": {"arg1": "val1"}}
</tool_call>

You may emit several <tool_call> blocks in one reply.
After each call the user replies with <tool_result>...</tool_result>.
Then either call more tools, or give a final answer WITHOUT any <tool_call> tags.

EXAMPLES
--------
User: create folder KAKA on my Desktop
You:
<tool_call>
{"name": "mkdir", "arguments": {"path": "<home>/Desktop/KAKA"}}
</tool_call>

User: сколько места на C:
You:
<tool_call>
{"name": "disk_usage", "arguments": {"path": "C:/"}}
</tool_call>

User: закрой хром
You:
<tool_call>
{"name": "process_kill", "arguments": {"name": "chrome"}}
</tool_call>

NEVER write bare function calls like mkdir("...") as plain text.
Always wrap them in a <tool_call> block.

TOOLS
-----
- list_dir(path=".")                          list files/folders (one level)
- read_file(path, start_line=1, end_line=0)   read text file
- write_file(path, content)                   create or overwrite a file
- edit_file(path, old_string, new_string)     exact substring replace
- append_file(path, content)                  append text to a file
- mkdir(path)                                 create directory (recursive)
- delete_path(path)                           delete file or directory
- move_path(src, dst)                         move or rename
- copy_path(src, dst)                         copy file or directory
- find_files(pattern, root=".")               glob search
- grep(pattern, root=".", glob="**/*")        regex search inside files
- open_path(path)                             open in file manager
- run_command(command, cwd=None)              run a shell command
- open_browser(browser="default", url=None)   launch browser
- get_time()                                  current local time
- get_date()                                  current local date + weekday
- process_list(filter="")                     list running processes
- process_kill(name)                          kill a process by name
- disk_usage(path="C:/")                      show disk usage
- timer(seconds, message)                     set a timer
- notify(title, message)                      show a notification

RULES
-----
- Always read a file before editing it.
- Prefer edit_file over write_file for small changes.
- Keep replies short. No filler. No apologies.
- After the task is done, give a 1-3 line summary and stop.
"""


def _ensure_config_dir():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def ensure_config_files():
    _ensure_config_dir()
    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(
            json.dumps(DEFAULT_CONFIG, indent=2, ensure_ascii=False),
            encoding="utf-8")
    if not PROMPT_FILE.exists():
        PROMPT_FILE.write_text(DEFAULT_SYSTEM_PROMPT, encoding="utf-8")
    if not THEMES_FILE.exists():
        THEMES_FILE.write_text("{}", encoding="utf-8")


def load_config():
    ensure_config_files()
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}
    merged = dict(DEFAULT_CONFIG)
    merged.update(data)
    return merged


def save_config(cfg):
    ensure_config_files()
    CONFIG_FILE.write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def load_user_themes():
    ensure_config_files()
    try:
        data = json.loads(THEMES_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def save_user_themes(t):
    ensure_config_files()
    THEMES_FILE.write_text(
        json.dumps(t, indent=2, ensure_ascii=False), encoding="utf-8")


def all_theme_names():
    names = list(THEMES.keys())
    for k in load_user_themes().keys():
        if k not in names:
            names.append(k)
    return names


def get_theme_dict(name):
    if name in THEMES:
        return dict(THEMES[name])
    ut = load_user_themes()
    if name in ut and isinstance(ut[name], dict):
        return dict(ut[name])
    return dict(THEMES["basic"])


def load_system_prompt():
    ensure_config_files()
    try:
        txt = PROMPT_FILE.read_text(encoding="utf-8")
        if txt.strip():
            return txt
    except Exception:
        pass
    return DEFAULT_SYSTEM_PROMPT


def render_prompt(cwd, now):
    template = load_system_prompt()
    return template.replace("{cwd}", cwd).replace("{now}", now)


def _sessions_dir():
    _ensure_config_dir()
    return SESSIONS_DIR


def list_sessions():
    d = _sessions_dir()
    sessions = []
    for f in d.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "id" in data:
                sessions.append(data)
        except Exception:
            continue
    sessions.sort(key=lambda s: s.get("updated", ""), reverse=True)
    return sessions


def save_session(sess):
    if not sess.get("messages"):
        return
    sess["updated"] = datetime.now().isoformat(timespec="seconds")
    d = _sessions_dir()
    (d / f"{sess['id']}.json").write_text(
        json.dumps(sess, ensure_ascii=False, indent=2), encoding="utf-8")


def new_session():
    now = datetime.now()
    return {
        "id": now.strftime("%Y%m%d_%H%M%S"),
        "title": "new chat",
        "created": now.isoformat(timespec="seconds"),
        "updated": now.isoformat(timespec="seconds"),
        "messages": [],
    }


def load_session(sid):
    p = _sessions_dir() / f"{sid}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def delete_session(sid):
    p = _sessions_dir() / f"{sid}.json"
    if p.exists():
        p.unlink()
        return True
    return False


def purge_all_sessions():
    d = _sessions_dir()
    n = 0
    for f in d.glob("*.json"):
        try:
            f.unlink()
            n += 1
        except Exception:
            continue
    return n


def set_title_if_empty(sess, first_user_msg):
    if sess.get("title") in ("new chat", "", None) and first_user_msg:
        t = first_user_msg.strip().replace("\n", " ")
        sess["title"] = t[:50] + ("..." if len(t) > 50 else "")


def list_ggufs(models_dir):
    d = Path(models_dir).expanduser()
    if not d.exists():
        return []
    try:
        return sorted(d.rglob("*.gguf"))
    except Exception:
        return []


DANGEROUS_COMMAND_PATTERNS = [
    r"\brm\s+(-[a-zA-Z]*\s+)*-[a-zA-Z]*[rR][a-zA-Z]*f[a-zA-Z]*\s+/(\s|$|\*)",
    r"\brm\s+(-[a-zA-Z]*\s+)*-[a-zA-Z]*f[a-zA-Z]*[rR][a-zA-Z]*\s+/(\s|$|\*)",
    r"\brm\s+-rf\s+~", r"\brm\s+-rf\s+\$HOME",
    r"\brm\s+-rf\s+\.(\s|$)", r"\brm\s+-rf\s+\*",
    r"\brm\s+-rf\s+/\*", r"\brm\s+-rf\s+/\.\.",
    r"\bmkfs(\.\w+)?\b", r"\bdd\s+.*of=/dev/",
    r"\bdd\s+.*of=\\\\\.\\", r"\bfdisk\b", r"\bparted\b",
    r"\bformat\s+[a-zA-Z]:", r"\bdiskpart\b",
    r":\(\)\s*\{\s*:\|:&\s*\}\s*;\s*:",
    r"\bwhile\s+true\s*;\s*do.*fork",
    r"\bshutdown\b", r"\breboot\b", r"\bhalt\b", r"\bpoweroff\b",
    r"\binit\s+0\b", r"\binit\s+6\b",
    r"\bsystemctl\s+(poweroff|reboot|halt)", r"\bStop-Computer\b",
    r"\bchmod\s+(-[a-zA-Z]+\s+)*777\s+/", r"\bchmod\s+-R\s+777\s+/",
    r"\bchown\s+-R\s+.*\s+/", r"\bicacls\s+[a-zA-Z]:\\\s+/grant",
    r"\btakeown\s+/f\s+[a-zA-Z]:\\",
    r"\bcurl\b[^|]*\|\s*(ba)?sh", r"\bwget\b[^|]*\|\s*(ba)?sh",
    r"\bcurl\b[^|]*\|\s*python", r"\bwget\b[^|]*\|\s*python",
    r"\bInvoke-WebRequest\b.*\|\s*iex", r"\biwr\b.*\|\s*iex",
    r"\breg\s+delete\b", r"\bbcdedit\b",
    r"\bvssadmin\s+delete\s+shadows", r"\bwbadmin\s+delete\b",
    r"\binsmod\b", r"\brmmod\b", r"\bmodprobe\s+-r\b",
    r"\buserdel\b", r"\bpasswd\s+root",
    r"\bnet\s+user\s+\S+\s+/delete", r"\bhistory\s+-c\b", r"\bshred\b",
]

PROTECTED_PATH_PATTERNS = [
    r"^/(bin|sbin|lib|lib64|usr|boot|dev|proc|sys|etc|var/lib|var/log)(/|$)",
    r"^/(System|Library)(/|$)",
    r"^[a-zA-Z]:\\Windows(\\|$)", r"^[a-zA-Z]:\\Program Files",
    r"^[a-zA-Z]:\\Program Files \(x86\)", r"^[a-zA-Z]:\\ProgramData(\\|$)",
    r"^[a-zA-Z]:\\\$Recycle\.Bin",
    r"/\.ssh(/|$)", r"/\.aws(/|$)", r"/\.gnupg(/|$)",
    r"/\.config/gcloud(/|$)", r"/\.kube(/|$)",
    r"/\.docker/config\.json$", r"/\.netrc$", r"/\.npmrc$",
    r"/\.pypirc$", r"/\.git-credentials$",
    r"/\.bashrc$", r"/\.zshrc$", r"/\.profile$", r"/\.bash_profile$",
]

PROTECTED_PROCESSES = {
    "system", "system idle process", "idle", "csrss", "csrss.exe",
    "wininit", "wininit.exe", "winlogon", "winlogon.exe",
    "services", "services.exe", "lsass", "lsass.exe",
    "smss", "smss.exe", "dwm", "dwm.exe",
    "registry", "memory compression", "svchost", "svchost.exe",
}


def is_dangerous_command(cmd):
    if not cmd:
        return True, "empty"
    low = cmd.strip()
    for pat in DANGEROUS_COMMAND_PATTERNS:
        if re.search(pat, low, re.IGNORECASE):
            return True, f"pattern '{pat}'"
    return False, ""


def is_protected_path(path):
    try:
        p = Path(path).expanduser()
        try:
            p = p.resolve(strict=False)
        except Exception:
            pass
        s = str(p).replace("\\", "/")
        for pat in PROTECTED_PATH_PATTERNS:
            if re.search(pat, s, re.IGNORECASE):
                return True, f"protected '{pat}'"
        return False, ""
    except Exception as e:
        return True, f"check failed: {e}"


STATE = {"cwd": os.getcwd(), "confirm": False, "theme": "basic",
         "theme_overrides": {}}


def _resolve(path):
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = Path(STATE["cwd"]) / p
    return p


def _blocked(reason):
    return f"BLOCKED by denylist: {reason}"


def list_dir(path="."):
    p = _resolve(path)
    if not p.exists():
        return f"ERROR: not found: {path}"
    if not p.is_dir():
        return f"ERROR: not a directory: {path}"
    items = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
    out = []
    for it in items[:1000]:
        if it.is_dir():
            out.append(f"  {it.name}/")
        else:
            try:
                sz = it.stat().st_size
            except OSError:
                sz = 0
            out.append(f"  {it.name}  ({sz} B)")
    return f"{p}\n" + ("\n".join(out) if out else "(empty)")


def read_file(path, start_line=1, end_line=0):
    p = _resolve(path)
    prot, why = is_protected_path(str(p))
    if prot:
        return _blocked(why)
    if not p.exists():
        return f"ERROR: not found: {path}"
    if p.is_dir():
        return f"ERROR: is a directory: {path}"
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"ERROR: {e}"
    lines = text.splitlines()
    s = max(1, int(start_line))
    e = len(lines) if not end_line else min(int(end_line), len(lines))
    chunk = lines[s - 1:e]
    numbered = "\n".join(f"{i + s:>5}  {ln}" for i, ln in enumerate(chunk))
    return f"{p}  ({len(lines)} lines total)\n{numbered}"


def write_file(path, content):
    p = _resolve(path)
    prot, why = is_protected_path(str(p))
    if prot:
        return _blocked(why)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"OK: wrote {len(content)} chars to {p}"


def append_file(path, content):
    p = _resolve(path)
    prot, why = is_protected_path(str(p))
    if prot:
        return _blocked(why)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(content)
    return f"OK: appended {len(content)} chars to {p}"


def edit_file(path, old_string, new_string):
    p = _resolve(path)
    prot, why = is_protected_path(str(p))
    if prot:
        return _blocked(why)
    if not p.exists():
        return f"ERROR: not found: {path}"
    text = p.read_text(encoding="utf-8")
    n = text.count(old_string)
    if n == 0:
        return "ERROR: old_string not found"
    if n > 1:
        return f"ERROR: old_string occurs {n} times"
    p.write_text(text.replace(old_string, new_string), encoding="utf-8")
    return f"OK: edited {p}"


def mkdir(path):
    p = _resolve(path)
    prot, why = is_protected_path(str(p))
    if prot:
        return _blocked(why)
    p.mkdir(parents=True, exist_ok=True)
    return f"OK: created {p}"


def _ask(msg):
    if not STATE["confirm"]:
        return True
    try:
        ans = input(f"{C_YEL}  ? {msg} [y/N] {R}").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return ans in ("y", "yes")


def delete_path(path):
    p = _resolve(path)
    prot, why = is_protected_path(str(p))
    if prot:
        return _blocked(why)
    if not p.exists():
        return f"ERROR: not found: {path}"
    if not _ask(f"delete {p}?"):
        return "DENIED"
    try:
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        return f"OK: deleted {p}"
    except Exception as e:
        return f"ERROR: {e}"


def move_path(src, dst):
    s, d = _resolve(src), _resolve(dst)
    for target in (s, d):
        prot, why = is_protected_path(str(target))
        if prot:
            return _blocked(why)
    if not s.exists():
        return f"ERROR: not found: {src}"
    if not _ask(f"move {s} -> {d}?"):
        return "DENIED"
    try:
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(s), str(d))
        return f"OK: {s} -> {d}"
    except Exception as e:
        return f"ERROR: {e}"


def copy_path(src, dst):
    s, d = _resolve(src), _resolve(dst)
    prot, why = is_protected_path(str(d))
    if prot:
        return _blocked(why)
    if not s.exists():
        return f"ERROR: not found: {src}"
    try:
        d.parent.mkdir(parents=True, exist_ok=True)
        if s.is_dir():
            shutil.copytree(s, d, dirs_exist_ok=True)
        else:
            shutil.copy2(s, d)
        return f"OK: {s} -> {d}"
    except Exception as e:
        return f"ERROR: {e}"


def find_files(pattern, root="."):
    r = _resolve(root)
    if not r.exists():
        return f"ERROR: not found: {root}"
    try:
        hits = [str(p) for p in r.glob(pattern) if p.is_file() or p.is_dir()]
    except Exception as e:
        return f"ERROR: {e}"
    hits = hits[:300]
    return "\n".join(hits) if hits else "(no matches)"


def grep(pattern, root=".", glob="**/*"):
    r = _resolve(root)
    if not r.exists():
        return f"ERROR: not found: {root}"
    try:
        rx = re.compile(pattern)
    except re.error as e:
        return f"ERROR: bad regex: {e}"
    out = []
    count = 0
    for p in r.glob(glob):
        if not p.is_file():
            continue
        prot, _ = is_protected_path(str(p))
        if prot:
            continue
        try:
            if p.stat().st_size > 2_000_000:
                continue
            for i, line in enumerate(
                    p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if rx.search(line):
                    out.append(f"{p}:{i}: {line[:200]}")
                    count += 1
                    if count >= 200:
                        return "\n".join(out) + "\n... (truncated)"
        except Exception:
            continue
    return "\n".join(out) if out else "(no matches)"


def open_path(path):
    p = _resolve(path)
    if not p.exists():
        return f"ERROR: not found: {path}"
    try:
        sysname = platform.system()
        if sysname == "Windows":
            os.startfile(str(p))
        elif sysname == "Darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return f"OK: opened {p}"
    except Exception as e:
        return f"ERROR: {e}"


def run_command(command, cwd=None):
    if not command:
        return "ERROR: empty"
    danger, why = is_dangerous_command(command)
    if danger:
        return _blocked(why)
    for token in re.findall(r"(?:[\w~./\\:-]+)", command):
        if len(token) < 3:
            continue
        if token.startswith(("/", "~", "./", "../")) or re.match(r"^[a-zA-Z]:", token):
            prot, pwhy = is_protected_path(token)
            if prot:
                return _blocked(pwhy)

    workdir = STATE["cwd"]
    if cwd:
        wp = Path(cwd).expanduser()
        if not wp.is_absolute():
            wp = Path(STATE["cwd"]) / wp
        prot, pwhy = is_protected_path(str(wp))
        if prot:
            return _blocked(f"cwd {pwhy}")
        if not wp.is_dir():
            return f"ERROR: cwd is not a directory: {wp}"
        workdir = str(wp.resolve())

    if not _ask(f"run (in {workdir}): {command}?"):
        return "DENIED"
    try:
        r = subprocess.run(command, shell=True, capture_output=True,
                           text=True, timeout=300, cwd=workdir)
        out = (r.stdout or "") + (r.stderr or "")
        if len(out) > 12000:
            out = out[:6000] + "\n... [truncated] ...\n" + out[-6000:]
        return f"exit={r.returncode}\n{out}"
    except subprocess.TimeoutExpired:
        return "ERROR: timeout"
    except Exception as e:
        return f"ERROR: {e}"


BROWSER_CMDS = {
    "chrome": "chrome", "google": "chrome",
    "edge": "msedge", "msedge": "msedge",
    "firefox": "firefox", "brave": "brave",
    "opera": "opera", "vivaldi": "vivaldi",
}


def _normalize_url(url):
    url = (url or "").strip()
    if not url:
        return ""
    if url.startswith(("http://", "https://", "file://", "ftp://", "about:")):
        return url
    if "." in url and " " not in url:
        return "https://" + url
    return "https://www.google.com/search?q=" + urllib.parse.quote(url)


def open_browser(browser="default", url=None):
    browser = (browser or "default").lower().strip()
    target_url = _normalize_url(url) if url else ""
    sysname = platform.system()
    try:
        if browser == "default" or browser not in BROWSER_CMDS:
            if target_url:
                webbrowser.open(target_url)
                return f"OK: opened {target_url}"
            webbrowser.open_new_tab("about:blank")
            return "OK: opened default browser"
        cmd_name = BROWSER_CMDS[browser]
        if sysname == "Windows":
            if target_url:
                subprocess.Popen(f'start "" {cmd_name} "{target_url}"', shell=True)
            else:
                subprocess.Popen(f'start "" {cmd_name}', shell=True)
            return f"OK: launched {browser}" + (f" with {target_url}" if target_url else "")
        elif sysname == "Darwin":
            args = ["open", "-a", browser.capitalize()]
            if target_url:
                args.append(target_url)
            subprocess.Popen(args)
            return f"OK: launched {browser}"
        else:
            args = [cmd_name] + ([target_url] if target_url else [])
            subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return f"OK: launched {browser}"
    except Exception as e:
        return f"ERROR: {e}"


def get_time():
    return datetime.now().strftime("%H:%M:%S")


def get_date():
    return datetime.now().strftime("%Y-%m-%d (%A)")


def process_list(filter=""):
    try:
        if os.name == "nt":
            cmd = "tasklist"
            if filter:
                cmd += f' /fi "imagename eq {filter}*"'
        else:
            cmd = "ps aux"
            if filter:
                cmd += f" | grep -i {filter}"
        r = subprocess.run(cmd, shell=True, capture_output=True,
                           text=True, timeout=20)
        out = (r.stdout or "") + (r.stderr or "")
        lines = out.splitlines()
        if len(lines) > 100:
            lines = lines[:100] + ["... (truncated)"]
        return "\n".join(lines) if lines else "(empty)"
    except Exception as e:
        return f"ERROR: {e}"


def process_kill(name):
    if not name:
        return "ERROR: empty name"
    low = name.lower().strip()
    base = low if low.endswith(".exe") else low + ".exe"
    if low in PROTECTED_PROCESSES or base in PROTECTED_PROCESSES:
        return f"BLOCKED: '{name}' is a critical system process"
    try:
        if os.name == "nt":
            r = subprocess.run(f'taskkill /f /im "{base}"', shell=True,
                               capture_output=True, text=True, timeout=20)
        else:
            r = subprocess.run(f'pkill -9 "{low}"', shell=True,
                               capture_output=True, text=True, timeout=20)
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        if len(out) > 2000:
            out = out[:2000] + "..."
        return f"exit={r.returncode}\n{out}"
    except Exception as e:
        return f"ERROR: {e}"


def disk_usage(path="C:/"):
    try:
        p = Path(path).expanduser() if path not in ("C:/", "C:", "C:\\") else Path(path)
        target = str(p)
        total, used, free = shutil.disk_usage(target)

        def fmt(n):
            for unit in ["B", "KB", "MB", "GB", "TB"]:
                if n < 1024:
                    return f"{n:.1f} {unit}"
                n /= 1024
            return f"{n:.1f} PB"

        pct = (free / total * 100) if total else 0
        return (f"{path}\n"
                f"  total: {fmt(total)}\n"
                f"  used:  {fmt(used)}\n"
                f"  free:  {fmt(free)}  ({pct:.1f}% free)")
    except Exception as e:
        return f"ERROR: {e}"


def notify(title, message):
    def _show():
        try:
            if os.name == "nt":
                import ctypes as _ct
                flags = 0x40 | 0x40000 | 0x10000
                _ct.windll.user32.MessageBoxW(0, str(message), str(title), flags)
            elif platform.system() == "Darwin":
                subprocess.Popen([
                    "osascript", "-e",
                    f'display notification "{message}" with title "{title}"'
                ])
            else:
                subprocess.Popen(["notify-send", str(title), str(message)])
        except Exception:
            pass

    threading.Thread(target=_show, daemon=True).start()
    return f"OK: notification shown ({title})"


def timer(seconds, message):
    try:
        secs = int(seconds)
    except (ValueError, TypeError):
        return "ERROR: seconds must be integer"
    if secs < 1 or secs > 86400:
        return "ERROR: seconds must be 1..86400"
    msg = str(message or "timer done")

    def _fire():
        time.sleep(secs)
        notify("Rora timer", msg)

    threading.Thread(target=_fire, daemon=True).start()
    mins = secs / 60
    when = f"{mins:.1f} min" if mins >= 1 else f"{secs}s"
    return f"OK: timer set for {when} -> \"{msg}\""


TOOLS = {
    "list_dir": list_dir, "read_file": read_file, "write_file": write_file,
    "append_file": append_file, "edit_file": edit_file, "mkdir": mkdir,
    "delete_path": delete_path, "move_path": move_path, "copy_path": copy_path,
    "find_files": find_files, "grep": grep, "open_path": open_path,
    "run_command": run_command, "open_browser": open_browser,
    "get_time": get_time, "get_date": get_date,
    "process_list": process_list, "process_kill": process_kill,
    "disk_usage": disk_usage, "timer": timer, "notify": notify,
}

TOOL_NAMES = list(TOOLS.keys())

TOOL_POSITIONAL = {
    "list_dir": ["path"],
    "read_file": ["path", "start_line", "end_line"],
    "write_file": ["path", "content"],
    "append_file": ["path", "content"],
    "edit_file": ["path", "old_string", "new_string"],
    "mkdir": ["path"], "delete_path": ["path"],
    "move_path": ["src", "dst"], "copy_path": ["src", "dst"],
    "find_files": ["pattern", "root"], "grep": ["pattern", "root", "glob"],
    "open_path": ["path"], "run_command": ["command", "cwd"],
    "open_browser": ["browser", "url"],
    "get_time": [], "get_date": [],
    "process_list": ["filter"], "process_kill": ["name"],
    "disk_usage": ["path"], "timer": ["seconds", "message"],
    "notify": ["title", "message"],
}


TOOL_CALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)
BARE_CALL_START_RE = re.compile(
    r"(?<![\w.])(" + "|".join(re.escape(n) for n in TOOL_NAMES) + r")\s*\("
)


def _try_parse_json(raw):
    candidates = [raw]
    fixed = re.sub(r'(?<!\\)\\(?![\\"/bfnrtu])', r"\\\\", raw)
    if fixed != raw:
        candidates.append(fixed)
    candidates.append(raw.replace("\\\\", "/").replace("\\", "/"))
    for c in candidates:
        try:
            return json.loads(c)
        except Exception:
            continue
    return None


def _find_balanced_close(s, open_idx):
    depth = 0
    in_str = None
    i = open_idx
    while i < len(s):
        ch = s[i]
        if in_str:
            if ch == "\\":
                i += 2
                continue
            if ch == in_str:
                in_str = None
            i += 1
            continue
        if ch in ('"', "'"):
            in_str = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _split_top_level(s):
    parts = []
    depth = 0
    cur = ""
    in_str = None
    i = 0
    while i < len(s):
        ch = s[i]
        if in_str:
            cur += ch
            if ch == "\\" and i + 1 < len(s):
                cur += s[i + 1]
                i += 2
                continue
            if ch == in_str:
                in_str = None
            i += 1
            continue
        if ch in ('"', "'"):
            in_str = ch
            cur += ch
        elif ch in "([{":
            depth += 1
            cur += ch
        elif ch in ")]}":
            depth -= 1
            cur += ch
        elif ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
        i += 1
    if cur.strip():
        parts.append(cur.strip())
    return parts


def _parse_value(s):
    s = s.strip()
    if not s:
        return ""
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        inner = s[1:-1]
        inner = inner.replace('\\"', '"').replace("\\'", "'")
        inner = inner.replace("\\n", "\n").replace("\\t", "\t")
        return inner
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


def _parse_args_str(args_str):
    parts = _split_top_level(args_str)
    pos, kw = [], {}
    for p in parts:
        eq = -1
        depth = 0
        in_str = None
        for i, ch in enumerate(p):
            if in_str:
                if ch == in_str and (i == 0 or p[i - 1] != "\\"):
                    in_str = None
                continue
            if ch in ('"', "'"):
                in_str = ch
            elif ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
            elif ch == "=" and depth == 0:
                eq = i
                break
        if eq > 0 and re.match(r"^\w+$", p[:eq].strip()):
            kw[p[:eq].strip()] = _parse_value(p[eq + 1:].strip())
        else:
            pos.append(_parse_value(p))
    return pos, kw


def _extract_bare_calls(text):
    cleaned = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    cleaned = re.sub(r"`[^`]*`", "", cleaned)
    calls = []
    for m in BARE_CALL_START_RE.finditer(cleaned):
        name = m.group(1)
        open_idx = m.end() - 1
        close_idx = _find_balanced_close(cleaned, open_idx)
        if close_idx == -1:
            continue
        args_str = cleaned[open_idx + 1:close_idx]
        pos, kw = _parse_args_str(args_str)
        names = TOOL_POSITIONAL.get(name, [])
        for i, v in enumerate(pos):
            if i < len(names):
                kw.setdefault(names[i], v)
        calls.append({"name": name, "arguments": kw})
    return calls


def parse_tool_calls(text):
    calls = []
    for m in TOOL_CALL_RE.finditer(text):
        raw = m.group(1).strip().rstrip(",")
        obj = _try_parse_json(raw)
        if isinstance(obj, dict) and "name" in obj:
            args = obj.get("arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}
            if not isinstance(args, dict):
                args = {}
            calls.append({"name": obj["name"], "arguments": args})
    if not calls:
        calls = _extract_bare_calls(text)
    return calls


class StreamFilter:
    OPEN = "<tool_call>"
    CLOSE = "</tool_call>"

    def __init__(self):
        self.buf = ""
        self.inside = False

    def feed(self, chunk):
        self.buf += chunk
        out = []
        while True:
            if self.inside:
                idx = self.buf.find(self.CLOSE)
                if idx == -1:
                    keep = len(self.CLOSE) - 1
                    if len(self.buf) > keep:
                        self.buf = self.buf[-keep:]
                    break
                self.buf = self.buf[idx + len(self.CLOSE):]
                self.inside = False
            else:
                idx = self.buf.find(self.OPEN)
                if idx == -1:
                    keep = len(self.OPEN) - 1
                    if len(self.buf) > keep:
                        out.append(self.buf[:-keep])
                        self.buf = self.buf[-keep:]
                    break
                if idx > 0:
                    out.append(self.buf[:idx])
                self.buf = self.buf[idx + len(self.OPEN):]
                self.inside = True
        return "".join(out)

    def flush(self):
        out = "" if self.inside else self.buf
        self.buf = ""
        self.inside = False
        return out


class Spinner:
    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, prefix):
        self.prefix = prefix
        self.stop_flag = threading.Event()
        self.thread = None

    def _spin(self):
        i = 0
        while not self.stop_flag.is_set():
            if is_visible_cached():
                frame = self.FRAMES[i % len(self.FRAMES)]
                try:
                    sys.stdout.write(f"\r{C_ACCENT}{frame}{R} {self.prefix}")
                    sys.stdout.flush()
                except Exception:
                    pass
            i += 1
            if self.stop_flag.wait(0.08):
                break

    def start(self):
        self.thread = threading.Thread(target=self._spin, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_flag.set()
        if self.thread:
            self.thread.join(timeout=0.4)
        try:
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()
        except Exception:
            pass


# ---------- PERF: buffered + focus-aware streaming ----------
BUFFER_FLUSH_INTERVAL = 0.033
BUFFER_FLUSH_SIZE = 200
_pending_output = []
_pending_lock = threading.Lock()


def _write_now(s):
    """Пишем в stdout только если окно видимо. Иначе копим."""
    if not s:
        return
    if is_visible_cached():
        try:
            sys.stdout.write(s)
            sys.stdout.flush()
        except Exception:
            with _pending_lock:
                _pending_output.append(s)
    else:
        with _pending_lock:
            _pending_output.append(s)


def _drain_pending():
    """Сбрасываем буфер когда окно снова видимо."""
    global _pending_output
    if not is_visible_cached():
        return
    with _pending_lock:
        if not _pending_output:
            return
        buf = "".join(_pending_output)
        _pending_output = []
    try:
        sys.stdout.write(buf)
        sys.stdout.flush()
    except Exception:
        with _pending_lock:
            _pending_output.insert(0, buf)


def stream_chat(llm, messages, max_tokens, temperature,
                spinner=None, buffered=True):
    full = ""
    sf = StreamFilter()
    first_token = True

    out_parts = []
    out_size = 0
    last_flush = time.time()

    def flush_now():
        nonlocal out_size, last_flush
        if not out_parts:
            return
        _write_now("".join(out_parts))
        out_parts.clear()
        out_size = 0
        last_flush = time.time()

    try:
        for chunk in llm.create_chat_completion(
            messages=messages, stream=True,
            max_tokens=max_tokens, temperature=temperature,
        ):
            delta = chunk["choices"][0].get("delta", {})
            piece = delta.get("content")
            if not piece:
                continue

            if first_token:
                if spinner is not None:
                    spinner.stop()
                first_token = False

            full += piece
            safe = sf.feed(piece)
            if not safe:
                continue

            if not buffered:
                _write_now(safe)
                continue

            out_parts.append(safe)
            out_size += len(safe)

            now = time.time()
            if (out_size >= BUFFER_FLUSH_SIZE
                    or (now - last_flush) >= BUFFER_FLUSH_INTERVAL
                    or "\n" in safe):
                flush_now()

        tail = sf.flush()
        if tail:
            if buffered:
                out_parts.append(tail)
            else:
                _write_now(tail)

    except KeyboardInterrupt:
        if buffered:
            flush_now()
        _write_now(f"\n{C_YEL}~ interrupted{R}\n")
    finally:
        if first_token and spinner is not None:
            spinner.stop()
        if buffered:
            flush_now()

    _write_now("\n")
    return full


def trim_messages(messages, keep_last=24):
    if len(messages) <= keep_last + 1:
        return messages
    return [messages[0]] + messages[-keep_last:]


def build_llm(model_path, cfg):
    n_threads = cfg.get("threads")
    if not n_threads:
        n_threads = _default_threads()
    n_ctx = int(cfg.get("ctx") or 4096)
    n_gpu = int(cfg.get("gpu_layers", -1))

    kwargs = dict(
        model_path=model_path,
        n_ctx=n_ctx,
        n_gpu_layers=n_gpu,
        n_threads=int(n_threads),
        n_batch=256,
        n_ubatch=256,
        use_mlock=True,
        use_mmap=True,
        verbose=False,
    )

    cf = cfg.get("chat_format")
    if cf:
        kwargs["chat_format"] = cf

    # flash_attn только если реально есть GPU-слои
    if n_gpu != 0:
        try:
            sig = inspect.signature(Llama.__init__)
            if "flash_attn" in sig.parameters:
                kwargs["flash_attn"] = False
        except Exception:
            pass

    try:
        return Llama(**kwargs)
    except TypeError:
        for key in ("flash_attn", "n_ubatch", "use_mlock"):
            kwargs.pop(key, None)
        return Llama(**kwargs)


def pick_model(models_dir):
    d = Path(models_dir).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    ggufs = sorted(d.rglob("*.gguf"))
    if not ggufs:
        print(f"{C_RED}no .gguf in {d}{R}")
        sys.exit(1)
    if len(ggufs) == 1:
        return str(ggufs[0])
    print(f"{C_ACCENT}models:{R}")
    for i, g in enumerate(ggufs, 1):
        print(f"  {B}{i}){R} {g.name}  {C_DIM}({g}){R}")
    while True:
        try:
            idx = int(input(f"{C_ACCENT}pick [1-{len(ggufs)}]: {R}").strip()) - 1
            if 0 <= idx < len(ggufs):
                return str(ggufs[idx])
        except (ValueError, KeyboardInterrupt):
            print()


RORA_LOGO = [
    "  ██████╗  ██████╗ ██████╗  █████╗ ",
    "  ██╔══██╗██╔═══██╗██╔══██╗██╔══██╗",
    "  ██████╔╝██║   ██║██████╔╝███████║",
    "  ██╔══██╗██║   ██║██╔══██╗██╔══██║",
    "  ██║  ██║╚██████╔╝██║  ██║██║  ██║",
    "  ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝",
]


def gradient_logo():
    c_tl, c_tr, c_bl, c_br = LOGO_COLORS
    n_rows = max(1, len(RORA_LOGO) - 1)
    out = []
    for i, line in enumerate(RORA_LOGO):
        t = i / n_rows
        left = lerp(c_tl, c_bl, t)
        right = lerp(c_tr, c_br, t)
        chars = list(line)
        n_cols = max(1, len(chars) - 1)
        buf = []
        for j, ch in enumerate(chars):
            c = lerp(left, right, j / n_cols)
            buf.append(f"\033[38;2;{c[0]};{c[1]};{c[2]}m{ch}")
        buf.append(R)
        out.append("".join(buf))
    return out


def make_box(title, body_lines, width, border_color, title_color=None):
    content_w = width - 4
    lines = [pad_to(l, content_w) for l in body_lines]
    t = f" {title} "
    tc = title_color or border_color
    dashes = max(0, width - 3 - len(t))
    top = (border_color + "╭─" + tc + t + border_color
           + "─" * dashes + "╮" + R)
    bot = border_color + "╰" + "─" * (width - 2) + "╯" + R
    out = [top]
    for ln in lines:
        out.append(border_color + "│ " + R + ln
                   + border_color + " │" + R)
    out.append(bot)
    return out


def render_welcome(model_path, sess, cfg, n_models):
    model_name = Path(model_path).stem
    if len(model_name) > 40:
        model_name = model_name[:37] + "..."

    W_L, W_M, W_R = 48, 36, 30
    cwd_display = _sanitize(STATE["cwd"])
    if len(cwd_display) > W_L - 6:
        cwd_display = "..." + cwd_display[-(W_L - 9):]

    logo = gradient_logo()
    left_body = [""]
    for l in logo:
        left_body.append(center(l, W_L - 4))
    left_body.append("")
    left_body.append(center(f"{C_LIGHT}welcome{R}", W_L - 4))
    left_body.append("")
    left_body.append(center(f"{C_WHITE}{model_name}{R}", W_L - 4))
    left_body.append(center(f"{C_DIMMER}{cwd_display}{R}", W_L - 4))
    left_body.append("")

    mid_body = [""]
    mid_body.append(f"  {C_ACCENT}sessions{R}")
    mid_body.append("")
    sessions = list_sessions()[:5]
    if sessions:
        for i, s in enumerate(sessions, 1):
            mark = f"{C_GRN}●{R}" if s.get("id") == sess.get("id") else f"{C_DIMMER}·{R}"
            title = s.get("title", "?")
            max_title = W_M - 4 - 6
            if len(title) > max_title:
                title = title[:max_title - 3] + "..."
            mid_body.append(f"  {mark} {C_LIGHT}{i}{R} {C_DIM}{title}{R}")
    else:
        mid_body.append(f"    {C_DIMMER}(empty){R}")
    mid_body.append("")
    cur = sess.get("title", "new chat")
    if len(cur) > W_M - 14:
        cur = cur[:W_M - 17] + "..."
    mid_body.append(f"  {C_ACCENT}now{R}  {C_WHITE}{cur}{R}")
    mid_body.append("")

    right_body = [""]
    right_body.append(f"  {C_ACCENT}theme{R}")
    right_body.append("")
    theme_name = STATE.get("theme", "basic")
    right_body.append(f"  {C_WHITE}{theme_name}{R}")
    bg_str = color_to_hex(BG_RGB) if BG_RGB else "terminal"
    right_body.append(f"  {C_DIM}bg{R}  {C_WHITE}{bg_str}{R}")
    right_body.append("")
    right_body.append(f"  {C_ACCENT}stats{R}")
    right_body.append("")
    right_body.append(f"  {C_DIM}models{R}  {C_WHITE}{n_models}{R}")
    right_body.append(f"  {C_DIM}ctx{R}     {C_WHITE}{cfg.get('ctx')}{R}")
    right_body.append(f"  {C_DIM}temp{R}    {C_WHITE}{cfg.get('temp')}{R}")

    h = max(len(left_body), len(mid_body), len(right_body))
    left_box  = make_box("Rora v1.7.3", left_body, W_L, C_ACCENT, C_LIGHT)
    mid_box   = make_box("sessions",  mid_body,  W_M, C_DIM,    C_ACCENT)
    right_box = make_box("meta",      right_body, W_R, C_DIM,    C_ACCENT)

    while len(left_box) < h + 2:
        left_box.insert(-1, C_ACCENT + "│ " + R + " " * (W_L - 4)
                        + C_ACCENT + " │" + R)
    while len(mid_box) < h + 2:
        mid_box.insert(-1, C_DIM + "│ " + R + " " * (W_M - 4)
                       + C_DIM + " │" + R)
    while len(right_box) < h + 2:
        right_box.insert(-1, C_DIM + "│ " + R + " " * (W_R - 4)
                         + C_DIM + " │" + R)

    print()
    for a, b, c in zip(left_box, mid_box, right_box):
        print(pad_to(a, W_L) + "  " + pad_to(b, W_M) + "  " + c)

    status_items = [
        (C_DIM, "config", C_DIMMER, str(CONFIG_FILE)),
        (C_DIM, "prompt", C_DIMMER, str(PROMPT_FILE)),
    ]
    if sess.get("messages"):
        status_items.append((C_DIM, "resumed", C_WHITE, sess.get("title", "?")))

    W_STATUS = W_L + W_M + W_R + 4
    inner = W_STATUS - 4
    lines = [""]
    for k, klbl, vv, vval in status_items:
        prefix = f"  {k}{klbl}{R}"
        prefix_spaces = len(klbl) + 2
        val_str = str(vval)
        max_val = inner - prefix_spaces - 2
        if len(val_str) > max_val:
            val_str = "..." + val_str[-(max_val - 3):]
        lines.append(prefix + "  " + vv + val_str + R)
    lines.append("")
    # INFO бокс — голубая рамка (было фиолетовое)
    status_box = make_box("info", lines, W_STATUS, C_ACCENT, C_LIGHT)
    for line in status_box:
        print(line)
    print()


def format_call_brief(name, args):
    if name in ("mkdir", "delete_path", "open_path", "list_dir",
                "read_file", "write_file", "append_file", "edit_file"):
        return args.get("path", "")
    if name in ("move_path", "copy_path"):
        return f"{args.get('src','')} → {args.get('dst','')}"
    if name == "run_command":
        cmd = args.get("command", "")
        cwd = args.get("cwd")
        if cwd:
            return f"[{cwd}] {cmd}"
        return cmd
    if name in ("find_files", "grep"):
        return args.get("pattern", "")
    if name == "open_browser":
        b = args.get("browser", "default")
        u = args.get("url", "") or ""
        return f"{b} {u}".strip()
    if name == "process_list":
        return args.get("filter", "") or "(all)"
    if name == "process_kill":
        return args.get("name", "")
    if name == "disk_usage":
        return args.get("path", "C:/")
    if name == "timer":
        s = args.get("seconds", "?")
        m = args.get("message", "")
        return f"{s}s · {m}"
    if name == "notify":
        t = args.get("title", "")
        m = args.get("message", "")
        return f"{t}: {m}"
    return ""


def print_tool_call(name, args):
    brief = format_call_brief(name, args)
    if len(brief) > 78:
        brief = brief[:75] + "..."
    print(f"  {C_ACCENT}○{R} {B}{C_LIGHT}{name}{R}  {C_DIM}{brief}{R}")


def print_tool_result(result):
    first = result.splitlines()[0] if result else ""
    if first.startswith("OK"):
        print(f"  {C_GRN}●{R} {C_DIM}{first}{R}")
    elif first.startswith("ERROR") or first.startswith("BLOCKED"):
        print(f"  {C_RED}✖{R} {C_RED}{first}{R}")
    elif first.startswith("DENIED"):
        print(f"  {C_YEL}●{R} {C_YEL}{first}{R}")
    elif first:
        print(f"  {C_DIMMER}· {first[:80]}{R}")


def print_status_line(model_path, elapsed, reply_chars):
    model_name = Path(model_path).stem
    if len(model_name) > 30:
        model_name = model_name[:27] + "..."
    tok_est = max(1, reply_chars // 4)
    body = f" {C_DIMMER}{model_name} · {elapsed:.1f}s · ~{tok_est} tok {R}"
    width = 70
    line_len = vis_len(body)
    left_pad = max(0, (width - line_len) // 2)
    print(f"\n{C_ACCENT}{'─' * left_pad}{R}{body}"
          f"{C_ACCENT}{'─' * max(0, width - line_len - left_pad)}{R}\n")


def show_sessions(sessions, current_id):
    if not sessions:
        print(f"  {C_DIM}no chats{R}")
        return
    for i, s in enumerate(sessions, 1):
        mark = f"{C_GRN}●{R}" if s.get("id") == current_id else f"{C_DIMMER}·{R}"
        updated = s.get("updated", "")[:16].replace("T", " ")
        title = s.get("title", "?")
        if len(title) > 48:
            title = title[:45] + "..."
        print(f"  {mark} {C_LIGHT}{i:>2}{R}  {C_WHITE}{title}{R}"
              f"  {C_DIMMER}{updated}{R}")


def show_models(models, current_path):
    if not models:
        print(f"  {C_DIM}no .gguf found{R}")
        return
    cur = str(Path(current_path).resolve()) if current_path else ""
    for i, m in enumerate(models, 1):
        try:
            size_mb = m.stat().st_size / (1024 * 1024)
            size = f"{size_mb:>6.0f} MB"
        except Exception:
            size = "     ? MB"
        mark = f"{C_GRN}●{R}" if str(m.resolve()) == cur else f"{C_DIMMER}·{R}"
        print(f"  {mark} {C_LIGHT}{i:>2}{R}  {C_WHITE}{m.name:<40}{R}"
              f"  {C_DIM}{size}  {m.parent}{R}")


def show_themes():
    names = all_theme_names()
    current = STATE.get("theme", "basic")
    user_themes = load_user_themes()

    print()
    print(f"  {C_ACCENT}themes{R}  {C_DIMMER}(current: {current}){R}")
    print()
    for n in names:
        t = get_theme_dict(n)
        a, l, p = t.get("accent"), t.get("light"), t.get("purple")
        swatch = ""
        if a:
            swatch += f"\033[38;2;{a[0]};{a[1]};{a[2]}m████{R} "
        if l:
            swatch += f"\033[38;2;{l[0]};{l[1]};{l[2]}m████{R} "
        if p:
            swatch += f"\033[38;2;{p[0]};{p[1]};{p[2]}m████{R} "
        bg = t.get("bg")
        if bg:
            swatch += f"\033[48;2;{bg[0]};{bg[1]};{bg[2]}m  bg  {R}"
        mark = f"{C_GRN}●{R}" if n == current else f"{C_DIMMER}·{R}"
        usr = f" {C_DIM}(user){R}" if n in user_themes else ""
        print(f"  {mark} {C_LIGHT}{n:<12}{R}  {swatch}{usr}")
    print()
    print(f"  {C_DIM}/theme <name>{R}         switch preset")
    print(f"  {C_DIM}/theme bg <#hex|none>{R}  terminal background")
    print(f"  {C_DIM}/theme edit <key> <v>{R}  edit one color")
    print(f"  {C_DIM}/theme reset{R}           drop overrides")
    print(f"  {C_DIM}/theme save <name>{R}     save as new preset")
    print()
    print(f"  {C_DIM}keys:{R}")
    keys = " ".join(THEME_KEYS)
    print(f"    {C_DIMMER}{keys}{R}")
    print(f"  {C_DIM}values:{R} #RRGGBB, R,G,B, name (red/blue/...), none")
    print()


def handle_theme_cmd(arg, cfg, redraw=None):
    parts = arg.split(maxsplit=2) if arg else []

    if not parts:
        show_themes()
        return cfg

    sub = parts[0].lower()

    if sub == "reset":
        overrides = {}
        apply_theme(STATE.get("theme", "basic"), overrides)
        cfg["theme_overrides"] = overrides
        save_config(cfg)
        if redraw:
            redraw()
        print(f"  {C_GRN}●{R} {C_DIM}overrides cleared{R}")
        return cfg

    if sub == "save":
        if len(parts) < 2:
            print(f"  {C_RED}✖ usage: /theme save <name>{R}")
            return cfg
        name = parts[1].strip().lower()
        current_theme = STATE.get("theme", "basic")
        overrides = STATE.get("theme_overrides", {})
        base = get_theme_dict(current_theme)
        base.update(overrides)
        ut = load_user_themes()
        ut[name] = base
        save_user_themes(ut)
        cfg["theme"] = name
        cfg["theme_overrides"] = {}
        STATE["theme"] = name
        STATE["theme_overrides"] = {}
        apply_theme(name, {})
        save_config(cfg)
        if redraw:
            redraw()
        print(f"  {C_GRN}●{R} {C_DIM}saved as '{name}'{R}")
        return cfg

    if sub == "bg":
        if len(parts) < 2:
            print(f"  {C_RED}✖ usage: /theme bg <color|#hex|none>{R}")
            return cfg
        c = parse_color(parts[1])
        if c is None and parts[1].strip().lower() not in ("none", "null", "-", "terminal", "reset"):
            print(f"  {C_RED}✖ could not parse color: {parts[1]}{R}")
            return cfg
        overrides = dict(STATE.get("theme_overrides", {}))
        overrides["bg"] = c
        STATE["theme_overrides"] = overrides
        apply_theme(STATE.get("theme", "basic"), overrides)
        cfg["theme_overrides"] = overrides
        save_config(cfg)
        apply_bg()
        val = color_to_hex(c) if c else "none"
        print(f"  {C_GRN}●{R} {C_DIM}background → {val}{R}")
        return cfg

    if sub == "edit":
        if len(parts) < 3:
            print(f"  {C_RED}✖ usage: /theme edit <key> <value>{R}")
            return cfg
        key = parts[1].strip().lower()
        val = parts[2].strip()
        if key not in THEME_KEYS:
            print(f"  {C_RED}✖ unknown key: {key}{R}")
            print(f"  {C_DIM}valid: {', '.join(THEME_KEYS)}{R}")
            return cfg
        c = parse_color(val)
        if c is None and val.lower() not in ("none", "null", "-"):
            print(f"  {C_RED}✖ could not parse: {val}{R}")
            return cfg
        overrides = dict(STATE.get("theme_overrides", {}))
        overrides[key] = c
        STATE["theme_overrides"] = overrides
        apply_theme(STATE.get("theme", "basic"), overrides)
        cfg["theme_overrides"] = overrides
        save_config(cfg)
        if key == "bg":
            apply_bg()
        print(f"  {C_GRN}●{R} {C_DIM}{key} → {color_to_hex(c) if c else 'none'}{R}")
        return cfg

    name = sub
    names = all_theme_names()
    if name not in names:
        print(f"  {C_RED}✖ unknown theme: {name}{R}")
        print(f"  {C_DIM}available: {', '.join(names)}{R}")
        return cfg
    overrides = {}
    STATE["theme"] = name
    STATE["theme_overrides"] = overrides
    apply_theme(name, overrides)
    cfg["theme"] = name
    cfg["theme_overrides"] = overrides
    save_config(cfg)
    if redraw:
        redraw()
    print(f"  {C_GRN}●{R} {C_DIM}theme → {name}{R}")
    return cfg


def show_help():
    W = 64
    box1 = make_box("general", [
        "",
        f"  {C_LIGHT}/new{R}              {C_DIM}start new chat{R}",
        f"  {C_LIGHT}/sessions{R}         {C_DIM}list saved chats{R}",
        f"  {C_LIGHT}/switch <n>{R}       {C_DIM}switch to chat #n{R}",
        f"  {C_LIGHT}/delete <n>{R}       {C_DIM}delete chat #n{R}",
        f"  {C_LIGHT}/purge{R}            {C_DIM}delete ALL chats{R}",
        f"  {C_LIGHT}/rename <title>{R}   {C_DIM}rename current chat{R}",
        f"  {C_LIGHT}/reset{R}            {C_DIM}clear current chat{R}",
        "",
    ], W, C_ACCENT, C_LIGHT)
    box2 = make_box("models & config", [
        "",
        f"  {C_LIGHT}/models{R}           {C_DIM}list .gguf files{R}",
        f"  {C_LIGHT}/model{R}            {C_DIM}show current model{R}",
        f"  {C_LIGHT}/model <n>{R}        {C_DIM}switch to model #n{R}",
        f"  {C_LIGHT}/reload-prompt{R}    {C_DIM}reload system_prompt.txt{R}",
        f"  {C_LIGHT}/config{R}           {C_DIM}show config paths{R}",
        "",
    ], W, C_ACCENT, C_LIGHT)
    box3 = make_box("theme", [
        "",
        f"  {C_LIGHT}/theme{R}            {C_DIM}list themes{R}",
        f"  {C_LIGHT}/theme <name>{R}     {C_DIM}switch preset{R}",
        f"  {C_LIGHT}/theme bg <c>{R}     {C_DIM}terminal background{R}",
        f"  {C_LIGHT}/theme edit <k> <v>{R} {C_DIM}edit a color{R}",
        f"  {C_LIGHT}/theme reset{R}      {C_DIM}drop overrides{R}",
        f"  {C_LIGHT}/theme save <name>{R} {C_DIM}save as preset{R}",
        "",
    ], W, C_ACCENT, C_LIGHT)
    box4 = make_box("shell & fs", [
        "",
        f"  {C_LIGHT}/cd <path>{R}        {C_DIM}change cwd{R}",
        f"  {C_LIGHT}/ls [path]{R}        {C_DIM}list files{R}",
        f"  {C_LIGHT}/open <path>{R}      {C_DIM}open in file manager{R}",
        f"  {C_LIGHT}/sh <cmd>{R}         {C_DIM}run shell command{R}",
        f"  {C_LIGHT}/help{R}             {C_DIM}this screen{R}",
        f"  {C_LIGHT}/exit{R}             {C_DIM}quit{R}",
        "",
    ], W, C_DIM, C_ACCENT)
    print()
    for b in (box1, box2, box3, box4):
        for line in b:
            print("  " + line)
        print()


def main():
    if _maybe_relaunch_in_cmd():
        print("launched")
        sys.exit(0)

    # повторно применяем настройки консоли в новом окне
    _setup_windows_console()

    ap = argparse.ArgumentParser()
    ap.add_argument("--model")
    ap.add_argument("--models-dir", default=None)
    ap.add_argument("--ctx", type=int, default=None)
    ap.add_argument("--gpu-layers", type=int, default=None)
    ap.add_argument("--threads", type=int, default=None)
    ap.add_argument("--temp", type=float, default=None)
    ap.add_argument("--max-tokens", type=int, default=None)
    ap.add_argument("--chat-format", default=None)
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--new", action="store_true")
    ap.add_argument("--session", default=None)
    ap.add_argument("--theme", default=None)
    ap.add_argument("--no-relaunch", action="store_true")
    ap.add_argument("--no-buffer", action="store_true")
    args = ap.parse_args()

    ensure_config_files()
    cfg = load_config()

    if args.model: cfg["model"] = args.model
    if args.models_dir: cfg["models_dir"] = args.models_dir
    if args.ctx is not None: cfg["ctx"] = args.ctx
    if args.gpu_layers is not None: cfg["gpu_layers"] = args.gpu_layers
    if args.threads is not None: cfg["threads"] = args.threads
    if args.temp is not None: cfg["temp"] = args.temp
    if args.max_tokens is not None: cfg["max_tokens"] = args.max_tokens
    if args.chat_format is not None: cfg["chat_format"] = args.chat_format
    if args.theme: cfg["theme"] = args.theme
    if args.confirm: cfg["confirm"] = True

    STATE["confirm"] = bool(cfg.get("confirm"))
    buffered = not args.no_buffer

    theme_name = cfg.get("theme") or "basic"
    overrides = cfg.get("theme_overrides") or {}
    if not isinstance(overrides, dict):
        overrides = {}
    clean_overrides = {}
    for k, v in overrides.items():
        if k not in THEME_KEYS:
            continue
        if isinstance(v, list) and len(v) == 3:
            clean_overrides[k] = tuple(v)
        elif v is None:
            clean_overrides[k] = None
        elif isinstance(v, tuple):
            clean_overrides[k] = v
    overrides = clean_overrides
    STATE["theme"] = theme_name
    STATE["theme_overrides"] = overrides
    apply_theme(theme_name, overrides)

    model_path = cfg.get("model")
    if model_path and not Path(model_path).expanduser().exists():
        print(f"{C_YEL}!{R} {C_DIM}model not found: {model_path}{R}")
        model_path = None
    if not model_path:
        model_path = pick_model(cfg.get("models_dir") or "~/models")
        cfg["model"] = model_path
        save_config(cfg)

    print(f"{C_DIM}loading{R} {C_LIGHT}{model_path}{R}")
    try:
        llm = build_llm(model_path, cfg)
    except Exception as e:
        print(f"{C_RED}load error: {e}{R}")
        sys.exit(1)

    if args.session:
        sess = load_session(args.session) or new_session()
    elif args.new:
        sess = new_session()
    else:
        sessions = list_sessions()
        sess = sessions[0] if sessions else new_session()

    def _sys_msg():
        return {"role": "system", "content": render_prompt(
            _sanitize(STATE["cwd"]),
            datetime.now().strftime("%Y-%m-%d %H:%M:%S (%A)"))}

    messages = [_sys_msg()]
    for m in sess.get("messages", []):
        messages.append(m)

    def redraw():
        clear_screen()
        apply_bg()
        n = len(list_ggufs(cfg.get("models_dir") or "~/models"))
        render_welcome(model_path, sess, cfg, n)

    apply_bg()
    render_welcome(model_path, sess, cfg,
                   len(list_ggufs(cfg.get("models_dir") or "~/models")))

    while True:
        try:
            user = input(f"{C_ACCENT}{B}you{R}{C_DIMMER} ›{R} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user:
            continue

        if user in ("/exit", "/quit", ":q"):
            save_session(sess)
            break

        if user == "/help":
            show_help()
            continue

        if user == "/theme" or user.startswith("/theme "):
            arg = user[6:].strip()
            cfg = handle_theme_cmd(arg, cfg, redraw=redraw)
            continue

        if user == "/new":
            save_session(sess)
            sess = new_session()
            messages = [_sys_msg()]
            print(f"  {C_GRN}●{R} {C_DIM}new chat{R}")
            continue

        if user == "/sessions":
            show_sessions(list_sessions(), sess.get("id"))
            continue

        if user == "/purge":
            try:
                ans = input(f"  {C_RED}delete ALL chats? type 'yes': {R}").strip().lower()
            except (EOFError, KeyboardInterrupt):
                ans = ""
            if ans == "yes":
                n = purge_all_sessions()
                sess = new_session()
                messages = [_sys_msg()]
                print(f"  {C_GRN}●{R} {C_DIM}purged {n} chats{R}")
            else:
                print(f"  {C_DIM}cancelled{R}")
            continue

        if user.startswith("/switch"):
            parts = user.split(maxsplit=1)
            if len(parts) < 2:
                show_sessions(list_sessions(), sess.get("id"))
                continue
            try:
                idx = int(parts[1].strip()) - 1
            except ValueError:
                print(f"  {C_RED}✖ usage: /switch <n>{R}")
                continue
            sessions = list_sessions()
            if 0 <= idx < len(sessions):
                save_session(sess)
                sess = sessions[idx]
                messages = [_sys_msg()]
                for m in sess.get("messages", []):
                    messages.append(m)
                print(f"  {C_GRN}●{R} {C_DIM}→ {sess.get('title','?')}{R}")
            else:
                print(f"  {C_RED}✖ out of range{R}")
            continue

        if user.startswith("/delete"):
            parts = user.split(maxsplit=1)
            if len(parts) < 2:
                print(f"  {C_RED}✖ usage: /delete <n>{R}")
                continue
            try:
                idx = int(parts[1].strip()) - 1
            except ValueError:
                print(f"  {C_RED}✖ usage: /delete <n>{R}")
                continue
            sessions = list_sessions()
            if 0 <= idx < len(sessions):
                victim = sessions[idx]
                if victim.get("id") == sess.get("id"):
                    print(f"  {C_YEL}!{R} {C_DIM}current → new{R}")
                    delete_session(victim["id"])
                    sess = new_session()
                    messages = [_sys_msg()]
                else:
                    delete_session(victim["id"])
                    print(f"  {C_GRN}●{R} {C_DIM}deleted{R}")
            else:
                print(f"  {C_RED}✖ out of range{R}")
            continue

        if user.startswith("/rename"):
            parts = user.split(maxsplit=1)
            if len(parts) < 2:
                print(f"  {C_RED}✖ usage: /rename <title>{R}")
                continue
            sess["title"] = parts[1].strip()[:60]
            save_session(sess)
            print(f"  {C_GRN}●{R} {C_DIM}renamed{R}")
            continue

        if user == "/models":
            models = list_ggufs(cfg.get("models_dir") or "~/models")
            show_models(models, model_path)
            continue

        if user.startswith("/model"):
            parts = user.split(maxsplit=1)
            if len(parts) == 1:
                print(f"  {C_DIM}current:{R} {model_path}")
                models = list_ggufs(cfg.get("models_dir") or "~/models")
                show_models(models, model_path)
                continue
            try:
                idx = int(parts[1].strip()) - 1
            except ValueError:
                print(f"  {C_RED}✖ usage: /model <n>{R}")
                continue
            models = list_ggufs(cfg.get("models_dir") or "~/models")
            if not (0 <= idx < len(models)):
                print(f"  {C_RED}✖ out of range{R}")
                continue
            new_path = str(models[idx])
            if str(Path(new_path).resolve()) == str(Path(model_path).resolve()):
                print(f"  {C_DIM}already on this model{R}")
                continue
            print(f"  {C_DIM}loading{R} {C_LIGHT}{new_path}{R}")
            try:
                new_llm = build_llm(new_path, cfg)
            except Exception as e:
                print(f"  {C_RED}✖ load failed: {e}{R}")
                continue
            try:
                del llm
            except Exception:
                pass
            llm = new_llm
            model_path = new_path
            cfg["model"] = new_path
            save_config(cfg)
            print(f"  {C_GRN}●{R} {C_DIM}switched → {Path(new_path).name}{R}")
            continue

        if user == "/reload-prompt":
            messages[0] = _sys_msg()
            print(f"  {C_GRN}●{R} {C_DIM}system prompt reloaded{R}")
            continue

        if user == "/config":
            print(f"  {C_DIM}config:{R}   {CONFIG_FILE}")
            print(f"  {C_DIM}prompt:{R}   {PROMPT_FILE}")
            print(f"  {C_DIM}themes:{R}   {THEMES_FILE}")
            print(f"  {C_DIM}sessions:{R} {SESSIONS_DIR}")
            print()
            for k, v in cfg.items():
                print(f"    {C_LIGHT}{k:<14}{R} = {C_WHITE}{v}{R}")
            continue

        if user == "/reset":
            sess["messages"] = []
            messages = [_sys_msg()]
            save_session(sess)
            print(f"  {C_DIM}~ cleared{R}")
            continue

        if user.startswith("/cd"):
            parts = user.split(maxsplit=1)
            target = parts[1].strip() if len(parts) > 1 else str(Path.home())
            p = Path(target).expanduser()
            if not p.is_absolute():
                p = Path(STATE["cwd"]) / p
            if p.is_dir():
                STATE["cwd"] = str(p.resolve())
                messages[0] = _sys_msg()
                print(f"  {C_GRN}●{R} {C_DIM}cwd → {_sanitize(STATE['cwd'])}{R}")
            else:
                print(f"  {C_RED}✖ not a dir{R}")
            continue

        if user.startswith("/ls"):
            parts = user.split(maxsplit=1)
            path = parts[1].strip() if len(parts) > 1 else "."
            print(list_dir(path))
            continue

        if user.startswith("/open"):
            parts = user.split(maxsplit=1)
            if len(parts) < 2:
                print(f"  {C_RED}✖ usage: /open <path>{R}")
            else:
                print(open_path(parts[1].strip()))
            continue

        if user.startswith("/sh "):
            cmd = user[4:].strip()
            danger, why = is_dangerous_command(cmd)
            if danger:
                print(f"  {C_RED}✖ BLOCKED: {why}{R}")
                continue
            try:
                r = subprocess.run(cmd, shell=True, cwd=STATE["cwd"])
                print(f"  {C_DIMMER}~ exit={r.returncode}{R}")
            except Exception as e:
                print(f"  {C_RED}✖ {e}{R}")
            continue

        set_title_if_empty(sess, user)
        sess["messages"].append({"role": "user", "content": user})
        messages.append({"role": "user", "content": user})

        t0 = time.time()
        reply_chars = 0

        for _ in range(30):
            trimmed = trim_messages(messages)
            spinner = Spinner(f"{C_CYAN}{B}rora{R}{C_DIMMER} ›{R}")
            spinner.start()
            reply = stream_chat(llm, trimmed,
                                int(cfg.get("max_tokens") or 1536),
                                float(cfg.get("temp") or 0.2),
                                spinner=spinner, buffered=buffered)
            if not reply.strip():
                _write_now(f"{C_CYAN}{B}rora{R}{C_DIMMER} ›{R} {C_DIMMER}(no output){R}\n")
            reply_chars += len(reply)
            calls = parse_tool_calls(reply)
            sess["messages"].append({"role": "assistant", "content": reply})
            messages.append({"role": "assistant", "content": reply})

            if not calls:
                print()
                break

            for tc in calls:
                name = tc.get("name")
                cargs = _expand_args(tc.get("arguments") or {})
                print_tool_call(name, cargs)
                fn = TOOLS.get(name)
                if fn is None:
                    result = f"ERROR: unknown tool '{name}'"
                else:
                    try:
                        result = fn(**cargs)
                    except TypeError as e:
                        result = f"ERROR: bad args: {e}"
                    except Exception as e:
                        result = f"ERROR: {e}"
                print_tool_result(result)
                safe_result = _sanitize(result)
                tool_msg = {"role": "user",
                            "content": f"<tool_result>\n{safe_result}\n</tool_result>"}
                sess["messages"].append(tool_msg)
                messages.append(tool_msg)
            print()

        elapsed = time.time() - t0
        print_status_line(model_path, elapsed, reply_chars)
        save_session(sess)

    print(f"  {C_DIMMER}bye{R}")


if __name__ == "__main__":
    main()
