"""Every budget sizes against the context that loaded; "auto" is sized per model and machine.

Live 2.5.5: the user's setting asked for 12000, VRAM held by another program left room for
2048, and the fallback loaded 2048. The GUI then replaced the model's n_ctx() method with a plain
number, every llm.n_ctx() reader failed over to the requested 12000, and prompts were sized for a
window six times the real one. Elsewhere fixed numbers (16384, 12288, 8192, 4096) stood in for
the window whenever it was not at hand, and a new user's "setting" was a constant.
"""
from __future__ import annotations

import json
import pathlib

import eli.cognition.gguf_inference as G

ROOT = pathlib.Path(__file__).resolve().parents[1]


class _Loaded:
    """A llama-cpp Llama after load: n_ctx() is a method, _n_ctx and context_params hold it too."""
    def __init__(self, n):
        self._n_ctx = n
        self.context_params = type("P", (), {"n_ctx": n})()

    def n_ctx(self):
        return self._n_ctx


def test_the_loaded_window_is_read_even_when_the_method_was_overwritten(monkeypatch):
    monkeypatch.setenv("ELI_GGUF_N_CTX", "12000")              # what was asked for
    llm = _Loaded(2048)
    llm.n_ctx = 2048                                           # what the GUI used to do
    monkeypatch.setattr(G, "_model_train_ctx", lambda *a: 262144)
    monkeypatch.setattr(G, "_ELI_EFFECTIVE_RUNTIME_REPORT", {}, raising=False)
    assert G._effective_ctx_limit(llm) == 2048


def test_a_request_never_stands_in_for_the_loaded_window(monkeypatch):
    monkeypatch.setenv("ELI_GGUF_N_CTX", "12000")
    monkeypatch.setattr(G, "_model_train_ctx", lambda *a: 0)
    monkeypatch.setattr(G, "_ELI_EFFECTIVE_RUNTIME_REPORT", {}, raising=False)
    assert G._effective_ctx_limit(object()) == 0               # unknown, not 12000 and not 4096


def test_the_gui_leaves_the_models_own_n_ctx_alone():
    text = (ROOT / "eli/gui/eli_pro_audio_gui_v2_0.py").read_text(encoding="utf-8")
    assert 'setattr(self.model, "n_ctx"' not in text


def test_context_window_prefers_what_loaded_then_what_was_published(monkeypatch, tmp_path):
    monkeypatch.setattr(G, "_llm", _Loaded(6144), raising=False)
    monkeypatch.setattr(G, "_model_train_ctx", lambda *a: 0)
    monkeypatch.setattr(G, "_ELI_EFFECTIVE_RUNTIME_REPORT", {}, raising=False)
    monkeypatch.setattr(G, "_live_runtime_params", {"n_ctx": 9999, "loaded": True}, raising=False)
    assert G.context_window() == 6144
    monkeypatch.setattr(G, "_llm", None, raising=False)
    assert G.context_window() == 9999


def test_context_window_falls_back_to_the_setting_not_a_constant(monkeypatch, tmp_path):
    monkeypatch.setattr(G, "_llm", None, raising=False)
    monkeypatch.setattr(G, "_live_runtime_params", {}, raising=False)
    from eli.core import paths
    monkeypatch.setattr(paths, "get_paths", lambda: type("P", (), {"artifacts_dir": tmp_path})())
    from eli.core import config
    monkeypatch.setattr(config, "get_gguf_n_ctx", lambda: 24576)
    assert G.context_window() == 24576
    monkeypatch.setattr(config, "get_gguf_n_ctx", lambda: 0)
    assert G.context_window() == 0                             # no model to size for


def test_a_snapshot_for_another_model_is_not_this_models_window(monkeypatch, tmp_path):
    monkeypatch.setattr(G, "_llm", None, raising=False)
    monkeypatch.setattr(G, "_live_runtime_params", {}, raising=False)
    (tmp_path / "runtime_snapshot.json").write_text(
        json.dumps({"model_path": "/m/other.gguf", "effective": {"n_ctx": 32768}}), encoding="utf-8")
    from eli.core import paths, config
    monkeypatch.setattr(paths, "get_paths", lambda: type("P", (), {"artifacts_dir": tmp_path})())
    monkeypatch.setattr(G, "get_model_path", lambda: pathlib.Path("/m/this.gguf"))
    monkeypatch.setattr(config, "get_gguf_n_ctx", lambda: 8192)
    assert G.context_window() == 8192
    monkeypatch.setattr(G, "get_model_path", lambda: pathlib.Path("/m/other.gguf"))
    assert G.context_window() == 32768


# ── the setting: auto unless the operator chose a number ─────────────────────

def test_a_new_install_has_no_context_size_of_its_own():
    from eli.core.runtime_settings import DEFAULTS
    assert DEFAULTS["n_ctx"] == 0


def test_auto_is_sized_for_the_configured_model(monkeypatch):
    from eli.core import config
    import eli.core.hardware_profile as hp
    monkeypatch.delenv("ELI_GGUF_N_CTX", raising=False)
    monkeypatch.delenv("ELI_N_CTX", raising=False)
    monkeypatch.setattr(config, "get", lambda key, default=None: 0 if key == "n_ctx" else default)
    monkeypatch.setattr(config, "get_gguf_model_path", lambda: "/m/model.gguf")
    seen = []
    monkeypatch.setattr(hp, "auto_ctx_for", lambda p: seen.append(p) or 40960)
    assert config.get_gguf_n_ctx() == 40960 and seen == ["/m/model.gguf"]
    monkeypatch.setenv("ELI_GGUF_N_CTX", "6000")
    assert config.get_gguf_n_ctx() == 6000                     # the operator's number wins


def test_auto_does_not_leave_a_stale_number_in_the_environment(monkeypatch):
    from eli.core import runtime_settings
    monkeypatch.setenv("ELI_GGUF_N_CTX", "12288")
    runtime_settings.apply_env({"n_ctx": 0})
    import os
    assert "ELI_GGUF_N_CTX" not in os.environ
    runtime_settings.apply_env({"n_ctx": 10000})
    assert os.environ["ELI_GGUF_N_CTX"] == "10000"


def test_the_headless_loader_never_hands_llama_cpp_a_zero(monkeypatch):
    import eli.core.hardware_profile as hp
    monkeypatch.delenv("ELI_GGUF_N_CTX", raising=False)
    monkeypatch.setattr(hp, "auto_ctx_for", lambda p: 18432)
    assert G._requested_ctx({"n_ctx": 0}, "/m/model.gguf") == 18432
    assert G._requested_ctx({"n_ctx": 9000}, "/m/model.gguf") == 9000
    monkeypatch.setattr(hp, "auto_ctx_for", lambda p: 0)
    assert G._requested_ctx({}, "/m/model.gguf") > 0


def test_the_settings_box_offers_auto_and_no_ceiling_of_its_own():
    text = (ROOT / "eli/gui/eli_pro_audio_gui_v2_0.py").read_text(encoding="utf-8")
    assert 'self.n_ctx_input.setSpecialValueText("auto")' in text
    assert "self.n_ctx_input.setRange(512, 32768)" not in text
    assert 's.get("n_ctx", 16384)' not in text


def test_no_fixed_window_stands_in_for_the_real_one():
    stand_ins = {
        "eli/kernel/engine.py": ['getattr(self, "_n_ctx", 16384)', "return 4096\n"],
        "eli/runtime/deterministic_grounding_gate.py": ['or settings.get("context_size") or 16384'],
        "eli/execution/executor_enhanced.py": ["_n_ctx = 16384", "ctx_tokens = 4096"],
        "eli/runtime/eli_identity_audit.py": ['rt.get("n_ctx") or 16384'],
        "eli/cognition/reasoning_modes.py": ['"ctx", default=16384'],
        "eli/gui/labs_tab.py": ["n_ctx = 12288"],
        "eli/cognition/orchestrator.py": ["current_context_limit() or 8192", "min(12000,"],
        "eli/gui/eli_pro_audio_gui_v2_0.py": ['getattr(backend, "n_ctx", 4096)', "getattr(backend, 'n_ctx', 4096)",
                                              '"ELI_CTX_BRIEF_FLOOR", "12288"'],
        "eli/cognition/gguf_inference.py": ['or 32768)', "163840", '"generic-16k-'],
        "eli/core/startup_hardware_optimizer.py": ["layers_total * 1024 / 1048576.0"],
        "eli/gui/app.py": ["n_ctx = 8192", "n_ctx = 4096"],
    }
    for name, needles in stand_ins.items():
        text = (ROOT / name).read_text(encoding="utf-8")
        for needle in needles:
            assert needle not in text, f"{name} still has {needle!r}"


# ── the KV cache type that was asked for is the one that loads ───────────────

class _Llama:
    """llama-cpp-python's Llama as far as loading goes: it names its parameters, takes anything
    else in **kwargs without a word, and refuses a quantized cache without flash attention."""
    loads: list = []
    refuse_quantized = False

    def __init__(self, model_path=None, n_ctx=0, n_threads=0, n_gpu_layers=0, n_batch=0,
                 use_mmap=True, use_mlock=False, type_k=None, type_v=None, flash_attn=False,
                 verbose=False, **kwargs):
        got = dict(n_ctx=n_ctx, n_gpu_layers=n_gpu_layers, type_k=type_k, type_v=type_v,
                   flash_attn=flash_attn, swallowed=sorted(kwargs))
        type(self).loads.append(got)
        if type_v is not None and (type(self).refuse_quantized or not flash_attn):
            raise ValueError("Failed to create llama_context")
        self._n_ctx = n_ctx

    def n_ctx(self):
        return self._n_ctx


def _headless(monkeypatch, tmp_path, settings, log_lines=()):
    import sys
    import types
    from contextlib import contextmanager
    import eli.cognition.model_load_diagnostics as mld
    import eli.core.llama_cpu_compat as lcc
    _Llama.loads, _Llama.refuse_quantized = [], False
    model = tmp_path / "m.gguf"
    model.write_bytes(b"GGUF" + b"\0" * 64)
    native = types.SimpleNamespace(llama_supports_gpu_offload=lambda: False)
    monkeypatch.setitem(sys.modules, "llama_cpp", types.SimpleNamespace(Llama=_Llama, llama_cpp=native))
    monkeypatch.setenv("ELI_GGUF_SMART_FIT", "0")
    for name in ("ELI_GGUF_N_CTX", "ELI_GGUF_N_GPU_LAYERS", "ELI_GGUF_N_BATCH", "ELI_GGUF_THREADS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(G, "get_model_path", lambda: model)
    monkeypatch.setattr(G, "_load_runtime_settings", lambda: dict(settings))
    # a load leaves its facts in the module and in the runtime snapshot: every one is put back,
    # and the snapshot goes to this test's folder, so the next test finds nothing of this one
    for name in ("_llm", "_kv_cache_refused", "_live_runtime_params", "_last_params",
                 "_vram_at_load", "_last_load_error"):
        monkeypatch.setattr(G, name, {"_llm": None, "_kv_cache_refused": False}.get(name, getattr(G, name, None)),
                            raising=False)
    monkeypatch.setattr(G, "_install_llama_abort_callback", lambda llm: None)
    monkeypatch.setattr(G, "_sync_world_model_runtime", lambda payload: None)
    import eli.core.paths as paths
    real = paths.get_paths()

    class _Here:
        artifacts_dir = tmp_path

        def __getattr__(self, name):
            return getattr(real, name)

    monkeypatch.setattr(paths, "get_paths", lambda: _Here())
    monkeypatch.setattr(lcc, "preflight_runtime", lambda: None)
    monkeypatch.setattr(mld, "preflight_gguf_model", lambda p: None)
    said = list(log_lines)

    @contextmanager
    def _log():
        yield [said.pop(0)] if said else []

    monkeypatch.setattr(mld, "capture_llama_log", _log)
    return G


def test_the_headless_loader_gives_llama_cpp_the_cache_type_under_names_it_takes(monkeypatch, tmp_path):
    # q4_0 is what an earlier tuner wrote into settings; it loads as q8_0 (the measured-safe one)
    g = _headless(monkeypatch, tmp_path, {"n_ctx": 4096, "cache_type_k": "q4_0", "cache_type_v": "q4_0"},
                  ["llama_kv_cache: size = 238.00 MiB ( 4096 cells, 28 layers, 1/1 seqs), "
                   "K (q8_0): 119.00 MiB, V (q8_0): 119.00 MiB\n"])
    g.load_model(force_reload=True)
    asked = _Llama.loads[-1]
    assert (asked["type_k"], asked["type_v"], asked["flash_attn"]) == (8, 8, True)
    assert asked["swallowed"] == [], "nothing llama.cpp would take and ignore"
    assert g._live_runtime_params["cache_type_k"] == "q8_0"


def test_the_default_cache_asks_llama_cpp_for_nothing_special(monkeypatch, tmp_path):
    g = _headless(monkeypatch, tmp_path, {"n_ctx": 4096, "cache_type_k": "", "cache_type_v": ""})
    g.load_model(force_reload=True)
    asked = _Llama.loads[-1]
    assert (asked["type_k"], asked["type_v"], asked["flash_attn"]) == (None, None, False)
    assert g._live_runtime_params["cache_type_k"] == "f16"


def test_a_cache_llama_cpp_refuses_is_loaded_again_as_the_default_and_stays_that_way(monkeypatch, tmp_path):
    g = _headless(monkeypatch, tmp_path, {"n_ctx": 4096, "cache_type_k": "q4_0", "cache_type_v": "q4_0"},
                  ["llama_init_from_model: quantized V cache requires flash_attn to be enabled\n"])
    _Llama.refuse_quantized = True
    g.load_model(force_reload=True)
    loads = [l["type_v"] for l in _Llama.loads if l["n_ctx"]]      # not the header-only read
    assert loads == [8, None], "once refused, then the default"
    assert g._cache_types({"cache_type_k": "q4_0"}) == ("", ""), "every later fit is for the default too"
    assert g._live_runtime_params["cache_type_k"] == "f16"


def test_an_argument_llama_cpp_does_not_take_is_left_out_and_said(caplog):
    from eli.cognition.model_load_diagnostics import kv_cache_refused, llama_accepts
    with caplog.at_level("WARNING"):
        kept = llama_accepts(_Llama, {"model_path": "m", "n_ctx": 8, "cache_type_k": "q4_0"})
    assert kept == {"model_path": "m", "n_ctx": 8}
    assert "cache_type_k" in caplog.text
    assert kv_cache_refused(["quantized V cache requires flash_attn to be enabled\n"])
    assert not kv_cache_refused(["CUDA error: out of memory\n"])


def test_the_one_loader_uses_the_one_helper():
    """One loader (gguf_inference.load_model, from the plan's llama_kwargs) builds the cache arguments
    with gguf_sizes.llama_cache_args; the window and the launcher hand their loads to it."""
    assert "llama_cache_args" in (ROOT / "eli/core/load_plan.py").read_text(encoding="utf-8")
    for rel in ("eli/cognition/gguf_inference.py", "eli/gui/app.py", "eli/gui/eli_pro_audio_gui_v2_0.py"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert 'kwargs["cache_type_k"]' not in text and 'kwargs["cache_type_v"]' not in text, rel
    assert "cache_setting" in (ROOT / "eli/cognition/gguf_inference.py").read_text(encoding="utf-8")


def test_the_settings_page_offers_only_cache_types_that_load():
    text = (ROOT / "eli/gui/eli_pro_audio_gui_v2_0.py").read_text(encoding="utf-8")
    offered = [line for line in text.splitlines() if "cache_type_" in line and ".addItems(" in line]
    assert len(offered) == 2, offered
    for line in offered:
        assert '["", "q8_0", "f16"]' in line, line

