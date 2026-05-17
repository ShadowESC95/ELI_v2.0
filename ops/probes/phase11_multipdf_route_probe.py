#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PDF1="/home/jay/Desktop/Physics/Theory_MATHEMATICS/Exergetic_Coherence_Revoloution.pdf"
PDF2="/home/jay/Desktop/Physics/Theory_MATHEMATICS/FINAL.pdf"

prompt = f"read and summarise {PDF1} and {PDF2}"

from eli.execution.router_enhanced import route, route_intent

for fn in (route, route_intent):
    r = fn(prompt)
    print("=" * 100)
    print(fn.__name__, "=>", r)
    args = r.get("args", {}) if isinstance(r, dict) else {}
    print("action:", r.get("action") if isinstance(r, dict) else None)
    print("path:", args.get("path"))
    print("paths:", args.get("paths"))
    print("paths_count:", len(args.get("paths") or []))
