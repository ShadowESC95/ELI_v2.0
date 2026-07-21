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
    smi = shutil.which("nvidia-smi")
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
    smi = shutil.which("nvidia-smi")
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


def _has_nvidia_gpu() -> bool:
    """True if an NVIDIA GPU is present, INDEPENDENT of parsing a CUDA version.

    ``_driver_cuda_version`` scrapes ``CUDA Version:`` out of the bare ``nvidia-smi``
    table, but that line can be absent/garbled on some setups (hybrid Intel+NVIDIA
    Optimus laptops, very new drivers) even though the GPU works fine and the same
    machine reads VRAM cleanly via ``nvidia-smi --query-gpu``. Failing to parse the
    version must NOT be mistaken for "no NVIDIA GPU" — that regression forced a
    working 1660 Ti onto CPU. Probe presence with the most robust signals, on every
    OS: the driver's device list (``nvidia-smi -L``), the proven ``--query-gpu``
    call, the PCI vendor id in sysfs (Linux), then the driver DLLs (Windows)."""
    smi = shutil.which("nvidia-smi")
    if smi:
        for args in ([smi, "-L"], [smi, "--query-gpu=name", "--format=csv,noheader"]):
            try:
                out = subprocess.run(args, capture_output=True, text=True, timeout=20)
                if out.returncode == 0 and (out.stdout or "").strip():
                    return True
            except Exception:
                continue
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


def _has_intel_arc_gpu() -> bool:
    """True for a DISCRETE Intel Arc GPU (NOT an integrated iGPU — Vulkan offload to
    an iGPU rarely beats CPU, so those stay on CPU unless the user forces --vulkan).

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


def _pick_vulkan_wheel() -> tuple[str, str] | None:
    """Return (version, url) of the CI-built Vulkan wheel for this python/platform."""
    try:
        with urllib.request.urlopen(VULKAN_RELEASE_API, timeout=30) as r:
            assets = json.load(r).get("assets", [])
    except Exception as exc:
        _say(f"gpu-packs release unavailable ({exc})")
        return None
    py = f"cp{sys.version_info.major}{sys.version_info.minor}"
    plat = _platform_tag()
    pat = re.compile(r"vulkan-llama_cpp_python-(\d+(?:\.\d+)+)-%s-%s-.*%s\.whl" % (py, py, plat))
    for a in assets:
        m = pat.fullmatch(a.get("name", ""))
        if m:
            return m.group(1), a["browser_download_url"]
    return None


def install(argv: list[str] | None = None) -> int:
    """Install the GPU pack, recording any unexpected crash to the install log.

    Callers run this on a worker thread and only see the return code, so an
    escaping exception would otherwise vanish entirely.
    """
    try:
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
        _say(f"GPU pack already installed at {dest} (use --force to reinstall)")
        return 0

    # Vendor presence — checked the SAME robust, presence-based way for every
    # vendor on every OS. An NVIDIA GPU counts as present if we parsed its CUDA
    # version OR simply see the card: the version parse is a refinement for picking
    # the exact wheel, not the gate for "is this NVIDIA". Conflating the two forced
    # a working 1660 Ti (whose bare nvidia-smi lacked a parseable CUDA line) onto CPU.
    drv = None if want_vulkan else _driver_cuda_version()
    nvidia_present = (not want_vulkan) and (drv is not None or _has_nvidia_gpu())
    amd_present = (not want_vulkan) and _has_amd_gpu()
    intel_arc_present = (not want_vulkan) and _has_intel_arc_gpu()
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
            return _fail("no CUDA wheel found for this python/platform in the llama-cpp-python index")
        backend, version, url = picked
    elif want_vulkan or amd_present or intel_arc_present:
        # AMD / Intel Arc (or forced): CI-built Vulkan backend. The GPU
        # driver already ships the Vulkan loader the wheel needs.
        _vendor = "AMD" if amd_present else ("Intel Arc" if intel_arc_present else "GPU")
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
        found = _pick_vulkan_wheel()
        if not found:
            return _fail(
                "no Vulkan wheel available for this python/platform in the "
                "gpu-packs release — run the gpu-packs workflow in ELI_v2.0, "
                "or use a source install. CPU inference keeps working."
            )
        backend, (version, url) = "vulkan", found
    else:
        return _fail(
            f"no supported GPU detected on this {sys.platform} — no NVIDIA, AMD, or "
            "discrete Intel Arc GPU found. Apple GPUs are already handled by the "
            "macOS (Metal) build. If you have a GPU the driver isn't exposing (or an "
            "Intel iGPU), force the Vulkan pack with:  ELI --install-gpu-pack --vulkan. "
            "CPU inference keeps working either way."
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

        if not (staging / "llama_cpp").is_dir():
            return _fail("wheel did not contain a llama_cpp package")

        if backend != "vulkan":
            # The CUDA wheels do NOT vendor the CUDA runtime (cudart/cublas):
            # NVIDIA ships those separately, CI runners have them system-wide,
            # end-user machines usually don't — v2.1.4 crashed at boot on
            # exactly this. Pull NVIDIA's official PyPI redistributables and
            # drop their libraries next to llama.dll (the llama loader adds
            # that directory to the DLL search path; rthook preloads them too).
            libdir = staging / "llama_cpp" / "lib"
            try:
                _vendor_cuda_runtime(libdir, Path(td), backend)
            except Exception as exc:
                return _fail(f"could not fetch the CUDA runtime libraries: {exc}")

        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        dest.mkdir(parents=True, exist_ok=True)
        for item in staging.iterdir():
            shutil.move(str(item), str(dest / item.name))

    # VERIFY before activation — a pack that cannot load must never be able
    # to brick the app (activation requires the .gpu_pack_ok marker).
    _say("verifying the GPU pack loads on this machine…")
    ok, detail = _verify(dest)
    if not ok:
        shutil.rmtree(dest, ignore_errors=True)
        return _fail(
            "the downloaded GPU build failed to load on this machine — removed it; "
            f"ELI stays on CPU (fully functional).\nLoader said: {detail}"
        )

    (dest / ".gpu_pack.json").write_text(
        json.dumps({"version": version, "backend": backend, "url": url}, indent=2),
        encoding="utf-8",
    )
    (dest / ".gpu_pack_ok").write_text("verified", encoding="utf-8")
    _say(f"installed and verified at {dest}")
    _say("done — the model loader will now offload layers to the GPU.")
    return 0


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

    Version pinned to the same CUDA minor the llama wheel was built against
    (cu124 → 12.4.x); x86_64 wheels only (PyPI also hosts aarch64)."""
    want_ext = ".dll" if sys.platform == "win32" else ".so"
    minor = f"{cuda_idx[2:4]}.{cuda_idx[4:]}"  # "cu124" -> "12.4"

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
        versions = sorted(
            (v for v in meta["releases"] if v.startswith(minor + ".")),
            key=lambda v: tuple(int(x) for x in v.split(".")),
            reverse=True,
        ) or [meta["info"]["version"]]
        hit = None
        for ver in versions:
            hit = _pick(meta["releases"][ver])
            if hit:
                break
        if not hit:
            raise RuntimeError(f"no x86_64 wheel for {pkg} (CUDA {minor})")
        _say(f"fetching CUDA runtime component {pkg} {ver}…")
        whl = tmp / f"{pkg}.whl"
        _download(hit["url"], whl)
        with zipfile.ZipFile(whl) as z:
            for name in z.namelist():
                base = name.rsplit("/", 1)[-1]
                if want_ext in base and ("/bin/" in name or "/lib/" in name):
                    with z.open(name) as src, open(libdir / base, "wb") as dst:
                        shutil.copyfileobj(src, dst)


def _verify(dest: Path) -> tuple[bool, str]:
    """Import llama_cpp from the pack in a throwaway ELI subprocess."""
    # Self-contained probe (no eli_gpu_pack import — must also work when the
    # verifier runs outside the frozen bundle, e.g. in tests).
    probe = (
        "import sys, os, ctypes\n"
        "from pathlib import Path\n"
        f"dest = Path({str(dest)!r})\n"
        "sys.path.insert(0, str(dest))\n"
        "lib = dest / 'llama_cpp' / 'lib'\n"
        "if lib.is_dir():\n"
        "    if sys.platform == 'win32':\n"
        "        os.add_dll_directory(str(lib))\n"
        "        pats = ('cudart64*.dll', 'cublasLt64*.dll', 'cublas64*.dll')\n"
        "    else:\n"
        "        pats = ('libcudart.so*', 'libcublasLt.so*', 'libcublas.so*')\n"
        "    for p in pats:\n"
        "        for f in sorted(lib.glob(p)):\n"
        "            try: ctypes.CDLL(str(f))\n"
        "            except Exception: pass\n"
        "import llama_cpp\n"
        "print('gpu-pack-verify-ok', llama_cpp.__version__)\n"
    )
    try:
        out = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True, text=True, timeout=180,
        )
    except Exception as exc:
        return False, str(exc)
    if out.returncode == 0 and "gpu-pack-verify-ok" in (out.stdout or ""):
        return True, out.stdout.strip()
    return False, (out.stderr or out.stdout or "no output").strip()[-800:]


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
        patterns = ("cudart64*.dll", "cublasLt64*.dll", "cublas64*.dll")
    else:
        patterns = ("libcudart.so*", "libcublasLt.so*", "libcublas.so*")
    for pat in patterns:
        for f in sorted(lib.glob(pat)):
            try:
                ctypes.CDLL(str(f))
            except Exception:
                pass
