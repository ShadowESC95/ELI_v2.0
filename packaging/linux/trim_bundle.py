#!/usr/bin/env python3
"""Take GTK and GLib's I/O library out of a built Linux bundle.

Qt's GTK theme plug-in and its GLib network plug-in bring the build machine's GTK and GLib I/O
library into the process. Each of those then loads its own plug-ins from the user's system
(gvfs, dconf, input methods), which are built for that system's GLib and not for the one the
bundle carries. On a system newer than the build machine every one fails, on every start:

    /usr/lib/x86_64-linux-gnu/gvfs/libgvfscommon.so: undefined symbol: g_variant_builder_init_static
    Failed to load module: /usr/lib/x86_64-linux-gnu/gio/modules/libgvfsdbus.so

and the file dialog loses network places and phones. ELI draws its own widgets. Without the
theme plug-in a file dialog is the desktop's own, asked for through its portal (the frozen entry
point asks for that), or Qt's where there is no portal.

    trim_bundle.py DIR      remove the two plug-ins and every library only they needed
    trim_bundle.py --check DIR
                            exit 1 when DIR still holds one of the plug-ins
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys

LOADS_THE_SYSTEMS_PLUGINS = ("platformthemes/libqgtk3.so", "networkinformation/libqglib.so")


def _needed(path: str) -> list:
    out = subprocess.run(["readelf", "-d", path], capture_output=True, text=True).stdout
    return re.findall(r"\(NEEDED\).*\[(.+?)\]", out)


def only_needed_by(gone: set, needs: dict) -> set:
    """`gone` and every file that only files in it need, by NEEDED entry, to the end of the
    chain. `needs` maps each file to the library names it needs. A library nothing names (one
    opened by name at run time, like Python's own) is never added."""
    gone = set(gone)
    while True:
        users: dict = {}
        for path, sonames in needs.items():
            for soname in sonames:
                users.setdefault(soname, set()).add(path)
        more = {path for path in needs
                if path not in gone and users.get(os.path.basename(path))
                and users[os.path.basename(path)] <= gone}
        if not more:
            return gone
        gone |= more


def _plugins(root: str) -> list:
    return sorted(os.path.relpath(os.path.join(folder, name), root)
                  for folder, _dirs, files in os.walk(root) for name in files
                  if os.path.join(folder, name).replace(os.sep, "/").endswith(LOADS_THE_SYSTEMS_PLUGINS))


def trim(root: str) -> list:
    """Remove those plug-ins and what only they needed. Returns what was removed."""
    needs: dict = {}
    for folder, _dirs, files in os.walk(root):
        for name in files:
            path = os.path.join(folder, name)
            if not os.path.islink(path) and (".so" in name or os.access(path, os.X_OK)):
                needs[os.path.relpath(path, root)] = _needed(path)
    names = {os.path.basename(path) for path in only_needed_by(set(_plugins(root)), needs)}
    removed = []
    for folder, _dirs, files in os.walk(root):
        for name in files:
            if name in names:                      # the file, and any link to it by the same name
                os.remove(os.path.join(folder, name))
                removed.append(os.path.relpath(os.path.join(folder, name), root))
    return sorted(removed)


def main(argv: list) -> int:
    check = argv[:1] == ["--check"]
    if len(argv) != (2 if check else 1):
        print(__doc__)
        return 2
    root = argv[-1]
    if not os.path.isdir(root):
        print(f"trim_bundle: {root} is not a folder", file=sys.stderr)
        return 2
    if check:
        left = _plugins(root)
        for path in left:
            print(f"trim_bundle: the bundle still carries {path}", file=sys.stderr)
        return 1 if left else 0
    if not shutil.which("readelf"):
        print("trim_bundle: readelf not found (install binutils)", file=sys.stderr)
        return 2
    removed = trim(root)
    print(f"trim_bundle: removed {len(removed)} files that only the GTK and GLib I/O plug-ins needed"
          + (": " + ", ".join(removed) if removed else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
