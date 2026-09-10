"""GPU pack in-process activation after install."""
import sys
from pathlib import Path

import pytest

PACK = Path("packaging/pyinstaller/eli_gpu_pack.py")


def test_activate_gpu_pack_runtime_helpers_exist():
    sys.path.insert(0, str(PACK.parent))
    import eli_gpu_pack

    assert hasattr(eli_gpu_pack, "activate_gpu_pack_runtime")
    assert hasattr(eli_gpu_pack, "deactivate_gpu_pack_runtime")


def test_deactivate_is_safe_without_pack(monkeypatch):
    sys.path.insert(0, str(PACK.parent))
    import eli_gpu_pack

    monkeypatch.setattr(sys, "path", [p for p in sys.path if "runtime/gpu" not in p])
    eli_gpu_pack.deactivate_gpu_pack_runtime()
