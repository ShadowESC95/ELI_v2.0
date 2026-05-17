#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${1:-$(pwd)}"
cd "$ROOT"

STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="ops/reports/phase19b_grounded_followup_meta_commit_${STAMP}"
mkdir -p "$OUT/backups/eli/kernel"

cp -a eli/kernel/engine.py "$OUT/backups/eli/kernel/engine.py"

python3 - <<'PY'
from pathlib import Path

path = Path("eli/kernel/engine.py")
text = path.read_text(encoding="utf-8")

marker = '# ELI_PHASE19B_COMMIT_REBOUND_META_V1'
if marker not in text:
    old = '''        meta.update({
            "matched_by": "eli.phase19.grounded_followup_rebind",
            "upgraded_from": "CHAT",
            "upgraded_reason": "prior_grounded_action_context",
            "prior_grounded_action": prior_action,
            "prior_request_id": str(prior.get("request_id") or ""),
            "grounded_followup": True,
            "grounded_followup_kind": "challenge" if challenge else "detail",
            "need_grounding": True,
            "allow_chat_without_evidence": False,
            "task_family": _eli_phase19_followup_task_family(prior_action),
        })
        current["action"] = prior_action
'''
    new = '''        meta.update({
            "matched_by": "eli.phase19.grounded_followup_rebind",
            "upgraded_from": "CHAT",
            "upgraded_reason": "prior_grounded_action_context",
            "prior_grounded_action": prior_action,
            "prior_request_id": str(prior.get("request_id") or ""),
            "grounded_followup": True,
            "grounded_followup_kind": "challenge" if challenge else "detail",
            "need_grounding": True,
            "allow_chat_without_evidence": False,
            "task_family": _eli_phase19_followup_task_family(prior_action),
        })
        # ELI_PHASE19B_COMMIT_REBOUND_META_V1
        # Phase 19 originally updated a local `meta` dict but failed to
        # persist it back into the routed intent packet. The action rebounded
        # correctly, but downstream code/tests could not see the grounded
        # follow-up contract fields.
        current["meta"] = meta
        current["action"] = prior_action
'''
    if old not in text:
        raise SystemExit("Phase 19 meta-update anchor not found; refusing blind edit.")
    text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")
PY

{
  echo "=== Phase 19b marker scan ==="
  grep -nE 'ELI_PHASE19B_COMMIT_REBOUND_META_V1|current\\["meta"\\] = meta' eli/kernel/engine.py || true
} > "$OUT/01_patch_markers.txt" 2>&1

python3 -m py_compile \
  eli/kernel/engine.py \
  tests/test_phase19_grounded_followup_truth_lock.py \
  > "$OUT/02_py_compile.txt" 2>&1

python3 -m pytest -q \
  tests/test_phase19_grounded_followup_truth_lock.py \
  tests/test_route_contracts.py \
  > "$OUT/03_pytest_phase19b_core.txt" 2>&1 || true

python3 - <<'PY' > "$OUT/04_phase19b_static_probe.txt" 2>&1
from eli.kernel.engine import _eli_phase19_rebind_grounded_followup

class Engine:
    _last_request_meta = {
        "request_id": "req-000002",
        "route_action": "RUNTIME_AUDIT",
        "result_action": "RUNTIME_AUDIT",
        "grounded": True,
        "evidence_used": True,
    }

intent = {
    "action": "CHAT",
    "args": {"message": "what are the exact lines?"},
    "confidence": 0.85,
    "meta": {"matched_by": "chat.long_question_guard"},
}

print(_eli_phase19_rebind_grounded_followup(
    Engine(),
    "what are the exact lines of the duplicates, can you fix it?",
    intent,
))
PY

{
  echo "# Phase 19b Grounded Follow-up Metadata Commit"
  echo
  echo "Date: $(date -Is)"
  echo "Root: $ROOT"
  echo
  echo "## Purpose"
  echo "- Persist Phase 19 rebound metadata into intent['meta']."
  echo "- Resolve the two new regression-test failures:"
  echo "  - missing grounded_followup"
  echo "  - missing grounded_followup_kind"
  echo "- Preserve the already-working RUNTIME_AUDIT action rebound."
  echo
  echo "## Outputs"
  echo "- 01_patch_markers.txt"
  echo "- 02_py_compile.txt"
  echo "- 03_pytest_phase19b_core.txt"
  echo "- 04_phase19b_static_probe.txt"
} > "$OUT/SUMMARY.md"

echo
cat "$OUT/SUMMARY.md"
echo
echo "Report directory: $OUT"
