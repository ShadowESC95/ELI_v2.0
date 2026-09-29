"""MULTI_COMMAND must skip a step whose dependency failed, rather than blindly running it —
and must never call the model when there's nothing to reason about."""
from unittest.mock import MagicMock, patch

import pytest

from eli.execution import command_dependency_graph as depgraph
from eli.execution.executor_enhanced import execute


@pytest.fixture(autouse=True)
def isolated_log(tmp_path, monkeypatch):
    monkeypatch.setenv("ELI_COMMAND_SEQUENCE_LOG", str(tmp_path / "seq.json"))


# ---- infer_dependencies unit tests (broker mocked/absent — no real model call) ----

def test_single_command_never_calls_the_broker():
    with patch("eli.cognition.inference_broker.get_broker") as gb:
        gb.side_effect = AssertionError("should not be called for a single command")
        assert depgraph.infer_dependencies(["do one thing"]) == {}


def test_env_var_disables_inference():
    with patch.dict("os.environ", {"ELI_MULTI_COMMAND_DAG": "0"}):
        with patch("eli.cognition.inference_broker.get_broker") as gb:
            gb.side_effect = AssertionError("should not be called when disabled")
            assert depgraph.infer_dependencies(["a", "b"]) == {}


def test_broker_unavailable_returns_independent():
    with patch("eli.cognition.inference_broker.get_broker", return_value=None):
        assert depgraph.infer_dependencies(["a", "b"]) == {}


def test_broker_not_ready_returns_independent():
    brk = MagicMock(gguf_ready=False)
    with patch("eli.cognition.inference_broker.get_broker", return_value=brk):
        assert depgraph.infer_dependencies(["a", "b"]) == {}


def test_valid_edges_are_parsed():
    brk = MagicMock(gguf_ready=True)
    brk.infer.return_value = '{"edges": [[1, 0]]}'
    with patch("eli.cognition.inference_broker.get_broker", return_value=brk):
        assert depgraph.infer_dependencies(["open file", "edit file", "unrelated"]) == {1: [0]}


def test_a_cycle_is_rejected_safely():
    brk = MagicMock(gguf_ready=True)
    brk.infer.return_value = '{"edges": [[0, 1], [1, 0]]}'
    with patch("eli.cognition.inference_broker.get_broker", return_value=brk):
        assert depgraph.infer_dependencies(["a", "b"]) == {}


def test_out_of_range_and_self_loop_edges_are_dropped():
    brk = MagicMock(gguf_ready=True)
    brk.infer.return_value = '{"edges": [[5, 0], [0, 0], [1, 0]]}'
    with patch("eli.cognition.inference_broker.get_broker", return_value=brk):
        assert depgraph.infer_dependencies(["a", "b"]) == {1: [0]}


def test_malformed_json_returns_independent():
    brk = MagicMock(gguf_ready=True)
    brk.infer.return_value = "not json at all"
    with patch("eli.cognition.inference_broker.get_broker", return_value=brk):
        assert depgraph.infer_dependencies(["a", "b"]) == {}


# ---- MULTI_COMMAND integration: a failed dependency blocks its dependent ----

def test_a_failed_step_blocks_only_its_dependent():
    cmds = ["this will definitely fail", "depends on the first", "an independent third thing"]
    with patch("eli.execution.command_dependency_graph.infer_dependencies",
              return_value={1: [0]}):
        r = execute("MULTI_COMMAND", {"commands": cmds, "raw": "three chained commands"})

    assert r["meta"]["dependencies"] == {1: [0]}
    assert "skipped — depends on step 0 which failed" in r["content"]
    # step 2 (independent) still ran — not swallowed by step 0's failure
    assert r["content"].count("•") == 3
    assert r["ok"] is False


def test_skipped_step_is_marked_not_done_and_retried_on_resume():
    cmds = ["this will definitely fail", "depends on the first"]
    with patch("eli.execution.command_dependency_graph.infer_dependencies",
              return_value={1: [0]}):
        execute("MULTI_COMMAND", {"commands": cmds, "raw": "two chained commands"})

    from eli.execution.command_sequence_log import start_or_resume
    resumed = start_or_resume("two chained commands", cmds)
    # neither the failed step nor the step skipped because of it counts as done
    assert resumed["done_ok"] == {}
