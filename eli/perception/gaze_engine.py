"""
eli/perception/gaze_engine.py
─────────────────────────────
ELI gaze tracking daemon wrapper.

Manages a background thread that:
  - Opens the webcam via FaceGazeExtractor
  - Runs real-time gaze estimation (MediaPipe iris / Haar fallback)
  - Applies ridge-regression calibration if a calibration file exists
  - Smooths output via OneEuroLikeFilter
  - Writes latest_gaze.json to the XDG state dir every ~100 ms

When no calibration exists the engine still runs and produces raw
face-centre coordinates — useful for "is someone present" detection.

Public API
----------
    start_gaze_engine(camera="auto") -> dict
    stop_gaze_engine()               -> dict
    get_gaze_status()                -> dict
    get_last_gaze()                  -> dict | None   (last written JSON payload)
    is_gaze_running()                -> bool
    needs_calibration()              -> bool
    get_calibration_path()           -> pathlib.Path

Settings key: "gaze_engine_enabled" (bool) in runtime_settings.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional


from eli.utils.log import get_logger
log = get_logger(__name__)

# ── gaze_core location ────────────────────────────────────────────────────────
# The kit lives in experimental/; inject it once, lazily.
_GAZE_CORE_CANDIDATES: list[Path] = [
    Path(__file__).resolve().parents[2] / "experimental" / "eli_ar_avatar_kit" / "eli_gaze_core",
    Path(__file__).resolve().parents[2] / "experimental" / "eli_ar_avatar_kit_v5_bad_calibration_backup_20260510_223039" / "eli_gaze_core",
]

_gaze_core_injected = False


def _inject_gaze_core() -> bool:
    """Add the first valid gaze_core parent to sys.path. Return True on success."""
    global _gaze_core_injected
    if _gaze_core_injected:
        return True
    for candidate in _GAZE_CORE_CANDIDATES:
        if candidate.is_dir():
            parent = str(candidate.parent)
            if parent not in sys.path:
                sys.path.insert(0, parent)
            _gaze_core_injected = True
            return True
    return False


# ── Cross-platform state/config paths (platformdirs via eli.core.paths) ──────
def _gaze_state_dir() -> Path:
    try:
        from eli.core.paths import data_dir
        base = Path(data_dir())
    except Exception:
        xdg = os.environ.get("XDG_STATE_HOME")
        base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "state"
    p = base / "eli_ar_avatar"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _gaze_config_dir() -> Path:
    try:
        from eli.core.paths import config_dir
        base = Path(config_dir())
    except Exception:
        xdg = os.environ.get("XDG_CONFIG_HOME")
        base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    p = base / "eli_ar_avatar"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_calibration_path() -> Path:
    return _gaze_config_dir() / "gaze_calibration_v2.json"


def needs_calibration() -> bool:
    return not get_calibration_path().exists()


# ── Singleton daemon ──────────────────────────────────────────────────────────

class _GazeEngineService:
    """Singleton background thread managing gaze capture and state writes."""

    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._last_payload: Optional[Dict[str, Any]] = None
        self._error: Optional[str] = None
        self._camera: str | int = "auto"

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, camera: str | int = "auto") -> Dict[str, Any]:
        with self._lock:
            if self.is_running():
                return {"ok": True, "already_running": True,
                        "message": "Gaze engine is already running.",
                        "calibrated": not needs_calibration()}
            if not _inject_gaze_core():
                msg = "Gaze core not found. Expected eli_ar_avatar_kit in experimental/."
                self._error = msg
                return {"ok": False, "error": msg, "message": msg}
            # Verify opencv is available before spawning
            try:
                import cv2  # noqa: F401
            except ImportError:
                msg = "cv2 (OpenCV) not installed. Run: pip install opencv-python-headless"
                self._error = msg
                return {"ok": False, "error": msg, "message": msg}
            self._camera = camera
            self._stop_event.clear()
            self._error = None
            self._thread = threading.Thread(
                target=self._run_loop,
                name="eli-gaze-engine",
                daemon=True,
            )
            self._thread.start()
            time.sleep(0.15)  # let thread initialise
            if self._error:
                return {"ok": False, "error": self._error, "message": self._error}
            return {
                "ok": True,
                "message": "Gaze engine started.",
                "calibrated": not needs_calibration(),
                "camera": camera,
            }

    def stop(self) -> Dict[str, Any]:
        with self._lock:
            if not self.is_running():
                return {"ok": True, "message": "Gaze engine was not running."}
            self._stop_event.set()
        self._thread.join(timeout=3.0)
        return {"ok": True, "message": "Gaze engine stopped."}

    def get_last_payload(self) -> Optional[Dict[str, Any]]:
        return self._last_payload

    def status(self) -> Dict[str, Any]:
        state_path = _gaze_state_dir() / "latest_gaze.json"
        cal_path = get_calibration_path()
        last: Optional[Dict[str, Any]] = None
        if state_path.exists():
            try:
                last = json.loads(state_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {
            "running": self.is_running(),
            "calibrated": cal_path.exists(),
            "calibration_path": str(cal_path),
            "state_path": str(state_path),
            "last_gaze": last,
            "error": self._error,
            "camera": self._camera,
        }

    # ── background loop ───────────────────────────────────────────────────────

    def _dwell_config(self) -> Dict[str, Any]:
        """Read dwell-click settings (opt-in; sensible defaults). Dwell-click is the
        hands-free AND voice-free path: rest your gaze on a target and it clicks there —
        for users who can operate neither a mouse nor voice. Off by default because an
        always-on auto-click is intrusive; a person who needs it turns it on and stays on."""
        try:
            from eli.core.runtime_settings import load_settings
            s = load_settings() or {}
        except Exception:
            s = {}
        def _f(key, dflt):
            try:
                return float(s.get(key, dflt))
            except Exception:
                return float(dflt)
        return {
            "enabled": bool(s.get("gaze_dwell_click", False)),
            "seconds": max(0.4, _f("gaze_dwell_seconds", 1.0)),   # hold time before it clicks
            "radius": max(20.0, _f("gaze_dwell_radius", 60.0)),   # px the gaze may wander
            "min_conf": max(0.0, min(1.0, _f("gaze_dwell_min_confidence", 0.35))),
        }

    def _do_dwell_click(self, x: int, y: int) -> None:
        """Left-click at the dwelled-on gaze point via the cross-platform mouse backend."""
        try:
            from eli.perception.os_controller import mouse_click
            mouse_click(button="left", x=int(x), y=int(y))
            log.debug(f"[GAZE] dwell-click at ({x},{y})")
        except Exception as e:
            log.debug(f"[GAZE] dwell-click failed: {e}")

    def _run_loop(self):
        try:
            from eli_gaze_core.face_gaze import FaceGazeExtractor, open_camera
            from eli_gaze_core.calibration import GazeMapper, OneEuroLikeFilter
        except Exception as e:
            self._error = f"Failed to import gaze core: {e}"
            return

        try:
            cap, cam_idx = open_camera(self._camera)
        except Exception as e:
            self._error = f"Camera open failed: {e}"
            return

        extractor = FaceGazeExtractor(mirror=True, prefer_mediapipe=True)
        smooth = OneEuroLikeFilter()
        cal_path = get_calibration_path()
        mapper: Optional[GazeMapper] = None
        if cal_path.exists():
            try:
                mapper = GazeMapper(cal_path)
            except Exception as e:
                log.debug(f"[GAZE] Calibration load failed: {e} — running uncalibrated")

        state_path = _gaze_state_dir() / "latest_gaze.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)

        last_write = 0.0
        WRITE_INTERVAL = 0.10  # 10 Hz state writes

        # Dwell-click state (accessibility). Config is cached + refreshed every 2s so toggling
        # the setting takes effect quickly without a file read on every frame.
        _dwell_anchor: Optional[tuple] = None
        _dwell_start = 0.0
        _last_dwell_click = 0.0
        _dcfg = self._dwell_config()
        _dcfg_ts = time.time()

        try:
            while not self._stop_event.is_set():
                ok, frame = cap.read()
                if not ok or frame is None:
                    time.sleep(0.05)
                    continue

                sample = extractor.extract(frame)
                now = time.time()

                if sample is None:
                    payload: Dict[str, Any] = {
                        "ts": now,
                        "camera": cam_idx,
                        "tracker": extractor.method,
                        "face_detected": False,
                        "confidence": 0.0,
                        "calibrated": mapper is not None,
                    }
                else:
                    if mapper is not None:
                        raw_x, raw_y = mapper.predict(sample.features)
                        sx, sy = smooth.update(raw_x, raw_y, confidence=sample.confidence)
                    else:
                        # Uncalibrated: use normalised iris midpoint scaled to 1920×1080 default
                        iris_x = float(sample.features[6]) if len(sample.features) > 6 else 0.5
                        iris_y = float(sample.features[7]) if len(sample.features) > 7 else 0.5
                        sx, sy = iris_x * 1920, iris_y * 1080
                        raw_x, raw_y = sx, sy

                    payload = {
                        "ts": now,
                        "camera": cam_idx,
                        "tracker": sample.method,
                        "face_detected": True,
                        "screen_x": float(sx),
                        "screen_y": float(sy),
                        "raw_x": float(raw_x),
                        "raw_y": float(raw_y),
                        "confidence": float(sample.confidence),
                        "face_box": list(sample.face_box),
                        "calibrated": mapper is not None,
                    }
                    self._last_payload = payload

                    # ── Dwell-click: hold your gaze on a spot and it clicks there — the
                    # hands-free AND voice-free path. Opt-in, calibrated + confident only, with
                    # a cooldown so it can't machine-gun. Resets after a click (must re-dwell).
                    if now - _dcfg_ts >= 2.0:
                        _dcfg = self._dwell_config()
                        _dcfg_ts = now
                    if _dcfg["enabled"] and mapper is not None and sample.confidence >= _dcfg["min_conf"]:
                        if (_dwell_anchor is not None
                                and abs(sx - _dwell_anchor[0]) <= _dcfg["radius"]
                                and abs(sy - _dwell_anchor[1]) <= _dcfg["radius"]):
                            if ((now - _dwell_start) >= _dcfg["seconds"]
                                    and (now - _last_dwell_click) >= max(_dcfg["seconds"], 1.2)):
                                self._do_dwell_click(int(sx), int(sy))
                                _last_dwell_click = now
                                _dwell_anchor = None
                        else:
                            _dwell_anchor = (sx, sy)
                            _dwell_start = now
                    else:
                        _dwell_anchor = None

                if now - last_write >= WRITE_INTERVAL:
                    try:
                        state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
                    except Exception:
                        pass
                    last_write = now

        finally:
            cap.release()


_service = _GazeEngineService()


# ── Module-level public API ───────────────────────────────────────────────────

def start_gaze_engine(camera: str | int = "auto") -> Dict[str, Any]:
    return _service.start(camera=camera)


def stop_gaze_engine() -> Dict[str, Any]:
    return _service.stop()


def get_gaze_status() -> Dict[str, Any]:
    return _service.status()


def is_gaze_running() -> bool:
    return _service.is_running()


def get_last_gaze() -> Optional[Dict[str, Any]]:
    state_path = _gaze_state_dir() / "latest_gaze.json"
    if state_path.exists():
        try:
            return json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return _service.get_last_payload()
