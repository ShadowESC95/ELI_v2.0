"""CPU compatibility for llama-cpp-python — parity with GPU probe/fallback policy.

Prebuilt CUDA (and many CPU) wheels ship ``libggml-cpu.so`` compiled for recent
x86_64 features (notably AVX-VNNI). ``import llama_cpp`` succeeds; the process
SIGILLs inside ``ggml_cpu_init()`` on older chips (e.g. Intel 8th-gen Core).

ELI must *measure* runtime init — the same way GPU offload is verified — and
fall back to a source build tuned for the host CPU when a wheel is incompatible.
"""
from __future__ import annotations

import platform
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Optional, Sequence, Tuple

from eli.utils.log import get_logger

log = get_logger(__name__)

# Kernels in current abetlen linux x86_64 wheels (0.3.30+) assume AVX-VNNI on
# the CPU backend even when GPU offload is enabled.
_PREBUILT_WHEEL_CPU_FLAGS: Sequence[str] = ("avx_vnni", "avx512vnni", "avx512_vnni")


def _linux_cpu_flags() -> frozenset[str]:
    try:
        txt = Path("/proc/cpuinfo").read_text(errors="replace")
    except OSError:
        return frozenset()
    flags: set[str] = set()
    for line in txt.splitlines():
        if line.lower().startswith("flags"):
            _, _, rest = line.partition(":")
            flags.update(rest.lower().split())
    return frozenset(flags)


def _windows_cpu_has_any(substrings: Iterable[str]) -> Optional[bool]:
    """Best-effort WMI probe; None when inconclusive."""
    if not sys.platform.startswith("win"):
        return None
    try:
        out = subprocess.check_output(
            ["wmic", "cpu", "get", "Caption,Manufacturer,Name", "/format:list"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=15,
        )
    except Exception:
        log.debug("llama_cpu_compat: wmic probe failed", exc_info=True)
        return None
    blob = out.lower()
    # No reliable VNNI bit via WMI — treat as unknown so smoke test decides.
    if any(s in blob for s in substrings):
        return True
    return None


def cpu_supports_prebuilt_llama_wheel() -> bool:
    """True when this host can safely run upstream prebuilt x86_64 llama-cpp wheels."""
    machine = (platform.machine() or "").lower()
    if machine not in ("x86_64", "amd64"):
        # ARM / other arches use different wheels or source builds.
        return False
    flags = _linux_cpu_flags()
    if flags:
        return any(f in flags for f in _PREBUILT_WHEEL_CPU_FLAGS)
    win = _windows_cpu_has_any(_PREBUILT_WHEEL_CPU_FLAGS)
    if win is not None:
        return win
    # Unknown host — try wheel, but caller must still smoke-test.
    return True


def safe_source_cmake_flags() -> str:
    """Portable CPU baseline for source builds (never -march=native)."""
    flags = _linux_cpu_flags()
    if flags:
        if "avx2" in flags:
            march = "x86-64-v3"
        elif "sse4_2" in flags:
            march = "x86-64-v2"
        else:
            march = "x86-64"
    else:
        # Conservative default when /proc/cpuinfo is unavailable.
        march = "x86-64-v2"
    return (
        f"-DGGML_NATIVE=OFF -DCMAKE_C_FLAGS=-march={march} "
        f"-DCMAKE_CXX_FLAGS=-march={march}"
    )


def runtime_smoke_test(*, timeout_s: float = 30.0) -> Tuple[bool, str]:
    """Return (ok, detail). Exercises llama_backend_init(), not merely import."""
    probe = (
        "from llama_cpp import llama_cpp as _lc\n"
        "_lc.llama_backend_init()\n"
        "print('llama-runtime-smoke-ok')\n"
    )
    try:
        out = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception as exc:
        return False, str(exc)
    if out.returncode == 0 and "llama-runtime-smoke-ok" in (out.stdout or ""):
        return True, "ok"
    detail = (out.stderr or out.stdout or "").strip()
    if out.returncode in (132, -4):
        return False, "illegal instruction (prebuilt wheel CPU backend incompatible)"
    return False, detail[-500:] if detail else f"exit {out.returncode}"


def _cli(argv: Optional[Sequence[str]] = None) -> int:
    args = list(argv or sys.argv[1:])
    cmd = args[0] if args else "help"
    if cmd == "trusted":
        print("yes" if cpu_supports_prebuilt_llama_wheel() else "no")
        return 0
    if cmd == "cmake-flags":
        print(safe_source_cmake_flags())
        return 0
    if cmd == "smoke":
        ok, why = runtime_smoke_test()
        if ok:
            print("ok")
            return 0
        print(why, file=sys.stderr)
        return 1
    print("usage: python -m eli.core.llama_cpu_compat {trusted|cmake-flags|smoke}")
    return 2


if __name__ == "__main__":
    raise SystemExit(_cli())
