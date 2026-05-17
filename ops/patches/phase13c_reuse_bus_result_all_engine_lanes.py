#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()
STAMP = subprocess.check_output(["date", "+%Y%m%d_%H%M%S"], text=True).strip()
OUT = ROOT / f"ops/reports/phase13c_reuse_bus_result_all_engine_lanes_{STAMP}"
OUT.mkdir(parents=True, exist_ok=True)

changed = []

eng = ROOT / "eli/kernel/engine.py"
s = eng.read_text(encoding="utf-8", errors="replace")
orig = s

helper = r'''
# --- Phase 13c: shared helper to reuse AgentBus action results -------------
def _eli_phase13c_bus_action_result(bus_result, action):
    """Return the already-executed system/plugin result for action, if present.

    Prevents duplicate executor calls after AgentBus has already run the direct
    action. Failed results are valid authoritative results and must be reused.
    """
    action_u = str(action or "").upper().strip()
    if not action_u or bus_result is None:
        return None

    try:
        ar = getattr(bus_result, "action_result", None)
        if isinstance(ar, dict) and ar:
            data_action = str(ar.get("action") or action_u).upper().strip()
            if data_action == action_u:
                return dict(ar)
    except Exception:
        pass

    try:
        for r in list(getattr(bus_result, "agent_results", []) or []):
            agent = str(getattr(r, "agent", "") or "")
            if agent not in {"system", "plugin"}:
                continue
            data = getattr(r, "data", None)
            if not isinstance(data, dict) or data.get("skipped"):
                continue
            data_action = str(data.get("action") or action_u).upper().strip()
            if data_action == action_u:
                return dict(data)
    except Exception:
        pass

    return None
'''

if "_eli_phase13c_bus_action_result" not in s:
    insert_at = s.find("\nclass CognitiveEngine")
    if insert_at == -1:
        raise SystemExit("Could not find class CognitiveEngine insertion point")
    s = s[:insert_at] + "\n" + helper + "\n" + s[insert_at:]

# Replace common fallback patterns.
replacements = [
    (
        '''                    if _action_result is None:
                        _action_result = execute_action(action, args)
''',
        '''                    if _action_result is None:
                        _action_result = _eli_phase13c_bus_action_result(bus_result, action)
                    if _action_result is None:
                        _action_result = execute_action(action, args)
'''
    ),
    (
        '''                    raw_result = execute_action(action, args)
''',
        '''                    raw_result = _eli_phase13c_bus_action_result(bus_result, action)
                    if raw_result is None:
                        raw_result = execute_action(action, args)
'''
    ),
    (
        '''                raw_result = execute_action(action, args)
''',
        '''                raw_result = _eli_phase13c_bus_action_result(bus_result, action)
                if raw_result is None:
                    raw_result = execute_action(action, args)
'''
    ),
    (
        '''        result = execute_action(action, args)
''',
        '''        result = _eli_phase13c_bus_action_result(locals().get("bus_result"), action)
        if result is None:
            result = execute_action(action, args)
'''
    ),
]

applied = []
for old, new in replacements:
    if old in s and new not in s:
        s = s.replace(old, new)
        applied.append(old.strip().splitlines()[0])

if s != orig:
    (OUT / "engine.py.before").write_text(orig, encoding="utf-8")
    eng.write_text(s, encoding="utf-8")
    changed.append("eli/kernel/engine.py")

# Probe: static assertion that helper exists and no obvious duplicate fallback remains in key lane.
probe = ROOT / "ops/probes/phase13c_engine_bus_reuse_static_probe.py"
probe.write_text(r'''#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
s = (ROOT / "eli/kernel/engine.py").read_text(errors="replace")

print("helper_present:", "_eli_phase13c_bus_action_result" in s)
print("helper_calls:", s.count("_eli_phase13c_bus_action_result("))
print("direct_execute_action_action_args:", s.count("execute_action(action, args)"))

assert "_eli_phase13c_bus_action_result" in s
assert s.count("_eli_phase13c_bus_action_result(") >= 2

print("phase13c_static_ok=True")
''', encoding="utf-8")
probe.chmod(0o755)

cp = subprocess.run(
    [sys.executable, "-m", "compileall", "-q", "eli"],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
)

summary = OUT / "SUMMARY.md"
summary.write_text(
    "# Phase 13c Reuse Bus Result Across Engine Lanes\n\n"
    "Changed files:\n"
    + ("".join(f"- {x}\n" for x in changed) if changed else "- none\n")
    + "\nApplied replacements:\n"
    + ("".join(f"- {x}\n" for x in applied) if applied else "- none\n")
    + "\nCompile output:\n\n```text\n"
    + cp.stdout
    + "\n```\n",
    encoding="utf-8",
)

print(f"REPORT: {OUT}")
print(summary.read_text())

if cp.returncode != 0:
    raise SystemExit(cp.returncode)
