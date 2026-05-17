from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict

from eli.core.paths import get_paths
from eli.runtime.identity_validation import normalize_identity_candidate


_BAD_NAMES = {"asking", "[user]", "<user>", "<username>", "<local_user>", "unknown", "none"}


def _runtime_dir() -> Path:
    p = Path(get_paths().artifacts_dir) / "runtime"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _state_path() -> Path:
    return _runtime_dir() / "state.json"


def _legacy_profile_path() -> Path:
    # Legacy global profile path. Kept only for repair/cleanup, not normal identity lookup.
    return _runtime_dir() / "user_profile.json"


def _read_json(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
    try:
        if path.exists():
            obj = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(obj, dict):
                return obj
    except Exception:
        pass
    return dict(default)


def _write_json(path: Path, data: Dict[str, Any]) -> Dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return data


def load_state() -> Dict[str, Any]:
    return _read_json(_state_path(), {})


def save_state(state: Dict[str, Any]) -> Dict[str, Any]:
    return _write_json(_state_path(), dict(state or {}))


def _safe_user_id(user_id: str | None = None) -> str:
    raw = str(user_id or "").strip()
    if not raw:
        raw = str(load_state().get("active_user_id") or "").strip()

    if not raw:
        try:
            uid_file = Path(get_paths().config_dir) / "user_id"
            if uid_file.exists():
                raw = uid_file.read_text(encoding="utf-8", errors="replace").strip()
        except Exception:
            raw = ""

    if not raw:
        try:
            uid_file = Path.home() / ".eli_user_id"
            if uid_file.exists():
                raw = uid_file.read_text(encoding="utf-8", errors="replace").strip()
        except Exception:
            raw = ""

    if not raw:
        raw = "default-user"

    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("._-")
    return safe[:96] or "default-user"


def get_active_user_id(default: str = "default-user") -> str:
    uid = _safe_user_id(None)
    return uid or default


def set_active_user_id(user_id: str) -> str:
    uid = _safe_user_id(user_id)
    state = load_state()
    state["active_user_id"] = uid
    # Never store a name globally here. This is only a scope key.
    state.pop("user_name", None)
    save_state(state)
    return uid


def _user_runtime_dir(user_id: str | None = None) -> Path:
    p = _runtime_dir() / "users" / _safe_user_id(user_id)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _profile_path(user_id: str | None = None) -> Path:
    return _user_runtime_dir(user_id) / "user_profile.json"


def load_user_profile(user_id: str | None = None) -> Dict[str, Any]:
    # Strictly user-scoped. No automatic legacy fallback, because that leaks one user's
    # identity/preferences into every other user.
    return _read_json(_profile_path(user_id), {})


def save_user_profile(profile: Dict[str, Any], user_id: str | None = None) -> Dict[str, Any]:
    return _write_json(_profile_path(user_id), dict(profile or {}))


def _clean_name(name: str) -> str:
    n = normalize_identity_candidate(name)
    return "" if n.lower() in _BAD_NAMES else n


def get_user_name(default: str = "", user_id: str | None = None) -> str:
    profile = load_user_profile(user_id)
    return _clean_name(str(profile.get("name", default) or ""))


def set_user_name(name: str, user_id: str | None = None) -> str:
    # Dynamic and user-scoped. This function is allowed, but it must only be called
    # after explicit identity extraction/confirmation for the active user.
    n = _clean_name(name)
    profile = load_user_profile(user_id)

    if n:
        profile["name"] = n
    else:
        profile.pop("name", None)

    save_user_profile(profile, user_id)
    sync_identity_to_world_model(user_id=user_id)
    return n


def clear_user_name(user_id: str | None = None) -> None:
    set_user_name("", user_id=user_id)


def update_user_profile(update: Dict[str, Any] | None = None, user_id: str | None = None, **kwargs: Any) -> Dict[str, Any]:
    profile = load_user_profile(user_id)

    if update:
        profile.update(dict(update))
    if kwargs:
        profile.update(kwargs)

    if _clean_name(str(profile.get("name", "") or "")) == "":
        profile.pop("name", None)

    for key in ("preferred_name", "nickname"):
        if key in profile and normalize_identity_candidate(profile.get(key, "")) == "":
            profile.pop(key, None)

    if isinstance(profile.get("aliases"), list):
        aliases = [
            v for v in (
                normalize_identity_candidate(x)
                for x in profile.get("aliases", [])
            )
            if v
        ]
        if aliases:
            profile["aliases"] = aliases
        else:
            profile.pop("aliases", None)

    save_user_profile(profile, user_id)
    sync_identity_to_world_model(user_id=user_id)
    return profile


def _format_profile_value(key: str, v: Any) -> str:
    label = key.replace("_", " ").capitalize()
    if isinstance(v, (list, tuple)):
        items = [str(x).strip() for x in v if str(x).strip()]
        if not items:
            return ""
        return label + ":\n" + "\n".join(f"  - {x}" for x in items)
    s = str(v).strip()
    return f"{label}: {s}" if s else ""


def get_user_profile_text(user_id: str | None = None) -> str:
    profile = load_user_profile(user_id)
    name = get_user_name("", user_id=user_id) or _clean_name(str(profile.get("name", "") or ""))

    lines = []
    if name:
        lines.append(f"Name: {name}")

    for k, v in profile.items():
        if k == "name":
            continue
        if v is None:
            continue
        formatted = _format_profile_value(k, v)
        if formatted:
            lines.append(formatted)

    return "\n".join(lines).strip()


def world_model_snapshot_bridge():
    try:
        from eli.kernel.world_model import world_model_snapshot
        return world_model_snapshot()
    except Exception:
        return {}


def sync_identity_to_world_model(user_id: str | None = None) -> None:
    try:
        from eli.kernel.world_model import get_world_model, save_world_model
        wm = get_world_model()
        uid = _safe_user_id(user_id)
        n = get_user_name("", user_id=uid).strip()
        wm.identity.user_id = uid
        wm.identity.preferred_name = n
        wm.identity.confidence = 1.0 if n else 0.0
        wm.identity.updated_at = time.time()
        save_world_model(wm)
    except Exception:
        pass


def repair_identity_state() -> Dict[str, Any]:
    """
    Remove invalid/global identity fragments from runtime artifacts.

    This deliberately does not promote any hardcoded name. User identity must come
    from active-user-scoped profile extraction.
    """
    state = load_state()
    changed: Dict[str, Any] = {
        "state_removed": [],
        "profile_removed": [],
        "legacy_profile_path": str(_legacy_profile_path()),
    }

    if "user_name" in state:
        state.pop("user_name", None)
        changed["state_removed"].append("user_name")

    # Clean active user profile.
    profile = load_user_profile()
    for key in ("name", "preferred_name", "nickname"):
        if key in profile and not normalize_identity_candidate(profile.get(key, "")):
            profile.pop(key, None)
            changed["profile_removed"].append(key)

    if isinstance(profile.get("aliases"), list):
        aliases = [
            v for v in (
                normalize_identity_candidate(x)
                for x in profile.get("aliases", [])
            )
            if v
        ]
        if aliases:
            profile["aliases"] = aliases
        else:
            profile.pop("aliases", None)
            changed["profile_removed"].append("aliases")

    save_state(state)
    save_user_profile(profile)
    sync_identity_to_world_model()

    changed["ok"] = True
    changed["active_user_id"] = get_active_user_id()
    changed["active_profile_path"] = str(_profile_path())
    changed["state"] = state
    changed["profile_keys"] = sorted(profile.keys())
    return changed


__all__ = [
    "load_state",
    "save_state",
    "get_active_user_id",
    "set_active_user_id",
    "load_user_profile",
    "save_user_profile",
    "get_user_name",
    "set_user_name",
    "clear_user_name",
    "update_user_profile",
    "get_user_profile_text",
    "world_model_snapshot_bridge",
    "sync_identity_to_world_model",
    "repair_identity_state",
]
