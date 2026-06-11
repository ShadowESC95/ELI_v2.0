"""In-process restricted execution for code-mode.

Runs a SMALL model-written program *in-process* so it can call ELI's live capabilities
(`api.*` / `execute(...)`) — which the process-isolated coding sandbox (`sandbox.run_code`)
deliberately cannot do, because that sandbox is walled off from ELI's live state.

Safety here is therefore STATIC + NAMESPACE based, not process isolation, AND gated:

  1. GATE — only runs when **Full Control** is ON (`is_full_control()`, the GUI toggle).
     Off (the default) → refuse without executing anything. Running model-written code
     in-process is a power-user capability and lives behind the same master switch that
     lifts ELI's other barriers.
  2. AST WHITELIST — the program may only use a fixed set of node types, may call only
     `api.*` / `execute(...)` + a curated safe-builtins set, and may NOT import, define
     classes, touch dunder/underscore attributes, or name a dangerous builtin
     (eval/exec/open/__import__/getattr/…). Anything else → rejected before execution.
  3. RESTRICTED NAMESPACE — exec runs with `__builtins__` replaced by the safe set and only
     `api` + `execute` injected, so even a missed static check fails closed (NameError).

This module is the gate + static validator + runner only; per-call risk classification
composes the existing `approval_engine` at the call site if desired.
"""
from __future__ import annotations

import ast
import contextlib
import io
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

# ── Safe builtins exposed to the program (curated; nothing introspective/dangerous) ──
_SAFE_BUILTINS: Dict[str, Any] = {
    k: __builtins__[k] if isinstance(__builtins__, dict) else getattr(__builtins__, k)
    for k in (
        "abs", "all", "any", "ascii", "bin", "bool", "bytes", "chr", "dict", "divmod",
        "enumerate", "filter", "float", "format", "frozenset", "hex", "int", "isinstance",
        "iter", "len", "list", "map", "max", "min", "next", "oct", "ord", "pow", "print",
        "range", "repr", "reversed", "round", "set", "slice", "sorted", "str", "sum",
        "tuple", "zip",
    )
}
_SAFE_BUILTINS.update({"True": True, "False": False, "None": None})

# Names that must never be referenced (escape vectors), even though they're not injected.
_FORBIDDEN_NAMES = frozenset({
    "eval", "exec", "compile", "open", "__import__", "input", "globals", "locals", "vars",
    "getattr", "setattr", "delattr", "hasattr", "dir", "id", "type", "object", "super",
    "memoryview", "breakpoint", "exit", "quit", "help", "__build_class__", "classmethod",
    "staticmethod", "property",
})

# AST node types the program may contain (anything else is rejected outright).
_ALLOWED_NODES: tuple = (
    ast.Module, ast.Expr, ast.Assign, ast.AugAssign, ast.AnnAssign, ast.NamedExpr,
    ast.If, ast.For, ast.While, ast.Break, ast.Continue, ast.Pass,
    ast.Call, ast.keyword, ast.Attribute, ast.Name, ast.Load, ast.Store,
    ast.Constant, ast.FormattedValue, ast.JoinedStr,
    ast.List, ast.Tuple, ast.Dict, ast.Set, ast.Starred,
    ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp, ast.comprehension,
    ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp, ast.Subscript, ast.Slice,
    ast.And, ast.Or, ast.Not, ast.Invert, ast.UAdd, ast.USub,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
    ast.LShift, ast.RShift, ast.BitOr, ast.BitXor, ast.BitAnd, ast.MatMult,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Is, ast.IsNot,
    ast.In, ast.NotIn,
)
# Explicitly hostile / out-of-scope nodes (clearer error than the generic whitelist reject).
_BANNED_NODES = (
    ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
    ast.Lambda, ast.Global, ast.Nonlocal, ast.With, ast.AsyncWith, ast.Try, ast.Raise,
    ast.Delete, ast.Yield, ast.YieldFrom, ast.Await, ast.AsyncFor, ast.Return,
)


@dataclass
class RestrictedResult:
    ok: bool = False
    blocked: bool = False              # refused by the Full Control gate
    validation_error: str = ""         # rejected by the AST whitelist
    runtime_error: str = ""            # raised during execution
    result: Any = None                 # the program's `result` variable
    stdout: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok, "blocked": self.blocked,
            "validation_error": self.validation_error, "runtime_error": self.runtime_error,
            "result": self.result, "stdout": self.stdout, "meta": self.meta,
        }


def validate_program(code: str, *, allowed_roots=("api", "execute")) -> Optional[str]:
    """Return None if `code` is safe to run in the restricted namespace, else an error
    string. Pure/static — no execution. Reusable for tests and pre-flight checks."""
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as e:
        return f"syntax error: {e.msg} (line {e.lineno})"

    for node in ast.walk(tree):
        if isinstance(node, _BANNED_NODES):
            return f"disallowed construct: {type(node).__name__}"
        if not isinstance(node, _ALLOWED_NODES):
            return f"disallowed construct: {type(node).__name__}"
        # No dunder / private attribute access (blocks __class__, __globals__, … escapes).
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            return f"disallowed attribute access: .{node.attr}"
        # No dangerous builtin names, no private/dunder identifiers.
        if isinstance(node, ast.Name):
            if node.id in _FORBIDDEN_NAMES:
                return f"disallowed name: {node.id}"
            if node.id.startswith("__"):
                return f"disallowed name: {node.id}"
    return None


def run_restricted(
    code: str,
    *,
    api: Any = None,
    execute: Optional[Callable] = None,
    max_stdout: int = 8000,
) -> RestrictedResult:
    """Gate → validate → run `code` in a restricted in-process namespace.

    The program should assign its answer to a variable named `result`. `api` and (if given)
    `execute` are the only injected names besides safe builtins.
    """
    # 1) Full Control gate — the master switch the user flips in the GUI.
    try:
        from eli.core.full_control import is_full_control
        _fc = bool(is_full_control())
    except Exception:
        _fc = False
    if not _fc:
        return RestrictedResult(
            ok=False, blocked=True,
            validation_error="",
            runtime_error="",
            meta={"reason": "code-mode execution requires Full Control (the GUI toggle is OFF)"},
        )

    # 2) Static AST whitelist.
    err = validate_program(code)
    if err is not None:
        return RestrictedResult(ok=False, validation_error=err)

    # 3) Restricted namespace — only safe builtins + api/execute.
    ns: Dict[str, Any] = {"__builtins__": dict(_SAFE_BUILTINS)}
    if api is not None:
        ns["api"] = api
    if execute is not None:
        ns["execute"] = execute

    buf = io.StringIO()
    try:
        compiled = compile(ast.parse(code, mode="exec"), "<eli-code-mode>", "exec")
        with contextlib.redirect_stdout(buf):
            exec(compiled, ns)  # noqa: S102 — bounded: gated + AST-whitelisted + restricted ns
    except Exception as e:  # the program raised
        return RestrictedResult(
            ok=False, runtime_error=f"{type(e).__name__}: {e}",
            stdout=buf.getvalue()[:max_stdout],
        )
    return RestrictedResult(
        ok=True, result=ns.get("result"),
        stdout=buf.getvalue()[:max_stdout],
        meta={"had_result": "result" in ns},
    )
