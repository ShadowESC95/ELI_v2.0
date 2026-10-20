"""Dual/multi-GPU settings → env publish + tensor_split resolution, and the planner's split. Offline,
no GPU needed."""
import json
import os

import pytest

from eli.core import runtime_settings as rs
from eli.core.load_plan import balanced_counts


@pytest.fixture(autouse=True)
def _restore_env():
    # apply_env() mutates os.environ (ELI_GGUF_*). Snapshot + restore so these tests
    # never leak environment into later settings/stress tests (ordering isolation).
    snap = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(snap)


def _clear():
    for k in ("ELI_GGUF_TENSOR_SPLIT", "ELI_GGUF_MAIN_GPU", "ELI_GGUF_SPLIT_MODE"):
        os.environ.pop(k, None)


def test_single_gpu_publishes_no_split():
    _clear()
    rs.apply_env({"tensor_split": "", "main_gpu": 0, "split_mode": ""})
    assert os.environ.get("ELI_GGUF_TENSOR_SPLIT") is None


def test_explicit_setting_published():
    _clear()
    rs.apply_env({"tensor_split": "0.5,0.5", "main_gpu": 0, "split_mode": "layer"})
    assert os.environ["ELI_GGUF_TENSOR_SPLIT"] == "0.5,0.5"
    assert os.environ["ELI_GGUF_SPLIT_MODE"] == "layer"
    _clear()


def test_profile_file_resolves_enabled_split(tmp_path):
    prof = {"profiles": [
        {"name": "off", "enabled": False, "tensor_split": None},
        {"name": "dual", "enabled": True, "main_gpu": 0,
         "tensor_split": [0.5, 0.5], "split_mode": "layer"},
    ]}
    f = tmp_path / "gpu_profiles.json"
    f.write_text(json.dumps(prof))
    ts, mg, sm = rs._resolve_gpu_split(
        {"tensor_split": "", "main_gpu": 0, "split_mode": "", "gpu_profiles_file": str(f)})
    assert ts == "0.5,0.5" and mg == 0 and sm == "layer"


def test_layers_are_split_so_every_card_fills_the_same_share():
    """An 8 GB and a 24 GB card: three times the room takes about three times the layers, and one
    card takes everything when it is the only one usable."""
    units = [100.0] * 40
    small, big = balanced_counts(units, 40, room=[2000.0, 6000.0], usable=[True, True])
    assert small + big == 40 and 9 <= small <= 11
    assert balanced_counts(units, 40, room=[2000.0, 6000.0], usable=[False, True]) == [0, 40]
    assert balanced_counts(units, 40, room=[1000.0, 1000.0], usable=[True, True]) is None   # 4 GB of layers


def test_shipped_profiles_file_is_valid_and_disabled():
    """The shipped config/gpu_profiles.json must be valid and all-disabled (single-GPU no-op)."""
    from eli.core.runtime_settings import _eli_runtime_physical_project_root
    p = _eli_runtime_physical_project_root() / "config" / "gpu_profiles.json"
    if not p.is_file():
        return  # not present in this checkout; template covers it
    data = json.loads(p.read_text())
    assert all(not prof.get("enabled") for prof in data.get("profiles", []))
