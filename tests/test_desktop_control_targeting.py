"""Behaviour locks for desktop control acting on the thing the user named.

Every case here is a defect observed in a live 2.3.15 session:

  * "maximise prime video" maximised the terminal. The router extracted
    window_name="prime video" correctly; the executor's MAXIMISE_WINDOW branch
    never read args at all and ran `wmctrl -r :ACTIVE:` unconditionally.
    MINIMISE_WINDOW, twelve lines above it, did read the name — the two halves
    of window control had drifted apart.
  * "open a browser on QFT" and "open browser QFT" were captured whole as app
    names and answered with "not installed on this machine — would you like me
    to download it?". OPEN_BROWSER has accepted a query all along; three
    separate matchers claimed the phrase first.
  * "click enter", "click enter button" and "move cursor right" moved nothing
    while the executor reported success for all three: unrecognised actions
    fell into an `else` that returned ok=True without touching the mouse,
    clicks required both x and y, relative movement was never implemented,
    and "enter" is a key that had arrived in the mouse-button slot.
"""
import re
from pathlib import Path

import pytest

from eli.execution import router_enhanced as router
from eli.execution import executor_enhanced as ex
from eli.system import portable_app_control as pac


def _route(text: str) -> dict:
    out = router.route(text)
    assert isinstance(out, dict) and "action" in out, f"{text!r} -> {out!r}"
    return out


# ── a browser request is a browser request ─────────────────────────────────
@pytest.mark.parametrize("phrase,query", [
    ("open a browser on QFT", "qft"),
    ("open browser QFT", "qft"),
    ("open a web browser on quantum field theory", "quantum field theory"),
    ("open browser for quantum mechanics", "quantum mechanics"),
    ("open the browser and search QFT", "qft"),
])
def test_browser_with_a_subject_opens_a_search(phrase, query):
    out = _route(phrase)
    assert out["action"] == "OPEN_BROWSER", f"{phrase!r} -> {out['action']}"
    assert (out.get("args") or {}).get("query", "").lower() == query


@pytest.mark.parametrize("phrase", ["open browser", "open the browser", "open a browser"])
def test_bare_browser_opens_the_default_browser(phrase):
    out = _route(phrase)
    assert out["action"] == "OPEN_BROWSER", f"{phrase!r} -> {out['action']}"
    assert not (out.get("args") or {}).get("query")


@pytest.mark.parametrize("phrase", [
    "open a browser on QFT", "open browser QFT", "open browser",
    "open a web browser on quantum field theory",
])
def test_browser_requests_never_become_app_installs(phrase):
    """The observed failure was an offer to install a program called
    'a browser on qft'."""
    out = _route(phrase)
    assert out["action"] != "OPEN_APP", f"{phrase!r} still routes to OPEN_APP"


# ── things that must keep working ──────────────────────────────────────────
@pytest.mark.parametrize("phrase,action", [
    ("open firefox", "OPEN_APP"),
    ("open spotify", "OPEN_APP"),
    ("open a terminal", "OPEN_APP"),
    ("open camera", "OPEN_APP"),
    ("open steam", "OPEN_APP"),
    ("open downloads", "OPEN_FILE_SYSTEM"),
    ("open home folder", "OPEN_FILE_SYSTEM"),
    ("open the trash", "OPEN_FILE_SYSTEM"),
    ("open github.com", "OPEN_URL"),
])
def test_other_open_targets_are_unchanged(phrase, action):
    assert _route(phrase)["action"] == action, f"{phrase!r} regressed"


def test_named_browsers_still_launch_as_apps():
    """'open firefox' is an app launch; only the generic word is a surface."""
    out = _route("open firefox")
    assert out["action"] == "OPEN_APP"
    assert "firefox" in str(out.get("args"))


# ── maximise must act on the named window, or on nothing ───────────────────
def test_maximise_uses_the_named_window(monkeypatch):
    seen = {}

    def _fake_maximize(name):
        seen["name"] = name
        return {"ok": True, "action": "MAXIMIZE_APP", "content": f"Maximised {name}."}

    monkeypatch.setattr(pac, "maximize_app", _fake_maximize)
    res = ex.execute("MAXIMISE_WINDOW", {"window_name": "prime video"})
    assert seen.get("name") == "prime video", "the named window was discarded again"
    assert res.get("ok") is True


@pytest.mark.parametrize("key", ["name", "target", "app", "window_name", "window"])
def test_maximise_reads_every_target_key_the_router_emits(monkeypatch, key):
    seen = {}
    monkeypatch.setattr(pac, "maximize_app",
                        lambda name: seen.setdefault("name", name) and None
                        or {"ok": True, "action": "MAXIMIZE_APP", "content": "ok"})
    ex.execute("MAXIMISE_WINDOW", {key: "prime video"})
    assert seen.get("name") == "prime video", f"args[{key!r}] ignored"


def test_maximise_does_not_fall_back_to_the_active_window(monkeypatch):
    """Acting on a different window than the one named is the defect itself."""
    monkeypatch.setattr(pac, "maximize_app",
                        lambda name: {"ok": False, "action": "MAXIMIZE_APP",
                                      "content": f"Could not find a window for: {name}"})
    res = ex.execute("MAXIMISE_WINDOW", {"window_name": "prime video"})
    assert res.get("ok") is False, "a missing named window silently maximised something else"
    assert "prime video" in str(res.get("content", ""))


@pytest.mark.parametrize("bare", [{}, {"name": ""}, {"name": "current window"},
                                  {"name": "it"}, {"name": "this"}])
def test_bare_maximise_still_means_the_active_window(monkeypatch, bare):
    called = {"n": 0}

    def _fake(name):
        called["n"] += 1
        return {"ok": True, "content": "should not be reached"}

    monkeypatch.setattr(pac, "maximize_app", _fake)
    ex.execute("MAXIMISE_WINDOW", bare)
    assert called["n"] == 0, f"{bare!r} was treated as a named target"


def test_maximize_app_exists_for_every_platform():
    src = Path("eli/system/portable_app_control.py").read_text(encoding="utf-8")
    block = src[src.index("def maximize_app"):]
    for plat in ('"linux"', '"darwin"', '"windows"', '"android"'):
        assert plat in block, f"maximize_app has no {plat} branch"


# ── the mouse must not report work it did not do ───────────────────────────
@pytest.mark.parametrize("args", [
    {"action": "click", "button": "purple"},
    {"action": "levitate"},
    {"action": "move"},
    {"action": "move", "direction": "sideways"},
    {},
])
def test_impossible_mouse_requests_fail_honestly(args):
    res = ex.execute("MOUSE_CONTROL", args)
    assert res.get("ok") is False, f"{args!r} reported success without acting"
    assert str(res.get("content", "")).strip(), "failed silently with no explanation"


def test_key_in_the_button_slot_is_pressed_not_clicked(monkeypatch):
    """'click enter' is a keystroke. It used to be an unclickable button."""
    import eli.perception.os_controller as osc
    pressed = {}
    monkeypatch.setattr(osc, "press_key",
                        lambda k: pressed.setdefault("key", k) and None
                        or {"ok": True, "content": f"Pressed {k}"})
    res = ex.execute("MOUSE_CONTROL", {"action": "click", "button": "enter"})
    assert pressed.get("key") == "enter", "the key was not routed to the keyboard"
    assert res.get("ok") is True
    assert res.get("rerouted_from") == "MOUSE_CONTROL"


def _strip_comments(code: str) -> str:
    """Structural checks must read code, not the comments describing the bug
    being prevented — those legitimately quote the old broken values."""
    return "\n".join(line.split("#", 1)[0] for line in code.splitlines())


def _mouse_branch() -> str:
    src = Path("eli/execution/executor_enhanced.py").read_text(encoding="utf-8")
    start = src.index('if a == "MOUSE_CONTROL":')
    end = src.index("# ---- SET_CLIPBOARD / GET_CLIPBOARD ----", start)
    return _strip_comments(src[start:end])


def test_mouse_branch_has_no_unconditional_success():
    branch = _mouse_branch()
    assert "performed" not in branch, "the phantom-success message is back"
    # Every success return must be reached from a backend result, never from
    # a bare else. The backends are the only places that build an ok=True.
    assert branch.count('"ok": True') == 1, (
        "more than one success path in MOUSE_CONTROL — the single one is the "
        "backend loop, which only runs after a backend reports it acted"
    )


def test_mouse_branch_supports_relative_movement():
    branch = _mouse_branch()
    assert "mousemove_relative" in branch or "moveRel" in branch, \
        "relative movement ('move cursor right') is unimplemented again"


def test_wayland_click_releases_the_button():
    """The old ydotool codes sent a press with no release — a stuck button —
    and named the wrong buttons (0x40001 is right-down, not left-click)."""
    branch = _mouse_branch()
    assert "0x40001" not in branch and "0x40002" not in branch, \
        "the press-without-release ydotool codes are back"
    assert "0xC0" in branch, "left click should be 0xC0 (down+up) for ydotool"


# ── Linux is two platforms: X11 and Wayland ────────────────────────────────
def test_display_server_is_detected():
    ds = pac.display_server()
    assert ds in {"wayland", "x11", ""}, ds


def test_wayland_failure_explains_itself():
    """wmctrl/xdotool see only XWayland windows, so under Wayland they fail
    silently. A bare 'Failed to maximise window' tells the user nothing."""
    advice = pac._wayland_window_advice("maximise Prime Video")
    low = advice.lower()
    assert "wayland" in low
    assert "kdotool" in low or "xwayland" in low
    assert "maximise prime video" in low


def test_wayland_capable_tools_are_attempted():
    src = Path("eli/system/portable_app_control.py").read_text(encoding="utf-8")
    block = src[src.index("def maximize_app"):]
    assert "_wayland_window_tools()" in block, "Wayland tools are never tried"
    assert "kdotool" in src and "wlrctl" in src


@pytest.mark.parametrize("platform_marker,forbidden", [
    ("win", "apt install"),
    ("darwin", "apt install"),
])
def test_mouse_advice_is_not_linux_only(platform_marker, forbidden):
    """The fallback told Windows and macOS users to `apt install xdotool`."""
    branch = _mouse_branch()
    idx = branch.index(platform_marker)
    window = branch[idx:idx + 400]
    assert forbidden not in window, f"{platform_marker} advice still says {forbidden!r}"


def test_macos_mouse_advice_mentions_accessibility():
    """macOS blocks synthetic input entirely until the app is granted
    Accessibility permission — without that note the failure looks like a bug."""
    branch = _mouse_branch()
    assert "Accessibility" in branch
