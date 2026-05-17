from __future__ import annotations

from typing import Any, Dict, Iterable, Tuple

from eli.gui.qt_compat import (
    QFrame,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPainter,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTimer,
    QVBoxLayout,
    QWidget,
)
from eli.world.local_world_bridge import append_event, get_world_state
from eli.world.renderers.pyside6.world_scene import EliWorldScene


def _room_name(room: str, state: Dict[str, Any]) -> str:
    rooms = state.get("rooms") or {}
    info = rooms.get(room) or {}
    return str(info.get("name") or room.replace("_", " ").title())


def _room_purpose(room: str, state: Dict[str, Any]) -> str:
    rooms = state.get("rooms") or {}
    info = rooms.get(room) or {}
    return str(info.get("purpose") or "No room purpose recorded.")


def _sentence(value: Any, fallback: str = "No signal recorded.") -> str:
    text = " ".join(str(value or "").split())
    return text or fallback


def _percent(value: Any) -> int:
    try:
        return max(0, min(100, int(float(value) * 100)))
    except Exception:
        return 0


def _recent_lines(rows: Iterable[Dict[str, Any]], *, limit: int = 6) -> str:
    out = []
    for row in list(rows or [])[-limit:]:
        kind = row.get("event_type") or row.get("action_type") or "entry"
        summary = row.get("summary") or row.get("reason") or row.get("room") or ""
        out.append(f"- {kind}: {_sentence(summary, 'No summary')}")
    return "\n".join(out) if out else "No recent world events recorded."


class EliWorldPanel(QWidget):
    """Human-readable Eli World dashboard."""

    BAR_KEYS: Tuple[Tuple[str, str], ...] = (
        ("focus", "Focus"),
        ("uncertainty", "Uncertainty"),
        ("memory_confidence", "Memory confidence"),
        ("evidence_confidence", "Evidence confidence"),
        ("repair_pressure", "Repair pressure"),
        ("reflection_depth", "Reflection depth"),
        ("tool_activity", "Tool activity"),
        ("autonomy_pressure", "Autonomy pressure"),
    )

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.scene = EliWorldScene()
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHints(QPainter.Antialiasing)
        self.status = QLabel("Eli's World: initializing")
        self.status.setStyleSheet("font-weight: 800; color: #253225;")

        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("font-size: 14px; color: #263025;")
        self.identity = QLabel("")
        self.identity.setWordWrap(True)
        self.objects = QLabel("")
        self.objects.setWordWrap(True)
        self.recent = QLabel("")
        self.recent.setWordWrap(True)
        self.actions = QLabel("")
        self.actions.setWordWrap(True)
        self.bars: Dict[str, QProgressBar] = {}

        root = QHBoxLayout(self)
        root.addWidget(self.view, 3)
        root.addWidget(self._side_panel(), 2)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1500)
        self.refresh()

    def _side_panel(self) -> QWidget:
        side = QWidget()
        outer = QVBoxLayout(side)
        outer.addWidget(self.status)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)

        layout.addWidget(self._card("Where ELI Is", self.summary))
        layout.addWidget(self._awareness_card())
        layout.addWidget(self._card("Active Room Objects", self.objects))
        layout.addWidget(self._card("Recent World Changes", self.recent))
        layout.addWidget(self._card("Identity And Rules", self.identity))
        layout.addWidget(self._manual_event_card())
        layout.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        return side

    def _card(self, title: str, body: QLabel) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame { background: #f4f0de; border: 1px solid #c8bea2; border-radius: 12px; padding: 8px; }"
            "QLabel { color: #2c3026; }"
        )
        layout = QVBoxLayout(frame)
        heading = QLabel(title)
        heading.setStyleSheet("font-weight: 800; font-size: 13px; color: #303620;")
        layout.addWidget(heading)
        layout.addWidget(body)
        return frame

    def _awareness_card(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame { background: #eef2e5; border: 1px solid #bdccb3; border-radius: 12px; padding: 8px; }"
        )
        layout = QVBoxLayout(frame)
        heading = QLabel("Awareness Gauges")
        heading.setStyleSheet("font-weight: 800; font-size: 13px; color: #303620;")
        layout.addWidget(heading)
        for key, label in self.BAR_KEYS:
            row = QHBoxLayout()
            text = QLabel(label)
            text.setMinimumWidth(132)
            bar = QProgressBar()
            bar.setRange(0, 100)
            self.bars[key] = bar
            row.addWidget(text)
            row.addWidget(bar)
            layout.addLayout(row)
        return frame

    def _manual_event_card(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame { background: #eee6d2; border: 1px solid #c8b98d; border-radius: 12px; padding: 8px; }"
        )
        layout = QVBoxLayout(frame)
        heading = QLabel("Safe Symbolic Events")
        heading.setStyleSheet("font-weight: 800; font-size: 13px; color: #303620;")
        layout.addWidget(heading)
        layout.addWidget(QLabel("These buttons alter only Eli's symbolic world state and event log."))

        buttons = [
            ("Reflect", lambda: self.inject("reflection", "Manual reflection event.", {"depth": 0.75})),
            ("Mark Memory Fog", lambda: self.inject("memory_uncertainty", "Manual memory uncertainty event.", {})),
            ("Tool Work", lambda: self.inject("tool_activity", "Manual tool activity event.", {})),
            ("Runtime Fault", lambda: self.inject("runtime_fault", "Manual runtime fault event.", {})),
            ("Weak Evidence", lambda: self.inject("evidence_weak", "Manual weak-evidence event.", {})),
            ("Stage Upgrade", lambda: self.inject("improvement_proposal", "Manual improvement proposal event.", {})),
            ("Task Complete", lambda: self.inject("task_completed", "Manual task-completed event.", {})),
            ("Refresh", self.refresh),
        ]
        for label, fn in buttons:
            button = QPushButton(label)
            button.clicked.connect(fn)
            layout.addWidget(button)
        return frame

    def inject(self, event_type: str, summary: str, payload: Dict[str, Any]) -> None:
        append_event(event_type, "eli_world_panel", summary, payload)
        self.refresh()

    def _object_summary(self, state: Dict[str, Any]) -> str:
        objects = state.get("objects") or {}
        active = [obj for obj in objects.values() if not obj.get("retired")]
        if not active:
            return "The house is quiet. No active symbolic objects are currently staged."
        lines = []
        for obj in active[-8:]:
            room = _room_name(str(obj.get("room") or "core_room"), state)
            name = obj.get("name") or obj.get("object_id") or "Object"
            reason = obj.get("symbolic_meaning") or obj.get("reason") or "No reason recorded."
            lines.append(f"- {name} in {room}: {_sentence(reason)}")
        if len(active) > 8:
            lines.append(f"- plus {len(active) - 8} older active objects not shown here.")
        return "\n".join(lines)

    def _identity_summary(self, state: Dict[str, Any]) -> str:
        identity = state.get("identity") or {}
        constitution = state.get("constitution") or {}
        principles = constitution.get("principles") or []
        purpose = identity.get("purpose") or "No world identity purpose recorded."
        local = "local-only" if identity.get("local_only") else "local flag not asserted"
        rules = "; ".join(str(p) for p in principles[:3])
        if len(principles) > 3:
            rules += f"; plus {len(principles) - 3} more rules"
        return f"{_sentence(purpose)}\nState boundary: {local}.\nRules: {rules or 'No constitution principles recorded.'}"

    def refresh(self) -> None:
        try:
            state = get_world_state()
            self.scene.update_from_state(state)
            avatar = state.get("avatar", {})
            awareness = state.get("awareness", {})
            room = str(avatar.get("room") or "core_room")
            room_name = _room_name(room, state)
            activity = avatar.get("activity") or "standing_by"
            expression = avatar.get("expression") or "neutral"
            posture = avatar.get("posture") or "idle"

            self.status.setText(f"Eli's World: {room_name} | {activity} | {expression}")
            self.summary.setText(
                f"ELI is currently in {room_name}.\n"
                f"Activity: {activity}. Expression: {expression}. Posture: {posture}.\n"
                f"Room purpose: {_room_purpose(room, state)}"
            )
            for key, _label_text in self.BAR_KEYS:
                bar = self.bars.get(key)
                if bar is not None:
                    bar.setValue(_percent(awareness.get(key)))
                    bar.setFormat(f"{_percent(awareness.get(key))}%")
            self.objects.setText(self._object_summary(state))
            self.recent.setText(_recent_lines(state.get("events") or [], limit=6))
            self.actions.setText(_recent_lines(state.get("actions") or [], limit=6))
            self.identity.setText(self._identity_summary(state))
        except Exception as exc:
            self.status.setText(f"Eli's World error: {type(exc).__name__}: {exc}")

