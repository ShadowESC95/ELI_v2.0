#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eli_gaze_core.paths import default_calibration_path, default_state_path, default_event_path, user_state_dir
from eli_gaze_core.face_gaze import FaceGazeExtractor, open_camera
from eli_gaze_core.calibration import GazeMapper, OneEuroLikeFilter

try:
    from PyQt6.QtCore import Qt, QTimer, QPoint
    from PyQt6.QtGui import QPainter, QPixmap, QColor, QPen, QFont
    from PyQt6.QtWidgets import QApplication, QWidget
except Exception as exc:
    raise SystemExit("PyQt6 is required. Install with: python -m pip install PyQt6\n" + str(exc))


class AvatarOverlay(QWidget):
    def __init__(self, asset: Path, size: int = 164, opacity: float = 0.94, click_through: bool = True):
        super().__init__()
        self.asset = asset
        self.avatar = QPixmap(str(asset))
        if self.avatar.isNull():
            raise RuntimeError(f"Could not load avatar image: {asset}")
        self.size_px = size
        self.opacity = opacity
        self.mode = "idle"
        self.confidence = 0.0
        self.text = "ELI"
        self.resize(size, size)
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        if click_through:
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.show()

    def set_state(self, mode: str, confidence: float, text: str = ""):
        self.mode = mode
        self.confidence = max(0.0, min(1.0, confidence))
        self.text = text[:40] if text else "ELI"
        self.update()

    def set_center(self, x: float, y: float):
        self.move(int(x - self.size_px / 2), int(y - self.size_px / 2))

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setOpacity(self.opacity)

        # State ring: modern OS-assistant feel, not decorative glitter.
        if self.mode == "listening":
            ring = QColor(95, 215, 255, 210)
        elif self.mode == "thinking":
            ring = QColor(160, 135, 255, 210)
        elif self.mode == "speaking":
            ring = QColor(120, 255, 190, 210)
        elif self.mode == "alert":
            ring = QColor(255, 90, 90, 225)
        else:
            ring = QColor(110, 175, 230, 155)

        pen = QPen(ring, max(2, self.size_px // 38))
        painter.setPen(pen)
        inset = max(5, self.size_px // 26)
        painter.drawEllipse(inset, inset, self.size_px - inset * 2, self.size_px - inset * 2)

        # Confidence arc approximation.
        painter.setPen(QPen(QColor(215, 245, 255, 210), max(2, self.size_px // 55)))
        span = int(360 * 16 * self.confidence)
        painter.drawArc(inset + 7, inset + 7, self.size_px - (inset + 7) * 2, self.size_px - (inset + 7) * 2, 90 * 16, -span)

        painter.drawPixmap(0, 0, self.size_px, self.size_px, self.avatar)

        # Small status label.
        painter.setOpacity(min(1.0, self.opacity + 0.05))
        painter.setPen(QColor(210, 235, 250, 210))
        font = QFont("DejaVu Sans", max(8, self.size_px // 16))
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(0, self.size_px - max(20, self.size_px // 9), self.size_px, max(18, self.size_px // 8), Qt.AlignmentFlag.AlignCenter, self.text)


def read_runtime_state(path: Path | None):
    if not path or not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_crop(x: int, y: int, radius: int = 96) -> str | None:
    try:
        import mss  # type: ignore
        from PIL import Image
        with mss.mss() as sct:
            mon = sct.monitors[0]
            left = max(mon["left"], x - radius)
            top = max(mon["top"], y - radius)
            box = {"left": left, "top": top, "width": radius * 2, "height": radius * 2}
            img = sct.grab(box)
            out = user_state_dir() / "latest_gaze_crop.png"
            Image.frombytes("RGB", img.size, img.rgb).save(out)
            return str(out)
    except Exception:
        return None


class GazeAvatarApp:
    def __init__(self, args):
        self.args = args
        self.cap, self.camera_idx = open_camera(args.camera, width=args.cam_width, height=args.cam_height)
        self.extractor = FaceGazeExtractor(mirror=not args.no_mirror, prefer_mediapipe=True)
        self.mapper = GazeMapper(Path(args.calibration).expanduser())
        self.filter = OneEuroLikeFilter(alpha_slow=args.smooth_slow, alpha_fast=args.smooth_fast, velocity_scale=args.velocity_scale)
        self.overlay = AvatarOverlay(Path(args.asset).expanduser(), size=args.avatar_size, opacity=args.opacity, click_through=not args.interactive)
        self.state_path = Path(args.state).expanduser() if args.state else None
        self.latest_path = Path(args.latest).expanduser()
        self.event_path = Path(args.events).expanduser()
        self.event_path.parent.mkdir(parents=True, exist_ok=True)
        self.last_stable = None
        self.stable_since = time.time()
        self.last_event_t = 0.0
        self.last_xy = (self.mapper.screen_width * 0.5, self.mapper.screen_height * 0.5)
        self.frame_count = 0
        self.last_print = 0.0

        self.timer = QTimer()
        self.timer.timeout.connect(self.tick)
        self.timer.start(max(1, int(1000 / args.fps)))

    def tick(self):
        ok, frame = self.cap.read()
        if not ok or frame is None:
            return
        sample = self.extractor.extract(frame)
        if sample is None:
            self.overlay.set_state("alert", 0.0, "no face")
            return
        raw_x, raw_y = self.mapper.predict(sample.features, gain=self.args.gain)
        x, y = self.filter.update(raw_x, raw_y, confidence=sample.confidence)

        # Optional deadzone prevents avatar micro-jitter while eyes are steady.
        lx, ly = self.last_xy
        if abs(x - lx) < self.args.deadzone and abs(y - ly) < self.args.deadzone:
            x, y = lx, ly
        self.last_xy = (x, y)
        self.overlay.set_center(x, y)

        runtime = read_runtime_state(self.state_path)
        mode = runtime.get("mode") or "listening"
        text = runtime.get("text") or f"{int(sample.confidence * 100)}%"
        self.overlay.set_state(str(mode), sample.confidence, str(text))

        payload = {
            "ts": time.time(),
            "camera": self.camera_idx,
            "tracker": sample.method,
            "screen_x": float(x),
            "screen_y": float(y),
            "raw_x": float(raw_x),
            "raw_y": float(raw_y),
            "confidence": float(sample.confidence),
            "face_box": list(sample.face_box),
        }
        self.latest_path.parent.mkdir(parents=True, exist_ok=True)
        self.latest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        self._dwell(x, y, sample.confidence)
        self.frame_count += 1
        if self.args.debug and time.time() - self.last_print > 0.75:
            print(f"gaze=({x:.0f},{y:.0f}) raw=({raw_x:.0f},{raw_y:.0f}) conf={sample.confidence:.2f} tracker={sample.method}")
            self.last_print = time.time()

    def _dwell(self, x: float, y: float, confidence: float):
        now = time.time()
        p = np.array([x, y], dtype=float)
        if self.last_stable is None:
            self.last_stable = p
            self.stable_since = now
            return
        dist = float(np.linalg.norm(p - self.last_stable))
        if dist <= self.args.dwell_radius:
            if (now - self.stable_since) * 1000 >= self.args.dwell_ms and now - self.last_event_t >= self.args.event_cooldown:
                crop = save_crop(int(x), int(y), radius=self.args.crop_radius) if self.args.save_target_crop else None
                event = {
                    "event": "gaze_dwell_target",
                    "ts": now,
                    "screen_x": float(x),
                    "screen_y": float(y),
                    "stable_x": float(self.last_stable[0]),
                    "stable_y": float(self.last_stable[1]),
                    "confidence": float(confidence),
                    "target_crop": crop,
                }
                with self.event_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(event) + "\n")
                self.last_event_t = now
        else:
            self.last_stable = p
            self.stable_since = now

    def close(self):
        self.cap.release()


def main():
    ap = argparse.ArgumentParser(description="Desktop gaze-controlled ELI avatar overlay v2.")
    ap.add_argument("--camera", default="auto")
    ap.add_argument("--asset", default=str(ROOT / "assets" / "eli_avatar_modern.png"))
    ap.add_argument("--calibration", default=str(default_calibration_path()))
    ap.add_argument("--state", default="", help="Optional JSON file written by ELI runtime: mode/text/confidence.")
    ap.add_argument("--latest", default=str(default_state_path()))
    ap.add_argument("--events", default=str(default_event_path()))
    ap.add_argument("--avatar-size", type=int, default=168)
    ap.add_argument("--opacity", type=float, default=0.94)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--cam-width", type=int, default=1280)
    ap.add_argument("--cam-height", type=int, default=720)
    ap.add_argument("--gain", type=float, default=None, help="Override model output gain. Try 1.05-1.35 if movement is compressed.")
    ap.add_argument("--deadzone", type=float, default=8.0)
    ap.add_argument("--smooth-slow", type=float, default=0.18)
    ap.add_argument("--smooth-fast", type=float, default=0.58)
    ap.add_argument("--velocity-scale", type=float, default=950.0)
    ap.add_argument("--dwell-ms", type=int, default=700)
    ap.add_argument("--dwell-radius", type=float, default=72.0)
    ap.add_argument("--event-cooldown", type=float, default=1.8)
    ap.add_argument("--save-target-crop", action="store_true")
    ap.add_argument("--crop-radius", type=int, default=110)
    ap.add_argument("--interactive", action="store_true", help="Let avatar receive mouse events. Default is click-through.")
    ap.add_argument("--no-mirror", action="store_true")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    cal = Path(args.calibration).expanduser()
    if not cal.exists():
        raise SystemExit(f"Calibration missing: {cal}\nRun: python scripts/eli_gaze_calibrate_plus.py --points 25")

    app = QApplication(sys.argv)
    ctl = GazeAvatarApp(args)
    try:
        code = app.exec()
    finally:
        ctl.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
