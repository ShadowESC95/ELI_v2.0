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

failed_evidence = """
{'ok': False, 'action': 'ANALYZE_PDF', 'error': '/tmp/nonexistent_a.pdf',
 'content': '/tmp/nonexistent_a.pdf',
 'response': '/tmp/nonexistent_a.pdf'}
FileNotFoundError: /tmp/nonexistent_a.pdf
"""

out = dummy._synthesize_answer(
    failed_evidence,
    "read and summarise /tmp/nonexistent_a.pdf",
    reasoning_mode="constitutional_ai",
    action="ANALYZE_PDF",
)

print(out)
print("--- checks ---")
print("contains_fake_success:", any(x in out.lower() for x in [
    "i'd be happy", "let me read", "here are the main points", "summarize the content"
]))
print("contains_failure:", "did not successfully" in out.lower() or "failed" in out.lower())
print("contains_path:", "/tmp/nonexistent_a.pdf" in out)
