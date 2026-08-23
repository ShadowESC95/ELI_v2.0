"""Behaviour locks for the remaining defects from the 2.3.15 session report.

Four separate faults, one theme -- ELI told the user things that were not true
about itself, and leaked its own internals into what the user reads:

  * The voice agent reported `engine=espeak` from `os.environ.get(
    "ELI_TTS_ENGINE", "espeak")`. That env var is almost never set, so the
    default WAS the answer -- while the same session logged
    `TTS_FINAL_PIPER_ONLY voice=en_US-amy-medium` for every single utterance.
    The model then repeated the wrong value as fact and told the user Piper
    was missing, seconds after Piper had spoken to them.
  * A failed-action surface rendered its own template placeholder:
    "I did not successfully complete `ACTION`" -- on a turn where the user had
    asked for no action at all.
  * A mistyped "ply" was answered with a raw JSON blob on screen:
    {"event": "input_fragment_guard", "heard": "ply", ...}
  * "i am not saying close files (the name of the app) ... this is the issue"
    was routed to EXAMINE_CODE at 0.96 and answered with lint warnings about
    unused imports, because an issue-word and a file-word merely had to
    co-occur somewhere in the sentence.

Plus the resource leak behind the ResourceWarnings: three mpv IPC helpers
closed their socket only on the success path.
"""
import inspect
import re
from pathlib import Path

import pytest

from eli.execution import router_enhanced as router
from eli.execution import executor_enhanced as ex
from eli.kernel import engine as eng


# ── a diagnostic must measure, not recite configuration ────────────────────
def test_voice_agent_probes_the_live_tts_layer():
    src = Path("eli/cognition/agent_bus.py").read_text(encoding="utf-8")
    start = src.index("class VoiceAgent") if "class VoiceAgent" in src else 0
    block = src[start:start + 6000] if start else src
    assert "available_backends()" in block, \
        "voice agent no longer asks the TTS layer what is loaded"


def test_voice_agent_does_not_default_the_engine_to_espeak():
    """The default WAS the bug: an unset env var became a confident answer."""
    src = Path("eli/cognition/agent_bus.py").read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    assert 'os.environ.get("ELI_TTS_ENGINE", "espeak")' not in code, \
        "the espeak default is back"


def test_live_tts_probe_reports_a_real_engine():
    """On a machine with Piper installed, the probe must say piper."""
    from eli.perception import tts_router as tts
    backends = tts.available_backends() or {}
    if not backends.get("active_model"):
        pytest.skip("no Piper model resolved on this machine")
    assert backends.get("active_voice"), "no active voice reported"
    assert str(backends["active_model"]).endswith(".onnx")


# ── template placeholders must never reach the user ────────────────────────
def test_unknown_failed_action_does_not_print_the_placeholder():
    line = eng._failed_executor_surface("ok=false something broke").splitlines()[0]
    assert "ACTION" not in line, f"placeholder leaked: {line!r}"
    assert line.strip(), "failure surface went empty"


def test_known_failed_action_is_still_named():
    line = eng._failed_executor_surface("'action': 'CLOSE_APP' ok=false").splitlines()[0]
    assert "CLOSE_APP" in line


def test_action_sentinel_is_never_interpolated():
    src = inspect.getsource(eng._failed_executor_surface)
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    assert 'act != "ACTION"' in code, "the sentinel is no longer excluded"


# ── fragmentary input gets a sentence, not a JSON dump ─────────────────────
@pytest.mark.parametrize("fragment", ["ply", "th", "uh", "mm"])
def test_fragment_guard_speaks_english(fragment):
    out = router.route(fragment)
    args = out.get("args") or {}
    for key in ("response", "content", "message"):
        text = str(args.get(key) or "")
        assert not text.lstrip().startswith("{"), f"{key} is raw JSON: {text[:60]}"
        assert "input_fragment_guard" not in text, f"{key} leaks the event name"
    assert fragment in str(args.get("response") or ""), "does not echo what was heard"


def test_fragment_guard_still_records_the_diagnostic():
    """The structured record is useful -- it just belongs in the log, not on screen."""
    args = router.route("ply").get("args") or {}
    diag = args.get("diagnostic") or {}
    assert diag.get("event") == "input_fragment_guard"
    assert diag.get("heard") == "ply"


# ── a complaint about ELI is not a request to audit ELI ────────────────────
@pytest.mark.parametrize("phrase", [
    "i am not saying close files (the name of the app/spftware) because you "
    "will just shut my pc down, but there you go, this is the issue",
    "the issue is that spotify keeps repeating the same file",
    "that is the problem with your code of conduct",
    "what's the issue with the code of conduct file",
])
def test_conversational_complaints_are_not_code_audits(phrase):
    out = router.route(phrase)
    assert out["action"] != "EXAMINE_CODE", (
        f"{phrase[:50]!r} still routes to a code examination -- this is what got "
        f"answered with lint warnings about unused imports"
    )


@pytest.mark.parametrize("phrase", [
    "is there any issues with the files?",
    "is there any issues with your code?",
    "any errors in the code?",
    "are there bugs in the codebase",
    "the code has problems",
    "examine the codebase for bugs",
    "check eli/kernel/engine.py for errors",
])
def test_real_code_audit_requests_still_route(phrase):
    assert router.route(phrase)["action"] == "EXAMINE_CODE", f"{phrase!r} regressed"


# ── sockets close on every path, not just the happy one ────────────────────
@pytest.mark.parametrize("fn", ["_mpv_alive", "_mpv_ipc", "_mpv_load_confirmed"])
def test_mpv_ipc_helpers_cannot_leak_a_socket(fn):
    """Each closed its socket only after the last statement, so any raise in
    between leaked the fd -- the ResourceWarnings in the session log."""
    src = inspect.getsource(getattr(ex, fn))
    assert "with _sock.socket(" in src, f"{fn} no longer uses a context manager"
    assert not re.search(r"^\s*s = _sock\.socket\(", src, re.M), \
        f"{fn} constructs a bare socket outside a with-block again"


def test_mpv_helpers_survive_a_missing_socket():
    """Nothing here may raise when mpv is not running."""
    assert ex._mpv_load_confirmed("/nonexistent/eli-test.sock") is False
    assert ex._mpv_load_confirmed("") is False
