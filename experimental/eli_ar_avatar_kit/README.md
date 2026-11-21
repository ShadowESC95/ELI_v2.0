# ELI AR Avatar Kit v5 — Gaze Calibration + Desktop Avatar

**Status: experimental.** This kit is a set of standalone scripts with their own virtual
environment. ELI does not install it or start its scripts, and by default reads none of the
files they write. The one piece ELI uses is `eli_gaze_core/`: ELI's gaze engine
(`eli/perception/gaze_engine.py`, behind the `GAZE_ENABLE` / `GAZE_DISABLE` /
`GAZE_CALIBRATE` / `GAZE_CLICK` / `GAZE_STATUS` actions and the desktop app's gaze
controls) imports it from this folder and runs it inside ELI's own process and
environment. That environment installs OpenCV but not MediaPipe, so ELI's engine tracks
with the OpenCV Haar fallback unless MediaPipe is installed there too. It reads its
calibration from `eli_ar_avatar/gaze_calibration_v2.json` in **ELI's config folder**
(`config/` in a source checkout) and writes `eli_ar_avatar/latest_gaze.json` in ELI's data
folder — not the `~/.config` / `~/.local/state` files below. To calibrate for ELI, pass
that path to the calibrator with `--out`; its default is the kit's own file.

## v5.2 critical dependency fix

MediaPipe 0.10.30+ removed the legacy `mp.solutions` API used by FaceMesh/iris tracking. This kit pins `mediapipe==0.10.21`, `numpy==1.26.4`, and `opencv-contrib-python==4.10.0.84` so desktop gaze calibration can use real iris landmarks instead of the useless Haar fallback.

Use:

```bash
./install_eli_ar_avatar.sh --recreate --with-mediapipe
source .venv/bin/activate
python scripts/eli_gaze_verify_tracker.py --camera auto
```

Expected verifier line:

```text
Extractor: mediapipe_facemesh_iris
```

Do not calibrate if it reports `opencv_haar_fallback`.


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

No `/home/<user>` path is hard-coded. User files are written through XDG paths
(`$XDG_CONFIG_HOME` / `$XDG_STATE_HOME`, defaulting to the ones shown):

```text
~/.config/eli_ar_avatar/gaze_calibration_v2.json
~/.local/state/eli_ar_avatar/latest_gaze.json
~/.local/state/eli_ar_avatar/gaze_events.jsonl
~/.local/state/eli_ar_avatar/latest_gaze_crop.png
~/.local/state/eli_ar_avatar/tracker_verification_report.json
~/.local/state/eli_ar_avatar/last_calibration_report.json
```

## Install

```bash
cd /path/to/eli_ar_avatar_kit
chmod +x install_eli_ar_avatar.sh scripts/*.py
./install_eli_ar_avatar.sh
source .venv/bin/activate
```

The installer builds `.venv` in the kit with `python3` and installs `requirements.txt`.
`--with-mediapipe` (or `--gaze`) adds MediaPipe, `--recreate` rebuilds the venv, and
`--system-deps` installs camera/X11/Python build packages with apt. The desktop overlay uses
PyQt6 (GPLv3), which goes into this venv only; ELI itself uses PySide6 and does not depend
on PyQt6.

Optional but strongly recommended for real eye/iris tracking:

```bash
python -m pip install -r requirements_optional_mediapipe.txt
```

If MediaPipe fails on Python 3.12, use a Python 3.11 venv for this kit. Without MediaPipe
the verifier stops and calibration refuses to run (unless you pass
`--allow-haar-fallback`), so the desktop avatar and the range test, which need a
calibration, have none; the face-anchored webcam avatar still runs on the OpenCV Haar
fallback, which is much less accurate.

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

For ELI's own gaze engine, write the calibration where ELI reads it (the `GAZE_CALIBRATE`
action prints that path), for example from a source checkout:

```bash
python scripts/eli_gaze_calibrate_plus.py --camera auto --points 25 \
  --out /path/to/ELI/config/eli_ar_avatar/gaze_calibration_v2.json
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

ELI does not read these files today. A desktop perception plugin could: read the dwell event, inspect the crop/window/icon under the coordinates, and route the result into the assistant chat or executor.

`--state <file>` lets the desktop avatar show a mode/text/confidence from a JSON file (`configs/runtime_state.example.json` shows the shape). ELI does not write one; the expression script below does.

## Facial expression cues

```bash
python scripts/eli_facial_expression_proactive.py --camera auto --debug
python scripts/eli_facial_expression_proactive.py --camera auto --debug --speak
python scripts/eli_facial_expression_proactive.py --camera auto --no-window --publish-events
```

A local webcam cue detector: it emits cautious labels (`possible_smile`, `possible_frustration_or_tension`, `possible_fatigue`, `focused_attention`, `speaking_or_mouth_open`, `neutral_or_uncertain`), never a diagnosis of emotion, and writes `latest_expression_state.json`, `runtime_state.json`, `facial_expression_events.jsonl` and `avatar_events.sqlite3` to `~/.local/state/eli_ar_avatar/`. `--speak` voices its prompts with pyttsx3. ELI does not run it or read its output.

## Key fix vs v4

If v4 only moved a few centimetres, the gaze feature range was being used directly or mapped with an underfit transform. v5 learns the screen mapping from many observed eye/face samples and expands/clamps the output through a calibrated model, not a tiny raw ratio.

## v5.1 critical gaze fix

Desktop gaze control now refuses to calibrate using the OpenCV Haar fallback unless you explicitly pass `--allow-haar-fallback`. Haar detection can find a face box, but it does not provide stable iris landmarks, so it produced zero usable calibration samples in testing.

Use this sequence:

```bash
./install_eli_ar_avatar.sh --with-mediapipe
source .venv/bin/activate
python scripts/eli_gaze_verify_tracker.py --camera auto
rm -f ~/.config/eli_ar_avatar/gaze_calibration_v2.json
python scripts/eli_gaze_calibrate_plus.py --camera auto --points 25 --samples-per-point 90 --gain 1.18
python scripts/eli_gaze_range_test.py --camera auto
python scripts/eli_gaze_desktop_avatar_plus.py --camera auto --asset assets/eli_avatar_modern.png --debug --save-target-crop
```

If `eli_gaze_verify_tracker.py` does not report `mediapipe_facemesh_iris` (its `Extractor:` line, and `tracker=` in its window), calibration is not ready. Fix MediaPipe first rather than recalibrating.
