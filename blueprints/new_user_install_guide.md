# ELI v2.0 — New User Installation Guide

> **Updated for v2.3.53 (August 2026).** **AUDIO IS BACK** — cross-platform microphone
> auto-resolve (no env vars on Linux/macOS/Windows). Primary install: prebuilt installers on
> [GitHub Releases](https://github.com/ShadowESC95/ELI_v2.0/releases/tag/v2.3.53) —
> `ELI-Setup-<v>.exe` (Windows), `.dmg` (macOS Apple Silicon), `.AppImage` (Linux).


**Version:** 2.3.53  
**Audience:** First-time users on Linux, Windows, or macOS  
**Release page:** https://github.com/ShadowESC95/ELI_v2.0/releases/tag/v2.3.53

---

## 1. What you are installing

ELI is a **local-first AI assistant**. Everything runs on your computer:

- Chat and reasoning (powered by a GGUF model you download)
- Memory, knowledge graph, and habits
- Desktop GUI (PySide6) and optional web interface for phone/tablet
- Voice input (Whisper STT) and voice output (Piper TTS)
- Offline by default — no cloud account required

**Honest hardware note:** Best tested on **Linux x86_64 + NVIDIA GPU**. Windows and macOS work; AMD and Apple Silicon are supported in code but less field-tested.

---

## 2. Choose your package (same software, different wrapper)

| Package | OS | What it is | Best for |
|---------|-----|------------|----------|
| **Portable folder** | Linux, Windows, macOS | Extracted directory with scripts | Tinkerers, USB drives, devs |
| **AppImage** | Linux only | Single executable file | Easiest Linux double-click |
| **Setup.exe** | Windows only | Graphical installer | Easiest Windows install |
| **Source clone** | All | Git checkout + `install.sh` | Contributors, bleeding edge |

**Important:** None of the release downloads include the large **chat model** (~2–5 GB). That is downloaded during first-time setup. Voice models (~200 MB) and the memory embedder (~85 MB) are fetched automatically by the installer.

---

## 3. Prerequisites (all platforms)

| Requirement | Details |
|-------------|---------|
| **Python** | 3.10, 3.11, or 3.12 |
| **Disk space** | ~10 GB free (venv + one chat model + voice) |
| **RAM** | 16 GB recommended; 8 GB minimum with a small model |
| **GPU** | NVIDIA recommended; CPU-only works but slower |
| **Network** | Required once during install (model + voice downloads) |

---

## 4. Linux — Portable folder (recommended for control)

### 4.1 Download and extract

```bash
cd ~/Desktop
wget https://github.com/ShadowESC95/ELI_v2.0/releases/download/v2.3.53/ELI_v2-2.3.53-linux-portable.tar.gz
tar -xzf ELI_v2-2.3.53-linux-portable.tar.gz
cd ELI_v2-2.3.53-linux-portable
```

### 4.2 First-time setup (run once)

**Easiest — guided setup (recommended):**

```bash
chmod +x ELI_Setup.sh
./ELI_Setup.sh
```

This runs eight steps automatically:

1. Welcome and Python check
2. Create `.venv` and install pip dependencies (`install.sh`)
3. Download a chat model sized to your GPU (or skip if present)
4. Initialize local databases
5. Download voice models (Whisper STT + Piper TTS) and memory embedder
6. Install app-menu icons (ELI v2.0, ELI Server, ELI Setup)
7. Open the graphical setup wizard
8. Launch ELI

**Manual equivalent:**

```bash
chmod +x INSTALL_ELI.sh RUN_ELI.sh install.sh
./INSTALL_ELI.sh
./RUN_ELI.sh
```

### 4.3 What the installer downloads

```bash
# Voice (STT + TTS) — automatic during install
.venv/bin/python -m eli.runtime.voice_assets

# Memory embedder — automatic during install
.venv/bin/python -m eli.core.model_download --aux

# Chat model — offered in wizard, or run manually:
.venv/bin/python -m eli.core.model_download --list    # see options
.venv/bin/python -m eli.core.model_download --auto    # pick by VRAM
```

**VRAM guide (NVIDIA):**

| GPU VRAM | Suggested model |
|----------|-----------------|
| 8 GB | Qwen2.5-7B Q4 (~4.5 GB) |
| 12 GB | Qwen2.5-14B Q4 or Mistral-7B |
| 24 GB+ | Larger quantised models |

### 4.4 Daily use (after setup)

```bash
cd ~/Desktop/ELI_v2-2.3.53-linux-portable

# Desktop GUI
./RUN_ELI.sh
# or
./eli.sh
# or click "ELI v2.0" in your application menu

# Web server — local PC browser only
./scripts/eli_serve.sh

# Web server — phone/tablet on same Wi-Fi (with microphone)
./scripts/eli_serve.sh --lan --https
```

**Unified launcher:**

```bash
./scripts/eli_launch.sh              # desktop GUI (default)
./scripts/eli_launch.sh serve --lan --https   # web server for phone
./scripts/eli_launch.sh both --lan --https    # server + GUI together
```

### 4.5 Phone / tablet access

1. Start the server with HTTPS (required for microphone on mobile browsers):

```bash
./scripts/eli_serve.sh --lan --https
```

2. The terminal prints URLs like:

```
http://192.168.1.118:8081/#token=XXXXXXXX
https://192.168.1.118:8443/#token=XXXXXXXX
```

3. On your phone (same Wi-Fi), open the **HTTP** URL first to connect.
4. For voice/mic, open the **HTTPS** URL and accept the one-time self-signed certificate warning.

**Firewall (if phone cannot connect):**

```bash
sudo ufw allow from 192.168.1.0/24 to any port 8081 proto tcp
sudo ufw allow from 192.168.1.0/24 to any port 8443 proto tcp
```

### 4.6 Linux — AppImage (double-click install)

```bash
cd ~/Desktop
wget https://github.com/ShadowESC95/ELI_v2.0/releases/download/v2.3.53/ELI_v2-2.3.53-x86_64.AppImage
chmod +x ELI_v2-2.3.53-x86_64.AppImage
./ELI_v2-2.3.53-x86_64.AppImage
```

**What happens on first launch:**

- ELI copies itself to `~/.local/share/ELI_v2`
- Runs `INSTALL_ELI.sh` automatically
- Shows a progress dialog, then launches ELI
- Later launches open ELI directly from `~/.local/share/ELI_v2`

**Daily use after AppImage first run:**

```bash
# From the installed copy:
cd ~/.local/share/ELI_v2
./RUN_ELI.sh
./scripts/eli_serve.sh --lan --https
```

Or use the app-menu icons installed during first run.

### 4.7 Portable vs AppImage — summary

| | Portable folder | AppImage |
|---|---|---|
| Location | Where you extracted it | Copies to `~/.local/share/ELI_v2` |
| Start | `./ELI_Setup.sh` then `./RUN_ELI.sh` | `chmod +x` and double-click |
| Updates | Download new tarball, re-run setup | Download new AppImage |
| Data | `artifacts/` inside folder | `~/.local/share/ELI_v2/artifacts/` |

---

## 5. Windows — Portable zip or Setup.exe

### 5.1 Download

From https://github.com/ShadowESC95/ELI_v2.0/releases/tag/v2.3.53:

- **Portable:** `ELI_v2-2.3.53-windows-x64.zip` — extract anywhere
- **Installer:** `ELI-Setup-2.3.53.exe` — graphical install (per-user, no admin; shows the licence first)

### 5.2 First-time setup

**Easiest — double-click:**

```
ELI_Setup.bat
```

**PowerShell (full control):**

```powershell
cd C:\Users\YourName\Desktop\ELI
powershell -ExecutionPolicy Bypass -File install.ps1 -Yes
```

**Command prompt:**

```cmd
cd C:\Users\YourName\Desktop\ELI
install.bat
```

**Install flags:**

```powershell
# CPU only (no NVIDIA GPU)
powershell -ExecutionPolicy Bypass -File install.ps1 -Yes -CpuOnly

# Auto-download chat model after install
powershell -ExecutionPolicy Bypass -File install.ps1 -Yes -AutoModel

# Skip model download (wizard later)
powershell -ExecutionPolicy Bypass -File install.ps1 -Yes -NoModel

# Also install CUDA toolkit via winget
powershell -ExecutionPolicy Bypass -File install.ps1 -Yes -InstallCuda
```

### 5.3 Daily use

```cmd
eli.bat
```

```powershell
.\scripts\eli_launch.sh gui
```

**Web server:**

```powershell
# Local only
.\scripts\eli_serve.ps1

# Phone/tablet on LAN (add -Https for microphone)
.\scripts\eli_serve.ps1 -Lan -Https
```

**Start Menu shortcuts (after install):**

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_desktop_apps.ps1
```

### 5.4 Windows voice assets (if mic/TTS fails)

```powershell
.venv\Scripts\python.exe -m eli.runtime.voice_assets
```

---

## 6. macOS — Portable or source install

macOS uses the same `install.sh` as Linux (Metal GPU instead of CUDA).

### 6.1 From portable tarball

```bash
cd ~/Desktop
curl -LO https://github.com/ShadowESC95/ELI_v2.0/releases/download/v2.3.53/ELI_v2-2.3.53-linux-portable.tar.gz
tar -xzf ELI_v2-2.3.53-linux-portable.tar.gz
cd ELI_v2-2.3.53-linux-portable
chmod +x ELI_Setup.sh
./ELI_Setup.sh
```

### 6.2 From source (git clone)

```bash
git clone https://github.com/ShadowESC95/ELI_v2.0.git
cd ELI_v2.0
bash install.sh --yes
./eli.sh
```

### 6.3 Daily use

```bash
./RUN_ELI.sh
./scripts/eli_serve.sh --lan --https
```

**Finder launchers** (installed by `install_desktop_apps.sh`):

```
~/Applications/ELI v2.0.command
~/Applications/ELI Server (Web App).command
~/Applications/ELI Setup.command
```

### 6.4 macOS system dependencies (optional features)

```bash
brew install tesseract ffmpeg portaudio
```

---

## 7. First-run wizard (all platforms)

After install, ELI opens a setup window. Complete these steps:

1. **Hardware profile** — ELI detects your GPU/RAM and suggests settings
2. **Chat model** — pick or download a GGUF model (required for replies)
3. **Onboarding** — ELI asks your name, work, answer style, and focus
   - Type your real name when asked ("What should I call you?")
   - Say `skip` at any time to skip onboarding

**If you answered onboarding wrong**, reset and start over:

```bash
cd /path/to/ELI_v2-2.3.53-linux-portable   # or your install root
export ELI_PROJECT_ROOT="$PWD" PYTHONPATH="$PWD"
.venv/bin/python <<'PY'
from pathlib import Path
import json, sqlite3
from eli.kernel.state import clear_user_name
from eli.onboarding.interview import clear_onboarding_state

clear_onboarding_state()
clear_user_name()
cfg = Path("config/settings.json")
s = json.loads(cfg.read_text())
s["user_name"] = ""
s["first_run_complete"] = False
cfg.write_text(json.dumps(s, indent=2) + "\n")
db = Path("artifacts/db/user.sqlite3")
con = sqlite3.connect(db)
for t in ["memories","user_patterns","kg_entities","conversations"]:
    try: con.execute(f"DELETE FROM {t}")
    except: pass
con.commit()
print("Reset complete — restart ELI")
PY
```

---

## 8. Folder layout (where your data lives)

```
ELI_v2-2.3.53-linux-portable/
  .venv/                  Python environment (created by install)
  models/
    gguf/                 Chat models you download
    embeddings/           Memory embedder (auto-downloaded)
    whisper/              Speech-to-text weights (auto-downloaded)
    tts/piper/            Text-to-speech voice (auto-downloaded)
  artifacts/
    db/                   SQLite databases (memory, habits, etc.)
    conversations/        Saved chat logs
    runtime/              User profile snapshots
  config/
    settings.json         Your preferences and model path
  scripts/
    eli_serve.sh          Web server launcher
    eli_launch.sh         Unified launcher
    eli_setup.sh          Guided setup
  ELI_Setup.sh            One-click first-time setup
  INSTALL_ELI.sh          Install only
  RUN_ELI.sh              Launch desktop app
  eli.sh                  Launch desktop app (alias)
```

---

## 9. Troubleshooting

### "No GGUF model found" / empty chat replies

Download a chat model:

```bash
.venv/bin/python -m eli.core.model_download --auto
```

Or set model path in **Settings → Model** in the GUI.

### STT error: "network disabled" / huggingface.co blocked

Whisper is not cached. Run:

```bash
.venv/bin/python -m eli.runtime.voice_assets
```

Then restart the server.

### TTS 503: "no voice model"

Piper voice missing. Run:

```bash
.venv/bin/python -m eli.runtime.voice_assets
```

### Phone mic does not work

Browsers block microphone on plain `http://LAN-IP`. Use HTTPS:

```bash
./scripts/eli_serve.sh --lan --https
```

Open the `https://` URL on the phone and accept the certificate warning.

### `./scripts/eli_serve.sh: No such file or directory`

You are in the wrong directory. Either:

```bash
cd /path/to/ELI_v2-2.3.53-linux-portable
./scripts/eli_serve.sh --lan --https
```

Or use the full path:

```bash
/home/you/Desktop/ELI_v2-2.3.53-linux-portable/scripts/eli_serve.sh --lan --https
```

### Only 9–10 GPU layers on 8 GB card

Use a smaller model (7B, not 35B). In the hardware wizard, pick Qwen2.5-7B.

### Re-run full setup safely

```bash
./ELI_Setup.sh
```

Safe to run multiple times — idempotent.

### Diagnostics

```bash
./eli_diagnose.sh
.venv/bin/python -c "from eli.setup.status import stage_checks; print(stage_checks())"
```

---

## 10. Quick reference — copy-paste commands

### Linux portable — full first install

```bash
wget https://github.com/ShadowESC95/ELI_v2.0/releases/download/v2.3.53/ELI_v2-2.3.53-linux-portable.tar.gz
tar -xzf ELI_v2-2.3.53-linux-portable.tar.gz
cd ELI_v2-2.3.53-linux-portable
chmod +x ELI_Setup.sh && ./ELI_Setup.sh
```

### Linux — daily desktop

```bash
cd ELI_v2-2.3.53-linux-portable && ./RUN_ELI.sh
```

### Linux — phone server with voice

```bash
cd ELI_v2-2.3.53-linux-portable && ./scripts/eli_serve.sh --lan --https
```

### Windows — first install

```cmd
cd ELI
ELI_Setup.bat
```

### Windows — daily desktop

```cmd
eli.bat
```

### Windows — phone server

```powershell
.\scripts\eli_serve.ps1 -Lan -Https
```

### macOS — first install

```bash
tar -xzf ELI_v2-2.3.53-linux-portable.tar.gz
cd ELI_v2-2.3.53-linux-portable
chmod +x ELI_Setup.sh && ./ELI_Setup.sh
```

---

## 11. What happens during install (technical summary)

| Step | Script | Network? | Size |
|------|--------|----------|------|
| Python venv + pip packages | `install.sh` / `install.ps1` | Yes (PyPI) | ~2 GB |
| Memory embedder | `model_download --aux` | Yes | ~85 MB |
| Voice STT (Whisper) | `voice_assets` | Yes | ~150 MB |
| Voice TTS (Piper amy) | `voice_assets` | Yes | ~63 MB |
| Chat model | wizard or `model_download` | Yes | 2–5 GB |
| Database init | `eli.core.init_data` | No | — |
| Desktop icons | `install_desktop_apps.sh` | No | — |

After install, ELI runs **offline by default**. Only deliberate actions (web search, model download) use the network.

---

## 12. Getting help

- **Release page:** https://github.com/ShadowESC95/ELI_v2.0/releases
- **Issues:** https://github.com/ShadowESC95/ELI_v2.0/issues
- **Server docs:** `docs/SERVER_AND_WEB_APP.md` (in the install folder)
- **Cross-platform notes:** `docs/CROSS_PLATFORM.md`

---

*ELI v2.0 — local, private, yours. This guide matches release v2.3.53.*
