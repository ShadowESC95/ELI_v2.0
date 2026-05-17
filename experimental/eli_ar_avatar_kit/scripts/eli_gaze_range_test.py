#!/usr/bin/env python3
from __future__ import annotations

import argparse, json, sys, time
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from eli_gaze_core.paths import default_calibration_path
from eli_gaze_core.face_gaze import FaceGazeExtractor, open_camera
from eli_gaze_core.calibration import GazeMapper, OneEuroLikeFilter


def main():
    ap = argparse.ArgumentParser(description="Check gaze range after calibration; adjust gain live with +/-.")
    ap.add_argument("--camera", default="auto")
    ap.add_argument("--calibration", default=str(default_calibration_path()))
    ap.add_argument("--gain", type=float, default=None)
    ap.add_argument("--no-mirror", action="store_true")
    args = ap.parse_args()
    cal = Path(args.calibration).expanduser()
    if not cal.exists():
        raise SystemExit(f"Missing calibration: {cal}")
    mapper = GazeMapper(cal)
    gain = mapper.output_gain if args.gain is None else args.gain
    cap, idx = open_camera(args.camera)
    extractor = FaceGazeExtractor(mirror=not args.no_mirror)
    filt = OneEuroLikeFilter(alpha_slow=0.15, alpha_fast=0.5)
    trail = []
    win = "ELI gaze range test"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    print("Look at each corner and centre. +/- changes gain. q quits.")
    while True:
        ok, frame = cap.read()
        if not ok: continue
        sample = extractor.extract(frame)
        canvas = frame.copy()
        if sample:
            x, y = mapper.predict(sample.features, gain=gain)
            x, y = filt.update(x, y, sample.confidence)
            trail.append((int(x), int(y)))
            trail[:] = trail[-150:]
        sw, sh = mapper.screen_width, mapper.screen_height
        # Draw screen-space preview scaled into webcam frame.
        h, w = canvas.shape[:2]
        margin = 18
        box_w, box_h = int(w * 0.42), int(h * 0.42)
        ox, oy = w - box_w - margin, margin
        cv2.rectangle(canvas, (ox, oy), (ox+box_w, oy+box_h), (80, 120, 150), 2)
        for tx, ty in [(0,0),(sw//2,0),(sw-1,0),(0,sh//2),(sw//2,sh//2),(sw-1,sh//2),(0,sh-1),(sw//2,sh-1),(sw-1,sh-1)]:
            px = ox + int(tx / sw * box_w)
            py = oy + int(ty / sh * box_h)
            cv2.circle(canvas, (px, py), 4, (120,220,255), -1)
        for px, py in trail:
            sx = ox + int(px / sw * box_w)
            sy = oy + int(py / sh * box_h)
            cv2.circle(canvas, (sx, sy), 2, (80,255,180), -1)
        txt = f"tracker={extractor.method} gain={gain:.2f} conf={(sample.confidence if sample else 0):.2f}"
        cv2.putText(canvas, txt, (22, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (210,235,255), 2, cv2.LINE_AA)
        cv2.putText(canvas, "If trace only covers a small area, recalibrate with --points 25 or increase gain to 1.25", (22, h-28), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (210,235,255), 2, cv2.LINE_AA)
        cv2.imshow(win, canvas)
        key = cv2.waitKey(1) & 0xFF
        if key in (27, ord('q')): break
        if key in (ord('+'), ord('=')): gain = min(1.8, gain + 0.04)
        if key == ord('-'): gain = max(0.65, gain - 0.04)
    cap.release(); cv2.destroyAllWindows()

if __name__ == '__main__':
    main()
