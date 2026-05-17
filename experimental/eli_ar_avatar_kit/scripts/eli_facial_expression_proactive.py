#!/usr/bin/env python3
"""
ELI Facial Expression + Proactive Cue Engine
============================================

Local-only webcam expression cue detector for ELI.

It detects visible facial-expression cues and emits cautious labels:
  possible_smile
  possible_frustration_or_tension
  possible_fatigue
  focused_attention
  speaking_or_mouth_open
  neutral_or_uncertain

It does NOT know or diagnose emotion. Prompts are phrased as uncertainty.

Outputs:
  ~/.local/state/eli_ar_avatar/latest_expression_state.json
  ~/.local/state/eli_ar_avatar/runtime_state.json
  ~/.local/state/eli_ar_avatar/facial_expression_events.jsonl
  ~/.local/state/eli_ar_avatar/avatar_events.sqlite3

Run:
  python scripts/eli_facial_expression_proactive.py --camera auto --debug
  python scripts/eli_facial_expression_proactive.py --camera auto --debug --speak
  python scripts/eli_facial_expression_proactive.py --camera auto --no-window --publish-events
"""

from __future__ import annotations

import argparse
import json
import math
import os
import queue
import sqlite3
import threading
import time
from collections import deque
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np


APP_NAME = "eli_ar_avatar"

L_EYE_OUTER, L_EYE_INNER, L_EYE_TOP, L_EYE_BOTTOM = 33, 133, 159, 145
R_EYE_OUTER, R_EYE_INNER, R_EYE_TOP, R_EYE_BOTTOM = 263, 362, 386, 374
L_BROW_INNER, L_BROW_OUTER = 105, 70
R_BROW_INNER, R_BROW_OUTER = 334, 300
MOUTH_LEFT, MOUTH_RIGHT, MOUTH_TOP, MOUTH_BOTTOM = 61, 291, 13, 14
NOSE_TIP, CHIN, FOREHEAD, LEFT_FACE, RIGHT_FACE = 1, 152, 10, 234, 454
LEFT_IRIS = [468, 469, 470, 471, 472]
RIGHT_IRIS = [473, 474, 475, 476, 477]


def state_dir() -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")).expanduser()
    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def latest_expression_path() -> Path:
    return state_dir() / "latest_expression_state.json"


def runtime_state_path() -> Path:
    return state_dir() / "runtime_state.json"


def event_db_path() -> Path:
    return state_dir() / "avatar_events.sqlite3"


def event_jsonl_path() -> Path:
    return state_dir() / "facial_expression_events.jsonl"


def parse_camera(value: str) -> int:
    if value != "auto":
        return int(value)
    for idx in range(8):
        cap = cv2.VideoCapture(idx)
        ok, _ = cap.read()
        cap.release()
        if ok:
            return idx
    raise SystemExit("No usable webcam found from indexes 0..7.")


def import_mediapipe():
    try:
        import mediapipe as mp  # type: ignore
        if not hasattr(mp, "solutions") or not hasattr(mp.solutions, "face_mesh"):
            raise RuntimeError(f"mediapipe {getattr(mp, '__version__', '?')} has no legacy mp.solutions.face_mesh")
        return mp
    except Exception as e:
        raise SystemExit(
            "MediaPipe legacy FaceMesh unavailable. In this venv run:\n"
            "  python -m pip install --force-reinstall 'numpy==1.26.4' 'mediapipe==0.10.21'\n"
            f"Actual error: {e}"
        )


def pt(lms, idx: int, w: int, h: int) -> np.ndarray:
    p = lms[idx]
    return np.array([p.x * w, p.y * h], dtype=np.float64)


def mean_pt(lms, indices: list[int], w: int, h: int) -> np.ndarray:
    return np.mean([pt(lms, i, w, h) for i in indices], axis=0)


def dist(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.linalg.norm(a - b))


def safe_div(a: float, b: float, default: float = 0.0) -> float:
    return default if abs(b) < 1e-8 else float(a / b)


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def sigmoid01(x: float, centre: float, width: float) -> float:
    if width <= 0:
        return 1.0 if x >= centre else 0.0
    return 1.0 / (1.0 + math.exp(-(x - centre) / width))


class LocalEventBus:
    def __init__(self) -> None:
        self.db_path = event_db_path()
        self.jsonl_path = event_jsonl_path()
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS avatar_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                source TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                consumed INTEGER NOT NULL DEFAULT 0
            )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_avatar_events_type ON avatar_events(event_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_avatar_events_consumed ON avatar_events(consumed)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_avatar_events_ts ON avatar_events(ts)")

    def publish(self, event_type: str, payload: dict[str, Any], source: str = "eli_facial_expression_proactive") -> int:
        ts = time.time()
        payload = dict(payload)
        payload.setdefault("published_ts", ts)
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)

        with sqlite3.connect(str(self.db_path)) as conn:
            cur = conn.execute(
                "INSERT INTO avatar_events (ts, source, event_type, payload_json, consumed) VALUES (?, ?, ?, ?, 0)",
                (ts, source, event_type, payload_json),
            )
            event_id = int(cur.lastrowid)

        record = {"id": event_id, "ts": ts, "source": source, "event_type": event_type, "payload": payload, "consumed": False}
        with self.jsonl_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        return event_id


class SpeechWorker:
    def __init__(self, enabled: bool = False, rate: int = 165) -> None:
        self.enabled = enabled
        self.rate = rate
        self.q: "queue.Queue[str]" = queue.Queue()
        self.thread: Optional[threading.Thread] = None
        self.stop_flag = threading.Event()
        if enabled:
            self.start()

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.enabled = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def set_enabled(self, value: bool) -> None:
        self.enabled = value
        if value and (self.thread is None or not self.thread.is_alive()):
            self.start()

    def say(self, text: str) -> None:
        if self.enabled:
            self.q.put(text)

    def _run(self) -> None:
        try:
            import pyttsx3  # type: ignore
            engine = pyttsx3.init()
            engine.setProperty("rate", self.rate)
        except Exception as e:
            print(f"[!] pyttsx3 unavailable: {e}")
            self.enabled = False
            return

        while not self.stop_flag.is_set():
            try:
                text = self.q.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                engine.say(text)
                engine.runAndWait()
            except Exception as e:
                print(f"[!] speech error: {e}")

    def stop(self) -> None:
        self.stop_flag.set()


@dataclass
class ExpressionState:
    ts: float
    face_present: bool
    label: str
    prompt: Optional[str]
    confidence: float
    cues: dict[str, float]
    raw: dict[str, float]
    face_box: Optional[list[int]]
    notes: str = "Expression cues are uncertain visual estimates, not verified emotions."


class CueSmoother:
    def __init__(self, window: int = 18) -> None:
        self.window = window
        self.buffers: dict[str, deque[float]] = {}

    def update(self, cues: dict[str, float]) -> dict[str, float]:
        out = {}
        for key, val in cues.items():
            buf = self.buffers.setdefault(key, deque(maxlen=self.window))
            buf.append(float(val))
            out[key] = float(np.mean(buf))
        return out


class ProactivePolicy:
    def __init__(self, cooldown: float = 25.0, min_confidence: float = 0.62) -> None:
        self.cooldown = cooldown
        self.min_confidence = min_confidence
        self.last_emit_by_label: dict[str, float] = {}
        self.last_any_emit = 0.0

    def should_emit(self, state: ExpressionState, force: bool = False) -> bool:
        if force:
            return state.prompt is not None
        if not state.face_present or not state.prompt:
            return False
        if state.confidence < self.min_confidence:
            return False
        now = time.time()
        if now - self.last_any_emit < 4.0:
            return False
        if now - self.last_emit_by_label.get(state.label, 0.0) < self.cooldown:
            return False
        self.last_emit_by_label[state.label] = now
        self.last_any_emit = now
        return True


def extract_metrics(frame_bgr: np.ndarray, face_mesh) -> Optional[dict[str, Any]]:
    h, w = frame_bgr.shape[:2]
    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    res = face_mesh.process(rgb)
    if not res.multi_face_landmarks:
        return None

    lms = res.multi_face_landmarks[0].landmark

    left_face = pt(lms, LEFT_FACE, w, h)
    right_face = pt(lms, RIGHT_FACE, w, h)
    chin = pt(lms, CHIN, w, h)
    forehead = pt(lms, FOREHEAD, w, h)
    nose = pt(lms, NOSE_TIP, w, h)

    face_width = max(1.0, dist(left_face, right_face))
    face_height = max(1.0, dist(chin, forehead))

    mouth_left = pt(lms, MOUTH_LEFT, w, h)
    mouth_right = pt(lms, MOUTH_RIGHT, w, h)
    mouth_top = pt(lms, MOUTH_TOP, w, h)
    mouth_bottom = pt(lms, MOUTH_BOTTOM, w, h)

    mouth_width = dist(mouth_left, mouth_right)
    mouth_open = dist(mouth_top, mouth_bottom)

    l_eye_outer = pt(lms, L_EYE_OUTER, w, h)
    l_eye_inner = pt(lms, L_EYE_INNER, w, h)
    l_eye_top = pt(lms, L_EYE_TOP, w, h)
    l_eye_bottom = pt(lms, L_EYE_BOTTOM, w, h)
    r_eye_outer = pt(lms, R_EYE_OUTER, w, h)
    r_eye_inner = pt(lms, R_EYE_INNER, w, h)
    r_eye_top = pt(lms, R_EYE_TOP, w, h)
    r_eye_bottom = pt(lms, R_EYE_BOTTOM, w, h)

    l_eye_width = max(1.0, dist(l_eye_outer, l_eye_inner))
    r_eye_width = max(1.0, dist(r_eye_outer, r_eye_inner))
    l_eye_open = dist(l_eye_top, l_eye_bottom)
    r_eye_open = dist(r_eye_top, r_eye_bottom)

    l_brow_inner = pt(lms, L_BROW_INNER, w, h)
    l_brow_outer = pt(lms, L_BROW_OUTER, w, h)
    r_brow_inner = pt(lms, R_BROW_INNER, w, h)
    r_brow_outer = pt(lms, R_BROW_OUTER, w, h)

    l_brow_eye = (dist(l_brow_inner, l_eye_top) + dist(l_brow_outer, l_eye_top)) / 2.0
    r_brow_eye = (dist(r_brow_inner, r_eye_top) + dist(r_brow_outer, r_eye_top)) / 2.0

    anchors = np.array([pt(lms, i, w, h) for i in [FOREHEAD, CHIN, LEFT_FACE, RIGHT_FACE]])
    f1 = anchors.min(axis=0)
    f2 = anchors.max(axis=0)
    face_box = [int(f1[0]), int(f1[1]), int(f2[0] - f1[0]), int(f2[1] - f1[1])]

    yaw_proxy = safe_div(float(nose[0] - (left_face[0] + right_face[0]) / 2.0), face_width)
    pitch_proxy = safe_div(float(nose[1] - (forehead[1] + chin[1]) / 2.0), face_height)

    left_iris = mean_pt(lms, LEFT_IRIS, w, h)
    right_iris = mean_pt(lms, RIGHT_IRIS, w, h)

    metrics = {
        "mouth_width_ratio": safe_div(mouth_width, face_width),
        "mouth_open_ratio": safe_div(mouth_open, face_height),
        "left_eye_open_ratio": safe_div(l_eye_open, l_eye_width),
        "right_eye_open_ratio": safe_div(r_eye_open, r_eye_width),
        "avg_eye_open_ratio": safe_div((safe_div(l_eye_open, l_eye_width) + safe_div(r_eye_open, r_eye_width)), 2.0),
        "brow_eye_ratio": safe_div((l_brow_eye + r_brow_eye) / 2.0, face_height),
        "inner_brow_gap_ratio": safe_div(dist(l_brow_inner, r_brow_inner), face_width),
        "yaw_proxy": yaw_proxy,
        "pitch_proxy": pitch_proxy,
        "face_width": face_width,
        "face_height": face_height,
        "left_iris_x": float(left_iris[0]),
        "left_iris_y": float(left_iris[1]),
        "right_iris_x": float(right_iris[0]),
        "right_iris_y": float(right_iris[1]),
    }

    return {"metrics": metrics, "face_box": face_box}


def metrics_to_cues(metrics: dict[str, float]) -> tuple[dict[str, float], dict[str, float]]:
    mouth_width_ratio = metrics["mouth_width_ratio"]
    mouth_open_ratio = metrics["mouth_open_ratio"]
    eye_open = metrics["avg_eye_open_ratio"]
    brow_eye = metrics["brow_eye_ratio"]
    inner_brow_gap = metrics["inner_brow_gap_ratio"]
    yaw = abs(metrics["yaw_proxy"])

    smile = sigmoid01(mouth_width_ratio, 0.39, 0.025) * (1.0 - 0.45 * sigmoid01(mouth_open_ratio, 0.055, 0.020))
    mouth_open = sigmoid01(mouth_open_ratio, 0.045, 0.012)
    squint = 1.0 - sigmoid01(eye_open, 0.225, 0.030)
    brow_raise = sigmoid01(brow_eye, 0.105, 0.018)
    brow_furrow = clamp01((1.0 - sigmoid01(inner_brow_gap, 0.285, 0.030)) * 0.75 + squint * 0.35)
    fatigue = clamp01((1.0 - sigmoid01(eye_open, 0.19, 0.025)) * 0.70 + mouth_open * 0.15)
    attention = clamp01((1.0 - min(1.0, yaw * 2.2)) * 0.60 + sigmoid01(eye_open, 0.18, 0.030) * 0.40)
    tension = clamp01(brow_furrow * 0.55 + squint * 0.25 + (1.0 - smile) * 0.20)
    possible_frustration = clamp01(tension * 0.75 + brow_furrow * 0.25)

    cues = {
        "possible_smile": clamp01(smile),
        "mouth_open_or_speaking": clamp01(mouth_open),
        "eye_squint": clamp01(squint),
        "brow_raise": clamp01(brow_raise),
        "brow_furrow_or_tension": clamp01(brow_furrow),
        "possible_fatigue": clamp01(fatigue),
        "focused_attention": clamp01(attention),
        "possible_frustration_or_tension": clamp01(possible_frustration),
    }
    return cues, metrics


def choose_label_and_prompt(cues: dict[str, float]) -> tuple[str, Optional[str], float]:
    smile = cues.get("possible_smile", 0.0)
    frustration = cues.get("possible_frustration_or_tension", 0.0)
    fatigue = cues.get("possible_fatigue", 0.0)
    attention = cues.get("focused_attention", 0.0)
    speaking = cues.get("mouth_open_or_speaking", 0.0)
    brow_raise = cues.get("brow_raise", 0.0)

    if frustration > 0.68:
        return ("possible_frustration_or_tension",
                "I might be reading this wrong, but you look a bit tense or frustrated. Want me to slow this down and isolate the next concrete step?",
                frustration)
    if smile > 0.70:
        return ("possible_smile", "Glad to see that. Looks like that might have landed better.", smile)
    if fatigue > 0.72:
        return ("possible_fatigue", "You might be getting tired. Want me to reduce this to the next two commands only?", fatigue)
    if attention > 0.76:
        return ("focused_attention", None, attention)
    if speaking > 0.75:
        return ("speaking_or_mouth_open", None, speaking)
    if brow_raise > 0.76:
        return ("possible_surprise_or_questioning",
                "You look like something may have caught your attention. Want me to explain what just changed?",
                brow_raise)
    return ("neutral_or_uncertain", None, max(cues.values()) if cues else 0.0)


def build_expression_state(face_data: Optional[dict[str, Any]], smoother: CueSmoother) -> ExpressionState:
    if face_data is None:
        return ExpressionState(time.time(), False, "no_face", None, 0.0, {}, {}, None)

    cues, raw = metrics_to_cues(face_data["metrics"])
    smoothed = smoother.update(cues)
    label, prompt, conf = choose_label_and_prompt(smoothed)
    return ExpressionState(time.time(), True, label, prompt, float(conf), smoothed, raw, face_data["face_box"])


def write_latest_state(state: ExpressionState, runtime_merge: bool = True) -> None:
    payload = asdict(state)
    latest_expression_path().write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if runtime_merge:
        runtime = {}
        path = runtime_state_path()
        try:
            if path.exists():
                runtime = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            runtime = {}

        runtime.update({
            "ts": time.time(),
            "face_present": state.face_present,
            "expression_label": state.label,
            "expression_confidence": state.confidence,
            "possible_frustration_or_tension": state.cues.get("possible_frustration_or_tension", 0.0),
            "possible_smile": state.cues.get("possible_smile", 0.0),
            "possible_fatigue": state.cues.get("possible_fatigue", 0.0),
            "focused_attention": state.cues.get("focused_attention", 0.0),
        })
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(runtime, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)


def draw_debug(frame: np.ndarray, state: ExpressionState, show_hud: bool = True) -> None:
    if state.face_box:
        x, y, w, h = state.face_box
        cv2.rectangle(frame, (x, y), (x + w, y + h), (190, 190, 190), 1)

    if not show_hud:
        return

    lines = [
        "ELI facial-expression proactive engine",
        f"label={state.label} conf={state.confidence:.2f} face={state.face_present}",
    ]
    for key in [
        "possible_smile",
        "possible_frustration_or_tension",
        "possible_fatigue",
        "focused_attention",
        "brow_furrow_or_tension",
        "eye_squint",
        "mouth_open_or_speaking",
    ]:
        if key in state.cues:
            lines.append(f"{key}: {state.cues[key]:.2f}")
    if state.prompt:
        lines.append("prompt: " + state.prompt[:92])
    lines.append("q quit | h HUD | s speech | p proactive | e emit event")

    yy = 24
    for line in lines[:14]:
        cv2.putText(frame, line, (12, yy), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(frame, line, (12, yy), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (235, 235, 235), 1, cv2.LINE_AA)
        yy += 22


def main() -> int:
    ap = argparse.ArgumentParser(description="Local facial-expression cue engine for proactive ELI avatar responses.")
    ap.add_argument("--camera", default="auto")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--mirror", action="store_true", default=True)
    ap.add_argument("--no-mirror", dest="mirror", action="store_false")
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--no-window", action="store_true")
    ap.add_argument("--publish-events", action="store_true", default=True)
    ap.add_argument("--no-publish-events", dest="publish_events", action="store_false")
    ap.add_argument("--speak", action="store_true")
    ap.add_argument("--no-proactive", dest="proactive", action="store_false", default=True)
    ap.add_argument("--cooldown", type=float, default=28.0)
    ap.add_argument("--min-confidence", type=float, default=0.64)
    ap.add_argument("--speech-rate", type=int, default=165)
    ap.add_argument("--window", type=int, default=18, help="Smoothing window over frames.")
    args = ap.parse_args()

    mp = import_mediapipe()
    cam = parse_camera(args.camera)

    cap = cv2.VideoCapture(cam)
    if not cap.isOpened():
        raise SystemExit(f"Could not open camera {cam}")
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)

    face_mesh = mp.solutions.face_mesh.FaceMesh(
        static_image_mode=False,
        max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=0.60,
        min_tracking_confidence=0.60,
    )

    bus = LocalEventBus() if args.publish_events else None
    smoother = CueSmoother(window=args.window)
    policy = ProactivePolicy(cooldown=args.cooldown, min_confidence=args.min_confidence)
    speaker = SpeechWorker(enabled=args.speak, rate=args.speech_rate)

    show_hud = True
    proactive_enabled = bool(args.proactive)
    speech_enabled = bool(args.speak)
    force_emit = False

    print("[+] ELI facial-expression proactive engine online.")
    print(f"[+] Camera: {cam}")
    print(f"[+] Latest expression: {latest_expression_path()}")
    print(f"[+] Runtime bridge:     {runtime_state_path()}")
    print(f"[+] Events DB:          {event_db_path()}")
    print(f"[+] Events JSONL:       {event_jsonl_path()}")
    print(f"[+] Speech enabled:     {speech_enabled}")
    print("[!] Labels are uncertain expression cues, not verified emotions.")

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.03)
                continue

            if args.mirror:
                frame = cv2.flip(frame, 1)

            face_data = extract_metrics(frame, face_mesh)
            state = build_expression_state(face_data, smoother)
            write_latest_state(state, runtime_merge=True)

            should = proactive_enabled and policy.should_emit(state, force=force_emit)
            if should:
                payload = asdict(state)
                if bus:
                    payload["event_id"] = bus.publish("facial_expression_cue", payload)
                print(json.dumps({
                    "event": "facial_expression_cue",
                    "label": state.label,
                    "confidence": round(state.confidence, 3),
                    "prompt": state.prompt,
                }, ensure_ascii=False))
                if state.prompt and speech_enabled:
                    speaker.say(state.prompt)
            force_emit = False

            if not args.no_window:
                draw_debug(frame, state, show_hud=show_hud)
                cv2.imshow("ELI Facial Expression Proactive Engine", frame)
                key = cv2.waitKey(1) & 0xFF
                if key in (27, ord("q")):
                    break
                elif key == ord("h"):
                    show_hud = not show_hud
                elif key == ord("s"):
                    speech_enabled = not speech_enabled
                    speaker.set_enabled(speech_enabled)
                    print(f"[+] speech_enabled={speech_enabled}")
                elif key == ord("p"):
                    proactive_enabled = not proactive_enabled
                    print(f"[+] proactive_enabled={proactive_enabled}")
                elif key == ord("e"):
                    force_emit = True

            if args.no_window:
                time.sleep(0.01)

    except KeyboardInterrupt:
        print("\n[+] stopped")
    finally:
        cap.release()
        speaker.stop()
        if not args.no_window:
            cv2.destroyAllWindows()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
