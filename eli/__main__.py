"""Console entry point. `python -m eli` and the `eli` script both call this.

Flags:
  --headless, -H   Run as a terminal REPL without any GUI.  Useful for
                   scripting, servers, and headless environments.
  --trust-agent <path> [--force]
                   Register a custom agent file as trusted (adds its SHA-256
                   hash to config/trusted_agents.json) then exit.
  --license, --licence
                   Print the PolyForm Internal Use terms ELI ships under, then
                   exit. Same command in every download.
"""
from __future__ import annotations
import sys


def main() -> int:
    args = sys.argv[1:]

    # ── Licence ───────────────────────────────────────────────────────────────
    # Before anything is imported or initialised: asking for the terms must work
    # on a broken install too.
    if "--license" in args or "--licence" in args:
        from eli.runtime.license_info import print_license
        return print_license()

    # ── Trust-agent utility ───────────────────────────────────────────────────
    if "--trust-agent" in args:
        idx = args.index("--trust-agent")
        if idx + 1 < len(args):
            from pathlib import Path
            from eli.cognition import agent_trust
            target = Path(args[idx + 1]).expanduser().resolve()
            if not target.exists():
                print(f"Error: file not found: {target}", file=sys.stderr)
                return 1
            # Goes through agent_trust so the CLI and the GUI write the SAME
            # provenance-carrying grant. It also scans first: approving code
            # without looking at it is what the old path did.
            force = "--force" in args
            result = agent_trust.grant(target, approved_by="cli", force=force)
            if not result.get("ok"):
                print(f"Refused to approve {target.name}:", file=sys.stderr)
                for problem in result.get("problems", []):
                    print(f"  - {problem}", file=sys.stderr)
                print("\nRe-run with --force if you wrote this code and understand "
                      "the findings.", file=sys.stderr)
                return 1
            scan = result.get("scan") or {}
            print(result.get("response", f"{target.name} approved."))
            print(f"  scan: {scan.get('verdict', '?')} (score {scan.get('score', 0)}/100)"
                  + ("" if scan.get("complete") else " — coverage partial"))
            return 0
        else:
            print("Error: --trust-agent requires a file path argument", file=sys.stderr)
            return 1

    # ── First-run/boot DB + machine-inventory bootstrap (idempotent) ─────────
    # Ensures the full schema exists and the app index is populated even when ELI
    # was not launched via install.sh (copied tree / portable bundle / bare run).
    try:
        from eli.core.init_data import bootstrap_once
        bootstrap_once()
    except Exception:
        import logging
        logging.getLogger("eli.boot").debug("boot bootstrap skipped", exc_info=True)

    # ── Headless REPL ────────────────────────────────────────────────────────
    if "--headless" in args or "-H" in args:
        from eli.cli.headless import run_headless
        return int(run_headless() or 0)

    # ── GUI (default) ────────────────────────────────────────────────────────
    from eli.gui.app import main as _gui_main
    return int(_gui_main() or 0)


if __name__ == "__main__":
    raise SystemExit(main())
