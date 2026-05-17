#!/usr/bin/env python3
from __future__ import annotations

import ast
import importlib
import inspect
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / "eli/execution/router_enhanced.py"
EXECUTOR = ROOT / "eli/execution/executor_enhanced.py"
ENGINE = ROOT / "eli/kernel/engine.py"
ORCH = ROOT / "eli/cognition/orchestrator.py"
GATE = ROOT / "eli/runtime/deterministic_grounding_gate.py"


def _extract_router_stages(src: str) -> list[str]:
    m = re.search(r"_ELI_ROUTE_PRIORITY_STAGES\s*=\s*_eli_route_priority_stages\(\)", src)
    if not m:
        return []
    start = src.find("def _eli_route_priority_stages():")
    end = src.find("_ELI_ROUTE_PRIORITY_STAGES = _eli_route_priority_stages()", start)
    block = src[start:end]
    return re.findall(r'\("([a-zA-Z0-9_]+)",\s*_stage_[a-zA-Z0-9_]+\)', block)


def _extract_executor_mw(src: str) -> list[str]:
    m = re.search(r"_ELI_EXECUTOR_MIDDLEWARE_TABLE\s*=\s*\((.*?)\)\n\n\s*def _eli_exec_core", src, re.S)
    if not m:
        return []
    block = m.group(1)
    return re.findall(r'\("([a-zA-Z0-9_]+)",\s*_eli_exec_mw_[a-zA-Z0-9_]+\)', block)


def _extract_engine_mw_markers(src: str) -> list[str]:
    seen: list[str] = []
    for marker in re.findall(r"ELI_ENGINE_MIDDLEWARE_([A-Z0-9_]+)", src):
        if marker not in seen:
            seen.append(marker)
    return seen


def _extract_orch_stage_keys(src: str) -> list[str]:
    out: list[str] = []
    for k in re.findall(r'wm\.trace\["([^"]+)"\]\s*=', src):
        if k not in out:
            out.append(k)
    return out


def _count_function_defs(src: str, name: str) -> list[int]:
    tree = ast.parse(src)
    out: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            out.append(int(node.lineno))
    return sorted(out)


def _self_method_calls_by_scope(src: str, method_name: str) -> list[tuple[str, int]]:
    tree = ast.parse(src)
    found: list[tuple[str, int]] = []

    class _Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self._scope_stack: list[str] = []

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._scope_stack.append(node.name)
            self.generic_visit(node)
            self._scope_stack.pop()

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._scope_stack.append(node.name)
            self.generic_visit(node)
            self._scope_stack.pop()

        def visit_Call(self, node: ast.Call) -> None:
            fn = node.func
            if (
                isinstance(fn, ast.Attribute)
                and isinstance(fn.value, ast.Name)
                and fn.value.id == "self"
                and fn.attr == method_name
            ):
                scope = self._scope_stack[-1] if self._scope_stack else "<module>"
                found.append((scope, int(node.lineno)))
            self.generic_visit(node)

    _Visitor().visit(tree)
    return found


def main() -> int:
    failures: list[str] = []

    router_src = ROUTER.read_text(encoding="utf-8", errors="replace")
    exec_src = EXECUTOR.read_text(encoding="utf-8", errors="replace")
    engine_src = ENGINE.read_text(encoding="utf-8", errors="replace")
    orch_src = ORCH.read_text(encoding="utf-8", errors="replace")
    gate_src = GATE.read_text(encoding="utf-8", errors="replace")

    router_stages = _extract_router_stages(router_src)
    executor_mw = _extract_executor_mw(exec_src)
    engine_mw = _extract_engine_mw_markers(engine_src)
    orch_stage_keys = _extract_orch_stage_keys(orch_src)
    execute_defs = _count_function_defs(exec_src, "execute")
    route_defs = _count_function_defs(router_src, "route")
    render_action_defs = _count_function_defs(gate_src, "render_action")
    run_internal_calls = _self_method_calls_by_scope(engine_src, "_run_internal_orchestrator")
    dispatch_bus_calls = _self_method_calls_by_scope(engine_src, "_dispatch_agent_bus")

    print("=== Pipeline Wiring Audit (Full) ===")
    print(f"router_priority_stages: {len(router_stages)}")
    print("  " + ", ".join(router_stages))
    print(f"executor_middleware_stages: {len(executor_mw)}")
    print("  " + ", ".join(executor_mw))
    print(f"engine_middleware_markers: {len(engine_mw)}")
    print("  " + ", ".join(engine_mw))
    print(f"orchestrator_trace_stage_keys: {len(orch_stage_keys)}")
    print("  " + ", ".join(orch_stage_keys))
    print()
    print("legacy_or_duplicate_surfaces:")
    print(f"  router.route defs: {len(route_defs)} at {route_defs}")
    print(f"  executor.execute defs: {len(execute_defs)} at {execute_defs[:8]}{' ...' if len(execute_defs) > 8 else ''}")
    print(f"  grounding.render_action defs: {len(render_action_defs)} at {render_action_defs[:8]}{' ...' if len(render_action_defs) > 8 else ''}")
    print(f"  engine calls self._run_internal_orchestrator: {run_internal_calls}")
    print(f"  engine calls self._dispatch_agent_bus: {dispatch_bus_calls}")
    print()

    # Runtime wiring checks
    router_mod = importlib.import_module("eli.execution.router_enhanced")
    exec_mod = importlib.import_module("eli.execution.executor_enhanced")
    gate_mod = importlib.import_module("eli.runtime.deterministic_grounding_gate")
    engine_mod = importlib.import_module("eli.kernel.engine")

    if not getattr(router_mod, "_ELI_ROUTE_PRIORITY_PIPELINE_V1", False):
        failures.append("Router priority pipeline flag is not active")
    if not hasattr(router_mod, "_ELI_ROUTE_PRIORITY_STAGES"):
        failures.append("Router stage table missing")
    if not getattr(exec_mod, "_ELI_EXECUTOR_CANONICAL_MIDDLEWARE_TABLE_V1", False):
        failures.append("Executor canonical middleware table flag is not active")
    if not hasattr(exec_mod, "_ELI_EXECUTOR_MIDDLEWARE_TABLE"):
        failures.append("Executor middleware table missing")
    if getattr(exec_mod, "execute_action", None) is not getattr(exec_mod, "execute", None):
        failures.append("execute_action is not bound to execute")
    if not getattr(gate_mod, "_ELI_DETERMINISTIC_GROUNDING_POLICY_ENGINE_V1", False):
        failures.append("Deterministic grounding immutable policy engine is not active")
    if not run_internal_calls:
        failures.append("No calls to self._run_internal_orchestrator found")
    else:
        _called_from_process = any(scope == "process" for scope, _ in run_internal_calls)
        if not _called_from_process:
            failures.append(
                "_run_internal_orchestrator is not called from process(); orchestrator stages are currently not on the main chat path"
            )

    # Route sanity spot checks
    samples = [
        ("what updates and checks have you performed as of late?", "SELF_REPORT"),
        ("how many memories do you have", "MEMORY_STATUS"),
        ("scan the gui runtime wiring and prove every hook with actual file-read evidence", "GUI_RUNTIME_AUDIT"),
    ]
    for prompt, expected in samples:
        got = (router_mod.route(prompt) or {}).get("action")
        if got != expected:
            failures.append(f"Route mismatch for {prompt!r}: expected {expected}, got {got}")

    print("=== Runtime Flags ===")
    print(f"router._ELI_ROUTE_PRIORITY_PIPELINE_V1={getattr(router_mod, '_ELI_ROUTE_PRIORITY_PIPELINE_V1', None)}")
    print(f"executor._ELI_EXECUTOR_CANONICAL_MIDDLEWARE_TABLE_V1={getattr(exec_mod, '_ELI_EXECUTOR_CANONICAL_MIDDLEWARE_TABLE_V1', None)}")
    print(f"grounding._ELI_DETERMINISTIC_GROUNDING_POLICY_ENGINE_V1={getattr(gate_mod, '_ELI_DETERMINISTIC_GROUNDING_POLICY_ENGINE_V1', None)}")
    try:
        print(f"router.route bound to line {inspect.getsourcelines(router_mod.route)[1]}")
    except Exception:
        print("router.route bound line: unavailable")
    try:
        print(f"executor.execute bound to line {inspect.getsourcelines(exec_mod.execute)[1]}")
    except Exception:
        print("executor.execute bound line: unavailable")
    try:
        print(f"grounding.render_action bound to line {inspect.getsourcelines(gate_mod.render_action)[1]}")
    except Exception:
        print("grounding.render_action bound line: unavailable")
    try:
        print(f"engine.process bound to line {inspect.getsourcelines(engine_mod.CognitiveEngine.process)[1]}")
    except Exception:
        print("engine.process bound line: unavailable")
    print()

    print("=== Result ===")
    if failures:
        print(f"FAILURES: {len(failures)}")
        for f in failures:
            print(" -", f)
        return 1

    print("PASS: pipeline wiring surfaces are active and internally consistent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
