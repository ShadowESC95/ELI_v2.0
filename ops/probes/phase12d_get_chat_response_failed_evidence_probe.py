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
The following grounded evidence is authoritative.

<grounded_evidence>
[AGENT:system] execute result: {'ok': False, 'action': 'ANALYZE_PDF', 'error': '/tmp/nonexistent_phase12d.pdf',
'content': '/tmp/nonexistent_phase12d.pdf', 'response': '/tmp/nonexistent_phase12d.pdf'}
FileNotFoundError: /tmp/nonexistent_phase12d.pdf
</grounded_evidence>

USER ASKED: read and summarise /tmp/nonexistent_phase12d.pdf

ANSWER:
"""

out = dummy._get_chat_response(prompt)

print(out)
print("--- checks ---")
print("contains_fake_success:", any(x in out.lower() for x in [
    "i'd be happy", "let me read", "here are the main points", "summarize the content"
]))
print("contains_failure:", "did not successfully" in out.lower() or "failed" in out.lower() or "ok=false" in out.lower())
print("contains_path:", "/tmp/nonexistent_phase12d.pdf" in out)
