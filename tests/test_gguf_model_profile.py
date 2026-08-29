"""GGUF header metadata drives layer count — not filename or file-size guesses."""
import struct
from pathlib import Path

import pytest

from eli.cognition import model_load_diagnostics as mld
from eli.core.hardware_profile import layers_for_model, smart_fit_config


def _write_gguf_kv(tmp_path: Path, name: str, kv: dict) -> Path:
    p = tmp_path / name
    with open(p, "wb") as f:
        f.write(b"GGUF")
        f.write(struct.pack("<I", 3))
        f.write(struct.pack("<Q", 0))
        f.write(struct.pack("<Q", len(kv)))
        for key, (vtype, val) in kv.items():
            kb = key.encode("utf-8")
            f.write(struct.pack("<Q", len(kb)))
            f.write(kb)
            f.write(struct.pack("<I", vtype))
            if vtype == 8:
                vb = val.encode("utf-8")
                f.write(struct.pack("<Q", len(vb)))
                f.write(vb)
            elif vtype == 4:
                f.write(struct.pack("<I", int(val)))
    return p


def test_block_count_read_from_gguf_header(tmp_path):
    p = _write_gguf_kv(
        tmp_path,
        "future-moe.gguf",
        {
            "general.architecture": (8, "gpt-oss"),
            "gpt-oss.block_count": (4, 24),
            "gpt-oss.context_length": (4, 131072),
            "gpt-oss.expert_count": (4, 32),
            "gpt-oss.expert_used_count": (4, 4),
        },
    )
    prof = mld.gguf_model_profile(p)
    assert prof.architecture == "gpt-oss"
    assert prof.block_count == 24
    assert prof.context_length == 131072
    assert prof.expert_count == 32
    assert prof.expert_used_count == 4
    assert prof.is_moe is True
    assert prof.uses_swa_kv is True
    assert prof.layer_count(size_gb=21.0) == 24


def test_layers_for_model_prefers_metadata_over_size_heuristic(tmp_path):
    p = _write_gguf_kv(
        tmp_path,
        "dense-21gb-but-24-blocks.gguf",
        {"general.architecture": (8, "gpt-oss"), "gpt-oss.block_count": (4, 24)},
    )
    # Size heuristic for 21 GB would be 48; metadata says 24.
    assert layers_for_model(str(p), 21.0) == 24


def test_smart_fit_uses_real_block_count_for_heavy_layers(tmp_path):
    p = _write_gguf_kv(
        tmp_path,
        "gpt-oss-fit.gguf",
        {"general.architecture": (8, "gpt-oss"), "gpt-oss.block_count": (4, 24)},
    )
    size_gb = 20.7
    ctx_heur, layers_heur, _ = smart_fit_config(
        size_gb, 6610, user_ctx=10384, user_batch=128,
        reserve_mb=700, kv_quantized=True,
    )
    ctx_meta, layers_meta, _ = smart_fit_config(
        size_gb, 6610, user_ctx=10384, user_batch=128,
        reserve_mb=700, kv_quantized=True, model_path=str(p),
    )
    assert ctx_heur == ctx_meta
    assert layers_meta <= layers_heur, (
        "real 24-block count must not recommend MORE GPU layers than the 48-layer heuristic"
    )


@pytest.mark.skipif(
    not Path("models/gpt-oss-20b-eddy.Q6_K.gguf").is_file(),
    reason="local gpt-oss model not present",
)
def test_local_gpt_oss_block_count_when_present():
    p = Path("models/gpt-oss-20b-eddy.Q6_K.gguf").resolve()
    prof = mld.gguf_model_profile(p)
    assert prof.architecture == "gpt-oss"
    assert prof.block_count == 24
    assert layers_for_model(str(p), p.stat().st_size / (1024 ** 3)) == 24


def test_gpt_oss_requires_modern_runtime():
    assert mld.architecture_requires_modern_runtime("gpt-oss") is True
    assert mld.architecture_requires_modern_runtime("gpt_oss") is True
