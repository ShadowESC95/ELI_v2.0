"""Reported: install.sh chose the GPU (CUDA) build plan on a machine whose
nvidia-smi was broken (NVML "Driver/library version mismatch" after a driver
update with no reboot), then failed partway through a from-source CUDA build
it should never have attempted. Root cause: nvidia-smi's SECOND output line on
that specific failure ("NVML library version: 595.91") matched none of the
keyword filters used to detect a broken driver, so it survived as a fake GPU
name and HAS_NVIDIA got set to 1 anyway.

These tests extract the real detection block out of install.sh (by line range,
not a copy) and execute it for real against a fake nvidia-smi, so a future
edit to the block itself is what's under test -- not a paraphrase of it.
"""
from __future__ import annotations

import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = ROOT / "install.sh"


def _extract_nvidia_block() -> str:
    lines = INSTALL_SH.read_text(encoding="utf-8").splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("if command -v nvidia-smi"))
    assert lines[start + 1].lstrip().startswith("# Broken drivers"), (
        "install.sh's nvidia-smi block moved or changed shape — update the "
        "line-range extraction in this test"
    )
    # Walk to the matching top-level `fi` (the block's own indentation is 4
    # spaces; the closing `fi` for the outer `if` is at column 0).
    end = next(i for i in range(start + 1, len(lines)) if lines[i] == "fi")
    return "\n".join(lines[start:end + 1])


def _run_block(tmp_path: Path, *, fake_nvidia_smi: str) -> subprocess.CompletedProcess:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    smi = bin_dir / "nvidia-smi"
    smi.write_text(fake_nvidia_smi, encoding="utf-8")
    smi.chmod(smi.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    harness = tmp_path / "harness.sh"
    harness.write_text(
        "set -euo pipefail\n"
        "ok() { echo \"OK: $*\"; }\n"
        "warn() { echo \"WARN: $*\"; }\n"
        "B=; GRN=; R=; D=\n"
        "HAS_NVIDIA=0\n"
        f"{_extract_nvidia_block()}\n"
        "echo \"HAS_NVIDIA=$HAS_NVIDIA\"\n",
        encoding="utf-8",
    )
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin"}
    return subprocess.run(
        ["bash", str(harness)], capture_output=True, text=True, timeout=15, env=env,
    )


def test_broken_nvml_driver_mismatch_does_not_select_gpu(tmp_path):
    """The exact field case: nvidia-smi exits nonzero and prints two lines,
    the second of which matches no keyword filter."""
    fake = (
        "#!/bin/sh\n"
        "echo 'Failed to initialize NVML: Driver/library version mismatch'\n"
        "echo 'NVML library version: 595.91'\n"
        "exit 18\n"
    )
    proc = _run_block(tmp_path, fake_nvidia_smi=fake)
    assert proc.returncode == 0, proc.stderr
    assert "HAS_NVIDIA=0" in proc.stdout, proc.stdout
    assert "driver unusable" in proc.stdout


def test_working_nvidia_smi_still_selects_gpu(tmp_path):
    """Must not regress the working case."""
    fake = (
        "#!/bin/sh\n"
        "if [ \"$4\" = \"memory.total\" ]; then echo 8192; "
        "else echo 'NVIDIA GeForce RTX 2060 SUPER'; fi\n"
    )
    proc = _run_block(tmp_path, fake_nvidia_smi=fake)
    assert proc.returncode == 0, proc.stderr
    assert "HAS_NVIDIA=1" in proc.stdout, proc.stdout
    assert "RTX 2060 SUPER" in proc.stdout


def test_classic_communication_failure_still_rejected(tmp_path):
    """The original (pre-existing) failure mode this block already guarded —
    must keep working."""
    fake = (
        "#!/bin/sh\n"
        "echo \"NVIDIA-SMI has failed because it couldn't communicate with the NVIDIA driver.\"\n"
        "exit 1\n"
    )
    proc = _run_block(tmp_path, fake_nvidia_smi=fake)
    assert proc.returncode == 0, proc.stderr
    assert "HAS_NVIDIA=0" in proc.stdout, proc.stdout


def test_native_cuda_arch_fallback_no_longer_trusts_native_detection():
    """CMAKE_CUDA_ARCHITECTURES=native re-probes the GPU through the same
    driver stack nvidia-smi just failed to reach — not a safe fallback."""
    text = INSTALL_SH.read_text(encoding="utf-8")
    assert '_ARCHS="native"' not in text, (
        "install.sh still falls back to CMAKE_CUDA_ARCHITECTURES=native when "
        "nvidia-smi's compute_cap query fails — that depends on the same "
        "driver stack nvidia-smi just failed to reach"
    )
    assert '_ARCHS="61;75;86;89"' in text, (
        "expected the same known-good architecture list the CI-built GPU "
        "pack uses (Pascal through Ada) as the safe fallback"
    )
