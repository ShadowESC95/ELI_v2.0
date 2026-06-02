#!/usr/bin/env python3
"""ELI eval harness — green/red regression board, 100% local, no extra deps.

Drives ELI's real pipeline via eli_driver and asserts on its OWN telemetry
(action, matched_by, grounding, response_mode, latency) plus the answer text.

Usage:
    python tools/eval/run_eval.py                 # router cases only (fast, no model)
    python tools/eval/run_eval.py --target all    # + engine cases (needs a model)
    python tools/eval/run_eval.py --target engine
    python tools/eval/run_eval.py --filter media  # only cases whose id contains 'media'
    python tools/eval/run_eval.py --json results.json

Exit code is non-zero if any case fails — wire it into CI / pre-push.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root on path

from tools.eval import assertions as A          # noqa: E402
from tools.eval import eli_driver as D           # noqa: E402

_G, _R, _Y, _B, _X = "\033[32m", "\033[31m", "\033[33m", "\033[34m", "\033[0m"


def _load_cases(path: Path):
    import yaml
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [c for c in (data or []) if isinstance(c, dict)]


def _net(case):
    v = case.get("network")
    if v is None:
        return None
    return str(v).strip().lower() in ("on", "true", "1", "yes")


def _run_case(case):
    target = str(case.get("target") or "router").lower()
    prompt = str(case.get("prompt") or "")
    net = _net(case)
    if target == "router":
        return D.route_only(prompt, network=net)
    return D.run_engine(prompt, network=net, reasoning_mode=str(case.get("mode") or "quick"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", choices=["router", "engine", "all"], default="router")
    ap.add_argument("--cases", default=str(Path(__file__).with_name("cases.yaml")))
    ap.add_argument("--filter", default="")
    ap.add_argument("--json", default="")
    args = ap.parse_args(argv)

    os.environ.setdefault("ELI_HEADLESS", "1")
    cases = _load_cases(Path(args.cases))
    if args.filter:
        cases = [c for c in cases if args.filter.lower() in str(c.get("id", "")).lower()]

    want = {"router", "engine"} if args.target == "all" else {args.target}
    cases = [c for c in cases if str(c.get("target", "router")).lower() in want]

    passed = failed = skipped = 0
    records = []
    print(f"\n  ELI eval — {len(cases)} case(s) [{args.target}]\n  " + "─" * 46)
    for c in cases:
        cid = str(c.get("id") or "?")
        try:
            res = _run_case(c)
        except Exception as e:
            print(f"  {_R}ERR {_X} {cid}: driver raised {e}")
            failed += 1
            records.append({"id": cid, "status": "error", "error": str(e)})
            continue

        if res.get("skipped"):
            print(f"  {_Y}SKIP{_X} {cid}  ({res.get('reason')})")
            skipped += 1
            records.append({"id": cid, "status": "skip", "reason": res.get("reason")})
            continue

        details, ok_all = [], True
        for a in (c.get("assert") or []):
            ok, detail = A.check(a, res)
            ok_all = ok_all and ok
            details.append(("✓" if ok else "✗") + " " + detail)

        lat = res.get("latency_s")
        tag = f"{_G}PASS{_X}" if ok_all else f"{_R}FAIL{_X}"
        print(f"  {tag} {cid}  ({lat}s)")
        if not ok_all:
            for d in details:
                if d.startswith("✗"):
                    print(f"        {_R}{d}{_X}")
            ans = (res.get("text") or "").replace("\n", " ")[:120]
            if ans:
                print(f"        ↳ answer: {ans!r}")
        passed += ok_all
        failed += (not ok_all)
        records.append({"id": cid, "status": "pass" if ok_all else "fail",
                        "result": {k: res.get(k) for k in
                                   ("action", "matched_by", "grounding",
                                    "response_mode", "latency_s")},
                        "checks": details})

    print("  " + "─" * 46)
    print(f"  {_G}{passed} passed{_X}  {_R}{failed} failed{_X}  {_Y}{skipped} skipped{_X}\n")
    if args.json:
        Path(args.json).write_text(json.dumps(records, indent=2), encoding="utf-8")
        print(f"  wrote {args.json}\n")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
