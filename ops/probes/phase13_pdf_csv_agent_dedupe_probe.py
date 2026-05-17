#!/usr/bin/env python3
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
