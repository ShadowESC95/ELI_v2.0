# Third-Party Notices — ELI v2.0

ELI v2.0 (© 2026 Jason Fitzgibbon Bridgeman) is open source under the
**Apache License 2.0** (see `LICENSE` and `NOTICE`); releases up to and including
v2.5.35 were published under the PolyForm Noncommercial License 1.0.0. The Apache
licence covers ELI's own code only. This file lists the **third-party** components
used at runtime or shipped in release packages, with their licences, which stay as
they are. It accompanies portable tarballs, wheels, the frozen bundles (`ELI.spec`
packs it) and source checkouts. Licences below are those the packages declare at
the versions in `requirements.lock.txt`.

> **Copyleft notes**
>
> - **PySide6 / shiboken6 (Qt) — LGPL-3.0.** ELI loads them as separate shared
>   libraries (a Python extension module is always linked dynamically), which the
>   LGPL allows from Apache-licensed code. Anyone redistributing ELI binaries must
>   still pass on the LGPL terms and Qt's source offer, and leave users able to
>   replace those libraries.
> - **piper-tts 1.4 — GPL-3.0-or-later, with espeak-ng (GPL-3.0-or-later) compiled
>   into it.** It is ELI's text-to-speech engine, imported in-process, and the
>   frozen builds include it (`ELI.spec` collects the `piper` package). Those
>   components are under the GPL in every copy, and whoever redistributes a bundle
>   takes on GPL-3.0's obligations for them, including offering their source
>   (upstream: <https://github.com/OHF-Voice/piper1-gpl>,
>   <https://github.com/espeak-ng/espeak-ng>). Apache-2.0 code may be combined with
>   GPL-3.0 code; on the FSF's reading, a bundle that combines them is distributed
>   under GPL-3.0's terms as a whole.
> - **Through PyAutoGUI** (BSD-3-Clause), the builds also carry MouseInfo
>   (GPLv3+ per its package metadata), PyMsgBox (BSD licence text, GPLv3+ classifier
>   in its metadata) and, on Linux, python3-Xlib (GPLv2).

---

## Core Python dependencies (`pip install -e .[full]`)

| Component | License | Notes |
|---|---|---|
| **PySide6** / **shiboken6** (Qt GUI) | LGPL-3.0 (also offered under GPL-2.0/3.0) | Canonical Qt binding for packaged ELI; see the note above |
| **llama-cpp-python** | MIT | GGUF inference. Releases bundle 0.3.36.1: upstream's 0.3.36 with a newer llama.cpp (MIT) swapped in by `packaging/llama_source.py` |
| **faiss-cpu** | MIT (with BSD-3-Clause parts) | Vector memory index |
| **faster-whisper** / **ctranslate2** | MIT | Local speech-to-text |
| **piper-tts** | GPL-3.0-or-later (espeak-ng inside) | Local text-to-speech; see the note above |
| **onnxruntime** | MIT | Runs the Piper voices and the wake-word features |
| **FastAPI** / **Starlette** / **uvicorn** | MIT / BSD-3-Clause / BSD-3-Clause | Web server |
| **paho-mqtt** | EPL-2.0 or BSD-3-Clause (EDL-1.0) | MQTT device server |
| **zeroconf** | LGPL-2.1-or-later | mDNS discovery |
| **PyAutoGUI** | BSD-3-Clause | Keyboard and mouse; brings in the GPL helpers named above |
| **chardet**, **python-xlib** | LGPL-2.1-or-later | Pulled in by other dependencies |
| **certifi**, **tqdm**, **pyttsx3**, **pathspec** | MPL-2.0 (tqdm: MPL-2.0 and MIT) | File-level copyleft |
| **numpy**, **Pillow**, **requests**, **pydantic**, **psutil**, etc. | BSD/MIT/Apache-2.0/HPND | See installed package metadata |

Full pinned versions: `requirements-full.txt`, `requirements.lock.txt`.

---

## Optional / feature extras

| Component | License | Used for |
|---|---|---|
| **diffusers**, **accelerate**, **safetensors** | Apache-2.0 | Local image generation |
| **opencv-python**, **mediapipe** | Apache-2.0 | Vision / gaze |
| **pytesseract** | Apache-2.0 | On-screen OCR (Tesseract itself is a system package) |
| **playwright** | Apache-2.0 | Browser automation plugin |
| **bleak** | MIT | Bluetooth discovery |
| **openwakeword** | Apache-2.0 code; the **pre-trained models in its package are CC BY-NC-SA 4.0** (non-commercial), per its own licence note | Wake word. ELI uses only its feature extractor (melspectrogram and speech-embedding models) and trains its own detector head (`eli/perception/wakeword.py`); the frozen builds collect the whole package's data, so the other pre-trained models travel with them |
| **yt-dlp** | Unlicense | YouTube playback |
| **coqui-tts** (XTTS-v2; source installs only, `.[natural]`) | MPL-2.0 code; the XTTS-v2 model weights it downloads are under the Coqui Public Model License (non-commercial) | Optional neural voice and voice cloning |
| **torch**, **transformers**, **peft**, **trl**, **datasets** (`.[training]`) | BSD-3-Clause / Apache-2.0 | Opt-in LoRA fine-tuning |

---

## Native / system dependencies (not bundled)

Installed by `install.sh` or the OS package manager as needed, and run as separate
programs (not linked into ELI):

- **CUDA / ROCm / Metal** — GPU drivers (vendor terms). The GPU packs ELI downloads
  on first start are llama-cpp-python builds (MIT); a CUDA pack runs on NVIDIA's
  driver and CUDA runtime, which are under NVIDIA's terms.
- **Piper CLI** (optional) — GPL-3.0 if installed separately
- **espeak-ng**, **ffmpeg**, **pandoc**, **LibreOffice**, **Tesseract**, **mpv** — system
  packages (various OSS licenses)

---

## Do not ship in official builds

| Component | License | Reason |
|---|---|---|
| **PyQt6 / PyQt5** | GPL-3.0 (or a commercial licence) | The shipped GUI stack stays on LGPL PySide6; `ELI.spec` excludes PyQt5, PyQt6 and PySide2 |
| **QScintilla** (with PyQt) | GPL-3.0 (or a commercial licence) | Optional editor for PyQt source installs only |

Experimental trees under `experimental/` may reference PyQt6 — they are **not**
part of the supported release.

---

## Model and voice weights

Third-party **model and voice binaries** are **not** ELI code, and the Apache
licence does not cover them. Licenses are documented separately in
**`models/MODEL_LICENSES.md`**. GGUF and Piper assets ship via GitHub Release tags
(e.g. `local-assets-v2.1`), not in this git repo. The release bundles carry the
twelve Piper voices from that pack and the nomic text embedder (Apache-2.0); one of
those voices, `ru_RU-ruslan-medium`, is trained on a CC BY-NC-SA 4.0
(non-commercial) dataset.

---

## Obtaining license texts

- PyPI packages: `pip show <package>` → **License** field; or the package’s
  `LICENSE` / `METADATA` in `.venv/lib/.../site-packages/`.
- PySide6 LGPL: https://www.qt.io/licensing/
- This file is included in release tarballs produced by `scripts/package_desktop_app.sh`
  and in the frozen bundles.

Questions: [open an issue](https://github.com/ShadowESC95/ELI_v2.0/issues).
