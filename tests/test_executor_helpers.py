"""Executor pure helpers — result normalisation, the fail-closed shell gate, and
the code-hygiene scanners.

These are the safely-testable, side-effect-free parts of the (very large) executor:
the response-shape contract the GUI/voice rely on, the security allowlist that must
never fail OPEN, and the scanners that catch merge markers / hardcoded user paths
(redistributable hygiene). The side-effecting action handlers (OPEN_APP, SHELL_EXEC,
…) are deliberately NOT exercised here — running them in a test could actually drive
the machine. Runs in the normal suite (no model, no subprocess side effects except a
whitelisted `echo`).
"""
from __future__ import annotations

import hashlib

import pytest

import eli.execution.executor_enhanced as ex


# --------------------------------------------------------------------------- #
# _normalize_result — the GUI/voice response-shape contract
# --------------------------------------------------------------------------- #
def test_normalize_non_dict_becomes_error_dict():
    r = ex._normalize_result("just a string")
    assert r["ok"] is False and r["error"] == "handler_returned_non_dict"
    assert r["content"] == "just a string" and r["response"] == "just a string"


def test_normalize_none():
    r = ex._normalize_result(None)
    assert r["ok"] is False and r["content"] == "" and r["response"] == ""


def test_normalize_mirrors_response_into_content():
    r = ex._normalize_result({"response": "hi"})
    assert r["content"] == "hi" and r["response"] == "hi"
    assert r["ok"] is False  # missing ok defaults to False


def test_normalize_mirrors_content_into_response():
    r = ex._normalize_result({"ok": True, "content": "yo"})
    assert r["response"] == "yo" and r["ok"] is True


def test_normalize_content_fallback_to_error():
    r = ex._normalize_result({"ok": False, "error": "boom"})
    assert r["content"] == "boom" and isinstance(r["response"], str)


def test_normalize_guarantees_string_fields():
    r = ex._normalize_result({"ok": True, "content": 123})
    assert isinstance(r["content"], str) and isinstance(r["response"], str)


# --------------------------------------------------------------------------- #
# _strip_ollama_artifacts
# --------------------------------------------------------------------------- #
def test_strip_artifacts():
    assert ex._strip_ollama_artifacts("hello<|end|>") == "hello"
    assert ex._strip_ollama_artifacts("  spaced   ") == "spaced"
    assert ex._strip_ollama_artifacts(None) == ""


# --------------------------------------------------------------------------- #
# _sha256_file
# --------------------------------------------------------------------------- #
def test_sha256_file_matches_hashlib(tmp_path):
    p = tmp_path / "f.bin"
    data = b"the quick brown fox" * 1000
    p.write_bytes(data)
    assert ex._sha256_file(p) == hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------- #
# _shell_command_allowed_fallback — MUST fail closed (security)
# --------------------------------------------------------------------------- #
@pytest.fixture
def no_full_control(monkeypatch):
    monkeypatch.setattr(ex, "_full_control", lambda: False)


def test_shell_gate_fails_closed_by_default(no_full_control, monkeypatch):
    monkeypatch.delenv("ELI_ALLOWED_CMDS", raising=False)
    # No Full Control, no allowlist → NOTHING runs.
    assert ex._shell_command_allowed_fallback("ls") is False
    assert ex._shell_command_allowed_fallback("rm") is False


def test_shell_gate_honours_allowlist(no_full_control, monkeypatch):
    monkeypatch.setenv("ELI_ALLOWED_CMDS", "echo ls")
    assert ex._shell_command_allowed_fallback("echo") is True
    assert ex._shell_command_allowed_fallback("ls") is True
    assert ex._shell_command_allowed_fallback("rm") is False  # not on the list


def test_shell_gate_wildcard(no_full_control, monkeypatch):
    monkeypatch.setenv("ELI_ALLOWED_CMDS", "*")
    assert ex._shell_command_allowed_fallback("anything") is True


def test_shell_gate_full_control_bypasses(monkeypatch):
    monkeypatch.setattr(ex, "_full_control", lambda: True)
    monkeypatch.delenv("ELI_ALLOWED_CMDS", raising=False)
    assert ex._shell_command_allowed_fallback("rm") is True


# --------------------------------------------------------------------------- #
# _run — the gate blocks a disallowed command BEFORE it executes
# --------------------------------------------------------------------------- #
def test_run_blocks_disallowed_command(no_full_control, monkeypatch):
    monkeypatch.setattr(ex, "_get_security_manager", lambda: None)  # force fallback gate
    monkeypatch.setenv("ELI_ALLOWED_CMDS", "echo")
    # 'rm' is not allowlisted → blocked, and crucially never executed.
    r = ex._run(["rm", "-rf", "/tmp/should-not-happen"])
    assert r["ok"] is False and "blocked by security policy" in r["stderr"]


def test_run_executes_allowlisted_command(no_full_control, monkeypatch):
    monkeypatch.setattr(ex, "_get_security_manager", lambda: None)
    monkeypatch.setenv("ELI_ALLOWED_CMDS", "echo")
    r = ex._run(["echo", "hello-from-test"])
    assert r["ok"] is True and "hello-from-test" in r["stdout"]


# --------------------------------------------------------------------------- #
# Code-hygiene scanners (redistributable / merge safety)
# --------------------------------------------------------------------------- #
def test_scan_merge_markers_detects_conflicts():
    lines = ["ok line", "<<<<<<< HEAD", "mine", "=======", "theirs", ">>>>>>> branch"]
    issues = ex._scan_merge_markers(lines)
    assert len(issues) == 3
    assert all(i["type"] == "merge_marker" for i in issues)


def test_scan_merge_markers_clean_file():
    assert ex._scan_merge_markers(["def f():", "    return 1"]) == []


def test_scan_user_paths_flags_hardcoded_home():
    issues = ex._scan_user_specific_paths(['CONFIG = "/home/someone/secret/config.json"'])
    assert len(issues) == 1 and issues[0]["type"] == "hardcoded_user_path"


def test_scan_user_paths_skips_comments_and_clean():
    lines = ["# see /home/docs/readme", 'x = data_dir() / "config"']
    assert ex._scan_user_specific_paths(lines) == []


def test_scan_top_level_symbols_flags_syntax_error(tmp_path):
    from pathlib import Path
    issues = ex._scan_top_level_symbols(Path("bad.py"), "def broken(:\n  pass")
    assert any(i["type"] == "syntax_error" for i in issues)
