"""
Compatibility shim:
Your systemd unit calls: python -m eli_tools.jobq worker ...
But the repo currently contains jobqueue.py / jobqueue_cli.py, not jobq.py.
This shim forwards to the existing implementation.
"""
from __future__ import annotations

import sys

def main(argv=None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    # Prefer jobqueue_cli if it exposes main()
    try:
        from eli.planning import jobqueue_cli
        if hasattr(jobqueue_cli, "main"):
            return int(jobqueue_cli.main(argv) or 0)
    except Exception:
        pass

    # Fallback: run worker directly from jobqueue.py if available
    try:
        from eli.planning import jobqueue
        if len(argv) >= 1 and argv[0] == "worker":
            # Pass through args; jobqueue.worker should parse internally or accept kwargs
            if hasattr(jobqueue, "cli_main"):
                return int(jobqueue.cli_main(argv) or 0)
            if hasattr(jobqueue, "worker_main"):
                return int(jobqueue.worker_main(argv[1:]) or 0)
    except Exception as e:
        print(f"[jobq shim] failed to dispatch: {e}", file=sys.stderr)

    print("[jobq shim] No compatible jobqueue CLI entrypoint found.", file=sys.stderr)
    return 2

if __name__ == "__main__":
    raise SystemExit(main())
