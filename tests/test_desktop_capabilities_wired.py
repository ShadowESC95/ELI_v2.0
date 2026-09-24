"""The desktop-control probe feeds the awareness briefing and SELF_TEST."""
from eli.perception import desktop_capabilities as dc
from eli.runtime.awareness_boot import AwarenessState


def test_the_summary_line_names_each_backend():
    line = dc.format_runtime_tools({
        "platform": "linux", "display_server": "wayland",
        "input": {"primary": "ydotool", "fallback": "pyautogui"},
        "screenshot": {"primary": "grim+slurp"},
        "locate": {"backends": ["atspi", "ocr"]},
    })
    assert line == ("linux/wayland: input via ydotool (fallback pyautogui); "
                    "screenshots via grim+slurp; find-on-screen via atspi, ocr")


def test_a_host_with_nothing_says_so_plainly():
    line = dc.format_runtime_tools({
        "platform": "android", "display_server": "other",
        "input": {"primary": "none", "fallback": "none"},
        "screenshot": {"primary": "none"}, "locate": {"backends": []},
    })
    assert "input via none" in line and "find-on-screen via none" in line


def test_the_briefing_carries_the_desktop_control_line():
    state = AwarenessState()
    state.desktop_control = "linux/x11: input via xdotool"
    state.platform_report = "platforms ok"
    text = state.full_briefing()
    assert "Desktop control: linux/x11: input via xdotool" in text
