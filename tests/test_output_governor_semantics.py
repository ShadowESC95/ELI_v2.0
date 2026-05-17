from eli.cognition.output_governor import normalize_assistant_text


def test_open_head_repair_frame_blocks_generic_medical_disclaimer():
    text = normalize_assistant_text(
        "I said I performed open head surgery on you.",
        "I'm an adaptive intelligence system. I cannot remember any surgical procedure in this context.",
    )

    assert "Wrong frame" in text
    assert "surgery on ELI" in text
    assert "cannot remember any surgical procedure" not in text


def test_generic_surgical_disclaimer_does_not_leave_fragment():
    text = normalize_assistant_text(
        "What do you recall?",
        "I'm an adaptive intelligence system. I cannot remember any surgical procedure in this context.",
    )

    assert text == "I'm an adaptive intelligence system"
    assert "surgical procedure" not in text
    assert "in this context" not in text


def test_engine_visible_response_governance_uses_output_governor():
    from eli.kernel.engine import CognitiveEngine

    engine = object.__new__(CognitiveEngine)
    text = engine._govern_visible_response(
        "I performed open head surgery on you.",
        "I'm an adaptive intelligence system. I cannot remember any surgical procedure in this context.",
        memory_context="local repair memory",
        is_grounded=True,
    )

    assert "Wrong frame" in text
    assert "cannot remember any surgical procedure" not in text
