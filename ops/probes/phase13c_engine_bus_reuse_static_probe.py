#!/usr/bin/env python3
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
