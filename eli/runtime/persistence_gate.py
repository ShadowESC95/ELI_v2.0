from __future__ import annotations

from typing import Any, Iterable

from eli.runtime.identity_validation import extract_explicit_identity_facts, normalize_identity_candidate


_ERR_PATTERNS = (
    "gguf streaming failed", "gguf error", "gguf init deferred",
    "gguf unavailable", "no gguf model found",
    "model not ready",
    "requested tokens", "exceed context window", "inference failed",
    "broker unavailable",
)

# These prefixes mark ELI system / error messages — never store as assistant turns.
_ERR_PREFIXES = ("[eli] ", "[eli]")

_ASSISTANT_TRIVIAL = {
    "i'm here.", "i'm here", "got it.", "got it", "ok.", "ok"
}

_ELI_SELF_PATTERNS = (
    "i am eli", "i'm eli", "my current reasoning mode",
    "### memory system", "current time (authoritative",
    "provider:", "model:", "context size:", "gpu layers:",
    "threads:", "batch:", "gguf loaded:", "confidence:",
    "agents:", "runtime snapshot failed:"
)

_QUESTION_STARTS = (
    "who ", "what ", "where ", "when ", "why ", "how ", "which ",
    "can you", "could you", "would you", "do you", "does ",
    "is there", "are there", "tell me", "give me", "show me",
    "list ", "explain ", "describe "
)


def _norm(text: Any) -> str:
    return str(text or "").strip()


def _low(text: Any) -> str:
    return _norm(text).lower()


def _tag_list(tags: Any) -> list[str]:
    if tags is None:
        return []
    if isinstance(tags, str):
        return [t.strip() for t in tags.split(",") if t.strip()]
    if isinstance(tags, Iterable):
        out = []
        for x in tags:
            s = str(x).strip()
            if s:
                out.append(s)
        return out
    s = str(tags).strip()
    return [s] if s else []


def should_store_conversation_turn(role: str, text: Any) -> bool:
    t = _norm(text)
    if not t:
        return False
    low = t.lower()
    if role == "assistant":
        # Block [ELI] system/error prefix messages regardless of length.
        if any(low.startswith(p) for p in _ERR_PREFIXES):
            return False
        # Block known error patterns (no length guard — short OR long error dumps).
        if any(p in low for p in _ERR_PATTERNS):
            return False
        if low in _ASSISTANT_TRIVIAL:
            return False
    return True


def should_store_memory_text(text: Any, role: str = "user", tags: Any = None) -> bool:
    t = _norm(text)
    if not t:
        return False

    low = t.lower()
    tag_list = _tag_list(tags)
    tag_low = {x.lower() for x in tag_list}

    if any(low.startswith(p) for p in _ERR_PREFIXES):
        return False
    if any(p in low for p in _ERR_PATTERNS):
        return False

    if any(p in low for p in _ELI_SELF_PATTERNS):
        return False

    if tag_low & {"identity", "name", "alias"}:
        facts = extract_explicit_identity_facts(t)
        structured_match = False
        for marker in (
            "user's name is",
            "user preferred name is",
            "user's preferred name is",
            "preferred name:",
            "nickname:",
        ):
            if marker in low:
                structured_match = True
                break
        if structured_match and not facts:
            # Structured identity memories created by ELI still have to carry a
            # valid candidate; otherwise grammar fragments become high-salience
            # identity facts.
            candidate = ""
            for sep in (" is ", ":"):
                if sep in t:
                    candidate = t.rsplit(sep, 1)[-1]
                    break
            if not normalize_identity_candidate(candidate):
                return False

    if role == "assistant":
        if len(t.split()) < 4:
            return False
        if low in _ASSISTANT_TRIVIAL:
            return False
        return True

    stripped = low.rstrip("?!.").strip()
    if low.endswith("?") or stripped.endswith("?"):
        return False
    if len(t.split()) < 4:
        return False
    if any(stripped.startswith(q) for q in _QUESTION_STARTS):
        return False

    if "auto_extracted" in tag_list:
        return True

    return True
