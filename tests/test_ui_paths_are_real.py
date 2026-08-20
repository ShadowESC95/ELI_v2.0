"""Locks user-facing "go to Settings ▸ X" instructions against the real GUI.

A live session (v2.1.64, 21:17): the user asked how to record their voice. ELI replied
``Settings > Voice > "Create a voice from an audio file…"``. The user went looking, said
"i cannot se that option there", and ELI repeated the same path back.

It was not a hallucination — the string is hard-coded in the CREATE_VOICE handler in
``executor_enhanced.py``. Both halves were wrong:

  * there is no **Voice** settings page. The pages are: advanced, agents, app, audio,
    gaze, generation, identity, model, runtime, server;
  * the create-voice drop-zone lives on the **Runtime** page, in the "VOICE / TTS" card
    (``_build_settings_runtime_page``), labelled "Drop an audio/video clip here, or
    click to browse…" — not "Create a voice from an audio file…".

Two further strings pointed at the same non-existent page (the voice-library hint in
LIST_VOICES and the onboarding blurb in ``panels/startup.py``).

These tests read the GUI source rather than trusting prose, so a page rename breaks the
build instead of quietly sending users somewhere that does not exist.
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _read(*parts: str) -> str:
    return (REPO.joinpath(*parts)).read_text(encoding="utf-8")


def _without_comments(src: str) -> str:
    """Drop ``#`` comment lines.

    Required, not cosmetic: the fix for this bug documents the OLD wrong path in a
    comment so the next reader knows what changed. Matching that comment is exactly
    how a test passes while proving nothing — it would have reported the phantom
    label as still present when only the explanation of it remained.
    """
    return "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))


GUI = _read("eli", "gui", "eli_pro_audio_gui_v2_0.py")
EXECUTOR = _without_comments(_read("eli", "execution", "executor_enhanced.py"))
STARTUP = _without_comments(_read("eli", "gui", "panels", "startup.py"))

# The settings pages that actually exist, derived from the builders themselves.
#
# There are TWO settings surfaces and a user can legitimately be sent to either:
# the main window's Settings tab (Model / Runtime / Generation / …), built by
# `_build_settings_<name>_page` in the GUI god-file, and the Settings *dialog*
# (Agents / Models / Cognition / Plugins / Marketplace / Self-Upgrade), whose pages
# are inner tabs registered in panels/settings.py. Discovering only the first made
# a correct instruction — "Settings > Marketplace" — look like a broken one.
SETTINGS_PANEL = _without_comments(_read("eli", "gui", "panels", "settings.py"))

REAL_PAGES = {
    m.group(1) for m in re.finditer(r"_build_settings_([a-z_]+)_page", GUI)
} | {
    m.group(1) for m in re.finditer(r"_build_([a-z_]+)_tab", SETTINGS_PANEL)
} | {
    # Inner-tab labels carry an emoji prefix; take the trailing word.
    m.group(1).lower()
    for m in re.finditer(r'inner_tabs\.addTab\([^,]+,\s*"[^"]*?([A-Za-z-]+)"',
                         SETTINGS_PANEL)
}


def test_the_settings_pages_are_discovered():
    """Guard the guard: if this ever comes back empty the assertions below are vacuous."""
    assert len(REAL_PAGES) >= 8, REAL_PAGES
    assert "runtime" in REAL_PAGES and "audio" in REAL_PAGES


def test_there_is_no_voice_settings_page():
    """The premise of the bug. If a Voice page is ever added, the strings that used to
    be wrong become right and this test should be updated deliberately."""
    assert "voice" not in REAL_PAGES


@pytest.mark.parametrize("src,label", [
    (EXECUTOR, "executor_enhanced.py"),
    (STARTUP, "panels/startup.py"),
])
def test_no_user_facing_string_points_at_a_voice_settings_page(src, label):
    """Catches "Settings > Voice", "Settings ▸ Voice", "Settings>Voice"."""
    hits = re.findall(r"Settings\s*[>▸]\s*Voice\b", src)
    assert not hits, f"{label} still directs users to a Settings page that does not exist"


def test_every_settings_page_named_in_the_executor_exists():
    """Any "Settings ▸ X" the executor tells a user to open must be a real page."""
    named = {m.group(1).lower() for m in re.finditer(r"Settings\s*[>▸]\s*([A-Za-z]+)", EXECUTOR)}
    unknown = named - REAL_PAGES
    assert not unknown, f"executor points at non-existent settings page(s): {sorted(unknown)}"


# ── the create-voice instruction specifically ───────────────────────────────
def _create_voice_message() -> str:
    """The guidance CREATE_VOICE returns when given no file — what the user saw."""
    i = EXECUTOR.index('if a == "CREATE_VOICE":')
    return EXECUTOR[i:i + 2500]


def test_create_voice_no_longer_cites_the_old_phantom_label():
    assert "Create a voice from an audio file" not in _create_voice_message()


def test_create_voice_points_at_the_runtime_page():
    msg = _create_voice_message()
    assert re.search(r"Settings\s*[>▸]\s*Runtime", msg), "does not name the real page"


def test_create_voice_quotes_the_card_that_hosts_the_control():
    assert "VOICE / TTS" in _create_voice_message()
    assert 'self._section_card(vbox, "VOICE / TTS")' in GUI, "the card was renamed"


def test_the_drop_zone_label_quoted_to_users_exists_in_the_gui():
    """The text a user will scan the screen for must be text the screen shows."""
    quoted = "Drop an audio/video clip here, or click to browse"
    assert quoted in _create_voice_message()
    assert quoted in GUI, "instruction quotes a label the GUI does not render"


def test_the_create_voice_control_really_is_on_the_runtime_page():
    """Parse the GUI: the drop-zone must sit inside _build_settings_runtime_page."""
    import ast

    tree = ast.parse(GUI)
    drop_line = next(
        i + 1 for i, ln in enumerate(GUI.splitlines())
        if "Drop an audio/video clip here" in ln
    )
    hosts = [
        n.name for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef)
        and n.lineno <= drop_line <= (n.end_lineno or 0)
        and n.name.startswith("_build_settings_")
    ]
    assert hosts == ["_build_settings_runtime_page"], hosts


def test_create_voice_still_lists_the_accepted_formats():
    """The rest of the guidance must survive the path correction."""
    msg = _create_voice_message()
    for ext in (".wav", ".mp3", ".mp4"):
        assert ext in msg, ext
