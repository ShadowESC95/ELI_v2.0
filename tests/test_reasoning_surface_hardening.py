from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_engine_has_no_reasoning_mode_self_awareness_phrase():
    text = (ROOT / "eli/kernel/engine.py").read_text(encoding="utf-8")
    assert "REASONING MODE SELF-AWARENESS" not in text


def test_visible_output_strips_private_reasoning_markers():
    from eli.runtime.visible_output import visible_text

    dirty = """
    REASONING MODE SELF-AWARENESS:
    - Active mode: Chain of Thought
    Chain-of-thought: first I will expose hidden steps.
    Final answer: use the patched visible-output contract.
    """

    clean = visible_text(dirty, user_input="test")
    low = clean.lower()

    assert "reasoning mode self-awareness" not in low
    assert "chain-of-thought" not in low
    assert "hidden steps" not in low
    assert "patched visible-output contract" in low


def test_tts_visible_text_uses_visible_contract():
    from eli.perception.tts_router import _eli_tts_visible_text

    dirty = "Chain-of-thought: bad leak. Final answer: speak only this."
    clean = _eli_tts_visible_text(dirty)
    low = clean.lower()

    assert "chain-of-thought" not in low
    assert "bad leak" not in low
    assert "speak only this" in low


def test_visible_output_preserves_explicit_final_answer_after_private_marker():
    from eli.runtime.visible_output import visible_text

    dirty = "Scratchpad: private junk. Final answer: Preserve this exact final."
    clean = visible_text(dirty)
    low = clean.lower()

    assert "scratchpad" not in low
    assert "private junk" not in low
    assert "preserve this exact final" in low
