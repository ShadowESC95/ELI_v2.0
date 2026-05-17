#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from eli.core.portable_paths import PROJECT_ROOT, resolve_path_value


SETTINGS = PROJECT_ROOT / "config/settings.json"
EXAMPLE = PROJECT_ROOT / "config/settings.example.json"


PATH_HINTS = ("path", "dir", "file", "folder", "home", "root", "model")


def materialize(obj):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(k, str) and any(h in k.lower() for h in PATH_HINTS) and isinstance(v, str):
                out[k] = resolve_path_value(v)
            else:
                out[k] = materialize(v)
        return out
    if isinstance(obj, list):
        return [materialize(x) for x in obj]
    return obj


def main() -> int:
    src = EXAMPLE if EXAMPLE.exists() else SETTINGS
    if not src.exists():
        raise SystemExit("No config/settings.json or config/settings.example.json found.")

    data = json.loads(src.read_text(encoding="utf-8"))
    data = materialize(data)

    SETTINGS.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote portable local settings: {SETTINGS}")
    print(f"Project root: {PROJECT_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
