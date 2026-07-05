# Third-Party Notices — ELI v2.0

ELI v2.0 (© 2026 Jason Fitzgibbon Bridgeman) is licensed under the
**PolyForm Internal Use License 1.0.0** (see `LICENSE`). This file lists
**third-party** components used at runtime or shipped in release packages,
with their licenses. It accompanies portable tarballs, wheels, and source
checkouts.

> **LGPL note:** PySide6 and some other components are LGPL-licensed. If you
> redistribute ELI binaries (only the copyright holder may do so under PolyForm),
> you must comply with LGPL source/relink requirements for those components.

---

## Core Python dependencies (`pip install -e .[full]`)

| Component | License | Notes |
|---|---|---|
| **PySide6** (Qt GUI) | LGPL-3.0 | Canonical Qt binding for packaged ELI |
| **llama-cpp-python** | MIT | GGUF inference |
| **faiss-cpu** | MIT | Vector memory index |
| **faster-whisper** | MIT | Local speech-to-text |
| **piper-tts** / **onnxruntime** | MIT | Local TTS runtime |
| **FastAPI** / **Starlette** / **uvicorn** | MIT | Web server |
| **paho-mqtt** | EPL-2.0 / EDL-1.0 | MQTT device server |
| **zeroconf** | LGPL-2.1+ | mDNS discovery |
| **numpy**, **Pillow**, **requests**, **pydantic**, etc. | BSD/MIT/Apache-2.0 | See installed package metadata |

Full pinned versions: `requirements-full.txt`, `requirements.lock.txt`.

---

## Optional / feature extras

| Component | License | Used for |
|---|---|---|
| **diffusers**, **accelerate**, **safetensors** | Apache-2.0 | Local image generation |
| **opencv-python** | Apache-2.0 | Vision / gaze |
| **playwright** | Apache-2.0 | Browser automation plugin |
| **bleak** | MIT | Bluetooth discovery |
| **openwakeword** | Apache-2.0 | Wake word |

---

## Native / system dependencies (not bundled)

Installed by `install.sh` or the OS package manager as needed:

- **CUDA / ROCm / Metal** — GPU drivers (vendor terms)
- **Piper CLI** (optional) — GPL-3.0 if installed separately
- **espeak-ng**, **ffmpeg**, **pandoc**, **LibreOffice** — system packages (various OSS licenses)

---

## Do not ship in official builds

| Component | License | Reason |
|---|---|---|
| **PyQt6 / PyQt5** | GPL-3.0 | Would copyleft shipped binaries |
| **QScintilla** (with PyQt) | GPL | Optional dev UI only |

Experimental trees under `experimental/` may reference PyQt6 — they are **not**
part of the supported release.

---

## Model and voice weights

Third-party **model and voice binaries** are **not** ELI code. Licenses are
documented separately in **`models/MODEL_LICENSES.md`**. GGUF and Piper assets
ship via GitHub Release tags (e.g. `local-assets-v2.1`), not in this git repo.

---

## Obtaining license texts

- PyPI packages: `pip show <package>` → **License** field; or the package’s
  `LICENSE` / `METADATA` in `.venv/lib/.../site-packages/`.
- PySide6 LGPL: https://www.qt.io/licensing/
- This file is included in release tarballs produced by `scripts/package_desktop_app.sh`.

Questions: **jaybridgeman0095@gmail.com**
