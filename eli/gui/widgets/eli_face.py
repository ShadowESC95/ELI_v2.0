"""ELI's animated face — a procedural 2D face that shows the tone_adaptor's emotion.

Not a photoreal avatar: a clean, stylised face (eyes, brows, mouth, pupils) drawn
with QPainter. Every expression from the emotion palette maps to a small parameter
set (brow angle/height, eye openness, mouth curve/openness, pupil offset); the
widget eases toward the target each frame and blinks on its own, so the face feels
alive and reacts as ELI's expressed tone changes.

Driven live: a timer polls ``tone_adaptor.expression()`` and morphs to match. Drop
it anywhere (the world panel embeds it); ``set_expression("grinning")`` also drives
it directly. Pure Qt primitives (no QPainterPath), so it works on every binding.
"""
from __future__ import annotations

import logging
import math
import random

from eli.gui.qt_compat import (
    Qt, QTimer, QWidget, QPainter, QPen, QBrush, QColor,
)

log = logging.getLogger(__name__)

# Expression → face parameters. All in [-1, 1] unless noted:
#   brow   brow vertical (−down/angry … +raised/surprised)
#   slant  inner-brow slant (−angry frown … +worried)
#   eye    eye openness (0 shut … 1 wide)
#   curve  mouth curve (−frown … +smile)
#   open   mouth openness (0 closed … 1 agape)
#   pupil  vertical pupil offset (−up … +down)
_FACES = {
    "neutral":   {"brow": 0.0,  "slant": 0.0,  "eye": 0.8, "curve": 0.05, "open": 0.0,  "pupil": 0.0},
    "smiling":   {"brow": 0.15, "slant": 0.15, "eye": 0.8, "curve": 0.7,  "open": 0.0,  "pupil": 0.0},
    "grinning":  {"brow": 0.25, "slant": 0.2,  "eye": 0.75,"curve": 0.95, "open": 0.0,  "pupil": 0.0},
    "beaming":   {"brow": 0.3,  "slant": 0.25, "eye": 0.7, "curve": 1.0,  "open": 0.2,  "pupil": 0.0},
    "ecstatic":  {"brow": 0.5,  "slant": 0.3,  "eye": 0.95,"curve": 1.0,  "open": 0.45, "pupil": -0.15},
    "smirking":  {"brow": 0.1,  "slant": -0.1, "eye": 0.7, "curve": 0.4,  "open": 0.0,  "pupil": 0.3},
    "curious":   {"brow": 0.5,  "slant": 0.2,  "eye": 1.0, "curve": 0.2,  "open": 0.1,  "pupil": -0.1},
    "focused":   {"brow": -0.2, "slant": 0.0,  "eye": 0.6, "curve": 0.0,  "open": 0.0,  "pupil": 0.0},
    "serene":    {"brow": 0.1,  "slant": 0.1,  "eye": 0.55,"curve": 0.35, "open": 0.0,  "pupil": 0.1},
    "kind":      {"brow": 0.15, "slant": 0.15, "eye": 0.7, "curve": 0.45, "open": 0.05, "pupil": 0.1},
    "gentle":    {"brow": 0.1,  "slant": 0.2,  "eye": 0.6, "curve": 0.3,  "open": 0.0,  "pupil": 0.1},
    "flat":      {"brow": -0.05,"slant": 0.0,  "eye": 0.55,"curve": -0.05,"open": 0.0,  "pupil": 0.0},
    "downcast":  {"brow": -0.1, "slant": 0.3,  "eye": 0.45,"curve": -0.5, "open": 0.0,  "pupil": 0.4},
    "puzzled":   {"brow": 0.3,  "slant": -0.3, "eye": 0.8, "curve": -0.15,"open": 0.1,  "pupil": 0.2},
    "angry":     {"brow": -0.4, "slant": -0.6, "eye": 0.7, "curve": -0.5, "open": 0.1,  "pupil": 0.0},
    "frowning":  {"brow": -0.2, "slant": -0.3, "eye": 0.7, "curve": -0.4, "open": 0.0,  "pupil": 0.0},
    "confident": {"brow": 0.0,  "slant": -0.05,"eye": 0.75,"curve": 0.4,  "open": 0.05, "pupil": 0.2},
    "manic":     {"brow": 0.6,  "slant": 0.0,  "eye": 1.0, "curve": 0.9,  "open": 0.4,  "pupil": -0.3},
    "intense":   {"brow": -0.3, "slant": -0.1, "eye": 0.65,"curve": -0.1, "open": 0.0,  "pupil": 0.0},
    # world-view expressions (persona_mapper) reuse the closest face
    "concerned": {"brow": 0.2,  "slant": 0.3,  "eye": 0.8, "curve": -0.3, "open": 0.05, "pupil": 0.2},
    "cautious":  {"brow": 0.1,  "slant": 0.1,  "eye": 0.7, "curve": -0.1, "open": 0.0,  "pupil": 0.2},
    "reflective":{"brow": 0.15, "slant": 0.1,  "eye": 0.6, "curve": 0.05, "open": 0.0,  "pupil": -0.2},
}


def face_params(expression: str) -> dict:
    """Public: the parameter set for an expression (falls back to neutral)."""
    return dict(_FACES.get(str(expression or "").lower(), _FACES["neutral"]))


class EliFaceWidget(QWidget):
    """A live, animated face for ELI's current expressed emotion."""

    def __init__(self, parent=None, *, poll_tone: bool = True, size: int = 160):
        super().__init__(parent)
        self.setMinimumSize(size, size)
        self._target = face_params("neutral")
        self._cur = dict(self._target)
        self._expression = "neutral"
        self._blink = 1.0            # 1 = open, dips to 0 on a blink
        self._blink_phase = 0.0
        self._next_blink = random.uniform(2.0, 5.0)
        self._t = 0.0
        self._skin = QColor("#f4f7cf")
        self._ink = QColor("#2d3220")

        self._timer = QTimer(self)
        self._timer.setInterval(50)   # 20 fps — cheap, smooth enough
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._poll = poll_tone
        if poll_tone:
            self._tone_timer = QTimer(self)
            self._tone_timer.setInterval(700)
            self._tone_timer.timeout.connect(self._poll_tone)
            self._tone_timer.start()

    # ── control ───────────────────────────────────────────────────────────────
    def set_expression(self, expression: str) -> None:
        expr = str(expression or "neutral").lower()
        if expr == self._expression:
            return
        self._expression = expr
        self._target = face_params(expr)

    def current_expression(self) -> str:
        return self._expression

    def _poll_tone(self) -> None:
        try:
            from eli.cognition import tone_adaptor
            self.set_expression(tone_adaptor.expression())
        except Exception:
            log.debug("eli_face: tone poll failed", exc_info=True)

    # ── animation ─────────────────────────────────────────────────────────────
    def _tick(self) -> None:
        self._t += 0.05
        # Ease current params toward target (smooth morph between expressions).
        for k, tv in self._target.items():
            self._cur[k] += (tv - self._cur[k]) * 0.18
        # Blink scheduling.
        if self._blink_phase > 0:
            self._blink_phase -= 0.16
            self._blink = abs(math.cos(max(0.0, self._blink_phase) * math.pi))
            if self._blink_phase <= 0:
                self._blink, self._blink_phase = 1.0, 0.0
        elif self._t >= self._next_blink:
            self._blink_phase = 1.0
            self._next_blink = self._t + random.uniform(2.5, 6.0)
        self.update()

    # ── painting ──────────────────────────────────────────────────────────────
    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt override)
        try:
            self._paint()
        except Exception:
            log.debug("eli_face: paint failed", exc_info=True)

    def _paint(self) -> None:
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        except Exception:
            log.debug("eli_face: antialias hint unavailable", exc_info=True)
        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0
        r = min(w, h) * 0.42
        c = self._cur

        # Head.
        p.setPen(QPen(self._ink, max(2.0, r * 0.03)))
        p.setBrush(QBrush(self._skin))
        p.drawEllipse(int(cx - r), int(cy - r), int(2 * r), int(2 * r))

        eye_dx = r * 0.42
        eye_y = cy - r * 0.12
        eye_w = r * 0.34
        eye_h = r * 0.34 * max(0.08, c["eye"] * self._blink)
        for sign in (-1, 1):
            ex = cx + sign * eye_dx
            # Eye white.
            p.setBrush(QBrush(QColor("#ffffff")))
            p.setPen(QPen(self._ink, max(1.5, r * 0.02)))
            p.drawEllipse(int(ex - eye_w / 2), int(eye_y - eye_h / 2), int(eye_w), int(eye_h))
            # Pupil (only when the eye is meaningfully open).
            if c["eye"] * self._blink > 0.25:
                pr = eye_w * 0.34
                px = ex - pr / 2
                py = eye_y - pr / 2 + c["pupil"] * eye_h * 0.35
                p.setBrush(QBrush(self._ink))
                p.setPen(QPen(self._ink, 1))
                p.drawEllipse(int(px), int(py), int(pr), int(pr))

        # Brows — a line per side. `brow` raises/lowers both; `slant` tilts the inner
        # end (+ = inner up = worried ^, − = inner down = angry V).
        brow_y = eye_y - r * 0.42 - c["brow"] * r * 0.12
        brow_len = r * 0.42
        p.setPen(QPen(self._ink, max(2.5, r * 0.055)))
        for sign in (-1, 1):
            bx = cx + sign * eye_dx
            inner_x = bx - sign * (brow_len / 2)   # toward the centre of the face
            outer_x = bx + sign * (brow_len / 2)   # toward the side
            inner_y = brow_y - c["slant"] * r * 0.16
            p.drawLine(int(inner_x), int(inner_y), int(outer_x), int(brow_y))

        # Mouth — an arc; curve sets the smile/frown, open sets height.
        mouth_w = r * 0.9
        mouth_h = r * (0.15 + 0.6 * c["open"]) + abs(c["curve"]) * r * 0.35
        mx = cx - mouth_w / 2
        my = cy + r * 0.28
        p.setPen(QPen(self._ink, max(2.0, r * 0.05)))
        if c["open"] > 0.18:
            p.setBrush(QBrush(QColor("#7a2f36")))
            p.drawChord(int(mx), int(my - mouth_h / 2), int(mouth_w), int(mouth_h),
                        0 if c["curve"] >= 0 else 180 * 16, 180 * 16 if c["curve"] >= 0 else -180 * 16)
        else:
            # Closed mouth: an arc bowed up (smile) or down (frown).
            span = int(160 * 16)
            if c["curve"] >= 0:
                p.drawArc(int(mx), int(my - mouth_h), int(mouth_w), int(mouth_h * 2),
                          int(200 * 16), span)
            else:
                p.drawArc(int(mx), int(my), int(mouth_w), int(mouth_h * 2),
                          int(20 * 16), span)
        p.end()
