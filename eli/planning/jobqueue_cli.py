from __future__ import annotations
import argparse, json, shlex
from eli.planning.jobqueue import submit, list_jobs, get_job

def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("submit")
    p1.add_argument("--cmd", required=True, help='command string, e.g. "python3 -m eli_tools.sweep_cli ..."')
    p1.add_argument("--cwd", default=".")
    p1.add_argument("--timeout", type=int, default=3600)
    p1.add_argument("--meta", default="{}", help="json dict string")

    p2 = sub.add_parser("list")
    p2.add_argument("--limit", type=int, default=20)
    p2.add_argument("--status", default="")

    p3 = sub.add_parser("get")
    p3.add_argument("--id", type=int, required=True)

    args = ap.parse_args()

    if args.cmd == "submit":
        argv = shlex.split(args.cmd)
        meta = json.loads(args.meta)
        jid = submit(argv, cwd=args.cwd, timeout_s=args.timeout, meta=meta)
        print(jid)
        return

    if args.cmd == "list":
        rows = list_jobs(limit=args.limit, status=(args.status or None))
        print(json.dumps(rows, indent=2))
        return

    if args.cmd == "get":
        j = get_job(args.id)
        print(json.dumps(j, indent=2))
        return

if __name__ == "__main__":
    main()
