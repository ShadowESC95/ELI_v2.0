#!/usr/bin/env python3
"""Model-grounded intent resolver (local GGUF, model-agnostic).

This is the fallback that lets ELI *understand* a request the deterministic
router didn't match — instead of dropping to a blind chat that can't act (and
may hallucinate facts like the date). It is grounded in ELI's REAL action
catalogue (``SUPPORTED_ACTIONS``, the single source of truth), so the model can
only resolve to actions that actually exist, and it must answer CHAT for genuine
conversation. No per-phrase hardcoding: the model generalises from its own
toolset.
"""
import json
import re
import threading
from typing import Dict, Any, List, Optional

from . import gguf_inference

from eli.utils.log import get_logger
log = get_logger(__name__)

_cache: Dict[str, Any] = {}
_cache_lock = threading.Lock()
_CACHE_MAX = 256  # prevent unbounded growth

# Actions the model should NOT be offered as an intent target: pure
# confirm/cancel/internal/no-op surfaces that are reached via dedicated
# confirmation flows or never by a fresh user phrasing. Derived by name, not a
# hand-maintained allow-list, so the catalogue stays the single source of truth.
_INTERNAL_ACTIONS = frozenset({
    "CHAT", "NOOP", "ANSWER", "DIRECT_RESPONSE", "TEMPLATE", "SEQUENCE_STEP",
    "CONFIRM_CODE_FIX", "CANCEL_CODE_FIX", "CONFIRM_HABIT", "DECLINE_HABIT",
    "CONFIRM_PENDING_REMEDIATION", "CANCEL_PENDING_REMEDIATION",
    "PREPARE_REMEDIATION", "DIAGNOSE_WRAPPERS", "CHECK_CHRONAL_ALIGNMENT",
})


def _catalogue() -> List[str]:
    """The live action catalogue, minus internal/confirm surfaces. Lazy import
    avoids a circular dependency at module load."""
    try:
        from eli.execution.executor_enhanced import SUPPORTED_ACTIONS
        acts = [a for a in SUPPORTED_ACTIONS if a not in _INTERNAL_ACTIONS]
        # stable, de-duplicated
        seen, out = set(), []
        for a in acts:
            if a not in seen:
                seen.add(a); out.append(a)
        return out
    except Exception:
        return []


# A few diverse FORMAT examples (teach arg extraction + the CHAT default). These
# illustrate the output shape and generalise — they are not a per-phrase routing
# table. Kept short and cross-domain on purpose.
_FEW_SHOT = (
    '{"q":"what day is it","action":"DATE","args":{},"confidence":0.95}\n'
    '{"q":"set the volume to 40 percent","action":"VOLUME",'
    '"args":{"level":40},"confidence":0.95}\n'
    '{"q":"open the communication hub","action":"OPEN_COMMUNICATION_HUB",'
    '"args":{},"confidence":0.9}\n'
    '{"q":"solve /home/u/x.py","action":"CODE_SOLVE",'
    '"args":{"path":"/home/u/x.py"},"confidence":0.9}\n'
    '{"q":"what is in the note you just wrote","action":"LIST_NOTES",'
    '"args":{},"confidence":0.8}\n'
    '{"q":"i am so happy to be alive","action":"CHAT","args":{},"confidence":0.95}\n'
    '{"q":"good morning","action":"CHAT","args":{},"confidence":0.95}\n'
    '{"q":"hey eli","action":"CHAT","args":{},"confidence":0.95}\n'
)


def parse_with_llm(text: str) -> Dict[str, Any]:
    """Resolve a free-text request to one of ELI's real actions, or CHAT.

    Returns ``{"action", "args", "confidence"}``. The action is guaranteed to be
    a member of the live catalogue or ``CHAT`` (anything else is coerced to
    CHAT). Degrades to CHAT on any failure (e.g. model not loaded)."""
    text = str(text or "").strip()
    if not text:
        return {"action": "CHAT", "args": {"message": text}, "confidence": 0.5}

    catalogue = _catalogue()
    if not catalogue:
        return {"action": "CHAT", "args": {"message": text}, "confidence": 0.5}

    valid = set(catalogue) | {"CHAT"}
    try:
        system = (
            "You are ELI's intent resolver. Map the user's message to the single "
            "best matching action from the provided list, extracting any obvious "
            "arguments. If the message is conversation, an opinion, a feeling, a "
            "complaint, small talk, a greeting or salutation (e.g. 'morning', "
            "'good morning', 'hey'), or does not clearly map to an action, answer "
            "CHAT. Use ONLY action names from the list. Output ONE JSON object: "
            '{"action": <NAME or CHAT>, "args": {...}, "confidence": <0..1>}.'
        )
        prompt = (
            "ACTIONS (choose exactly one, or CHAT):\n"
            + ", ".join(catalogue)
            + "\n\nEXAMPLES (format only):\n" + _FEW_SHOT
            + f'\nUSER: "{text}"\nJSON:'
        )
        response = gguf_inference.chat_completion(
            prompt, system=system, max_tokens=90, temperature=0.1,
        )
        m = re.search(r"\{.*\}", response or "", re.DOTALL)
        if not m:
            return {"action": "CHAT", "args": {"message": text}, "confidence": 0.5}
        parsed = json.loads(m.group())
        action = str(parsed.get("action") or "CHAT").strip().upper()
        if action not in valid:
            action = "CHAT"
        args = parsed.get("args")
        if not isinstance(args, dict):
            args = {}
        try:
            conf = float(parsed.get("confidence", 0.6))
        except Exception:
            conf = 0.6
        conf = max(0.0, min(1.0, conf))
        if action == "CHAT":
            args = {"message": text}
        return {"action": action, "args": args, "confidence": conf,
                "meta": {"matched_by": "llm_intent.resolver"}}
    except Exception as e:
        log.debug(f"[LLM_INTENT] resolve failed: {e}")
        return {"action": "CHAT", "args": {"message": text}, "confidence": 0.5}


def parse_cached(text: str) -> Dict[str, Any]:
    """Cached resolver (avoids re-inferring identical phrasings)."""
    key = str(text or "").strip().lower()
    with _cache_lock:
        if key in _cache:
            return _cache[key]
    result = parse_with_llm(text)
    with _cache_lock:
        if len(_cache) >= _CACHE_MAX:
            for k in list(_cache.keys())[: _CACHE_MAX // 2]:
                _cache.pop(k, None)
        _cache[key] = result
    return result
