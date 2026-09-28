"""A mixture-of-experts model that won't fit as requested is what the loader actually offloads
with experts kept in RAM and every layer on the GPU — a much lighter VRAM footprint than the raw
request. Proving the raw (non-MoE) request tested a configuration that never gets attempted for
real, thrashing the full timeout budget every launch. The probe now tests the configuration that
will actually load.
"""
from __future__ import annotations

import json

from eli.core import load_probe


class _FakeCompleted:
    def __init__(self, stdout="PROBE_OK\n", returncode=0):
        self.stdout, self.returncode, self.stderr = stdout, returncode, ""


def test_probe_tests_the_moe_adjusted_configuration(monkeypatch):
    monkeypatch.setattr(load_probe, "cached_verdict", lambda *a, **k: None)
    monkeypatch.setattr(load_probe, "_recently_timed_out", lambda *a, **k: False)
    monkeypatch.setattr(
        "eli.core.moe_offload.plan_for_load",
        lambda *a, **k: {"resident_gb": 2.0, "experts_gb": 17.7, "layers": 40},
    )
    captured = {}

    def _fake_run(cmd, **kwargs):
        captured["payload"] = json.loads(cmd[-1])
        return _FakeCompleted()

    monkeypatch.setattr(load_probe.subprocess, "run", _fake_run)

    verdict, _why = load_probe.probe_verdict("model.gguf", 12500, 40, 192, use_cache=False)

    assert verdict == load_probe.PROVEN_OK
    assert captured["payload"]["n_gpu_layers"] == 41
    assert captured["payload"]["moe_expert_offload"] is True


def test_a_dense_model_is_probed_as_requested(monkeypatch):
    monkeypatch.setattr(load_probe, "cached_verdict", lambda *a, **k: None)
    monkeypatch.setattr(load_probe, "_recently_timed_out", lambda *a, **k: False)
    monkeypatch.setattr("eli.core.moe_offload.plan_for_load", lambda *a, **k: None)
    captured = {}

    def _fake_run(cmd, **kwargs):
        captured["payload"] = json.loads(cmd[-1])
        return _FakeCompleted()

    monkeypatch.setattr(load_probe.subprocess, "run", _fake_run)

    load_probe.probe_verdict("model.gguf", 12500, 40, 192, use_cache=False)

    assert captured["payload"]["n_gpu_layers"] == 40
    assert captured["payload"]["moe_expert_offload"] is False


def test_the_timeout_budget_is_moe_aware_not_the_full_file(monkeypatch, tmp_path):
    """probe_timeout_for() scaled the VRAM-upload rate (10s/GB) off the FULL file even under
    MoE, where only a small resident share actually touches VRAM. For a 24GB MoE model that
    overshot to ~294s uncapped and got cut at the same 180s ceiling as everything else — the
    probe_verdict() fix (above) tested the right configuration, but was still handed a budget
    computed as if it hadn't been.
    """
    big = "nemotron.gguf"

    class _FakeStat:
        st_size = int(23.93 * 1024 ** 3)

    monkeypatch.setattr(
        load_probe, "Path",
        lambda p: type("FakePath", (), {"stat": staticmethod(lambda: _FakeStat())})(),
    )
    monkeypatch.setattr(
        "eli.core.moe_offload.plan_for_load",
        lambda *a, **k: {"resident_gb": 2.39, "experts_gb": 21.54, "layers": 52},
    )
    moe_budget = load_probe.probe_timeout_for(big, 12200)
    assert moe_budget < 180.0, "a MoE-scaled budget should not need the old ceiling"
    assert not load_probe.budget_is_ceiling_cut(big, 12200)

    monkeypatch.setattr("eli.core.moe_offload.plan_for_load", lambda *a, **k: None)
    dense_budget = load_probe.probe_timeout_for(big, 12200)
    assert dense_budget == 180.0, "a genuinely dense model of the same size keeps the old ceiling"
    assert load_probe.budget_is_ceiling_cut(big, 12200)


def test_a_non_moe_typical_model_budget_is_unchanged(monkeypatch, tmp_path):
    class _FakeStat:
        st_size = int(4 * 1024 ** 3)

    monkeypatch.setattr(
        load_probe, "Path",
        lambda p: type("FakePath", (), {"stat": staticmethod(lambda: _FakeStat())})(),
    )
    monkeypatch.setattr("eli.core.moe_offload.plan_for_load", lambda *a, **k: None)
    assert round(load_probe.probe_timeout_for("typical.gguf", 8192), 3) == 86.384
