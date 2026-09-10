# ELI v2 — Installation Guide (Complete Beginner)

**Version:** 2.4.12 · **Updated:** 2026-09-10

This guide answers one question: **“Which file do I run, in what order, on my machine?”**

ELI is **local-first** — it builds a private Python environment (`.venv`) in the folder you unpacked or cloned, detects your CPU/GPU/RAM, installs the right inference engine, and optionally downloads models. You do **not** need to know Python; you only need to pick the right entry script for your situation.

---

## 1. Choose your package (30 seconds)

| What you downloaded | Best for | Size note |
|---------------------|----------|-----------|
| **`ELI_v2-*-x86_64.AppImage`** | Linux — **easiest**. No install step; GPU pack downloads on first launch | ~1.4 GB (under GitHub limit) |
| **`ELI_v2-*-linux-portable.tar.gz`** | Linux — offline GPU packs bundled; builds `.venv` on your machine | ~300 MB **larger** than older portables because it includes `gpu-packs/` (~800 MB CUDA wheel inside) |
| **Git clone** (`ELI_v2.0` repo) | Developers, always-latest code | Smallest download; longest first run |
| **`ELI_v2-*-windows-x64.zip`** or **`ELI-Setup-*.exe`** | Windows 10/11 x64 | Setup.exe = installer; zip = portable folder |
| **`ELI_v2-*-macos-arm64.dmg`** | Apple Silicon Mac | Metal GPU auto-detected |
| **`.deb` package** | Debian/Ubuntu package managers | `eli-v2` system command |

**Rule of thumb:** If you just want ELI working on Linux with an NVIDIA GPU, use the **AppImage** first. Use the **portable tarball** when you need fully offline GPU wheels or want to hack the source tree in place.

---

## 2. Priority order — what to run first

Think of install scripts in **layers**. Only go to the next layer if the previous one failed or you know you need it.

### Layer 0 — One-shot launchers (no build)

| Priority | File | Platform | What it does |
|:--------:|------|----------|--------------|
| ★★★ | **`ELI_v2-*.AppImage`** | Linux | Copies to `~/.local/share/ELI_v2`, downloads GPU pack if needed, runs setup once, opens GUI |
| ★★★ | **`ELI-Setup-*.exe`** | Windows | Inno Setup installer; adds Start Menu entries |
| ★★ | **`RUN_ELI.sh`** | Linux portable | Launches ELI **after** install — not for first time |

### Layer 1 — Guided first-time setup (recommended)

| Priority | File | Same as | What it does |
|:--------:|------|---------|--------------|
| ★★★ | **`ELI_Setup.sh`** | `scripts/eli_setup.sh` | **Best first click** on portable/clone. GUI wizard when possible; otherwise runs full `install.sh` |
| ★★★ | **`INSTALL_ELI.sh`** | (portable only) | Alias → `scripts/eli_setup.sh` |
| ★★★ | **`./scripts/eli_setup.sh`** | — | Same wizard from a git clone |
| ★★★ | **`ELI_Setup.bat`** | (Windows zip) | GUI installer; falls back to `install.ps1` |
| ★★ | **`python -m eli.setup --full-install`** | — | Direct GUI wizard (needs minimal `.venv` + PySide6) |

### Layer 2 — Full terminal install (when Layer 1 fails)

| Priority | File | Platform | When to use |
|:--------:|------|----------|-------------|
| ★★★ | **`bash install.sh --yes --auto-model`** | Linux / macOS | Portable shows `Please install PySide6`, or wizard never opens |
| ★★★ | **`install.bat`** / **`install.ps1 -Yes -AutoModel`** | Windows | Same |
| ★★ | **`bash install.sh`** (interactive) | Linux / macOS | You want to pick models/GPU options manually |
| ★★ | **`bash scripts/install_android.sh`** | Android Termux | Auto-selected on Android (no GUI) |

### Layer 3 — Daily launch (after install succeeds)

| File | Purpose |
|------|---------|
| **`./eli.sh`** or **`./scripts/eli_launch.sh`** | Desktop GUI |
| **`./RUN_ELI.sh`** | Portable launcher → `scripts/eli_startup.sh` |
| **`eli`** (terminal) | After `scripts/install_eli_command.sh` or `scripts/fix_eli_shell_env.sh` |
| **`./scripts/eli_launch.sh serve --lan --https`** | Phone/tablet web UI with mic |

### Layer 4 — Fixes & extras (optional)

| File | When |
|------|------|
| **`bash scripts/fix_eli_shell_env.sh --yes`** | `eli` command opens wrong folder / wrong version (v2 vs v3 alias leak) |
| **`bash scripts/install_desktop_apps.sh`** | Missing app-menu icons |
| **`bash scripts/install_eli_command.sh --force`** | Install `~/.local/bin/eli` |
| **`bash scripts/eli_one_click_setup.sh`** | Clone: install + desktop icon + `eli` command in one go |
| **`./scripts/eli_startup.sh --with-github-assets`** | Download extra models/voices from GitHub release assets |

---

## 3. Every install-related script — plain English

### Root folder (you see these after unzip or clone)

| File | Type | Beginner summary |
|------|------|------------------|
| **`ELI_Setup.sh`** | sh | **Run this first** on portable Linux. Friendly name for the setup wizard. |
| **`INSTALL_ELI.sh`** | sh | Same as `ELI_Setup.sh` (legacy name in portable packages). |
| **`RUN_ELI.sh`** | sh | **Launch ELI** after install. Do not use for first-time setup. |
| **`install.sh`** | sh | **The real installer** — creates `.venv`, GPU/CPU llama-cpp, PySide6, models, databases. Use if setup wizard fails. |
| **`eli.sh`** | sh | Quick launcher: `.venv/bin/python -m eli` |
| **`install.bat`** | bat | Windows: opens PowerShell installer (`install.ps1`). |
| **`install.ps1`** | ps1 | Windows full installer (mirrors `install.sh`). |
| **`eli.bat`** | bat | Windows quick launcher. |
| **`UNINSTALL.bat`** | bat | Windows uninstall helper. |

### `scripts/` folder

| File | Beginner summary |
|------|------------------|
| **`eli_setup.sh`** | **Main first-time entry** for clones. GUI wizard → streams `install.sh` inside one window. Terminal fallback runs `install.sh --yes` when no display/Qt. |
| **`eli_startup.sh`** | Smart launcher: optional setup, optional GitHub asset restore, then GUI. Used by `RUN_ELI.sh`. |
| **`eli_launch.sh`** | Daily GUI launch + `serve` mode for LAN/web. |
| **`eli_serve.sh`** / **`eli_serve.ps1`** | Web server only (phone mic). |
| **`install_eli_command.sh`** | Puts `eli` in `~/.local/bin` pointing at this checkout. |
| **`fix_eli_shell_env.sh`** | Fixes stale bash `alias eli=` and wrong `ELI_PROJECT_ROOT` when v2 and v3 coexist. |
| **`install_desktop_apps.sh`** / **`.ps1`** | App-menu icons: ELI, ELI Server, ELI Setup. |
| **`install_android.sh`** | Termux/headless CPU-only install. |
| **`eli_one_click_setup.sh`** | Developer convenience: `install.sh` + icons + terminal command. |
| **`safe_install_linux.sh`** | Extra-safe Linux path for broken system Python/pip. |
| **`eli_uninstall.sh`** | Remove desktop entries and optionally data. |

### Python entry points (advanced)

| Command | Purpose |
|---------|---------|
| `python -m eli.setup --full-install` | Unified GUI installer (what `eli_setup.sh` opens) |
| `python -m eli.setup --run-remaining` | Finish incomplete wizard stages |
| `python -m eli.setup --status` | Check what's installed |
| `python -m eli.core.model_download --auto` | Pick/download chat model by VRAM |

### Maintainer-only (ignore unless you build releases)

`build_packages.sh`, `scripts/package_desktop_app.sh`, `packaging/linux/build-appimage-pyinstaller.sh`, `packaging/windows/build-windows.ps1`, etc.

---

## 4. Step-by-step recipes

### A. Linux AppImage (recommended for NVIDIA)

```bash
chmod +x ELI_v2-2.4.12-x86_64.AppImage
./ELI_v2-2.4.12-x86_64.AppImage
```

First launch downloads the GPU pack (~800 MB) if not bundled. Data lives in `~/.local/share/ELI_v2/`.

### B. Linux portable tarball

```bash
tar -xzf ELI_v2-2.4.12-linux-portable.tar.gz
cd ELI_v2-2.4.12-linux-portable
chmod +x ELI_Setup.sh RUN_ELI.sh install.sh
./ELI_Setup.sh
```

**If you see `Please install PySide6`:**

```bash
bash install.sh --yes --auto-model
./RUN_ELI.sh
```

This was a known v2.4.7 bug (setup thought Qt was installed because of headless stubs). **Fixed in v2.4.8.**

**Why is the tarball ~300 MB bigger than before?** v2.4.7 bundles offline `gpu-packs/` (CUDA + Vulkan llama-cpp wheels). The AppImage omits them to stay under GitHub's 2 GiB limit and downloads at first launch instead.

### C. Git clone (developer)

```bash
git clone https://github.com/ShadowESC95/ELI_v2.0.git
cd ELI_v2.0
./scripts/eli_setup.sh
# or: bash install.sh --yes --auto-model
./scripts/eli_launch.sh
```

### D. Windows portable zip

1. Unzip `ELI_v2-*-windows-portable.zip`
2. Double-click **`ELI_Setup.bat`**
3. If GUI fails: `install.bat` or `powershell -File install.ps1 -Yes -AutoModel`
4. Daily: **`ELI.exe`** or **`eli.bat`**

### E. Android (Termux)

```bash
bash scripts/install_android.sh
.venv/bin/python -m eli.cli.headless
```

No desktop GUI on Android by design.

---

## 5. What the installer does automatically (all paths)

When `install.sh` / `install.ps1` / the GUI wizard runs successfully:

1. **Detects hardware** — CPU, RAM, NVIDIA / AMD / Intel GPU, macOS Metal
2. **Creates `.venv`** — isolated Python; never uses system site-packages for ELI
3. **Installs PyTorch** — CPU, CUDA, ROCm, or Metal as appropriate
4. **Builds or installs llama-cpp-python** — GPU offload when possible; CPU fallback on SIGILL
5. **Installs ELI** — editable from source + pinned `requirements.lock.txt`
6. **Installs PySide6** — from bundled `wheelhouse/` (portable) or PyPI
7. **GPU pack** — from bundled `gpu-packs/` or download (AppImage)
8. **Seeds databases** — blank SQLite under `artifacts/db/`
9. **Downloads embedder** — required for memory/RAG (~85 MB)
10. **Optional chat model + voice** — wizard or `--auto-model`
11. **Desktop icons** — Linux: `install_desktop_apps.sh`

**Compute mode** (Auto / GPU / CPU) is chosen in the first-run startup dialog and saved in `config/settings.json`.

---

## 6. Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Please install PySide6` during setup | `bash install.sh --yes --auto-model` (portable v2.4.7); upgrade to **v2.4.8+** |
| `.venv not found` | Run `install.sh` or `eli_setup.sh` first |
| `eli` opens wrong version / wrong DB path | `bash scripts/fix_eli_shell_env.sh --yes` then `source ~/.bashrc` |
| Portable huge but AppImage small | Expected — portable bundles offline GPU packs |
| 0 GPU layers | Re-run `bash install.sh --install-cuda` (NVIDIA) or check Compute mode = Auto/GPU |
| `SIGILL` / illegal instruction | CPU too old for prebuilt wheel; portable builds from source on your machine |
| Disk full during setup | Need ~15 GB free for models + CUDA toolkit optional install |
| Wrong Python version | ELI needs **Python 3.10–3.13**. Check: `python3 --version`. Portable wheelhouse ships PySide6 for cp310–cp313. |

**Diagnostic:**

```bash
./eli_diag.sh
# or
.venv/bin/python -m eli.setup --status
```

---

## 7. Config files you might touch (rarely)

| File | Purpose |
|------|---------|
| `pyproject.toml` | Version and package metadata |
| `requirements.lock.txt` | Pinned deps (reproducible install) |
| `requirements-portable-bootstrap.txt` | PySide6-only offline bootstrap |
| `config/settings.json` | Runtime settings (created on first run) |
| `.env.example` | Optional env overrides — copy to `.env` only if needed |

---

## 8. Where data lives

| Install type | Data directory |
|--------------|----------------|
| Source / portable | `<ELI folder>/artifacts/` |
| AppImage | `~/.local/share/ELI_v2/artifacts/` |
| `.deb` | XDG data dir + package layout |

---

## 9. Still stuck?

1. Read **[ELI_SCRIPT_REFERENCE.md](ELI_SCRIPT_REFERENCE.md)** §2 (decision tree) and §3 (every script).
2. See **`blueprints/full_setup_guide.md`** and **`docs/FIRST_RUN.md`**.
3. File an issue: [github.com/ShadowESC95/ELI_v2.0/issues](https://github.com/ShadowESC95/ELI_v2.0/issues) with output of `python3 --version` and the last 30 lines of `artifacts/setup_gui.log`.

---

*ELI v2.4.8 — local, private, yours.*
