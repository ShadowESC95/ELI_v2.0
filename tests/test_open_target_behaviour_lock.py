"""Behaviour locks for open-target routing and self-explanation.

Every case here is a defect observed in a live session:

  * "open downloads" / "open ~/Downloads" launched an APP and offered to
    install a program called "downloads" — the router's path branch had been
    made unreachable by a variable that was reassigned before it was read.
  * "open home directory and the downloads directory" opened home, reported
    success, and silently dropped the second target.
  * "fair play to you on that, but …" routed to Bluetooth audio with the
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


# ── a site known by its name, or pointed at ─────────────────────────────────
#
# Live: "open nasa website" answered "nasa website is not installed on this machine ... Would
# you like me to download/install it?", and "could you open that website in the browser please",
# said after a reply that listed https://www.nasa.gov/, opened a search for "that website".

@pytest.mark.parametrize("phrase,name", [
    ("open nasa website", "nasa"),
    ("open the nasa website instead", "nasa"),
    ("open nasa site", "nasa"),                 # was https://nasa.site
    ("open bbc's home page", "bbc"),
    ("open the new york times website please", "new york times"),
])
def test_a_site_named_is_a_site_and_its_address_is_not_made_up(phrase, name):
    out = _route(phrase)
    assert out["action"] == "OPEN_URL" and out["args"] == {"site": name}


@pytest.mark.parametrize("phrase,which", [
    ("could you open that website in the browser please", 1),
    ("open that website", 1),
    ("open the second link", 2),
    ("open it in the browser", 1),
])
def test_a_page_pointed_at_is_looked_for_in_the_conversation(phrase, which):
    out = _route(phrase)
    assert out["action"] == "OPEN_URL" and out["args"]["which"] == which and out["args"]["refers_to"]


def test_a_site_in_the_table_keeps_its_address_however_it_is_asked_for():
    assert _route("open youtube")["args"] == {"url": "https://youtube.com"}
    assert _route("open youtube website")["args"] == {"url": "https://youtube.com"}


@pytest.mark.parametrize("phrase", ["open apple tv", "open notes app", "open my site", "open it"])
def test_an_ordinary_word_after_a_name_is_not_a_web_ending(phrase):
    """"tv", "app" and "site" are endings too. Without a dot they describe the thing."""
    assert _route(phrase)["action"] != "OPEN_URL"


@pytest.mark.parametrize("phrase,url", [("open github com", "https://github.com"),
                                        ("open github dot com", "https://github.com"),
                                        ("open otter.ai", "https://otter.ai")])
def test_an_address_said_aloud_is_still_an_address(phrase, url):
    assert _route(phrase)["args"] == {"url": url}


# ── the window a command names ──────────────────────────────────────────────
#
# Live: "maximise browser" had no rule, the model resolved it to MAXIMISE_WINDOW with no name and
# ELI maximised its own window; "switch to weather tab in browser" was resolved to OPEN_URL
# 'weather'. "go to the youtube tab" opened https://the youtube tab.

@pytest.mark.parametrize("phrase,action,name", [
    ("maximise browser", "MAXIMISE_WINDOW", "browser"),
    ("maximize the browser", "MAXIMISE_WINDOW", "browser"),
    ("maximise prime video", "MAXIMISE_WINDOW", "prime video"),
    ("fullscreen the browser", "MAXIMISE_WINDOW", "browser"),
    ("make the browser full screen", "MAXIMISE_WINDOW", "browser"),
    ("minimize the browser window", "MINIMIZE_APP", "browser"),
    ("minimise spotify", "MINIMIZE_APP", "spotify"),
    ("switch to firefox", "FOCUS_APP", "firefox"),
])
def test_a_window_command_keeps_the_window_it_names(phrase, action, name):
    out = _route(phrase)
    assert out["action"] == action and out["args"]["name"] == name


@pytest.mark.parametrize("phrase", ["maximise this window", "maximise the window", "fullscreen"])
def test_the_window_in_front_is_meant_only_when_none_is_named(phrase):
    out = _route(phrase)
    assert out["action"] == "MAXIMISE_WINDOW" and not out["args"].get("name")


@pytest.mark.parametrize("phrase,name", [
    ("switch to weather tab in browser", "weather"),
    ("switch to the weather tab", "weather"),
    ("go to the youtube tab", "youtube"),
])
def test_a_tab_asked_for_by_name_is_looked_for_as_a_window_title(phrase, name):
    out = _route(phrase)
    assert out["action"] == "FOCUS_APP" and out["args"] == {"name": name, "tab": True}


def test_a_tab_that_is_not_in_front_is_said_to_be_out_of_reach(monkeypatch):
    from eli.execution import executor_enhanced as ex
    from eli.system import portable_app_control as pac

    monkeypatch.setattr(pac, "focus_app", lambda name: {"ok": False, "action": "FOCUS_APP", "content": f"Could not focus {name}."})
    out = ex.execute("FOCUS_APP", {"name": "weather", "tab": True})
    assert out["ok"] is False and "No window is showing a tab called weather" in out["content"]


@pytest.mark.parametrize("phrase,args", [
    ("go to github.com", {"url": "https://github.com"}),
    ("browse to bbc.co.uk/news", {"url": "https://bbc.co.uk/news"}),
    ("go to youtube", {"url": "https://youtube.com"}),
    ("visit nasa", {"site": "nasa"}),
])
def test_going_to_a_site_uses_its_address_and_never_builds_one_from_words(phrase, args):
    out = _route(phrase)
    assert out["action"] == "OPEN_URL" and {k: v for k, v in out["args"].items() if v} == args


@pytest.mark.parametrize("phrase", ["go to sleep", "go to the next song", "go to the youtube tab"])
def test_go_to_is_not_always_an_address(phrase):
    assert _route(phrase)["action"] != "OPEN_URL"


def test_one_table_of_site_names():
    from eli.execution import app_aliases, portable_intent_contract
    assert router.WEBSITE_ALIASES is app_aliases.WEBSITE_ALIASES is portable_intent_contract.WEBSITE_ALIASES
    import inspect
    from eli.execution import executor_enhanced
    assert "_site_map" not in inspect.getsource(executor_enhanced)
    assert inspect.getsource(router).count('": "https://') == 0, "the router keeps no table of its own"


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
    "fair play to you on that, but i mean another thing",
    "move on to the next thing",
    "switch to the other approach and tell me what you think",
])
def test_prose_never_routes_to_bluetooth_audio(phrase):
    out = _route(phrase)
    assert out["action"] != "SMART_HOME", (
        f"{phrase!r} is conversation, not a device command: {out!r}")


def test_device_name_is_never_a_whole_sentence():
    out = _route("fair play to you on that, but i mean something else altogether")
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
