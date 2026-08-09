"""Locks on the Devices tab's room assignment and manual add flow.

Two defects, both of the "does nothing and says nothing" kind:

* Moving a device to a room used a bare `prompt()` asking the user to TYPE the
  room name. One typo silently created a second room ("Kitchen" vs "kitchen")
  and the device disappeared from where they expected it, with no explanation.
* The manual add form was unlabelled MQTT jargon, and `if(!body.device_id)return;`
  meant pressing **Add** with an empty ID did nothing whatsoever — no error, no
  hint. Backend `{"ok": false, "error": ...}` responses were dropped too, so a
  rejected add looked exactly like a successful one.

These are source-level assertions on api/static/app.js. The suite has no browser
and no JS engine binding, so behaviour is pinned where it is expressible: the
call shapes and the absence of the patterns that caused the failures. The drag
handlers themselves are covered only structurally — that is a real limit, not a
claim that the gesture was exercised.
"""
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_JS = REPO_ROOT / "api" / "static" / "app.js"
APP_CSS = REPO_ROOT / "api" / "static" / "app.css"


@pytest.fixture(scope="module")
def js() -> str:
    return APP_JS.read_text(encoding="utf-8")


# ── room assignment ─────────────────────────────────────────────────────────
def test_room_move_no_longer_uses_a_typed_prompt(js):
    """A typed room name is how duplicate rooms got created."""
    start = js.index("function moveDevice(")
    end = js.index("\n  function ", start + 10)
    assert "prompt(" not in js[start:end]


def test_room_move_offers_existing_rooms(js):
    start = js.index("function moveDevice(")
    end = js.index("\n  function ", start + 10)
    body = js[start:end]
    assert "_knownRooms" in body, "the picker must list rooms that already exist"
    assert "__new" in body, "creating a new room must still be possible"


def test_known_rooms_are_populated_from_the_render(js):
    assert "_knownRooms=rooms.map(" in js.replace(" ", "")


# ── drag to room ────────────────────────────────────────────────────────────
def test_device_cards_are_draggable(js):
    assert "card.setAttribute('draggable','true')" in js.replace('"', "'")


@pytest.mark.parametrize("handler", ["dragstart", "dragend", "dragover", "dragleave", "drop"])
def test_drag_handlers_are_wired(js, handler):
    assert f"'{handler}'" in js


def test_dragover_prevents_default(js):
    """Without preventDefault the browser refuses the drop and releasing does
    nothing at all — the single most common way drag-and-drop silently fails."""
    start = js.index("sec.addEventListener('dragover'")
    assert "preventDefault" in js[start:start + 260]


def test_drop_moves_the_device(js):
    start = js.index("sec.addEventListener('drop'")
    body = js[start:start + 420]
    assert "setDeviceRoom" in body


def test_unassigned_drop_clears_the_room(js):
    """'Unassigned' is a display label, not a room name — sending it as one would
    create a literal room called Unassigned."""
    start = js.index("sec.addEventListener('drop'")
    assert "rm.room==='Unassigned'" in js[start:start + 420].replace('"', "'")


def test_touch_users_keep_a_non_drag_path(js):
    """HTML5 drag events never fire on touch, so the picker is the only way in
    on a phone and must stay wired to the card."""
    assert "moveDevice(dv)" in js


def test_drag_styles_exist():
    css = APP_CSS.read_text(encoding="utf-8")
    assert ".grid .card.drag" in css
    assert ".roomsec.dropok" in css


# ── manual add ──────────────────────────────────────────────────────────────
def test_add_device_reports_failure(js):
    """The old version returned silently on a blank id and swallowed backend
    errors, so a failed add was indistinguishable from a successful one."""
    start = js.index("function addDevice(")
    end = js.index("\n  function ", start + 10)
    body = js[start:end]
    assert "if(!body.device_id){return;}" not in body.replace(" ", "")
    assert ".catch(" in body, "network failures must surface"
    assert "r.ok===false" in body.replace(" ", ""), "backend errors must surface"


def test_add_device_derives_an_id_from_the_name(js):
    """'Unique ID' is meaningless to a layman; a name should be enough."""
    start = js.index("function addDevice(")
    end = js.index("\n  function ", start + 10)
    assert "toLowerCase().replace(" in js[start:end]


def test_add_form_explains_the_mqtt_fields(js):
    start = js.index("function addDevicePrompt(")
    end = js.index("\n  function ", start + 10)
    body = js[start:end]
    assert "ESPHome" in body or "Tasmota" in body, "topics need plain-English provenance"
    assert "Command topic" in body, "fields need real labels, not bare placeholders"
