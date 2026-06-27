"""API users + roles (admin / member RBAC) for the web server.

Opt-in. With no users defined the API stays in single-operator mode — the legacy
``ELI_API_TOKEN`` (or a loopback bind) is treated as the admin operator, exactly as
before. Define users and every request's bearer token resolves to a ``(user_id, role)``:
attribution becomes *authenticated* (a member can't claim to be someone else), and
admin-only surfaces (the Admin console + user management) are gated to admins.

Security: tokens are stored ONLY as SHA-256 hashes; the raw token is shown once, at
creation. The store lives at ``config/api_users.json`` (gitignored, per-deployment).
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

_lock = threading.Lock()
ROLES = ("admin", "member")


def _store_path() -> Path:
    env = os.environ.get("ELI_API_USERS_FILE", "").strip()
    if env:
        return Path(env).expanduser()
    try:
        from eli.core.paths import config_dir
        return Path(config_dir()) / "api_users.json"
    except Exception:
        return Path("config") / "api_users.json"


def _hash(token: str) -> str:
    # Namespaced so the hash is useless outside ELI's token space.
    return hashlib.sha256(("eli-api:" + (token or "")).encode("utf-8")).hexdigest()


def _load_raw() -> List[dict]:
    p = _store_path()
    try:
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return [d for d in data if isinstance(d, dict)]
    except Exception:
        pass
    return []


def _save_raw(users: List[dict]) -> None:
    p = _store_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.part")
    tmp.write_text(json.dumps(users, indent=2), encoding="utf-8")
    tmp.replace(p)


def rbac_enabled() -> bool:
    """True once at least one user is defined — RBAC is then enforced."""
    return len(_load_raw()) > 0


def list_users() -> List[Dict[str, str]]:
    """User ids + roles (never the token hashes)."""
    return [{"user_id": u.get("user_id", ""), "role": u.get("role", "member")}
            for u in _load_raw()]


def resolve_token(token: str) -> Optional[Dict[str, str]]:
    """Resolve a raw bearer token to its {user_id, role}, or None. Constant-time."""
    if not token:
        return None
    h = _hash(token)
    match = None
    for u in _load_raw():
        # Compare every row (no early return) to avoid leaking which row matched via timing.
        if secrets.compare_digest(str(u.get("token_sha256", "")), h):
            match = {"user_id": u.get("user_id", ""), "role": u.get("role", "member")}
    return match


def add_user(user_id: str, role: str = "member") -> Dict[str, Any]:
    """Create (or replace) a user, returning a freshly-minted token ONCE."""
    user_id = (user_id or "").strip()
    role = role if role in ROLES else "member"
    if not user_id:
        return {"ok": False, "error": "user_id required"}
    token = secrets.token_urlsafe(24)
    with _lock:
        users = [u for u in _load_raw() if u.get("user_id") != user_id]
        users.append({"user_id": user_id, "role": role, "token_sha256": _hash(token)})
        _save_raw(users)
    return {"ok": True, "user_id": user_id, "role": role, "token": token}


def remove_user(user_id: str) -> Dict[str, Any]:
    with _lock:
        users = _load_raw()
        kept = [u for u in users if u.get("user_id") != user_id]
        if len(kept) == len(users):
            return {"ok": False, "error": "no such user"}
        # Don't let the LAST admin be removed (would lock everyone out of admin).
        if not any(u.get("role") == "admin" for u in kept):
            return {"ok": False, "error": "cannot remove the last admin"}
        _save_raw(kept)
    return {"ok": True, "user_id": user_id}


def _main(argv: List[str]) -> int:
    use = ("Usage: python -m eli.runtime.api_users "
           "add <user_id> [admin|member] | remove <user_id> | list")
    if not argv:
        print(use)
        return 2
    cmd = argv[0]
    if cmd == "list":
        users = list_users()
        print("RBAC " + ("ENABLED" if users else "disabled (single-operator mode)"))
        for u in users:
            print(f"  {u['role']:<7} {u['user_id']}")
        return 0
    if cmd == "add" and len(argv) >= 2:
        role = argv[2] if len(argv) >= 3 else "member"
        r = add_user(argv[1], role)
        if not r.get("ok"):
            print("error:", r.get("error"))
            return 1
        print(f"Created {r['role']} '{r['user_id']}'.")
        print(f"  Token (store it now — shown only once): {r['token']}")
        return 0
    if cmd == "remove" and len(argv) >= 2:
        r = remove_user(argv[1])
        print("removed" if r.get("ok") else ("error: " + str(r.get("error"))))
        return 0 if r.get("ok") else 1
    print(use)
    return 2


if __name__ == "__main__":
    import sys
    raise SystemExit(_main(sys.argv[1:]))
