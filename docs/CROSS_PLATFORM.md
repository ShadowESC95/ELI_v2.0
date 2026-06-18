# Cross-platform capability coverage

ELI is **model-, user-, and hardware-agnostic** and runs on **Linux, macOS, Windows, and
Android/Termux**, plus **headless / via the web server (FastAPI)**. This document is the honest
map of how each capability family behaves on each target.

## The backbone (why it's portable)
Every OS-touching operation routes through one of three cross-platform layers — never a raw
Linux call:
- **`eli/utils/platform_compat.py`** — open URL/file/app, notifications, clipboard, volume/mute,
  play-sound, key/type, user dirs. Branches for Linux / macOS / Windows / Android(Termux) / BSD,
  each guarded with `shutil.which` and degrading gracefully.
- **`eli/core/paths.py`** — all data/config/cache/log/models paths via `platformdirs`
  (XDG on Linux, `~/Library` on macOS, `%APPDATA%`/`%LOCALAPPDATA%` on Windows, sdcard on Android).
- **`eli/perception/os_controller.py`** / **`eli/system/portable_app_control.py`** — screenshots,
  app enumeration/control with per-OS implementations.

**No capability hard-crashes off Linux** — anything platform-specific is guarded and returns a
clean "unavailable" result instead of raising.

## Legend
✅ full · ⚠️ Linux/desktop-primary, graceful degrade elsewhere · 🖥️ needs a desktop (display/
input) — not on a headless server or Android · ➖ N/A on that platform

| Capability family | Linux | macOS | Windows | Android/Termux | Headless / Web API |
|---|:--:|:--:|:--:|:--:|:--:|
| Chat, reasoning, memory, RAG, KG, User Model | ✅ | ✅ | ✅ | ✅ | ✅ |
| Web search / news synthesis | ✅ | ✅ | ✅ | ✅ | ✅ |
| Code examine / repair / file analysis | ✅ | ✅ | ✅ | ✅ | ✅ |
| File ops + paths (data/config/models) | ✅ | ✅ | ✅ | ✅ | ✅ |
| Open URL / file / app | ✅ | ✅ | ✅ | ✅ (termux) | ✅ (URL/file) |
| Desktop notifications | ✅ | ✅ | ✅ (plyer) | ✅ (termux) | ➖ |
| Clipboard get/set | ✅ | ✅ | ✅ | ✅ (termux) | ➖ |
| Volume / mute | ✅ (pactl) | ✅ (osascript) | ✅ (pycaw) | ➖ | ➖ |
| Play sound | ✅ | ✅ | ✅ | ✅ (termux) | ➖ |
| Screenshot | ✅ | ✅ | ✅ | 🖥️ | ➖ |
| Type text / key press | ✅ | ✅ (pyautogui) | ✅ (pyautogui) | 🖥️ | ➖ |
| Voice STT / TTS | ✅ | ✅ | ✅ | ⚠️ (audio dev) | ➖ |
| Media control (play/pause/next) | ✅ (playerctl) | ⚠️ | ⚠️ | ⚠️ (termux) | ➖ |
| Window management (focus/move/tile) | ✅ (wmctrl) | ⚠️ | ⚠️ | ➖ | ➖ |
| Gaze cursor / AR avatar | ✅ | ⚠️ | ⚠️ | ➖ | ➖ |
| GUI (PySide6 desktop app) | ✅ | ✅ | ✅ | ➖ | ➖ |
| Web app / REST API (FastAPI server) | ✅ | ✅ | ✅ | ✅ (client) | ✅ |
| Scheduling, habits, proactive, reflection, self-improve | ✅ | ✅ | ✅ | ✅ | ✅ |
| LoRA fine-tuning (`training/`) | ✅ | ⚠️ (CPU/MPS) | ✅ | ➖ | ✅ |

## Notes on the ⚠️ rows (honest limitations)
- **Media control** uses `playerctl` (MPRIS) on Linux; on macOS/Windows/Android it falls back to
  best-effort and may report "no player" rather than controlling a specific app. (Media *playback*
  via `play_sound` is fully cross-platform.)
- **Window management** (`wmctrl`/`xdotool`) is X11/Linux-centric; on macOS/Windows these actions
  degrade gracefully (return "not available") — they don't crash.
- **Gaze/AR** needs a camera + display and `opencv`; desktop-only, Linux-tested.
- These are *guarded* — they never raise; they return a clean unavailable result and ELI says so.

## The "Flask" (headless / web server) axis
The FastAPI server (`api/server.py`, see `docs/SERVER_AND_WEB_APP.md`) exposes `POST /v1/chat`
and `POST /v1/execute`. Through it, **every capability that doesn't require a local display or
input device works** — chat, memory, search, code, file ops, scheduling, status, open-URL. The
🖥️ rows (screenshot, type, gaze, window-mgmt, GUI) inherently need a desktop session and so are
not available over a remote/headless API — by nature, not by bug. A phone talking to a
desktop-hosted server gets the full *assistant*; the desktop-control actions run on the host.

## System dependencies (the binaries pip can't install)
**Core ELI — chat, memory, RAG, GGUF inference, the GUI, and the web server — needs only the
pip packages** and works right after install with no system tools. Some *optional* features need
OS-level binaries; the installers handle these best-effort:

| Feature | System dep | Linux (`install.sh`) | macOS (`install.sh`) | Windows (`install.ps1`) |
|---|---|---|---|---|
| Screen OCR | `tesseract` | apt/dnf/pacman | brew | winget (UB-Mannheim) |
| Voice input (mic) | PortAudio | apt/dnf/pacman | brew | bundled in the PyAudio wheel |
| Media playback / Whisper | `ffmpeg`, `mpv` | apt/dnf/pacman | brew | winget (FFmpeg) |
| Desktop control | xdotool, wmctrl, scrot, xclip/wl-clipboard, libnotify | apt/dnf/pacman | native APIs | native APIs |
| GPU offload | CUDA toolkit / Metal | `--install-cuda` (apt/dnf/pacman) | Metal (built in) | `/cuda` (winget) |
| Web automation | playwright browsers | `playwright install` | `playwright install` | `playwright install` |
| Volume / clipboard / notifications | — | system tools above | native (osascript/pbcopy) | native (pycaw/clip/plyer) |

The installer installs these **when a package manager + sudo/admin is available**; otherwise it
**prints the exact command** so you can run it. None are required for ELI to start — missing ones
only disable that one optional feature (gracefully).

## Verifying on your platform
- `python -c "from eli.utils.platform_compat import normalize_platform; print(normalize_platform())"`
  → prints `linux`/`macos`/`windows`/`android`.
- Each OS-action returns `{"ok": false, ...}` with a clear reason when a backend is missing — so
  you can see degradation explicitly rather than guessing.
