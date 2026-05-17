#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()
STAMP = subprocess.check_output(["date", "+%Y%m%d_%H%M%S"], text=True).strip()
OUT = ROOT / f"ops/reports/phase13_dedupe_pdf_csv_agent_execution_{STAMP}"
OUT.mkdir(parents=True, exist_ok=True)

p = ROOT / "eli/cognition/agent_bus.py"
s = p.read_text(encoding="utf-8", errors="replace")

changed = []

if '"ANALYZE_PDF", "ANALYZE_CSV",' in s:
    backup = OUT / "agent_bus.py.before"
    backup.write_text(s, encoding="utf-8")

    # PDF/CSV are executor-owned system actions. Do not let PluginAgent
    # execute them too; that creates duplicate file reads and repeated failures.
    s = s.replace(
        '''    PLUGIN_ACTIONS: Set[str] = {
        "GET_WEATHER", "LIST_EVENTS", "ADD_EVENT",
        "ANALYZE_PDF", "ANALYZE_CSV",
    }
''',
        '''    PLUGIN_ACTIONS: Set[str] = {
        "GET_WEATHER", "LIST_EVENTS", "ADD_EVENT",
    }
'''
    )

    # Fix misleading log label in PluginAgent.
    s = s.replace(
        'print(f"[AGENT:system] execute result: {result}")',
        'print(f"[AGENT:plugin] execute result: {result}")',
        1
    )

    p.write_text(s, encoding="utf-8")
    changed.append("eli/cognition/agent_bus.py")

probe = ROOT / "ops/probes/phase13_pdf_csv_agent_dedupe_probe.py"
probe.write_text(r'''#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eli.cognition.agent_bus import SystemAgent, PluginAgent

print("ANALYZE_PDF in SystemAgent:", "ANALYZE_PDF" in SystemAgent.SYSTEM_ACTIONS)
print("ANALYZE_CSV in SystemAgent:", "ANALYZE_CSV" in SystemAgent.SYSTEM_ACTIONS)
print("ANALYZE_PDF in PluginAgent:", "ANALYZE_PDF" in PluginAgent.PLUGIN_ACTIONS)
print("ANALYZE_CSV in PluginAgent:", "ANALYZE_CSV" in PluginAgent.PLUGIN_ACTIONS)

assert "ANALYZE_PDF" in SystemAgent.SYSTEM_ACTIONS
assert "ANALYZE_CSV" in SystemAgent.SYSTEM_ACTIONS
assert "ANALYZE_PDF" not in PluginAgent.PLUGIN_ACTIONS
assert "ANALYZE_CSV" not in PluginAgent.PLUGIN_ACTIONS

print("phase13_dedupe_ok=True")
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
    "# Phase 13 PDF/CSV Agent Execution Dedupe\n\n"
    "Changed files:\n"
    + ("".join(f"- {x}\n" for x in changed) if changed else "- none\n")
    + "\nCompile output:\n\n```text\n"
    + cp.stdout
    + "\n```\n",
    encoding="utf-8",
)

print(f"REPORT: {OUT}")
print(summary.read_text())

if cp.returncode != 0:
    raise SystemExit(cp.returncode)
