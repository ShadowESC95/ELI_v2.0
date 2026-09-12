# ELI v2.0 — New User Installation Guide

> **Updated for v2.4.24.** One hardware-aware GUI wizard.  
> Releases: https://github.com/ShadowESC95/ELI_v2.0/releases/tag/v2.4.24  
> Full guide: **`first time Installation/INSTALLATION_GUIDE.md`**

**Version:** 2.4.24

## What the wizard installs (core)

Env + llama-cpp (CPU/CUDA/Vulkan/Metal by hardware) + databases + **nomic** + **Piper/Whisper** + starter **chat GGUF**. Those stages **hard-fail** until present. Desktop shortcuts where supported. OS extras (mpv, OCR, …) are best-effort.

## Pick a package

| Package | First click |
|---------|-------------|
| AppImage (Linux) | `chmod +x` → run |
| `ELI-Setup-*.exe` (Windows) | Run Setup |
| Frozen Windows zip | `ELI\ELI.exe` |
| `.dmg` (macOS) | Applications |
| Portable Linux | `./ELI_Setup.sh` |
| Git clone | `./scripts/eli_setup.sh` |

## Windows note

Desktop icon is **ELI only**. Server is Start Menu only. Second GUI instance is blocked.

## Phone / tablet

Use Settings → Web Server on the host PC. **Home** tab = MQTT devices (not Home Assistant).
