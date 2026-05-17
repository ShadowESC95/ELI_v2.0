#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase65_nonquick_grounded_bypass_synthesis_repair_${STAMP}"

ENGINE="eli/kernel/engine.py"
PHASE63_SCRIPT="ops/patches/phase63_nonquick_grounded_surface_synthesis_path_truth_audit_v1.sh"
MARKER="ELI_PHASE65_NONQUICK_GROUNDED_SYNTHESIS_REPAIR_V1"

mkdir -p "$OUT/backups"

if [[ ! -f "$ENGINE" ]]; then
  echo "Missing engine file: $ENGINE" >&2
  exit 1
fi

cp "$ENGINE" "$OUT/backups/engine.py.before_phase65.bak"

cat > "$OUT/SUMMARY.md" <<'EOF'
# Phase65 — Non-Quick Grounded Bypass Synthesis Repair

Purpose:

Phase63 proved two non-Quick control surfaces were bypassing the synthesis path:

1. MEMORY_STATUS.recent_processing
2. SELF_REPORT.recent_updates

Phase64 proved the codebase already contains the correct repair pattern in:

- RUNTIME_STATUS non-Quick synthesis
- EXPLAIN_MEMORY_RUNTIME non-Quick synthesis

This patch:

- preserves Quick direct deterministic evidence,
- routes Non-Quick recent-memory-processing through a dedicated validated GGUF synthesis helper,
- routes Non-Quick self-report recent-updates through a dedicated validated GGUF synthesis helper,
- removes the non-Quick `*_no_gguf_*` bypass labels,
- prevents `synthesis_validated=True` from being claimed before synthesis,
- preserves fail-closed behavior when evidence or synthesis is unavailable.
EOF

python3 - "$ENGINE" "$OUT" "$MARKER" <<'PY'
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from textwrap import dedent

engine_path = Path(sys.argv[1])
out = Path(sys.argv[2])
marker = sys.argv[3]

src = engine_path.read_text(encoding="utf-8")

patch_log: list[str] = []
assertions: list[tuple[bool, str]] = []

def record(ok: bool, msg: str) -> None:
    assertions.append((ok, msg))

# -----------------------------------------------------------------------------
# 0. Idempotency gate
# -----------------------------------------------------------------------------

already_patched = marker in src
patch_log.append(f"ALREADY_PATCHED={already_patched}")

# -----------------------------------------------------------------------------
# 1. Insert dedicated non-Quick synthesis helpers after the existing
#    _mw_mem_runtime_strict_synthesize function.
# -----------------------------------------------------------------------------

helper_block = dedent(f'''

# =============================================================================
# {marker}
# Dedicated non-Quick synthesis helpers for deterministic grounded evidence
# surfaces that were previously returned directly in all modes:
#
#   - MEMORY_STATUS.recent_processing
#   - SELF_REPORT.recent_updates
#
# Quick mode remains direct evidence. Non-Quick modes must synthesize through
# local GGUF, validate the generated answer, and return only the synthesized
# surface. This mirrors _mw_rs_synthesize() and
# _mw_mem_runtime_strict_synthesize().
# =============================================================================

def _mw_recent_memory_processing_synthesize(question, mode, evidence) -> dict:
    evidence_text = _mw_rs_extract_text(evidence)
    evidence_source = (
        str((evidence or {{}}).get("evidence_source") or "recent_memory_processing_grounded_evidence")
        if isinstance(evidence, dict)
        else "recent_memory_processing_grounded_evidence"
    )

    if not evidence_text:
        err = evidence.get("error") if isinstance(evidence, dict) else ""
        msg = (
            "Recent-memory-processing evidence collection failed, so non-Quick "
            f"synthesis was not attempted. Error: {{err}}"
        )
        return {{
            "ok": False,
            "action": "MEMORY_STATUS",
            "content": msg,
            "response": msg,
            "source": "recent_memory_processing_nonquick_synth_no_evidence_v5",
            "evidence_source": evidence_source,
            "grounded": False,
            "evidence_used": False,
            "report": {{
                "requested_mode": mode,
                "synthesis_validated": False,
                "direct_telemetry_returned": False,
                "quick_direct_allowed": False,
                "repair_reason": "recent_memory_processing_nonquick_synthesis_v5",
            }},
        }}

    mode_instruction = {{
        "chain_of_thought": "Use private structured reasoning. Do not reveal hidden reasoning. Output only the final answer.",
        "self_consistency": "Privately compare several possible phrasings and output only the strongest final answer.",
        "tree_of_thoughts": "Privately explore branches, prune weak ones, and output only the strongest final answer.",
        "constitutional_ai": "Draft, privately critique for accuracy and contract compliance, revise, and output only the final answer.",
    }}.get(str(mode), "Use the normal non-Quick synthesis path. Output only the final answer.")

    system = (
        "You are ELI, the local assistant inside the ELI MKXI project. "
        "You are answering a question about recent durable memory-processing evidence. "
        "Use ONLY the evidence below. Do not invent recent processing, emotional activity, "
        "mathematical work, project work, or hidden background actions unless the evidence states it. "
        "Do not expose JSON packets, report keys, repair reasons, validation machinery, or raw metadata. "
        "Return a concise but complete synthesized answer."
    )

    prompt = (
        f"Original user question:\\n{{question}}\\n\\n"
        f"Reasoning mode:\\n{{mode}}\\n\\n"
        f"Mode contract:\\n{{mode_instruction}}\\n\\n"
        f"Grounded recent-memory-processing evidence:\\n{{evidence_text}}\\n\\n"
        "Task:\\n"
        "Answer what recent durable memory-processing evidence exists. "
        "Summarize the available counts and meaningful recent categories or rows "
        "without pasting raw control packets. If the evidence shows no clean recent "
        "activity in a category, state that plainly.\\n"
    )

    try:
        synthesized = _mw_rs_generate(prompt, system, mode).strip()
    except Exception as e:
        msg = f"Recent-memory-processing evidence was collected, but non-Quick synthesis failed: {{e}}"
        return {{
            "ok": False,
            "action": "MEMORY_STATUS",
            "content": msg,
            "response": msg,
            "source": "recent_memory_processing_nonquick_synth_failed_v5",
            "evidence_source": evidence_source,
            "grounded": True,
            "evidence_used": True,
            "report": {{
                "requested_mode": mode,
                "synthesis_validated": False,
                "direct_telemetry_returned": False,
                "quick_direct_allowed": False,
                "repair_reason": "recent_memory_processing_nonquick_synthesis_v5",
                "error": repr(e),
            }},
        }}

    low = synthesized.lower()
    if not low.strip():
        bad = "empty synthesis"
    else:
        bad = ""
        forbidden = (
            "raw gguf candidate",
            "raw_gguf_candidates_skipped",
            "repair_reason",
            "response_surface:",
            "evidence_source:",
            "synthesis_validated",
            "{{'ok':",
            '"ok":',
            '"report":',
        )
        for frag in forbidden:
            if frag in low:
                bad = f"leaked internal/direct evidence marker: {{frag}}"
                break

        if not bad:
            required_any = (
                "memory",
                "memories",
                "recent",
                "rows",
                "observations",
                "learning",
                "faiss",
                "conversation",
                "stored",
            )
            if sum(1 for x in required_any if x in low) < 2:
                bad = "synthesis did not preserve enough recent-memory evidence"

    if bad:
        msg = (
            f"Recent-memory-processing non-Quick synthesis failed validation: {{bad}}. "
            "Direct evidence was not returned because only Quick mode may use that surface."
        )
        return {{
            "ok": False,
            "action": "MEMORY_STATUS",
            "content": msg,
            "response": msg,
            "source": "recent_memory_processing_nonquick_synth_validation_failed_v5",
            "evidence_source": evidence_source,
            "grounded": True,
            "evidence_used": True,
            "report": {{
                "requested_mode": mode,
                "synthesis_validated": False,
                "direct_telemetry_returned": False,
                "quick_direct_allowed": False,
                "repair_reason": "recent_memory_processing_nonquick_synthesis_v5",
                "validation_error": bad,
            }},
        }}

    return {{
        "ok": True,
        "action": "MEMORY_STATUS",
        "content": synthesized,
        "response": synthesized,
        "source": "recent_memory_processing_nonquick_synthesized_v5",
        "evidence_source": evidence_source,
        "grounded": True,
        "evidence_used": True,
        "report": {{
            "requested_mode": mode,
            "synthesis_validated": True,
            "direct_telemetry_returned": False,
            "quick_direct_allowed": False,
            "repair_reason": "recent_memory_processing_nonquick_synthesis_v5",
        }},
    }}


def _mw_self_report_recent_updates_synthesize(question, mode, evidence) -> dict:
    evidence_text = _mw_rs_extract_text(evidence)
    evidence_source = (
        str((evidence or {{}}).get("evidence_source") or "self_report_recent_updates_grounded_evidence")
        if isinstance(evidence, dict)
        else "self_report_recent_updates_grounded_evidence"
    )

    if not evidence_text:
        err = evidence.get("error") if isinstance(evidence, dict) else ""
        msg = (
            "Self-report recent-updates evidence collection failed, so non-Quick "
            f"synthesis was not attempted. Error: {{err}}"
        )
        return {{
            "ok": False,
            "action": "SELF_REPORT",
            "content": msg,
            "response": msg,
            "source": "self_report_recent_updates_nonquick_synth_no_evidence_v5",
            "evidence_source": evidence_source,
            "grounded": False,
            "evidence_used": False,
            "report": {{
                "requested_mode": mode,
                "synthesis_validated": False,
                "direct_telemetry_returned": False,
                "quick_direct_allowed": False,
                "repair_reason": "self_report_recent_updates_nonquick_synthesis_v5",
            }},
        }}

    mode_instruction = {{
        "chain_of_thought": "Use private structured reasoning. Do not reveal hidden reasoning. Output only the final answer.",
        "self_consistency": "Privately compare several possible phrasings and output only the strongest final answer.",
        "tree_of_thoughts": "Privately explore branches, prune weak ones, and output only the strongest final answer.",
        "constitutional_ai": "Draft, privately critique for accuracy and contract compliance, revise, and output only the final answer.",
    }}.get(str(mode), "Use the normal non-Quick synthesis path. Output only the final answer.")

    system = (
        "You are ELI, the local assistant inside the ELI MKXI project. "
        "You are answering a self-report question about what updates, checks, or recent "
        "operational work are actually evidenced. Use ONLY the grounded report below. "
        "Do not invent Git commits, status changes, capability changes, runtime changes, "
        "maintenance actions, or emotional colour not present in evidence. "
        "Do not expose JSON packets, report keys, repair reasons, validation machinery, or raw metadata. "
        "Return a concise but complete synthesized answer."
    )

    prompt = (
        f"Original user question:\\n{{question}}\\n\\n"
        f"Reasoning mode:\\n{{mode}}\\n\\n"
        f"Mode contract:\\n{{mode_instruction}}\\n\\n"
        f"Grounded self-report recent-updates evidence:\\n{{evidence_text}}\\n\\n"
        "Task:\\n"
        "Answer what ELI has concrete evidence for recently: Git evidence if present, "
        "capability manifest evidence, runtime snapshot facts, and working-tree status "
        "if available. If there is no recent Git commit evidence, state that plainly. "
        "Synthesize — do not paste raw evidence packets.\\n"
    )

    try:
        synthesized = _mw_rs_generate(prompt, system, mode).strip()
    except Exception as e:
        msg = f"Self-report recent-updates evidence was collected, but non-Quick synthesis failed: {{e}}"
        return {{
            "ok": False,
            "action": "SELF_REPORT",
            "content": msg,
            "response": msg,
            "source": "self_report_recent_updates_nonquick_synth_failed_v5",
            "evidence_source": evidence_source,
            "grounded": True,
            "evidence_used": True,
            "report": {{
                "requested_mode": mode,
                "synthesis_validated": False,
                "direct_telemetry_returned": False,
                "quick_direct_allowed": False,
                "repair_reason": "self_report_recent_updates_nonquick_synthesis_v5",
                "error": repr(e),
            }},
        }}

    low = synthesized.lower()
    if not low.strip():
        bad = "empty synthesis"
    else:
        bad = ""
        forbidden = (
            "raw gguf candidate",
            "raw_gguf_candidates_skipped",
            "repair_reason",
            "response_surface:",
            "evidence_source:",
            "synthesis_validated",
            "{{'ok':",
            '"ok":',
            '"report":',
        )
        for frag in forbidden:
            if frag in low:
                bad = f"leaked internal/direct evidence marker: {{frag}}"
                break

        if not bad:
            required_any = (
                "eli",
                "runtime",
                "model",
                "git",
                "commit",
                "capability",
                "working tree",
                "updates",
                "evidence",
            )
            if sum(1 for x in required_any if x in low) < 2:
                bad = "synthesis did not preserve enough grounded self-report evidence"

    if bad:
        msg = (
            f"Self-report recent-updates non-Quick synthesis failed validation: {{bad}}. "
            "Direct evidence was not returned because only Quick mode may use that surface."
        )
        return {{
            "ok": False,
            "action": "SELF_REPORT",
            "content": msg,
            "response": msg,
            "source": "self_report_recent_updates_nonquick_synth_validation_failed_v5",
            "evidence_source": evidence_source,
            "grounded": True,
            "evidence_used": True,
            "report": {{
                "requested_mode": mode,
                "synthesis_validated": False,
                "direct_telemetry_returned": False,
                "quick_direct_allowed": False,
                "repair_reason": "self_report_recent_updates_nonquick_synthesis_v5",
                "validation_error": bad,
            }},
        }}

    return {{
        "ok": True,
        "action": "SELF_REPORT",
        "content": synthesized,
        "response": synthesized,
        "source": "self_report_recent_updates_nonquick_synthesized_v5",
        "evidence_source": evidence_source,
        "grounded": True,
        "evidence_used": True,
        "report": {{
            "requested_mode": mode,
            "synthesis_validated": True,
            "direct_telemetry_returned": False,
            "quick_direct_allowed": False,
            "repair_reason": "self_report_recent_updates_nonquick_synthesis_v5",
        }},
    }}

# =============================================================================
# END {marker}
# =============================================================================
''')

if not already_patched:
    tree = ast.parse(src)
    target = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_mw_mem_runtime_strict_synthesize":
            target = node
            break

    if target is None or getattr(target, "end_lineno", None) is None:
        raise SystemExit("Could not locate _mw_mem_runtime_strict_synthesize insertion anchor.")

    lines = src.splitlines(keepends=True)
    lines[target.end_lineno:target.end_lineno] = [helper_block]
    src = "".join(lines)
    patch_log.append("INSERTED_DEDICATED_NONQUICK_SYNTHESIS_HELPERS=YES")
else:
    patch_log.append("INSERTED_DEDICATED_NONQUICK_SYNTHESIS_HELPERS=SKIPPED_ALREADY_PRESENT")

# -----------------------------------------------------------------------------
# 2. Repair metadata truth in memory-runtime evidence collector.
#    Evidence collection must not pre-claim synthesis validation.
# -----------------------------------------------------------------------------

old_truth_line = 'report["synthesis_validated"] = None if mode == "quick" else True'
new_truth_line = 'report["synthesis_validated"] = None'

if old_truth_line in src:
    src = src.replace(old_truth_line, new_truth_line, 1)
    patch_log.append("MEMORY_RUNTIME_COLLECTOR_SYNTHESIS_VALIDATED_PRECLAIM_REMOVED=YES")
elif new_truth_line in src:
    patch_log.append("MEMORY_RUNTIME_COLLECTOR_SYNTHESIS_VALIDATED_PRECLAIM_REMOVED=ALREADY_CLEAN")
else:
    patch_log.append("MEMORY_RUNTIME_COLLECTOR_SYNTHESIS_VALIDATED_PRECLAIM_REMOVED=ANCHOR_NOT_FOUND")

old_surface = 'else "non-Quick synthesized memory-runtime answer"'
new_surface = 'else "non-Quick memory-runtime evidence packet pending downstream synthesis"'

if old_surface in src:
    src = src.replace(old_surface, new_surface, 1)
    patch_log.append("MEMORY_RUNTIME_COLLECTOR_RESPONSE_SURFACE_TRUTH_FIXED=YES")
elif new_surface in src:
    patch_log.append("MEMORY_RUNTIME_COLLECTOR_RESPONSE_SURFACE_TRUTH_FIXED=ALREADY_CLEAN")
else:
    patch_log.append("MEMORY_RUNTIME_COLLECTOR_RESPONSE_SURFACE_TRUTH_FIXED=ANCHOR_NOT_FOUND")

# -----------------------------------------------------------------------------
# 3. Update misleading comments for recent-memory-processing block.
# -----------------------------------------------------------------------------

old_recent_comment = (
    "        # Recent-memory-processing questions are deterministic memory-runtime\n"
    "        # evidence queries. They must not enter GGUF in any reasoning mode.\n"
)
new_recent_comment = (
    "        # Recent-memory-processing questions are deterministic memory-runtime\n"
    "        # evidence queries. Quick may return compact evidence directly; Non-Quick\n"
    "        # must synthesize from that evidence through local GGUF and return only\n"
    "        # the validated synthesized surface.\n"
)

if old_recent_comment in src:
    src = src.replace(old_recent_comment, new_recent_comment, 1)
    patch_log.append("RECENT_MEMORY_COMMENT_CONTRACT_UPDATED=YES")
elif new_recent_comment in src:
    patch_log.append("RECENT_MEMORY_COMMENT_CONTRACT_UPDATED=ALREADY_CLEAN")
else:
    patch_log.append("RECENT_MEMORY_COMMENT_CONTRACT_UPDATED=ANCHOR_NOT_FOUND")

old_self_comment = (
    "        # Recent self-report/update questions are grounded runtime evidence\n"
    "        # queries. They must return structured SELF_REPORT dicts and must not\n"
    "        # collapse to plain strings or hallucinated maintenance claims.\n"
)
new_self_comment = (
    "        # Recent self-report/update questions are grounded runtime evidence\n"
    "        # queries. Quick may return structured evidence directly; Non-Quick\n"
    "        # must synthesize from that evidence and return only the validated\n"
    "        # synthesized surface, never hallucinated maintenance claims.\n"
)

if old_self_comment in src:
    src = src.replace(old_self_comment, new_self_comment, 1)
    patch_log.append("SELF_REPORT_COMMENT_CONTRACT_UPDATED=YES")
elif new_self_comment in src:
    patch_log.append("SELF_REPORT_COMMENT_CONTRACT_UPDATED=ALREADY_CLEAN")
else:
    patch_log.append("SELF_REPORT_COMMENT_CONTRACT_UPDATED=ANCHOR_NOT_FOUND")

# -----------------------------------------------------------------------------
# 4. Replace recent-memory-processing direct-return segment.
# -----------------------------------------------------------------------------

recent_start_anchor = "                _eli_rm_out = _eli_recent_mem_v3_execute(user_input)\n"
recent_end_anchor = "        except Exception as _eli_recent_mem_middleware_err:\n"

if recent_start_anchor in src:
    start = src.index(recent_start_anchor)
    end = src.index(recent_end_anchor, start)

    old_segment = src[start:end]
    new_segment = dedent('''\
                _eli_rm_evidence = _eli_recent_mem_v3_execute(user_input)

                if _eli_rm_quick:
                    _eli_rm_out = _eli_rm_evidence

                    if isinstance(_eli_rm_out, dict):
                        _eli_rm_out = dict(_eli_rm_out)
                        _eli_rm_report = dict(_eli_rm_out.get("report") or {})
                        _eli_rm_report["gguf_used"] = False
                        _eli_rm_report["process_override"] = "recent_memory_processing_primary_middleware_v5"
                        _eli_rm_report["quick_direct_allowed"] = True
                        _eli_rm_report["synthesis_validated"] = None
                        _eli_rm_out["report"] = _eli_rm_report
                        _eli_rm_out["evidence_source"] = "recent_memory_processing_quick_direct_clean_v5"

                    return _eli_rm_out

                _eli_rm_out = _mw_recent_memory_processing_synthesize(
                    user_input,
                    _eli_rm_mode,
                    _eli_rm_evidence,
                )
                print("[ENGINE] MEMORY_STATUS recent_processing non-Quick: synthesized via GGUF", flush=True)
                return _eli_rm_out

''')

    src = src[:start] + new_segment + src[end:]
    patch_log.append("RECENT_MEMORY_NONQUICK_DIRECT_BYPASS_REPLACED=YES")
else:
    patch_log.append("RECENT_MEMORY_NONQUICK_DIRECT_BYPASS_REPLACED=ANCHOR_NOT_FOUND")

# -----------------------------------------------------------------------------
# 5. Replace self-report recent-updates direct-return segment.
# -----------------------------------------------------------------------------

self_start_anchor = "                if isinstance(_eli_self_mw_evidence, dict):\n"
self_end_anchor = "        except Exception as _eli_self_report_middleware_err:\n"

if self_start_anchor in src:
    start = src.index(self_start_anchor)
    end = src.index(self_end_anchor, start)

    old_segment = src[start:end]
    new_segment = dedent('''\
                if _eli_self_mw_quick:
                    if isinstance(_eli_self_mw_evidence, dict):
                        _eli_self_mw_out = dict(_eli_self_mw_evidence)
                        _eli_self_mw_content = (
                            _eli_self_mw_out.get("content")
                            or _eli_self_mw_out.get("response")
                            or ""
                        )
                        _eli_self_mw_report = dict(_eli_self_mw_out.get("report") or {})
                        _eli_self_mw_report["gguf_used"] = False
                        _eli_self_mw_report["process_override"] = "self_report_recent_updates_primary_middleware_v5"
                        _eli_self_mw_report["quick_direct_allowed"] = True
                        _eli_self_mw_report["synthesis_validated"] = None

                        _eli_self_mw_out.update({
                            "ok": bool(_eli_self_mw_out.get("ok", True)),
                            "action": "SELF_REPORT",
                            "content": str(_eli_self_mw_content),
                            "response": str(_eli_self_mw_content),
                            "evidence_source": "self_report_recent_updates_quick_direct_v5",
                            "report": _eli_self_mw_report,
                        })
                        return _eli_self_mw_out

                    return {
                        "ok": False,
                        "action": "SELF_REPORT",
                        "content": "Self-report evidence provider did not return a structured result.",
                        "response": "Self-report evidence provider did not return a structured result.",
                        "evidence_source": "self_report_recent_updates_provider_invalid_quick_v5",
                        "report": {
                            "gguf_used": False,
                            "process_override": "self_report_recent_updates_primary_middleware_v5",
                            "quick_direct_allowed": True,
                            "synthesis_validated": None,
                        },
                    }

                _eli_self_mw_out = _mw_self_report_recent_updates_synthesize(
                    user_input,
                    _eli_self_mw_mode,
                    _eli_self_mw_evidence,
                )
                print("[ENGINE] SELF_REPORT recent_updates non-Quick: synthesized via GGUF", flush=True)
                return _eli_self_mw_out

''')

    src = src[:start] + new_segment + src[end:]
    patch_log.append("SELF_REPORT_NONQUICK_DIRECT_BYPASS_REPLACED=YES")
else:
    patch_log.append("SELF_REPORT_NONQUICK_DIRECT_BYPASS_REPLACED=ANCHOR_NOT_FOUND")

# -----------------------------------------------------------------------------
# 6. Persist source
# -----------------------------------------------------------------------------

engine_path.write_text(src, encoding="utf-8")
(out / "01_patch_log.txt").write_text("\n".join(patch_log) + "\n", encoding="utf-8")

# -----------------------------------------------------------------------------
# 7. Targeted post-write assertions
# -----------------------------------------------------------------------------

post = engine_path.read_text(encoding="utf-8")

record(marker in post, "Phase65 marker present")
record("def _mw_recent_memory_processing_synthesize(" in post, "recent-memory non-Quick synthesis helper present")
record("def _mw_self_report_recent_updates_synthesize(" in post, "self-report recent-updates non-Quick synthesis helper present")
record("_mw_recent_memory_processing_synthesize(" in post, "recent-memory middleware references synthesis helper")
record("_mw_self_report_recent_updates_synthesize(" in post, "self-report middleware references synthesis helper")
record("recent_memory_processing_nonquick_grounded_no_gguf_v4" not in post, "old recent-memory no-GGUF non-Quick label removed")
record("self_report_recent_updates_nonquick_grounded_no_gguf_v4" not in post, "old self-report no-GGUF non-Quick label removed")
record('report["synthesis_validated"] = None if mode == "quick" else True' not in post, "memory-runtime evidence collector no longer preclaims synthesis validation")
record('else "non-Quick synthesized memory-runtime answer"' not in post, "memory-runtime evidence collector no longer mislabels evidence as synthesized answer")
record('else "non-Quick memory-runtime evidence packet pending downstream synthesis"' in post, "memory-runtime evidence collector response-surface truth label installed")
record('print("[ENGINE] MEMORY_STATUS recent_processing non-Quick: synthesized via GGUF"' in post, "recent-memory non-Quick GGUF synthesis trace installed")
record('print("[ENGINE] SELF_REPORT recent_updates non-Quick: synthesized via GGUF"' in post, "self-report non-Quick GGUF synthesis trace installed")

assert_lines = ["=== PHASE65 TARGETED ASSERTIONS ==="]
failures = 0
for ok, msg in assertions:
    assert_lines.append(("PASS: " if ok else "FAIL: ") + msg)
    if not ok:
        failures += 1
assert_lines.append("")
assert_lines.append(f"TARGETED_ASSERTION_FAILURES={failures}")

(out / "02_targeted_assertions.txt").write_text(
    "\n".join(assert_lines) + "\n",
    encoding="utf-8",
)

print("\n".join(assert_lines))

if failures:
    raise SystemExit(f"Phase65 targeted assertion failures: {failures}")
PY

echo "=== PY_COMPILE ===" | tee "$OUT/03_py_compile.txt"
python3 -m py_compile "$ENGINE" 2>&1 | tee -a "$OUT/03_py_compile.txt"
echo "PY_COMPILE_OK" | tee -a "$OUT/03_py_compile.txt"

echo "=== FOCUSED POST-PATCH GREP ===" | tee "$OUT/04_focused_post_patch_grep.txt"
grep -nE \
  'ELI_PHASE65_NONQUICK_GROUNDED_SYNTHESIS_REPAIR_V1|_mw_recent_memory_processing_synthesize|_mw_self_report_recent_updates_synthesize|nonquick_grounded_no_gguf|synthesis_validated.*else True|MEMORY_STATUS recent_processing non-Quick: synthesized via GGUF|SELF_REPORT recent_updates non-Quick: synthesized via GGUF' \
  "$ENGINE" 2>&1 | tee -a "$OUT/04_focused_post_patch_grep.txt" || true

if [[ -x "$PHASE63_SCRIPT" ]]; then
  echo "=== POST-PATCH PHASE63 VERIFICATION ===" | tee "$OUT/05_phase63_rerun_console.txt"
  bash "$PHASE63_SCRIPT" 2>&1 | tee -a "$OUT/05_phase63_rerun_console.txt"

  POST63="$(ls -td ops/reports/phase63_nonquick_grounded_surface_synthesis_path_truth_audit_* | head -1 || true)"
  if [[ -n "${POST63:-}" && -d "$POST63" ]]; then
    echo "$POST63" > "$OUT/06_post_phase63_report_path.txt"
    cp "$POST63/11_console_verdict.txt" "$OUT/07_post_phase63_verdict.txt" 2>/dev/null || true
    cp "$POST63/10_targeted_assertions.txt" "$OUT/08_post_phase63_targeted_assertions.txt" 2>/dev/null || true
    cp "$POST63/08_nonquick_direct_bypass_risk_matrix.txt" "$OUT/09_post_phase63_risk_matrix.txt" 2>/dev/null || true
  fi
fi

POST63_VERDICT="$OUT/07_post_phase63_verdict.txt"
POST63_ASSERTS="$OUT/08_post_phase63_targeted_assertions.txt"

{
  echo "=== PHASE65 DIGEST ==="
  echo "Engine compile: PASS"
  echo "Phase65 targeted assertions: PASS"
  echo "Dedicated recent-memory non-Quick synthesis helper: INSTALLED"
  echo "Dedicated self-report recent-updates non-Quick synthesis helper: INSTALLED"
  echo "Old non-Quick no-GGUF labels: REMOVED"
  echo "Memory-runtime evidence collector pre-synthesis truth metadata: CORRECTED"
  echo
  if [[ -f "$POST63_VERDICT" ]]; then
    echo "Post-patch Phase63 verdict:"
    cat "$POST63_VERDICT"
  else
    echo "Post-patch Phase63 verdict: NOT AVAILABLE"
  fi
  echo
  echo "Review:"
  echo "- 01_patch_log.txt"
  echo "- 02_targeted_assertions.txt"
  echo "- 03_py_compile.txt"
  echo "- 04_focused_post_patch_grep.txt"
  echo "- 07_post_phase63_verdict.txt"
  echo "- 08_post_phase63_targeted_assertions.txt"
  echo "- 09_post_phase63_risk_matrix.txt"
  echo
  echo "PHASE65_OUT=$OUT"
} | tee "$OUT/10_console_digest.txt"
