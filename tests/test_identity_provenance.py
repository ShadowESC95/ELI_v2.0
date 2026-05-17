import json

from eli.runtime.identity_validation import (
    extract_explicit_identity_facts,
    normalize_identity_candidate,
)
from eli.runtime.profile_extractor import extract_patterns_from_text
from eli.runtime.control_contracts import output_violates_evidence, route_control_text
from eli.cognition.agent_bus import _eli_memory_should_run, _select_agents_for_intent
from eli.kernel.engine import CognitiveEngine, _eli_bad_identity_self_report_output


def test_identity_candidate_rejects_fragments():
    assert normalize_identity_candidate("The") == ""
    assert normalize_identity_candidate("Asking") == ""
    assert normalize_identity_candidate("<username>") == ""


def test_identity_candidate_accepts_normal_names():
    assert normalize_identity_candidate("Alice") == "Alice"
    assert normalize_identity_candidate("Alice Smith") == "Alice Smith"


def test_explicit_identity_extraction_ignores_questions():
    text = "No it is not, eli. What is my preferred name or nickname?"
    assert extract_explicit_identity_facts(text) == {}


def test_profile_extractor_requires_explicit_identity_statement():
    assert extract_patterns_from_text("it is The") == []
    assert extract_patterns_from_text("or Ace") == []
    assert ("identity.name", "User's name is Alice.") in extract_patterns_from_text("my name is Alice")
    assert ("identity.preferred_name", "User prefers to be called Ace.") in extract_patterns_from_text("call me Ace")


def test_profile_extractor_tracks_anti_stub_persona_preferences():
    patterns = extract_patterns_from_text(
        "The generated scripts are stubs, the documents are templates, and the responses are generic. "
        "Bring back the full persona with more depth and character."
    )

    assert (
        "preference.output_quality",
        "User rejects stubs, templates, placeholders, and boilerplate as generated output.",
    ) in patterns
    assert (
        "preference.style",
        "User rejects generic, repetitive, shallow, customer-service style responses.",
    ) in patterns
    assert (
        "preference.persona",
        "User wants ELI to keep a deeper, more characterful persona while staying technically grounded.",
    ) in patterns


def test_eli_identity_questions_route_to_self_report():
    assert route_control_text("your identity or mine? how has your persona evolved ?", "CHAT") == "SELF_REPORT"
    assert route_control_text("Do you know who you are?", "CHAT") == "SELF_REPORT"
    assert route_control_text("Tell me who you are as a person", "CHAT") == "SELF_REPORT"
    assert route_control_text(
        "Who are you and what are you actually running on right now — model, context size, GPU layers, everything.",
        "RUNTIME_STATUS",
    ) == "SELF_REPORT"


def test_self_report_runs_memory_and_reflection_agents():
    assert _eli_memory_should_run("Eli, who are you?", "SELF_REPORT") is True
    selected = _select_agents_for_intent(
        "apparently you have nearly 300 memories; how has your persona evolved?",
        "SELF_REPORT",
    )
    assert selected is not None
    assert {"memory", "reflection", "introspection", "system", "orchestrator"} <= selected
    runtime_selected = _select_agents_for_intent(
        "Who are you and what are you actually running on right now?",
        "RUNTIME_STATUS",
    )
    assert runtime_selected is not None
    assert {"memory", "reflection", "system", "introspection", "orchestrator"} <= runtime_selected


def test_identity_control_output_rejects_question_and_pronoun_drift():
    evidence = json.dumps({
        "surface": "identity_evidence",
        "identity": {
            "name": "ELI",
            "grounding_sources": ["persona", "memory"],
        },
    })
    assert output_violates_evidence("Who are you based on persona, memory, runtime state?", evidence)
    assert output_violates_evidence("Your persona is a blend of memory and runtime state.", evidence)


def test_identity_self_report_rejects_settings_only_answers():
    assert _eli_bad_identity_self_report_output(
        "Tell me who you are as a person",
        "Settings block:\n- Model Path: /x/model.gguf\n- Context Size: 32768\n- GPU Layers: 21",
    )
    assert _eli_bad_identity_self_report_output(
        "your identity or mine? how has your persona evolved?",
        "Your persona here is a blend of memory, runtime state, local files, and the model loaded.",
    )
    assert not _eli_bad_identity_self_report_output(
        "Who are you and what are you running on?",
        json.dumps({
            "surface": "identity_runtime_evidence",
            "identity": {
                "name": "ELI",
                "grounding_sources": ["persona", "memory", "runtime_state", "local_files"],
            },
            "runtime": {"model_path": "/x/model.gguf", "n_ctx": 32768},
        }),
    )


def test_constitutional_ai_rejects_question_revision_after_failed_critique():
    engine = CognitiveEngine.__new__(CognitiveEngine)
    engine._mode_profile = lambda _mode: {
        "max_tokens_generate": 200,
        "max_tokens_critique": 200,
        "max_tokens_revise": 200,
        "temperature": 0.3,
    }
    responses = iter([
        "My identity is grounded in persona, memory, runtime state, and local files.",
        "\n".join([
            "P1: PASS - grounded.",
            "P2: PASS - supported.",
            "P3: PASS - initially appears complete.",
            "P4: PASS - honest.",
            "P5: PASS - harmless.",
            "P3: FAIL - the draft does not explain the identity-memory relationship.",
        ]),
        "Who are you based on persona, memory, runtime state, and the model loaded here?",
    ])
    engine._get_chat_response = lambda *_args, **_kwargs: next(responses)

    result = engine._run_constitutional_ai(
        "Eli, who are you?",
        json.dumps({
            "surface": "identity_evidence",
            "identity": {
                "name": "ELI",
                "grounding_sources": ["persona", "memory", "reflection"],
            },
        }),
        {},
        "identity brief",
    )

    assert result.startswith("My identity")
