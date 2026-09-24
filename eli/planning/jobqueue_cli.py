"""Durable background jobs that run as separate processes and survive a restart.

    eli-jobs submit --cmd "python3 script.py"    queue a command, prints its id
    eli-jobs worker [--once]                     run queued jobs (keep this running)
    eli-jobs list [--status queued|running|done|failed]
    eli-jobs get --id N
"""
from __future__ import annotations

import argparse
import json
import shlex
import sys

from eli.planning.jobqueue import get_job, list_jobs, run_worker, submit


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="eli-jobs", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    p1 = sub.add_parser("submit")
    p1.add_argument("--cmd", required=True, help='command string, e.g. "python3 script.py --flag"')
    p1.add_argument("--cwd", default=".")
    p1.add_argument("--timeout", type=int, default=3600)
    p1.add_argument("--meta", default="{}", help="json dict string")

    p2 = sub.add_parser("list")
    p2.add_argument("--limit", type=int, default=20)
    p2.add_argument("--status", default="")

    p3 = sub.add_parser("get")
    p3.add_argument("--id", type=int, required=True)

    p4 = sub.add_parser("worker")
    p4.add_argument("--once", action="store_true", help="exit when the queue is empty")
    p4.add_argument("--poll", type=float, default=0.5)

    args = ap.parse_args(argv)

    if args.command == "submit":
        print(submit(shlex.split(args.cmd), cwd=args.cwd, timeout_s=args.timeout,
                     meta=json.loads(args.meta)))
    elif args.command == "list":
        print(json.dumps(list_jobs(limit=args.limit, status=(args.status or None)), indent=2))
    elif args.command == "get":
        job = get_job(args.id)
        if job is None:
            print(f"no job {args.id}", file=sys.stderr)
            return 1
        print(json.dumps(job, indent=2))
    elif args.command == "worker":
        run_worker(poll_s=args.poll, once=args.once)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
