"""Memory costs come from the model file, not from one size for every model.

The fit sized a layer as the file size over the layer count (embeddings included, which never
leave the CPU) and the KV cache at a fixed 6000 bytes per token per layer. Measured on real files
against llama.cpp: a hybrid-attention MoE caches KV on one layer in four (the constant was nearly
twelve times too large), gemma-4 keeps 3.5 GB of embeddings on the CPU (its layers were sized at nearly
double). The files below are built with the same header fields those models carry.
"""
from __future__ import annotations

import struct

import pytest

from eli.core import gguf_sizes
import eli.core.hardware_profile as hp

MIB = 1024 * 1024


def _gguf(path, arch: str, meta: dict, tensors: dict) -> str:
    """A GGUF file with this metadata and tensors of these byte sizes (contents are zeros)."""
    def s(text):
        raw = text.encode()
        return struct.pack("<Q", len(raw)) + raw

    def value(v):
        if isinstance(v, bool):
            return struct.pack("<I", 7) + struct.pack("<?", v)
        if isinstance(v, int):
            return struct.pack("<I", 4) + struct.pack("<I", v)
        if isinstance(v, str):
            return struct.pack("<I", 8) + s(v)
        if isinstance(v, list):
            if all(isinstance(x, bool) for x in v):
                return struct.pack("<II", 9, 7) + struct.pack("<Q", len(v)) + b"".join(struct.pack("<?", x) for x in v)
            return struct.pack("<II", 9, 4) + struct.pack("<Q", len(v)) + b"".join(struct.pack("<I", x) for x in v)
        raise TypeError(v)

    kv = {"general.architecture": arch, "general.alignment": 32}
    kv.update({f"{arch}.{k}": v for k, v in meta.items()})
    head = b"GGUF" + struct.pack("<I", 3) + struct.pack("<QQ", len(tensors), len(kv))
    head += b"".join(s(k) + value(v) for k, v in kv.items())
    offset = 0
    for name, size in tensors.items():
        head += s(name) + struct.pack("<I", 1) + struct.pack("<Q", size) + struct.pack("<I", 0)
        head += struct.pack("<Q", offset)
        offset += size + (-size % 32)
    head += b"\0" * (-len(head) % 32)
    with open(path, "wb") as f:
        f.write(head)
        f.truncate(len(head) + offset)
    return str(path)


def _dense(tmp_path, name="dense.gguf", *, blocks=28, block_mib=30, embd_mib=297, tied=True, meta=None):
    tensors = {"token_embd.weight": embd_mib * MIB}
    for i in range(blocks):
        tensors[f"blk.{i}.attn_q.weight"] = block_mib * MIB // 2
        tensors[f"blk.{i}.ffn_up.weight"] = block_mib * MIB // 2
    if not tied:
        tensors["output.weight"] = embd_mib * MIB
    base = {"block_count": blocks, "embedding_length": 1024, "attention.head_count": 16,
            "attention.head_count_kv": 8, "attention.key_length": 128, "attention.value_length": 128}
    base.update(meta or {})
    return _gguf(tmp_path / name, "qwen3", base, tensors)


# ── KV per token from the header, checked against llama.cpp's own numbers ────

def test_grouped_query_attention_matches_llama_cpp(tmp_path):
    # Qwen3-0.6B: llama.cpp reported 448 MiB for 4096 cells at f16, 112 KiB a token
    path = _dense(tmp_path)
    assert gguf_sizes.kv_bytes_per_token(path, "f16") == 112 * 1024


def test_head_size_defaults_to_width_over_heads(tmp_path):
    # SmolLM3 carries no key_length: 2048 wide, 16 heads, 4 KV heads, 36 layers -> 72 KiB measured
    path = _gguf(tmp_path / "s.gguf", "smollm3",
                 {"block_count": 36, "embedding_length": 2048, "attention.head_count": 16,
                  "attention.head_count_kv": 4}, {"blk.0.attn_q.weight": MIB})
    assert gguf_sizes.kv_bytes_per_token(path, "f16") == 72 * 1024


def test_a_hybrid_model_caches_kv_on_its_attention_layers_only(tmp_path):
    # Qwen3.6-35B-A3B: full attention every 4th of 40 layers, 2 KV heads of 256+256
    path = _gguf(tmp_path / "h.gguf", "qwen35moe",
                 {"block_count": 40, "embedding_length": 2048, "attention.head_count": 16,
                  "attention.head_count_kv": 2, "attention.key_length": 256,
                  "attention.value_length": 256, "full_attention_interval": 4},
                 {"blk.0.attn_q.weight": MIB})
    per_token = gguf_sizes.kv_bytes_per_token(path, "f16")
    assert per_token == 10 * 2 * 512 * 2
    assert per_token * 11 < 6000 * 40          # the constant was nearly twelve times this


def test_sliding_window_and_shared_layers_err_large_never_small(tmp_path):
    # gemma-4-E4B: llama.cpp measured 76 KiB a token; the header rules must not undercount
    path = _gguf(tmp_path / "g.gguf", "gemma4",
                 {"block_count": 42, "embedding_length": 2560, "attention.head_count": 8,
                  "attention.head_count_kv": 2, "attention.key_length": 512,
                  "attention.value_length": 512, "attention.key_length_swa": 256,
                  "attention.value_length_swa": 256, "attention.shared_kv_layers": 18,
                  "attention.sliding_window": 512},
                 {"blk.0.attn_q.weight": MIB})
    assert gguf_sizes.kv_bytes_per_token(path, "f16") >= 76 * 1024


def test_cache_types_scale_by_their_block_layout(tmp_path):
    path = _dense(tmp_path)
    f16 = gguf_sizes.kv_bytes_per_token(path, "f16")
    assert gguf_sizes.kv_bytes_per_token(path, "q8_0") == pytest.approx(f16 * 34 / 64)
    assert gguf_sizes.kv_bytes_per_token(path, "q4_0") == pytest.approx(f16 * 18 / 64)


# llama.cpp 0.3.35, gemma-4-E4B at n_ctx 4096: two caches, the second with V wider than K
_GEMMA_LOAD = [
    "llama_kv_cache:        CPU KV buffer size =    64.00 MiB\n",
    "llama_kv_cache: size =   64.00 MiB (  4096 cells,   4 layers,  1/1 seqs), K (f16):   32.00 MiB, V (f16):   32.00 MiB\n",
    "llama_kv_cache:        CPU KV buffer size =   240.00 MiB\n",
    "llama_kv_cache: size =  240.00 MiB (  4096 cells,  20 layers,  1/1 seqs), K (f16):   80.00 MiB, V (f16):  160.00 MiB\n",
]


def test_a_load_report_replaces_the_estimate_with_the_measured_size(tmp_path, monkeypatch):
    monkeypatch.setattr(gguf_sizes, "_record_path", lambda: tmp_path / "model_sizes.json")
    path = _dense(tmp_path, "g4.gguf")
    assert gguf_sizes.kv_elements_per_token(path)[2] == "estimated"
    gguf_sizes.record_load_report(path, _GEMMA_LOAD)
    k, v, source = gguf_sizes.kv_elements_per_token(path)
    assert source == "measured"
    assert gguf_sizes.kv_bytes_per_token(path, "f16") == 76 * 1024
    # a report from a q4_0 load still yields elements, so f16 sizing stays exact
    gguf_sizes.record_load_report(path, [
        "llama_kv_cache: size =  31.50 MiB (  4096 cells,  28 layers,  1/1 seqs), "
        "K (q4_0):   15.75 MiB, V (q4_0):   15.75 MiB\n"])
    assert gguf_sizes.kv_bytes_per_token(path, "f16") == 28 * 1024     # 7168 K + 7168 V elements


def test_a_log_without_a_kv_report_records_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(gguf_sizes, "_record_path", lambda: tmp_path / "model_sizes.json")
    path = _dense(tmp_path)
    assert gguf_sizes.record_load_report(path, ["load_tensors: layer 0 assigned to device CPU\n"]) is None
    assert gguf_sizes.kv_elements_per_token(path)[2] == "estimated"


# ── weights per layer from the tensor table ──────────────────────────────────

def test_embeddings_never_count_as_gpu_layers(tmp_path):
    path = _dense(tmp_path, blocks=10, block_mib=100, embd_mib=1000)
    w = gguf_sizes.weights(path)
    assert w.gpu_bytes(5, experts_in_ram=False) == 5 * 100 * MIB          # the last five blocks
    # every block plus the output layer, which with tied embeddings is a copy of token_embd
    assert w.gpu_bytes(11, experts_in_ram=False) == (10 * 100 + 1000) * MIB


def test_expert_offload_keeps_experts_out_of_the_gpu_figure(tmp_path):
    tensors = {"token_embd.weight": 64 * MIB, "output.weight": 64 * MIB}
    for i in range(4):
        tensors[f"blk.{i}.attn_q.weight"] = 8 * MIB
        tensors[f"blk.{i}.ffn_up_exps.weight"] = 200 * MIB
    path = _gguf(tmp_path / "moe.gguf", "qwen35moe",
                 {"block_count": 4, "embedding_length": 512, "attention.head_count": 4,
                  "expert_count": 64}, tensors)
    w = gguf_sizes.weights(path)
    assert w.experts_total == 4 * 200 * MIB
    assert w.gpu_bytes(5, experts_in_ram=True) == (4 * 8 + 64) * MIB
    assert w.gpu_bytes(5, experts_in_ram=False) == (4 * 208 + 64) * MIB


def test_the_fit_uses_the_files_sizes(tmp_path):
    """Half this file is embeddings: by its tensors every layer fits, by size/layers fewer do."""
    path = _dense(tmp_path, blocks=32, block_mib=100, embd_mib=3200)
    size_gb = 6.25
    kw = dict(user_ctx=4096, user_batch=128, reserve_mb=500, kv_quantized=True, min_batch=128)
    from_file = hp.unified_fit_config(size_gb, 6000, 32.0, model_path=path, **kw)
    by_size = hp.unified_fit_config(size_gb, 6000, 32.0, model_path=str(tmp_path / "missing.gguf"),
                                    total_layers=32, **kw)
    assert from_file[1] > by_size[1]


def test_an_unreadable_file_falls_back_to_the_estimate(tmp_path):
    bad = tmp_path / "bad.gguf"
    bad.write_bytes(b"not a gguf")
    assert gguf_sizes.weights(bad) is None
    assert hp.model_cost(str(bad)) is None


# ── decisions measured from the model and the machine ────────────────────────

def test_kv_is_quantized_only_when_memory_limits_the_context(tmp_path, monkeypatch):
    import eli.core.startup_hardware_optimizer as sho
    monkeypatch.setattr(sho, "_gguf_metadata_ctx", lambda p: 32768)
    path = _dense(tmp_path)
    roomy = hp.kv_cache_quantized(path, 1.1, free_vram_mb=24000, available_ram_gb=64.0, use_gpu=True)
    tight = hp.kv_cache_quantized(path, 1.1, free_vram_mb=0, available_ram_gb=2.0, use_gpu=False)
    assert roomy is False and tight is True


def test_an_unknown_model_keeps_llama_cpp_default_cache(monkeypatch):
    import eli.core.startup_hardware_optimizer as sho
    monkeypatch.setattr(sho, "_gguf_metadata_ctx", lambda p: 0)
    assert hp.kv_cache_quantized("missing.gguf", 4.0, free_vram_mb=0, available_ram_gb=1.0,
                                 use_gpu=False) is False


def test_no_card_size_rule_is_left():
    import pathlib
    root = pathlib.Path(hp.__file__).resolve().parents[1]
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        assert "_mb < 12000" not in text and "vram_mb < 12000" not in text, path
