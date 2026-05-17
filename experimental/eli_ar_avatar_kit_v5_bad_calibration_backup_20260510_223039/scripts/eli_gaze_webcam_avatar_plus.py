#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eli_gaze_core.paths import default_calibration_path
from eli_gaze_core.face_gaze import FaceGazeExtractor, open_camera
from eli_gaze_core.calibration import GazeMapper, OneEuroLikeFilter


def overlay_png(frame, png, x, y, scale=1.0, alpha=0.92):
    h, w = frame.shape[:2]
    ph, pw = png.shape[:2]
    nw, nh = max(8, int(pw * scale)), max(8, int(ph * scale))
    icon = cv2.resize(png, (nw, nh), interpolation=cv2.INTER_AREA)
    x0, y0 = int(x - nw / 2), int(y - nh / 2)
    x1, y1 = x0 + nw, y0 + nh
    ix0, iy0 = max(0, -x0), max(0, -y0)
    ix1, iy1 = nw - max(0, x1 - w), nh - max(0, y1 - h)
    fx0, fy0 = max(0, x0), max(0, y0)
    fx1, fy1 = min(w, x1), min(h, y1)
    if fx1 <= fx0 or fy1 <= fy0:
        return frame
    roi = frame[fy0:fy1, fx0:fx1]
    part = icon[iy0:iy1, ix0:ix1]
    if part.shape[2] == 4:
        a = (part[:, :, 3:4].astype(np.float32) / 255.0) * alpha
        rgb = part[:, :, :3].astype(np.float32)
        roi[:] = (roi.astype(np.float32) * (1 - a) + rgb * a).astype(np.uint8)
    else:
        cv2.addWeighted(part, alpha, roi, 1-alpha, 0, roi)
    return frame


def main():
    ap = argparse.ArgumentParser(description="Webcam AR mode with modern ELI avatar and optional gaze anchoring.")
    ap.add_argument("--camera", default="auto")
    ap.add_argument("--asset", default=str(ROOT / "assets" / "eli_avatar_modern.png"))
    ap.add_argument("--calibration", default=str(default_calibration_path()))
    ap.add_argument("--anchor", choices=["face", "gaze", "centre"], default="face")
    ap.add_argument("--scale", type=float, default=0.18)
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--no-mirror", action="store_true")
    args = ap.parse_args()

    cap, idx = open_camera(args.camera, width=1280, height=720)
    extractor = FaceGazeExtractor(mirror=not args.no_mirror, prefer_mediapipe=True)
    mapper = None
    if args.anchor == "gaze" and Path(args.calibration).expanduser().exists():
        mapper = GazeMapper(Path(args.calibration).expanduser())
    elif args.anchor == "gaze":
        print("[!] No calibration found; falling back to face anchor.")
        args.anchor = "face"
    filt = OneEuroLikeFilter()

    avatar = cv2.imread(str(Path(args.asset).expanduser()), cv2.IMREAD_UNCHANGED)
    if avatar is None:
        raise SystemExit(f"Could not load avatar: {args.asset}")

    print(f"[+] camera={idx} tracker={extractor.method} anchor={args.anchor}")
    win = "ELI webcam avatar plus"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    while True:
        ok, frame = cap.read()
        if not ok:
            continue
        if not args.no_mirror:
            show = cv2.flip(frame, 1)
            proc = frame
        else:
            show = frame.copy()
            proc = frame
        sample = extractor.extract(frame)
        h, w = show.shape[:2]
        if args.anchor == "centre" or sample is None:
            x, y = w * 0.5, h * 0.5
            conf = 0.0 if sample is None else sample.confidence
        elif args.anchor == "face":
            bx, by, bw, bh = sample.face_box
            x, y = bx + bw * 0.5, max(60, by - bh * 0.16)
            conf = sample.confidence
        else:
            sx, sy = mapper.predict(sample.features)
            x = (sx / mapper.screen_width) * w
            y = (sy / mapper.screen_height) * h
            conf = sample.confidence
        x, y = filt.update(x, y, conf)
        overlay_png(show, avatar, x, y, scale=args.scale, alpha=0.94)
        if args.debug and sample is not None:
            cv2.putText(show, f"{sample.method} conf={sample.confidence:.2f} anchor={args.anchor}", (24, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (210,235,255), 2, cv2.LINE_AA)
            lx, ly = map(int, sample.left_eye)
            rx, ry = map(int, sample.right_eye)
            cv2.circle(show, (lx, ly), 5, (80, 255, 255), -1)
            cv2.circle(show, (rx, ry), 5, (80, 255, 255), -1)
        cv2.imshow(win, show)
        key = cv2.waitKey(1) & 0xFF
        if key in (27, ord('q')):
            break
        if key == ord('+') or key == ord('='):
            args.scale *= 1.08
        if key == ord('-'):
            args.scale /= 1.08
    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
