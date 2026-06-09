"""Integration: multi-pass reasoning algorithms actually fire multiple GGUF calls.

These tests bypass ELI_TEST_MODE so the algorithm dispatch runs for real.
They mock _get_chat_response (the inner GGUF call) at the engine-instance
level to count invocations and control return values.

Why these tests exist:
  - All 4 private modes were previously single-pass on the streaming path
    (generate_from_assembled_prompt → one _get_chat_response regardless of mode)
  - Tests with ELI_TEST_MODE=1 skipped _supports_mode_algorithm entirely and
    never caught the bypass
  - Each test here asserts that the algorithm ran the expected number of
    _get_chat_response calls, not just that output is non-empty
"""
import pytest
from unittest.mock import MagicMock, patch, call


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_engine():
    """CognitiveEngine with GGUF disabled; ELI_TEST_MODE NOT set."""
    from eli.kernel.engine import CognitiveEngine
    return CognitiveEngine(auto_init_gguf=False)


def _patch_get_chat(engine, responses):
    """Replace engine._get_chat_response with a mock returning responses in order."""
    side_effects = list(responses)
    mock = MagicMock(side_effect=side_effects)
    engine._get_chat_response = mock
    return mock


# ---------------------------------------------------------------------------
# Chain-of-thought: 2 GGUF calls (scratchpad + synthesis)
# ---------------------------------------------------------------------------

class TestChainOfThoughtMultipass:

    def test_cot_calls_get_chat_response_twice(self):
        """_run_chain_of_thought must call _get_chat_response exactly 2 times."""
        engine = _make_engine()
        mock = _patch_get_chat(engine, [
            "Step 1: think...\nStep 2: reason...",   # private scratchpad
            "Final clean answer.",                    # synthesis
        ])
        result = engine._run_chain_of_thought(
            user_input="Explain how memory works.",
            working_context="",
            gen_overrides={"max_tokens": 512, "temperature": 0.5},
            situation_brief="",
        )
        assert mock.call_count == 2, (
            f"CoT must make exactly 2 GGUF calls (scratchpad + synthesis), "
            f"got {mock.call_count}"
        )

    def test_cot_returns_final_not_scratchpad(self):
        """CoT must return the synthesis output, not the private scratchpad."""
        engine = _make_engine()
        _patch_get_chat(engine, [
            "INTERNAL REASONING: step 1... step 2...",
            "The final clean answer to the question.",
        ])
        result = engine._run_chain_of_thought(
            "What is 2+2?", "", {}, "",
        )
        assert "INTERNAL REASONING" not in result, (
            "CoT leaked private scratchpad into the returned response"
        )
        assert "final" in result.lower() or len(result) > 5

    def test_cot_second_call_receives_scratchpad_as_context(self):
        """Stage-2 prompt must contain the stage-1 scratchpad text."""
        engine = _make_engine()
        scratchpad_text = "SCRATCHPAD: here is my thinking about the question"
        calls_seen = []

        def _capture(prompt, context, **kwargs):
            calls_seen.append(prompt)
            return scratchpad_text if len(calls_seen) == 1 else "Final answer."

        engine._get_chat_response = _capture
        engine._run_chain_of_thought("Tell me about ELI.", "", {}, "")
        assert len(calls_seen) == 2
        assert scratchpad_text in calls_seen[1], (
            "Stage-2 synthesis prompt does not include the stage-1 scratchpad"
        )


# ---------------------------------------------------------------------------
# Tree-of-thoughts: 2 GGUF calls (propose branches + develop best)
# ---------------------------------------------------------------------------

class TestTreeOfThoughtsMultipass:

    def test_tot_calls_get_chat_response_twice(self):
        """_run_tree_of_thoughts must call _get_chat_response exactly 2 times."""
        engine = _make_engine()
        mock = _patch_get_chat(engine, [
            "Branch 1: approach A\nBranch 2: approach B\nBranch 3: approach C",
            "Developed answer following the best branch.",
        ])
        result = engine._run_tree_of_thoughts(
            "How should I structure a complex project?", "", {}, "",
        )
        assert mock.call_count == 2, (
            f"ToT must make exactly 2 GGUF calls (propose + develop), got {mock.call_count}"
        )

    def test_tot_returns_non_empty_string(self):
        engine = _make_engine()
        _patch_get_chat(engine, [
            "Branch A: ...\nBranch B: ...",
            "Developed final answer.",
        ])
        result = engine._run_tree_of_thoughts("Question", "", {}, "")
        assert isinstance(result, str) and len(result.strip()) > 0


# ---------------------------------------------------------------------------
# Constitutional AI: 2-3 GGUF calls (draft + critique + optional revision)
# ---------------------------------------------------------------------------

class TestConstitutionalAIMultipass:

    def test_cai_calls_get_chat_response_three_times_when_fail(self):
        """CAI must call _get_chat_response 3x when the critique lists concrete issues."""
        engine = _make_engine()
        mock = _patch_get_chat(engine, [
            "Initial draft answer.",
            "1. P2: the claim 'fully autonomous' is unsupported by the context — remove or qualify it.\n"
            "2. P3: the answer omits the architecture detail that was asked for — add it.",
            "Revised answer addressing both issues.",
        ])
        result = engine._run_constitutional_ai(
            "Describe ELI's architecture.", "", {}, "",
        )
        assert mock.call_count == 3, (
            f"CAI must make 3 GGUF calls when the critique lists issues, got {mock.call_count}"
        )

    def test_cai_skips_revision_when_no_issues(self):
        """CAI skips the revision pass when the critique reports NO ISSUES — only 2 calls."""
        engine = _make_engine()
        mock = _patch_get_chat(engine, [
            "Initial draft answer.",
            "NO ISSUES",
        ])
        result = engine._run_constitutional_ai(
            "What time is it?", "", {}, "",
        )
        assert mock.call_count == 2, (
            f"CAI must skip revision (only 2 calls) when the critique reports NO ISSUES, got {mock.call_count}"
        )

    def test_cai_rejects_revision_that_leaks_critique(self):
        """If the revision output contains P1-P5 FAIL lines, fall back to initial draft."""
        engine = _make_engine()
        initial_draft = "This is the correct initial draft."
        _patch_get_chat(engine, [
            initial_draft,
            "P1: FAIL — bad\nP2: PASS\nP3: PASS\nP4: PASS\nP5: PASS\nFix the claim.",
            # Revision accidentally reproduces critique structure — must be rejected
            "P1: FAIL — still wrong\nP2: PASS\nP3: PASS\nP4: PASS\nP5: PASS",
        ])
        result = engine._run_constitutional_ai("Question?", "", {}, "")
        assert result.strip() == initial_draft.strip() or (
            "P1: FAIL" not in result
        ), "CAI returned a revision that leaked critique P-lines"

    def test_cai_returns_initial_when_revision_echoes_question(self):
        """If revision just repeats the question verbatim, fall back to initial draft."""
        engine = _make_engine()
        user_input = "What is ELI?"
        initial = "ELI is an embodied language intelligence."
        _patch_get_chat(engine, [
            initial,
            "P1: FAIL — check identity\nP2: PASS\nP3: PASS\nP4: PASS\nP5: PASS",
            user_input,  # revision output = question echoed back
        ])
        result = engine._run_constitutional_ai(user_input, "", {}, "")
        assert result.strip() != user_input.strip(), (
            "CAI returned the question back as the response instead of the initial draft"
        )


# ---------------------------------------------------------------------------
# Self-consistency: N+1 GGUF calls (N samples + 1 consensus)
# ---------------------------------------------------------------------------

class TestSelfConsistencyMultipass:

    def test_sc_calls_get_chat_response_n_plus_one_times(self):
        """_run_self_consistency with n=3 must make exactly 4 GGUF calls."""
        engine = _make_engine()
        n = 3
        mock = _patch_get_chat(engine, [
            f"Sample {i} answer." for i in range(1, n + 1)
        ] + ["The most consistent answer chosen from samples."])
        result = engine._run_self_consistency(
            "What is ELI?", "", {}, "", n=n,
        )
        assert mock.call_count == n + 1, (
            f"SC(n={n}) must make {n+1} GGUF calls (samples + consensus), "
            f"got {mock.call_count}"
        )

    def test_sc_with_n2_makes_three_calls(self):
        """SC with n=2 makes exactly 3 calls."""
        engine = _make_engine()
        mock = _patch_get_chat(engine, [
            "Answer A.", "Answer B.", "Chosen: Answer A.",
        ])
        engine._run_self_consistency("Question", "", {}, "", n=2)
        assert mock.call_count == 3

    def test_sc_strips_sample_marker_leaks(self):
        """SC must strip '=== SAMPLE N ===' markers if the selector echoes them."""
        engine = _make_engine()
        _patch_get_chat(engine, [
            "Sample one text.",
            "Sample two text.",
            # Selector leaks the bundle format back
            "=== SAMPLE 1 ===\nSample one text.\n=== SAMPLE 2 ===\nSample two text.",
        ])
        result = engine._run_self_consistency("Q?", "", {}, "", n=2)
        assert "=== SAMPLE" not in result, (
            "SC returned output containing raw sample markers from the selector pass"
        )


# ---------------------------------------------------------------------------
# Streaming path: private modes go through _run_mode_algorithm, not single-pass
# ---------------------------------------------------------------------------

class TestStreamingUsesAlgorithm:
    """Verify generate_stream_from_assembled_prompt routes private modes through
    _run_mode_algorithm rather than the old generate_from_assembled_prompt path."""

    def _make_wm(self):
        from types import SimpleNamespace
        return SimpleNamespace(
            assembled_context="",
            persona_handoff="",
            final_response="",
            trace={},
            bus_result=None,
            short_term_memory=SimpleNamespace(recent_turns=[]),
        )

    @pytest.mark.parametrize("mode", [
        "chain_of_thought",
        "tree_of_thoughts",
        "constitutional_ai",
        "self_consistency",
    ])
    def test_stream_private_mode_calls_run_mode_algorithm(self, mode):
        """For private modes, generate_stream_from_assembled_prompt must call
        _run_mode_algorithm, not the old single-pass generate_from_assembled_prompt."""
        engine = _make_engine()
        algo_mock = MagicMock(return_value=f"Algorithm output for {mode}.")
        engine._run_mode_algorithm = algo_mock
        # Also mock _govern_visible_response to pass through
        engine._govern_visible_response = MagicMock(side_effect=lambda p, r, **kw: r)
        engine._build_persona_handoff_once = MagicMock(return_value="brief")
        engine._chat_generation_overrides = MagicMock(return_value={"max_tokens": 512})

        gen = engine.generate_stream_from_assembled_prompt(
            "Hello, describe yourself.",
            working_memory=self._make_wm(),
            reasoning_mode=mode,
        )
        tokens = list(gen)
        full_text = "".join(tokens)

        assert algo_mock.called, (
            f"generate_stream_from_assembled_prompt did not call _run_mode_algorithm "
            f"for mode={mode!r} — multi-pass algorithm was bypassed"
        )
        called_mode = algo_mock.call_args[0][0]
        assert called_mode == mode, (
            f"_run_mode_algorithm called with mode={called_mode!r}, expected {mode!r}"
        )
        assert len(full_text.strip()) > 0, "Stream yielded empty output"

    def test_stream_quick_mode_does_not_call_run_mode_algorithm(self):
        """Quick mode must NOT route through _run_mode_algorithm."""
        engine = _make_engine()
        algo_mock = MagicMock(return_value="Should not be called")
        engine._run_mode_algorithm = algo_mock
        engine._build_persona_handoff_once = MagicMock(return_value="brief")

        # For quick mode, the live streaming path runs — mock the GGUF layer
        with patch("eli.cognition.gguf_inference.chat_completion",
                   return_value={"content": "Quick streamed response"}), \
             patch("eli.cognition.gguf_inference.is_loaded", return_value=True):
            gen = engine.generate_stream_from_assembled_prompt(
                "What time is it?",
                working_memory=self._make_wm(),
                reasoning_mode="quick",
            )
            list(gen)

        assert not algo_mock.called, (
            "generate_stream_from_assembled_prompt called _run_mode_algorithm "
            "for quick mode — should only use it for private modes"
        )

    def test_stream_algorithm_fallback_on_error(self):
        """If _run_mode_algorithm raises, the stream must fall back gracefully
        to _get_chat_response (not crash or yield nothing)."""
        engine = _make_engine()
        engine._run_mode_algorithm = MagicMock(side_effect=RuntimeError("algo failed"))
        engine._get_chat_response = MagicMock(return_value="Fallback single-pass response.")
        engine._govern_visible_response = MagicMock(side_effect=lambda p, r, **kw: r)
        engine._build_persona_handoff_once = MagicMock(return_value="")
        engine._chat_generation_overrides = MagicMock(return_value={"max_tokens": 512})

        gen = engine.generate_stream_from_assembled_prompt(
            "What is ELI?",
            working_memory=self._make_wm(),
            reasoning_mode="chain_of_thought",
        )
        tokens = list(gen)
        assert len("".join(tokens).strip()) > 0, (
            "Stream yielded empty output after _run_mode_algorithm failure — "
            "fallback to _get_chat_response did not produce output"
        )
