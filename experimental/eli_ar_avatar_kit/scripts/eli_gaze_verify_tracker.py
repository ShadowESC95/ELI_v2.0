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

from eli_gaze_core.face_gaze import FaceGazeExtractor, open_camera
from eli_gaze_core.paths import user_state_dir


def draw_sample(frame, sample, extractor):
    h, w = frame.shape[:2]
    if sample is None:
        cv2.putText(frame, "NO FACE / NO EYE LANDMARKS", (24, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (40, 80, 255), 2, cv2.LINE_AA)
        return frame
    x, y, fw, fh = sample.face_box
    cv2.rectangle(frame, (x, y), (x + fw, y + fh), (80, 210, 255), 2)
    le = tuple(map(int, sample.left_eye))
    re = tuple(map(int, sample.right_eye))
    cv2.circle(frame, le, 5, (80, 255, 180), -1, cv2.LINE_AA)
    cv2.circle(frame, re, 5, (80, 255, 180), -1, cv2.LINE_AA)
    f = sample.features
    msg = f"tracker={sample.method} conf={sample.confidence:.2f} le=({f[0]:.2f},{f[1]:.2f}) re=({f[2]:.2f},{f[3]:.2f})"
    cv2.putText(frame, msg, (24, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.67, (220, 240, 255), 2, cv2.LINE_AA)
    cv2.putText(frame, "Move eyes left/right/up/down. The le/re ratios should visibly change.", (24, h - 28), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (220, 240, 255), 2, cv2.LINE_AA)
    return frame


def main():
    ap = argparse.ArgumentParser(description="Verify MediaPipe iris tracking before calibration.")
    ap.add_argument("--camera", default="auto")
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--no-mirror", action="store_true")
    ap.add_argument("--cam-width", type=int, default=1280)
    ap.add_argument("--cam-height", type=int, default=720)
    args = ap.parse_args()

    cap, idx = open_camera(args.camera, width=args.cam_width, height=args.cam_height)
    extractor = FaceGazeExtractor(mirror=not args.no_mirror, prefer_mediapipe=True)
    print(f"[+] Camera: {idx}")
    print(f"[+] Extractor: {extractor.method}")
    if extractor.method != "mediapipe_facemesh_iris":
        print("[!] MediaPipe iris tracker is NOT active. Calibration will fail or be useless.")
        if getattr(extractor, "backend_error", ""):
            print(f"[!] MediaPipe error: {extractor.backend_error}")
        print("[!] Run: python -m pip install -r requirements_optional_mediapipe.txt")
        return 2

    win = "ELI gaze tracker verifier - press q/ESC to quit"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    start = time.time()
    usable = 0
    total = 0
    last = None
    feature_min = None
    feature_max = None

    while time.time() - start < args.seconds:
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        total += 1
        sample = extractor.extract(frame)
        if sample is not None and sample.confidence >= 0.50:
            usable += 1
            f = sample.features[:6].astype(float)
            feature_min = f.copy() if feature_min is None else np.minimum(feature_min, f)
            feature_max = f.copy() if feature_max is None else np.maximum(feature_max, f)
            last = {
                "method": sample.method,
                "confidence": sample.confidence,
                "features_head": sample.features[:8].tolist(),
                "face_box": list(sample.face_box),
            }
        shown = cv2.flip(frame, 1) if args.no_mirror else frame.copy()
        draw_sample(shown, sample, extractor)
        cv2.imshow(win, shown)
        key = cv2.waitKey(1) & 0xFF
        if key in (27, ord('q')):
            break

    cap.release()
    cv2.destroyAllWindows()

    report = {
        "camera": idx,
        "tracker": extractor.method,
        "frames": total,
        "usable_frames": usable,
        "usable_ratio": usable / max(total, 1),
        "last_sample": last,
    }
    if feature_min is not None and feature_max is not None:
        report["feature_range_first6"] = (feature_max - feature_min).tolist()
    out = user_state_dir() / "tracker_verification_report.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"[+] Report: {out}")
    if usable < 30:
        print("[!] Too few usable iris frames. Improve light, face camera directly, remove glare, or choose another camera.")
        return 3
    print("[+] Tracker is usable. Proceed to calibration.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
