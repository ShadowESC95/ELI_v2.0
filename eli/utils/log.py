"""
eli.utils.log — Central ELI logger factory.

Usage in any module:
    from eli.utils.log import get_logger
    log = get_logger(__name__)

Level is controlled at runtime via:
    ELI_LOG_LEVEL=DEBUG   (default: DEBUG — all diagnostic output)
    ELI_LOG_LEVEL=INFO    — startup/state changes only
    ELI_LOG_LEVEL=WARNING — warnings and errors only
    ELI_LOG_LEVEL=ERROR   — errors only

Set ELI_LOG_LEVEL=WARNING in production to silence diagnostic chatter.
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Optional


_CONFIGURED = False
_FMT = "%(message)s"  # keep existing [TAG] prefix style intact; no extra decoration


def _configure_root() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    level_name = os.environ.get("ELI_LOG_LEVEL", "DEBUG").upper()
    level = getattr(logging, level_name, logging.DEBUG)

    root = logging.getLogger("eli")
    if root.handlers:
        return

    root.setLevel(logging.DEBUG)  # capture everything; handler filters by ELI_LOG_LEVEL

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(_FMT))
    root.addHandler(handler)

    # Suppress noisy third-party loggers
    for noisy in ("urllib3", "httpx", "httpcore", "PIL", "matplotlib"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Return an ELI-namespaced logger. Pass __name__ from the calling module."""
    _configure_root()
    if name and not name.startswith("eli"):
        name = f"eli.{name}"
    return logging.getLogger(name or "eli")
