# Cross-platform capability coverage

ELI is **model-, user-, and hardware-agnostic** and runs on **Linux, macOS, Windows, and
Android/Termux**, plus **headless / via the web server (FastAPI)**. This document is the honest
map of how each capability family behaves on each target.

## Tested on — what's actually been run (2026-07-04)

The matrix below is **code coverage** — how each capability is *implemented* per OS. This bit is
separate and more honest: what I've genuinely **run**.

- **Run-verified, end to end:** **Linux (x86_64) + NVIDIA.** Install, first-run, the full test
  suite (7,300+ passing), voice, vision, the server — all of it. This is the tested path.
- **AppImage engine run-verified across the mainstream distros (2026-07-18, v2.1.18):** the shipped
  `.AppImage` was extracted and driven through a **real chat turn** (full router → agent bus →
  memory → persona → streaming pipeline, bundled embedder loaded) in fresh containers of
  **Arch, Ubuntu, Debian, Fedora, and openSUSE Tumbleweed** — all pass, all on the AppImage's own
  bundled Python 3.11 (so Arch's system Python 3.14 is irrelevant), no generator-repr leak. The
  AppImage is self-contained; it does not use the host's Python or package manager. *Note: this was
  the **headless engine** path — it never loads the Qt GUI's xcb platform plugin, which is why the
  GUI-only `libxcb-cursor` gap below went unnoticed until v2.1.20.*
- **AppImage desktop GUI verified on Arch (2026-07-20, v2.1.20):** ran the graphical app on a clean
  Arch VM (XFCE). Confirmed the engine loads and the local database initialises with no error. Found
  and fixed a real gap: the Qt 6.5+ **xcb platform plugin needs `libxcb-cursor.so.0`**, which the
  AppImage did not bundle — so on a lean system without it the window failed to open with
  *"xcb-cursor0 or libxcb-cursor0 is needed to load the Qt xcb platform plugin"*. **v2.1.20 bundles
  it** (plus a virtual-X GUI selftest in CI so it can't regress), so the AppImage now launches
  out of the box on minimal distros with no `pacman`/`apt` needed.
- **Database on WAL-hostile filesystems fixed (2026-07-20, v2.1.19):** the portable build stores its
  database under the folder it is extracted to. On filesystems that don't support SQLite's
  write-ahead-log locking — **NTFS/exFAT/FAT, and network mounts** (common for a `~/Downloads` on a
  dual-boot data drive) — this failed with *"attempt to write a readonly database"*. ELI now detects
  a WAL-hostile filesystem and falls back to a rollback journal, so it works wherever it is placed.
- **Code-verified, not yet run on real hardware:** **AMD (ROCm), Windows, macOS, Android.** The
  installers, per-OS requirements, paths, GPU detection (NVIDIA / AMD / Apple), and the abstraction
  layer below are all present and read line-by-line — but "correct in the code" isn't the same as
  "confirmed on the metal," and I won't pretend it is. Run ELI on one of these and send me the
  result (working or broken) — that's the fastest way to close the gap for everyone.

A few edges worth knowing going in:
- **musl distros (Alpine) need a glibc shim.** The Linux `.AppImage` is glibc-linked (built on
  Ubuntu), like essentially every AppImage. On a musl-libc distro such as **Alpine** the bundled
  binary won't start — you get a misleading `no such file or directory` on the launcher (that's the
  glibc dynamic linker being absent, not a missing file). Install the `gcompat` glibc-compat layer,
  or run ELI from source in a `python:3.11` (glibc) environment instead. Every mainstream desktop
  distro (Arch, Ubuntu/Debian, Fedora, openSUSE, Mint, Pop!_OS, …) is glibc and runs the AppImage
  directly — see the run-verified list above.
- **Running from source (not the AppImage) needs the Qt xcb libs** — the self-contained AppImage
  bundles `libxcb-cursor.so.0` as of v2.1.20, but a **source / portable** install uses your system's
  Qt libraries. On a minimal desktop the GUI may need `libxcb-cursor0` (Debian/Ubuntu) or
  `xcb-util-cursor` (Arch) installed. The AppImage does not.
- **AMD voice is CPU-only** — the speech-to-text engine (CTranslate2) has no ROCm support, so on an
  AMD GPU it stays on the CPU (works, just not accelerated). The main model + vision use the AMD GPU
  via hipBLAS.
- **Windows secret-file permissions are weaker** — `0600` is a Unix bit Windows ignores; the
  token/key files lean on `%APPDATA%` being private (it is, by default). A proper Windows ACL is on
  the list.
- **Big models can be slow to load or run out of memory** — a large model takes a minute on first
  use, and if VRAM/RAM is tight the server can drop mid-reply. Run the server on its own (not
  alongside the desktop app) so the model loads once.

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
| GPU offload | CUDA / **AMD ROCm** / Metal | CUDA `--install-cuda`; **AMD auto-detected → ROCm/hipBLAS build** | Metal (built in) | CUDA `/cuda` (winget) |
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
