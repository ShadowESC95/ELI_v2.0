"""CLAIM: every executor SUPPORTED_ACTION has a dispatch branch: nothing is advertised that routes
but cannot run."""
from __future__ import annotations

import ast

from . import _helpers as H


def test_every_supported_action_is_handled():
    unhandled = set(H.supported_actions()) - H.executor_action_branches()
    assert not unhandled, f"SUPPORTED_ACTIONS with no executor dispatch path: {sorted(unhandled)}"


def _pure_actions(test):
    """The actions an `if` tests when its condition is `a == "X"` or `a in (...)` and nothing else."""
    if isinstance(test, ast.Compare) and isinstance(test.left, ast.Name) and test.left.id == "a" \
            and len(test.ops) == 1:
        op, comp = test.ops[0], test.comparators[0]
        if isinstance(op, ast.Eq) and isinstance(comp, ast.Constant) and isinstance(comp.value, str):
            return {comp.value}
        if isinstance(op, ast.In) and isinstance(comp, (ast.Tuple, ast.List, ast.Set)) and all(
                isinstance(e, ast.Constant) and isinstance(e.value, str) for e in comp.elts):
            return {e.value for e in comp.elts}
    return None


def _always_returns(body):
    for s in body:
        if isinstance(s, (ast.Return, ast.Raise)):
            return True
        if isinstance(s, ast.If) and _always_returns(s.body) and _always_returns(s.orelse):
            return True
        if isinstance(s, ast.With) and _always_returns(s.body):
            return True
        if isinstance(s, ast.Try) and (_always_returns(s.finalbody) or (
                (_always_returns(s.body) or _always_returns(s.orelse))
                and all(_always_returns(h.body) for h in s.handlers))):
            return True
    return False


def test_no_action_branch_is_behind_one_that_always_answers_it():
    """A second OPEN_FILE_SYSTEM branch, MCP_STATUS in the MCP_LIST branch, and CREATE_DOCUMENT /
    GENERATE_DOCUMENT in the DOC_GENERATE block could never run: an earlier branch for the same
    action returned on every path. Code that never runs still reads as what the action does."""
    tree = ast.parse((H.REPO / "eli" / "execution" / "executor_enhanced.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_execute_impl")
    answered, dead = {}, []
    for s in fn.body:
        acts = _pure_actions(s.test) if isinstance(s, ast.If) else None
        if not acts:
            continue
        returns = _always_returns(s.body)
        for act in sorted(acts):
            if act in answered:
                dead.append(f"{act} at line {s.lineno} (answered at line {answered[act]})")
            elif returns:
                answered[act] = s.lineno
    assert not dead, "branches that can never run:\n" + "\n".join(dead)
