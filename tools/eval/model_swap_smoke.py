#!/usr/bin/env python3
"""Model-swap smoke test — the one-command "did the new model break anything?" check.

The model-free pytest eval (`tests/test_eval_cases.py`) can't see the model. This
runs ELI's REAL engine with whatever GGUF is currently configured and checks the
things that actually break when you swap a model:

  • it loads + answers at all (no crash, no empty reply)
  • no degenerate output (the lone "-"/"-G" fragments a weak/mis-templated model
    produces — also catches a wrong chat template after a swap)
  • grounded/deterministic actions still return real content
  • every reasoning mode (quick/normal/advanced/research/expert) runs without error

Usage:
    python tools/eval/model_swap_smoke.py
    python tools/eval/model_swap_smoke.py --json smoke.json

Exit code is non-zero if any case fails — wire it into a model-upgrade checklist.
Skips gracefully (exit 0) if no model is loadable.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault("ELI_HEADLESS", "1")

from tools.eval import eli_driver as D  # noqa: E402

_G, _R, _Y, _X = "\033[32m", "\033[31m", "\033[33m", "\033[0m"

# (id, prompt, reasoning_mode, kind) — kind: "chat" | "grounded"
_CHECKS = [
    ("greeting",      "hey, how's it going?",                         "quick",    "chat"),
    ("identity",      "who are you?",                                  "quick",    "grounded"),
    ("model_report",  "what model are you running right now?",         "quick",    "grounded"),
    ("personal_mem",  "what do you know about me?",                    "quick",    "grounded"),
    ("runtime_audit", "run a runtime audit",                          "quick",    "grounded"),
    ("explain",       "explain what a knowledge graph is, briefly",    "normal",   "chat"),
    ("advanced",      "what are the trade-offs of local vs cloud AI?", "advanced", "chat"),
    ("research",      "summarise the main risks of a solo software project", "research", "chat"),
    ("expert",        "give a careful two-paragraph take on AI privacy",    "expert",   "chat"),
]


def _is_degenerate(text: str) -> bool:
    """Reuse the engine's fragment detector when available; else a local check."""
    try:
        from eli.kernel.engine import _eli_is_fragment_output
        return bool(_eli_is_fragment_output(text))
    except Exception:
        t = (text or "").strip()
        return (len(t) < 3) or (not any(c.isalnum() for c in t))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="")
    args = ap.parse_args(argv)

    # Probe the model once.
    probe = D.run_engine("hi", reasoning_mode="quick")
    if probe.get("skipped"):
        print(f"  {_Y}SKIP{_X} no model loadable ({probe.get('reason')}) — nothing to smoke-test.")
        return 0

    print(f"\n  ELI model-swap smoke — {len(_CHECKS)} checks\n  " + "─" * 50)
    records, failed = [], 0
    for cid, prompt, mode, kind in _CHECKS:
        try:
            r = D.run_engine(prompt, reasoning_mode=mode)
        except Exception as e:
            print(f"  {_R}ERR {_X} {cid}: driver raised {e}")
            failed += 1
            records.append({"id": cid, "status": "error", "error": str(e)})
            continue

        text = str(r.get("text") or "")
        problems = []
        if r.get("error") or text.startswith("[error]"):
            problems.append(f"engine error: {text[:80]}")
        elif not text.strip():
            problems.append("empty reply")
        elif _is_degenerate(text):
            problems.append(f"degenerate output: {text[:40]!r} (often a wrong chat template after a swap)")
        if kind == "grounded" and not problems and len(text.strip()) < 15:
            problems.append("grounded action returned a near-empty answer")

        ok = not problems
        failed += 0 if ok else 1
        tag = f"{_G}PASS{_X}" if ok else f"{_R}FAIL{_X}"
        print(f"  {tag} {cid:14} [{mode:8}] ({r.get('latency_s')}s)")
        for p in problems:
            print(f"        {_R}✗ {p}{_X}")
        records.append({"id": cid, "mode": mode, "kind": kind, "status": "pass" if ok else "fail",
                        "problems": problems, "latency_s": r.get("latency_s"),
                        "preview": text[:120]})

    passed = len(_CHECKS) - failed
    print("  " + "─" * 50)
    color = _G if failed == 0 else _R
    print(f"  {color}{passed} passed  {failed} failed{_X}\n")
    if args.json:
        Path(args.json).write_text(json.dumps(records, indent=2))
        print(f"  wrote {args.json}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
