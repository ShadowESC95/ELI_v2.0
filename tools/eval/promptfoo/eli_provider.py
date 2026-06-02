"""promptfoo custom provider for ELI.

Thin adapter over the SAME driver the pure-Python harness uses (tools/eval/
eli_driver). promptfoo calls `call_api`; we run the prompt through ELI's real
pipeline and return the answer + metadata (action / grounding / response_mode /
latency) so you can assert on routing & grounding, not just text.

Wire it up in promptfooconfig.yaml:
    providers:
      - id: 'python:eli_provider.py'
        label: 'ELI (loaded model)'

Per-test network state via vars:  vars: { network: 'off' }
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Put the repo root on sys.path so `tools.eval.eli_driver` imports.
_REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO))
os.environ.setdefault("ELI_HEADLESS", "1")
os.environ.setdefault("ELI_NO_GUI", "1")


def call_api(prompt, options, context):
    from tools.eval import eli_driver as D
    cfg = (options or {}).get("config", {}) or {}
    vars_ = (context or {}).get("vars", {}) or {}

    net = vars_.get("network", cfg.get("network"))
    network = None if net is None else str(net).lower() in ("on", "true", "1", "yes")
    mode = str(vars_.get("mode", cfg.get("mode", "quick")))

    res = D.run_engine(prompt, network=network, reasoning_mode=mode)
    return {
        "output": res.get("text", ""),
        "metadata": {
            "action": res.get("action"),
            "matched_by": res.get("matched_by"),
            "grounding": res.get("grounding"),
            "response_mode": res.get("response_mode"),
            "latency_s": res.get("latency_s"),
            "skipped": res.get("skipped", False),
        },
    }
