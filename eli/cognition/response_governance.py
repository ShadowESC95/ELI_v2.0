"""Re-export shim — canonical home is eli.cognition.output_governor.

Response-quality governance (confabulation detection, scoring, memory-worthiness,
GGUF-artifact cleaning) now lives in output_governor. Kept so existing
`from eli.cognition.response_governance import ...` imports keep working.
"""
from __future__ import annotations

from eli.cognition.output_governor import (
    detect_confabulation,
    is_hard_knowledge_query,
    score_response_quality,
    govern_response,
    should_store_as_memory,
    score_confidence,
    clean_gguf_artifacts,
)

# Legacy name: the GGUF-artifact cleaner was called normalize_response here.
# It is clean_gguf_artifacts(response, user_input) — NOT output_governor's
# normalize_response(user_input, text). New code should import clean_gguf_artifacts.
normalize_response = clean_gguf_artifacts

__all__ = [
    "detect_confabulation", "is_hard_knowledge_query", "score_response_quality",
    "govern_response", "should_store_as_memory", "score_confidence",
    "clean_gguf_artifacts", "normalize_response",
]
