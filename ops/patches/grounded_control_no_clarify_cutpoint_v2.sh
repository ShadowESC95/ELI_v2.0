#!/usr/bin/env bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

python3 - <<'PY'
from pathlib import Path

p = Path("eli/kernel/engine.py")
src = p.read_text(encoding="utf-8")

marker = "ELI_GROUNDED_CONTROL_NO_CLARIFY_CUTPOINT_V2"
if marker in src:
    print("[PATCH] grounded-control no-clarify cutpoint v2 already installed")
    raise SystemExit(0)

old = '''        if best_score < threshold and profile.get(
            'clarify', True):
            print(
    f'[COGNITIVE][FINAL] clarify score={
        best_score:.2f} threshold={
            threshold:.2f}')

            return {'response': self._clarifying_response(
                user_input,
                best_score,
                threshold,
                memory_context=working_context,
                evidence=evidence,
                reasoning_mode=reasoning_mode,
            ), 'score': best_score, 'threshold': threshold, 'evidence': evidence, 'clarified': True}

'''

new = '''        if best_score < threshold and profile.get(
            'clarify', True):
            # ELI_GROUNDED_CONTROL_NO_CLARIFY_CUTPOINT_V2
            _eli_gc_action = ""
            try:
                if isinstance(intent, dict):
                    _eli_gc_action = str(intent.get("action") or "").upper()
            except Exception:
                _eli_gc_action = ""

            _eli_gc_grounded_actions = {
                "RUNTIME_STATUS",
                "MEMORY_COUNT",
                "RECENT_MEMORY_PROCESSING",
                "SELF_REPORT_RECENT_UPDATES",
                "GUI_RUNTIME_AUDIT",
            }

            if _eli_gc_action in _eli_gc_grounded_actions:
                print(
                    f"[COGNITIVE][FINAL] grounded-control no-clarify v2 suppressed "
                    f"action={_eli_gc_action} score={best_score:.2f} threshold={threshold:.2f}",
                    flush=True,
                )
                return {
                    'response': best_answer,
                    'score': best_score,
                    'threshold': threshold,
                    'evidence': evidence,
                    'clarified': False,
                    'clarify_suppressed': True,
                }

            print(
                f'[COGNITIVE][FINAL] clarify score={best_score:.2f} threshold={threshold:.2f}'
            )

            return {'response': self._clarifying_response(
                user_input,
                best_score,
                threshold,
                memory_context=working_context,
                evidence=evidence,
                reasoning_mode=reasoning_mode,
            ), 'score': best_score, 'threshold': threshold, 'evidence': evidence, 'clarified': True}

'''

if old not in src:
    raise SystemExit("ERROR: exact clarification block not found; refusing unsafe patch")

src = src.replace(old, new, 1)
p.write_text(src, encoding="utf-8")

print("[PATCH] installed grounded-control no-clarify cutpoint v2")
PY
