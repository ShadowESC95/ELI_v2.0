#!/usr/bin/env bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

python3 - <<'PY'
from pathlib import Path

p = Path("eli/kernel/engine.py")
src = p.read_text(encoding="utf-8")

if "ELI_RUNTIME_STATUS_POISON_GUARD_V2" in src:
    print("[PATCH] runtime-status poison guard v2 already installed")
    raise SystemExit(0)

if "ELI_RUNTIME_STATUS_POISON_GUARD_V1" not in src:
    raise SystemExit("[PATCH] v1 marker not found; install v1 first or inspect engine.py")

old = '''                # ELI_RUNTIME_STATUS_POISON_GUARD_V1
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
'''

new = '''                # ELI_RUNTIME_STATUS_POISON_GUARD_V1
                # ELI_RUNTIME_STATUS_POISON_GUARD_V2
                # Runtime-status synthesis may rephrase live evidence, but must not invent
                # unsupported operational claims, future deferrals, memory claims, project claims,
                # dependency claims, or generic assistant chatter. Quick mode remains direct;
                # this only rejects bad non-Quick candidates before final control repair.
                if _synth and str(action or "").upper() == "RUNTIME_STATUS":
                    _eli_rs_lc = _synth.lower()
                    _eli_rs_poison_terms = (
                        "no active projects",
                        "no memory states",
                        "no external connections",
                        "no external databases",
                        "no external models loaded",
                        "no external dependencies",
                        "external dependencies are active",
                        "no external dependencies are active",
                        "model details will be provided in the next response",
                        "memory usage: 512 mb",
                        "memory usage: adaptive",
                        "mapped to memory: yes",
                        "locked in memory: yes",
                        "no use of locking",
                        "active projects include",
                        "active debugging",
                        "debugging sqlite memory",
                        "project development",
                        "operational context includes",
                        "no recent failures or errors have been stored",
                        "no other details are stored",
                        "latest gguf model",
                        "how can i assist you further",
                        "what specifically are you interested",
                        "what specific details",
                        "what specifically do you need this for",
                        "this setup is optimized",
                        "allows for detailed and personalized responses",
                        "tailored to your needs",
                        "without relying on external services",
                        "independently of external services",
                        "cloud services are used",
                        "secure and private experience",
                    )
                    _eli_rs_hits = [term for term in _eli_rs_poison_terms if term in _eli_rs_lc]
                    if _eli_rs_hits:
                        print(
                            f"[COGNITIVE] Runtime-status poisoned synthesis rejected hits={_eli_rs_hits}; retrying compact synthesis",
                            flush=True,
                        )
                        _synth = ""
'''

if old not in src:
    raise SystemExit("[PATCH] v1 block not found exactly; inspect around ELI_RUNTIME_STATUS_POISON_GUARD_V1")

src = src.replace(old, new, 1)
p.write_text(src, encoding="utf-8")
print("[PATCH] upgraded runtime-status poison guard to v2")
PY

python3 -m py_compile eli/kernel/engine.py
grep -n "ELI_RUNTIME_STATUS_POISON_GUARD_V2\|Runtime-status poisoned synthesis rejected" eli/kernel/engine.py
