"""NVIDIA GPU acceleration pack for frozen ELI builds.

The shipped bundle contains the CPU llama.cpp build (safe on every machine —
CUDA builds crash at boot without NVIDIA drivers). This module downloads the
matching CUDA build of llama-cpp-python from the official wheel index
(https://abetlen.github.io/llama-cpp-python/whl/<cuda>/) into
    <ELI root>/runtime/gpu/llama_cpp
and the runtime hook puts that directory FIRST on sys.path, so the CUDA copy
shadows the bundled CPU copy on the next launch. Like models and voices, the
heavy GPU binaries are per-machine downloads, never part of the installer.

Invoked via:  ELI --install-gpu-pack   (ELI-Server.exe on Windows shows progress)
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

WHEEL_INDEX = "https://abetlen.github.io/llama-cpp-python/whl/{cuda}/llama-cpp-python/"
# Newest first — pick the newest index the driver supports.
CUDA_INDEXES = ("cu124", "cu123", "cu122", "cu121")


def _say(msg: str) -> None:
    print(f"[gpu-pack] {msg}", flush=True)


def _fail(msg: str) -> int:
    print(f"[gpu-pack] ERROR: {msg}", file=sys.stderr, flush=True)
    return 1


def _eli_root() -> Path:
    import os
    env = os.environ.get("ELI_PROJECT_ROOT")
    if env:
        return Path(env)
    raise RuntimeError("ELI_PROJECT_ROOT not set — run via the ELI executable")


def _driver_cuda_version() -> tuple[int, int] | None:
    smi = shutil.which("nvidia-smi")
    if not smi:
        return None
    try:
        out = subprocess.run([smi], capture_output=True, text=True, timeout=20).stdout
    except Exception:
        return None
    m = re.search(r"CUDA Version:\s*(\d+)\.(\d+)", out)
    return (int(m.group(1)), int(m.group(2))) if m else None


def _has_amd_gpu() -> bool:
    try:
        if sys.platform == "win32":
            import os
            sys32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
            return (sys32 / "amdhip64.dll").is_file() or (sys32 / "atiadlxx.dll").is_file()
        drm = Path("/sys/class/drm")
        for card in drm.glob("card*/device/vendor"):
            if card.read_text().strip().lower() == "0x1002":  # AMD PCI vendor id
                return True
    except Exception:
        pass
    return False


def _platform_tag() -> str:
    if sys.platform == "win32":
        return "win_amd64"
    return "linux_x86_64"  # abetlen linux wheels use the plain linux tag


def _pick_wheel(cuda_idx: str) -> tuple[str, str] | None:
    """Return (version, url) of the newest wheel for this python/platform."""
    url = WHEEL_INDEX.format(cuda=cuda_idx)
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            html = r.read().decode("utf-8", "replace")
    except Exception as exc:
        _say(f"index {cuda_idx} unavailable ({exc})")
        return None
    py = f"cp{sys.version_info.major}{sys.version_info.minor}"
    plat = _platform_tag()
    pat = re.compile(
        r'href="([^"]*llama_cpp_python-(\d+(?:\.\d+)+)[^"]*-%s-%s-[^"]*%s\.whl[^"]*)"'
        % (py, py, plat)
    )
    hits = pat.findall(html)
    if not hits:
        return None

    def _ver_key(v: str):
        return tuple(int(x) for x in v.split("."))

    href, version = max(hits, key=lambda h: _ver_key(h[1]))
    if href.startswith("http"):
        return version, href
    return version, urllib.request.urljoin(url, href)


def install(argv: list[str] | None = None) -> int:
    force = bool(argv and "--force" in argv)
    try:
        root = _eli_root()
    except RuntimeError as exc:
        return _fail(str(exc))

    dest = root / "runtime" / "gpu"
    if (dest / "llama_cpp").is_dir() and not force:
        _say(f"GPU pack already installed at {dest} (use --force to reinstall)")
        return 0

    drv = _driver_cuda_version()
    if drv is None:
        if _has_amd_gpu():
            return _fail(
                "AMD GPU detected. llama.cpp supports AMD via Vulkan/ROCm, but no "
                "official prebuilt python wheels exist yet, so the GPU pack cannot "
                "install one — ELI continues with CPU inference. A Vulkan GPU pack "
                "built by this project's CI is planned; source installs (install.sh) "
                "can compile llama-cpp-python with -DGGML_VULKAN=on today."
            )
        return _fail(
            "no NVIDIA driver detected (nvidia-smi not found or unreadable). "
            "The GPU pack only accelerates NVIDIA cards; Apple GPUs are already "
            "supported by the macOS build, and CPU inference keeps working."
        )
    _say(f"NVIDIA driver supports CUDA {drv[0]}.{drv[1]}")

    candidates = [c for c in CUDA_INDEXES if (int(c[2:4]), int(c[4:])) <= drv]
    if not candidates:
        return _fail(f"driver CUDA {drv[0]}.{drv[1]} is older than the oldest wheel index ({CUDA_INDEXES[-1]}) — update the NVIDIA driver")

    picked = None
    for cuda_idx in candidates:
        found = _pick_wheel(cuda_idx)
        if found:
            picked = (cuda_idx, *found)
            break
    if not picked:
        return _fail("no CUDA wheel found for this python/platform in the llama-cpp-python index")

    cuda_idx, version, url = picked
    _say(f"downloading llama-cpp-python {version} ({cuda_idx}, {_platform_tag()}) — several hundred MB…")
    with tempfile.TemporaryDirectory() as td:
        whl = Path(td) / "pack.whl"
        try:
            with urllib.request.urlopen(url, timeout=60) as r, open(whl, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                done = 0
                while chunk := r.read(1 << 20):
                    f.write(chunk)
                    done += len(chunk)
                    if total:
                        print(f"\r[gpu-pack] {done // (1 << 20)} / {total // (1 << 20)} MB", end="", flush=True)
                print(flush=True)
        except Exception as exc:
            return _fail(f"download failed: {exc}")

        staging = Path(td) / "unpacked"
        try:
            with zipfile.ZipFile(whl) as z:
                z.extractall(staging)
        except Exception as exc:
            return _fail(f"wheel unpack failed: {exc}")

        if not (staging / "llama_cpp").is_dir():
            return _fail("wheel did not contain a llama_cpp package")

        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        dest.mkdir(parents=True, exist_ok=True)
        for item in staging.iterdir():
            shutil.move(str(item), str(dest / item.name))

    (dest / ".gpu_pack.json").write_text(
        json.dumps({"version": version, "cuda_index": cuda_idx, "url": url}, indent=2),
        encoding="utf-8",
    )
    _say(f"installed to {dest}")
    _say("done — restart ELI; the model loader will now offload layers to the GPU.")
    return 0
