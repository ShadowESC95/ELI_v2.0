#!/usr/bin/env python3
"""Locate and print ELI's licence, wherever ELI happens to be running from.

ELI is source-available under PolyForm Internal Use 1.0.0, so every artifact has
to be able to put the terms in front of the user — not just the Windows
installer, which is the only wrapper with a licence pane of its own. This module
is the one place that knows where `LICENSE` lives in each shape ELI ships in:

  * frozen bundle (exe / zip / dmg / AppImage) — `sys._MEIPASS/LICENSE`, put
    there by ELI.spec's data manifest
  * source tree / portable tarball          — `<repo root>/LICENSE`

Both entry points expose it as `--license`, so the command is identical on every
platform and in every download.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

# Companion files worth naming when someone asks about terms.
_COMPANIONS = ("NOTICE", "THIRD_PARTY_NOTICES.md", "models/MODEL_LICENSES.md")

SUMMARY = (
    "ELI v2.0 — source-available under the PolyForm Internal Use License 1.0.0.\n"
    "Copyright (c) 2026 Jason Fitzgibbon Bridgeman. All rights reserved.\n"
    "\n"
    "You may run and modify ELI for your own personal or internal use.\n"
    "You may NOT redistribute, publish, host for others, sublicense or sell it.\n"
)


def _roots() -> tuple[Path, ...]:
    """Every directory that could hold the licence, most specific first."""
    roots: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:  # PyInstaller one-dir/one-file bundle
        roots.append(Path(meipass))
    exe_dir = Path(sys.executable).resolve().parent
    roots.append(exe_dir)
    # …/ELI.app/Contents/MacOS/ELI -> the bundle's Resources
    roots.append(exe_dir.parent / "Resources")
    # source checkout: eli/runtime/license_info.py -> repo root
    roots.append(Path(__file__).resolve().parent.parent.parent)
    roots.append(Path.cwd())
    seen: list[Path] = []
    for r in roots:
        if r not in seen:
            seen.append(r)
    return tuple(seen)


def license_path() -> Optional[Path]:
    """Full path to the LICENSE that ships with this build, or None."""
    for root in _roots():
        candidate = root / "LICENSE"
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def license_text() -> str:
    """The full licence text, or the summary if the file didn't ship."""
    path = license_path()
    if path is None:
        return (
            SUMMARY
            + "\nThe full LICENSE file was not found next to this build.\n"
              "Read it at https://github.com/ShadowESC95/ELI_v2.0/blob/main/LICENSE\n"
        )
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return SUMMARY


def print_license() -> int:
    """Print the licence plus pointers to the third-party notices. Never raises."""
    try:
        sys.stdout.write(license_text().rstrip() + "\n")
        path = license_path()
        if path is not None:
            sys.stdout.write(f"\nThis copy: {path}\n")
            extra = [n for n in _COMPANIONS if (path.parent / n).is_file()]
            if extra:
                sys.stdout.write(
                    "Third-party components and model/voice terms: "
                    + ", ".join(extra) + "\n"
                )
    except Exception:  # a licence print must never take the process down
        try:
            sys.stdout.write(SUMMARY)
        except Exception:
            pass
    return 0
