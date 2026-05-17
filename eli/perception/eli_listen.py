from __future__ import annotations

import shutil
import subprocess
from typing import Optional


def _run_clipboard(cmd: list[str], text: str) -> bool:
    try:
        p = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        p.communicate(text)
        return p.returncode == 0
    except Exception:
        return False


def copy_to_clipboard(text: str) -> bool:
    text = "" if text is None else str(text)

    if shutil.which("wl-copy"):
        return _run_clipboard(["wl-copy"], text)

    if shutil.which("xclip"):
        return _run_clipboard(["xclip", "-selection", "clipboard"], text)

    if shutil.which("xsel"):
        return _run_clipboard(["xsel", "--clipboard", "--input"], text)

    if shutil.which("pbcopy"):
        return _run_clipboard(["pbcopy"], text)

    if shutil.which("clip.exe"):
        return _run_clipboard(["clip.exe"], text)

    return False


def clip_set(text: str) -> bool:
    return copy_to_clipboard(text)


__all__ = ["copy_to_clipboard", "clip_set"]
