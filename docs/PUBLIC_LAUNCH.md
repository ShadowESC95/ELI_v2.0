# ELI v2 — public launch copy-paste

> **Current release: v2.4.12 (September 2026).** Hardware fit profiles (Balanced / Max GPU /
> Max context) with joint VRAM+RAM planner; RAM slider re-fits on discrete GPUs. GPU pack
> activates in-process after install (Intel Iris Xe Vulkan fix). Portable setup requires
> `llama_cpp`+`requests` before declaring install complete. Session memory LLM summaries
> at depth ≥ 0.25.

## Links (share these)

- **Repo:** https://github.com/ShadowESC95/ELI_v2.0
- **Release v2.4.6:** https://github.com/ShadowESC95/ELI_v2.0/releases/tag/v2.4.12
- **License:** PolyForm Internal Use (source-available, personal use — not OSI open source)

## Easiest install — Linux

```bash
# AppImage (recommended)
wget https://github.com/ShadowESC95/ELI_v2.0/releases/download/v2.4.12/ELI_v2-2.4.12-x86_64.AppImage
chmod +x ELI_v2-2.4.12-x86_64.AppImage
./ELI_v2-2.4.12-x86_64.AppImage
```

```bash
# Portable tarball (source + voices)
wget https://github.com/ShadowESC95/ELI_v2.0/releases/download/v2.4.12/ELI_v2-2.4.12-linux-portable.tar.gz
tar -xzf ELI_v2-2.4.12-linux-portable.tar.gz && cd ELI_v2-2.4.12-linux-portable
chmod +x ELI_Setup.sh && ./ELI_Setup.sh
```

**Requires:** Linux x86_64 (glibc). NVIDIA GPU recommended; AMD Vulkan and CPU-only supported.

**Phone / tablet (LAN):** after install, run `./scripts/eli_serve.sh --lan --https` — HTTPS unlocks the microphone on mobile browsers.

## Easiest install — Windows

1. Download `ELI-Setup-2.4.12.exe` or `ELI_v2-2.4.12-windows-x64.zip` from the release page
2. Install or extract → run **ELI**
3. Set your headset **Chat** mic as the default recording device if voice input is silent

## Easiest install — macOS (Apple Silicon)

1. Download `ELI_v2-2.4.12-macos-arm64.dmg`
2. Drag to Applications → right-click → Open (unsigned)
3. Grant mic access when prompted; AirPods work when set as system input

## Hacker News / Reddit one-liner

> **ELI v2.4.6.** Local-first AI assistant (~192k LOC, 227 capabilities, GGUF, PySide6 GUI, offline-by-default). Thread-aware web grounding, honest model identity, phatic fast path. https://github.com/ShadowESC95/ELI_v2.0/releases/tag/v2.4.12

## What to say it is

ELI is a **local cognitive assistant**: chat, voice, memory, tools, and a desktop GUI — powered by GGUF models on your GPU/CPU. Not a ChatGPT wrapper; the full stack runs on your hardware.

## Honest limits (say these upfront)

- Best human-run-tested: **Linux + NVIDIA** (cross-platform mic auto-resolve, v2.3.44+)
