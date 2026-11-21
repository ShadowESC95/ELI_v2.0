# ELI v2.0 — New User Installation Guide

> **Updated for v2.5.36.** One hardware-aware GUI wizard.  
> Releases: https://github.com/ShadowESC95/ELI_v2.0/releases/tag/v2.5.36  
> Full guide: **`first time Installation/INSTALLATION_GUIDE.md`**

**Version:** 2.5.36 · open source under the Apache License 2.0

## What the wizard installs (core)

Env + llama-cpp (CPU/CUDA/ROCm/Vulkan/Metal by hardware) + databases + **nomic** + **Piper/Whisper** + starter **chat GGUF**. Those stages **hard-fail** until present. Desktop shortcuts where supported. OS extras (mpv, OCR, …) are best-effort.

## Pick a package

| Package | First click |
|---------|-------------|
| AppImage (Linux, glibc 2.39 or newer) | `chmod +x` → run |
| `ELI-Setup-*.exe` (Windows) | Run Setup |
| Frozen Windows zip (`ELI_v2-*-windows-x64.zip`) | `ELI\ELI.exe` |
| `.dmg` (macOS) | Applications |
| Portable Linux | `./ELI_Setup.sh` |
| Git clone | `./scripts/eli_setup.sh` |

## Windows note

The desktop shortcuts (a Setup option, on by default) are **ELI** and **Uninstall ELI**. Server is Start Menu only. Second GUI instance is blocked.

## Phone / tablet

Use Settings → Web Server on the host PC (**Start (phone / Wi-Fi)**), then scan the QR. The served page's **Home** tab = ELI's own MQTT devices (not Home Assistant).
