#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _ensure_project_on_path() -> None:
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rebuild ELI's canonical FAISS vector index.")
    parser.add_argument("--full", action="store_true", help="Accepted for GUI/backward compatibility.")
    parser.parse_args(argv)

    _ensure_project_on_path()
    from eli.memory import rebuild_vector_index_from_search_db

    result = rebuild_vector_index_from_search_db()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ok") and result.get("faiss_persisted", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
