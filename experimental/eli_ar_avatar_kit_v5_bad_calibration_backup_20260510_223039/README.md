# ELI AR Avatar Kit v5 — Gaze Calibration + Desktop Avatar

This version fixes the compressed-corner movement problem by replacing simple eye-ratio mapping with:

- 25-point desktop calibration
- many samples per point
- feature standardization
- robust outlier rejection
- polynomial ridge regression
- output gain control
- velocity-aware smoothing
- transparent always-on-top PyQt6 avatar overlay
- JSON gaze/event bridge for later ELI integration
- a cleaner modern ELI avatar asset

No `/home/<user>` path is hard-coded. User files are written through XDG paths:

```text
~/.config/eli_ar_avatar/gaze_calibration_v2.json
~/.local/state/eli_ar_avatar/latest_gaze.json
~/.local/state/eli_ar_avatar/gaze_events.jsonl
~/.local/state/eli_ar_avatar/latest_gaze_crop.png
```

## Install

```bash
cd /path/to/eli_ar_avatar_kit
chmod +x install_eli_ar_avatar.sh scripts/*.py
./install_eli_ar_avatar.sh
source .venv/bin/activate
```

Optional but strongly recommended for real eye/iris tracking:

```bash
python -m pip install -r requirements_optional_mediapipe.txt
```

If MediaPipe fails on Python 3.12, use a Python 3.11 venv for this kit. The scripts still run with OpenCV fallback, but fallback tracking is much less accurate.

## Generate modern avatar

```bash
python scripts/eli_avatar_generator_modern.py --out assets/eli_avatar_modern.png --size 1024 --text ELI
```

## Recalibrate properly

Use 25 points. Do not use the old calibration file.

```bash
rm -f ~/.config/eli_ar_avatar/gaze_calibration_v2.json
python scripts/eli_gaze_calibrate_plus.py --camera auto --points 25 --samples-per-point 90 --gain 1.18
```

During calibration:

- keep your head mostly still
- move your eyes, not your whole head
- keep your face evenly lit
- put the webcam above/near the monitor centre
- look directly at each dot until it moves

## Test range before using overlay

```bash
python scripts/eli_gaze_range_test.py --camera auto
```

Look at each screen corner. The trace should cover most of the preview rectangle. If it still only covers a small area:

```bash
python scripts/eli_gaze_range_test.py --camera auto --gain 1.35
```

Then recalibrate with more samples:

```bash
python scripts/eli_gaze_calibrate_plus.py --camera auto --points 25 --samples-per-point 130 --gain 1.25
```

## Run desktop gaze avatar

```bash
python scripts/eli_gaze_desktop_avatar_plus.py \
  --camera auto \
  --asset assets/eli_avatar_modern.png \
  --avatar-size 168 \
  --save-target-crop \
  --debug
```

The avatar is click-through by default so it does not block your desktop. Use `--interactive` only if you want it to receive mouse events.

## Run webcam avatar mode

```bash
python scripts/eli_gaze_webcam_avatar_plus.py --camera auto --asset assets/eli_avatar_modern.png --anchor face --debug
```

or gaze-anchored inside the webcam preview:

```bash
python scripts/eli_gaze_webcam_avatar_plus.py --camera auto --asset assets/eli_avatar_modern.png --anchor gaze --debug
```

## ELI integration bridge

The live gaze state is written to:

```text
~/.local/state/eli_ar_avatar/latest_gaze.json
```

Stable gaze/dwell events are appended to:

```text
~/.local/state/eli_ar_avatar/gaze_events.jsonl
```

Example dwell event:

```json
{
  "event": "gaze_dwell_target",
  "ts": 1770000000.0,
  "screen_x": 802.0,
  "screen_y": 420.0,
  "stable_x": 798.0,
  "stable_y": 418.0,
  "confidence": 0.86,
  "target_crop": "/home/user/.local/state/eli_ar_avatar/latest_gaze_crop.png"
}
```

ELI can later consume this through a desktop perception plugin: read the dwell event, inspect the crop/window/icon under the coordinates, and route the result into the assistant chat or executor.

## Key fix vs v4

If v4 only moved a few centimetres, the gaze feature range was being used directly or mapped with an underfit transform. v5 learns the screen mapping from many observed eye/face samples and expands/clamps the output through a calibrated model, not a tiny raw ratio.
