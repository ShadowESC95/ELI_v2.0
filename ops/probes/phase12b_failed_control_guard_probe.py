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

def forbidden_get_chat_response(*args, **kwargs):
    raise RuntimeError("GGUF synthesis was incorrectly invoked")

dummy._get_chat_response = forbidden_get_chat_response

failed_evidence = """
[AGENT:system] execute result: {'ok': False, 'action': 'ANALYZE_PDF', 'error': '/tmp/nonexistent_a.pdf',
'content': '/tmp/nonexistent_a.pdf', 'response': '/tmp/nonexistent_a.pdf'}
FileNotFoundError: /tmp/nonexistent_a.pdf
"""

out = dummy._synthesize_control_with_mode_framing(
    "read and summarise /tmp/nonexistent_a.pdf",
    failed_evidence,
    "ANALYZE_PDF",
    "constitutional_ai",
)

print(out)
print("--- checks ---")
print("contains_fake_success:", any(x in out.lower() for x in [
    "i'd be happy", "let me read", "here are the main points", "summarize the content"
]))
print("contains_failure:", "did not successfully" in out.lower() or "failed" in out.lower())
print("contains_path:", "/tmp/nonexistent_a.pdf" in out)
