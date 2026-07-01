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
    p.write_text(token, encoding="utf-8")
    # It's a credential — restrict to the owner where the OS supports it.
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

    Invalidates every currently-paired device — they must re-open the fresh URL.
    """
    tok = secrets.token_urlsafe(16)
    _write_file_token(tok)
    os.environ[_TOKEN_ENV] = tok
    return tok
