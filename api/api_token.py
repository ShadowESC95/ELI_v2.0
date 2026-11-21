"""Stable LAN API token.

The LAN web server (the phone companion) authenticates devices with a bearer
token. Historically the GUI minted a BRAND-NEW token on every server start, which
silently stranded any already-paired phone: its saved URL / PWA still carried the
old ``?token=…``, so after any restart the server answered 401 and the phone
"could no longer access the server".

This module persists the token ONCE under ``config_dir()`` and reuses it across
restarts, so a paired device keeps working. Rotate explicitly (``rotate_token``)
when you actually want to kick paired devices off.
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

_TOKEN_ENV = "ELI_API_TOKEN"
_TOKEN_FILENAME = "api_token"


def _token_file() -> Path:
    # Imported lazily so this module has no import-time dependency on the paths
    # package (keeps it safe to import from the API server and the GUI alike).
    from eli.core.paths import config_dir
    return config_dir() / _TOKEN_FILENAME


def _read_file_token() -> str:
    try:
        p = _token_file()
        if p.exists():
            return p.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return ""


def _write_file_token(token: str) -> None:
    p = _token_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    # write_text() + chmod() would birth this credential world-readable (0644 on a
    # umask-022 box) and only lock it a few milliseconds later — the exact TOCTOU
    # `eli.core.secure_io` exists to remove, and which the sibling API-user store
    # already uses. This is the LAN bearer token: anyone who reads it in that
    # window owns the server. Write it born-locked and rename atomically instead.
    try:
        from eli.core.secure_io import secure_write_text as _secure_write
        _secure_write(p, token, mode=0o600)
        return
    except Exception:
        pass
    # Fallback only if secure_io is unavailable — still better than not writing.
    p.write_text(token, encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except Exception:
        pass


def get_stable_token() -> str:
    """Return the persistent LAN API token, minting+persisting one on first use.

    Precedence:
      1. ``ELI_API_TOKEN`` already in the environment (explicit override) — used as-is.
      2. The persisted token file under ``config_dir()``.
      3. A freshly generated token, persisted for next time.
    """
    env = os.environ.get(_TOKEN_ENV, "").strip()
    if env:
        return env
    tok = _read_file_token()
    if not tok:
        tok = secrets.token_urlsafe(16)
        _write_file_token(tok)
    return tok


def rotate_token() -> str:
    """Generate a NEW token, persist it, and export it into the environment.

    Invalidates every currently-paired device — they must re-open the fresh URL. A
    server in another process sees it through its token file (``serve_persisted``).
    """
    tok = secrets.token_urlsafe(16)
    _write_file_token(tok)
    os.environ[_TOKEN_ENV] = tok
    return tok


# Set in a server process whose token is the persisted one. The flag lives in the
# environment because uvicorn imports `api.server` afresh: a module global set in
# main() is not the module that answers requests.
_FOLLOW_FILE_ENV = "ELI_API_TOKEN_FOLLOWS_FILE"
_file_cache: dict = {"key": None, "token": ""}


def serve_persisted(token: str) -> bool:
    """Called by a server as it starts with ``token``. When that is the persisted token,
    requests are checked against the token file from then on (``current_token``), so
    a rotation made by another process — the desktop app — reaches this server at
    once. An explicit token that is not the persisted one is kept as given."""
    if token and token == _read_file_token():
        os.environ[_FOLLOW_FILE_ENV] = "1"
        return True
    os.environ.pop(_FOLLOW_FILE_ENV, None)
    return False


def current_token() -> str:
    """The token a request is checked against: the token file's when this process
    serves the persisted token, else ``ELI_API_TOKEN``. The file is re-read only when
    it changes, and an unreadable file falls back to the token the server started with."""
    env = os.environ.get(_TOKEN_ENV, "").strip()
    if os.environ.get(_FOLLOW_FILE_ENV) != "1":
        return env
    try:
        st = _token_file().stat()
        key = (st.st_mtime_ns, st.st_size, st.st_ino)
    except OSError:
        return env
    if key != _file_cache["key"]:
        _file_cache["token"] = _read_file_token()
        _file_cache["key"] = key
    return _file_cache["token"] or env
