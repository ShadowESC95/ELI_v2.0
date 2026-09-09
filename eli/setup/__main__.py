"""Entry: python -m eli.setup [--wizard] [--launch] [--status] [--full-install]"""
from __future__ import annotations

import argparse
import sys


def _has_venv() -> bool:
    try:
        from eli.setup.status import has_venv
        return has_venv()
    except Exception:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="ELI v2.0 setup wizard and status checks")
    parser.add_argument("--wizard", action="store_true", help="Open the graphical setup wizard")
    parser.add_argument("--launch", action="store_true", help="Launch ELI after wizard completes")
    parser.add_argument("--status", action="store_true", help="Print setup stage status and exit")
    parser.add_argument("--run-remaining", action="store_true", help="Run wizard for incomplete stages")
    parser.add_argument(
        "--full-install",
        action="store_true",
        help="One-click GUI installer (install.sh + assets + launch)",
    )
    args = parser.parse_args()

    if args.status:
        from eli.setup.status import main as status_main
        return status_main()

    if args.full_install:
        from eli.setup.unified_installer import run_unified_installer
        return run_unified_installer(launch_after=args.launch)

    if args.wizard or args.run_remaining or not any((args.status, args.full_install)):
        from eli.setup.unified_installer import gui_install_available, run_unified_installer
        from eli.setup.wizard import run_wizard
        if gui_install_available():
            return run_unified_installer(launch_after=args.launch)
        return run_wizard(auto_run=args.run_remaining, launch_after=args.launch)

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
