"""Entry: python -m eli.setup [--wizard] [--launch] [--status]"""
from __future__ import annotations

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="ELI v2.0 setup wizard and status checks")
    parser.add_argument("--wizard", action="store_true", help="Open the graphical setup wizard")
    parser.add_argument("--launch", action="store_true", help="Launch ELI after wizard completes")
    parser.add_argument("--status", action="store_true", help="Print setup stage status and exit")
    parser.add_argument("--run-remaining", action="store_true", help="Run wizard for incomplete stages")
    args = parser.parse_args()

    if args.status:
        from eli.setup.status import main as status_main
        return status_main()

    if args.wizard or args.run_remaining or not any((args.status,)):
        from eli.setup.wizard import run_wizard
        return run_wizard(auto_run=args.run_remaining, launch_after=args.launch)

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
