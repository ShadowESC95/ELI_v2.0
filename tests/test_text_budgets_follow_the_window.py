"""Prompt and text budgets follow the window that loaded, and whisper's GPU use follows the card.

Each of these was a fixed size tuned for one window: a 12000-character persona valve, a compact
switch at 8192/12288 tokens, evidence blocks "sized for a 16384-ctx model", a 12000-character
PDF and code window, a 4096-token answer cap. Too big for a 2k model, a sliver of a 128k one.
"""
from __future__ import annotations

import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _engine(monkeypatch, window):
    from eli.kernel import engine as E
    eng = E.CognitiveEngine.__new__(E.CognitiveEngine)
    monkeypatch.setattr(E.CognitiveEngine, "_runtime_n_ctx", lambda self: window)
    monkeypatch.setattr(E.CognitiveEngine, "_generation_settings", lambda self: {"max_tokens": 512})
    from eli.cognition import context_budget
    monkeypatch.setattr(context_budget, "chars_per_token", lambda: 4.0)
    return E, eng


def test_the_persona_is_trimmed_to_its_share_of_the_window(monkeypatch):
    E, eng = _engine(monkeypatch, 4096)
    monkeypatch.setattr(E, "_load_persona_text", lambda: "x" * 20000)
    small = eng._compact_persona()
    E2, eng2 = _engine(monkeypatch, 131072)
    big = eng2._compact_persona()
    assert len(small) < 20000 <= len(big)


def test_compact_prompt_is_chosen_by_fit_not_by_window_size(monkeypatch):
    E, eng = _engine(monkeypatch, 4096)
    monkeypatch.setattr(E, "_load_persona_text", lambda: "x" * 30000)       # 7500 tokens
    assert eng._use_compact_system("hello there", "", "chain_of_thought") is True
    E, eng = _engine(monkeypatch, 65536)
    monkeypatch.setattr(E, "_load_persona_text", lambda: "x" * 30000)
    assert eng._use_compact_system("a long and careful question " * 3, "", "chain_of_thought") is False


def test_evidence_budgets_scale_with_the_window():
    text = (ROOT / "eli/kernel/engine.py").read_text(encoding="utf-8")
    body = text[text.index("    def _build_evidence_prompt"):][:1500]
    assert "BUDGET_SNIPPETS = 2048" not in body and "_win * " in body


def test_code_review_windows_are_half_the_loaded_window(monkeypatch):
    from eli.runtime import code_examiner, runtime_policy
    from eli.cognition import context_budget
    monkeypatch.setattr(context_budget, "chars_per_token", lambda: 4.0)
    monkeypatch.setattr(runtime_policy, "context_size", lambda default=0: 8192)
    assert code_examiner._max_file_chars() == 16384
    monkeypatch.setattr(runtime_policy, "context_size", lambda default=0: 0)
    assert code_examiner._max_file_chars() > 10 ** 12          # no window, nothing to cut to


def test_the_mode_evidence_table_scales_with_the_window(monkeypatch):
    from eli.cognition import context_synthesiser as cs
    from eli.runtime import runtime_policy
    monkeypatch.setattr(runtime_policy, "context_size", lambda default=0: runtime_policy._BUDGET_REFERENCE_CTX * 4)
    big = cs._handoff_budgets("tree_of_thoughts")
    monkeypatch.setattr(runtime_policy, "context_size", lambda default=0: runtime_policy._BUDGET_REFERENCE_CTX // 4)
    small = cs._handoff_budgets("tree_of_thoughts")
    assert big["grounded_max_chars"] == 16 * small["grounded_max_chars"]
    assert big["grounded_max_lines"] == small["grounded_max_lines"]    # counts are not sizes


def test_answers_are_capped_by_the_window_only():
    from eli.core.startup_hardware_optimizer import max_tokens_from_ctx
    assert max_tokens_from_ctx(262144) == 131072
    assert max_tokens_from_ctx(2048) == 1024


def test_timeouts_grow_with_the_window_without_steps(monkeypatch):
    from eli.runtime import runtime_policy
    times = []
    for ctx in (8192, 16384, 32768, 131072):
        monkeypatch.setattr(runtime_policy, "context_size", lambda default=0, c=ctx: c)
        times.append(runtime_policy.timeout("x", 10.0))
    assert times[0] == 10.0 and times[1] == pytest.approx(12.5) and times[2] == pytest.approx(15.0)
    assert times[3] > times[2]


# ── whisper takes the GPU only when there is measured room ──────────────────

def test_whisper_stays_off_the_gpu_when_the_language_model_needs_it(monkeypatch, tmp_path):
    import sys
    from eli.perception import local_whisper_stt as w
    import eli.core.hardware_profile as hp
    from tests.test_model_costs_come_from_the_file import _dense
    model = _dense(tmp_path, blocks=32, block_mib=200, embd_mib=500)        # ~6.9 GB on the GPU
    monkeypatch.setattr(w, "_gpu_total_mb", lambda: 12288)
    monkeypatch.setattr(w, "_whisper_weights_mb", lambda m, d: 461.0)
    monkeypatch.setattr(hp, "vram_reserve_mb", lambda **k: 700)
    from eli.core import config
    monkeypatch.setattr(config, "get_gguf_model_path", lambda: model)
    monkeypatch.setattr(config, "get_gguf_n_ctx", lambda: 4096)
    monkeypatch.setitem(sys.modules, "eli.cognition.gguf_inference", None)
    monkeypatch.setattr(hp, "get_live_gpu_telemetry", lambda: {"free_mb": 8000})
    assert w._gpu_room_for_whisper("small.en", str(tmp_path)) is False    # a 12 GB card, no room
    monkeypatch.setattr(hp, "get_live_gpu_telemetry", lambda: {"free_mb": 11500})
    assert w._gpu_room_for_whisper("small.en", str(tmp_path)) is True


def test_whisper_is_never_put_on_the_gpu_on_a_guess(monkeypatch, tmp_path):
    from eli.perception import local_whisper_stt as w
    monkeypatch.setattr(w, "_gpu_total_mb", lambda: 24576)
    monkeypatch.setattr(w, "_whisper_weights_mb", lambda m, d: 0.0)         # not downloaded
    assert w._gpu_room_for_whisper("small.en", str(tmp_path)) is False


def test_none_of_the_fixed_sizes_came_back():
    needles = {
        "eli/kernel/engine.py": ["persona[:12000]", "ctx_window <= 8192", "ctx_window <= 12288",
                                 "BUDGET_SNIPPETS = 2048", "(_nctx - 6600)", "+ 12000\n"],
        "eli/runtime/code_examiner.py": ["MAX_FILE_CHARS = 12000"],
        "eli/execution/executor_enhanced.py": ["_body[:12000]"],
        "eli/perception/local_whisper_stt.py": ['"ELI_WHISPER_GPU_MIN_MB", "12000"'],
        "eli/gui/eli_pro_audio_gui_v2_0.py": ["self._n_ctx <= 8192", "min(131072, int(ram_gb * 1024))",
                                              "max_tokens_input.setRange(128, 4096)"],
        "eli/core/startup_hardware_optimizer.py": ["min(8192, n_ctx // 2)", "min(131072, int(net_gb * 1024))"],
        "eli/core/dynamic_runtime_budget.py": ["[2048, 4096, 6144, 8192, 12288, 16384, 24576, 32768]"],
        "eli/runtime/runtime_policy.py": ["min(4.0, ctx / 8192.0)", "if ctx >= 32768"],
        "eli/memory/vector_store.py": ["n_ctx=2048,"],
    }
    for name, items in needles.items():
        text = (ROOT / name).read_text(encoding="utf-8")
        for needle in items:
            assert needle not in text, f"{name} still has {needle!r}"
