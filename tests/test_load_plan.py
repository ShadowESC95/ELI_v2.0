"""The load planner (eli/core/load_plan.py): what a model loads with on this machine, measured by
llama.cpp on every GPU it sees.

It replaced a ladder of guessed configurations, a load probe whose checks timed out (30 of 32), a
one-card fit and a fit calculator per window. What those protected is tested here: the user's own
settings load when they fit, a reserve stays free on every card, "every layer" means every layer and
the output head, the cards and shares chosen are the ones used, a mixture-of-experts model keeps
experts in RAM only as far as it must, and a file llama.cpp cannot open is handed over as asked.

The machine is fake; its llama.cpp writes its log in llama.cpp's own format, so the log reading is
exercised as well, and one test reads lines copied from a real load on two RTX 2060 SUPER cards.
"""
from __future__ import annotations

from typing import List, Optional, Sequence

import pytest

from eli.core import gguf_sizes, hardware_profile as hp, load_plan
from eli.core.load_plan import Device, Footprint, Request

MIB = 1024 * 1024
BLOCKS = 8
BLOCK_MB = 100.0           # each block's weights
OUTPUT_MB = 50.0           # the output head
KV_MB_PER_1K = 4.0         # each block's cache per 1024 tokens of context
COMPUTE_MB_PER_512 = 120.0  # each card's compute buffer per 512 of batch


def _weights(experts_mb: float = 0.0) -> gguf_sizes.Weights:
    return gguf_sizes.Weights(blocks=BLOCKS, block_bytes=tuple([int(BLOCK_MB * MIB)] * BLOCKS),
                              expert_bytes=tuple([int(experts_mb * MIB)] * BLOCKS),
                              output_bytes=int(OUTPUT_MB * MIB), input_bytes=int(40 * MIB))


def _llama_log(*, n_ctx: int, n_batch: int, n_gpu_layers: int, tensor_split: Optional[Sequence[float]],
               gpu_names: Sequence[str]) -> List[str]:
    """What llama.cpp logs for a simulated load: each unit's device, the cache by layer and its size,
    each device's compute buffer, the flash-attention decision."""
    units = BLOCKS + 1
    counts = [int(c) for c in (tensor_split or [n_gpu_layers])]
    where = load_plan.layer_devices(units, n_gpu_layers, counts)
    lines = [f"load_tensors: layer {u:3d} assigned to device {gpu_names[where[u]] if u in where else 'CPU'}, is_swa = 0"
             for u in range(units)]
    lines += [f"llama_kv_cache: layer {b:3d}: dev = {gpu_names[where[b]] if b in where else 'CPU'}" for b in range(BLOCKS)]
    lines.append(f"llama_kv_cache: size = {KV_MB_PER_1K * n_ctx / 1024 * BLOCKS:.2f} MiB ( {n_ctx} cells, "
                 f"{BLOCKS} layers,  1/1 seqs), K (q8_0):  1.00 MiB, V (q8_0):  1.00 MiB")
    names = list(gpu_names) or ["CPU"]
    for d in sorted(set(where.values()) or {0}):   # the first card keeps a compute buffer even with no layers
        lines.append(f"sched_reserve:      {names[d]} compute buffer size = "
                     f"{COMPUTE_MB_PER_512 * n_batch / 512:.2f} MiB")
    lines.append("sched_reserve:  CUDA_Host compute buffer size =    20.00 MiB")
    lines.append("llama_context: Flash Attention enabled")
    return [ln + "\n" for ln in lines]          # llama.cpp's log callback hands over text with its newlines


@pytest.fixture
def machine(monkeypatch, tmp_path):
    """Two cards (free MiB settable) and a dense 8-block model; returns a setter for the cards."""
    state = {"free": [2000.0, 2000.0], "weights": _weights(), "unreadable": False, "sims": []}

    def _devices():
        return [Device(i, f"CUDA{i}", f"Card {i}", f, 4096.0, False) for i, f in enumerate(state["free"])]

    def _simulate(model_path, *, n_ctx, n_batch, n_gpu_layers, split_mode, main_gpu, tensor_split, type_k, type_v,
                  flash_attn, experts_in_ram, weights, gpu_names):
        state["sims"].append(dict(n_ctx=n_ctx, n_batch=n_batch, n_gpu_layers=n_gpu_layers, split=tensor_split,
                                  experts_in_ram=experts_in_ram))
        if state["unreadable"]:
            return Footprint(ok=False, error="llama_model_load: error loading model: unknown model architecture",
                             unreadable=True)
        lines = _llama_log(n_ctx=n_ctx, n_batch=n_batch, n_gpu_layers=n_gpu_layers,
                           tensor_split=tensor_split, gpu_names=gpu_names)
        return load_plan.parse_footprint(lines, weights, gpu_names, experts_in_ram=experts_in_ram)

    monkeypatch.setattr(load_plan, "devices", _devices)
    monkeypatch.setattr(load_plan, "simulate", _simulate)
    monkeypatch.setattr(load_plan, "simulation_supported", lambda: True)
    monkeypatch.setattr(gguf_sizes, "weights", lambda path: state["weights"])
    monkeypatch.delenv("ELI_VRAM_RESERVE_MB", raising=False)
    monkeypatch.setattr(hp, "cpu_ram_budget_mb", lambda *a, **k: 64000)
    monkeypatch.setattr(hp, "detect_hardware", lambda *a, **k: hp.HardwareProfile(ram_gb=32.0, available_ram_gb=24.0))
    monkeypatch.setattr(hp, "recommend_cpu_threads", lambda *a, **k: 6)
    monkeypatch.delenv("ELI_MOE_EXPERT_OFFLOAD", raising=False)
    return state


def _req(**kw) -> Request:
    base = dict(model_path="m.gguf", n_ctx=8192, n_gpu_layers=None, n_batch=512, fit_priority="balanced")
    base.update(kw)
    return Request(**base)


def _within_reserve(p, state):
    """Each card keeps its headroom free: here, nothing measured yet, llama.cpp's compute figure."""
    for d, used in p.use_mb.items():
        assert used <= state["free"][d] - COMPUTE_MB_PER_512 * p.n_batch / 512 + 1e-6, (d, used)


# ── the user's settings, as asked, when they fit ────────────────────────────

def test_settings_that_fit_load_as_asked_on_both_cards(machine):
    p = load_plan.plan(_req())
    assert (p.n_ctx, p.n_batch, p.n_gpu_layers) == (8192, 512, BLOCKS + 1)
    assert p.measured and "your settings fit as asked" in p.notes
    assert all(c > 0 for c in p.tensor_split)          # both cards carry layers
    _within_reserve(p, machine)


def test_every_block_asked_for_means_the_output_head_too(machine):
    """llama.cpp counts the output head as one more layer: 8 asked of an 8-block model left block 0
    on the processor while ELI reported 8/8."""
    assert load_plan.plan(_req(n_gpu_layers=BLOCKS)).n_gpu_layers == BLOCKS + 1


def test_a_partial_layer_count_is_kept(machine):
    assert load_plan.plan(_req(n_gpu_layers=5)).n_gpu_layers == 5


# ── when the cards cannot hold it all ───────────────────────────────────────

def test_less_memory_gives_fewer_layers_and_says_so(machine):
    machine["free"] = [700.0, 700.0]          # the whole model with its cache and buffers needs ~1.6 GB
    p = load_plan.plan(_req())
    assert 0 < p.n_gpu_layers < BLOCKS + 1
    assert any("the most that fits now" in n for n in p.notes)
    _within_reserve(p, machine)


def test_no_room_on_any_card_runs_on_the_processor(machine, monkeypatch):
    machine["free"] = [20.0, 20.0]            # not even a compute buffer at the smallest batch fits
    monkeypatch.setattr(hp, "cpu_ram_fit_config", lambda *a, **k: (8192, 256))
    p = load_plan.plan(_req())
    assert p.n_gpu_layers == 0 and any("no GPU placement fits" in n for n in p.notes)


# ── which cards, and how much on each ───────────────────────────────────────

def test_one_card_chosen_is_the_only_card_used(machine):
    p = load_plan.plan(_req(gpu_devices="1"))
    assert p.tensor_split[0] == 0 and p.tensor_split[1] == p.n_gpu_layers


def test_manual_shares_are_honoured(machine):
    machine["free"] = [4000.0, 4000.0]
    p = load_plan.plan(_req(tensor_split="1,3"))
    small, big = p.tensor_split
    assert small + big == p.n_gpu_layers and big > small


def test_a_card_with_less_room_carries_fewer_layers(machine):
    machine["free"] = [700.0, 2000.0]
    p = load_plan.plan(_req())
    assert p.tensor_split[0] < p.tensor_split[1]
    _within_reserve(p, machine)


def test_processor_only_never_touches_a_card(machine):
    p = load_plan.plan(_req(cpu_only=True))
    assert p.n_gpu_layers == 0 and all(sim["n_gpu_layers"] == 0 for sim in machine["sims"])
    kwargs = p.llama_kwargs()
    assert kwargs["n_gpu_layers"] == 0 and kwargs["main_gpu"] == -1


def test_the_processor_plan_is_measured_by_llamacpp(machine, monkeypatch):
    """Weights 850 MB, cache 32 MB per 1024 tokens, buffers 140 MB: 1100 MB holds 3520 tokens. The
    estimate it replaced added a fixed "CUDA overhead" to a load with no GPU."""
    monkeypatch.setattr(hp, "cpu_ram_budget_mb", lambda *a, **k: 1100)
    p = load_plan.plan(_req(cpu_only=True))
    assert p.measured and p.n_ctx == 3520 and p.n_batch == 512


# ── mixture-of-experts ──────────────────────────────────────────────────────

def test_experts_go_to_ram_only_as_far_as_they_must(machine):
    """Every layer on the cards, with the experts of the fewest leading layers kept in RAM."""
    machine["weights"] = _weights(experts_mb=300.0)
    machine["free"] = [1700.0, 1700.0]          # the whole model needs ~3.7 GB; the cards hold 2.8
    p = load_plan.plan(_req())
    assert p.n_gpu_layers == BLOCKS + 1
    assert p.experts_in_ram is not None and 0 < p.experts_in_ram < BLOCKS
    _within_reserve(p, machine)


# ── a file llama.cpp cannot open ────────────────────────────────────────────

def test_an_unopenable_file_is_handed_over_as_asked_after_one_try(machine):
    machine["unreadable"] = True
    p = load_plan.plan(_req(n_gpu_layers=20))
    assert len(machine["sims"]) == 1                       # no search on a file no setting opens
    assert p.n_gpu_layers == 20 and any("cannot open this model" in n for n in p.notes)


def test_an_unreadable_tensor_table_gives_no_plan(machine, monkeypatch):
    monkeypatch.setattr(gguf_sizes, "weights", lambda path: None)
    assert load_plan.plan(_req()) is None


# ── reading llama.cpp's log ─────────────────────────────────────────────────

REAL_GEMMA4_LINES = [   # gemma-4-E4B, 42 blocks, split over two RTX 2060 SUPER (bench g_split.log)
    "load_tensors: layer   0 assigned to device CUDA0, is_swa = 1",
    "load_tensors: layer   5 assigned to device CUDA0, is_swa = 0",
    "load_tensors: layer  13 assigned to device CUDA1, is_swa = 1",
    "load_tensors: layer  42 assigned to device CUDA1, is_swa = 0",
    "llama_kv_cache: layer   0: filtered",
    "llama_kv_cache: layer   5: dev = CUDA0",
    "llama_kv_cache: layer  23: dev = CUDA1",
    "llama_kv_cache: layer  24: does not have KV cache",
    "llama_kv_cache: size =  628.00 MiB ( 40192 cells,   2 layers,  1/1 seqs), K (f16):  314.00 MiB, V (f16):  314.00 MiB",
    "llama_kv_cache: layer   0: dev = CUDA0",
    "llama_kv_cache: layer   5: filtered",
    "llama_kv_cache: size = 1570.00 MiB ( 40192 cells,  1 layers,  1/1 seqs), K (f16):  785.00 MiB, V (f16):  785.00 MiB",
    "sched_reserve:      CUDA0 compute buffer size =   519.07 MiB",
    "sched_reserve:      CUDA1 compute buffer size =   914.08 MiB",
    "sched_reserve:  CUDA_Host compute buffer size =   345.09 MiB",
    "llama_context: Flash Attention enabled",
]


def test_a_real_two_card_log_is_read_per_card():
    fp = load_plan.parse_footprint([ln + "\n" for ln in REAL_GEMMA4_LINES], None, ["CUDA0", "CUDA1"])
    assert fp.layer_dev == {0: "CUDA0", 5: "CUDA0", 13: "CUDA1", 42: "CUDA1"}
    assert fp.layer_kv_mb == {5: pytest.approx(314.0), 23: pytest.approx(314.0), 0: pytest.approx(1570.0)}
    assert fp.per_device["CUDA0"] == pytest.approx(314.0 + 1570.0 + 519.07)
    assert fp.per_device["CUDA1"] == pytest.approx(314.0 + 914.08)
    assert fp.host_compute_mb == pytest.approx(345.09) and fp.flash_attn is True


# ── headroom: measured on the machine, remembered ───────────────────────────

def _cards():
    return [Device(0, "CUDA0", "Card 0", 2000.0, 4096.0, False), Device(1, "CUDA1", "Card 1", 2000.0, 4096.0, False)]


def test_a_card_never_measured_keeps_llamacpps_compute_figure_free(machine):
    assert load_plan.headroom_mb(_cards()[0], "m.gguf", 512, compute_mb=120.0) == 120.0


def test_what_a_load_took_is_measured_and_used_next_time(machine, monkeypatch):
    plan = load_plan.plan(_req())
    load_plan.watch_headroom(plan)
    machine["free"] = [f - 55.0 for f in machine["free"]]          # llama.cpp's buffers on the first prompt
    load_plan.note_headroom()
    assert load_plan.headroom_mb(_cards()[0], "m.gguf", 512, compute_mb=120.0) == pytest.approx(55.0)
    # a larger batch than measured needs proportionally more
    assert load_plan.headroom_mb(_cards()[0], "m.gguf", 1024, compute_mb=240.0) == pytest.approx(110.0)
    # another model on the same card starts from what this card was seen to need
    assert load_plan.headroom_mb(_cards()[0], "other.gguf", 512, compute_mb=120.0) == pytest.approx(55.0)


def test_memory_another_program_takes_later_is_not_put_down_to_eli(machine):
    load_plan.watch_headroom(load_plan.plan(_req()))
    machine["free"] = [f - 40.0 for f in machine["free"]]
    for _ in range(10):
        load_plan.note_headroom()
    machine["free"] = [f - 2000.0 for f in machine["free"]]           # a game starts an hour later
    load_plan.note_headroom()
    assert load_plan.headroom_mb(_cards()[0], "m.gguf", 512, compute_mb=120.0) == pytest.approx(40.0)


def test_the_operators_own_figure_wins(machine, monkeypatch):
    monkeypatch.setenv("ELI_VRAM_RESERVE_MB", "900")
    assert load_plan.headroom_mb(_cards()[0], "m.gguf", 512, compute_mb=120.0) == 900.0


def test_minus_one_is_every_layer_as_in_llamacpp(machine):
    """llama.cpp's own value for every layer; "99" stood for it and fell short on models of more blocks."""
    assert load_plan.plan(_req(n_gpu_layers=-1)).n_gpu_layers == BLOCKS + 1
