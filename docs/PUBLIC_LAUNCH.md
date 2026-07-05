# ELI v2 — public launch copy-paste

## Links (share these)

- **Repo:** https://github.com/ShadowESC95/ELI_v2.0
- **Release v2.0.7:** https://github.com/ShadowESC95/ELI_v2.0/releases/tag/v2.0.7
- **License:** PolyForm Internal Use (source-available, personal use — not OSI open source)

## Easiest install — Linux

```bash
# Option A: AppImage (double-click after chmod)
wget https://github.com/ShadowESC95/ELI_v2.0/releases/download/v2.0.7/ELI_v2-2.0.7-x86_64.AppImage
chmod +x ELI_v2-2.0.7-x86_64.AppImage
./ELI_v2-2.0.7-x86_64.AppImage
```

```bash
# Option B: portable tarball
wget https://github.com/ShadowESC95/ELI_v2.0/releases/download/v2.0.7/ELI_v2-2.0.7-linux-portable.tar.gz
tar -xzf ELI_v2-2.0.7-linux-portable.tar.gz && cd ELI_v2-2.0.7-linux-portable
chmod +x ELI_Setup.sh && ./ELI_Setup.sh
```

**Requires:** Python 3.10+, Linux x86_64, NVIDIA GPU recommended (RTX-class tested).

## Easiest install — Windows

1. Download `ELI_v2-2.0.7-windows-portable.zip` from the release page
2. Extract → double-click **`ELI_Setup.bat`**
3. Run **`eli.bat`**

## Hacker News / Reddit one-liner

> **ELI v2.0.7** — local-first AI assistant (GGUF, PySide6 GUI, offline-by-default). Runs entirely on your machine; no cloud account. Linux AppImage + portable; Windows zip. Source-available (PolyForm Internal Use). https://github.com/ShadowESC95/ELI_v2.0/releases/tag/v2.0.7

## What to say it is

ELI is a **local cognitive assistant**: chat, voice, memory, tools, and a desktop GUI — powered by GGUF models on your GPU/CPU. Not a ChatGPT wrapper; the full stack runs on your hardware.

## Honest limits (say these upfront)

- Best tested: **Linux + NVIDIA**
- First run downloads a ~5 GB model (one-time)
- Source-available license — **not redistribution-friendly** (personal/evaluation use)
- v3 is commercial; v2 is the public evaluation release
