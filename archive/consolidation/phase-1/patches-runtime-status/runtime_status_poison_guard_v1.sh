#!/usr/bin/env bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

python3 - <<'PY'
from pathlib import Path

p = Path("eli/kernel/engine.py")
src = p.read_text(encoding="utf-8")

marker = "ELI_RUNTIME_STATUS_POISON_GUARD_V1"
if marker in src:
    print("[PATCH] runtime-status poison guard v1 already installed")
    raise SystemExit(0)

old = '''                _synth = str((_loop_result or {}).get("response") or "").strip()
                if _synth and _output_violates_evidence(_synth, _ev_text):
                    print(f"[COGNITIVE] Full control synthesis rejected action={action}; retrying compact synthesis")
                    _synth = ""
'''

new = '''                _synth = str((_loop_result or {}).get("response") or "").strip()

                # ELI_RUNTIME_STATUS_POISON_GUARD_V1
                # Runtime-status synthesis is allowed to phrase live evidence, but not invent
                # unsupported operational claims, defer to a future answer, or add generic helper
                # chatter. Quick mode remains direct; this only rejects bad non-Quick candidates.
                if _synth and str(action or "").upper() == "RUNTIME_STATUS":
                    _eli_rs_lc = _synth.lower()
                    _eli_rs_poison_terms = (
                        "no active projects",
                        "no memory states",
                        "no external connections",
                        "no external databases",
                        "no external models loaded",
                        "model details will be provided in the next response",
                        "memory usage: 512 mb",
                        "no use of locking",
                        "active projects include",
                        "how can i assist you further",
                        "what specifically are you interested",
                        "what specific details",
                        "this setup is optimized",
                        "without relying on external services",
                        "independently of external services",
                    )
                    _eli_rs_hits = [term for term in _eli_rs_poison_terms if term in _eli_rs_lc]
                    if _eli_rs_hits:
                        print(
                            f"[COGNITIVE] Runtime-status poisoned synthesis rejected hits={_eli_rs_hits}; retrying compact synthesis",
                            flush=True,
                        )
                        _synth = ""

                if _synth and _output_violates_evidence(_synth, _ev_text):
                    print(f"[COGNITIVE] Full control synthesis rejected action={action}; retrying compact synthesis")
                    _synth = ""
'''

if old not in src:
    raise SystemExit("[PATCH] target block not found; inspect around `_loop_result` / `_synth = str` in eli/kernel/engine.py")

src = src.replace(old, new, 1)
p.write_text(src, encoding="utf-8")
print("[PATCH] installed runtime-status poison guard v1")
PY

python3 -m py_compile eli/kernel/engine.py
grep -n "ELI_RUNTIME_STATUS_POISON_GUARD_V1\|Runtime-status poisoned synthesis rejected" eli/kernel/engine.py
