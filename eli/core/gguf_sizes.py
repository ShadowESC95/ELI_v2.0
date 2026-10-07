"""What a GGUF model costs in memory, read from the file and corrected by what llama.cpp reports.

Two numbers decide every fit: the bytes each layer puts on the GPU, and the KV cache bytes per
token of context. Both were estimates that ignored the model: file size divided by the layer count
(embeddings included, which never leave the CPU), and one KV size for every model. On a hybrid
attention model the KV estimate was nearly twelve times too large; on gemma-4 the layer estimate was
nearly double.

Here the weights come from the file's tensor table and the KV from its attention metadata. The
first time a model loads, llama.cpp's own KV report replaces the estimate, recorded per model file
(record_load_report), so an architecture these rules do not know is corrected by measurement.
"""
from __future__ import annotations

import json
import os
import re
import struct
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

from eli.utils.log import get_logger

log = get_logger(__name__)

MIB = 1024 * 1024

# Bytes per element of each cache type, from ggml's block layouts (a q4_0 block holds 32 values
# in 18 bytes). Format facts, not tuning.
_BYTES_PER_ELEMENT = {
    "f32": 4.0, "f16": 2.0, "bf16": 2.0,
    "q8_0": 34 / 32, "q5_1": 24 / 32, "q5_0": 22 / 32,
    "q4_1": 20 / 32, "q4_0": 18 / 32, "iq4_nl": 18 / 32,
}

_EXPERTS = re.compile(r"blk\.\d+\.ffn_(up|down|gate|gate_up)_exps")
_BLOCK = re.compile(r"blk\.(\d+)\.")
# tensors llama.cpp keeps on the CPU whatever the layer count (embedding lookups)
_INPUT = re.compile(r"(^|\.)(token_embd|per_layer_token_embd|token_types|position_embd)\.")

_SCALAR = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?",
           10: "<Q", 11: "<q", 12: "<d"}

_lock = threading.Lock()
_header_cache: Dict[Tuple[str, int, int], Optional["_Header"]] = {}


def bytes_per_element(cache_type: Optional[str]) -> float:
    return _BYTES_PER_ELEMENT.get(str(cache_type or "f16").strip().lower() or "f16", 2.0)


@dataclass(frozen=True)
class _Header:
    meta: Dict[str, Any]
    tensors: Dict[str, int]          # name -> bytes


def _string(f) -> str:
    n = struct.unpack("<Q", f.read(8))[0]
    return f.read(n).decode("utf-8", "replace")


def _value(f, vtype: int):
    if vtype == 8:
        return _string(f)
    if vtype == 9:
        etype = struct.unpack("<I", f.read(4))[0]
        n = struct.unpack("<Q", f.read(8))[0]
        if etype == 8:
            for _ in range(n):
                _string(f)
            return None
        fmt = _SCALAR[etype]
        size = struct.calcsize(fmt)
        raw = f.read(size * n)
        return [struct.unpack_from(fmt, raw, i * size)[0] for i in range(n)]
    fmt = _SCALAR[vtype]
    return struct.unpack(fmt, f.read(struct.calcsize(fmt)))[0]


def _read_header(path: str) -> Optional[_Header]:
    with open(path, "rb") as f:
        if f.read(4) != b"GGUF":
            return None
        f.read(4)                                            # version
        n_tensors = struct.unpack("<Q", f.read(8))[0]
        n_kv = struct.unpack("<Q", f.read(8))[0]
        meta: Dict[str, Any] = {}
        for _ in range(n_kv):
            key = _string(f)
            vtype = struct.unpack("<I", f.read(4))[0]
            val = _value(f, vtype)
            if val is not None:
                meta[key] = val
        offsets = []
        for _ in range(n_tensors):
            name = _string(f)
            dims = struct.unpack("<I", f.read(4))[0]
            f.read(8 * dims + 4)                             # shape, type
            offsets.append((struct.unpack("<Q", f.read(8))[0], name))
        align = int(meta.get("general.alignment", 32) or 32)
        here = f.tell()
        data_start = here + (-here % align)
    data_bytes = os.path.getsize(path) - data_start
    offsets.sort()
    tensors = {}
    for i, (offset, name) in enumerate(offsets):
        end = offsets[i + 1][0] if i + 1 < len(offsets) else data_bytes
        tensors[name] = max(0, end - offset)
    return _Header(meta, tensors)


def _header(path) -> Optional[_Header]:
    try:
        p = str(Path(path).expanduser().resolve())
        st = os.stat(p)
    except (OSError, TypeError, ValueError):
        return None
    key = (p, st.st_size, int(st.st_mtime))
    with _lock:
        if key in _header_cache:
            return _header_cache[key]
    try:
        head = _read_header(p)
    except Exception:
        log.debug("gguf_sizes: header unreadable for %s", p, exc_info=True)
        head = None
    with _lock:
        _header_cache[key] = head
    return head


# ── weights ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Weights:
    blocks: int
    block_bytes: Tuple[int, ...]     # per block, without expert tensors
    expert_bytes: Tuple[int, ...]    # per block, expert tensors only
    output_bytes: int                # output head: on the GPU once every block is
    input_bytes: int                 # embedding lookups: always on the CPU

    @property
    def experts_total(self) -> int:
        return sum(self.expert_bytes)

    @property
    def resident_total(self) -> int:
        """Everything but the experts: what expert offload keeps on the GPU at full offload."""
        return sum(self.block_bytes) + self.output_bytes

    def gpu_bytes(self, n_gpu_layers: int, *, experts_in_ram: bool) -> int:
        """Weight bytes llama.cpp places on the GPU for this layer count: the last n blocks, plus
        the output head when n exceeds the block count."""
        n = max(0, int(n_gpu_layers))
        on_gpu = range(max(0, self.blocks - n), self.blocks)
        total = sum(self.block_bytes[i] for i in on_gpu)
        if not experts_in_ram:
            total += sum(self.expert_bytes[i] for i in on_gpu)
        if n > self.blocks:
            total += self.output_bytes
        return total


def weights(model_path) -> Optional[Weights]:
    head = _header(model_path)
    if head is None:
        return None
    arch = str(head.meta.get("general.architecture") or "")
    blocks = int(head.meta.get(f"{arch}.block_count") or 0)
    if blocks <= 0:
        return None
    block = [0] * blocks
    experts = [0] * blocks
    output = inputs = 0
    for name, size in head.tensors.items():
        m = _BLOCK.match(name)
        if m and int(m.group(1)) < blocks:
            (experts if _EXPERTS.match(name) else block)[int(m.group(1))] += size
        elif _INPUT.search(name):
            inputs += size
        else:
            output += size
    if "output.weight" not in head.tensors:
        # tied embeddings: llama.cpp gives the output layer its own copy of token_embd
        output += int(head.tensors.get("token_embd.weight") or 0)
    return Weights(blocks, tuple(block), tuple(experts), output, inputs)


# ── KV cache ─────────────────────────────────────────────────────────────────

def _per_layer(value, blocks: int):
    if isinstance(value, list):
        return [int(v) for v in value[:blocks]] + [0] * max(0, blocks - len(value))
    return [int(value or 0)] * blocks


def _estimated_kv_elements(meta: Dict[str, Any]) -> Optional[Tuple[int, int]]:
    """(K, V) cache elements per token from the attention metadata, or None.

    Errs large where the rules are unsure (a sliding-window layer is counted at full size), since
    an underestimate is what runs out of memory. The first load replaces it with the real figure."""
    arch = str(meta.get("general.architecture") or "")
    p = f"{arch}."
    blocks = int(meta.get(p + "block_count") or 0)
    heads = meta.get(p + "attention.head_count")
    embd = int(meta.get(p + "embedding_length") or 0)
    if blocks <= 0:
        return None
    if heads in (None, 0, []):
        # no head counts: full multi-head attention is the most a layer of this width can cache
        return (blocks * embd, blocks * embd) if embd > 0 else None
    n_head = _per_layer(heads, blocks)
    n_head_kv = _per_layer(meta.get(p + "attention.head_count_kv", heads), blocks)
    head_dim = embd // max(1, max(n_head)) if embd else 0
    key_len = max(int(meta.get(p + "attention.key_length") or head_dim),
                  int(meta.get(p + "attention.key_length_swa") or 0))
    val_len = max(int(meta.get(p + "attention.value_length") or key_len),
                  int(meta.get(p + "attention.value_length_swa") or 0))
    lora = int(meta.get(p + "attention.kv_lora_rank") or 0)
    if lora:                         # multi-head latent attention caches the compressed form
        key_len = lora + int(meta.get(p + "rope.dimension_count") or 0)
        val_len = lora
        n_head_kv = [1 if h else 0 for h in n_head_kv]
    interval = int(meta.get(p + "full_attention_interval") or 0)
    if interval > 1:                 # hybrid: the other layers keep a fixed-size recurrent state
        n_head_kv = [h if (i + 1) % interval == 0 else 0 for i, h in enumerate(n_head_kv)]
    shared = int(meta.get(p + "attention.shared_kv_layers") or 0)
    if 0 < shared < blocks:          # these layers reuse an earlier layer's cache
        n_head_kv = n_head_kv[:blocks - shared] + [0] * shared
    kv_heads = sum(n_head_kv)
    if kv_heads <= 0 or key_len <= 0:
        return None
    return kv_heads * key_len, kv_heads * val_len


def _record_path() -> Path:
    from eli.core.paths import get_paths
    path = Path(get_paths().artifacts_dir) / "runtime" / "model_sizes.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _model_key(model_path) -> Optional[str]:
    try:
        p = Path(model_path).expanduser()
        return f"{p.name}|{p.stat().st_size}"
    except (OSError, TypeError, ValueError):
        return None


def _records() -> Dict[str, Any]:
    try:
        data = json.loads(_record_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def kv_elements_per_token(model_path) -> Optional[Tuple[int, int, str]]:
    """(K, V, source) cache elements per token: "measured" by a load on this machine, else
    "estimated" from the file. None when neither is available."""
    key = _model_key(model_path)
    if key:
        got = _records().get(key) or {}
        if int(got.get("kv_k_elements") or 0) > 0:
            return int(got["kv_k_elements"]), int(got.get("kv_v_elements") or 0), "measured"
    head = _header(model_path)
    est = _estimated_kv_elements(head.meta) if head else None
    return (est[0], est[1], "estimated") if est else None


def kv_bytes_per_token(model_path, cache_type_k: Optional[str] = None,
                       cache_type_v: Optional[str] = None) -> Optional[float]:
    got = kv_elements_per_token(model_path)
    if not got:
        return None
    k, v, _source = got
    return k * bytes_per_element(cache_type_k) + v * bytes_per_element(cache_type_v or cache_type_k)


_KV_LINE = re.compile(
    r"llama_kv_cache:\s*size\s*=\s*[\d.]+\s*MiB\s*\(\s*(\d+)\s*cells.*?"
    r"K\s*\((\w+)\):\s*([\d.]+)\s*MiB,\s*V\s*\((\w+)\):\s*([\d.]+)\s*MiB")


def record_load_report(model_path, log_lines: Iterable[str]) -> Optional[Tuple[int, int]]:
    """Read llama.cpp's KV report from a load's log and keep it for this model file.

    llama.cpp prints one line per cache (a model with sliding-window layers has two); each gives
    its cell count and the K and V bytes with their types, so elements per token follow exactly
    whatever cache type that load used."""
    k = v = 0.0
    for line in "".join(str(x) for x in (log_lines or [])).splitlines():
        m = _KV_LINE.search(line)
        if not m:
            continue
        cells = max(1, int(m.group(1)))
        k += float(m.group(3)) * MIB / cells / bytes_per_element(m.group(2))
        v += float(m.group(5)) * MIB / cells / bytes_per_element(m.group(4))
    key = _model_key(model_path)
    if k <= 0 or not key:
        return None
    measured = (int(round(k)), int(round(v)))
    try:
        records = _records()
        records[key] = {**(records.get(key) or {}),
                        "kv_k_elements": measured[0], "kv_v_elements": measured[1]}
        _record_path().write_text(json.dumps(records, indent=2), encoding="utf-8")
    except Exception:
        log.debug("gguf_sizes: could not keep the measured KV size", exc_info=True)
    return measured
