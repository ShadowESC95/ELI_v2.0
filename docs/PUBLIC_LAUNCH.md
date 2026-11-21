# ELI v2 — public launch copy-paste

> **Current release: v2.5.36 (November 2026).** ELI v2 is now open source under the Apache
> License 2.0 (v2.5.35 and earlier were PolyForm Noncommercial). Forgetting something now removes
> it from the vector index files and deletes the claims that rested only on it; long messages are
> fitted to the loaded model's context instead of cut at 8,192 characters; the shell gate judges
> every command in a line; the LAN server refuses tokenless access to names that are not this
> machine's, and multi-user members cannot have ELI run the owner's actions.

## Links (share these)

- **Repo:** https://github.com/ShadowESC95/ELI_v2.0
- **Release v2.5.36:** https://github.com/ShadowESC95/ELI_v2.0/releases/tag/v2.5.36
- **License:** Apache-2.0 (open source; models and voices keep their own licences — see `models/MODEL_LICENSES.md`)

## Easiest install — Linux

```bash
# AppImage (recommended)
wget https://github.com/ShadowESC95/ELI_v2.0/releases/download/v2.5.36/ELI_v2-2.5.36-x86_64.AppImage
chmod +x ELI_v2-2.5.36-x86_64.AppImage
./ELI_v2-2.5.36-x86_64.AppImage
```

```bash
# Portable tarball (source + voices)
wget https://github.com/ShadowESC95/ELI_v2.0/releases/download/v2.5.36/ELI_v2-2.5.36-linux-portable.tar.gz
tar -xzf ELI_v2-2.5.36-linux-portable.tar.gz && cd ELI_v2-2.5.36-linux-portable
chmod +x ELI_Setup.sh && ./ELI_Setup.sh
```

**Requires:** Linux x86_64. The AppImage needs glibc 2.39 or newer (Ubuntu 24.04+, Debian 13+,
Fedora 40+); on older systems use the portable tarball, which builds against the system's own
libraries. NVIDIA GPU recommended; AMD/Intel (Vulkan) and CPU-only supported.

**Phone / tablet (LAN):** after install, run `./scripts/eli_serve.sh --lan --https` (AppImage:
`./ELI_v2-2.5.36-x86_64.AppImage --server --lan --https`) — HTTPS unlocks the microphone on mobile
browsers.

## Easiest install — Windows

1. Download `ELI-Setup-2.5.36.exe` or `ELI_v2-2.5.36-windows-x64.zip` from the release page
2. Install or extract → run **ELI**
3. Set your headset **Chat** mic as the default recording device if voice input is silent

## Easiest install — macOS (Apple Silicon)

1. Download `ELI_v2-2.5.36-macos-arm64.dmg`
2. Drag to Applications → right-click → Open (unsigned)
3. Grant mic access when prompted; AirPods work when set as system input

## Hacker News / Reddit one-liner

> **ELI v2.5.36.** Open-source (Apache-2.0), local-first AI assistant (~207k lines of Python, 231 capabilities, GGUF, PySide6 GUI, offline-by-default). https://github.com/ShadowESC95/ELI_v2.0/releases/tag/v2.5.36

## What to say it is

ELI is a **local cognitive assistant**: chat, voice, memory, tools, and a desktop GUI — powered by GGUF models on your GPU/CPU. Not a ChatGPT wrapper; the full stack runs on your hardware.

## Honest limits (say these upfront)

- Best human-run-tested: **Linux + NVIDIA** (cross-platform mic auto-resolve, v2.3.44+)
