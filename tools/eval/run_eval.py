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
    if target == "executor":
        return D.run_executor(case.get("action"), case.get("args"), network=net)
    return D.run_engine(prompt, network=net, reasoning_mode=str(case.get("mode") or "quick"))


def run_board(target: str = "router", *, cases_path=None, case_filter: str = "",
              smoke: bool = False, on_case=None) -> dict:
    """Run the eval board and RETURN the results instead of printing them.

    Extracted verbatim from main() so the harness has a programmatic entry point —
    main() now calls this and does the printing. The GUI needs it in-process: the
    rubric assertions are graded by ELI's own loaded model, and running the board in
    a subprocess would load a second copy of the chat model into the same VRAM.
    """
    os.environ.setdefault("ELI_HEADLESS", "1")
    cases = _load_cases(Path(cases_path or Path(__file__).with_name("cases.yaml")))
    if case_filter:
        cases = [c for c in cases if case_filter.lower() in str(c.get("id", "")).lower()]

    want = {"router", "executor", "engine"} if target == "all" else {target}
    cases = [c for c in cases if str(c.get("target", "router")).lower() in want]

    if smoke:
        cases = [c for c in cases
                 if str(c.get("target", "router")).lower() in ("router", "executor")
                 or c.get("smoke") is True]

    passed = failed = skipped = 0
    records = []
    for c in cases:
        cid = str(c.get("id") or "?")
        if on_case is not None:
            try:
                on_case(cid, len(records), len(cases))
            except Exception:
                pass
        try:
            res = _run_case(c)
        except Exception as e:
            failed += 1
            records.append({"id": cid, "status": "error", "error": str(e),
                            "prompt": str(c.get("prompt") or "")})
            continue

        if res.get("skipped"):
            skipped += 1
            records.append({"id": cid, "status": "skip", "reason": res.get("reason"),
                            "prompt": str(c.get("prompt") or "")})
            continue

        res.setdefault("prompt", str(c.get("prompt") or ""))
        details, ok_all = [], True
        for a in (c.get("assert") or []):
            ok, detail = A.check(a, res)
            ok_all = ok_all and ok
            details.append(("\u2713" if ok else "\u2717") + " " + detail)

        passed += ok_all
        failed += (not ok_all)
        records.append({"id": cid, "status": "pass" if ok_all else "fail",
                        "prompt": str(c.get("prompt") or ""),
                        "answer": (res.get("text") or "")[:600],
                        "latency_s": res.get("latency_s"),
                        "result": {k: res.get(k) for k in
                                   ("action", "matched_by", "grounding",
                                    "response_mode", "latency_s")},
                        "checks": details})

    return {"ok": failed == 0, "target": target, "passed": passed, "failed": failed,
            "skipped": skipped, "total": len(cases), "records": records,
            "model": _loaded_model_name()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", choices=["router", "executor", "engine", "all"], default="router")
    ap.add_argument("--cases", default=str(Path(__file__).with_name("cases.yaml")))
    ap.add_argument("--filter", default="")
    ap.add_argument("--json", default="")
    ap.add_argument("--smoke", action="store_true",
                    help="fast subset: all router cases + engine cases tagged 'smoke: true'")
    ap.add_argument("--history", action="store_true",
                    help="append a timestamped record + trend line under artifacts/eval/history/ "
                         "and write artifacts/eval/regressions.json on any failure")
    args = ap.parse_args(argv)

    board = run_board(args.target, cases_path=args.cases, case_filter=args.filter,
                      smoke=args.smoke)
    records = board["records"]
    passed, failed, skipped = board["passed"], board["failed"], board["skipped"]

    print(f"\n  ELI eval — {board['total']} case(s) [{args.target}]\n  " + "\u2500" * 46)
    for rec in records:
        cid = rec["id"]
        if rec["status"] == "error":
            print(f"  {_R}ERR {_X} {cid}: driver raised {rec.get('error')}")
            continue
        if rec["status"] == "skip":
            print(f"  {_Y}SKIP{_X} {cid}  ({rec.get('reason')})")
            continue
        ok_all = rec["status"] == "pass"
        tag = f"{_G}PASS{_X}" if ok_all else f"{_R}FAIL{_X}"
        print(f"  {tag} {cid}  ({rec.get('latency_s')}s)")
        if not ok_all:
            for d in rec.get("checks") or []:
                if d.startswith("\u2717"):
                    print(f"        {_R}{d}{_X}")
            ans = (rec.get("answer") or "").replace("\n", " ")[:120]
            if ans:
                print(f"        \u21b3 answer: {ans!r}")

    print("  " + "\u2500" * 46)
    print(f"  {_G}{passed} passed{_X}  {_R}{failed} failed{_X}  {_Y}{skipped} skipped{_X}\n")
    if args.json:
        Path(args.json).write_text(json.dumps(records, indent=2), encoding="utf-8")
        print(f"  wrote {args.json}\n")
    if args.history:
        _write_history(records, args.target, passed, failed, skipped)
    return 1 if failed else 0


def _loaded_model_name() -> str:
    """The model the eval actually ran against — for per-model trend/A-B comparison."""
    try:
        from eli.core.paths import get_paths
        snap = Path(get_paths().artifacts_dir) / "runtime_snapshot.json"
        if snap.exists():
            d = json.loads(snap.read_text(encoding="utf-8"))
            return str(d.get("model_name") or Path(str(d.get("model_path") or "")).name or "")
    except Exception:
        pass
    return ""


def _write_history(records, target, passed, failed, skipped) -> None:
    """Append a timestamped run record + a one-line trend entry, and persist the
    current regressions — so quality/latency/grounding are tracked across model and
    code changes instead of a single overwritten file (P3), and overnight failures
    become an actionable list (P5). All under artifacts/eval/."""
    import datetime
    try:
        from eli.core.paths import get_paths
        evdir = Path(get_paths().artifacts_dir) / "eval"
    except Exception:
        evdir = Path("artifacts/eval")
    hist = evdir / "history"
    hist.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
    scored = [r for r in records if r.get("status") in ("pass", "fail")]

    def _mean(key):
        vals = [float(r["result"][key]) for r in scored
                if isinstance(r.get("result"), dict) and r["result"].get(key) is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    summary = {
        "ts": ts, "target": target, "model": _loaded_model_name(),
        "passed": passed, "failed": failed, "skipped": skipped,
        "pass_rate": round(passed / max(1, passed + failed), 4),
        "mean_latency_s": _mean("latency_s"), "mean_grounding": _mean("grounding"),
    }
    (hist / f"{ts}.json").write_text(
        json.dumps({"summary": summary, "records": records}, indent=2), encoding="utf-8")
    with (hist / "trend.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(summary) + "\n")

    regs = [{"id": r["id"], "checks": r.get("checks")}
            for r in records if r.get("status") == "fail"]
    (evdir / "regressions.json").write_text(
        json.dumps({"ts": ts, "target": target, "model": summary["model"],
                    "count": len(regs), "regressions": regs}, indent=2), encoding="utf-8")
    print(f"  history → {hist}/{ts}.json  ·  trend.jsonl +1  ·  "
          f"regressions.json ({len(regs)})\n")


if __name__ == "__main__":
    raise SystemExit(main())
