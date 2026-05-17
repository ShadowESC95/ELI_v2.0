from eli.kernel.engine import CognitiveEngine


def test_memory_count_quick_is_concise_and_no_gguf():
    eng = CognitiveEngine.__new__(CognitiveEngine)
    out = eng.process("How many memories do you have, eli?", reasoning_mode="quick")

    assert isinstance(out, dict)
    assert out["evidence_source"].startswith("memory_count_quick_concise_validated")
    assert out["report"]["gguf_used"] is False
    assert out["report"]["synthesis_validated"] is None
    assert out["report"]["synthesis_kind"] == "quick_concise_deterministic"

    assert out["content"].startswith("I have ")
    assert "long-term memory rows" in out["content"]
    assert "Grounded supporting counts" not in out["content"]
    assert "Related stores" not in out["content"]
    assert not out["content"].startswith("You have ")


def test_memory_count_nonquick_is_grounded_more_detailed_and_no_gguf():
    eng = CognitiveEngine.__new__(CognitiveEngine)

    for mode in ("chain_of_thought", "constitutional_ai"):
        out = eng.process("How many memories do you have, eli?", reasoning_mode=mode)

        assert isinstance(out, dict)
        assert out["evidence_source"].startswith(
            "memory_count_grounded_synthesis_validated"
        )
        assert out["evidence_source"] != "memory_count_quick_concise_validated_v5"
        assert out["report"]["gguf_used"] is False
        assert out["report"]["synthesis_validated"] is True
        assert out["report"]["synthesis_kind"] == "deterministic_grounded_synthesis"

        assert out["content"].startswith("I have ")
        assert not out["content"].startswith("You have ")
        assert "long-term memory rows" in out["content"]
        assert "Grounded supporting counts" in out["content"]
        assert "FTS memory rows" in out["content"]
        assert "FAISS vector entries" in out["content"]
