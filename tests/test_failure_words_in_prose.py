"""Locks on a report ABOUT failures not being mistaken for a failed report.

`test_self_report_recent_updates_no_gguf` passed all morning and failed the same
afternoon on an unchanged commit. The cause was not the code and not the machine
state — it was a git commit message.

SELF_REPORT answers "what have you done lately?" partly from recent commits. One
of them read:

    "...also stop printing a FileNotFoundError stack when clearing a pending fix
     that was never there"

Three separate guards scan evidence for failure words. All three matched
"filenotfounderror" in that sentence and replaced a successful report — ok=True,
synthesis_validated=True — with:

    "I did not successfully complete `ACTION`."

with a placeholder name, because there was no action to name. A commit about
FIXING an error was read as an error.

The guards are worth keeping: they stop ELI narrating success over an executor
that failed. What they must not do is treat prose as telemetry. Three changes:

  * report-style actions (SELF_REPORT, EXPLAIN_*, audits) are exempt — their
    evidence quotes logs and failure counts by design, and the caller already
    knows whether they succeeded;
  * an error NAME in prose needs a structured neighbour ("execute result", a
    traceback) before it counts;
  * the broad prompt scan dropped "grounded_evidence" from its co-occurrence
    set — every grounded turn contains it, so it could not disqualify anything.
"""
import pytest

from eli.kernel.engine import (
    _REPORTS_ABOUT_STATE, _failed_executor_is_failed,
    _failed_executor_is_failed_block,
)

COMMIT_MESSAGE = (
    "a 5693-token prompt generated with max_tokens=128 and cut mid-word — "
    "estimate, clamp, truncate is the wrong order; also stop printing a "
    "FileNotFoundError stack when clearing a pending fix that was never there"
)


# ── the exact live trigger ─────────────────────────────────────────────────
def test_a_commit_message_about_an_error_is_not_an_error():
    assert not _failed_executor_is_failed_block(COMMIT_MESSAGE)


def test_a_self_report_quoting_that_commit_still_succeeds():
    assert not _failed_executor_is_failed(
        f"<grounded_evidence>Recent commits:\n- {COMMIT_MESSAGE}</grounded_evidence>",
        action="SELF_REPORT",
    )


@pytest.mark.parametrize("prose", [
    "fixed: file not found on the docs path",
    "the changelog mentions a FileNotFoundError we resolved last week",
    "no failures recorded since the patch",
])
def test_narrative_mentions_are_ignored(prose):
    assert not _failed_executor_is_failed_block(prose)


# ── real failures must still be caught ────────────────────────────────────
@pytest.mark.parametrize("block", [
    "execute result: {'ok': False, 'action': 'ANALYZE_PDF'}",
    'execute result: {"ok": false, "action": "OPEN_APP"}',
    "action=ANALYZE_PDF ok=False",
    "Successful: 0 | Failed: 3",
    "execute result: FileNotFoundError: /tmp/x.pdf",
    "Traceback (most recent call last) ... FileNotFoundError: no such file",
    "analyze_pdf failure",
])
def test_structured_failures_are_still_detected(block):
    assert _failed_executor_is_failed_block(block)


def test_an_explicitly_named_failing_action_is_still_caught():
    assert _failed_executor_is_failed(
        "execute result: {'ok': False}", action="ANALYZE_PDF")


# ── the report family ─────────────────────────────────────────────────────
@pytest.mark.parametrize("action", sorted(_REPORTS_ABOUT_STATE))
def test_report_actions_are_exempt(action):
    """Their evidence is failure data by definition."""
    assert not _failed_executor_is_failed(
        "action=CHAT ok=False\nfilenotfounderror\nSuccessful: 0 | Failed: 9",
        action=action,
    )


def test_a_normal_action_is_not_exempt():
    assert "ANALYZE_PDF" not in _REPORTS_ABOUT_STATE
    assert "OPEN_APP" not in _REPORTS_ABOUT_STATE


def test_telemetry_rows_do_not_flip_an_unnamed_action():
    """A self-report bundles dispatch telemetry; one failed row in it is a log
    entry about some other turn, not this one."""
    telemetry = (
        "Recent agent-dispatch telemetry (8 cycles, newest first):\n"
        "- action=CHAT agents=[memory] confidence=0.84 elapsed=448ms ok=True\n"
        "- action=MEMORY_RECALL agents=[memory] confidence=0.58 ok=False"
    )
    assert not _failed_executor_is_failed(telemetry)


# ── the co-occurrence set must not include a universal marker ─────────────
def test_grounded_evidence_is_not_used_to_qualify_a_failure():
    """It appears on every grounded turn, so it disqualified nothing."""
    from pathlib import Path as _P

    # _get_chat_response is a method on CognitiveEngine, not a module function.
    src = (_P(__file__).resolve().parents[1] / "eli" / "kernel" / "engine.py"
           ).read_text(encoding="utf-8")
    broad = src[src.index("Broad fallback"):src.index("Broad fallback") + 1200]
    code = "\n".join(l for l in broad.splitlines() if not l.lstrip().startswith("#"))
    assert "grounded_evidence" not in code
