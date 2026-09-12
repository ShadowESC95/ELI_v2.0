"""Install-time accelerator inventory and CPU-only recommendation.

Single source of truth for the GUI wizard, ``platform_profile``, and shell
bootstraps. Detection is best-effort and never raises — installers must keep
working on locked-down / headless hosts.

Policy (aligned with ``install.sh --yes``):
  * Explicit ``ELI_INSTALL_CPU_ONLY`` / ``ELI_FORCE_GPU`` env wins.
  * Apple Metal, NVIDIA, AMD discrete, Intel Arc → GPU build path.
  * Intel integrated (Iris Xe / UHD), ≤8 GB RAM, or no discrete GPU → CPU.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import platform
import re
import shutil
import subprocess
import sys
from typing import Optional


def _run(cmd: list[str], timeout: float = 4.0) -> str:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return (proc.stdout or "") + (proc.stderr or "")
    except Exception:
        return ""


def _env_truthy(name: str) -> Optional[bool]:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return None
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return None


@dataclass(frozen=True)
class AcceleratorInventory:
    """Observed compute topology for install planning."""

    nvidia: bool = False
    amd: bool = False
    intel_igpu: bool = False
    intel_arc: bool = False
    qualcomm: bool = False
    apple_metal: bool = False
    ram_gb: Optional[int] = None
    notes: tuple[str, ...] = ()

    @property
    def has_discrete_gpu(self) -> bool:
        return bool(self.nvidia or self.amd or self.intel_arc)

    @property
    def label(self) -> str:
        if self.apple_metal:
            return "Apple Metal"
        if self.nvidia:
            return "NVIDIA CUDA"
        if self.amd:
            return "AMD ROCm/Vulkan"
        if self.intel_arc:
            return "Intel Arc Vulkan"
        if self.intel_igpu:
            return "Intel integrated"
        if self.qualcomm:
            return "Qualcomm Adreno"
        return "CPU"


def _ram_gb() -> Optional[int]:
    if sys.platform == "win32":
        out = _run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory",
            ]
        )
        try:
            bytes_total = int(re.sub(r"\D", "", out.splitlines()[0]) or "0")
            if bytes_total > 0:
                return max(1, bytes_total // (1024**3))
        except Exception:
            return None
        return None
    if sys.platform == "darwin":
        out = _run(["sysctl", "-n", "hw.memsize"])
        try:
            return max(1, int(out.strip()) // (1024**3))
        except Exception:
            return None
    out = _run(["free", "-g"])
    for line in out.splitlines():
        if line.lower().startswith("mem:"):
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                return int(parts[1])
    return None


def _lspci_display_lines() -> list[str]:
    if not shutil.which("lspci"):
        return []
    out = _run(["lspci"])
    return [
        ln for ln in out.splitlines()
        if re.search(r"(?i)vga|3d|display", ln)
    ]


_NVIDIA_SMI_NOISE = re.compile(
    r"(?i)failed|couldn.?t\s+communicate|nvidia-smi|driver\s+not|"
    r"no\s+devices\s+were\s+found|insufficient\s+permissions|"
    r"not\s+supported|has\s+failed"
)


def _nvidia_smi_gpu_names() -> list[str]:
    """Return usable GPU names from nvidia-smi — never treat error text as a GPU.

    Broken driver installs still print to stdout (e.g. ``NVIDIA-SMI has failed
    because it couldn't communicate with the NVIDIA driver``). Counting those
    lines as GPUs incorrectly selects the CUDA install path on CPU laptops.
    """
    if not shutil.which("nvidia-smi"):
        return []
    smi = _run(
        ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
        timeout=6.0,
    )
    names: list[str] = []
    for ln in smi.splitlines():
        name = ln.strip()
        if not name or _NVIDIA_SMI_NOISE.search(name):
            continue
        # Real CSV names are short product strings, not multi-sentence errors.
        if len(name) > 120 or "\t" in name:
            continue
        names.append(name)
    return names


def detect_accelerators() -> AcceleratorInventory:
    notes: list[str] = []
    nvidia = amd = intel_igpu = intel_arc = qualcomm = False
    apple_metal = sys.platform == "darwin"
    smi_names = _nvidia_smi_gpu_names()
    if smi_names:
        nvidia = True
    elif shutil.which("nvidia-smi"):
        notes.append("nvidia-smi present but driver unusable — not selecting CUDA")

    if shutil.which("rocm-smi"):
        amd = True

    if sys.platform == "win32":
        out = _run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name",
            ]
        )
        for ln in out.splitlines():
            name = ln.strip()
            if not name:
                continue
            low = name.lower()
            if "nvidia" in low:
                # Prefer live nvidia-smi; WMI alone is OK when smi is absent.
                if smi_names or not shutil.which("nvidia-smi"):
                    nvidia = True
            if re.search(r"(?:\bamd\b|\bati\b|\bradeon\b)", low):
                amd = True
            elif re.search(r"arc\s*(a|pro|b)?\d", low) or "intel arc" in low:
                intel_arc = True
            elif "intel" in low:
                intel_igpu = True
            elif re.search(r"qualcomm|adreno|snapdragon", low):
                qualcomm = True
    else:
        for ln in _lspci_display_lines():
            low = ln.lower()
            # Do NOT set nvidia from lspci alone — a powered-off / broken
            # discrete NVIDIA on a laptop still appears in lspci while
            # nvidia-smi fails. CUDA wheels then SIGILL / miss libcudart.
            if "nvidia" in low:
                if not smi_names:
                    notes.append("PCI NVIDIA present but driver unusable — ignoring for install")
                continue
            if re.search(r"(?:\bamd\b|\bati\b|\bradeon\b)", low):
                amd = True
            elif re.search(r"arc\s*(a|pro|b)?\d", low):
                intel_arc = True
            elif "intel" in low:
                intel_igpu = True
            elif re.search(r"qualcomm|adreno|snapdragon", low):
                qualcomm = True

    # Arc is discrete; do not also treat as iGPU.
    if intel_arc:
        intel_igpu = False

    ram = _ram_gb()
    if ram is not None and ram <= 8:
        notes.append(f"{ram} GB RAM — prefer CPU llama-cpp on non-discrete GPUs")
    if intel_igpu:
        notes.append("Intel integrated GPU — portable path prefers CPU wheels")
    if intel_arc:
        notes.append("Intel Arc — Vulkan llama-cpp path")

    return AcceleratorInventory(
        nvidia=nvidia,
        amd=amd,
        intel_igpu=intel_igpu,
        intel_arc=intel_arc,
        qualcomm=qualcomm,
        apple_metal=apple_metal,
        ram_gb=ram,
        notes=tuple(notes),
    )


def recommend_cpu_only(
    inventory: Optional[AcceleratorInventory] = None,
    *,
    respect_env: bool = True,
) -> bool:
    """Return True when the install should pass ``--cpu-only`` / ``-CpuOnly``."""
    if respect_env:
        forced = _env_truthy("ELI_INSTALL_CPU_ONLY")
        if forced is not None:
            return forced
        if _env_truthy("ELI_FORCE_GPU") is True:
            return False

    inv = inventory or detect_accelerators()
    # Working discrete accelerators → GPU path. Dead NVIDIA is already False
    # (nvidia-smi error text / lspci-only must not set nvidia=True).
    if inv.apple_metal or inv.nvidia or inv.amd or inv.intel_arc:
        return False
    if inv.intel_igpu:
        return True
    if inv.ram_gb is not None and inv.ram_gb <= 8:
        return True
    # No discrete accelerator → CPU wheels (Qualcomm Vulkan is experimental;
    # install.sh may still attempt Vulkan when not forced CPU-only).
    if inv.qualcomm and (inv.ram_gb is None or inv.ram_gb > 8):
        return False
    return True


def apply_cpu_only_env(inventory: Optional[AcceleratorInventory] = None) -> bool:
    """Set ``ELI_INSTALL_CPU_ONLY`` from policy and return the chosen value."""
    decision = recommend_cpu_only(inventory)
    os.environ["ELI_INSTALL_CPU_ONLY"] = "1" if decision else "0"
    return decision


def summarize_for_ui(inventory: Optional[AcceleratorInventory] = None) -> str:
    inv = inventory or detect_accelerators()
    cpu = recommend_cpu_only(inv)
    bits = [
        f"Accelerator: {inv.label}",
        f"Install path: {'CPU-only' if cpu else 'GPU-aware'}",
    ]
    if inv.ram_gb is not None:
        bits.append(f"RAM: {inv.ram_gb} GB")
    bits.extend(inv.notes)
    return " · ".join(bits)


def main() -> int:
    """CLI for shell bootstraps: prints ``cpu`` or ``gpu`` on stdout."""
    inv = detect_accelerators()
    decision = recommend_cpu_only(inv)
    if "--json" in sys.argv:
        import json
        print(json.dumps({
            "cpu_only": decision,
            "label": inv.label,
            "ram_gb": inv.ram_gb,
            "nvidia": inv.nvidia,
            "amd": inv.amd,
            "intel_igpu": inv.intel_igpu,
            "intel_arc": inv.intel_arc,
            "qualcomm": inv.qualcomm,
            "apple_metal": inv.apple_metal,
            "notes": list(inv.notes),
        }))
    else:
        print("cpu" if decision else "gpu")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
