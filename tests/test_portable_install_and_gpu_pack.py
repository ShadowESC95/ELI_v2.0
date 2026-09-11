"""Portable installer must define helpers before first use."""
from __future__ import annotations

from pathlib import Path


def test_install_sh_defines_safe_pipeline_before_use():
    src = Path("install.sh").read_text(encoding="utf-8")
    defn = src.find("_safe_pipeline() {")
    use = src.find('_CPUS="$(_safe_pipeline')
    assert defn >= 0, "_safe_pipeline definition missing"
    assert use >= 0, "_safe_pipeline use missing"
    assert defn < use, (
        "_safe_pipeline is used before it is defined — portable tar.gz setup "
        "dies at 'Scanning hardware' with command not found"
    )


def test_install_sh_drm_pci_expands_in_outer_shell():
    """Intel/Qualcomm DRM vendor walk must expand $_drm in the outer shell."""
    src = Path("install.sh").read_text(encoding="utf-8")
    assert 'readlink -f "$(dirname "$_drm")"' in src
    # Nested single-quoted bash -c left $_drm unset → blank Intel/Qualcomm name.
    assert 'bash -c \'readlink -f "$(dirname "$_drm")"' not in src


def test_install_sh_pipeline_helpers_never_abort():
    """Inner pipeline failures must not trip set -e mid-function."""
    src = Path("install.sh").read_text(encoding="utf-8")
    assert '"$@" || true' in src
    assert "grep -iE \"intel\"" in src or "grep -iE 'intel'" in src
    assert "fsspec==2026.2.0" in Path("requirements.txt").read_text(encoding="utf-8")
    setup = Path("scripts/eli_setup.sh").read_text(encoding="utf-8")
    assert "|| true" in setup
    assert "eli_setup.sh" in Path("scripts/install_eli.sh").read_text(encoding="utf-8")
    assert "Redirecting" in Path("scripts/install_eli.sh").read_text(encoding="utf-8")
    one = Path("scripts/eli_one_click_setup.sh").read_text(encoding="utf-8")
    assert "eli_setup.sh" in one
    assert "eli.setup.hardware_policy" in setup
    assert "HAS_INTEL_ARC" in src
    assert 'HAS_INTEL_ARC" -eq 1 ] || [ "$HAS_INTEL_IGPU" -eq 1 ]' in src


def test_gpu_pack_activate_relaxes_vulkan_igpu():
    import importlib.util
    import sys
    from pathlib import Path as P

    path = P("packaging/pyinstaller/eli_gpu_pack.py").resolve()
    spec = importlib.util.spec_from_file_location("eli_gpu_pack", path)
    gp = importlib.util.module_from_spec(spec)
    sys.modules["eli_gpu_pack"] = gp
    assert spec.loader is not None
    spec.loader.exec_module(gp)
    assert hasattr(gp, "_relax_offload_verify")
    assert gp._relax_offload_verify(P("/tmp/no-such-eli-gpu-pack")) is False
