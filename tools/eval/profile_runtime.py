#!/usr/bin/env python3
"""Runtime-graph profiler — what ELI ACTUALLY executes.

Replays real turns (artifacts/conversations/*.json + eval cases.yaml) through
ELI and measures, with NO external dependency (uses sys.settrace):

  • exact executed-line set per eli/ file  → % of (AST) statement lines hit
  • per-module hot/cold heatmap (by package + per file), ranked by hit-count
  • which of the ~160 executor actions ever ROUTE       (action coverage)
  • which of the 14 bus agents ever FIRE                (agent coverage; --agents/--engine)

Modes (cost vs completeness):
  --mode route   (default) per turn → router.route()        fast, no model
  --mode agents            + AgentBus.dispatch()            offline, ~no model
  --mode engine            full CognitiveEngine.process()   needs a model (slow) → use --limit

The route-mode heatmap is the ROUTING-layer graph; engine-mode is the full
pipeline graph. Read each per its mode.

Usage:
  python tools/eval/profile_runtime.py                       # route, all convos+cases
  python tools/eval/profile_runtime.py --mode agents --limit 300
  python tools/eval/profile_runtime.py --mode engine --limit 20   # needs a model
  python tools/eval/profile_runtime.py --json profile.json
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import sys
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO))
os.environ.setdefault("ELI_HEADLESS", "1")
os.environ.setdefault("ELI_NO_GUI", "1")

_ELI_DIR = (_REPO / "eli").resolve()

# ── line tracer (dependency-free) ──────────────────────────────────────────
_hits: "defaultdict[str, Counter]" = defaultdict(Counter)   # file → {lineno: count}
_tracing = False


def _tracer(frame, event, arg):
    if event == "line":
        fn = frame.f_code.co_filename
        if fn.startswith(str(_ELI_DIR)):
            _hits[fn][frame.f_lineno] += 1
    return _tracer


def _start_trace():
    global _tracing
    _tracing = True
    threading.settrace(_tracer)
    sys.settrace(_tracer)


def _stop_trace():
    global _tracing
    sys.settrace(None)
    threading.settrace(None)
    _tracing = False


# ── universes (denominators) ────────────────────────────────────────────────
def _executable_lines(path: Path) -> set:
    """AST statement linenos — a fair 'could-execute' denominator."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.stmt):
            out.add(node.lineno)
    return out


def _action_universe() -> set:
    import re
    src = (_ELI_DIR / "execution" / "executor_enhanced.py").read_text(encoding="utf-8")
    acts = set(re.findall(r'a == "([A-Z_]+)"', src))
    for grp in re.findall(r'a in \(([^)]+)\)', src):
        acts.update(re.findall(r'"([A-Z_]+)"', grp))
    return acts


def _agent_universe() -> list:
    import eli.cognition.agent_bus as B
    return [getattr(a, "name", "?") for a in B._ALL_AGENTS]


# ── turn corpus ─────────────────────────────────────────────────────────────
def _load_turns(limit: int = 0):
    turns = []
    conv_dir = _REPO / "artifacts" / "conversations"
    for f in sorted(conv_dir.glob("*.json")) if conv_dir.is_dir() else []:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        for m in (d.get("messages") or []):
            if m.get("role") == "user":
                t = str(m.get("content") or "").strip()
                if t:
                    turns.append(t)
    # eval cases too
    try:
        import yaml
        cases = yaml.safe_load((Path(__file__).with_name("cases.yaml")).read_text())
        for c in (cases or []):
            if c.get("prompt"):
                turns.append(str(c["prompt"]))
    except Exception:
        pass
    if limit and limit > 0:
        turns = turns[:limit]
    return turns


# ── run ─────────────────────────────────────────────────────────────────────
def _run(turns, mode):
    from tools.eval import eli_driver as D
    actions = Counter()
    agents = Counter()
    errors = 0
    _start_trace()
    t0 = time.perf_counter()
    for t in turns:
        try:
            if mode == "route":
                r = D.route_only(t)
                actions[r.get("action") or "?"] += 1
            elif mode == "agents":
                r = D.route_only(t)
                actions[r.get("action") or "?"] += 1
                try:
                    from eli.cognition.agent_bus import get_bus
                    res = get_bus().dispatch(t, r.get("raw") or {"action": r.get("action")})
                    for a in (getattr(res, "agents_used", []) or []):
                        agents[a] += 1
                except Exception:
                    errors += 1
            else:  # engine
                r = D.run_engine(t)
                if not r.get("skipped"):
                    actions[r.get("action") or "?"] += 1
        except Exception:
            errors += 1
    elapsed = time.perf_counter() - t0
    _stop_trace()
    return actions, agents, errors, elapsed


# ── analyse ───────────────────────────────────────────────────────────────--
def _analyse():
    per_file = {}
    pkg = defaultdict(lambda: [0, 0, 0])   # pkg → [hit_lines, exec_lines, hit_count]
    for py in _ELI_DIR.rglob("*.py"):
        execset = _executable_lines(py)
        if not execset:
            continue
        hit = _hits.get(str(py.resolve()), Counter())
        hit_lines = len(set(hit) & execset)
        total_hits = sum(hit.values())
        rel = py.relative_to(_REPO)
        per_file[str(rel)] = {
            "exec_lines": len(execset),
            "hit_lines": hit_lines,
            "pct": round(100.0 * hit_lines / len(execset), 1) if execset else 0.0,
            "hit_count": total_hits,
        }
        top = rel.parts[1] if len(rel.parts) > 1 else rel.parts[0]
        pkg[top][0] += hit_lines
        pkg[top][1] += len(execset)
        pkg[top][2] += total_hits
    return per_file, pkg


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["route", "agents", "engine"], default="route")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--json", default="")
    args = ap.parse_args(argv)

    turns = _load_turns(args.limit)
    print(f"\n  RUNTIME PROFILE  ·  mode={args.mode}  ·  turns={len(turns)}")
    print("  " + "─" * 56)
    actions, agents, errors, elapsed = _run(turns, args.mode)
    per_file, pkg = _analyse()

    tot_hit = sum(v[0] for v in pkg.values())
    tot_exec = sum(v[1] for v in pkg.values())
    print(f"  eli/ line coverage (mode={args.mode}): "
          f"{tot_hit}/{tot_exec}  ({100.0*tot_hit/max(tot_exec,1):.1f}%)   "
          f"[{elapsed:.1f}s, {errors} errs]\n")

    # actions
    universe = _action_universe()
    fired = set(a for a in actions if a and a != "?")
    print(f"  ACTIONS routed: {len(fired)} distinct  (executor knows ~{len(universe)})")
    for a, n in actions.most_common(12):
        print(f"      {n:5d}  {a}")
    print()

    # agents
    if args.mode in ("agents", "engine") and agents:
        roster = _agent_universe()
        fired_a = set(agents)
        print(f"  AGENTS fired: {len(fired_a)} of {len(roster)}")
        for a in roster:
            mark = "✓" if a in fired_a else "·"
            print(f"      {mark} {a:18s} {agents.get(a,0)}")
        print()

    # heatmap by package
    print("  MODULE HEATMAP (package · % stmt-lines hit · total line-hits):")
    rows = sorted(pkg.items(), key=lambda kv: kv[1][2], reverse=True)
    for name, (h, e, c) in rows:
        pct = 100.0 * h / max(e, 1)
        band = "HOT " if pct >= 40 else ("WARM" if pct >= 10 else "COLD")
        bar = "█" * int(pct / 5)
        print(f"      [{band}] eli/{name:14s} {pct:5.1f}%  hits={c:<7d} {bar}")
    print()

    # cold files (0% hit) — refactor/cut candidates, biggest first
    cold = [(f, d) for f, d in per_file.items() if d["hit_lines"] == 0]
    cold.sort(key=lambda fd: fd[1]["exec_lines"], reverse=True)
    print(f"  COLD files (0 lines hit this run): {len(cold)} — largest 12:")
    for f, d in cold[:12]:
        print(f"      {d['exec_lines']:5d} stmt  {f}")

    if args.json:
        Path(args.json).write_text(json.dumps({
            "mode": args.mode, "turns": len(turns), "elapsed_s": elapsed,
            "coverage_pct": round(100.0*tot_hit/max(tot_exec,1), 2),
            "actions": dict(actions), "agents": dict(agents),
            "packages": {k: {"hit": v[0], "exec": v[1], "hits": v[2]} for k, v in pkg.items()},
            "files": per_file,
        }, indent=2), encoding="utf-8")
        print(f"\n  wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
