#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import cv2
import numpy as np

# Allow running from scripts/ without installing package.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eli_gaze_core.paths import default_calibration_path, user_state_dir
from eli_gaze_core.face_gaze import FaceGazeExtractor, open_camera
from eli_gaze_core.calibration import fit_calibration


def get_screen_size():
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        w = root.winfo_screenwidth()
        h = root.winfo_screenheight()
        root.destroy()
        return int(w), int(h)
    except Exception:
        return 1920, 1080


def calibration_points(width: int, height: int, mode: str):
    margin_x = int(width * 0.08)
    margin_y = int(height * 0.10)
    if mode == "9":
        xs = [margin_x, width // 2, width - margin_x]
        ys = [margin_y, height // 2, height - margin_y]
    elif mode == "16":
        xs = np.linspace(margin_x, width - margin_x, 4).astype(int).tolist()
        ys = np.linspace(margin_y, height - margin_y, 4).astype(int).tolist()
    elif mode == "25":
        xs = np.linspace(margin_x, width - margin_x, 5).astype(int).tolist()
        ys = np.linspace(margin_y, height - margin_y, 5).astype(int).tolist()
    else:
        raise ValueError("points must be 9, 16, or 25")
    pts = [(x, y) for y in ys for x in xs]
    # Centre first improves user orientation; then sweep outer/full grid.
    centre = (width // 2, height // 2)
    pts = [centre] + [p for p in pts if p != centre]
    return pts


def draw_target(canvas, x, y, radius, phase, label, stats=""):
    h, w = canvas.shape[:2]
    canvas[:] = (8, 10, 14)
    # subtle grid for spatial reference
    for gx in range(0, w, max(80, w // 16)):
        cv2.line(canvas, (gx, 0), (gx, h), (24, 30, 40), 1)
    for gy in range(0, h, max(80, h // 10)):
        cv2.line(canvas, (0, gy), (w, gy), (24, 30, 40), 1)
    pulse = int(radius + 8 * (0.5 + 0.5 * math.sin(phase * 8)))
    cv2.circle(canvas, (x, y), pulse, (40, 120, 170), 2, cv2.LINE_AA)
    cv2.circle(canvas, (x, y), radius, (145, 235, 255), -1, cv2.LINE_AA)
    cv2.circle(canvas, (x, y), max(3, radius//4), (5, 15, 25), -1, cv2.LINE_AA)
    cv2.putText(canvas, label, (30, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (210, 230, 245), 2, cv2.LINE_AA)
    cv2.putText(canvas, "Keep your head mostly still; move only your eyes to the dot. Press ESC to abort.", (30, h - 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (150, 170, 190), 2, cv2.LINE_AA)
    if stats:
        cv2.putText(canvas, stats, (30, 82), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (140, 215, 255), 2, cv2.LINE_AA)


def main():
    ap = argparse.ArgumentParser(description="High-range gaze calibration for ELI desktop avatar.")
    ap.add_argument("--camera", default="auto")
    ap.add_argument("--out", default=str(default_calibration_path()))
    ap.add_argument("--points", choices=["9", "16", "25"], default="25", help="25 is recommended for desktop control.")
    ap.add_argument("--samples-per-point", type=int, default=90)
    ap.add_argument("--warmup-ms", type=int, default=800)
    ap.add_argument("--degree", type=int, choices=[1, 2, 3], default=2)
    ap.add_argument("--ridge", type=float, default=2e-3)
    ap.add_argument("--gain", type=float, default=1.18, help="Post-calibration expansion. Use 1.0-1.35. Fixes compressed movement.")
    ap.add_argument("--screen-width", type=int, default=0)
    ap.add_argument("--screen-height", type=int, default=0)
    ap.add_argument("--no-mirror", action="store_true")
    args = ap.parse_args()

    sw, sh = get_screen_size()
    if args.screen_width > 0:
        sw = args.screen_width
    if args.screen_height > 0:
        sh = args.screen_height

    cap, cam_idx = open_camera(args.camera, width=1280, height=720)
    extractor = FaceGazeExtractor(mirror=not args.no_mirror, prefer_mediapipe=True)

    print(f"[+] Camera: {cam_idx}")
    print(f"[+] Extractor: {extractor.method}")
    if extractor.method != "mediapipe_facemesh_iris":
        print("[!] MediaPipe iris tracking is not active. Install with: python -m pip install mediapipe")
        print("[!] Haar fallback is coarse and will not be accurate enough for desktop eye control.")
    print(f"[+] Screen: {sw}x{sh}")

    window = "ELI gaze calibration v2"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.setWindowProperty(window, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

    pts = calibration_points(sw, sh, args.points)
    samples = []
    frame_canvas = np.zeros((sh, sw, 3), dtype=np.uint8)

    try:
        for pid, (tx, ty) in enumerate(pts):
            # Warmup/fixation phase
            start = time.time()
            while (time.time() - start) * 1000 < args.warmup_ms:
                ok, frame = cap.read()
                if not ok:
                    continue
                sample = extractor.extract(frame)
                conf = 0.0 if sample is None else sample.confidence
                elapsed = (time.time() - start) * 1000
                remain = max(0, args.warmup_ms - elapsed)
                draw_target(
                    frame_canvas, tx, ty, max(16, sw // 95), elapsed / 1000,
                    f"Point {pid+1}/{len(pts)}: fixate dot - starting in {remain/1000:.1f}s",
                    f"tracker={extractor.method} confidence={conf:.2f} collected={len(samples)}",
                )
                cv2.imshow(window, frame_canvas)
                key = cv2.waitKey(1) & 0xFF
                if key == 27:
                    raise KeyboardInterrupt

            accepted = 0
            attempts = 0
            while accepted < args.samples_per_point and attempts < args.samples_per_point * 4:
                attempts += 1
                ok, frame = cap.read()
                if not ok:
                    continue
                sample = extractor.extract(frame)
                if sample is not None and sample.confidence >= 0.35:
                    samples.append({
                        "point_id": pid,
                        "target_x": float(tx),
                        "target_y": float(ty),
                        "features": sample.features.tolist(),
                        "confidence": float(sample.confidence),
                        "method": sample.method,
                        "timestamp": sample.timestamp,
                    })
                    accepted += 1
                draw_target(
                    frame_canvas, tx, ty, max(16, sw // 95), attempts / 12,
                    f"Point {pid+1}/{len(pts)}: collecting {accepted}/{args.samples_per_point}",
                    f"tracker={extractor.method} accepted={accepted} attempts={attempts} total={len(samples)}",
                )
                cv2.imshow(window, frame_canvas)
                key = cv2.waitKey(1) & 0xFF
                if key == 27:
                    raise KeyboardInterrupt

            if accepted < max(12, args.samples_per_point // 4):
                print(f"[!] Point {pid+1} produced few usable samples: {accepted}. Lighting/face angle may be poor.")
    except KeyboardInterrupt:
        print("\n[!] Calibration aborted.")
        return 1
    finally:
        cap.release()
        cv2.destroyAllWindows()

    out = Path(args.out).expanduser()
    result = fit_calibration(
        samples,
        screen_width=sw,
        screen_height=sh,
        path=out,
        degree=args.degree,
        ridge=args.ridge,
        output_gain=args.gain,
    )
    summary = {
        "calibration_file": str(result.path),
        "screen": [sw, sh],
        "degree": result.degree,
        "samples": result.samples,
        "points": result.points,
        "mean_error_px": result.mean_error_px,
        "median_error_px": result.median_error_px,
        "p90_error_px": result.p90_error_px,
    }
    (user_state_dir() / "last_calibration_report.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("\n[+] Calibration saved:", result.path)
    print(json.dumps(summary, indent=2))
    if result.mean_error_px > max(160, sw * 0.08):
        print("[!] Calibration is weak. Re-run in better lighting with MediaPipe installed, use --points 25, and keep your head fixed.")
    else:
        print("[+] Calibration quality is usable. Run eli_gaze_desktop_avatar_plus.py next.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
