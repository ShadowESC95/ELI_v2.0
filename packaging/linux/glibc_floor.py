#!/usr/bin/env python3
"""The oldest glibc a built Linux bundle starts on.

A Linux binary needs a glibc at least as new as the one it was built against (built on
Ubuntu 24.04: 2.39). This reads that number out of a bundle's binaries.

    glibc_floor.py DIR              print the floor, e.g. 2.39
    glibc_floor.py DIR --max 2.39   also exit 1 when the bundle needs something newer

Linux only; needs readelf (binutils). Exit 2 when it cannot measure.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys

_NEEDS = re.compile(r"Name: GLIBC_(\d+)\.(\d+)")


def parse(text: str) -> tuple[int, int]:
    return tuple(int(part) for part in text.strip().split(".")[:2])  # type: ignore[return-value]


def needed_by(path: str) -> tuple[int, int] | None:
    """Highest GLIBC version this file asks the host for, or None when it asks for none."""
    out = subprocess.run(["readelf", "-V", "--wide", path], capture_output=True, text=True).stdout
    # needs only: a library that defines GLIBC_x.y is not asking for it
    start = out.find("Version needs section")
    if start < 0:
        return None
    found = [(int(a), int(b)) for a, b in _NEEDS.findall(out[start:])]
    return max(found) if found else None


def floor_of(root: str) -> tuple[tuple[int, int] | None, dict[str, tuple[int, int]]]:
    needs: dict[str, tuple[int, int]] = {}
    for folder, _dirs, files in os.walk(root):
        for name in files:
            path = os.path.join(folder, name)
            if os.path.islink(path):
                continue
            try:
                with open(path, "rb") as handle:
                    if handle.read(4) != b"\x7fELF":
                        continue
            except OSError:
                continue
            version = needed_by(path)
            if version:
                needs[os.path.relpath(path, root)] = version
    return (max(needs.values()) if needs else None), needs


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv else 2
    root = argv[0]
    limit = parse(argv[argv.index("--max") + 1]) if "--max" in argv else None
    if not os.path.isdir(root):
        print(f"glibc_floor: {root} is not a folder", file=sys.stderr)
        return 2
    if not shutil.which("readelf"):
        print("glibc_floor: readelf not found (install binutils)", file=sys.stderr)
        return 2
    floor, needs = floor_of(root)
    if floor is None:
        print("glibc_floor: no binary under this folder asks for a glibc version", file=sys.stderr)
        return 2
    print("%d.%d" % floor)
    if limit and floor > limit:
        over = sorted(path for path, version in needs.items() if version > limit)
        print("glibc_floor: this bundle needs glibc %d.%d; the declared floor is %d.%d. "
              "%d file(s) ask for more than that:" % (*floor, *limit, len(over)), file=sys.stderr)
        for path in over[:20]:
            print("  %s (GLIBC_%d.%d)" % (path, *needs[path]), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
