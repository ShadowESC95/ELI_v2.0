"""Deictic shell follow-up and timestamp diagnostic routing."""
from __future__ import annotations

from eli.execution.router_enhanced import route
from eli.runtime.shell_followup import (
    extract_shell_from_assistant,
    is_run_prior_shell_request,
    resolve_run_prior_shell,
)


def _action(text: str) -> str:
    return (route(text) or {}).get("action") or ""


def _args(text: str) -> dict:
    return (route(text) or {}).get("args") or {}


def test_run_that_command_is_not_open_app():
    assert _action("run that command") != "OPEN_APP"


def test_run_that_command_executes_prior_shell_block(monkeypatch):
    prior = (
        "I'll check the clock.\n\n"
        "```bash\n"
        "date -Iseconds\n"
        "echo ---\n"
        "stat --format='%Y %y' /proc/1/status\n"
        "```"
    )
    monkeypatch.setattr(
        "eli.runtime.shell_followup._last_assistant_text",
        lambda: prior,
    )
    assert is_run_prior_shell_request("run that command")
    assert resolve_run_prior_shell("run that command") == "date -Iseconds"
    r = route("run that command")
    assert r["action"] == "SHELL_EXEC"
    assert r["args"]["cmd"] == "date -Iseconds"


def test_extract_shell_prefers_read_only_line():
    text = "```bash\necho ---\ndate -Iseconds\n```"
    assert extract_shell_from_assistant(text) == "date -Iseconds"


def test_dig_into_timestamps_routes_to_diag():
    assert _action("yes please dig into the timestamps") == "TIMESTAMP_DIAG"


def test_portable_does_not_open_that_command():
    from eli.execution.portable_intent_contract import try_route
    assert try_route("run that command") is None
