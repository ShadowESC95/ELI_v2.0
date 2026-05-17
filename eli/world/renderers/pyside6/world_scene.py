from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

from eli.gui.qt_compat import (
    QBrush,
    QColor,
    QGraphicsEllipseItem,
    QGraphicsLineItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QPen,
)
from eli.world.avatar.locomotion import ROOM_COORDS
from eli.world.core.ontology import get_default_rooms


ROOM_PALETTE = {
    "core_room": ("#20302f", "#86d1bd"),
    "memory_archive": ("#2c2a3f", "#c8b6ff"),
    "workshop": ("#3b301f", "#e6b85c"),
    "reflection_chamber": ("#253449", "#9fc7ff"),
    "debug_basement": ("#332526", "#ff8f75"),
    "upgrade_bay": ("#273a2b", "#a8df82"),
    "simulation_lab": ("#23373c", "#74d7e4"),
    "anomaly_room": ("#3c263a", "#ee91dc"),
    "evidence_wall": ("#3b3525", "#f0d37b"),
}


def _room_label(room: str, rooms: Dict[str, Dict[str, Any]]) -> str:
    info = rooms.get(room) or {}
    return str(info.get("name") or room.replace("_", " ").title())


def _short(text: Any, limit: int = 22) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= limit:
        return value
    return value[: max(1, limit - 1)].rstrip() + "..."


class EliWorldScene(QGraphicsScene):
    """House-style renderer for the symbolic Eli World state."""

    def __init__(self) -> None:
        super().__init__()
        self.rooms = get_default_rooms()
        self.setSceneRect(-510, -380, 1020, 760)
        self.room_items: Dict[str, QGraphicsRectItem] = {}
        self.object_items: Dict[str, List[Any]] = {}
        self.avatar_item = QGraphicsEllipseItem(-14, -14, 28, 28)
        self.avatar_item.setBrush(QBrush(QColor("#f4f7cf")))
        self.avatar_item.setPen(QPen(QColor("#2d3220"), 2))
        self._draw_house()

    def _palette(self, room: str) -> Tuple[QColor, QColor]:
        fill, accent = ROOM_PALETTE.get(room, ("#282d35", "#b8c2cc"))
        return QColor(fill), QColor(accent)

    def _add_text(self, text: str, x: float, y: float, color: str = "#f1f3e8", width: int = 140) -> QGraphicsTextItem:
        item = QGraphicsTextItem(text)
        item.setDefaultTextColor(QColor(color))
        item.setTextWidth(width)
        item.setPos(x, y)
        self.addItem(item)
        return item

    def _draw_background(self) -> None:
        bg = QGraphicsRectItem(-510, -380, 1020, 760)
        bg.setBrush(QBrush(QColor("#d8dcc7")))
        bg.setPen(QPen(QColor("#b8c0aa"), 1))
        self.addItem(bg)

        floor = QGraphicsRectItem(-470, -330, 940, 660)
        floor.setBrush(QBrush(QColor("#e7e1c9")))
        floor.setPen(QPen(QColor("#9a8f6f"), 2))
        self.addItem(floor)

        for y in range(-300, 321, 40):
            line = QGraphicsLineItem(-470, y, 470, y)
            line.setPen(QPen(QColor("#d4ccb2"), 1))
            self.addItem(line)

    def _draw_connections(self) -> None:
        core = ROOM_COORDS.get("core_room", (0.0, 0.0))
        for room, (x, y) in ROOM_COORDS.items():
            if room == "core_room":
                continue
            line = QGraphicsLineItem(core[0], core[1], x, y)
            line.setPen(QPen(QColor("#887e68"), 3))
            self.addItem(line)

    def _draw_house(self) -> None:
        self._draw_background()
        self._draw_connections()
        self._draw_rooms()
        self.addItem(self.avatar_item)
        self._add_text("ELI's House", -470, -365, "#2f392e", 260)

    def _draw_rooms(self) -> None:
        for room, (x, y) in ROOM_COORDS.items():
            fill, accent = self._palette(room)
            rect = QGraphicsRectItem(x - 82, y - 52, 164, 104)
            rect.setPen(QPen(accent, 3))
            rect.setBrush(QBrush(fill))
            self.addItem(rect)
            self.room_items[room] = rect

            door = QGraphicsRectItem(x - 12, y + 39, 24, 14)
            door.setBrush(QBrush(QColor("#e7e1c9")))
            door.setPen(QPen(accent, 1))
            self.addItem(door)

            self._add_room_details(room, x, y, accent)
            self._add_text(_room_label(room, self.rooms), x - 72, y - 49, "#fff8df", 146)

    def _add_room_details(self, room: str, x: float, y: float, accent: QColor) -> None:
        pen = QPen(accent, 2)
        soft_pen = QPen(QColor("#f5ead2"), 1)
        if room == "memory_archive":
            for off in (-48, -20, 8):
                shelf = QGraphicsRectItem(x + off, y - 12, 18, 38)
                shelf.setBrush(QBrush(QColor("#433f62")))
                shelf.setPen(soft_pen)
                self.addItem(shelf)
        elif room == "workshop":
            bench = QGraphicsRectItem(x - 52, y + 10, 104, 16)
            bench.setBrush(QBrush(QColor("#6e5130")))
            bench.setPen(pen)
            self.addItem(bench)
            lamp = QGraphicsLineItem(x + 34, y - 8, x + 48, y + 10)
            lamp.setPen(pen)
            self.addItem(lamp)
        elif room == "reflection_chamber":
            mirror = QGraphicsEllipseItem(x - 24, y - 16, 48, 34)
            mirror.setBrush(QBrush(QColor("#314961")))
            mirror.setPen(pen)
            self.addItem(mirror)
        elif room == "debug_basement":
            for off in (-44, -12, 20):
                console = QGraphicsRectItem(x + off, y - 6, 24, 20)
                console.setBrush(QBrush(QColor("#4b2b2b")))
                console.setPen(QPen(QColor("#ffb09d"), 1))
                self.addItem(console)
        elif room == "upgrade_bay":
            rack = QGraphicsRectItem(x - 42, y - 10, 84, 42)
            rack.setBrush(QBrush(QColor("#314d34")))
            rack.setPen(pen)
            self.addItem(rack)
            for off in (-26, 0, 26):
                line = QGraphicsLineItem(x + off, y - 8, x + off, y + 30)
                line.setPen(QPen(QColor("#d5efbc"), 1))
                self.addItem(line)
        elif room == "simulation_lab":
            for off in (-40, -20, 0, 20, 40):
                h = QGraphicsLineItem(x - 45, y + off / 2, x + 45, y + off / 2)
                v = QGraphicsLineItem(x + off, y - 22, x + off, y + 22)
                h.setPen(QPen(QColor("#9deefa"), 1))
                v.setPen(QPen(QColor("#9deefa"), 1))
                self.addItem(h)
                self.addItem(v)
        elif room == "anomaly_room":
            container = QGraphicsEllipseItem(x - 25, y - 18, 50, 38)
            container.setBrush(QBrush(QColor("#552c52")))
            container.setPen(pen)
            self.addItem(container)
        elif room == "evidence_wall":
            board = QGraphicsRectItem(x - 42, y - 18, 84, 44)
            board.setBrush(QBrush(QColor("#5b4d2c")))
            board.setPen(pen)
            self.addItem(board)
            for off in (-26, 0, 26):
                pin = QGraphicsEllipseItem(x + off - 3, y - 1, 6, 6)
                pin.setBrush(QBrush(QColor("#f8db75")))
                pin.setPen(soft_pen)
                self.addItem(pin)
        else:
            core = QGraphicsEllipseItem(x - 24, y - 18, 48, 36)
            core.setBrush(QBrush(QColor("#39504d")))
            core.setPen(pen)
            self.addItem(core)

    def _object_color(self, obj: Dict[str, Any]) -> QColor:
        obj_type = str(obj.get("object_type") or "").lower()
        if "fault" in obj_type or "debug" in obj_type:
            return QColor("#ff8f75")
        if "evidence" in obj_type:
            return QColor("#f0d37b")
        if "reflection" in obj_type:
            return QColor("#9fc7ff")
        if "upgrade" in obj_type:
            return QColor("#a8df82")
        if "memory" in obj_type or "diagnostic" in obj_type:
            return QColor("#c8b6ff")
        return QColor("#86d1bd")

    def _clear_objects(self) -> None:
        for items in self.object_items.values():
            for item in items:
                try:
                    self.removeItem(item)
                except Exception:
                    pass
        self.object_items.clear()

    def _room_object_offset(self, idx: int) -> Tuple[float, float]:
        return -52 + (idx % 4) * 34, 8 + ((idx // 4) % 2) * 21

    def _room_items_for_objects(self, objects: Iterable[Tuple[str, Dict[str, Any]]]) -> None:
        room_counts: Dict[str, int] = {}
        for object_id, obj in objects:
            if obj.get("retired"):
                continue
            room = str(obj.get("room") or "core_room")
            idx = room_counts.get(room, 0)
            room_counts[room] = idx + 1
            rx, ry = ROOM_COORDS.get(room, (0.0, 0.0))
            ox, oy = self._room_object_offset(idx)
            dot = QGraphicsEllipseItem(-7, -7, 14, 14)
            dot.setBrush(QBrush(self._object_color(obj)))
            dot.setPen(QPen(QColor("#fffbe8"), 1))
            dot.setPos(rx + ox, ry + oy)
            try:
                dot.setToolTip(str(obj.get("symbolic_meaning") or obj.get("reason") or object_id))
            except Exception:
                pass
            self.addItem(dot)

            label = self._add_text(_short(obj.get("name") or object_id, 18), rx + ox + 8, ry + oy - 10, "#fff8df", 68)
            self.object_items[object_id] = [dot, label]

    def update_from_state(self, state: Dict[str, Any]) -> None:
        avatar = state.get("avatar", {})
        room = str(avatar.get("room") or "core_room")
        x, y = ROOM_COORDS.get(room, (0.0, 0.0))
        self.avatar_item.setPos(x, y + 34)
        try:
            self.avatar_item.setToolTip(
                f"{avatar.get('name', 'ELI')} | {avatar.get('activity')} | {avatar.get('expression')}"
            )
        except Exception:
            pass

        for r, rect in self.room_items.items():
            _fill, accent = self._palette(r)
            width = 5 if r == room else 3
            rect.setPen(QPen(QColor("#f7f2b8") if r == room else accent, width))

        self._clear_objects()
        objects = state.get("objects", {}) or {}
        self._room_items_for_objects(list(objects.items())[:80])

