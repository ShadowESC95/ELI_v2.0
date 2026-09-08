"""Turn dossier wiring — awareness assembly, handoff injection, routing precedence."""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_static_dynamic_meta_routes_personal_memory_deep_explain():
    from eli.execution.route_contracts import classify_precedence_route

    text = (
        "are you just referring to hardcoded stubs? "
        "what about dynamic understanding of me?"
    )
    r = classify_precedence_route(text)
    assert r is not None
    assert r["action"] == "PERSONAL_MEMORY_DEEP_EXPLAIN"


def test_parse_intent_precedence_beats_phatic_for_meta_question():
    from eli.kernel.engine import CognitiveEngine

    text = (
        "hey pal, are you just referring to hardcoded stubs? "
        "what about dynamic understanding of me?"
    )
    ce = CognitiveEngine.__new__(CognitiveEngine)
    intent = ce._parse_intent(text, [])
    assert intent.get("action") == "PERSONAL_MEMORY_DEEP_EXPLAIN"
    assert (intent.get("meta") or {}).get("matched_by") == (
        "eli.route_contracts.personal_memory_deep_explain"
    )


def test_attach_dossier_sets_working_memory_context():
    from eli.cognition.turn_dossier import TurnDossier, attach_dossier_to_working_memory

    wm = MagicMock()
    dossier = TurnDossier(
        user_brief="[USER MODEL — dynamic brief]\nPrefers depth.",
        retrieval_text="[MEMORY — light recall]\n  • past note",
    )
    attach_dossier_to_working_memory(wm, dossier)
    assert getattr(wm, "turn_dossier") is dossier
    assert "Prefers depth" in getattr(wm, "dossier_context")
    assert getattr(wm, "reranked_hits") == []


def test_handoff_blocks_from_dossier_phatic_caps_and_trims_heavy_retrieval():
    from eli.cognition.turn_dossier import TurnDossier, handoff_blocks_from_dossier

    dossier = TurnDossier(
        identity_block="[USER IDENTITY — verified]\nName: Jay",
        insight_block="[BACKGROUND REFLECTION — synthesised insight]\nPattern noted.",
        retrieval_text=(
            "[MEMORY — retrieved for this turn]\n"
            + "\n".join(f"  • hit {i}" for i in range(20))
        ),
    )
    blocks = handoff_blocks_from_dossier(dossier, phatic=True, max_chars=400)
    joined = "\n".join(blocks)
    assert "Pattern noted" in joined
    assert "Name: Jay" not in joined
    assert "[MEMORY — retrieved for this turn]" not in joined
    assert len(joined) <= 420


@patch("eli.memory.retrieval.retrieve_for_turn")
@patch("eli.runtime.user_model.get_user_brief", return_value="likes thorough answers")
@patch("eli.kernel.state.get_user_name", return_value="Jay")
@patch("eli.kernel.state.get_user_profile_text", return_value="")
def test_assemble_turn_dossier_phatic_light_retrieval(_profile, _name, _brief, _retrieve):
    from eli.cognition.turn_dossier import assemble_turn_dossier

    result = MagicMock()
    result.semantic_hits = [{"text": "user prefers depth", "provenance_kind": "profile"}]
    result.conv_hits = []
    _retrieve.return_value = result

    engine = MagicMock()
    engine.memory = MagicMock()
    engine.user_id = "u1"
    engine.session_id = "s1"

    dossier = assemble_turn_dossier(
        engine,
        "hey pal, how are you?",
        query_class="PHATIC",
        user_id="u1",
        session_id="s1",
    )
    assert dossier.query_class == "PHATIC"
    assert "Jay" in dossier.identity_block
    assert "likes thorough answers" in dossier.user_brief
    assert dossier.retrieval_text
    assert "light recall" in dossier.retrieval_text.lower()
    _retrieve.assert_called_once()
    assert _retrieve.call_args.kwargs.get("semantic_limit") == 4


def test_phatic_handoff_includes_dossier_blocks():
    from unittest.mock import MagicMock

    from eli.kernel.engine import CognitiveEngine
    from eli.cognition.turn_dossier import TurnDossier

    ce = CognitiveEngine.__new__(CognitiveEngine)
    ce.memory = MagicMock()
    ce.memory.get_recent_conversation.return_value = []
    wm = MagicMock()
    wm.turn_dossier = TurnDossier(
        insight_block="[BACKGROUND REFLECTION — synthesised insight]\nCached insight here.",
        user_brief="[USER MODEL — dynamic brief]\nShould not appear in phatic handoff.",
    )
    brief = ce._build_phatic_handoff_brief("hey pal", working_memory=wm)
    assert "Cached insight here" in brief
    assert "Should not appear" not in brief
    assert "CURRENT TIME" in brief
