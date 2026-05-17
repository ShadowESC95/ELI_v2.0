import json
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


def test_create_document_test_mode_uses_document_artifacts(monkeypatch, tmp_path):
    from eli.execution import executor_enhanced as ex

    monkeypatch.setenv("ELI_TEST_MODE", "1")
    monkeypatch.setenv("ELI_ARTIFACTS_DIR", str(tmp_path / "artifacts"))

    result = ex.execute("CREATE_DOCUMENT", {"topic": "runtime audit report", "format": "txt"})

    assert result["ok"] is True
    path = Path(result["doc_path"])
    assert path.exists()
    assert "artifacts/documents" in result["doc_path"]
    assert "artifacts/scripts" not in result["doc_path"]
    assert "This is a generated text document" not in result["content"]
    body = path.read_text(encoding="utf-8")
    assert "Generated in ELI_TEST_MODE" not in body
    assert "Requested topic:" not in body
    assert "Generation Contract" in body


def test_generate_script_rejects_invalid_python(monkeypatch):
    from eli.cognition import gguf_inference
    from eli.execution import executor_enhanced as ex

    monkeypatch.setattr(gguf_inference, "load_model", lambda: None)
    monkeypatch.setattr(ex, "chat", lambda *args, **kwargs: {"content": "def broken(:\n    pass"})

    result = ex.execute("GENERATE_SCRIPT", {"description": "write a python script to print hello"})

    assert result["ok"] is False
    assert "syntax validation" in result["error"]


def test_generate_script_rejects_stub_markers(monkeypatch):
    from eli.execution import executor_enhanced as ex

    monkeypatch.setattr(
        ex,
        "chat",
        lambda *args, **kwargs: {"content": "def generated():\n    # TODO: Add code here\n    pass\n"},
    )

    result = ex.execute("GENERATE_SCRIPT", {"description": "write a python script to print hello"})

    assert result["ok"] is False
    assert "stub/template markers" in result["error"]


def test_generate_script_chat_backend_skips_router(monkeypatch, tmp_path):
    from eli.cognition import gguf_inference
    from eli.execution import executor_enhanced as ex

    calls = []

    monkeypatch.setenv("ELI_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setattr(gguf_inference, "load_model", lambda: None)

    def fake_chat(*args, **kwargs):
        calls.append(kwargs)
        return {"content": "print('hello')"}

    monkeypatch.setattr(ex, "chat", fake_chat)

    result = ex.execute("GENERATE_SCRIPT", {"description": "write a python script to print hello"})

    assert result["ok"] is True
    assert calls
    assert calls[0].get("skip_router") is True


def test_relative_time_function_generation_is_deterministic():
    from datetime import datetime
    from eli.execution import executor_enhanced as ex

    result = ex.execute(
        "GENERATE_SCRIPT",
        {
            "description": (
                "Write a Python function that takes a unix timestamp float and "
                'returns a human-readable relative time string ("3 hours ago", '
                '"yesterday at 14:30", etc).'
            ),
            "language": "python",
        },
    )

    assert result["ok"] is True
    path = Path(result["path"])
    namespace = {}
    exec(path.read_text(encoding="utf-8"), namespace)
    relative_time = namespace["relative_time"]
    now = datetime(2026, 5, 5, 21, 0)

    assert relative_time(datetime(2026, 5, 5, 18, 0).timestamp(), now=now) == "3 hours ago"
    assert relative_time(datetime(2026, 5, 4, 14, 30).timestamp(), now=now) == "yesterday at 14:30"


def test_script_language_inference_ignores_in_an_ide_tail():
    from eli.execution.portable_intent_contract import infer_script_language

    text = (
        "create a python script for the following; A quantum system has "
        "decoherence time T2 = 100us and gate time tg = 50ns. "
        "why did you not open the previous script in an IDE default?"
    )

    assert infer_script_language(text) == "python"


def test_generation_complaints_are_not_routed_as_new_scripts():
    from eli.execution.portable_intent_contract import try_route

    assert try_route("You did not generate that script, your code generation agent never ran.") is None


def test_type_ia_supernova_redshift_generation_is_deterministic():
    from eli.execution import executor_enhanced as ex

    result = ex.execute(
        "GENERATE_SCRIPT",
        {
            "description": "write a python script to calculate the redshift of a supernova typa 1a",
            "language": "python",
        },
    )

    assert result["ok"] is True
    assert result["language"] == "python"
    assert result["open_in_labs"] is True
    assert result["open_in_ide"] is True
    path = Path(result["path"])
    namespace = {}
    exec(path.read_text(encoding="utf-8"), namespace)

    z = namespace["redshift_from_wavelength"](7626.0, 6355.0)
    assert round(z, 6) == 0.200000
    assert namespace["luminosity_distance_mpc_from_modulus"](35.0) == 100.0


def test_quantum_decoherence_depth_generation_is_deterministic():
    from eli.execution import executor_enhanced as ex

    result = ex.execute(
        "GENERATE_SCRIPT",
        {
            "description": (
                "create a python script for the following; A quantum system has "
                "decoherence time T2 = 100us and gate time tg = 50ns. What's "
                "the maximum circuit depth before fidelity drops below 99%? Show the calculation."
            ),
            "language": "an",
        },
    )

    assert result["ok"] is True
    assert result["language"] == "python"
    assert result["open_in_labs"] is True
    assert result["open_in_ide"] is True
    path = Path(result["path"])
    namespace = {}
    exec(path.read_text(encoding="utf-8"), namespace)

    continuous, depth = namespace["max_depth_exponential"](100e-6, 50e-9, 0.99)
    assert round(continuous, 6) == 20.100672
    assert depth == 20
    assert namespace["fidelity_after_depth"](20, 100e-6, 50e-9) >= 0.99
    assert namespace["fidelity_after_depth"](21, 100e-6, 50e-9) < 0.99


def test_ton_618_mass_density_generation_is_deterministic():
    from eli.execution import executor_enhanced as ex

    result = ex.execute(
        "GENERATE_SCRIPT",
        {
            "description": (
                "create a python script to generate the mass and density on "
                "ton 618 against earths mass and density"
            ),
            "language": "python",
        },
    )

    assert result["ok"] is True
    assert result["language"] == "python"
    assert result["open_in_labs"] is True
    assert result["open_in_ide"] is True
    path = Path(result["path"])
    namespace = {}
    exec(path.read_text(encoding="utf-8"), namespace)

    comparison = namespace["compare_ton_618"]()
    assert comparison.mass_earth_masses > 1e16
    assert comparison.density_earth_ratio < 1e-5
    assert namespace["EARTH_RADIUS_M"] > 6_000_000


def test_generate_document_normalizes_to_documents_dir(monkeypatch, tmp_path):
    from eli.runtime.generated_script_guard import _normalise_document_result

    monkeypatch.setenv("ELI_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    scripts_dir = tmp_path / "artifacts" / "scripts"
    scripts_dir.mkdir(parents=True)
    script_doc = scripts_dir / "regression_document_path_probe.md"
    script_doc.write_text(
        "# Probe\n\n"
        "This regression document has enough body text to prove the normalizer moves real "
        "document content out of the scripts directory without accepting old status-message "
        "or placeholder artifacts. It is intentionally substantive so the anti-stub guard "
        "does not mistake it for a generated skeleton.\n",
        encoding="utf-8",
    )

    result = _normalise_document_result(
        {
            "ok": True,
            "action": "GENERATE_DOCUMENT",
            "doc_path": str(script_doc),
            "content": "# Probe\n\nBody",
            "response": "raw doc",
        },
        {"topic": "Regression Document Path Probe", "format": "md"},
        "GENERATE_DOCUMENT",
    )

    assert result["ok"] is True
    assert str(tmp_path / "artifacts" / "documents") in result["doc_path"]
    assert "/scripts/" not in result["doc_path"]
    payload = json.loads(result["content"])
    assert payload["event"] == "artifact_generated"
    assert payload["kind"] == "document"
    assert result["doc_path"] == payload["path"]


def test_gui_has_generated_artifact_open_signal_and_handlers():
    source = Path("eli/gui/eli_pro_audio_gui_MKI.py").read_text(encoding="utf-8")

    assert "_generated_artifact_open_sig = pyqtSignal(object)" in source
    assert "_open_generated_artifact_from_result" in source
    assert "_load_path_into_labs_sim_ide" in source
    assert "self._generated_artifact_open_sig.emit(dict(result))" in source
