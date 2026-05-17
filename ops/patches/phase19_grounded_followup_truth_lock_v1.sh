#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${1:-$(pwd)}"
cd "$ROOT"

STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="ops/reports/phase19_grounded_followup_truth_lock_${STAMP}"
mkdir -p "$OUT/backups/eli/kernel" "$OUT/backups/eli/runtime" "$OUT/backups/eli/cognition" "$OUT/backups/tests"

cp -a eli/kernel/engine.py "$OUT/backups/eli/kernel/engine.py"
cp -a eli/runtime/control_contracts.py "$OUT/backups/eli/runtime/control_contracts.py"
cp -a eli/cognition/output_governor.py "$OUT/backups/eli/cognition/output_governor.py"
[[ -f tests/test_phase19_grounded_followup_truth_lock.py ]] && cp -a tests/test_phase19_grounded_followup_truth_lock.py "$OUT/backups/tests/test_phase19_grounded_followup_truth_lock.py" || true

python3 - <<'PY'
from __future__ import annotations
from pathlib import Path
import textwrap

root = Path('.')
engine = root / 'eli/kernel/engine.py'
control = root / 'eli/runtime/control_contracts.py'
governor = root / 'eli/cognition/output_governor.py'
testfile = root / 'tests/test_phase19_grounded_followup_truth_lock.py'

# ---------------------------------------------------------------------
# 1) Engine: rebind contextual follow-ups to the previous grounded action.
# ---------------------------------------------------------------------
text = engine.read_text(encoding='utf-8')
marker = '# === ELI_PHASE19_GROUNDED_FOLLOWUP_REBIND_V1 ==='
if marker not in text:
    insert_before = 'def _classify_query(text: str, action: str) -> str:\n'
    if insert_before not in text:
        raise SystemExit('engine insertion anchor not found: _classify_query')
    helper = textwrap.dedent(r'''
    # === ELI_PHASE19_GROUNDED_FOLLOWUP_REBIND_V1 ===
    # Contextual detail/challenge turns after an authoritative grounded action
    # must remain attached to that action. Without this, prompts such as
    # "what are the exact lines?", "can you fix it?", or "are you lying?"
    # fell through to generic CHAT and the model fabricated concrete details.
    _ELI_PHASE19_GROUNDED_FOLLOWUP_ACTIONS = {
        "RUNTIME_AUDIT",
        "IMPORT_AUDIT",
        "GUI_RUNTIME_AUDIT",
        "RESOLVE_RUNTIME_PATHS",
        "RUNTIME_STATUS",
        "EXPLAIN_MEMORY_RUNTIME",
        "EXPLAIN_COGNITION_RUNTIME",
        "EXPLAIN_LAST_RESPONSE",
        "SELF_REPORT",
        "USER_IDENTITY_SUMMARY",
        "PERSONAL_MEMORY_SUMMARY",
        "PERSONAL_MEMORY_DEEP_EXPLAIN",
        "ROUTING_FAULT_EXPLAIN",
        "NAME_SOURCE_AUDIT",
    }

    _ELI_PHASE19_DETAIL_FOLLOWUP_RX = re.compile(
        r"(?:"
        r"^\s*please\s+do\b"
        r"|\b(?:exact|where|which|what|show|tell|give|can\s+you|could\s+you)\b.{0,100}"
        r"\b(?:line|lines|file|files|path|paths|issue|issues|duplicate|duplicates|finding|findings|report|result|results|fix|repair|remove|delete)\b"
        r"|\b(?:issue|issues|duplicate|duplicates|finding|findings)\b.{0,100}"
        r"\b(?:where|line|lines|file|files|fix|repair|remove|delete)\b"
        r")",
        re.IGNORECASE | re.DOTALL,
    )

    _ELI_PHASE19_CHALLENGE_FOLLOWUP_RX = re.compile(
        r"\b(?:"
        r"are\s+you\s+(?:lying|lieing)\s+to\s+me"
        r"|you\s+(?:lied|made\s+that\s+up|invented\s+that|fabricated\s+that)"
        r"|that(?:'s|\s+is)\s+(?:wrong|false|not\s+correct|incorrect)"
        r"|thats\s+funny\s+because"
        r"|that(?:'s|\s+is)\s+funny\s+because"
        r"|verify\s+that"
        r"|check\s+that\s+again"
        r"|double[-\s]?check\s+that"
        r"|look\s+again"
        r")\b",
        re.IGNORECASE,
    )

    def _eli_phase19_followup_task_family(action: str) -> str:
        act = str(action or "").upper()
        if act in {"RUNTIME_AUDIT", "IMPORT_AUDIT", "GUI_RUNTIME_AUDIT", "RESOLVE_RUNTIME_PATHS"}:
            return "grounded_audit"
        if act in {"RUNTIME_STATUS", "SELF_REPORT", "USER_IDENTITY_SUMMARY"}:
            return "grounded_status"
        return "grounded_diagnostic"

    def _eli_phase19_rebind_grounded_followup(engine, user_input: str, intent: Dict[str, Any]) -> Dict[str, Any]:
        current = dict(intent or {})
        if str(current.get("action") or "CHAT").upper() != "CHAT":
            return current

        try:
            prior = dict(getattr(engine, "_last_request_meta", {}) or {})
        except Exception:
            prior = {}
        if not prior:
            return current
        if not bool(prior.get("grounded")) or not bool(prior.get("evidence_used")):
            return current

        prior_action = str(
            prior.get("route_action")
            or prior.get("result_action")
            or prior.get("action")
            or ""
        ).strip().upper()
        if prior_action not in _ELI_PHASE19_GROUNDED_FOLLOWUP_ACTIONS:
            return current

        raw = str(user_input or "")
        low = re.sub(r"\s+", " ", raw.lower()).strip()
        if not low:
            return current

        contextual_detail = bool(_ELI_PHASE19_DETAIL_FOLLOWUP_RX.search(low))
        challenge = bool(_ELI_PHASE19_CHALLENGE_FOLLOWUP_RX.search(low))
        if not contextual_detail and not challenge:
            return current

        meta = dict(current.get("meta") or {})
        meta.update({
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
        current["args"] = {
            "question": raw,
            "followup_to_action": prior_action,
            "followup_to_request_id": str(prior.get("request_id") or ""),
            "followup_kind": "challenge" if challenge else "detail",
        }
        try:
            current["confidence"] = max(float(current.get("confidence") or 0.0), 0.985)
        except Exception:
            current["confidence"] = 0.985
        return current

    # === END ELI_PHASE19_GROUNDED_FOLLOWUP_REBIND_V1 ===

    ''')
    text = text.replace(insert_before, helper + insert_before, 1)

parse_anchor = '        intent = self._parse_intent(user_input, context)\n        print(f"[COGNITIVE][TIMING] route={time.perf_counter() -t_route:.3f}s total_since_start={time.perf_counter() -t0:.3f}s")\n'
if '# ELI_PHASE19_APPLY_GROUNDED_FOLLOWUP_REBIND_V1' not in text:
    if parse_anchor not in text:
        raise SystemExit('engine parse-intent insertion anchor not found')
    parse_replacement = '''        intent = self._parse_intent(user_input, context)
        # ELI_PHASE19_APPLY_GROUNDED_FOLLOWUP_REBIND_V1
        _eli_p19_before_action = str((intent or {}).get("action") or "CHAT").upper()
        intent = _eli_phase19_rebind_grounded_followup(self, user_input, intent)
        _eli_p19_after_action = str((intent or {}).get("action") or "CHAT").upper()
        if _eli_p19_after_action != _eli_p19_before_action:
            print(
                f"[COGNITIVE] Phase 19 grounded follow-up rebound "
                f"{_eli_p19_before_action} -> {_eli_p19_after_action}",
                flush=True,
            )
        print(f"[COGNITIVE][TIMING] route={time.perf_counter() -t_route:.3f}s total_since_start={time.perf_counter() -t0:.3f}s")
'''
    text = text.replace(parse_anchor, parse_replacement, 1)
engine.write_text(text, encoding='utf-8')

# ---------------------------------------------------------------------
# 2) Control contracts: reject unsupported line numbers and fake fix claims.
# ---------------------------------------------------------------------
ct = control.read_text(encoding='utf-8')
ct_marker = '# === ELI_PHASE19_CONTROL_TRUTH_LOCK_V1 ==='
if ct_marker not in ct:
    anchor = 'def output_violates_evidence(text: Any, evidence_text: Any = "") -> bool:\n'
    if anchor not in ct:
        raise SystemExit('control_contracts anchor not found: output_violates_evidence')
    block = textwrap.dedent(r'''
    # === ELI_PHASE19_CONTROL_TRUTH_LOCK_V1 ===
    _ELI_PHASE19_LINE_CLAIM_RX = re.compile(
        r"\blines?\s+((?:\d+\s*(?:(?:,|/|-|and|or)\s*)?)+)",
        re.IGNORECASE,
    )
    _ELI_PHASE19_MUTATION_CLAIM_RX = re.compile(
        r"\b(?:"
        r"i(?:'|’)?ll\s+(?:delete|remove|fix|patch|edit|change|apply)"
        r"|i\s+will\s+(?:delete|remove|fix|patch|edit|change|apply)"
        r"|i(?:'|’)?ve\s+(?:deleted|removed|fixed|patched|edited|changed|applied)"
        r"|i\s+have\s+(?:deleted|removed|fixed|patched|edited|changed|applied)"
        r"|i\s+(?:deleted|removed|fixed|patched|edited|changed|applied)"
        r"|already\s+(?:deleted|removed|fixed|patched|edited|changed|applied)"
        r")\b",
        re.IGNORECASE,
    )

    def _eli_phase19_line_claims_supported(out: str, ev: str) -> bool:
        for match in _ELI_PHASE19_LINE_CLAIM_RX.finditer(str(out or "")):
            numbers = re.findall(r"\d+", match.group(1) or "")
            if numbers and any(num not in str(ev or "") for num in numbers):
                return False
        return True

    def _eli_phase19_mutation_claim_supported(out: str, ev: str) -> bool:
        m = _ELI_PHASE19_MUTATION_CLAIM_RX.search(str(out or ""))
        if not m:
            return True
        phrase = re.sub(r"\s+", " ", m.group(0).lower()).strip()
        ev_low = re.sub(r"\s+", " ", str(ev or "").lower()).strip()
        return bool(phrase and phrase in ev_low)

    # === END ELI_PHASE19_CONTROL_TRUTH_LOCK_V1 ===

    ''')
    ct = ct.replace(anchor, block + anchor, 1)

old = '    return False\n\ndef compact_evidence_answer(action: str, evidence_result: Dict[str, Any]) -> str:\n'
if '# ELI_PHASE19_CONTROL_TRUTH_CHECKS_V1' not in ct:
    if old not in ct:
        raise SystemExit('control_contracts return-false anchor not found')
    new = '''    # ELI_PHASE19_CONTROL_TRUTH_CHECKS_V1
    # Exact line references and claims of code mutation are not allowed unless
    # the deterministic evidence packet supports them.
    if not _eli_phase19_line_claims_supported(out, ev):
        return True
    if not _eli_phase19_mutation_claim_supported(out, ev):
        return True

    return False

def compact_evidence_answer(action: str, evidence_result: Dict[str, Any]) -> str:
'''
    ct = ct.replace(old, new, 1)
control.write_text(ct, encoding='utf-8')

# ---------------------------------------------------------------------
# 3) Output governor: validator also catches unsupported line/mutation claims.
# ---------------------------------------------------------------------
gv = governor.read_text(encoding='utf-8')
gv_marker = '# === ELI_PHASE19_EVIDENCE_VALIDATOR_TRUTH_LOCK_V1 ==='
if gv_marker not in gv:
    anchor = 'def validate_against_evidence(\n'
    if anchor not in gv:
        raise SystemExit('output_governor anchor not found: validate_against_evidence')
    block = textwrap.dedent(r'''
    # === ELI_PHASE19_EVIDENCE_VALIDATOR_TRUTH_LOCK_V1 ===
    _ELI_PHASE19_GOV_LINE_CLAIM_RX = re.compile(
        r"\blines?\s+((?:\d+\s*(?:(?:,|/|-|and|or)\s*)?)+)",
        re.IGNORECASE,
    )
    _ELI_PHASE19_GOV_MUTATION_CLAIM_RX = re.compile(
        r"\b(?:"
        r"i(?:'|’)?ll\s+(?:delete|remove|fix|patch|edit|change|apply)"
        r"|i\s+will\s+(?:delete|remove|fix|patch|edit|change|apply)"
        r"|i(?:'|’)?ve\s+(?:deleted|removed|fixed|patched|edited|changed|applied)"
        r"|i\s+have\s+(?:deleted|removed|fixed|patched|edited|changed|applied)"
        r"|i\s+(?:deleted|removed|fixed|patched|edited|changed|applied)"
        r"|already\s+(?:deleted|removed|fixed|patched|edited|changed|applied)"
        r")\b",
        re.IGNORECASE,
    )

    def _eli_phase19_gov_line_claims(text: str) -> List[Dict[str, Any]]:
        claims: List[Dict[str, Any]] = []
        for match in _ELI_PHASE19_GOV_LINE_CLAIM_RX.finditer(str(text or "")):
            numbers = re.findall(r"\d+", match.group(1) or "")
            if numbers:
                claims.append({"raw": match.group(0), "numbers": numbers})
        return claims

    # === END ELI_PHASE19_EVIDENCE_VALIDATOR_TRUTH_LOCK_V1 ===

    ''')
    gv = gv.replace(anchor, block + anchor, 1)

insert_after = '''    # 5. PASS/FAIL audit lines for specific files
    for status, fname in _PASS_FAIL_AUDIT_RX.findall(out):
        claims_total += 1
        if fname in ev:
            continue
        claims_unverified += 1
        violations.append({
            "kind": "fabricated_audit_line",
            "value": f"{status} {fname}",
            "reason": "audit line for file not in evidence audit results",
        })
'''
if '# 5b. Phase 19 exact line-number truth lock.' not in gv:
    if insert_after not in gv:
        raise SystemExit('output_governor audit-line block anchor not found')
    addition = insert_after + '''
    # 5b. Phase 19 exact line-number truth lock.
    # A grounded answer may mention concrete line numbers only if every such
    # number appears in the evidence packet provided to synthesis.
    for claim in _eli_phase19_gov_line_claims(out):
        claims_total += 1
        missing = [num for num in claim.get("numbers", []) if str(num) not in ev]
        if not missing:
            continue
        claims_unverified += 1
        violations.append({
            "kind": "fabricated_line_reference",
            "value": str(claim.get("raw") or ""),
            "reason": "line number reference not present in evidence",
        })

    # 5c. Phase 19 fake-mutation truth lock.
    # Claims that a code edit was or will be applied must be evidenced. Audit
    # synthesis may propose a fix, but it cannot represent an edit as executed.
    mutation_match = _ELI_PHASE19_GOV_MUTATION_CLAIM_RX.search(out)
    if mutation_match:
        claims_total += 1
        mutation_phrase = re.sub(r"\\s+", " ", mutation_match.group(0).lower()).strip()
        if mutation_phrase not in ev_lower:
            claims_unverified += 1
            violations.append({
                "kind": "unsupported_mutation_claim",
                "value": mutation_match.group(0),
                "reason": "code mutation claim not present in evidence",
            })
            catastrophic = True
'''
    gv = gv.replace(insert_after, addition, 1)

old_strip = '            if kind in ("fabricated_path", "fabricated_signature", "fabricated_audit_line"):\n'
new_strip = '            if kind in ("fabricated_path", "fabricated_signature", "fabricated_audit_line", "fabricated_line_reference", "unsupported_mutation_claim"):\n'
if old_strip in gv:
    gv = gv.replace(old_strip, new_strip, 1)
else:
    if new_strip not in gv:
        raise SystemExit('output_governor strip kinds anchor not found')
old_mark = '            if kind in ("fabricated_path", "fabricated_signature", "fabricated_audit_line"):\n'
new_mark = '            if kind in ("fabricated_path", "fabricated_signature", "fabricated_audit_line", "fabricated_line_reference", "unsupported_mutation_claim"):\n'
# replace remaining mark-inline occurrence only if still present
if old_mark in gv:
    gv = gv.replace(old_mark, new_mark, 1)

governor.write_text(gv, encoding='utf-8')

# ---------------------------------------------------------------------
# 4) Tests: dedicated regression contract for this failure.
# ---------------------------------------------------------------------
testfile.write_text(textwrap.dedent(r'''
from __future__ import annotations

from eli.kernel.engine import _eli_phase19_rebind_grounded_followup
from eli.runtime.control_contracts import output_violates_evidence
from eli.cognition.output_governor import validate_against_evidence


class _DummyEngine:
    _last_request_meta = {
        "request_id": "req-audit-1",
        "route_action": "RUNTIME_AUDIT",
        "result_action": "RUNTIME_AUDIT",
        "action": "RUNTIME_AUDIT",
        "evidence_used": True,
        "grounded": True,
    }


def _chat_intent():
    return {
        "action": "CHAT",
        "args": {"message": "placeholder"},
        "confidence": 0.85,
        "meta": {"matched_by": "chat.long_question_guard"},
    }


def test_phase19_rebinds_exact_line_followup_to_prior_grounded_action():
    result = _eli_phase19_rebind_grounded_followup(
        _DummyEngine(),
        "what are the exact lines of the duplicates, can you fix it?",
        _chat_intent(),
    )
    assert result["action"] == "RUNTIME_AUDIT"
    assert result["meta"]["grounded_followup"] is True
    assert result["meta"]["allow_chat_without_evidence"] is False
    assert result["meta"]["task_family"] == "grounded_audit"


def test_phase19_rebinds_challenge_followup_to_prior_grounded_action():
    result = _eli_phase19_rebind_grounded_followup(
        _DummyEngine(),
        "are you lieing to me?",
        _chat_intent(),
    )
    assert result["action"] == "RUNTIME_AUDIT"
    assert result["meta"]["grounded_followup_kind"] == "challenge"


def test_phase19_leaves_unrelated_chat_as_chat():
    result = _eli_phase19_rebind_grounded_followup(
        _DummyEngine(),
        "how was your evening?",
        _chat_intent(),
    )
    assert result["action"] == "CHAT"


def test_phase19_control_truth_lock_rejects_wrong_line_numbers():
    evidence = "FAIL router_enhanced.py\n  - line 4422 route also defined at lines [631, 4422]"
    output = "The duplicates are at lines 42 and 56."
    assert output_violates_evidence(output, evidence) is True


def test_phase19_control_truth_lock_allows_evidenced_line_numbers():
    evidence = "FAIL router_enhanced.py\n  - line 4422 route also defined at lines [631, 4422]"
    output = "The duplicate route definitions are reported at lines 631 and 4422."
    assert output_violates_evidence(output, evidence) is False


def test_phase19_control_truth_lock_rejects_fake_edit_claims():
    evidence = "Runtime audit only. No code edit action occurred."
    output = "I'll delete the duplicate now."
    assert output_violates_evidence(output, evidence) is True


def test_phase19_output_governor_rejects_wrong_line_numbers():
    evidence = "FAIL router_enhanced.py\n  - line 4422 route also defined at lines [631, 4422]"
    verdict = validate_against_evidence(
        "The duplicates are at lines 42 and 56.",
        evidence,
        mode="strip_silent",
    )
    assert verdict["unsafe"] is True
    assert any(v["kind"] == "fabricated_line_reference" for v in verdict["violations"])


def test_phase19_output_governor_rejects_fake_mutation_claims():
    verdict = validate_against_evidence(
        "I'll delete the duplicate now.",
        "Runtime audit evidence only; no mutation executor action occurred.",
        mode="strip_silent",
    )
    assert verdict["unsafe"] is True
    assert any(v["kind"] == "unsupported_mutation_claim" for v in verdict["violations"])
''').lstrip(), encoding='utf-8')
PY

{
  echo "=== Phase 19 touched files ==="
  printf '%s\n' \
    eli/kernel/engine.py \
    eli/runtime/control_contracts.py \
    eli/cognition/output_governor.py \
    tests/test_phase19_grounded_followup_truth_lock.py
  echo
  echo "=== Marker scan ==="
  grep -RInE 'ELI_PHASE19_GROUNDED_FOLLOWUP_REBIND_V1|ELI_PHASE19_CONTROL_TRUTH_LOCK_V1|ELI_PHASE19_EVIDENCE_VALIDATOR_TRUTH_LOCK_V1|ELI_PHASE19_APPLY_GROUNDED_FOLLOWUP_REBIND_V1' \
    eli/kernel/engine.py \
    eli/runtime/control_contracts.py \
    eli/cognition/output_governor.py || true
} > "$OUT/01_patch_markers.txt" 2>&1

python3 -m py_compile \
  eli/kernel/engine.py \
  eli/runtime/control_contracts.py \
  eli/cognition/output_governor.py \
  tests/test_phase19_grounded_followup_truth_lock.py \
  > "$OUT/02_py_compile.txt" 2>&1

python3 -m pytest -q \
  tests/test_phase19_grounded_followup_truth_lock.py \
  tests/test_route_contracts.py \
  tests/test_output_governor_semantics.py \
  > "$OUT/03_pytest_phase19_targeted.txt" 2>&1 || true

python3 - <<'PY' > "$OUT/04_phase19_static_probe.txt" 2>&1
from eli.kernel.engine import _eli_phase19_rebind_grounded_followup
from eli.runtime.control_contracts import output_violates_evidence
from eli.cognition.output_governor import validate_against_evidence

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
print(_eli_phase19_rebind_grounded_followup(Engine(), "what are the exact lines of the duplicates, can you fix it?", intent))
evidence = "FAIL router_enhanced.py\\n  - line 4422 route also defined at lines [631, 4422]"
print("wrong_line_control_violation=", output_violates_evidence("The duplicates are at lines 42 and 56.", evidence))
print("correct_line_control_violation=", output_violates_evidence("The duplicate route definitions are reported at lines 631 and 4422.", evidence))
print("fake_mutation_control_violation=", output_violates_evidence("I'll delete the duplicate now.", evidence))
print(validate_against_evidence("The duplicates are at lines 42 and 56.", evidence, mode="strip_silent"))
PY

{
  echo "# Phase 19 Grounded Follow-up Truth Lock"
  echo
  echo "Date: $(date -Is)"
  echo "Root: $ROOT"
  echo
  echo "## Purpose"
  echo "- Rebind contextual exact-line/fix/challenge follow-ups to the previous grounded control action."
  echo "- Reject unsupported line-number claims during control synthesis."
  echo "- Reject unsupported claims that a code mutation was or will be applied."
  echo "- Add dedicated regression tests and a static smoke probe."
  echo
  echo "## Outputs"
  echo "- 01_patch_markers.txt"
  echo "- 02_py_compile.txt"
  echo "- 03_pytest_phase19_targeted.txt"
  echo "- 04_phase19_static_probe.txt"
  echo
  echo "## Notes"
  echo "The two pre-existing tests in tests/test_output_governor_semantics.py may remain failing if they were already failing before this patch; see the targeted pytest output."
} > "$OUT/SUMMARY.md"

echo
cat "$OUT/SUMMARY.md"
echo
echo "Report directory: $OUT"
