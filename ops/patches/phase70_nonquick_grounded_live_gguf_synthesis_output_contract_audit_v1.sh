#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase70_nonquick_grounded_live_gguf_synthesis_output_contract_audit_${STAMP}"

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
# Phase 70 — Non-Quick Grounded Live GGUF Synthesis Output Contract Audit

## Purpose

Phase69 proved runtime branch truth using sentinel helper monkeypatching.
Phase70 removes the monkeypatch and runs the real live helper paths.

This audit verifies that non-Quick grounded actions:

1. Route correctly.
2. Execute through the real engine process() path.
3. Return structured synthesized result dictionaries.
4. Preserve the expected routed action.
5. Report synthesis_validated=True on success.
6. Do not expose raw evidence/control packet content to the user-visible surface.
7. Do not collapse into the same Quick direct evidence surface.
8. Emit the expected non-Quick synthesis trace.

## Surfaces

- EXPLAIN_MEMORY_RUNTIME
- MEMORY_STATUS.recent_processing
- SELF_REPORT.recent_updates

## Modes

- quick
- chain_of_thought
- self_consistency
- tree_of_thoughts
- constitutional_ai

## Interpretation

This is a live GGUF output contract audit.
If it fails, the remaining defect is no longer router dispatch or branch selection;
it is a real output-surface or synthesis-validation defect.
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
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable

out = Path(sys.argv[1])

report: dict[str, Any] = {
    "phase": "phase70_nonquick_grounded_live_gguf_synthesis_output_contract_audit_v1",
    "engine_instantiation": {},
    "route_sanity": [],
    "quick_surfaces": {},
    "cases": [],
    "assertions": [],
    "metrics": {},
}

def record(ok: bool, label: str, detail: str = "") -> None:
    report["assertions"].append({
        "ok": bool(ok),
        "label": label,
        "detail": detail,
    })

def safe_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)

def preview(value: Any, limit: int = 1200) -> str:
    try:
        if isinstance(value, str):
            s = value
        else:
            s = safe_json(value)
    except Exception:
        s = repr(value)
    return s[:limit]

def norm_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip().lower()

def extract_action(result: Any) -> str:
    if isinstance(result, dict):
        return str(result.get("action") or "").strip().upper()
    return ""

def extract_content(result: Any) -> str:
    if isinstance(result, dict):
        return str(result.get("content") or result.get("response") or "")
    return str(result or "")

def extract_report(result: Any) -> dict[str, Any]:
    if isinstance(result, dict) and isinstance(result.get("report"), dict):
        return dict(result["report"])
    return {}

def raw_surface_hits(text: str) -> list[str]:
    low = str(text or "").lower()
    stripped = str(text or "").lstrip()

    markers = [
        '"evidence_source"',
        '"repair_reason"',
        '"synthesis_validated"',
        '"quick_direct_allowed"',
        '"direct_telemetry_returned"',
        '"process_override"',
        '"report":',
        '"action":',
        "{'action':",
        "{'ok':",
        "control evidence packet:",
        "runtime evidence packet:",
        "grounded eli self-report / recent update evidence:",
        "personal memory evidence report",
        "recent memory processing evidence",
    ]

    hits = [m for m in markers if m in low]

    if stripped.startswith("{"):
        hits.append("jsonish_object_prefix")
    if stripped.startswith("[{"):
        hits.append("jsonish_array_prefix")

    return sorted(set(hits))

def failure_surface_hits(text: str) -> list[str]:
    low = str(text or "").lower()
    markers = [
        "non-quick synthesis failed validation",
        "non-quick synthesis was not attempted",
        "evidence collection failed",
        "provider did not return a structured result",
        "synthesis failed",
        "failed validation",
    ]
    return [m for m in markers if m in low]

def find_engine_instance(engine_mod: Any) -> Any:
    attempts: list[dict[str, str]] = []

    cls = getattr(engine_mod, "CognitiveEngine", None)
    if cls is not None and inspect.isclass(cls):
        try:
            obj = cls()
            if hasattr(obj, "process") and callable(getattr(obj, "process")):
                report["engine_instantiation"] = {
                    "selected": "CognitiveEngine()",
                    "mode": "factory",
                    "attempts": attempts,
                }
                return obj
            attempts.append({
                "candidate": "CognitiveEngine()",
                "status": "returned_without_callable_process",
                "detail": repr(obj),
            })
        except Exception as exc:
            attempts.append({
                "candidate": "CognitiveEngine()",
                "status": "error",
                "detail": f"{type(exc).__name__}: {exc}",
            })

    for name in ("ENGINE", "engine", "cognitive_engine"):
        obj = getattr(engine_mod, name, None)
        if obj is not None and hasattr(obj, "process") and callable(getattr(obj, "process")):
            report["engine_instantiation"] = {
                "selected": name,
                "mode": "module_object",
                "attempts": attempts,
            }
            return obj

    for name in ("get_engine", "get_cognitive_engine", "build_engine", "create_engine"):
        fn = getattr(engine_mod, name, None)
        if callable(fn):
            try:
                obj = fn()
                if hasattr(obj, "process") and callable(getattr(obj, "process")):
                    report["engine_instantiation"] = {
                        "selected": f"{name}()",
                        "mode": "factory",
                        "attempts": attempts,
                    }
                    return obj
                attempts.append({
                    "candidate": f"{name}()",
                    "status": "returned_without_callable_process",
                    "detail": repr(obj),
                })
            except Exception as exc:
                attempts.append({
                    "candidate": f"{name}()",
                    "status": "error",
                    "detail": f"{type(exc).__name__}: {exc}",
                })

    report["engine_instantiation"] = {
        "selected": None,
        "mode": None,
        "attempts": attempts,
    }
    return None

def invoke_process(engine_obj: Any, prompt: str, mode: str) -> tuple[Any, str, str, float]:
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    t0 = time.perf_counter()

    with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
        try:
            result = engine_obj.process(prompt, reasoning_mode=mode)
        except TypeError as first_exc:
            first_detail = f"{type(first_exc).__name__}: {first_exc}"
            try:
                result = engine_obj.process(prompt, mode=mode)
                stdout_buf.write(
                    f"\n[PHASE70 invoke fallback: process(prompt, mode=...); "
                    f"primary failed: {first_detail}]\n"
                )
            except TypeError as second_exc:
                second_detail = f"{type(second_exc).__name__}: {second_exc}"
                raise RuntimeError(
                    "process() invocation failed for both keyword shapes: "
                    f"reasoning_mode -> {first_detail}; mode -> {second_detail}"
                )

    elapsed = time.perf_counter() - t0
    return result, stdout_buf.getvalue(), stderr_buf.getvalue(), elapsed

try:
    import eli.kernel.engine as engine_mod
except Exception:
    (out / "01_engine_import_failure.txt").write_text(traceback.format_exc(), encoding="utf-8")
    raise

try:
    from eli.execution.router_enhanced import route as route_fn
except Exception:
    (out / "02_router_import_failure.txt").write_text(traceback.format_exc(), encoding="utf-8")
    raise

engine_obj = find_engine_instance(engine_mod)
record(
    engine_obj is not None,
    "engine instance resolved for live GGUF output contract audit",
    safe_json(report["engine_instantiation"]),
)

if engine_obj is None:
    (out / "03_phase70_live_output_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    raise SystemExit("Phase70: could not resolve engine process() surface.")

try:
    report["engine_instantiation"]["process_signature"] = str(inspect.signature(engine_obj.process))
except Exception:
    report["engine_instantiation"]["process_signature"] = "<signature unavailable>"

CASES = [
    {
        "id": "memory_runtime_exact",
        "surface": "EXPLAIN_MEMORY_RUNTIME",
        "prompt": "Explain exactly how your memory system works internally — which files, which DB tables, which functions.",
        "expected_action": "EXPLAIN_MEMORY_RUNTIME",
        "expected_trace": "[ENGINE] EXPLAIN_MEMORY_RUNTIME non-Quick: synthesized via GGUF",
    },
    {
        "id": "recent_memory_processing",
        "surface": "MEMORY_STATUS.recent_processing",
        "prompt": "What memories have you been processing lately?",
        "expected_action": "MEMORY_STATUS",
        "expected_trace": "[ENGINE] MEMORY_STATUS recent_processing non-Quick: synthesized via GGUF",
    },
    {
        "id": "self_report_recent_updates",
        "surface": "SELF_REPORT.recent_updates",
        "prompt": "What have you been working on recently?",
        "expected_action": "SELF_REPORT",
        "expected_trace": "[ENGINE] SELF_REPORT recent_updates non-Quick: synthesized via GGUF",
    },
]

NONQUICK_MODES = [
    "chain_of_thought",
    "self_consistency",
    "tree_of_thoughts",
    "constitutional_ai",
]

# ---------------------------------------------------------------------
# Router sanity
# ---------------------------------------------------------------------

for case in CASES:
    try:
        routed = route_fn(case["prompt"])
        action = extract_action(routed)
        report["route_sanity"].append({
            "id": case["id"],
            "expected_action": case["expected_action"],
            "observed_action": action,
            "route_result": routed,
        })
        record(
            action == case["expected_action"],
            f"router sanity: {case['id']} routes to {case['expected_action']}",
            f"observed={action}",
        )
    except Exception as exc:
        report["route_sanity"].append({
            "id": case["id"],
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        })
        record(
            False,
            f"router sanity: {case['id']} route probe executes cleanly",
            f"{type(exc).__name__}: {exc}",
        )

# ---------------------------------------------------------------------
# Quick reference surfaces
# ---------------------------------------------------------------------

for case in CASES:
    case_id = case["id"]
    try:
        result, stdout_text, stderr_text, elapsed = invoke_process(engine_obj, case["prompt"], "quick")
        content = extract_content(result)
        report["quick_surfaces"][case_id] = {
            "ok": True,
            "result_type": type(result).__name__,
            "result_action": extract_action(result),
            "content": content,
            "content_preview": preview(content, 1800),
            "report": extract_report(result),
            "stdout_tail": stdout_text[-5000:],
            "stderr_tail": stderr_text[-2500:],
            "elapsed_seconds": round(elapsed, 3),
        }
        record(
            bool(content.strip()),
            f"{case_id} quick reference surface returns non-empty content",
            f"chars={len(content)}",
        )
        record(
            case["expected_trace"] not in stdout_text,
            f"{case_id} quick reference does not emit non-Quick synthesis trace",
            f"trace_present={case['expected_trace'] in stdout_text}",
        )
    except Exception as exc:
        report["quick_surfaces"][case_id] = {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }
        record(
            False,
            f"{case_id} quick reference execution completes",
            f"{type(exc).__name__}: {exc}",
        )

# ---------------------------------------------------------------------
# Real non-Quick GGUF output contract audit
# ---------------------------------------------------------------------

for case in CASES:
    quick_entry = report["quick_surfaces"].get(case["id"]) or {}
    quick_content = str(quick_entry.get("content") or "")

    for mode in NONQUICK_MODES:
        row: dict[str, Any] = {
            "case_id": case["id"],
            "surface": case["surface"],
            "mode": mode,
            "expected_action": case["expected_action"],
        }

        try:
            result, stdout_text, stderr_text, elapsed = invoke_process(engine_obj, case["prompt"], mode)

            action = extract_action(result)
            content = extract_content(result)
            meta_report = extract_report(result)

            raw_hits = raw_surface_hits(content)
            fail_hits = failure_surface_hits(content)
            trace_present = case["expected_trace"] in stdout_text
            gguf_timing_present = "[GGUF][TIMING]" in stdout_text
            content_differs_from_quick = norm_text(content) != norm_text(quick_content)

            row.update({
                "ok": True,
                "result_type": type(result).__name__,
                "result_action": action,
                "content": content,
                "content_preview": preview(content, 2200),
                "report": meta_report,
                "raw_surface_hits": raw_hits,
                "failure_surface_hits": fail_hits,
                "trace_present": trace_present,
                "gguf_timing_present": gguf_timing_present,
                "content_differs_from_quick": content_differs_from_quick,
                "stdout_tail": stdout_text[-7000:],
                "stderr_tail": stderr_text[-3000:],
                "elapsed_seconds": round(elapsed, 3),
            })

            record(
                isinstance(result, dict),
                f"{case['id']} {mode} returns structured dict result",
                f"type={type(result).__name__}",
            )
            record(
                action == case["expected_action"],
                f"{case['id']} {mode} preserves expected action {case['expected_action']}",
                f"observed={action}",
            )
            record(
                bool(content.strip()),
                f"{case['id']} {mode} returns non-empty synthesized content",
                f"chars={len(content)}",
            )
            record(
                trace_present,
                f"{case['id']} {mode} emits expected non-Quick synthesis trace",
                f"trace_present={trace_present}",
            )
            record(
                not raw_hits,
                f"{case['id']} {mode} user-visible content has no raw evidence/control packet markers",
                f"hits={raw_hits}",
            )
            record(
                not fail_hits,
                f"{case['id']} {mode} user-visible content has no synthesis failure-surface wording",
                f"hits={fail_hits}",
            )
            record(
                content_differs_from_quick,
                f"{case['id']} {mode} synthesized content differs from Quick direct surface",
                f"differs={content_differs_from_quick}",
            )

            synthesis_validated = meta_report.get("synthesis_validated")
            record(
                synthesis_validated is True,
                f"{case['id']} {mode} report.synthesis_validated is True",
                f"value={synthesis_validated!r}",
            )

            quick_direct_allowed = meta_report.get("quick_direct_allowed", False)
            record(
                bool(quick_direct_allowed) is False,
                f"{case['id']} {mode} report.quick_direct_allowed is False",
                f"value={quick_direct_allowed!r}",
            )

            direct_telemetry_returned = meta_report.get("direct_telemetry_returned", False)
            record(
                bool(direct_telemetry_returned) is False,
                f"{case['id']} {mode} report.direct_telemetry_returned is not True",
                f"value={direct_telemetry_returned!r}",
            )

            if "gguf_used" in meta_report:
                record(
                    meta_report.get("gguf_used") is True,
                    f"{case['id']} {mode} report.gguf_used is True when field is present",
                    f"value={meta_report.get('gguf_used')!r}",
                )

        except Exception as exc:
            row.update({
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            })
            record(
                False,
                f"{case['id']} {mode} live GGUF synthesis execution completes",
                f"{type(exc).__name__}: {exc}",
            )

        report["cases"].append(row)

# ---------------------------------------------------------------------
# Metrics and verdict
# ---------------------------------------------------------------------

failures = [a for a in report["assertions"] if not a["ok"]]
nonquick_rows = report["cases"]

raw_hit_count = sum(1 for r in nonquick_rows if r.get("raw_surface_hits"))
failure_surface_hit_count = sum(1 for r in nonquick_rows if r.get("failure_surface_hits"))
trace_missing_count = sum(1 for r in nonquick_rows if r.get("ok") and not r.get("trace_present"))
quick_equal_count = sum(1 for r in nonquick_rows if r.get("ok") and not r.get("content_differs_from_quick"))
gguf_timing_seen_count = sum(1 for r in nonquick_rows if r.get("gguf_timing_present"))

report["metrics"] = {
    "targeted_assertion_failures": len(failures),
    "nonquick_case_count": len(nonquick_rows),
    "raw_packet_hit_count": raw_hit_count,
    "failure_surface_hit_count": failure_surface_hit_count,
    "trace_missing_count": trace_missing_count,
    "nonquick_equal_to_quick_count": quick_equal_count,
    "gguf_timing_seen_count": gguf_timing_seen_count,
}

closed = len(failures) == 0

verdict_lines = [
    "=== PHASE70 NON-QUICK GROUNDED LIVE GGUF SYNTHESIS OUTPUT CONTRACT VERDICT ===",
    f"LIVE_GGUF_SYNTHESIS_OUTPUT_CONTRACT_CLOSED={str(closed).upper()}",
    f"TARGETED_ASSERTION_FAILURES={len(failures)}",
    f"NONQUICK_CASE_COUNT={len(nonquick_rows)}",
    f"RAW_PACKET_HIT_COUNT={raw_hit_count}",
    f"FAILURE_SURFACE_HIT_COUNT={failure_surface_hit_count}",
    f"TRACE_MISSING_COUNT={trace_missing_count}",
    f"NONQUICK_EQUAL_TO_QUICK_COUNT={quick_equal_count}",
    f"GGUF_TIMING_SEEN_COUNT={gguf_timing_seen_count}",
    "",
]

if closed:
    verdict_lines.extend([
        "Conclusion:",
        "- The real live GGUF synthesis output contract is clean for the audited grounded surfaces.",
        "- Non-Quick outputs are structured, action-preserving, validated, and distinct from Quick direct evidence surfaces.",
        "- No raw evidence/control packet markers leaked into the user-visible content.",
        "- Phase69 branch truth is now backed by real live output-surface proof.",
    ])
else:
        verdict_lines.extend([
        "Conclusion:",
        "- At least one live GGUF output contract assertion failed.",
        "- This is no longer a router or branch-selection problem.",
        "- Inspect the failed assertions, case matrix, and live output previews before patching.",
    ])

assertion_lines = ["=== PHASE70 TARGETED ASSERTIONS ==="]
for item in report["assertions"]:
    prefix = "PASS" if item["ok"] else "FAIL"
    line = f"{prefix}: {item['label']}"
    if item["detail"]:
        line += f" — {item['detail']}"
    assertion_lines.append(line)
assertion_lines.append("")
assertion_lines.append(f"TARGETED_ASSERTION_FAILURES={len(failures)}")

matrix_lines = ["=== PHASE70 LIVE OUTPUT CASE MATRIX ==="]
for row in report["cases"]:
    matrix_lines.append("")
    matrix_lines.append(f"[{row.get('case_id')} | mode={row.get('mode')}]")
    matrix_lines.append(f"surface={row.get('surface')}")
    matrix_lines.append(f"ok={row.get('ok')}")
    if row.get("error"):
        matrix_lines.append(f"error={row.get('error')}")
        continue
    matrix_lines.append(f"result_type={row.get('result_type')}")
    matrix_lines.append(f"result_action={row.get('result_action')}")
    matrix_lines.append(f"trace_present={row.get('trace_present')}")
    matrix_lines.append(f"gguf_timing_present={row.get('gguf_timing_present')}")
    matrix_lines.append(f"content_differs_from_quick={row.get('content_differs_from_quick')}")
    matrix_lines.append(f"raw_surface_hits={row.get('raw_surface_hits')}")
    matrix_lines.append(f"failure_surface_hits={row.get('failure_surface_hits')}")
    matrix_lines.append(f"elapsed_seconds={row.get('elapsed_seconds')}")
    rep = row.get("report") or {}
    matrix_lines.append(f"report.synthesis_validated={rep.get('synthesis_validated')!r}")
    matrix_lines.append(f"report.quick_direct_allowed={rep.get('quick_direct_allowed')!r}")
    matrix_lines.append(f"report.direct_telemetry_returned={rep.get('direct_telemetry_returned')!r}")
    if "gguf_used" in rep:
        matrix_lines.append(f"report.gguf_used={rep.get('gguf_used')!r}")

(out / "03_phase70_live_output_report.json").write_text(
    json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n",
    encoding="utf-8",
)
(out / "04_phase70_verdict.txt").write_text(
    "\n".join(verdict_lines) + "\n",
    encoding="utf-8",
)
(out / "05_phase70_targeted_assertions.txt").write_text(
    "\n".join(assertion_lines) + "\n",
    encoding="utf-8",
)
(out / "06_phase70_live_output_case_matrix.txt").write_text(
    "\n".join(matrix_lines) + "\n",
    encoding="utf-8",
)
(out / "07_phase70_route_sanity.json").write_text(
    json.dumps(report["route_sanity"], indent=2, ensure_ascii=False, default=str) + "\n",
    encoding="utf-8",
)
(out / "08_phase70_quick_reference_surfaces.json").write_text(
    json.dumps(report["quick_surfaces"], indent=2, ensure_ascii=False, default=str) + "\n",
    encoding="utf-8",
)

print("\n".join(verdict_lines))
print()
print("\n".join(assertion_lines))
PY

{
  echo "=== PHASE70 DIGEST ==="
  cat "$OUT/04_phase70_verdict.txt"
  echo
  echo "Review:"
  echo "- 03_phase70_live_output_report.json"
  echo "- 04_phase70_verdict.txt"
  echo "- 05_phase70_targeted_assertions.txt"
  echo "- 06_phase70_live_output_case_matrix.txt"
  echo "- 07_phase70_route_sanity.json"
  echo "- 08_phase70_quick_reference_surfaces.json"
  echo
  echo "PHASE70_OUT=$OUT"
} | tee "$OUT/09_console_digest.txt"

echo "PHASE70_OUT=$OUT"
