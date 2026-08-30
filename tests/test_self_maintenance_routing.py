"""Self-maintenance routing and packaged-build behaviour."""
from __future__ import annotations

from eli.execution.router_enhanced import route


def test_casual_code_change_notice_routes_chat_not_self_report():
    out = route("do you notice any changes in your code recently?")
    assert out["action"] != "SELF_REPORT"


def test_technical_git_update_still_self_report():
    out = route("what updates were made recently to your code?")
    assert out["action"] == "SELF_REPORT"


def test_fix_your_code_routes_self_patch():
    out = route("can you fix your code?")
    assert out["action"] == "SELF_PATCH"


def test_fix_the_errors_routes_self_patch():
    out = route("fix the errors")
    assert out["action"] == "SELF_PATCH"


def test_fix_those_issues_routes_self_patch():
    out = route("fix those issues")
    assert out["action"] == "SELF_PATCH"


def test_self_fix_typo_routes_self_patch():
    out = route("well do self fixx")
    assert out["action"] == "SELF_PATCH"


def test_close_app_empty_args_not_actionable():
    from eli.runtime.failure_taxonomy import classify, is_actionable

    tags = classify("missing app name", "CLOSE_APP {}")
    assert tags["category"] == "user_input"
    assert not is_actionable(tags["category"])


def test_deterministic_patch_already_applied():
    from eli.runtime.deterministic_failure_patches import propose_deterministic_patch

    patch = propose_deterministic_patch({
        "error": "Missing topic for document generation",
        "command": 'CREATE_DOCUMENT {"name": "new agent"}',
    })
    assert patch is not None
    assert patch.get("already_applied") is True
