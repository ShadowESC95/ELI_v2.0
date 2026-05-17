#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eli.kernel.engine import CognitiveEngine

class Dummy(CognitiveEngine):
    def __init__(self):
        pass

dummy = Dummy()

prompt = """
## Runtime Persona Notes
Some stale action mentions PAUSE_MEDIA and unrelated old path /tmp/nonexistent_b.pdf.
## Recent Failure Patterns
Old stale path /Exergetic_Coherence_Revoloution.pdf.

<grounded_evidence>
[AGENT:system] execute result: {'ok': False, 'action': 'ANALYZE_PDF', 'error': '/tmp/nonexistent_phase12e.pdf',
'content': '/tmp/nonexistent_phase12e.pdf', 'response': '/tmp/nonexistent_phase12e.pdf'}
FileNotFoundError: /tmp/nonexistent_phase12e.pdf
</grounded_evidence>

USER ASKED: read and summarise /tmp/nonexistent_phase12e.pdf

ANSWER:
"""

out = dummy._get_chat_response(prompt)

print(out)
print("--- checks ---")
low = out.lower()
print("contains_fake_success:", any(x in low for x in [
    "i'd be happy", "let me read", "here are the main points", "summarize the content"
]))
print("contains_failure:", "did not successfully" in low or "failed" in low)
print("contains_pdf_action:", "analyse the pdf request" in low or "analyze_pdf" in out)
print("contains_wrong_pause:", "pause_media" in low)
print("contains_stale_path_b:", "/tmp/nonexistent_b.pdf" in out)
print("contains_old_exergetic_path:", "/Exergetic_Coherence_Revoloution.pdf" in out)
print("contains_target_path:", "/tmp/nonexistent_phase12e.pdf" in out)
