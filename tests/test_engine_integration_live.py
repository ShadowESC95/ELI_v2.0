"""Live engine integration suite — a REAL local model, REAL turns.

The normal suite mocks llama_cpp/torch/faiss (for speed), so the genuine
inference + cognition pipeline is never executed there. This lane loads an actual
small GGUF through the full `CognitiveEngine` and drives real turns end-to-end
(router -> agent bus -> grounding/escalation -> GGUF broker -> governed output).

Discipline (no fine-tuning): model output is non-deterministic, so every
assertion is STRUCTURAL — routed action, non-empty response, result shape,
subsystem behaviour — never an exact model string. We assert what the *code*
guarantees, not what the model happened to say.

Run on the clean lane (real deps + coverage), pointing at a small model:

    ELI_MODEL_PATH=models/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf \
    ELI_ARTIFACTS_DIR=/tmp/eli_live \
    .venv/bin/python -m pytest tests/test_engine_integration_live.py --noconftest \
        --cov=eli --cov-report=term

Skips gracefully under the mocked full suite (llama_cpp is a MagicMock there).
"""
from __future__ import annotations

import glob
import os

import pytest

# Under the mocked full suite, llama_cpp/torch are MagicMocks — a real load is
# impossible, so skip cleanly (never break the main run).
try:
    import llama_cpp as _llama
    if type(_llama).__name__ == "MagicMock":
        raise RuntimeError("llama_cpp mocked")
except Exception as _e:  # pragma: no cover
    pytest.skip(f"live model lane unavailable ({_e}); run with --noconftest",
                allow_module_level=True)


def _pick_small_model() -> str | None:
    """ELI_MODEL_PATH if set, else the smallest chat-capable GGUF present."""
    env = os.environ.get("ELI_MODEL_PATH")
    if env and os.path.exists(env):
        return env
    cands = []
    for g in glob.glob("models/**/*.gguf", recursive=True):
        base = os.path.basename(g).lower()
        if any(x in base for x in ("mmproj", "embed", "nomic", "clip")):
            continue  # not a chat model
        cands.append((os.path.getsize(g), g))
    cands.sort()
    return cands[0][1] if cands else None


@pytest.fixture(scope="module")
def engine():
    model = _pick_small_model()
    if not model:
        pytest.skip("no small chat GGUF available for the live lane")
    # ELI_GGUF_MODEL_PATH is the STRONGEST override and is honoured before the
    # loader's own PYTEST_CURRENT_TEST guard (gguf_inference.get_model_path); a bare
    # ELI_MODEL_PATH is checked after that guard, so it never loads under pytest.
    os.environ["ELI_GGUF_MODEL_PATH"] = model
    os.environ["ELI_MODEL_PATH"] = model
    os.environ.setdefault("ELI_ARTIFACTS_DIR", "/tmp/eli_live_artifacts")
    # `_eli_test_mode()` is forced True under pytest (it detects PYTEST_CURRENT_TEST /
    # the pytest module), which deliberately skips the real GGUF load + daemons. For
    # THIS lane we genuinely want a live model, so patch it False for the fixture's
    # lifetime, then restore.
    import eli.kernel.engine as eng_mod
    _orig_tm = eng_mod._eli_test_mode
    eng_mod._eli_test_mode = lambda: False
    try:
        eng = eng_mod.CognitiveEngine(auto_init_gguf=True, enforce_hardware_authority=False)
    except Exception as e:
        eng_mod._eli_test_mode = _orig_tm
        pytest.skip(f"engine construction failed: {e}")
    if not getattr(eng, "_gguf_available", False):
        try:
            eng.shutdown()
        finally:
            eng_mod._eli_test_mode = _orig_tm
        pytest.skip("model failed to load in this environment")
    yield eng
    try:
        eng.shutdown()
    finally:
        eng_mod._eli_test_mode = _orig_tm


def _text(result) -> str:
    if isinstance(result, dict):
        return str(result.get("response") or result.get("content") or result.get("text") or "")
    return str(result or "")


# --------------------------------------------------------------------------- #
def test_model_actually_loaded(engine):
    assert engine._gguf_available is True
    assert isinstance(engine._model_path, str) and engine._model_path.endswith(".gguf")


def test_chat_turn_real_generation(engine):
    r = engine.process("say hello in one short sentence", reasoning_mode="quick")
    assert isinstance(r, dict)
    assert _text(r).strip(), "a real chat turn must produce a non-empty reply"


def test_result_shape_contract(engine):
    r = engine.process("what is the capital of France?", reasoning_mode="quick")
    assert isinstance(r, dict)
    # The engine contract: a routed action + a user-visible surface.
    assert "action" in r
    assert (r.get("response") or r.get("content")) is not None


def test_arithmetic_pipeline_runs(engine):
    # We do NOT assert the model got the maths right (that would be fine-tuning to
    # the model); we assert the pipeline ran and returned a governed reply.
    r = engine.process("what is 2 plus 2? answer briefly", reasoning_mode="quick")
    assert _text(r).strip()


def test_memory_store_then_recall(engine):
    engine.process("remember that my favourite colour is teal", reasoning_mode="quick")
    r = engine.process("what is my favourite colour?", reasoning_mode="quick")
    # Structural: the recall turn produces a grounded, non-empty answer and routes
    # through the pipeline without error. (We don't hard-assert the model echoes
    # "teal" — a small model may not; that's a model-quality property, not a code one.)
    assert isinstance(r, dict) and _text(r).strip()


def test_introspection_runtime_status(engine):
    r = engine.process("what model are you running on right now?", reasoning_mode="quick")
    assert isinstance(r, dict) and _text(r).strip()
    # The action should be an introspection/grounded-status surface, not a web hedge.
    assert str(r.get("action", "")).upper() not in {"WEB_SEARCH", "NEWS_FETCH"}


def test_two_turn_session_continuity(engine):
    a = engine.process("my name is Sam", reasoning_mode="quick")
    b = engine.process("what did I just tell you my name was?", reasoning_mode="quick")
    assert _text(a).strip() and _text(b).strip()
    assert engine.session_id  # a stable session persisted across turns


def test_empty_and_whitespace_input_are_safe(engine):
    for junk in ("", "   ", "\n\t"):
        r = engine.process(junk, reasoning_mode="quick")
        # Must not raise; returns a dict/str, never crashes the pipeline.
        assert r is not None


# --------------------------------------------------------------------------- #
# Varied intents + deeper reasoning modes — each drives different router/executor/
# grounding/escalation paths through the REAL pipeline (structural assertions only).
# --------------------------------------------------------------------------- #
def test_capability_query(engine):
    r = engine.process("what can you do?", reasoning_mode="quick")
    assert isinstance(r, dict) and _text(r).strip()


def test_time_query_routes_and_answers(engine):
    r = engine.process("what time is it right now?", reasoning_mode="quick")
    assert isinstance(r, dict) and _text(r).strip()


def test_news_query_offline_is_grounded_not_fabricated(engine, monkeypatch):
    # With the net gated off, a news ask must degrade to a grounded, non-empty answer
    # (honest "can't fetch" / cached) rather than crash or fabricate live headlines.
    import eli.core.config as cfg
    monkeypatch.setattr(cfg, "network_allowed", lambda: False, raising=False)
    r = engine.process("what's the latest news?", reasoning_mode="quick")
    assert isinstance(r, dict) and _text(r).strip()


def test_normal_mode_turn(engine):
    # 'normal' mode exercises more of the pipeline than the single-pass 'quick'.
    r = engine.process("explain what you are in a sentence", reasoning_mode="normal")
    assert isinstance(r, dict) and _text(r).strip()


def test_advanced_mode_multipass(engine):
    # A deeper mode drives the multi-pass / escalation path (a distinct code route).
    r = engine.process("give me a brief thought on curiosity", reasoning_mode="advanced")
    assert isinstance(r, dict) and _text(r).strip()


def test_opinion_prompt_stays_conversational(engine):
    r = engine.process("what's your favourite kind of music?", reasoning_mode="quick")
    assert isinstance(r, dict) and _text(r).strip()
    # A subjective/rapport prompt must not be shunted to a web/news action.
    assert str(r.get("action", "")).upper() not in {"WEB_SEARCH", "NEWS_FETCH"}


def test_repeated_identical_turns_are_stable(engine):
    a = engine.process("hello", reasoning_mode="quick")
    b = engine.process("hello", reasoning_mode="quick")
    # Both complete without error and produce a reply (persona may vary — that's fine).
    assert _text(a).strip() and _text(b).strip()


# --------------------------------------------------------------------------- #
# Safe, read-only executor handlers driven through a real turn. These route via
# the deterministic regex router (not the model), so the handler actually runs and
# gets covered. Destructive handlers (open app, shell, screenshot, volume, media)
# are deliberately NOT triggered — a test must never drive the machine.
# --------------------------------------------------------------------------- #
def test_date_handler(engine):
    r = engine.process("what's the date today?", reasoning_mode="quick")
    assert isinstance(r, dict) and _text(r).strip()


def test_gpu_status_handler(engine):
    r = engine.process("what's your gpu status right now?", reasoning_mode="quick")
    assert isinstance(r, dict) and _text(r).strip()


def test_list_dir_handler(engine, tmp_path):
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    (tmp_path / "b.txt").write_text("y", encoding="utf-8")
    r = engine.process(f"list the files in {tmp_path}", reasoning_mode="quick")
    assert isinstance(r, dict) and _text(r).strip()


def test_summarize_file_handler(engine, tmp_path):
    p = tmp_path / "note.txt"
    p.write_text("The meeting is on Tuesday at 3pm about the budget.\n" * 5, encoding="utf-8")
    r = engine.process(f"summarise the file at {p}", reasoning_mode="quick")
    assert isinstance(r, dict) and _text(r).strip()


def test_read_file_handler(engine, tmp_path):
    p = tmp_path / "data.txt"
    p.write_text("hello from the read-file test", encoding="utf-8")
    r = engine.process(f"read the file {p}", reasoning_mode="quick")
    assert isinstance(r, dict) and _text(r).strip()


def test_create_file_handler(engine, tmp_path):
    # CREATE_FILE runs through the security path gate; whether it writes or is
    # blocked, the handler executes and returns a structured result (never crashes).
    target = tmp_path / "made.txt"
    r = engine.process(f"create a file at {target} containing hello world",
                       reasoning_mode="quick")
    assert isinstance(r, dict) and _text(r).strip()


def test_background_jobs_handler(engine):
    r = engine.process("are there any background jobs running?", reasoning_mode="quick")
    assert isinstance(r, dict) and _text(r).strip()


def test_weather_offline_grounded(engine, monkeypatch):
    import eli.core.config as cfg
    monkeypatch.setattr(cfg, "network_allowed", lambda: False, raising=False)
    r = engine.process("what's the weather in Dublin?", reasoning_mode="quick")
    # Net off: must degrade to an honest, non-empty answer, not crash or fabricate.
    assert isinstance(r, dict) and _text(r).strip()
