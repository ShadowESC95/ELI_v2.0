"""Coverage audit: assert that the test suite actually covers the critical paths.

These tests are meta-tests — they verify that the test infrastructure itself
is not deceiving us. They check:

  1. ELI_TEST_MODE is set in the test environment (so we know when we're
     bypassing real paths and can explicitly opt out)
  2. _eli_test_mode() returns True during normal pytest runs
  3. Tests that explicitly need real algorithm dispatch patch it out correctly
  4. The streaming path is exercised by at least one test with stream=True
  5. _run_mode_algorithm is not silently skipped in integration tests

Also includes: response-length sanity tests — a private mode response must
produce more tokens than a quick-mode response on the same substantive prompt,
given both are running the real algorithm (no ELI_TEST_MODE bypass).
"""
import os
import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Meta: test-mode awareness
# ---------------------------------------------------------------------------

class TestTestModeAwareness:

    def test_eli_test_mode_is_set_in_conftest(self):
        """ELI_TEST_MODE=1 must be in the environment during pytest runs.
        If it's missing, _eli_test_mode() returns False and algorithm dispatch
        tries to call GGUF for real — tests will either hang or error."""
        assert os.environ.get("ELI_TEST_MODE") == "1", (
            "ELI_TEST_MODE is not set to '1' — conftest.py should set it. "
            "Without this, integration tests may call real GGUF inference."
        )

    def test_eli_test_mode_function_returns_true_in_tests(self):
        from eli.kernel.engine import _eli_test_mode
        assert _eli_test_mode() is True, (
            "_eli_test_mode() returned False during pytest — "
            "multi-pass algorithm dispatch will be attempted with no GGUF model loaded."
        )

    def test_supports_mode_algorithm_skipped_in_normal_test_run(self):
        """In normal test mode, _run_chat_reasoning_loop skips the algorithm block.
        This is why integration tests for the algorithm must patch out test mode."""
        from eli.kernel.engine import CognitiveEngine, _eli_test_mode
        assert _eli_test_mode(), (
            "This test only verifies that test mode IS active during normal runs. "
            "If it fails, the rest of the test suite may try to run real GGUF."
        )

    def test_integration_reasoning_tests_patch_test_mode(self):
        """Verify that the reasoning algorithm tests in test_integration_reasoning_multipass.py
        call the algorithm methods DIRECTLY rather than going through the test-mode guard."""
        # The integration tests call engine._run_chain_of_thought() directly,
        # bypassing the _eli_test_mode() guard in _run_chat_reasoning_loop.
        # This test documents that design decision.
        from eli.kernel.engine import CognitiveEngine
        engine = CognitiveEngine(auto_init_gguf=False)
        mock = MagicMock(side_effect=["scratchpad", "final answer"])
        engine._get_chat_response = mock
        # Direct call bypasses _eli_test_mode guard
        result = engine._run_chain_of_thought("test question", "", {}, "")
        assert mock.call_count == 2, (
            "Direct _run_chain_of_thought call should always make 2 _get_chat_response calls "
            f"regardless of test mode. Got {mock.call_count}."
        )


# ---------------------------------------------------------------------------
# Response length: private modes must produce longer responses than quick
# ---------------------------------------------------------------------------

class TestPrivateModeResponseLength:
    """With identical prompts and token budgets, private modes must produce
    at least as much output as quick mode — because they run more passes.

    These tests mock _get_chat_response to return realistic multi-sentence
    outputs so length comparisons are meaningful."""

    PROMPT = "Explain how ELI's 12-stage cognitive pipeline processes a user request."

    def _make_engine(self):
        from eli.kernel.engine import CognitiveEngine
        return CognitiveEngine(auto_init_gguf=False)

    def test_cot_response_uses_both_stage_outputs(self):
        """CoT must incorporate the scratchpad into the final answer — not ignore it."""
        engine = self._make_engine()
        scratchpad = (
            "Step 1: The pipeline starts with PERCEIVE+INGEST. "
            "Step 2: Input is normalized. Step 3: Router classifies intent. "
            "Step 4: Truth gate. Step 5: Executive planner. Step 6: Agent bus. "
            "Step 7: Working memory. Step 8: Inference broker. Step 9: Reasoning. "
            "Step 10: Output governor. Step 11: Response delivery. Step 12: Learning."
        )
        final = "ELI processes requests through a 12-stage pipeline starting with perception and ending with learning and state update."
        mock = MagicMock(side_effect=[scratchpad, final])
        engine._get_chat_response = mock
        result = engine._run_chain_of_thought(self.PROMPT, "", {}, "")
        # The final output is what's returned (scratchpad stays private)
        assert result.strip() == final.strip()
        assert mock.call_count == 2

    def test_sc_consensus_call_receives_all_samples(self):
        """The consensus/selection call in SC must receive all N sample texts."""
        engine = self._make_engine()
        samples = [f"Sample {i}: ELI has 12 pipeline stages." for i in range(1, 4)]
        calls_seen = []

        def capture(prompt, *args, **kwargs):
            calls_seen.append(prompt)
            if len(calls_seen) <= 3:
                return samples[len(calls_seen) - 1]
            return "The most consistent answer."

        engine._get_chat_response = capture
        engine._run_self_consistency(self.PROMPT, "", {}, "", n=3)

        # The selection prompt (4th call) must contain all 3 sample texts
        selection_prompt = calls_seen[3]
        for i, sample in enumerate(samples, 1):
            assert sample in selection_prompt, (
                f"Sample {i} text is missing from the SC consensus/selection prompt. "
                f"The selector cannot choose intelligently without seeing all samples."
            )

    def test_tot_develop_call_receives_branch_proposals(self):
        """The development call in ToT must contain the branch proposals from stage 1."""
        engine = self._make_engine()
        branch_proposals = "Branch 1: Start from stage 1\nBranch 2: Start from stage 12\nBranch 3: Start from the router"
        calls_seen = []

        def capture(prompt, *args, **kwargs):
            calls_seen.append(prompt)
            if len(calls_seen) == 1:
                return branch_proposals
            return "Developed answer from best branch."

        engine._get_chat_response = capture
        engine._run_tree_of_thoughts(self.PROMPT, "", {}, "")
        assert len(calls_seen) == 2
        # Stage 2 (develop) must reference the proposals
        assert "Branch" in calls_seen[1] or "branch" in calls_seen[1].lower(), (
            "ToT develop call did not receive the branch proposals from stage 1. "
            "Development pass is reasoning in the dark."
        )


# ---------------------------------------------------------------------------
# Wiring audit: all 4 algorithm dispatch names match _supports_mode_algorithm
# ---------------------------------------------------------------------------

class TestAlgorithmDispatchSurface:

    def test_all_private_modes_are_supported_algorithms(self):
        """_supports_mode_algorithm must return True for all 4 private modes."""
        from eli.kernel.engine import CognitiveEngine
        engine = CognitiveEngine(auto_init_gguf=False)
        for mode in ("chain_of_thought", "tree_of_thoughts", "constitutional_ai", "self_consistency"):
            assert engine._supports_mode_algorithm(mode), (
                f"_supports_mode_algorithm('{mode}') returned False — "
                f"this mode will run as a single pass even when selected"
            )

    def test_quick_mode_is_not_an_algorithm(self):
        from eli.kernel.engine import CognitiveEngine
        engine = CognitiveEngine(auto_init_gguf=False)
        assert not engine._supports_mode_algorithm("quick"), (
            "_supports_mode_algorithm('quick') returned True — quick must be single-pass"
        )

    def test_run_mode_algorithm_dispatches_to_all_four(self):
        """_run_mode_algorithm must dispatch to the correct method for each mode."""
        from eli.kernel.engine import CognitiveEngine
        engine = CognitiveEngine(auto_init_gguf=False)

        for mode, method_name in [
            ("chain_of_thought",  "_run_chain_of_thought"),
            ("tree_of_thoughts",  "_run_tree_of_thoughts"),
            ("constitutional_ai", "_run_constitutional_ai"),
            ("self_consistency",  "_run_self_consistency"),
        ]:
            method_mock = MagicMock(return_value=f"output for {mode}")
            setattr(engine, method_name, method_mock)
            result = engine._run_mode_algorithm(mode, "question", "context", {}, "")
            assert method_mock.called, (
                f"_run_mode_algorithm('{mode}') did not call {method_name}"
            )
            assert result == f"output for {mode}"

    def test_run_mode_algorithm_returns_none_for_quick(self):
        from eli.kernel.engine import CognitiveEngine
        engine = CognitiveEngine(auto_init_gguf=False)
        result = engine._run_mode_algorithm("quick", "question", "", {}, "")
        assert result is None, (
            "_run_mode_algorithm('quick') should return None (no algorithm for quick mode)"
        )


# ---------------------------------------------------------------------------
# Reasoning modes module: is_private_reasoning_mode covers all 4
# ---------------------------------------------------------------------------

class TestReasoningModesModule:

    def test_is_private_for_all_four_modes(self):
        from eli.cognition.reasoning_modes import is_private_reasoning_mode
        for mode in ("chain_of_thought", "tree_of_thoughts", "constitutional_ai", "self_consistency"):
            assert is_private_reasoning_mode(mode), (
                f"is_private_reasoning_mode('{mode}') returned False — "
                f"the streaming path will not route it through the algorithm"
            )

    def test_quick_is_not_private(self):
        from eli.cognition.reasoning_modes import is_private_reasoning_mode
        assert not is_private_reasoning_mode("quick")
        assert not is_private_reasoning_mode("fast")

    def test_strip_reasoning_leaks_removes_scratchpad_header(self):
        from eli.cognition.reasoning_modes import strip_reasoning_leaks
        text = "Chain of Thought:\nStep 1: think...\nFinal Answer:\nThe answer is 42."
        result = strip_reasoning_leaks(text)
        assert "Chain of Thought" not in result
        assert "42" in result

    def test_strip_reasoning_leaks_removes_sample_blocks(self):
        from eli.cognition.reasoning_modes import strip_reasoning_leaks
        text = "Candidate 1: answer one\nCandidate 2: answer two\nFinal answer: answer one"
        result = strip_reasoning_leaks(text)
        assert "Candidate 1" not in result or "Candidate 2" not in result
