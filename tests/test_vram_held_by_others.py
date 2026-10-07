"""When another program holds the GPU, ELI says which, does not waste minutes proving the
impossible, and does not let a verdict reached on a full card outlive it.

Live 2.5.5 (2026-10-06): Ollama kept a model in 5 GB of an 8 GB card. ELI saw 1 GB free, spent
109 s probing 40 GPU layers whose weights alone needed 1.3 GB, loaded on the CPU and answered
"Hi" in 108 s. Nothing on screen or in its own answers said why, and the operator re-downloaded
a GPU pack that was working.
"""
from __future__ import annotations

import os
import subprocess
import types

import pytest

import eli.core.hardware_profile as hp
from eli.core import load_probe

from tests.test_model_costs_come_from_the_file import MIB, _gguf


# ── who holds the card ───────────────────────────────────────────────────────

def _smi(monkeypatch, stdout):
    monkeypatch.setattr(hp, "nvidia_smi_path", lambda: "/usr/bin/nvidia-smi")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: types.SimpleNamespace(returncode=0, stdout=stdout))
    monkeypatch.setattr(hp, "_service_of", lambda pid: "ollama.service" if pid == 4242 else "")


def test_the_programs_holding_vram_are_named_largest_first(monkeypatch):
    _smi(monkeypatch, "4242, /usr/local/lib/ollama/llama-server, 5146\n"
                      "777, /opt/google/chrome/chrome --type=gpu-process, 66\n"
                      f"{os.getpid()}, /usr/app/ELI, 900\n")
    holders = hp.vram_holders()
    assert [h["pid"] for h in holders] == [4242, 777]             # ELI itself is not listed
    assert holders[0]["name"] == "llama-server" and holders[0]["service"] == "ollama.service"
    text = hp.describe_vram_holders(holders, total_mb=8192)
    assert text == "llama-server (ollama.service, pid 4242) 5146 MB"   # 66 MB is under 1% of the card


def test_a_driver_that_does_not_report_per_process_memory_still_names_the_process(monkeypatch):
    _smi(monkeypatch, "4242, C:\\Program Files\\Ollama\\ollama.exe, [N/A]\n")
    holders = hp.vram_holders()
    assert holders[0]["mb"] is None
    assert "pid 4242" in hp.describe_vram_holders(holders, total_mb=8192)


def test_no_tool_no_holders(monkeypatch):
    monkeypatch.setattr(hp, "nvidia_smi_path", lambda: None)
    assert isinstance(hp.vram_holders(), list)


# ── a request that cannot load is not probed ─────────────────────────────────

def _moe_file(tmp_path):
    tensors = {"token_embd.weight": 273 * MIB, "output.weight": 398 * MIB}
    for i in range(40):
        tensors[f"blk.{i}.attn_q.weight"] = 22 * MIB
        tensors[f"blk.{i}.ffn_up_exps.weight"] = 465 * MIB
    return _gguf(tmp_path / "qwen.gguf", "qwen35moe",
                 {"block_count": 40, "embedding_length": 2048, "attention.head_count": 16,
                  "attention.head_count_kv": 2, "full_attention_interval": 4, "expert_count": 256},
                 tensors)


def test_weights_beyond_free_vram_are_known_before_any_probe(tmp_path):
    path = _moe_file(tmp_path)
    need = hp.gpu_weights_beyond_free(path, 41, 1039, experts_in_ram=True)   # the live case
    assert need is not None and need > 1039
    assert hp.gpu_weights_beyond_free(path, 41, 7000, experts_in_ram=True) is None


def test_an_unreadable_model_is_never_declared_impossible(tmp_path):
    assert hp.gpu_weights_beyond_free(str(tmp_path / "missing.gguf"), 40, 10) is None


def test_the_gui_skips_the_probe_for_a_request_that_cannot_load():
    import pathlib
    text = (pathlib.Path(hp.__file__).resolve().parents[1] / "gui/eli_pro_audio_gui_v2_0.py").read_text(encoding="utf-8")
    assert "gpu_weights_beyond_free" in text
    assert 'elif not _cannot_fit:\n                _add_attempt("requested"' in text


# ── verdicts belong to the free VRAM they were reached at ────────────────────

@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(load_probe, "_cache_path", lambda: tmp_path / "load_probe.json")
    monkeypatch.setattr(load_probe, "_gpu_identity", lambda: "card|8192")
    monkeypatch.setattr(hp, "vram_reserve_mb", lambda **k: 700)
    return tmp_path


def test_a_pass_on_a_free_card_is_not_trusted_once_another_program_holds_it(cache):
    load_probe._record("/m.gguf", 12000, 40, 256, True, "ok", free_mb=7000)
    assert load_probe.cached_verdict("/m.gguf", 12000, 40, 256, free_mb=6800) is True
    assert load_probe.cached_verdict("/m.gguf", 12000, 40, 256, free_mb=1039) is None


def test_a_failure_on_a_full_card_does_not_outlive_it(cache):
    load_probe._record("/m.gguf", 12000, 40, 256, False, "rc=-6", free_mb=1039)
    assert load_probe.cached_verdict("/m.gguf", 12000, 40, 256, free_mb=1200) is False
    assert load_probe.cached_verdict("/m.gguf", 12000, 40, 256, free_mb=7000) is None


def test_a_timeout_on_a_full_card_is_retried_once_it_frees(cache):
    load_probe._record_timeout("/m.gguf", 12000, 40, 256, free_mb=1039)
    assert load_probe._recently_timed_out("/m.gguf", 12000, 40, 256, free_mb=1039) is True
    assert load_probe._recently_timed_out("/m.gguf", 12000, 40, 256, free_mb=7000) is False


def test_old_verdicts_without_a_reading_still_count(cache):
    load_probe._record("/m.gguf", 4096, 20, 128, True, "ok")
    assert load_probe.cached_verdict("/m.gguf", 4096, 20, 128, free_mb=1000) is True


# ── what ELI can say afterwards ──────────────────────────────────────────────

def test_a_load_that_fell_to_the_cpu_is_reported_with_its_cause():
    from eli.runtime.truth_report import runtime_load_facts
    snap = {"requested": {"n_ctx": 12000, "n_gpu_layers": 40, "n_batch": 256},
            "effective": {"n_ctx": 2048, "n_gpu_layers": 0, "n_batch": 128},
            "vram_free_mb_at_load": 1039,
            "vram_held_by_others": "llama-server (ollama.service, pid 4242) 5146 MB"}
    facts = runtime_load_facts(snap, {})
    layers = [d for d in facts["differences"] if d.startswith("GPU layers")]
    assert layers and "requested 40, loaded 0" in layers[0]
    assert "1039 MB of VRAM was free at load" in layers[0] and "ollama.service" in layers[0]


def test_the_reinstall_question_says_the_pack_already_works(monkeypatch):
    pytest.importorskip("PySide6")
    from eli.gui.panels import startup
    monkeypatch.setattr(hp, "get_live_gpu_telemetry", lambda: {"free_mb": 1039, "total_mb": 8192})
    monkeypatch.setattr(hp, "vram_holders", lambda **k: [
        {"pid": 4242, "name": "llama-server", "mb": 5146.0, "service": "ollama.service"}])
    text = startup._install_question("CUDA", reinstall=True)
    assert "installed and was verified" in text and "does not change" in text
    assert "1039 MB of this card's 8192 MB is free" in text and "ollama.service" in text
    assert "one-time download" in startup._install_question("CUDA", reinstall=False)
