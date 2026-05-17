"""Console entry point. `python -m eli` and the `eli` script both call this."""
from __future__ import annotations


def main() -> int:
    from eli.gui.app import main as _gui_main
    return int(_gui_main() or 0)


if __name__ == "__main__":
    raise SystemExit(main())
