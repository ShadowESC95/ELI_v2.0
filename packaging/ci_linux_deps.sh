#!/usr/bin/env bash
# The Linux build's dependencies: the system libraries, then the Python stack. The release build and
# the release's test job both run this, so the tests run against exactly what is bundled.
# Reads REQUIRED_EXTRAS, OPTIONAL_EXTRAS and PIP_CONSTRAINT from the workflow's environment.
set -euo pipefail

sudo apt-get update
# xcb-util family: Qt 6.5+'s xcb platform plugin (libqxcb.so) links the
#   whole set at runtime (libxcb-cursor/icccm/image/keysyms/render-util/util).
#   PyInstaller only bundles what is present at build time, so these MUST be
#   installed or the AppImage fails on lean end-user distros — Qt reports it
#   misleadingly as "libxcb-cursor0 is needed" whichever member is missing.
# xvfb: virtual X server for the real-xcb GUI selftest in the smoke check.
sudo apt-get install -y --no-install-recommends \
  portaudio19-dev libasound2-dev libegl1 libgl1 libxkbcommon-x11-0 \
  libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
  libxcb-render-util0 libxcb-util1 libxcb-shape0 libxcb-randr0 libxcb-render0 \
  libxcb-shm0 libxcb-sync1 libxcb-xfixes0 libxcb-xkb1 libxkbcommon0 espeak-ng xvfb

python -m pip install --upgrade pip wheel
pip install -r requirements-build.txt
# CPU torch stack FIRST — default PyPI torch drags ~6 GB of CUDA libs into the
# bundle. torchaudio is included here for the same reason: the `natural`
# (XTTS-v2) extra requires it, and resolving it from PyPI afterwards pulls the
# CUDA build of torch straight back in.
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
# an extra that pins its own torch version gets the CPU build of that version too
export PIP_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cpu
pip install ".[$(echo $REQUIRED_EXTRAS | tr ' ' ',')]"
pip install llama-cpp-python --prefer-binary \
  --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu \
  || pip install llama-cpp-python
for extra in $OPTIONAL_EXTRAS; do
  pip install ".[$extra]" \
    || echo "::warning::optional extra '$extra' has no installable wheels on linux — shipped build degrades cleanly without it"
done
# An extra that quietly re-resolved torch from PyPI would pull the CUDA build
# (~6 GB of nvidia-* wheels) and push the AppImage past GitHub's 2 GB per-asset
# limit — the exact failure that kept `natural` out of the bundle before. Fail
# here, where the cause is obvious, rather than at upload.
# the whole list is read first: grep -q quit at the first match, pip died on the
# closed pipe and pipefail turned the test false, which let CUDA through
cuda="$(pip list --format=freeze | grep -E '^(nvidia-|triton=)' || true)"
if [ -n "$cuda" ]; then
  echo "::error::CUDA wheels were pulled in — the torch stack is no longer CPU-only:"
  echo "$cuda" | sed 's/^/  /'
  exit 1
fi
python - <<'PY'
import importlib
for mod, why in (("torch", "neural voice engine"), ("TTS", "XTTS-v2 (coqui-tts)")):
    try:
        importlib.import_module(mod)
        print(f"  {mod}: present ({why})")
    except Exception as e:
        print(f"::warning::{mod} unavailable — {why} will degrade to Piper: {e}")
PY
