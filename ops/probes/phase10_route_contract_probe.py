
#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


PDF1 = "/home/jay/Desktop/Physics/Theory_MATHEMATICS/Exergetic_Coherence_Revoloution.pdf"
PDF2 = "/home/jay/Desktop/Physics/Theory_MATHEMATICS/FINAL.pdf"

samples = [
    f"read and summarise {PDF1} and {PDF2}",
    "analyse and talk to me about [PDF content — Exergetic_Coherence_Revoloution.pdf]: Exergetic Cosmology and Vacuum Hydrodynamics",
    "play guilty conscience by eminem on spotify",
    "audit your world_model, agent_bus, gguf_inference, orchestrator, output_governer, hyde, vector_store, runtime_settings and every file in the /runtime folder",
]

print("=== Import router ===")
import eli.execution.router_enhanced as r

if hasattr(r, "_extract_pdf_paths"):
    for s in samples[:2]:
        print("INPUT:", s[:160])
        print("PDF_PATHS:", r._extract_pdf_paths(s))
        print("PDF_PATH:", r._extract_pdf_path(s))
        print()

print("=== Media guard imports ===")
import eli.execution.portable_intent_contract as pic
import eli.execution.media_intents as mi

for mod in (pic, mi):
    guard = getattr(mod, "_eli_phase10_blocks_media_intent", None)
    print(mod.__name__, "guard_exists=", bool(guard))
    if guard:
        print("pdf blocked:", guard(samples[1]))
        print("song blocked:", guard(samples[2]))
