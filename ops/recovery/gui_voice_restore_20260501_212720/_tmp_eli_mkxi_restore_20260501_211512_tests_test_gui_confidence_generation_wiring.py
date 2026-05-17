from pathlib import Path


def test_quick_mode_clarifies_when_below_confidence_threshold():
    from eli.kernel.engine import CognitiveEngine

    engine = object.__new__(CognitiveEngine)
    profile = engine._mode_profile("quick")

    assert profile["clarify"] is True


def test_dynamic_clarifier_returns_question_from_model_path():
    from eli.kernel.engine import CognitiveEngine

    engine = object.__new__(CognitiveEngine)
    engine._get_chat_response = lambda *args, **kwargs: "Which file should I inspect first?"

    text = engine._clarifying_response(
        "audit the broken GUI wiring",
        0.31,
        0.64,
        memory_context="GUI context missing exact callback target",
    )

    assert text == "Which file should I inspect first?"


def test_engine_ask_uses_cognitive_engine_dict_response():
    source = Path("eli/gui/eli_pro_audio_gui_MKI.py").read_text(encoding="utf-8")
    engine_ask = source[source.index("    def _engine_ask("):source.index("    def create_labs_tab(")]

    assert "if isinstance(result, dict):" in engine_ask
    assert 'result.get("response")' in engine_ask
    assert "backend.chat" in engine_ask
    assert engine_ask.index("if isinstance(result, dict):") < engine_ask.index("backend.chat")


def test_gui_preloaded_handoff_reads_preloaded_params():
    source = Path("eli/gui/eli_pro_audio_gui_MKI.py").read_text(encoding="utf-8")
    handoff = source[source.index("_PRELOADED_PARAMS"):source.index("QTimer.singleShot(600")]

    assert "_pre_params" in handoff
    assert "for _src in (_pre_params, locals())" in handoff
    assert '"model_path"' in handoff
    assert '"batch_size"' in handoff


def test_runtime_status_context_allows_followup_when_evidence_missing():
    from eli.cognition.context_synthesiser import build_persona_handoff

    packet = build_persona_handoff(
        "runtime status",
        intent={"action": "RUNTIME_STATUS"},
        orchestrator_result={},
    )
    context = packet["assembled_context"].lower()

    assert "do not ask the user a follow-up question" not in context
    assert "ask the narrowest follow-up" in context


def test_create_document_test_mode_uses_document_artifacts(monkeypatch):
    from eli.execution import executor_enhanced as ex

    monkeypatch.setenv("ELI_TEST_MODE", "1")

    result = ex.execute("CREATE_DOCUMENT", {"topic": "runtime audit report", "format": "txt"})

    assert result["ok"] is True
    path = Path(result["doc_path"])
    assert path.exists()
    assert "artifacts/documents" in result["doc_path"]
    assert "artifacts/scripts" not in result["doc_path"]
    assert "This is a generated text document" not in result["content"]


def test_generate_script_rejects_invalid_python(monkeypatch):
    from eli.cognition import gguf_inference
    from eli.execution import executor_enhanced as ex

    monkeypatch.setattr(gguf_inference, "load_model", lambda: None)
    monkeypatch.setattr(ex, "chat", lambda *args, **kwargs: {"content": "def broken(:\n    pass"})

    result = ex.execute("GENERATE_SCRIPT", {"description": "write a python script to print hello"})

    assert result["ok"] is False
    assert "syntax validation" in result["error"]
