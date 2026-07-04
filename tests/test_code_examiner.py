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
        # Remove the compiled bytecode too — otherwise the .pyc lingers as a "ghost"
        # (no matching .py) in __pycache__ and trips the source-only-pycache guard
        # (test_12_filesystem) on the next full-suite run.
        for pyc in (p.parent / "__pycache__").glob(p.stem + ".*.pyc"):
            pyc.unlink(missing_ok=True)
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


def test_format_report_cosmetic_is_report_only(tmp_module):
    # An unused import is COSMETIC — it must be shown but NEVER offered for fixing, even with
    # allow_fix=True. Only genuine breakage (syntax/import/undefined-name) is auto-fixable.
    p = tmp_module("_ce_report.py", "import os\n\nVALUE = 1\n")
    findings = CE.examine([p], run_tier3=False)
    report = CE.format_report([p], findings, allow_fix=True)
    assert "Tier 2" in report
    assert "Say 'yes'" not in report
    assert "REPORT-ONLY" in report


def test_format_report_offers_real_breakage_when_named(tmp_module):
    # A genuine undefined name IS offered for fixing when files were explicitly named.
    p = tmp_module("_ce_break.py", "def g():\n    return undefined_xyz\n")
    findings = CE.examine([p], run_tier3=False)
    assert any(CE.is_real_breakage(f) for f in findings)
    assert "Say 'yes'" in CE.format_report([p], findings, allow_fix=True)
    # ...but a broad audit (allow_fix=False) never offers, even for real breakage.
    assert "Say 'yes'" not in CE.format_report([p], findings, allow_fix=False)


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

    # REAL breakage (undefined name) on an explicitly-named file → fix is offered.
    p = tmp_module("_ce_e2e.py", "def g():\n    return undefined_xyz\n")

    res = EX.execute("EXAMINE_CODE", {"request": f"examine eli/_ce_e2e.py for errors"})
    assert res["ok"]
    assert CE.get_pending_fix() is not None

    class _FakeBroker:
        def infer(self, prompt, system="", max_tokens=600, temperature=0.0):
            return json.dumps({
                "old": "    return undefined_xyz\n",
                "new": "    return 0\n",
                "description": "replace the undefined name",
            })

    monkeypatch.setattr(IB, "get_broker", lambda: _FakeBroker())
    res2 = EX.execute("CONFIRM_CODE_FIX", {"message": "yes"})
    assert res2["ok"]
    assert "Code-fix cycle complete" in res2["content"]
    # File is syntactically valid and the undefined name is gone.
    after = p.read_text(encoding="utf-8")
    assert "undefined_xyz" not in after
    import ast
    ast.parse(after)


def test_sweep_audit_is_report_only(tmp_module, monkeypatch):
    """A broad audit (no file named) must NOT create a pending fix, even with real breakage."""
    from eli.execution import executor_enhanced as EX
    CE.clear_pending_fix()
    p = tmp_module("_ce_sweep.py", "def g():\n    return undefined_xyz\n")
    # Force the sweep to target our file (no named path in the request).
    monkeypatch.setattr(CE, "resolve_targets", lambda _req: [p])
    res = EX.execute("EXAMINE_CODE", {"request": "run a full audit of your files"})
    assert res["ok"]
    assert CE.get_pending_fix() is None       # report-only: nothing pending to patch
    assert "Say 'yes'" not in res["content"]
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


# --------------------------------------------------------------------------- #
# Frontier patch generator: scope context + validate-and-retry                #
# --------------------------------------------------------------------------- #
def test_enclosing_scope_picks_smallest_def():
    src = ("import os\n\ndef outer():\n    x = 1\n    def inner():\n"
           "        return undefined_xyz\n    return inner\n")
    # line 6 is inside inner() — the smallest enclosing def
    assert CE._enclosing_scope(src, 6) == (5, 6)
    # line 4 is in outer() but not inner()
    assert CE._enclosing_scope(src, 4) == (3, 7)
    assert CE._file_import_block(src).strip() == "import os"


def test_validate_patch_rejects_nonverbatim_and_syntax_break():
    src = "def f():\n    x = 1\n    return x\n"
    assert CE._validate_patch(src, {"old": "NOT IN FILE", "new": "y"})  # truthy error string
    assert CE._validate_patch(src, {"old": "x = 1", "new": "x = ("})    # breaks syntax
    assert CE._validate_patch(src, {"old": "", "new": "y"})             # empty old
    assert CE._validate_patch(src, {"old": "return x", "new": "return 0"}) is None  # valid


def test_generate_fix_patch_retries_with_feedback(tmp_module, monkeypatch):
    """A bad first attempt (non-verbatim old) is rejected locally and retried; the corrected
    second attempt is accepted — without anything touching disk until apply."""
    import eli.cognition.inference_broker as IB
    p = tmp_module("_ce_retry.py", "def g():\n    return undefined_xyz\n")
    calls = {"n": 0}

    class _Broker:
        def infer(self, prompt, system="", max_tokens=700, temperature=0.05):
            calls["n"] += 1
            if calls["n"] == 1:
                return json.dumps({"old": "this snippet is not in the file", "new": "x"})
            # The retry prompt must carry the prior error back to the model.
            assert "previous attempt FAILED" in prompt
            return json.dumps({"old": "return undefined_xyz", "new": "return 0",
                               "description": "replace undefined name"})

    monkeypatch.setattr(IB, "get_broker", lambda: _Broker())
    patch = CE.generate_fix_patch({"file": "eli/_ce_retry.py", "line": 2,
                                   "kind": "lint", "message": "undefined name 'undefined_xyz'"})
    assert patch["ok"] is True
    assert patch["new"] == "return 0"
    assert calls["n"] == 2   # proves it retried after the local rejection
