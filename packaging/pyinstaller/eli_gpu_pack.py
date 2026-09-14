"""NVIDIA GPU acceleration pack for frozen ELI builds.

The shipped bundle contains the CPU llama.cpp build (safe on every machine —
CUDA builds crash at boot without NVIDIA drivers). This module downloads the
matching CUDA build of llama-cpp-python from the official wheel index
(https://abetlen.github.io/llama-cpp-python/whl/<cuda>/) into
    <ELI root>/runtime/gpu/llama_cpp
and the runtime hook puts that directory FIRST on sys.path, so the CUDA copy
shadows the bundled CPU copy on the next launch. Like models and voices, the
heavy GPU binaries are per-machine downloads, never part of the installer.

Backends:
  NVIDIA      official CUDA wheels (abetlen index), picked by driver version
  AMD/Intel   CI-built Vulkan wheels from the ELI_v2.0 `gpu-packs` release
              (auto on AMD; use --vulkan to force, e.g. Intel Arc)
  Apple       nothing to do — the macOS bundle already uses Metal

Invoked via:  ELI --install-gpu-pack [--vulkan] [--force]
              (ELI-Server.exe on Windows shows progress)
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
# CI-built Vulkan wheels (AMD / Intel Arc) — built by .github/workflows/
# gpu-packs.yml in the public ELI_v2.0 repo; both v2 and v3 download from it.
VULKAN_RELEASE_API = "https://api.github.com/repos/ShadowESC95/ELI_v2.0/releases/tags/gpu-packs"
# Direct asset URLs — used when the GitHub Releases API is rate-limited or
# unreachable. Keep versions in sync with .github/workflows/gpu-packs.yml.
GPU_PACKS_DOWNLOAD = (
    "https://github.com/ShadowESC95/ELI_v2.0/releases/download/gpu-packs"
)
# Newest-first. ``py3-none`` wheels work on every CPython 3.x; cp311 tags are
# legacy fallbacks from older CI builds.
_GPU_PACK_FALLBACK_ASSETS: tuple[str, ...] = (
    "vulkan-llama_cpp_python-0.3.35-py3-none-linux_x86_64.whl",
    "vulkan-llama_cpp_python-0.3.35-py3-none-win_amd64.whl",
    "cuda-llama_cpp_python-0.3.35-py3-none-linux_x86_64.whl",
    "cuda-llama_cpp_python-0.3.35-py3-none-win_amd64.whl",
    "vulkan-llama_cpp_python-0.3.19-cp311-cp311-linux_x86_64.whl",
    "vulkan-llama_cpp_python-0.3.19-cp311-cp311-win_amd64.whl",
)


def _log_path() -> "Path | None":
    """Install log location — inside the user root, next to the pack itself."""
    import os
    root = os.environ.get("ELI_PROJECT_ROOT")
    if not root:
        return None
    try:
        p = Path(root) / "runtime"
        p.mkdir(parents=True, exist_ok=True)
        return p / "gpu-pack.log"
    except Exception:
        return None


def _record(line: str) -> None:
    """Append to the install log. Frozen GUI builds have no visible console, so
    without this a failure leaves the user (and a bug report) with nothing but
    'could not be installed or verified' and no way to find out why."""
    p = _log_path()
    if p is None:
        return
    try:
        import time
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")
    except Exception:
        pass


def _say(msg: str) -> None:
    print(f"[gpu-pack] {msg}", flush=True)
    _record(msg)


def _fail(msg: str) -> int:
    print(f"[gpu-pack] ERROR: {msg}", file=sys.stderr, flush=True)
    _record(f"ERROR: {msg}")
    return 1


def last_failure() -> str:
    """The most recent recorded ERROR line, for the GUI to show the user."""
    p = _log_path()
    if p is None or not p.is_file():
        return ""
    try:
        errors = [l for l in p.read_text(encoding="utf-8", errors="replace").splitlines()
                  if " ERROR: " in l]
        return errors[-1].split(" ERROR: ", 1)[1].strip() if errors else ""
    except Exception:
        return ""


def _eli_root() -> Path:
    import os
    env = os.environ.get("ELI_PROJECT_ROOT")
    if env:
        return Path(env)
    raise RuntimeError("ELI_PROJECT_ROOT not set — run via the ELI executable")


def _nvidia_driver_version() -> tuple[int, int] | None:
    """(major, minor) of the installed NVIDIA driver — distro-independent.

    Reads the version from ``nvidia-smi --query-gpu=driver_version`` (a stable
    machine field, unlike the human header) and falls back to
    ``/proc/driver/nvidia/version``, which the kernel module writes on EVERY
    distro whenever it is loaded. Neither depends on the CUDA-header line that
    Node's Optimus + driver-610 setup didn't emit."""
    smi = _smi()
    if smi:
        try:
            out = subprocess.run([smi, "--query-gpu=driver_version", "--format=csv,noheader"],
                                 capture_output=True, text=True, timeout=20)
            m = re.search(r"(\d+)\.(\d+)", out.stdout or "")
            if m:
                return int(m.group(1)), int(m.group(2))
        except Exception:
            pass
    try:  # e.g. "NVRM version: NVIDIA UNIX x86_64 Kernel Module  610.43.03  ..."
        txt = Path("/proc/driver/nvidia/version").read_text()
        m = re.search(r"Kernel Module\s+(\d+)\.(\d+)", txt)
        if m:
            return int(m.group(1)), int(m.group(2))
    except Exception:
        pass
    # Windows has no /proc; the driver records its version in the display-class
    # registry key. Without this the driver version was unknowable off Linux
    # whenever nvidia-smi was unavailable, and no CUDA build could be chosen.
    if sys.platform == "win32":
        ps = shutil.which("powershell") or shutil.which("pwsh")
        if ps:
            try:
                q = (
                    "$ErrorActionPreference='SilentlyContinue';"
                    "(Get-ItemProperty 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Class\\"
                    "{4d36e968-e325-11ce-bfc1-08002be10318}\\*' |"
                    " Where-Object { $_.ProviderName -like '*NVIDIA*' } |"
                    " Select-Object -First 1).DriverVersion"
                )
                out = subprocess.run([ps, "-NoProfile", "-Command", q],
                                     capture_output=True, text=True, timeout=25)
                # Windows reports e.g. 32.0.15.6094 -> NVIDIA driver 560.94
                m = re.search(r"(\d+)\.(\d+)\.(\d+)\.(\d+)", out.stdout or "")
                if m:
                    digits = (m.group(3) + m.group(4))[-5:]
                    return int(digits[:3]), int(digits[3:])
            except Exception:
                pass
    return None


def _cuda_from_driver(drv: tuple[int, int]) -> tuple[int, int] | None:
    """Max CUDA a Linux NVIDIA driver supports — coarse but monotonic, enough to
    choose among the cu121..cu124 wheel indices. Newer drivers are backward
    compatible, so a driver >= 550 (incl. Node's 610) safely runs the cu124 pack."""
    major = drv[0]
    for min_drv, cuda in ((550, (12, 4)), (545, (12, 3)), (535, (12, 2)), (525, (12, 1))):
        if major >= min_drv:
            return cuda
    return None  # older than the oldest wheel index


def _driver_cuda_version() -> tuple[int, int] | None:
    """Best CUDA version the NVIDIA driver supports. Tries, in order: the
    ``CUDA Version`` header from ``nvidia-smi`` (bare, then ``-q``), then DERIVES
    it from the driver version. The header is a display string that some drivers/
    configs (Optimus, headless, very new drivers) omit or garble — deriving from
    the driver version makes wheel selection work regardless, on every distro."""
    smi = _smi()
    if smi:
        for args in ([smi], [smi, "-q"]):
            try:
                out = subprocess.run(args, capture_output=True, text=True, timeout=20).stdout or ""
            except Exception:
                out = ""
            m = re.search(r"CUDA Version\s*:?\s*(\d+)\.(\d+)", out)
            if m:
                return int(m.group(1)), int(m.group(2))
    drv = _nvidia_driver_version()
    if drv is not None:
        return _cuda_from_driver(drv)
    return None


# PCI vendor ids (sysfs `/sys/.../vendor`, lowercased). One source of truth so
# every vendor is detected the SAME robust way, on every OS.
_PCI_VENDOR = {"nvidia": "0x10de", "amd": "0x1002", "intel": "0x8086"}
# Known DISCRETE Intel Arc PCI device-id ranges (Alchemist / Arc Pro / Battlemage).
# Used so an Intel iGPU (same 0x8086 vendor, but Vulkan offload rarely beats CPU)
# is NOT auto-routed to a GPU pack, while a real discrete Arc is.
_INTEL_ARC_DEVICE_RANGES = ((0x4F80, 0x4F8F), (0x5690, 0x56BF), (0xE200, 0xE21F))


def _smi() -> str | None:
    """nvidia-smi by absolute path, PATH or not.

    On Windows the driver installs nvidia-smi into System32 and the CUDA
    toolkit into its own directory; a frozen app can inherit an environment
    where neither is on PATH. shutil.which() then returns None and the GPU
    pack concludes "no NVIDIA GPU" on a machine that has one -- which is how a
    working card ended up running on CPU with 0 offloaded layers.
    """
    found = shutil.which("nvidia-smi")
    if found:
        return found
    import os
    if sys.platform == "win32":
        cands = [
            Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "nvidia-smi.exe",
            Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
            / "NVIDIA Corporation" / "NVSMI" / "nvidia-smi.exe",
            Path(os.environ.get("ProgramW6432", r"C:\Program Files"))
            / "NVIDIA Corporation" / "NVSMI" / "nvidia-smi.exe",
        ]
    else:
        cands = [Path("/usr/bin/nvidia-smi"), Path("/usr/local/bin/nvidia-smi"),
                 Path("/opt/nvidia/bin/nvidia-smi")]
    for c in cands:
        try:
            if c.is_file():
                return str(c)
        except Exception:
            continue
    return None


def _sysfs_pci_vendor_present(vendor_hex: str) -> bool:
    """True if any PCI device reports *vendor_hex* (Linux sysfs). Vendor-neutral."""
    try:
        import os
        for entry in os.listdir("/sys/bus/pci/devices"):
            try:
                if (Path("/sys/bus/pci/devices") / entry / "vendor").read_text().strip().lower() == vendor_hex:
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


_NVIDIA_SMI_ERROR_RE = re.compile(
    r"(?i)failed|couldn.?t\s+communicate|nvidia-smi|driver\s+not|"
    r"unable\s+to\s+determine|no\s+devices\s+were\s+found|"
    r"not\s+supported|has\s+failed"
)


def _nvidia_smi_stdout_usable(text: str) -> bool:
    """True when nvidia-smi stdout looks like a real GPU name, not an error blob."""
    raw = (text or "").strip()
    if not raw:
        return False
    for line in raw.splitlines():
        s = line.strip()
        if not s or _NVIDIA_SMI_ERROR_RE.search(s):
            continue
        # nvidia-smi -L: "GPU 0: GeForce ..." / --query-gpu: bare name
        if s.upper().startswith("GPU ") or len(s) >= 3:
            return True
    return False


def _has_nvidia_gpu() -> bool:
    """True if a usable NVIDIA GPU is present (not merely a stub driver / PCI id).

    ``_driver_cuda_version`` scrapes ``CUDA Version:`` out of the bare ``nvidia-smi``
    table, but that line can be absent/garbled on some setups (hybrid Intel+NVIDIA
    Optimus laptops, very new drivers) even though the GPU works fine and the same
    machine reads VRAM cleanly via ``nvidia-smi --query-gpu``. Failing to parse the
    version must NOT be mistaken for "no NVIDIA GPU" — that regression forced a
    working 1660 Ti onto CPU.

    Conversely: when ``nvidia-smi`` is installed but only prints
    ``NVIDIA-SMI has failed because it couldn't communicate with the NVIDIA
    driver``, do NOT fall through to PCI / ``libcuda.so.1`` stubs. Those signals
    are common on Intel-iGPU laptops with a broken leftover NVIDIA package and
    previously caused a CUDA wheel install on machines that cannot run CUDA.
    """
    smi = _smi()
    if smi:
        for args in ([smi, "-L"], [smi, "--query-gpu=name", "--format=csv,noheader"]):
            try:
                out = subprocess.run(args, capture_output=True, text=True, timeout=20)
                if out.returncode == 0 and _nvidia_smi_stdout_usable(out.stdout or ""):
                    return True
            except Exception:
                continue
        # Tool present but unusable — refuse PCI/stub fallback.
        return False
    # Kernel-provided signals — present on EVERY distro when the driver is loaded,
    # independent of nvidia-smi/userspace tools being installed or well-behaved.
    if Path("/proc/driver/nvidia/version").is_file() or Path("/sys/module/nvidia").is_dir():
        return True
    if _sysfs_pci_vendor_present(_PCI_VENDOR["nvidia"]):
        return True
    if sys.platform == "win32":
        import os
        sys32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
        if (sys32 / "nvcuda.dll").is_file() or (sys32 / "nvml.dll").is_file():
            return True
    return False


def _has_amd_gpu() -> bool:
    """True if an AMD GPU is present, on every OS. Presence-based (no fragile
    version parse): the driver runtime DLLs (Windows), the PCI vendor id in sysfs
    (Linux), or an rocm-smi that lists a device."""
    if sys.platform == "win32":
        import os
        sys32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
        if (sys32 / "amdhip64.dll").is_file() or (sys32 / "atiadlxx.dll").is_file():
            return True
    if _sysfs_pci_vendor_present(_PCI_VENDOR["amd"]):
        return True
    smi = shutil.which("rocm-smi")
    if smi:
        try:
            out = subprocess.run([smi, "--showid"], capture_output=True, text=True, timeout=20)
            if out.returncode == 0 and "GPU" in (out.stdout or ""):
                return True
        except Exception:
            pass
    return False


def _has_intel_igpu() -> bool:
    """Intel Iris Xe / UHD integrated graphics (shared memory)."""
    try:
        from eli.core.hardware_profile import detect_hardware
        hw = detect_hardware()
        return bool(hw.gpu_integrated and hw.gpu_vendor == "intel")
    except Exception:
        return False


def _has_qualcomm_igpu() -> bool:
    """Qualcomm Adreno / Snapdragon unified-memory GPU."""
    try:
        from eli.core.hardware_profile import detect_hardware
        hw = detect_hardware()
        return bool(hw.gpu_integrated and hw.gpu_vendor == "qualcomm")
    except Exception:
        return False


def _has_intel_arc_gpu() -> bool:
    """True for a DISCRETE Intel Arc GPU (NOT an integrated iGPU).

    Linux: the newer ``xe`` kernel driver is discrete-only, or a PCI device id in a
    known Arc family range. Windows: detect_hardware's registry scan surfaces the
    adapter name (e.g. "Intel Arc A770"); the first-run offer routes it to Vulkan
    from there, and ``--install-gpu-pack --vulkan`` always works."""
    try:
        for dev in Path("/sys/class/drm").glob("card*/device"):
            try:
                if (dev / "vendor").read_text().strip().lower() != _PCI_VENDOR["intel"]:
                    continue
                try:
                    if (dev / "driver").resolve().name.lower() == "xe":
                        return True
                except Exception:
                    pass
                did = int((dev / "device").read_text().strip(), 16)
                if any(lo <= did <= hi for lo, hi in _INTEL_ARC_DEVICE_RANGES):
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def _vulkan_loader_present() -> bool:
    """The Vulkan pack needs the system Vulkan loader (GPU drivers ship it;
    minimal Linux installs may not have it)."""
    try:
        if sys.platform == "win32":
            import os
            return (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "vulkan-1.dll").is_file()
        import ctypes.util
        return bool(ctypes.util.find_library("vulkan"))
    except Exception:
        return True  # inconclusive — let the install-time verifier decide


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
    # Two ABI shapes: the old cpXY-cpXY tag, and the py3-none tag that
    # scikit-build-core produces for current releases. Matching only the first
    # made every 0.3.3x pack invisible to the installer.
    pat = re.compile(
        r'href="([^"]*llama_cpp_python-(\d+(?:\.\d+)+)[^"]*-(?:%s-%s|py3-none)-[^"]*%s\.whl[^"]*)"'
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


# Below this, llama.cpp cannot read hybrid attention+SSM GGUFs (qwen35,
# nemotron-h): they fail with a missing ssm_conv1d tensor. The abetlen CUDA
# index stops at 0.3.19 for several interpreters, so an NVIDIA machine could
# end up with a GPU-accelerated runtime that cannot open current models --
# while the AppImage it came from bundles a newer one that can. Measured on a
# live 2.3.17 install: pack 0.3.19 failed, the bundled 0.3.35 loaded the same
# file fine.
MIN_MODERN_ARCH_VERSION = (0, 3, 30)


def _ver_tuple(v: str) -> tuple:
    out = []
    for part in str(v or "").split("."):
        try:
            out.append(int(part))
        except ValueError:
            break
    return tuple(out)


def _too_old_for_modern_archs(version: str) -> bool:
    t = _ver_tuple(version)
    return bool(t) and t < MIN_MODERN_ARCH_VERSION


def pack_backend_from_url(url: str) -> str:
    """Name the backend a gpu-packs asset actually contains.

    The gpu-packs release carries both cuda- and vulkan- built wheels. Labelling
    by URL/filename (not by caller intent) keeps .gpu_pack.json honest.
    """
    raw = str(url).replace("\\", "/")
    name = raw.rsplit("/", 1)[-1].lower()
    if name.startswith("cuda-") or "/cuda-" in raw.lower():
        return "cuda"
    return "vulkan"


def _normalize_cuda_idx(cuda_idx: str) -> str:
    """Map a backend label to a cuNNN PyPI pin.

    Never treat the bare label ``\"cuda\"`` as a cuNNN token (``\"cuda\".startswith(\"cu\")``
    used to yield the nonsense minor ``da.`` and accidentally pulled the *newest*
    cudart — which worked). Mapping ``cuda`` → ``cu124`` then pinned an *older*
    runtime than the CI wheel (built with CUDA 12.6 in gpu-packs.yml), and verify
    failed on live NVIDIA boxes even though ``ggml_cuda_init`` found the GPU.
    """
    s = (cuda_idx or "").strip().lower()
    if re.fullmatch(r"cu\d{2,3}", s):
        return s
    # CI-built cuda-* packs (.github/workflows/gpu-packs.yml) use toolkit 12.6.
    if s in ("cuda", "ci", "gpu-packs", ""):
        return "cu126"
    return "cu126"


def _libdir_has_cuda_natives(libdir: Path) -> bool:
    if not libdir.is_dir():
        return False
    if sys.platform == "win32":
        return bool(list(libdir.glob("*ggml*cuda*.dll")) or list(libdir.glob("ggml-cuda*.dll")))
    return bool(list(libdir.glob("libggml-cuda.so*")))


def _libdir_has_vulkan_natives(libdir: Path) -> bool:
    if not libdir.is_dir():
        return False
    if sys.platform == "win32":
        return bool(list(libdir.glob("*ggml*vulkan*.dll")) or list(libdir.glob("ggml-vulkan*.dll")))
    return bool(list(libdir.glob("libggml-vulkan.so*")))


def _libdir_has_cudart(libdir: Path) -> bool:
    if not libdir.is_dir():
        return False
    if sys.platform == "win32":
        return bool(list(libdir.glob("cudart64*.dll")))
    return bool(list(libdir.glob("libcudart.so*")))


def _assert_cuda_runtime_complete(libdir: Path) -> None:
    """Fail closed when a CUDA ggml backend is present without vendored cudart/cublas."""
    if not _libdir_has_cuda_natives(libdir):
        return
    missing: list[str] = []
    if sys.platform == "win32":
        if not list(libdir.glob("cudart64*.dll")):
            missing.append("cudart64_*.dll")
        if not (list(libdir.glob("cublas64*.dll")) or list(libdir.glob("cublasLt64*.dll"))):
            missing.append("cublas64_*.dll / cublasLt64_*.dll")
    else:
        if not list(libdir.glob("libcudart.so*")):
            missing.append("libcudart.so.12")
        if not (list(libdir.glob("libcublas.so*")) or list(libdir.glob("libcublasLt.so*"))):
            missing.append("libcublas.so.12")
    if missing:
        raise RuntimeError(
            "CUDA GPU pack is missing vendored NVIDIA runtime libraries: "
            + ", ".join(missing)
            + ". Without them libggml-cuda.so cannot load on machines that do not "
            "have a full CUDA toolkit installed."
        )


def _dedupe_wheel_native_trees(staging: Path) -> None:
    """Wheels ship identical natives under ``lib/`` and ``llama_cpp/lib/``.

    Keep ``llama_cpp/lib/`` (what Python loads) and drop duplicate top-level
    ``lib/*.so*`` / ``*.dll`` copies — saves ~1.3 GB on CUDA packs.
    """
    primary = staging / "llama_cpp" / "lib"
    duplicate = staging / "lib"
    if not primary.is_dir() or not duplicate.is_dir():
        return
    for p in list(duplicate.iterdir()):
        if not p.is_file():
            continue
        name = p.name
        is_native = (
            name.endswith(".so")
            or ".so." in name
            or name.lower().endswith(".dll")
        )
        if not is_native:
            continue
        if (primary / name).exists():
            try:
                p.unlink()
            except Exception:
                pass


def _bundled_gpu_dir() -> Path | None:
    """Directory of GPU-pack wheels shipped inside the bundle or portable tar."""
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            candidates.append(Path(meipass) / "gpu-packs")
    try:
        root = _eli_root()
        candidates.append(root / "gpu-packs")
    except RuntimeError:
        pass
    for d in candidates:
        try:
            if d.is_dir() and any(d.glob("*.whl")):
                return d
        except Exception:
            continue
    return None


def _wheel_name_matches_platform(name: str) -> bool:
    py = f"cp{sys.version_info.major}{sys.version_info.minor}"
    plat = _platform_tag()
    if py in name or "py3-none" in name:
        if plat in name or (plat.startswith("linux") and "linux" in name):
            return True
        if sys.platform == "win32" and "win" in name.lower():
            return True
    return False


def _pick_bundled_wheel(*, prefer_cuda: bool = True) -> tuple[str, str, Path] | None:
    """Return (backend, version, local_wheel_path) for the best bundled wheel."""
    d = _bundled_gpu_dir()
    if not d:
        return None
    best_cuda: tuple[tuple, str, str, Path] | None = None
    best_vulkan: tuple[tuple, str, str, Path] | None = None
    for whl in sorted(d.glob("*.whl")):
        if not _wheel_name_matches_platform(whl.name):
            continue
        m = re.match(
            r"^(cuda|vulkan)-llama_cpp_python-(\d+(?:\.\d+)+).*\.whl$",
            whl.name,
        )
        if not m:
            continue
        backend, version = m.group(1), m.group(2)
        rank = (_ver_tuple(version), 1 if backend == "cuda" else 0)
        entry = (rank, backend, version, whl)
        if backend == "cuda":
            if best_cuda is None or entry[0] > best_cuda[0]:
                best_cuda = entry
        else:
            if best_vulkan is None or entry[0] > best_vulkan[0]:
                best_vulkan = entry
    pick = None
    if prefer_cuda and best_cuda is not None:
        pick = best_cuda
    elif best_vulkan is not None:
        pick = best_vulkan
    elif best_cuda is not None:
        pick = best_cuda
    if not pick:
        return None
    return pick[1], pick[2], pick[3]


def _activate_staged_gpu_pack(
    staging: Path,
    *,
    dest: Path,
    backend: str,
    version: str,
    source: str,
    cuda_idx: str = "cu124",
) -> int:
    """Vendor CUDA runtimes if needed, move into dest, verify, write markers."""
    if not (staging / "llama_cpp").is_dir():
        return _fail("wheel did not contain a llama_cpp package")

    libdir = staging / "llama_cpp" / "lib"
    # Content-based: never skip cudart/cublas when libggml-cuda is in the wheel,
    # even if the caller mislabelled the pack as "vulkan".
    has_cuda = _libdir_has_cuda_natives(libdir)
    has_vk = _libdir_has_vulkan_natives(libdir)
    if has_cuda and not has_vk and backend == "vulkan":
        _say("wheel contains CUDA natives but was labelled vulkan — correcting to cuda")
        backend = "cuda"
    if has_cuda or (backend not in ("", "vulkan") and not has_vk):
        try:
            with tempfile.TemporaryDirectory() as td:
                _vendor_cuda_runtime(libdir, Path(td), _normalize_cuda_idx(cuda_idx))
        except Exception as exc:
            return _fail(f"could not fetch the CUDA runtime libraries: {exc}")
        try:
            _assert_cuda_runtime_complete(libdir)
        except RuntimeError as exc:
            return _fail(str(exc))

    _dedupe_wheel_native_trees(staging)

    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)
    for item in staging.iterdir():
        shutil.move(str(item), str(dest / item.name))

    _say("verifying the GPU pack loads on this machine…")
    # Relax offload only for true Vulkan packs on shared-memory iGPU — never for
    # a CUDA pack that happened to be requested via --vulkan.
    relax_offload = (
        backend == "vulkan"
        and _libdir_has_vulkan_natives(dest / "llama_cpp" / "lib")
        and _shared_memory_gpu()
    )
    ok, detail = _verify(dest, require_offload=not relax_offload)
    if not ok:
        shutil.rmtree(dest, ignore_errors=True)
        _no_offload = "gpu-pack-verify-no-offload" in (detail or "")
        return _fail(
            ("the GPU build loaded but reports NO GPU offload on this machine — "
             "removed it rather than letting it shadow the bundled CPU runtime. "
             "ELI stays on CPU (fully functional)."
             if _no_offload else
             "the GPU build failed to load on this machine — removed it; "
             "ELI stays on CPU (fully functional).")
            + f"\nLoader said: {detail}"
        )

    (dest / ".gpu_pack.json").write_text(
        json.dumps({"version": version, "backend": backend, "source": source}, indent=2),
        encoding="utf-8",
    )
    (dest / ".gpu_pack_ok").write_text("verified", encoding="utf-8")
    _say(f"installed and verified at {dest}")
    _say("done — the model loader will now offload layers to the GPU.")
    return 0


def _pack_backend(dest: Path) -> str:
    try:
        meta = json.loads((dest / ".gpu_pack.json").read_text(encoding="utf-8"))
        return str((meta or {}).get("backend") or "").strip().lower()
    except Exception:
        return ""


def _relax_offload_verify(dest: Path | None = None) -> bool:
    """Match install-time policy: Vulkan on shared-memory iGPU often reports
    ``llama_supports_gpu_offload() == False`` even when the pack is usable.
    Install already writes ``.gpu_pack_ok`` in that case; activate/operational
    must not contradict it or the UI shows a false 'install failed'."""
    if dest is None:
        return False
    root = Path(dest)
    if _pack_backend(root) != "vulkan":
        return False
    # Mislabelled / incomplete CUDA packs must never get the Vulkan iGPU waiver.
    lib = root / "llama_cpp" / "lib"
    if _libdir_has_cuda_natives(lib) and not _libdir_has_vulkan_natives(lib):
        return False
    return _shared_memory_gpu()


def gpu_pack_operational(dest: Path | None = None) -> bool:
    """True when a verified pack loads and reports GPU offload in THIS environment.

    Matches the frozen runtime hook: a stale CUDA pack on Intel iGPU, or any pack
    whose backend cannot bind here, is treated as not installed.
    Vulkan + shared-memory iGPU: offload flag is optional (same as install verify).
    """
    try:
        root = _eli_root()
    except RuntimeError:
        return False
    dest = dest or (root / "runtime" / "gpu")
    if not (dest / ".gpu_pack_ok").is_file() or not (dest / "llama_cpp").is_dir():
        return False
    ok, _detail = _verify(dest, require_offload=not _relax_offload_verify(dest))
    return bool(ok)


def _install_from_local_wheel(
    whl_path: Path,
    backend: str,
    version: str,
    *,
    force: bool = False,
    cuda_idx: str = "cu124",
) -> int:
    """Install a GPU pack from a wheel already on disk (bundled asset)."""
    try:
        root = _eli_root()
    except RuntimeError as exc:
        return _fail(str(exc))
    dest = root / "runtime" / "gpu"
    if (dest / "llama_cpp").is_dir() and (dest / ".gpu_pack_ok").is_file() and not force:
        if gpu_pack_operational(dest):
            _say(f"GPU pack already installed at {dest}")
            return 0
        _say("GPU pack present but cannot offload — reinstalling…")
        force = True
    with tempfile.TemporaryDirectory() as td:
        staging = Path(td) / "unpacked"
        try:
            with zipfile.ZipFile(whl_path) as z:
                z.extractall(staging)
        except Exception as exc:
            return _fail(f"wheel unpack failed: {exc}")
        return _activate_staged_gpu_pack(
            staging,
            dest=dest,
            backend=backend,
            version=version,
            source=str(whl_path),
            cuda_idx=cuda_idx,
        )


def ensure_gpu_pack_for_hardware(*, bundle_only: bool = False) -> int:
    """Detect hardware and install a verified GPU pack (bundled first, then network).

    Safe to call before llama_cpp is imported. Returns 0 when GPU offload is ready
    or when no GPU is present; non-zero only on an explicit install failure.
    """
    try:
        root = _eli_root()
    except RuntimeError:
        return 0

    dest = root / "runtime" / "gpu"
    if gpu_pack_operational(dest):
        return 0
    if (dest / ".gpu_pack_ok").is_file():
        try:
            (dest / ".gpu_pack_ok").unlink(missing_ok=True)
        except Exception:
            pass

    runtime = root / "runtime"
    marker = runtime / ".gpu_choice"
    try:
        from eli.core.hardware_profile import detect_hardware
        hp = detect_hardware()
    except Exception:
        return 0

    runtime.mkdir(parents=True, exist_ok=True)
    if not hp.has_gpu:
        marker.write_text("cpu-no-gpu-hardware", encoding="utf-8")
        return 0

    # A stale cpu-user-choice marker must not block reinstall when the pack is gone.
    if marker.is_file():
        choice = marker.read_text(encoding="utf-8", errors="replace").strip()
        if choice == "cpu-no-gpu-hardware":
            return 0

    name_l = (hp.gpu_name or "").lower()
    nvidia = "nvidia" in name_l or "geforce" in name_l or "rtx" in name_l or "gtx" in name_l
    bundled = _pick_bundled_wheel(prefer_cuda=nvidia)
    if bundled:
        bk, ver, path = bundled
        _say(f"hardware={hp.gpu_name!r} — installing bundled {bk} pack ({path.name})")
        rc = _install_from_local_wheel(path, bk, ver)
        if rc == 0:
            marker.write_text("gpu-bundled", encoding="utf-8")
        return rc

    if bundle_only:
        return 1

    _say(f"hardware={hp.gpu_name!r} — no bundled GPU pack; downloading for this machine…")
    argv: list[str] = []
    if not nvidia and ("amd" in name_l or "radeon" in name_l or "arc" in name_l
                       or getattr(hp, "gpu_integrated", False)):
        argv.append("--vulkan")
    rc = install(argv)
    if rc == 0:
        marker.write_text("gpu-download", encoding="utf-8")
    return rc


def _pick_vulkan_wheel(*, prefer_cuda: bool = False) -> tuple[str, str] | None:
    """Return (version, url) of a CI-built gpu-packs wheel for this python/platform.

    ``prefer_cuda=False`` (AMD / Intel / ``--vulkan``): only ``vulkan-`` assets.
    Preferring CUDA here previously installed a CUDA wheel on Iris Xe machines,
    labelled it vulkan, skipped cudart vendoring, and left a broken 2.7 GB pack.

    ``prefer_cuda=True`` (NVIDIA modern-arch fallback): newest wheel, CUDA over
    Vulkan at the same version — CUDA is the native NVIDIA backend.
    """
    py = f"cp{sys.version_info.major}{sys.version_info.minor}"
    plat = _platform_tag()
    prefix = r"(?:vulkan|cuda)" if prefer_cuda else r"vulkan"
    pat = re.compile(
        r"%s-llama_cpp_python-(\d+(?:\.\d+)+)-(?:%s-%s|py3-none)-.*%s\.whl"
        % (prefix, py, py, plat)
    )

    def _best_from_names(entries: list[tuple[str, str]]) -> tuple[str, str] | None:
        # entries: (filename, download_url)
        best = None
        for name, url in entries:
            m = pat.fullmatch(name)
            if not m:
                continue
            ver = _ver_tuple(m.group(1))
            rank = (ver, 1 if (prefer_cuda and name.startswith("cuda-")) else 0)
            if best is None or rank > best[0]:
                best = (rank, m.group(1), url)
        return (best[1], best[2]) if best else None

    assets: list[tuple[str, str]] = []
    api_err: str | None = None
    try:
        with urllib.request.urlopen(VULKAN_RELEASE_API, timeout=30) as r:
            for a in json.load(r).get("assets", []) or []:
                name = str(a.get("name") or "")
                url = str(a.get("browser_download_url") or "")
                if name and url:
                    assets.append((name, url))
    except Exception as exc:
        api_err = str(exc)
        _say(f"gpu-packs release API unavailable ({exc}) — trying direct download URLs")

    picked = _best_from_names(assets) if assets else None
    if picked:
        return picked

    # Rate-limit / offline API / empty asset list: fall back to known release
    # filenames so Iris/AMD machines are not told "no Vulkan wheel" when the
    # 103 MB vulkan-0.3.35 asset is sitting on the same tag.
    fallback = [
        (name, f"{GPU_PACKS_DOWNLOAD}/{name}")
        for name in _GPU_PACK_FALLBACK_ASSETS
    ]
    picked = _best_from_names(fallback)
    if picked:
        _say(f"using direct gpu-packs URL for {picked[1].rsplit('/', 1)[-1]}")
        return picked

    if api_err:
        _say(f"no matching gpu-packs asset after API failure ({api_err})")
    return None


def install(argv: list[str] | None = None) -> int:
    """Install the GPU pack, recording any unexpected crash to the install log.

    Callers run this on a worker thread and only see the return code, so an
    escaping exception would otherwise vanish entirely.

    Opens a scoped NetGuard allow window: ELI is offline-by-default, and GPU
    pack install is an explicit user/first-run download (abetlen index, GitHub
    gpu-packs, PyPI cudart/cublas). Without this, every index probe fails with
    ``network disabled (offline mode)`` and the UI shows a false
    ``no CUDA wheel found``.
    """
    try:
        try:
            from eli.core.netguard import allow_network
        except Exception:
            return _install(argv)
        with allow_network("gpu-pack install"):
            return _install(argv)
    except Exception:
        import traceback
        return _fail(f"unexpected error:\n{traceback.format_exc()}")


def _install(argv: list[str] | None = None) -> int:
    argv = argv or []
    force = "--force" in argv
    want_vulkan = "--vulkan" in argv
    try:
        root = _eli_root()
    except RuntimeError as exc:
        return _fail(str(exc))

    dest = root / "runtime" / "gpu"
    if (dest / "llama_cpp").is_dir() and not force:
        if gpu_pack_operational(dest):
            _say(f"GPU pack already installed at {dest} (use --force to reinstall)")
            return 0
        _say("GPU pack present but cannot offload — reinstalling…")
        force = True

    # Vendor presence — checked the SAME robust, presence-based way for every
    # vendor on every OS. An NVIDIA GPU counts as present if we parsed its CUDA
    # version OR simply see the card: the version parse is a refinement for picking
    # the exact wheel, not the gate for "is this NVIDIA". Conflating the two forced
    # a working 1660 Ti (whose bare nvidia-smi lacked a parseable CUDA line) onto CPU.
    drv = None if want_vulkan else _driver_cuda_version()
    nvidia_present = (not want_vulkan) and (drv is not None or _has_nvidia_gpu())
    amd_present = (not want_vulkan) and _has_amd_gpu()
    intel_arc_present = (not want_vulkan) and _has_intel_arc_gpu()
    intel_igpu_present = (not want_vulkan) and _has_intel_igpu()
    qualcomm_igpu_present = (not want_vulkan) and _has_qualcomm_igpu()
    if nvidia_present:
        if drv is not None:
            _say(f"NVIDIA driver supports CUDA {drv[0]}.{drv[1]}")
            candidates = [c for c in CUDA_INDEXES if (int(c[2:4]), int(c[4:])) <= drv]
            if not candidates:
                return _fail(f"driver CUDA {drv[0]}.{drv[1]} is older than the oldest wheel index ({CUDA_INDEXES[-1]}) — update the NVIDIA driver")
        else:
            # NVIDIA GPU present but the driver's CUDA version was unreadable — try
            # newest→oldest CUDA wheels. The install-time load verify rejects any
            # build the driver can't actually run, so this is safe, not a gamble.
            _say("NVIDIA GPU detected but the driver's CUDA version was unreadable — "
                 "trying the newest CUDA wheels (each is load-verified before it activates)")
            candidates = list(CUDA_INDEXES)
        picked = None
        for cuda_idx in candidates:
            found = _pick_wheel(cuda_idx)
            if found:
                picked = (cuda_idx, *found)
                break
        if not picked:
            # abetlen index down / still blocked / no matching tag — CI cuda
            # packs on the gpu-packs release are the supported NVIDIA fallback.
            _say("official CUDA wheel index had no usable wheel — "
                 "trying CI-built CUDA pack from the gpu-packs release")
            ci = _pick_vulkan_wheel(prefer_cuda=True)
            if ci and pack_backend_from_url(ci[1]) == "cuda":
                backend, version, url = "cuda", ci[0], ci[1]
            else:
                return _fail(
                    "no CUDA wheel found for this python/platform in the "
                    "llama-cpp-python index or the gpu-packs release. "
                    "Check network access (ELI is offline-by-default; GPU pack "
                    "install opens a scoped allow window — retry after 2.4.26). "
                    "CPU inference keeps working."
                )
        else:
            backend, version, url = picked

        # The CUDA index is frequently far behind. When the best CUDA wheel is
        # too old to read current architectures, prefer the CI-built pack:
        # it is built from CURRENT llama-cpp-python source by
        # .github/workflows/gpu-packs.yml. Prefer CUDA on NVIDIA; Vulkan only
        # when that is what the asset actually is.
        if _too_old_for_modern_archs(version):
            _say(f"newest CUDA wheel is {version}, which cannot read current model "
                 f"architectures (needs >= {'.'.join(map(str, MIN_MODERN_ARCH_VERSION))})")
            vk = _pick_vulkan_wheel(prefer_cuda=True)
            # Prefer CUDA CI packs on NVIDIA; label by asset URL. Only demand the
            # Vulkan loader when the pick really is a Vulkan build.
            _bk = pack_backend_from_url(vk[1]) if vk else "vulkan"
            if vk and not _too_old_for_modern_archs(vk[0]) and (
                    _bk == "cuda" or _vulkan_loader_present()):
                _say(f"using the CI-built {_bk.upper()} pack {vk[0]} instead — "
                     f"GPU-accelerated on NVIDIA and current enough for hybrid "
                     f"attention+SSM models")
                backend, version, url = _bk, vk[0], vk[1]
            else:
                _say("no newer Vulkan pack available — installing the CUDA wheel. "
                     "Models with newer architectures will not load under it; run "
                     "with ELI_DISABLE_GPU_PACK=1 to use the bundled runtime instead.")
    elif want_vulkan or amd_present or intel_arc_present or intel_igpu_present or qualcomm_igpu_present:
        # AMD / Intel (Arc or iGPU) / Qualcomm Adreno (or forced): CI-built Vulkan backend.
        # The GPU driver already ships the Vulkan loader the wheel needs.
        if amd_present:
            _vendor = "AMD"
        elif intel_arc_present:
            _vendor = "Intel Arc"
        elif intel_igpu_present:
            _vendor = "Intel integrated (Iris Xe / UHD)"
        elif qualcomm_igpu_present:
            _vendor = "Qualcomm Adreno"
        else:
            _vendor = "GPU"
        _say(f"using the Vulkan backend ({_vendor})" if not want_vulkan
             else "Vulkan backend forced (--vulkan)")
        # Vulkan is llama.cpp's universal AMD/Intel path: works on every card
        # with a standard graphics driver, no ROCm/oneAPI install needed (no
        # official prebuilt ROCm wheels exist; a ROCm pack can be added to the
        # gpu-packs workflow later if a card would benefit).
        if not _vulkan_loader_present():
            return _fail(
                "the system Vulkan loader is missing. Install your GPU vendor's "
                "driver (Windows) or the distro package (e.g. Debian/Ubuntu: "
                "libvulkan1, Fedora: vulkan-loader) and retry. CPU keeps working."
            )
        found = _pick_vulkan_wheel(prefer_cuda=False)
        if not found:
            return _fail(
                "no Vulkan wheel available for this python/platform in the "
                "gpu-packs release (and direct download fallbacks missed too) — "
                "check network access to github.com, re-run the gpu-packs "
                "workflow in ELI_v2.0, or stay on CPU. CPU inference keeps working."
            )
        version, url = found
        backend = pack_backend_from_url(url)
        if backend != "vulkan":
            return _fail(
                f"internal error: expected a vulkan- wheel for {_vendor}, "
                f"got {backend} from {url.rsplit('/', 1)[-1]!r}"
            )
    else:
        return _fail(
            f"no supported GPU detected on this {sys.platform} — no NVIDIA, AMD, or "
            "discrete Intel Arc GPU found. Apple GPUs are already handled by the "
            "macOS (Metal) build. If you have a GPU the driver isn't exposing (or an "
            "Intel iGPU), force the Vulkan pack with:  ELI --install-gpu-pack --vulkan. "
            "CPU inference keeps working either way."
        )

    prefer_cuda = nvidia_present and not want_vulkan
    bundled = _pick_bundled_wheel(prefer_cuda=prefer_cuda)
    if bundled:
        bk, bver, bpath = bundled
        if want_vulkan and bk == "cuda":
            alt = _pick_bundled_wheel(prefer_cuda=False)
            if alt:
                bk, bver, bpath = alt
        elif prefer_cuda and bk == "vulkan":
            alt = _pick_bundled_wheel(prefer_cuda=True)
            if alt and alt[0] == "cuda":
                bk, bver, bpath = alt
        _say(f"using bundled GPU pack {bpath.name} ({bk})")
        return _install_from_local_wheel(
            bpath, bk, bver, force=force, cuda_idx=_normalize_cuda_idx(backend),
        )

    _say(f"downloading llama-cpp-python {version} ({backend}, {_platform_tag()}) — several hundred MB…")
    with tempfile.TemporaryDirectory() as td:
        whl = Path(td) / "pack.whl"
        try:
            _download(url, whl)
        except Exception as exc:
            return _fail(f"download failed: {exc}")

        staging = Path(td) / "unpacked"
        try:
            with zipfile.ZipFile(whl) as z:
                z.extractall(staging)
        except Exception as exc:
            return _fail(f"wheel unpack failed: {exc}")

        pack_backend = backend if backend in ("cuda", "vulkan") else pack_backend_from_url(url)
        return _activate_staged_gpu_pack(
            staging,
            dest=dest,
            backend=pack_backend,
            version=version,
            source=url,
            cuda_idx=_normalize_cuda_idx(backend),
        )


def _download(url: str, path: Path) -> None:
    with urllib.request.urlopen(url, timeout=60) as r, open(path, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while chunk := r.read(1 << 20):
            f.write(chunk)
            done += len(chunk)
            if total:
                print(f"\r[gpu-pack] {done // (1 << 20)} / {total // (1 << 20)} MB", end="", flush=True)
        print(flush=True)


def _vendor_cuda_runtime(libdir: Path, tmp: Path, cuda_idx: str = "cu124") -> None:
    """Fetch cudart + cublas from NVIDIA's official PyPI wheels into libdir.

    Prefer the CUDA minor the llama wheel was built against (cu126 → 12.6.x),
    then newer 12.x lines — a too-old cudart against a newer libggml-cuda.so is
    what made verify delete a pack after ggml_cuda_init already found the GPU.
    """
    want_ext = ".dll" if sys.platform == "win32" else ".so"
    cuda_idx = _normalize_cuda_idx(cuda_idx)
    pin_major = int(cuda_idx[2:4])
    pin_minor = int(cuda_idx[4:] or "0")
    minor_candidates = [f"{pin_major}.{m}" for m in range(pin_minor, pin_minor + 8)]

    def _pick(files):
        for f in files:
            n = f["filename"]
            if not n.endswith(".whl"):
                continue
            if sys.platform == "win32":
                if "win_amd64" in n:
                    return f
            elif "manylinux" in n and "x86_64" in n:
                return f
        return None

    for pkg in ("nvidia-cuda-runtime-cu12", "nvidia-cublas-cu12"):
        with urllib.request.urlopen(f"https://pypi.org/pypi/{pkg}/json", timeout=30) as r:
            meta = json.load(r)
        hit = None
        ver = None
        for minor in minor_candidates:
            versions = sorted(
                (v for v in meta["releases"] if v.startswith(minor + ".")),
                key=lambda v: tuple(int(x) for x in v.split(".")),
                reverse=True,
            )
            for candidate in versions:
                hit = _pick(meta["releases"][candidate])
                if hit:
                    ver = candidate
                    break
            if hit:
                break
        if not hit:
            # Last resort: newest published wheel for the package.
            ver = meta["info"]["version"]
            hit = _pick(meta["releases"].get(ver) or [])
        if not hit:
            raise RuntimeError(f"no x86_64 wheel for {pkg} (CUDA {minor_candidates[0]}+)")
        _say(f"fetching CUDA runtime component {pkg} {ver}…")
        whl = tmp / f"{pkg}.whl"
        _download(hit["url"], whl)
        with zipfile.ZipFile(whl) as z:
            for name in z.namelist():
                base = name.rsplit("/", 1)[-1]
                if want_ext in base and ("/bin/" in name or "/lib/" in name):
                    with z.open(name) as src, open(libdir / base, "wb") as dst:
                        shutil.copyfileobj(src, dst)


def _shared_memory_gpu() -> bool:
    """True for iGPU / APU / Apple unified memory (shared RAM, not discrete VRAM)."""
    try:
        from eli.core.hardware_profile import detect_hardware
        hw = detect_hardware()
        return bool(getattr(hw, "gpu_integrated", False))
    except Exception:
        return False


def _intel_integrated_gpu() -> bool:
    return _shared_memory_gpu()


def _verify(dest: Path, *, require_offload: bool = True) -> tuple[bool, str]:
    """Import llama_cpp from the pack in a throwaway ELI subprocess."""
    import os
    libdir = dest / "llama_cpp" / "lib"
    try:
        _assert_cuda_runtime_complete(libdir)
    except RuntimeError as exc:
        return False, str(exc)
    # Self-contained probe (no eli_gpu_pack import — must also work when the
    # verifier runs outside the frozen bundle, e.g. in tests).
    # The probe must do BOTH things the old one skipped:
    #   * preload the VULKAN loader, not only the CUDA libs -- a vulkan pack
    #     needs libvulkan.so.1, which the pack does not ship because it belongs
    #     to the GPU driver;
    #   * assert the pack can actually OFFLOAD, not merely that it imports.
    # A pack that imports but reports llama_supports_gpu_offload() == False is
    # worse than no pack: it shadows the bundled runtime with something slower
    # AND older. That combination shipped, and reported
    # "llama.cpp GPU offload support: False" on a machine with a working GPU.
    probe = (
        "import sys, os, ctypes, ctypes.util\n"
        "from pathlib import Path\n"
        f"dest = Path({str(dest)!r})\n"
        "sys.path.insert(0, str(dest))\n"
        "lib = dest / 'llama_cpp' / 'lib'\n"
        "if lib.is_dir():\n"
        "    if sys.platform == 'win32':\n"
        "        os.add_dll_directory(str(lib))\n"
        "        pats = ('cudart64*.dll', 'cublasLt64*.dll', 'cublas64*.dll', 'vulkan-1.dll')\n"
        "    else:\n"
        "        pats = ('libcudart.so*', 'libcublasLt.so*', 'libcublas.so*')\n"
        "    for p in pats:\n"
        "        for f in sorted(lib.glob(p)):\n"
        "            try: ctypes.CDLL(str(f))\n"
        "            except Exception: pass\n"
        "    if sys.platform != 'win32' and any(lib.glob('libggml-vulkan.so*')):\n"
        "        cands = [c for c in [ctypes.util.find_library('vulkan')] if c]\n"
        "        cands += ['/usr/lib/x86_64-linux-gnu/libvulkan.so.1',\n"
        "                  '/lib/x86_64-linux-gnu/libvulkan.so.1',\n"
        "                  '/usr/lib64/libvulkan.so.1', 'libvulkan.so.1']\n"
        "        _icds = []\n"
        "        for _icd_dir in ('/usr/share/vulkan/icd.d','/etc/vulkan/icd.d',\n"
        "                         '/usr/lib/x86_64-linux-gnu/GL/vulkan/icd.d'):\n"
        "            _d = Path(_icd_dir)\n"
        "            if _d.is_dir():\n"
        "                for _icd in sorted(_d.glob('*.json')):\n"
        "                    _icds.append(str(_icd))\n"
        "        if _icds and not os.environ.get('VK_ICD_FILENAMES'):\n"
        "            os.environ['VK_ICD_FILENAMES'] = ':'.join(_icds)\n"
        "        for c in cands:\n"
        "            try:\n"
        "                ctypes.CDLL(c, mode=ctypes.RTLD_GLOBAL); break\n"
        "            except Exception: pass\n"
        "    if sys.platform != 'win32':\n"
        "        for p in ('libggml-base.so*', 'libggml-cpu.so*',\n"
        "                  'libggml-vulkan.so*', 'libggml-cuda.so*',\n"
        "                  'libggml.so*'):\n"
        "            for f in sorted(lib.glob(p)):\n"
        "                try: ctypes.CDLL(str(f), mode=ctypes.RTLD_GLOBAL)\n"
        "                except Exception: pass\n"
        "import llama_cpp\n"
        "from llama_cpp import llama_cpp as _lc\n"
        "_lc.llama_backend_init()\n"
        "off = bool(llama_cpp.llama_supports_gpu_offload())\n"
        "print('gpu-pack-verify-offload', off)\n"
        f"if {require_offload!r} and not off:\n"
        "    print('gpu-pack-verify-no-offload'); raise SystemExit(2)\n"
        "print('gpu-pack-verify-ok', llama_cpp.__version__)\n"
    )
    env = os.environ.copy()
    if sys.platform != "win32" and libdir.is_dir():
        # AppImage / frozen runs pin LD_LIBRARY_PATH at the bundle; without the
        # pack libdir first, the probe can bind the wrong cudart and die after
        # ggml_cuda_init already printed the GPU list.
        prev = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = str(libdir) + (os.pathsep + prev if prev else "")
    try:
        out = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True, text=True, timeout=180,
            env=env,
        )
    except Exception as exc:
        return False, str(exc)
    stdout = (out.stdout or "").strip()
    stderr = (out.stderr or "").strip()
    detail = "\n".join(x for x in (stdout, stderr) if x) or "no output"
    if out.returncode == 0 and "gpu-pack-verify-ok" in stdout:
        return True, stdout
    # Exit 2 = llama_supports_gpu_offload() False. When ggml_cuda_init already
    # enumerated devices, that flag is a known false negative (AppImage + some
    # driver/cudart pairs). Keep the pack — deleting it after a successful CUDA
    # device probe is what produced the 2.4.26 "Loader said: found 1 CUDA
    # devices" failure dialog on a working RTX 2060.
    cuda_found = bool(re.search(r"ggml_cuda_init:\s*found\s+[1-9]", stderr))
    if require_offload and cuda_found and (
        out.returncode == 2 or "gpu-pack-verify-no-offload" in stdout
    ):
        return True, "gpu-pack-verify-ok (cuda devices enumerated)\n" + detail[-700:]
    return False, detail[-800:]


def preload_native_libs(pack_dir: str | Path) -> None:
    """Preload the pack's CUDA runtime libs so dependency resolution succeeds
    regardless of RPATH. Called by the frozen runtime hook on activation and
    by the install-time verifier."""
    import ctypes
    lib = Path(pack_dir) / "llama_cpp" / "lib"
    if not lib.is_dir():
        return
    if sys.platform == "win32":
        try:
            import os
            os.add_dll_directory(str(lib))
        except Exception:
            pass
        patterns = ("cudart64*.dll", "cublasLt64*.dll", "cublas64*.dll", "vulkan-1.dll")
    else:
        patterns = ("libcudart.so*", "libcublasLt.so*", "libcublas.so*")
    for pat in patterns:
        for f in sorted(lib.glob(pat)):
            try:
                ctypes.CDLL(str(f))
            except Exception:
                pass

    # A VULKAN pack needs the system Vulkan LOADER (libvulkan.so.1), which the
    # pack does not ship -- it belongs to the GPU driver. Only the CUDA libs
    # were preloaded here, so inside the frozen app, whose LD_LIBRARY_PATH
    # points at its own bundled libraries, libggml-vulkan.so could not bind the
    # loader; ggml then dropped the Vulkan backend and
    # llama_supports_gpu_offload() returned False. Live symptom, on a machine
    # whose GPU worked minutes earlier outside the bundle:
    #     llama.cpp GPU offload support: False
    #     GPU offload unavailable at runtime -> forcing CPU-safe tuning
    # Loading the loader by absolute path, before llama_cpp is imported, is
    # what makes the Vulkan backend resolvable from inside the bundle.
    if sys.platform != "win32" and any(lib.glob("libggml-vulkan.so*")):
        import ctypes.util
        import os
        candidates = []
        found = ctypes.util.find_library("vulkan")
        if found:
            candidates.append(found)
        candidates += [
            "/usr/lib/x86_64-linux-gnu/libvulkan.so.1",
            "/lib/x86_64-linux-gnu/libvulkan.so.1",
            "/usr/lib64/libvulkan.so.1",
            "/usr/lib/libvulkan.so.1",
            "/usr/lib/i386-linux-gnu/libvulkan.so.1",
            "libvulkan.so.1",
        ]
        # Intel/AMD/Mesa ICD paths — without these, llama_supports_gpu_offload()
        # can report False inside AppImage even when Vulkan works outside it.
        _icd_files: list[str] = []
        for _icd_dir in (
            Path("/usr/share/vulkan/icd.d"),
            Path("/etc/vulkan/icd.d"),
            Path("/usr/lib/x86_64-linux-gnu/GL/vulkan/icd.d"),
        ):
            if not _icd_dir.is_dir():
                continue
            for _icd in sorted(_icd_dir.glob("*.json")):
                _icd_files.append(str(_icd))
        if _icd_files and not os.environ.get("VK_ICD_FILENAMES"):
            os.environ["VK_ICD_FILENAMES"] = ":".join(_icd_files)
        for cand in candidates:
            try:
                ctypes.CDLL(cand, mode=getattr(ctypes, "RTLD_GLOBAL", 0))
                break
            except Exception:
                continue

    # Then the pack's own libraries, in dependency order.
    #
    # These MUST all be preloaded, not just the backends. The frozen app keeps
    # its own CPU-only libggml.so.0 / libggml-base.so.0 / libllama.so.0 at the
    # top of _internal, which is on LD_LIBRARY_PATH. The pack's libllama.so
    # records "NEEDED libggml.so.0", so if the pack's own libggml.so has not
    # already been loaded under that SONAME, the dynamic linker satisfies it
    # from the bundle instead -- the pack's Vulkan/CUDA backend never registers
    # and llama_supports_gpu_offload() reports False on a working GPU. Loading
    # each of the pack's libraries by absolute path with RTLD_GLOBAL registers
    # it under its SONAME first, so every later NEEDED resolves inside the pack.
    # Order matters: dependencies before dependents.
    #
    # libllama.so and libmtmd.so are deliberately NOT in this list. llama_cpp
    # loads libllama itself by absolute path, so preloading it RTLD_GLOBAL as
    # well produced "double free or corruption (!prev)" at interpreter exit --
    # offload reported True and then the process died on the way out. Only the
    # ggml libraries, which nothing else loads by absolute path, belong here.
    if sys.platform != "win32":
        for pat in ("libggml-base.so*", "libggml-cpu.so*",
                    "libggml-vulkan.so*", "libggml-cuda.so*",
                    "libggml.so*"):
            for f in sorted(lib.glob(pat)):
                try:
                    ctypes.CDLL(str(f), mode=getattr(ctypes, "RTLD_GLOBAL", 0))
                except Exception:
                    pass


def activate_gpu_pack_runtime(dest: str | Path, *, verify: bool = True) -> bool:
    """Make an installed GPU pack the active llama_cpp in THIS process.

    Install-time verification runs in a throwaway subprocess; the live GUI
    process may already have imported the bundled CPU runtime, or may need
    ``llama_backend_init()`` before ``llama_supports_gpu_offload()`` is true
    (common for Vulkan on Intel iGPU inside AppImage/portable builds).
    """
    import sys

    pack = Path(dest)
    if not (pack / "llama_cpp").is_dir():
        return False
    if not (pack / ".gpu_pack_ok").is_file() and not gpu_pack_operational(pack):
        return False

    pack_s = str(pack.resolve())
    for q in list(sys.path):
        if "runtime/gpu" in str(q).replace("\\", "/") and q != pack_s:
            try:
                sys.path.remove(q)
            except ValueError:
                continue
    if pack_s not in sys.path:
        sys.path.insert(0, pack_s)

    preload_native_libs(pack)

    for name in [k for k in list(sys.modules)
                 if k == "llama_cpp" or k.startswith("llama_cpp.")]:
        sys.modules.pop(name, None)

    try:
        import llama_cpp
        from llama_cpp import llama_cpp as _lc

        _lc.llama_backend_init()
        if verify and not bool(llama_cpp.llama_supports_gpu_offload()):
            if _relax_offload_verify(pack):
                # Pack imports; install already accepted this iGPU/Vulkan case.
                return True
            return False
        return True
    except Exception:
        return False


def deactivate_gpu_pack_runtime(dest: str | Path | None = None) -> None:
    """Drop the GPU pack from sys.path and unload llama_cpp (bundled CPU resumes)."""
    import sys

    pack_s = str(Path(dest).resolve()) if dest else ""
    for q in list(sys.path):
        if "runtime/gpu" in str(q).replace("\\", "/") or (pack_s and q == pack_s):
            try:
                sys.path.remove(q)
            except ValueError:
                continue
    for name in [k for k in list(sys.modules)
                 if k == "llama_cpp" or k.startswith("llama_cpp.")]:
        sys.modules.pop(name, None)
