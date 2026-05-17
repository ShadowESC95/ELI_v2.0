from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "eli_ar_avatar"


def kit_root() -> Path:
    return Path(__file__).resolve().parents[1]


def user_config_dir() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    p = base / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def user_state_dir() -> Path:
    xdg = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "state"
    p = base / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def default_calibration_path() -> Path:
    return user_config_dir() / "gaze_calibration_v2.json"


def default_state_path() -> Path:
    return user_state_dir() / "latest_gaze.json"


def default_event_path() -> Path:
    return user_state_dir() / "gaze_events.jsonl"
