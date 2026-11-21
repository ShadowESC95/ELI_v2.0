"""Executor pure helpers — result normalisation and the code-hygiene scanners.

These are the safely-testable, side-effect-free parts of the (very large) executor:
the response-shape contract the GUI/voice rely on, and the scanners that catch merge
markers / hardcoded user paths (redistributable hygiene). The side-effecting action
handlers (OPEN_APP, SHELL_EXEC, …) are deliberately NOT exercised here — running them
in a test could actually drive the machine. The live shell gate is
eli/execution/shell_gate.py, tested in its own files; the executor's allowlist helper
(`_run`, `_shell_command_allowed_fallback`) was called by nothing and is gone, and its
tests with it. Runs in the normal suite (no model, no subprocess).
"""
from __future__ import annotations

import hashlib

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
