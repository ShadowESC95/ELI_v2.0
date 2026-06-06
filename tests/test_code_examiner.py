"""Tests for the code examiner: tiered findings, target resolution, pending-fix
state, the examine→confirm→patch round-trip, and the router confirm intercept.

All deterministic — the Tier-3 LLM pass is disabled (run_tier3=False) or the
broker is monkeypatched, so no model is required.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from eli.runtime import code_examiner as CE


PROJECT_ROOT = CE.PROJECT_ROOT


@pytest.fixture
def tmp_module(request):
    """Create a temp .py file *inside the project* (examiner refuses outside-root
    targets) and clean it + any backups afterwards."""
    created = []

    def _make(name: str, body: str) -> Path:
        p = (PROJECT_ROOT / "eli" / name).resolve()
        p.write_text(body, encoding="utf-8")
        created.append(p)
        return p

    yield _make

    for p in created:
        p.unlink(missing_ok=True)
        for bak in p.parent.glob(p.name + ".eli_bak*"):
            bak.unlink(missing_ok=True)
    CE.clear_pending_fix()


def test_resolve_targets_named_and_alias():
    named = CE.resolve_targets("examine eli/runtime/grounding_escalation.py for errors")
    assert any(p.name == "grounding_escalation.py" for p in named)

    dotted = CE.resolve_targets("scan eli.cognition.orchestrator for issues")
    assert any(p.name == "orchestrator.py" for p in dotted)

    alias = CE.resolve_targets("review the router for bugs")
    assert any(p.name == "router_enhanced.py" for p in alias)


def test_resolve_targets_default_sweep_is_capped():
    # No file named → falls back to git-recent / core set, always capped.
    paths = CE.resolve_targets("examine the codebase for bugs")
    assert paths, "default sweep should return something"
    assert len(paths) <= CE.MAX_SWEEP_FILES
    assert all(p.suffix == ".py" for p in paths)


def test_tier1_catches_syntax_error(tmp_module):
    p = tmp_module("_ce_syntax.py", "def broken(:\n    pass\n")
    findings = CE.examine([p], run_tier3=False)
    assert any(f.tier == 1 and f.kind == "syntax" for f in findings)
    # Syntax error short-circuits deeper tiers.
    assert all(f.tier == 1 for f in findings)


def test_tier2_catches_unused_import(tmp_module):
    p = tmp_module("_ce_unused.py", "import os\n\nVALUE = 1\n")
    findings = CE.examine([p], run_tier3=False)
    # Tier 2 uses pyflakes when installed (kind "lint") and an AST fallback
    # otherwise (kind "unused-import"); accept either, but it must flag 'os'.
    t2 = [f for f in findings if f.tier == 2 and "os" in f.message]
    assert t2, f"expected a Tier-2 unused-import finding, got {[f.to_dict() for f in findings]}"
    assert t2[0].confidence == CE.TIER_CONF[2]
    assert t2[0].kind in ("unused-import", "lint")


def test_clean_file_reports_no_errors(tmp_module):
    p = tmp_module("_ce_clean.py", "VALUE = 1\n\n\ndef add(a, b):\n    return a + b\n")
    findings = CE.examine([p], run_tier3=False)
    assert findings == []
    report = CE.format_report([p], findings)
    assert "No errors found" in report


def test_format_report_groups_and_offers(tmp_module):
    p = tmp_module("_ce_report.py", "import os\n\nVALUE = 1\n")
    findings = CE.examine([p], run_tier3=False)
    report = CE.format_report([p], findings)
    assert "Tier 2" in report
    assert "Say 'yes'" in report


def test_pending_state_roundtrip(tmp_module):
    p = tmp_module("_ce_pending.py", "import os\n\nVALUE = 1\n")
    findings = CE.examine([p], run_tier3=False)
    assert CE.get_pending_fix() is None
    CE.set_pending_fix(findings, [p])
    pending = CE.get_pending_fix()
    assert pending and len(pending["findings"]) == len(findings)
    CE.clear_pending_fix()
    assert CE.get_pending_fix() is None


def test_examine_confirm_patch_roundtrip(tmp_module, monkeypatch):
    """End-to-end: EXAMINE_CODE → pending → CONFIRM_CODE_FIX applies a verified
    patch (broker mocked) and the file ends up correct."""
    from eli.execution import executor_enhanced as EX
    import eli.cognition.inference_broker as IB

    p = tmp_module("_ce_e2e.py", "import os\nimport sys\n\nVALUE = 42\n")

    res = EX.execute("EXAMINE_CODE", {"request": f"examine eli/_ce_e2e.py for errors"})
    assert res["ok"]
    assert CE.get_pending_fix() is not None

    class _FakeBroker:
        def infer(self, prompt, system="", max_tokens=600, temperature=0.0):
            return json.dumps({
                "old": "import os\nimport sys\n",
                "new": "import os\n",
                "description": "drop unused sys import",
            })

    monkeypatch.setattr(IB, "get_broker", lambda: _FakeBroker())
    res2 = EX.execute("CONFIRM_CODE_FIX", {"message": "yes"})
    assert res2["ok"]
    assert "Code-fix cycle complete" in res2["content"]
    # File is syntactically valid and the unused import is gone.
    after = p.read_text(encoding="utf-8")
    assert "import sys" not in after
    import ast
    ast.parse(after)
    # Pending cleared after a confirm.
    assert CE.get_pending_fix() is None


def test_tier3_findings_gated_until_confirmed(tmp_module, monkeypatch):
    """A Tier-3 (needs_confirmation) finding must NOT be patched on a plain 'yes';
    only when the user opts into the logic ones."""
    from eli.execution import executor_enhanced as EX

    p = tmp_module("_ce_tier3.py", "VALUE = 1\n")
    t3 = CE.Finding(file="eli/_ce_tier3.py", tier=3, confidence=CE.TIER_CONF[3],
                    kind="logic", message="suspected off-by-one", line=1,
                    needs_confirmation=True)
    CE.set_pending_fix([t3], [p])

    # Plain "yes" → Tier-3 left untouched (0 confirmed), nothing patched.
    res = EX.execute("CONFIRM_CODE_FIX", {"message": "yes"})
    assert res["ok"]
    assert "patches_applied: 0/0" in res["content"]
    assert "untouched" in res["content"]


def test_pending_confirm_routing(tmp_module):
    """With a pending fix, 'yes' routes to CONFIRM_CODE_FIX and 'no' to CANCEL."""
    from eli.execution.router_enhanced import route

    p = tmp_module("_ce_route.py", "import os\n\nVALUE = 1\n")
    findings = CE.examine([p], run_tier3=False)
    CE.set_pending_fix(findings, [p])
    try:
        assert route("yes")["action"] == "CONFIRM_CODE_FIX"
        assert route("fix it")["action"] == "CONFIRM_CODE_FIX"
        assert route("no")["action"] == "CANCEL_CODE_FIX"
    finally:
        CE.clear_pending_fix()
