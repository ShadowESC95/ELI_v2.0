"""The GPU report's "Performance reading" must describe THIS load, not loads in general.

From the 2.1.84 session, the report ended with three fixed strings printed no matter
what was measured:

    - The live runtime is constrained by available VRAM. On 8 GB GPU, large context
      and high GPU-layer counts can exceed it and force fallback.
    - If ELI booted with lower selected ctx/GPU-layer parameters than requested, the
      fallback is expected behavior, not a settings lie.
    - Higher free VRAM gives more room for GPU layers or batch size; …

The middle line hedges about a fallback that provably had not happened, while the
proof sat in the same payload: `requested` and `effective` were both present and
identical (10384/99/128/10), and the loader log showed attempt 1 of 12 selected
outright. A report whose whole job is telling the user the truth about their runtime
should not speculate about its own state.

Second defect, found while fixing the first: `live_runtime_brief()` already existed
to say this, and its clamp branch was DEAD. It read `snap.get("clamped", False)`, but
the publisher that actually runs in the shipped GUI — the [GGUF][EFFECTIVE] contract
in gguf_inference — writes `requested`/`effective` and no such flag. Only
eli/gui/app.py sets it, and that is not the writer on a normal launch. So however
hard the loader had squeezed the model in, the brief reported nothing.
"""
import csv
import json

import pytest

from eli.cognition.context_synthesiser import runtime_load_gap
import eli.execution.executor_enhanced as ex


# The live snapshot from that session, verbatim in shape: no "clamped", no "on_gpu".
AS_REQUESTED = {
    "provider": "gguf", "model_name": "Qwen_Qwen3-8B-Q4_K_M.gguf",
    "n_ctx": 10384, "n_gpu_layers": 99, "n_threads": 10, "n_batch": 128,
    "gpu_offload_supported": True, "load_mode": "GPU", "loaded": True,
    "runtime_contract": "requested_effective_split",
    "requested": {"n_ctx": 10384, "n_gpu_layers": 99, "n_threads": 10, "n_batch": 128},
    "effective": {"n_ctx": 10384, "n_gpu_layers": 99, "n_threads": 10, "n_batch": 128},
}
CLAMPED = dict(
    AS_REQUESTED, n_ctx=4096, n_gpu_layers=49,
    effective={"n_ctx": 4096, "n_gpu_layers": 49, "n_threads": 10, "n_batch": 128},
)

# name, total, used, free, util, temp, power, limit, driver — the reading from that run.
SMI_TIGHT = "NVIDIA GeForce RTX 2060 SUPER, 8192, 7493, 260, 11, 44, 24.58, 215.00, 595.84"
SMI_ROOMY = "NVIDIA GeForce RTX 2060 SUPER, 8192, 2048, 6144, 11, 44, 24.58, 215.00, 595.84"


# ── the comparison itself ───────────────────────────────────────────────────
def test_a_clean_load_is_reported_as_clean():
    gap = runtime_load_gap(AS_REQUESTED)
    assert gap["ok"] and gap["on_gpu"]
    assert gap["clamped"] is False
    assert gap["reduced"] == {}


def test_a_clamp_is_detected_without_any_flag():
    """The whole point: the shipped snapshot carries no 'clamped' key."""
    assert "clamped" not in CLAMPED
    gap = runtime_load_gap(CLAMPED)
    assert gap["clamped"] is True
    assert gap["reduced"]["n_ctx"] == {"requested": 10384, "effective": 4096}
    assert gap["reduced"]["n_gpu_layers"] == {"requested": 99, "effective": 49}


def test_an_explicit_flag_still_wins_when_a_writer_provides_one():
    """eli/gui/app.py does set it; that writer must not be second-guessed."""
    assert runtime_load_gap(dict(AS_REQUESTED, clamped=True))["clamped"] is True


def test_a_flat_legacy_snapshot_still_compares():
    flat = {"n_ctx": 4096, "requested_n_ctx": 10384, "n_gpu_layers": 99,
            "requested_n_gpu_layers": 99, "load_mode": "GPU"}
    assert runtime_load_gap(flat)["reduced"]["n_ctx"] == {"requested": 10384, "effective": 4096}


def test_an_empty_snapshot_claims_nothing():
    gap = runtime_load_gap({})
    assert gap["ok"] is False and gap["clamped"] is False and gap["reduced"] == {}


# ── the rendered report ─────────────────────────────────────────────────────
@pytest.fixture
def gpu_report(monkeypatch, tmp_path):
    def _run(snapshot, smi_row):
        (tmp_path / "runtime_snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")

        class _Paths:
            artifacts_dir = tmp_path
        monkeypatch.setattr(ex, "get_paths", lambda: _Paths())

        class _Proc:
            returncode = 0
            stdout = smi_row
            stderr = ""
        monkeypatch.setattr(ex.subprocess, "run", lambda *a, **k: _Proc())
        return ex._gpu_status_report()["content"]
    return _run


def test_the_boilerplate_is_gone(gpu_report):
    txt = gpu_report(AS_REQUESTED, SMI_TIGHT)
    assert "not a settings lie" not in txt
    assert "If ELI booted with lower" not in txt
    assert "can exceed it and force fallback" not in txt


def test_a_clean_load_says_so_plainly(gpu_report):
    txt = gpu_report(AS_REQUESTED, SMI_TIGHT)
    assert "Loaded exactly as requested" in txt
    assert "no fallback occurred" in txt
    assert "ctx=10384" in txt and "gpu_layers=99" in txt


def test_a_clamped_load_names_what_was_reduced(gpu_report):
    txt = gpu_report(CLAMPED, SMI_TIGHT)
    assert "Loaded BELOW request" in txt
    assert "n_ctx 10384 → 4096" in txt
    assert "n_gpu_layers 99 → 49" in txt
    assert "Loaded exactly as requested" not in txt


def test_headroom_is_read_from_the_measured_vram(gpu_report):
    tight = gpu_report(AS_REQUESTED, SMI_TIGHT)
    assert "260 MiB of 8192 MiB VRAM free (3.2%)" in tight
    assert "no headroom" in tight

    roomy = gpu_report(AS_REQUESTED, SMI_ROOMY)
    assert "6144 MiB of 8192 MiB VRAM free (75.0%)" in roomy
    assert "headroom available" in roomy


def test_cpu_only_is_called_out(gpu_report):
    cpu = dict(AS_REQUESTED, load_mode="CPU", n_gpu_layers=0,
               effective={"n_ctx": 10384, "n_gpu_layers": 0, "n_threads": 10, "n_batch": 128})
    txt = gpu_report(cpu, SMI_TIGHT)
    assert "Running CPU-only" in txt


def test_the_measured_hardware_lines_are_untouched(gpu_report):
    """The fix must not disturb the part of the report that was already true."""
    txt = gpu_report(AS_REQUESTED, SMI_TIGHT)
    assert "NVIDIA GeForce RTX 2060 SUPER" in txt
    assert "7493 MiB used / 8192 MiB total" in txt
    assert "temperature: 44 C" in txt
    assert "driver: 595.84" in txt
