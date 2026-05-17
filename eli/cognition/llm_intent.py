#!/usr/bin/env python3
"""LLM intent parsing - NOW USING GGUF instead of Ollama"""
import json
import os
from typing import Dict, Any
from . import gguf_inference

_cache = {}

def parse_with_llm(text: str) -> Dict[str, Any]:
    """Parse intent using GGUF model (not Ollama)."""
    try:
        prompt = f"""Given the user query: "{text}"
Return ONLY a JSON object with:
- action: the intent (CHAT, OPEN_APP, GET_TIME, etc.)
- args: parameters for the action
- confidence: float between 0 and 1

JSON:"""
        
        response = gguf_inference.chat_completion(
            prompt,
            system="You are ELI's intent parser. Output only valid JSON.",
            max_tokens=150,
            temperature=0.1
        )
        
        # Extract JSON from response
        import re
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
    except Exception as e:
        print(f"[LLM] Intent parse failed: {e}")
    
    return {"action": "CHAT", "args": {"message": text}, "confidence": 0.5}

def parse_cached(text: str) -> Dict[str, Any]:
    """Cached version of parse_with_llm."""
    if text in _cache:
        return _cache[text]
    result = parse_with_llm(text)
    _cache[text] = result
    return result
