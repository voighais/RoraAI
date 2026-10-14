<div align="center">

# Rora

**Local AI agent with full access to your computer.**
Works offline. No API keys. No subscriptions. One file.

[![python](https://img.shields.io/badge/python-3.9+-3776ab?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![license](https://img.shields.io/badge/license-MIT-64aaff?style=flat-square)](LICENSE)
[![deps](https://img.shields.io/badge/dependencies-1-78dc96?style=flat-square)](https://pypi.org/project/llama-cpp-python/)
[![telegram](https://img.shields.io/badge/telegram-@voighais-64aaff?style=flat-square&logo=telegram&logoColor=white)](https://t.me/voighais)
[![github](https://img.shields.io/badge/github-voighais-aa5adc?style=flat-square&logo=github&logoColor=white)](https://github.com/voighais)

</div>

---

Rora turns any local GGUF model into a terminal coding agent — like Claude Code, but running on your own machine, on your own model, with your own rules.

It reads files. Writes files. Runs commands. Opens browsers. Kills processes. Checks disk usage. Sets timers. All offline. All free. All yours.

**One file. One dependency. 90 KB of Python.**

---

## Example

```text
you > создай папку KAKA на рабочем столе

rora > ○ mkdir  <home>/Desktop/KAKA
       ● OK: created <home>/Desktop/KAKA

       Готово. Папка KAKA на рабочем столе.

       ──── Qwen2.5-7B · 1.2s · ~12 tok ────
```

```text
you > сколько места на C:

rora > ● disk_usage  C:/
       ● C:/  total: 476.9 GB  used: 312.4 GB  free: 164.5 GB (34.5%)
```

```text
you > закрой хром

rora > ● process_kill  chrome
       ● exit=0  SUCCESS: terminated process "chrome.exe"
```

---

## Why

Most AI agents need internet, an account, and a paid subscription. Rora doesn't.

- **Offline** — works without internet, permanently
- **Free** — no API keys, no tokens, no subscriptions
- **Private** — your data never leaves your machine
- **Yours** — one Python file, you can read every line
- **Portable** — runs on a laptop, desktop, potato, anything with Python

If your internet dies — it still works.
If OpenAI bans you — it still works.
If you're in a country where cloud AI is blocked — it still works.

---

## Features

### Files
Create, read, edit, append, move, copy, delete. Recursive. Glob search. Regex grep inside files.

### Shell
Run any command, optionally in a specific directory. 300 second timeout. Full stdout + stderr returned.

### Browser
Launch Chrome, Edge, Firefox, Brave, Opera, or Vivaldi with any URL. If you pass a search query — it goes to Google.

### System
Disk usage, current time, current date, process list, kill by name, popup notifications, timers.

### Safety
- Denylist with 45+ patterns (`rm -rf /`, `mkfs`, `shutdown`, `curl | bash`)
- Protected paths (`C:\Windows`, `~/.ssh`, `~/.aws`, `/etc`, `/usr`)
- Protected processes (`csrss.exe`, `winlogon.exe`, `lsass.exe`)
- Optional `--confirm` mode for paranoid users

### Quality of life
- Sessions with auto-save (`~/.rora/sessions/`)
- 12 built-in themes + custom colors via `/theme`
- Switch models live without restarting (`/model <n>`)
- Custom system prompt in a text file (`~/.rora/system_prompt.txt`)
- Auto-relaunch in a fresh cmd window on Windows

---

## Install

**Requires Python 3.9+ and one dependency.**

```bash
# 1. install llama.cpp bindings
pip install llama-cpp-python

# 2. download rora.py from this repo

# 3. grab a model (.gguf) — see Models section below
#    put it in ~/models/ or pass --model

# 4. run
python rora.py
```

On Windows Rora **auto-relaunches itself in a fresh cmd window** — no bat files needed. To disable, pass `--no-relaunch`.

---

## Quick start

```bash
you > создай папку KAKA на рабочем столе
you > открой хром и ютуб
you > сколько места на C:
you > закрой хром
you > напомни через 5 минут выпить чай
you > какой сегодня день?
you > прочитай calculator.py и объясни что он делает
```

Rora understands plain language. No need to memorize commands — just say what you want.

---

## Commands

### Chats

| Command | Description |
|---|---|
| `/new` | start a new chat (current one is saved) |
| `/sessions` | list all saved chats |
| `/switch <n>` | switch to chat number n |
| `/delete <n>` | delete chat n |
| `/purge` | delete **ALL** chats (asks for confirmation) |
| `/rename <title>` | rename current chat |
| `/reset` | clear current chat history |

### Models & config

| Command | Description |
|---|---|
| `/models` | list all `.gguf` files in `~/models` |
| `/model` | show current model |
| `/model <n>` | switch to model #n without restart |
| `/reload-prompt` | reload `~/.rora/system_prompt.txt` |
| `/config` | show config paths and values |

### Themes

| Command | Description |
|---|---|
| `/theme` | list all presets |
| `/theme <name>` | switch theme |
| `/theme bg <color>` | set terminal background |
| `/theme edit <key> <value>` | change one color |
| `/theme reset` | drop custom overrides |
| `/theme save <name>` | save current as new preset |

### Shell & files

| Command | Description |
|---|---|
| `/cd <path>` | change working directory |
| `/ls [path]` | list files |
| `/open <path>` | open in system file manager |
| `/sh <cmd>` | run a shell command manually |

### Misc

| Command | Description |
|---|---|
| `/help` | help screen |
| `/exit` | save and quit |

---

## Tools

The model calls these automatically — you just describe the task.

| Tool | What it does |
|---|---|
| `list_dir(path)` | list files and folders |
| `read_file(path, start, end)` | read a text file |
| `write_file(path, content)` | create or overwrite a file |
| `edit_file(path, old, new)` | exact substring replace |
| `append_file(path, content)` | append to a file |
| `mkdir(path)` | create directory (recursive) |
| `delete_path(path)` | delete file or directory |
| `move_path(src, dst)` | move or rename |
| `copy_path(src, dst)` | copy file or directory |
| `find_files(pattern, root)` | glob search (`**/*.py`) |
| `grep(pattern, root, glob)` | regex search inside files |
| `open_path(path)` | open in OS file manager |
| `run_command(cmd, cwd)` | run shell command, optionally in cwd |
| `open_browser(browser, url)` | launch a browser with URL |
| `get_time()` | current time |
| `get_date()` | current date |
| `process_list(filter)` | list running processes |
| `process_kill(name)` | kill a process by name |
| `disk_usage(path)` | show total / used / free space |
| `timer(seconds, message)` | set a timer with notification |
| `notify(title, message)` | show a system popup |

---

## Models

Rora works with **any `.gguf` model** produced by `llama.cpp`. Tested with:

- Qwen 2.5 / 2.5-Coder — 3B, 7B, 14B, 32B, 72B
- Llama 3.1 / 3.2 / 3.3 — 1B, 3B, 8B, 70B
- DeepSeek-Coder-V2 — Lite, V3
- Mistral / Mixtral — 7B, 8x7B
- Hermes 3 — 3B, 8B, 70B
- Gemma 2 / 3 — 2B, 7B, 9B, 27B
- Phi-3 / Phi-4 — mini, 14B
- Yi 1.5 — 6B, 9B, 34B

### Picking a model for your hardware

| VRAM / RAM | Recommended model | Size (Q4) |
|---|---|---|
| 4 GB | Qwen2.5-3B, Llama-3.2-3B | ~2 GB |
| 6 GB | Qwen2.5-7B, Mistral-7B | ~4.5 GB |
| 8 GB | Qwen2.5-Coder-7B, Hermes-3-8B | ~5 GB |
| 12 GB | Qwen2.5-14B, Phi-4-14B | ~9 GB |
| 16-24 GB | Qwen2.5-32B, Mixtral-8x7B | ~20 GB |
| 24+ GB | Llama-3.3-70B, Qwen2.5-72B | ~40+ GB |
| CPU only | Qwen2.5-3B, Gemma-2-2B | works, slow |

**Rule of thumb:** `Q4_K_M` quant is the sweet spot. Use `Q8_0` if you have spare memory, `Q3_K_M` if you're tight.

### Where to download

- **HuggingFace** — search for `bartowski`, `TheBloke`, `Qwen`, `unsloth` — they upload GGUF quants
- **LM Studio** — built-in search, downloads GGUF directly
- **Ollama** — `ollama pull qwen2.5` (own format, convertible to GGUF)

Put `.gguf` files in `~/models/` and Rora finds them automatically, or pass `--model /path/to/model.gguf`.

---

## Config

All settings live in `~/.rora/`:

```text
~/.rora/
├── config.json         settings
├── system_prompt.txt   model instructions (edit in notepad)
├── themes.json         custom theme presets
└── sessions/
    ├── 20261014_120000.json
    └── 20261014_130000.json
```

### config.json

```json
{
  "model": null,
  "models_dir": "~/models",
  "ctx": 8192,
  "gpu_layers": -1,
  "threads": null,
  "temp": 0.2,
  "max_tokens": 2048,
  "chat_format": null,
  "confirm": false,
  "theme": "basic",
  "theme_overrides": {}
}
```

CLI flags override config values. Example:

```bash
python rora.py --ctx 4096 --temp 0.1 --threads 6
```

### system_prompt.txt

Edit this to customize how Rora behaves. After editing, run `/reload-prompt` inside Rora — no restart needed.

---

## Safety

Rora has a **denylist** that blocks dangerous operations **before** they run. It's always on, even without `--confirm`.

### Blocked commands (45+ patterns)

```text
rm -rf /          mkfs.*            dd of=/dev/*
rm -rf ~          fdisk             parted
shutdown          reboot            halt
chmod -R 777 /    chown -R /        icacls /grant
curl | bash       wget | sh         iwr | iex
reg delete        bcdedit           vssadmin delete
:(){ :|:& };:     userdel           passwd root
```

### Protected paths

```text
/bin  /sbin  /lib  /usr  /boot  /dev  /proc  /sys  /etc  /var/lib
/System  /Library
C:\Windows  C:\Program Files  C:\ProgramData
~/.ssh  ~/.aws  ~/.gnupg  ~/.config/gcloud  ~/.kube
~/.netrc  ~/.npmrc  ~/.pypirc  ~/.git-credentials
~/.bashrc  ~/.zshrc  ~/.profile  ~/.bash_profile
```

### Protected processes

`csrss.exe`, `winlogon.exe`, `lsass.exe`, `services.exe`, `wininit.exe`, `smss.exe`, `dwm.exe`, `svchost.exe` — cannot be killed.

### Confirm mode

```bash
python rora.py --confirm
```

Adds `[y/N]` prompts for `run_command`, `delete_path`, `move_path`. Use this if you don't fully trust the model yet.

---

## Themes

12 built-in presets:

```text
basic      halloween      christmas      neon
ocean      matrix         sunset         dracula
nord       gruvbox        tokyo          mono
```

Switch live with `/theme <name>`. Customize any color:

```text
/theme edit accent #ff64c8
/theme edit red 255,0,0
/theme edit logo_tl 200,240,255
/theme bg #1a1a2e
```

18 customizable fields: `accent`, `light`, `deep`, `dim`, `dimmer`, `green`, `red`, `yellow`, `white`, `cyan`, `magenta`, `purple`, `purple_d`, `logo_tl`, `logo_tr`, `logo_bl`, `logo_br`, `bg`.

Save your setup as a preset:

```text
/theme save mytheme
```

Persists in `~/.rora/themes.json`.

---

## How it works

```text
your message
    │
    ▼
Rora sends it to the model (Qwen / Llama / etc.)
    │
    ▼
model writes a tool call inside <tool_call>{...}</tool_call>
    │
    ▼
StreamFilter hides the tool call from you — you see only clean text
    │
    ▼
parse_tool_calls extracts the JSON
    │
    ▼
_expand_args swaps <home> back to the real path
    │
    ▼
is_protected_path checks the path is safe
    │
    ▼
the Python function runs on your actual disk
    │
    ▼
result goes back to the model as <tool_result>
    │
    ▼
model generates a final answer
    │
    ▼
session saved to ~/.rora/sessions/
```

Model decides **what** to do. Rora does **how**. You see only the outcome.

---

## CLI flags

```bash
python rora.py [flags]

--model PATH          path to .gguf (overrides config)
--models-dir PATH     folder with .gguf files
--ctx N               context size (default 8192)
--gpu-layers N        -1 = all on GPU, 0 = CPU only
--threads N           CPU threads (default: os.cpu_count())
--temp F              temperature (default 0.2)
--max-tokens N        max tokens per reply (default 2048)
--chat-format NAME    override chat template
--confirm             ask before run / delete / move
--new                 start a fresh session
--session ID          resume a specific session
--theme NAME          theme on startup
--no-relaunch         don't spawn a new cmd on Windows
```

---

## Examples

### Create a Python script

```text
you > сделай калькулятор на питоне на рабочем столе

rora > ○ write_file  <home>/Desktop/calculator.py
       ● OK: wrote 676 chars

       Готово. calculator.py на рабочем столе.
```

### Check disk, kill a process, set a timer

```text
you > сколько места на C:
rora > ● disk_usage  C:/
       ● C:/  total: 476.9 GB  used: 312.4 GB  free: 164.5 GB (34.5%)

you > закрой хром
rora > ● process_kill  chrome
       ● exit=0  SUCCESS: terminated process "chrome.exe"

you > напомни через 10 минут проверить билд
rora > ● timer  600s · проверить билд
       ● OK: timer set for 10.0 min
```

### Read a file

```text
you > прочитай pom.xml и скажи какие зависимости

rora > ● read_file  <home>/Desktop/my_plugin/pom.xml
       ● 48 lines total

       В pom.xml одна зависимость: paper-api 1.16.5-R0.1-SNAPSHOT
       (scope: provided). Target: Java 16.
```

---

## Requirements

- **Python** — 3.9 or newer
- **`llama-cpp-python`** — the only dependency
- **RAM / VRAM** — depends on model size (see table above)
- **OS** — Windows 10/11, Linux, macOS

### GPU acceleration (optional)

```bash
# NVIDIA (CUDA)
CMAKE_ARGS="-DGGML_CUDA=on" pip install llama-cpp-python --upgrade --force-reinstall

# Apple Silicon (Metal)
CMAKE_ARGS="-DGGML_METAL=on" pip install llama-cpp-python --upgrade --force-reinstall

# AMD / Intel (Vulkan)
CMAKE_ARGS="-DGGML_VULKAN=on" pip install llama-cpp-python --upgrade --force-reinstall
```

---

## License

MIT. Do whatever you want. No warranty.

---

## Links

- **Telegram** — [@voighais](https://t.me/voighais)
- **GitHub** — [github.com/voighais](https://github.com/voighais)
- **Issues** — [github.com/voighais/rora/issues](https://github.com/voighais/rora/issues)

---

<div align="center">

**Rora** — local AI agent for those who are tired of clouds.

</div>
