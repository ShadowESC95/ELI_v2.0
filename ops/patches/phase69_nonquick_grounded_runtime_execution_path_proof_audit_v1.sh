#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase69_nonquick_grounded_runtime_execution_path_proof_audit_${STAMP}"

ENGINE="eli/kernel/engine.py"
ROUTER="eli/execution/router_enhanced.py"

mkdir -p "$OUT"

for f in "$ENGINE" "$ROUTER"; do
  if [[ ! -f "$f" ]]; then
    echo "Required file missing: $f" >&2
    exit 1
  fi
done

cat > "$OUT/SUMMARY.md" <<'EOF'
# Phase 69 — Non-Quick Grounded Runtime Execution-Path Proof Audit

## Purpose

Phase63/68b closed the source-shape audit. This phase moves from static
inspection to live execution-path proof.

It verifies, through temporary in-process monkeypatching of the dedicated
synthesis helpers, that:

1. Quick mode does not enter the non-Quick synthesis helper.
2. Non-Quick modes do enter the correct synthesis helper.
3. The engine returns the helper's synthesized branch output.
4. The expected runtime trace strings are emitted for non-Quick execution.

## Scope

Surfaces audited:

- EXPLAIN_MEMORY_RUNTIME
- MEMORY_STATUS.recent_processing
- SELF_REPORT.recent_updates

Modes audited:

- quick
- chain_of_thought
- self_consistency
- tree_of_thoughts
- constitutional_ai

## Important limitation

This proves **runtime branch execution**, not live GGUF answer quality.
The synthesis helpers are replaced with sentinel return packets so the audit can
prove exact control flow without depending on model latency or output variance.
EOF

echo "=== PY_COMPILE ===" | tee "$OUT/00_py_compile.txt"
python3 -m py_compile "$ENGINE" "$ROUTER" 2>&1 | tee -a "$OUT/00_py_compile.txt"
echo "PY_COMPILE_OK" | tee -a "$OUT/00_py_compile.txt"

python3 - "$OUT" <<'PY'
from __future__ import annotations

import contextlib
import inspect
import io
import json
import traceback
import types
import sys
from pathlib import Path
from typing import Any, Callable

out = Path(sys.argv[1])

report: dict[str, Any] = {
    "phase": "phase69_nonquick_grounded_runtime_execution_path_proof_audit_v1",
    "engine_instantiation": {},
    "route_sanity": [],
    "cases": [],
    "assertions": [],
}

def record(ok: bool, label: str, detail: str = "") -> None:
    report["assertions"].append({
        "ok": bool(ok),
        "label": label,
        "detail": detail,
    })

def text_preview(value: Any, limit: int = 500) -> str:
    try:
        if isinstance(value, str):
            s = value
        else:
            s = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        s = repr(value)
    return s[:limit]

def extract_action(result: Any) -> str:
    if isinstance(result, dict):
        return str(result.get("action") or "").upper()
    return ""

def result_contains_sentinel(result: Any, sentinel: str) -> bool:
    try:
        if isinstance(result, dict):
            surface = "\n".join([
                str(result.get("content") or ""),
                str(result.get("response") or ""),
                json.dumps(result, ensure_ascii=False, sort_keys=True, default=str),
            ])
        else:
            surface = str(result)
        return sentinel in surface
    except Exception:
        return False

def find_engine_instance(engine_mod: Any) -> Any:
    candidates: list[tuple[str, Callable[[], Any]]] = []

    cls = getattr(engine_mod, "CognitiveEngine", None)
    if cls is not None and inspect.isclass(cls):
        candidates.append(("CognitiveEngine()", lambda: cls()))

    for name in (
        "get_engine",
        "get_cognitive_engine",
        "build_engine",
        "create_engine",
    ):
        fn = getattr(engine_mod, name, None)
        if callable(fn):
            candidates.append((f"{name}()", lambda fn=fn: fn()))

    for name in ("ENGINE", "engine", "cognitive_engine"):
        obj = getattr(engine_mod, name, None)
        if obj is not None and hasattr(obj, "process"):
            report["engine_instantiation"]["selected"] = name
            report["engine_instantiation"]["mode"] = "module_object"
            return obj

    attempts: list[dict[str, str]] = []
    for label, factory in candidates:
        try:
            obj = factory()
            if hasattr(obj, "process") and callable(getattr(obj, "process")):
                report["engine_instantiation"]["selected"] = label
                report["engine_instantiation"]["mode"] = "factory"
                report["engine_instantiation"]["attempts"] = attempts
                return obj
            attempts.append({
                "candidate": label,
                "status": "returned_object_without_callable_process",
                "detail": repr(obj),
            })
        except Exception as exc:
            attempts.append({
                "candidate": label,
                "status": "error",
                "detail": f"{type(exc).__name__}: {exc}",
            })

    report["engine_instantiation"]["attempts"] = attempts
    return None

def invoke_process(engine_obj: Any, prompt: str, mode: str) -> tuple[Any, str, str]:
    """
    Invoke process() using the primary contract first, then a small controlled
    fallback set. Every attempt is recorded by the caller through stdout/error.
    """
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()

    with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
        try:
            result = engine_obj.process(prompt, reasoning_mode=mode)
            return result, stdout_buf.getvalue(), stderr_buf.getvalue()
        except TypeError as first_exc:
            first_detail = f"{type(first_exc).__name__}: {first_exc}"
            try:
                result = engine_obj.process(prompt, mode=mode)
                marker = f"[PHASE69 invoke fallback: process(prompt, mode=...); primary failed: {first_detail}]\n"
                return result, marker + stdout_buf.getvalue(), stderr_buf.getvalue()
            except TypeError as second_exc:
                second_detail = f"{type(second_exc).__name__}: {second_exc}"
                raise RuntimeError(
                    "process() invocation failed for both supported keyword shapes: "
                    f"reasoning_mode -> {first_detail}; mode -> {second_detail}"
                )

# ---------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------

try:
    import eli.kernel.engine as engine_mod
except Exception:
    (out / "01_import_failure.txt").write_text(traceback.format_exc(), encoding="utf-8")
    raise

try:
    from eli.execution.router_enhanced import route as route_fn
except Exception:
    (out / "02_router_import_failure.txt").write_text(traceback.format_exc(), encoding="utf-8")
    raise

# ---------------------------------------------------------------------
# Engine instance
# ---------------------------------------------------------------------

engine_obj = find_engine_instance(engine_mod)
record(engine_obj is not None, "engine instance resolved for runtime process() audit",
       json.dumps(report["engine_instantiation"], ensure_ascii=False, default=str))

if engine_obj is None:
    (out / "03_phase69_runtime_execution_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    raise SystemExit("Phase69: could not resolve a CognitiveEngine instance with process().")

try:
    report["engine_instantiation"]["process_signature"] = str(inspect.signature(engine_obj.process))
except Exception:
    report["engine_instantiation"]["process_signature"] = "<signature unavailable>"

# ---------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------

CASES = [
    {
        "id": "memory_runtime_exact",
        "surface": "EXPLAIN_MEMORY_RUNTIME",
        "prompt": "Explain exactly how your memory system works internally — which files, which DB tables, which functions.",
        "expected_action": "EXPLAIN_MEMORY_RUNTIME",
        "helper": "_mw_mem_runtime_strict_synthesize",
        "trace": "[ENGINE] EXPLAIN_MEMORY_RUNTIME non-Quick: synthesized via GGUF",
    },
    {
        "id": "recent_memory_processing",
        "surface": "MEMORY_STATUS.recent_processing",
        "prompt": "What memories have you been processing lately?",
        "expected_action": "MEMORY_STATUS",
        "helper": "_mw_recent_memory_processing_synthesize",
        "trace": "[ENGINE] MEMORY_STATUS recent_processing non-Quick: synthesized via GGUF",
    },
    {
        "id": "self_report_recent_updates",
        "surface": "SELF_REPORT.recent_updates",
        "prompt": "What have you been working on recently?",
        "expected_action": "SELF_REPORT",
        "helper": "_mw_self_report_recent_updates_synthesize",
        "trace": "[ENGINE] SELF_REPORT recent_updates non-Quick: synthesized via GGUF",
    },
]

MODES = [
    "quick",
    "chain_of_thought",
    "self_consistency",
    "tree_of_thoughts",
    "constitutional_ai",
]

# Route sanity before runtime execution
for case in CASES:
    try:
        routed = route_fn(case["prompt"])
        action = extract_action(routed)
        row = {
            "id": case["id"],
            "expected_action": case["expected_action"],
            "observed_action": action,
            "route_result": routed,
        }
        report["route_sanity"].append(row)
        record(
            action == case["expected_action"],
            f"router sanity: {case['id']} routes to {case['expected_action']}",
            f"observed={action}",
        )
    except Exception as exc:
        report["route_sanity"].append({
            "id": case["id"],
            "error": f"{type(exc).__name__}: {exc}",
        })
        record(False, f"router sanity: {case['id']} route probe executes cleanly",
               f"{type(exc).__name__}: {exc}")

# Runtime branch execution cases
for case in CASES:
    helper_name = case["helper"]
    helper = getattr(engine_mod, helper_name, None)

    record(
        callable(helper),
        f"runtime helper present: {helper_name}",
        f"callable={callable(helper)}",
    )

    if not callable(helper):
        continue

    for mode in MODES:
        sentinel = f"PHASE69_SENTINEL::{case['id']}::{mode}"
        helper_calls: list[dict[str, Any]] = []
        original_helper = helper

        def fake_helper(question: Any, mode_arg: Any, evidence: Any, *,
                        _sentinel: str = sentinel,
                        _expected_action: str = case["expected_action"],
                        _case_id: str = case["id"]) -> dict[str, Any]:
            helper_calls.append({
                "question": str(question),
                "mode_arg": str(mode_arg),
                "evidence_type": type(evidence).__name__,
                "evidence_preview": text_preview(evidence, 300),
            })
            return {
                "ok": True,
                "action": _expected_action,
                "content": _sentinel,
                "response": _sentinel,
                "source": "phase69_runtime_execution_path_probe_fake_synth",
                "evidence_source": f"phase69_probe::{_case_id}",
                "report": {
                    "phase69_probe": True,
                    "sentinel": _sentinel,
                    "mode_arg": str(mode_arg),
                },
            }

        setattr(engine_mod, helper_name, fake_helper)

        case_result: dict[str, Any] = {
            "case_id": case["id"],
            "surface": case["surface"],
            "mode": mode,
            "helper": helper_name,
            "sentinel": sentinel,
        }

        try:
            result, stdout_text, stderr_text = invoke_process(engine_obj, case["prompt"], mode)
            action = extract_action(result)
            contains_sentinel = result_contains_sentinel(result, sentinel)
            trace_present = case["trace"] in stdout_text

            case_result.update({
                "ok": True,
                "result_type": type(result).__name__,
                "result_action": action,
                "result_preview": text_preview(result, 1000),
                "stdout_preview": stdout_text[-4000:],
                "stderr_preview": stderr_text[-2000:],
                "helper_call_count": len(helper_calls),
                "helper_calls": helper_calls,
                "contains_sentinel": contains_sentinel,
                "expected_trace": case["trace"],
                "trace_present": trace_present,
            })

            if mode == "quick":
                record(
                    len(helper_calls) == 0,
                    f"{case['id']} quick mode bypasses non-Quick synthesis helper",
                    f"helper_calls={len(helper_calls)}",
                )
                record(
                    not contains_sentinel,
                    f"{case['id']} quick mode does not return fake synthesized sentinel",
                    f"contains_sentinel={contains_sentinel}",
                )
            else:
                record(
                    len(helper_calls) >= 1,
                    f"{case['id']} {mode} invokes dedicated synthesis helper",
                    f"helper_calls={len(helper_calls)}",
                )
                record(
                    contains_sentinel,
                    f"{case['id']} {mode} returns synthesized branch output",
                    f"contains_sentinel={contains_sentinel}",
                )
                record(
                    action == case["expected_action"],
                    f"{case['id']} {mode} preserves expected action {case['expected_action']}",
                    f"observed_action={action}",
                )
                record(
                    trace_present,
                    f"{case['id']} {mode} emits expected non-Quick synthesis trace",
                    f"trace_present={trace_present}",
                )

        except Exception as exc:
            case_result.update({
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
                "helper_call_count": len(helper_calls),
                "helper_calls": helper_calls,
            })
            record(
                False,
                f"{case['id']} {mode} runtime process execution completes",
                f"{type(exc).__name__}: {exc}",
            )
        finally:
            setattr(engine_mod, helper_name, original_helper)

        report["cases"].append(case_result)

# ---------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------

failures = [a for a in report["assertions"] if not a["ok"]]
closed = not failures

verdict_lines = [
    "=== PHASE69 NON-QUICK GROUNDED RUNTIME EXECUTION-PATH PROOF VERDICT ===",
    f"RUNTIME_EXECUTION_PATH_PROOF_CLOSED={str(closed).upper()}",
    f"TARGETED_ASSERTION_FAILURES={len(failures)}",
    f"RUNTIME_CASE_COUNT={len(report['cases'])}",
    "",
]

if closed:
    verdict_lines.extend([
        "Conclusion:",
        "- Runtime execution-path proof is clean for all audited grounded surfaces.",
        "- Quick mode bypasses the dedicated non-Quick synthesis helpers.",
        "- Non-Quick modes invoke the expected dedicated synthesis helpers and return their synthesized branch outputs.",
        "- The Phase63/68b source-path closure is now backed by live engine branch-execution evidence.",
    ])
else:
    verdict_lines.extend([
        "Conclusion:",
        "- At least one runtime execution-path assertion failed.",
        "- Inspect the runtime case matrix and failed assertion list before applying any patch.",
        "- A failure here is now a live execution-path issue, not merely static source-shape ambiguity.",
    ])

assertion_lines = ["=== PHASE69 TARGETED ASSERTIONS ==="]
for item in report["assertions"]:
    prefix = "PASS" if item["ok"] else "FAIL"
    line = f"{prefix}: {item['label']}"
    if item["detail"]:
        line += f" — {item['detail']}"
    assertion_lines.append(line)
assertion_lines.append("")
assertion_lines.append(f"TARGETED_ASSERTION_FAILURES={len(failures)}")

case_lines = ["=== PHASE69 RUNTIME CASE MATRIX ==="]
for case in report["cases"]:
    case_lines.append("")
    case_lines.append(f"[{case.get('case_id')} | mode={case.get('mode')}]")
    case_lines.append(f"surface={case.get('surface')}")
    case_lines.append(f"ok={case.get('ok')}")
    case_lines.append(f"helper={case.get('helper')}")
    case_lines.append(f"helper_call_count={case.get('helper_call_count')}")
    if "result_action" in case:
        case_lines.append(f"result_action={case.get('result_action')}")
    if "contains_sentinel" in case:
        case_lines.append(f"contains_sentinel={case.get('contains_sentinel')}")
    if "trace_present" in case:
        case_lines.append(f"trace_present={case.get('trace_present')}")
    if case.get("error"):
        case_lines.append(f"error={case.get('error')}")

(out / "03_phase69_runtime_execution_report.json").write_text(
    json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n",
    encoding="utf-8",
)
(out / "04_phase69_verdict.txt").write_text(
    "\n".join(verdict_lines) + "\n",
    encoding="utf-8",
)
(out / "05_phase69_targeted_assertions.txt").write_text(
    "\n".join(assertion_lines) + "\n",
    encoding="utf-8",
)
(out / "06_phase69_runtime_case_matrix.txt").write_text(
    "\n".join(case_lines) + "\n",
    encoding="utf-8",
)
(out / "07_phase69_route_sanity.json").write_text(
    json.dumps(report["route_sanity"], indent=2, ensure_ascii=False, default=str) + "\n",
    encoding="utf-8",
)

print("\n".join(verdict_lines))
print()
print("\n".join(assertion_lines))
PY

{
  echo "=== PHASE69 DIGEST ==="
  cat "$OUT/04_phase69_verdict.txt"
  echo
  echo "Review:"
  echo "- 03_phase69_runtime_execution_report.json"
  echo "- 04_phase69_verdict.txt"
  echo "- 05_phase69_targeted_assertions.txt"
  echo "- 06_phase69_runtime_case_matrix.txt"
  echo "- 07_phase69_route_sanity.json"
  echo
  echo "PHASE69_OUT=$OUT"
} | tee "$OUT/08_console_digest.txt"

echo "PHASE69_OUT=$OUT"
