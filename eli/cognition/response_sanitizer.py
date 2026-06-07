"""Re-export shim — canonical home is eli.cognition.output_governor.

Kept so existing `from eli.cognition.response_sanitizer import ...` imports work.
These 1-arg aliases are sanitize-only and are DISTINCT from output_governor's
2-arg normalize_assistant_text(user_input, text).
"""
from __future__ import annotations

from eli.cognition.output_governor import sanitize_assistant_text

normalize_assistant_text = sanitize_assistant_text
clean_assistant_text = sanitize_assistant_text

__all__ = ["sanitize_assistant_text", "normalize_assistant_text", "clean_assistant_text"]
