#!/usr/bin/env python3
"""ELI Validation Sweep — one command for "the whole lot".

Runs, in order, and reports a single PASS/FAIL:
  1. Behavioural eval board   (tools/eval/run_eval.py) — routing + (optional) engine
     cases, including the LOCAL rubric judge on the engine cases.
  2. Full pytest suite        (tools/run_test_report.py) — every test + a report.

Artifacts written:
  artifacts/eval/engine_eval_results.json · history/<ts>.json · trend.jsonl · regressions.json
  artifacts/test_report.md

Usage:
  python tools/validate.py                 # router eval + full suite (fast, no model)
  python tools/validate.py --engine        # + engine cases + rubric judge (needs a model)
  python tools/validate.py --smoke         # eval smoke subset + full suite
  python tools/validate.py --no-suite       # eval only

Exit code is non-zero if ANY stage fails — wire it into CI / pre-release.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_G, _R, _B, _X = "\033[32m", "\033[31m", "\033[34m", "\033[0m"

# Model/runtime env overrides (e.g. a hand-picked eval model) must NOT leak into the
# pytest suite — the suite asserts DEFAULT/configured behaviour (model tier, settings,
# paths), so a model override makes it false-fail. The eval keeps the env; the suite
# runs with these stripped.
_MODEL_ENV = (
    "ELI_MODEL_PATH", "ELI_GGUF_MODEL_PATH", "ELI_MODEL", "ELI_CUSTOM_MODEL_PATH",
    "ELI_BUNDLED_MODEL_PATH", "ELI_MODEL_TIER", "ELI_MODEL_THINK",
    "ELI_N_CTX", "ELI_GGUF_N_CTX", "ELI_N_GPU_LAYERS", "ELI_GGUF_N_GPU_LAYERS",
    "ELI_BATCH_SIZE", "ELI_GGUF_N_BATCH",
)


def _run(label: str, cmd: list[str], *, clean_model_env: bool = False) -> bool:
    print(f"\n{_B}━━ {label} ━━{_X}\n  $ {' '.join(cmd)}")
    env = None
    if clean_model_env:
        env = {k: v for k, v in os.environ.items() if k not in _MODEL_ENV}
    t = time.perf_counter()
    rc = subprocess.run(cmd, cwd=str(_REPO), env=env).returncode
    dt = time.perf_counter() - t
    tag = f"{_G}PASS{_X}" if rc == 0 else f"{_R}FAIL (rc={rc}){_X}"
    print(f"  → {tag}  ({dt:.0f}s)")
    return rc == 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ELI Validation Sweep")
    ap.add_argument("--engine", action="store_true",
                    help="include engine cases + rubric judge (needs a loaded model; slow)")
    ap.add_argument("--smoke", action="store_true",
                    help="eval smoke subset (router board + a few quick engine cases)")
    ap.add_argument("--no-suite", action="store_true", help="skip the pytest suite")
    args = ap.parse_args(argv)

    py = sys.executable
    eval_cmd = [py, "tools/eval/run_eval.py", "--history",
                "--json", "artifacts/eval/engine_eval_results.json"]
    if args.smoke:
        eval_cmd.append("--smoke")
    elif args.engine:
        eval_cmd += ["--target", "all"]
    # else: default target=router (fast, model-free)

    # Suite first (fast, fail-fast on code regressions) before the slow engine eval.
    results: list[tuple[str, bool]] = []
    if not args.no_suite:
        results.append(("Full test suite",
                        _run("1/2  Full test suite", [py, "tools/run_test_report.py", "tests/"],
                             clean_model_env=True)))
    results.append(("Eval board" + (" + judge" if args.engine or args.smoke else " (router)"),
                    _run("2/2  Eval board", eval_cmd)))

    print(f"\n{_B}━━ Validation Sweep summary ━━{_X}")
    ok_all = True
    for name, ok in results:
        ok_all = ok_all and ok
        print(f"  {(_G + 'PASS' + _X) if ok else (_R + 'FAIL' + _X)}  {name}")
    print(f"\n  {'ALL GREEN' if ok_all else 'FAILURES ABOVE'}\n")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
