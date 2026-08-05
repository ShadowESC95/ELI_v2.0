"""Behaviour locks for open-target routing and self-explanation.

Every case here is a defect observed in a live session:

  * "open downloads" / "open ~/Downloads" launched an APP and offered to
    install a program called "downloads" — the router's path branch had been
    made unreachable by a variable that was reassigned before it was read.
  * "open home directory and the downloads directory" opened home, reported
    success, and silently dropped the second target.
  * "fair play on your explanation, but …" routed to Bluetooth audio with the
    rest of the sentence as a device name.
  * An OPEN_APP resolved by the model carried {"app_name": …}; the executor
    read only "name"/"app" and answered "Missing app name".
  * "why did you say that" printed a ~6,000-character repr of the plan dict.
"""
import threading

import pytest

from eli.execution import router_enhanced as router


def _route(text: str) -> dict:
    out = router.route(text)
    assert isinstance(out, dict) and "action" in out, f"{text!r} -> {out!r}"
    return out


def _matched_by(out: dict) -> str:
    return str((out.get("meta") or {}).get("matched_by") or "")


# ── well-known folders are locations, never app launches ────────────────────
@pytest.mark.parametrize("phrase", [
    "open downloads",
    "open the downloads folder",
    "open download directory",
    "open documents",
    "open desktop",
    "open pictures",
    "open ~/Downloads",
    "open /home",
])
def test_known_folders_open_the_file_manager(phrase):
    out = _route(phrase)
    assert out["action"] == "OPEN_FILE_SYSTEM", (
        f"{phrase!r} must open a location, not launch an app: {out!r}")
    assert str((out.get("args") or {}).get("path") or "").strip()


def test_folder_name_resolves_to_a_real_path_not_the_bare_word():
    """The executor probes Path.home()/<token>; on a case-sensitive filesystem
    'downloads' does not exist, only 'Downloads' does."""
    path = (_route("open downloads").get("args") or {}).get("path")
    assert path and path != "downloads"
    assert path.lower().endswith("downloads")


# ── app launches must still reach the app launcher ──────────────────────────
@pytest.mark.parametrize("phrase", ["open spotify", "open steam", "launch firefox"])
def test_apps_still_route_to_open_app(phrase):
    assert _route(phrase)["action"] == "OPEN_APP", phrase


def test_conjunction_in_an_app_name_is_not_split():
    out = _route("open steam and chill")
    assert out["action"] == "OPEN_APP"
    assert "steam and chill" in str(out.get("args"))


def test_bare_domain_still_opens_a_url():
    out = _route("open github.com")
    assert out["action"] == "OPEN_URL"


# ── compound targets: both, or it is a silent data loss bug ─────────────────
def test_two_folders_open_both():
    out = _route("open home directory and the downloads directory")
    assert out["action"] == "SEQUENCE", out
    steps = (out.get("args") or {}).get("steps") or []
    assert len(steps) == 2, out
    assert all(s.get("action") == "OPEN_FILE_SYSTEM" for s in steps)
    paths = [str((s.get("args") or {}).get("path", "")).lower() for s in steps]
    assert any(p == "~" or p.endswith("home") or p == "/home/" for p in paths), paths
    assert any(p.endswith("downloads") for p in paths), paths


# ── the audio matcher must not eat prose ────────────────────────────────────
@pytest.mark.parametrize("phrase", [
    "switch audio to the kitchen speaker",
    "change sound to my headphones",
    "route audio to the bedroom speaker",
])
def test_real_audio_routing_still_works(phrase):
    out = _route(phrase)
    assert out["action"] == "SMART_HOME", f"{phrase!r} -> {out!r}"
    assert _matched_by(out) in {"audio.output", "bluetooth.audio"}


@pytest.mark.parametrize("phrase", [
    "fair play on your explanation, but i am talking about something different",
    "move on to the next thing",
    "switch to the other approach and tell me what you think",
])
def test_prose_never_routes_to_bluetooth_audio(phrase):
    out = _route(phrase)
    assert out["action"] != "SMART_HOME", (
        f"{phrase!r} is conversation, not a device command: {out!r}")


def test_device_name_is_never_a_whole_sentence():
    out = _route("fair play on your explanation, but i am talking about something else entirely")
    device = str((out.get("args") or {}).get("device") or "")
    assert len(device.split()) <= 5, device


# ── the model may name args whatever it likes ───────────────────────────────
def test_llm_arg_aliases_are_normalised_additively():
    from eli.cognition.llm_intent import normalize_args
    out = normalize_args({"app_name": "cyberpunk 2077"})
    assert out["name"] == "cyberpunk 2077"
    assert out["app_name"] == "cyberpunk 2077", "existing keys must be preserved"
    assert normalize_args({"file_path": "/tmp/x.py"})["path"] == "/tmp/x.py"
    assert normalize_args({"value": 40})["level"] == 40


def test_normalise_does_not_overwrite_a_real_value():
    from eli.cognition.llm_intent import normalize_args
    assert normalize_args({"name": "a", "app_name": "b"})["name"] == "a"


def test_open_app_accepts_app_name_from_the_resolver():
    """The executor must not reject an understood request over a key name.

    Opening a missing app PERSISTS a "shall I install it?" offer, and a stale
    offer hijacks the next short command — so the offer is cleared on both
    sides of the call rather than left in the developer's runtime state.
    """
    from eli.execution import executor_enhanced as ex
    from eli.runtime.grounded_remediation import clear_pending

    clear_pending()
    try:
        res = ex.execute("OPEN_APP", {"app_name": "definitely-not-installed-xyz"})
    finally:
        clear_pending()
    assert isinstance(res, dict)
    assert "missing app name" not in str(res.get("error", "")).lower(), res


# ── self-explanation must be readable, not a struct dump ────────────────────
def test_plan_is_summarised_not_dumped():
    from eli.runtime.control_contracts import _trace_text
    plan = {
        "type": "quick_direct", "primary_action": "TILE_WINDOWS",
        "reasoning_mode": "quick", "query_class": "GENERAL",
        "agents_used": ["system"],
        "stage_order": [f"{i} stage" for i in range(1, 13)],
        "stage_matrix": [{"stage": i, "skippable": False} for i in range(1, 13)],
        "mode_contract": {"runtime": {"degrade_path": [{"priority": p} for p in range(3)]}},
    }
    text = _trace_text({"request_id": "req-1", "action": "TILE_WINDOWS",
                        "aggregated_confidence": 0.3, "plan": plan})
    assert "stage_matrix" not in text and "degrade_path" not in text, text
    assert "quick_direct" in text and "TILE_WINDOWS" in text
    assert len(text) < 1000, f"trace evidence ballooned to {len(text)} chars"


def test_routing_fault_questions_reach_the_explainer():
    for phrase in ("why did that one finally work and the others did not?",
                   "why did you fail to open downloads"):
        assert _route(phrase)["action"] == "ROUTING_FAULT_EXPLAIN", phrase


def test_routing_fault_explanation_is_derived_not_canned():
    """It used to return a fixed paragraph about a browser regardless of input."""
    from eli.runtime.personal_memory_deep_response import build_routing_fault_explanation
    text = build_routing_fault_explanation(
        'why did that work? i typed "open downloads" and "open spotify"')
    assert "open downloads" in text and "open spotify" in text, text
    assert "OPEN_FILE_SYSTEM" in text, text


# ── world state is read concurrently by three subsystems ────────────────────
def test_concurrent_world_state_reads_do_not_race():
    from eli.world.local_world_bridge import get_world_state
    errors = []

    def worker():
        for _ in range(15):
            try:
                get_world_state()
            except Exception as exc:  # pragma: no cover - the bug under test
                errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, f"world-state race: {errors[:3]}"
