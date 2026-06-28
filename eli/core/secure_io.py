"""Race-free writing of files that must never be world-readable.

The naive pattern ``path.write_text(...)`` then ``os.chmod(path, 0o600)`` leaves a
window: on a typical umask of 022 the file is born ``0644`` (world-readable) and,
on a multi-user box, another user could read it in the milliseconds before the
chmod lands. That is a real (if narrow) TOCTOU on exactly the files where it
matters most — the audit HMAC key, the API token store, settings that may hold
broker passwords.

``secure_write_text`` removes the window instead of closing it after the fact:
it writes to a temp file in the *same directory* that is born locked
(``tempfile.mkstemp`` creates with mode ``0600`` by design), flushes/fsyncs, sets
the intended mode explicitly, then ``os.replace`` — an atomic rename on the same
filesystem. The destination therefore never exists in a world-readable state,
and readers either see the old file or the fully-written new one, never a
partial.

POSIX-first; degrades gracefully on Windows (mode bits are advisory there, and
mkstemp still restricts via the user's default ACL).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Union

__all__ = ["secure_write_text", "secure_write_bytes"]


def secure_write_bytes(path: Union[str, "os.PathLike[str]"], data: bytes,
                       *, mode: int = 0o600) -> Path:
    """Atomically write ``data`` to ``path`` such that the file is never
    world-readable at any instant. Returns the resolved destination Path."""
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    # mkstemp is born 0600 and uses O_EXCL, so the secret bytes are written into
    # a file that is owner-only from the very first byte.
    fd, tmp = tempfile.mkstemp(dir=str(dest.parent), prefix="." + dest.name + ".",
                               suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        # Make the intended mode explicit (e.g. callers asking for 0o600 vs a
        # looser mode) rather than relying solely on mkstemp's default.
        try:
            os.chmod(tmp, mode)
        except OSError:
            pass
        os.replace(tmp, dest)  # atomic on the same filesystem
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return dest


def secure_write_text(path: Union[str, "os.PathLike[str]"], text: str,
                      *, mode: int = 0o600, encoding: str = "utf-8") -> Path:
    """Text convenience wrapper around :func:`secure_write_bytes`."""
    return secure_write_bytes(path, text.encode(encoding), mode=mode)
