from __future__ import annotations
def _eli_phase10_blocks_media_intent(text: str) -> bool:
    """
    Hard block document/code/analysis prompts from PLAY_MEDIA.
    This prevents long academic PDF prompts being interpreted as songs.
    """
    s = str(text or "").lower().strip()

    if len(s) > 260:
        return True

    blockers = (
        ".pdf", "[pdf content", "pdf content", "analyse", "analyze",
        "summarise", "summarize", "read and summarise", "read and summarize",
        "abstract", "lagrangian", "field equation", "equation of motion",
        "stress-energy", "tensor", "cosmology", "framework", "theory",
        "audit", "router", "executor", "gguf_inference", "orchestrator",
        "python files", "codebase",
    )
    return any(b in s for b in blockers)


import re
from typing import Optional


def normalise_voice_text(text: str) -> str:
    text = str(text or "").strip().lower()
    text = text.replace("’", "'").replace("“", '"').replace("”", '"')
    text = text.replace(" per cent", "%").replace(" percent", "%")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _clean_target(text: str) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip(" .,:;")
    s = re.sub(r"\b(?:chikovsky|chekovsky|chaykovsky|chaikovsky)\b", "tchaikovsky", s, flags=re.I)
    s = re.sub(r"\b(?:a moral technique|immoral technique|immortal technic|immortal technical)\b", "immortal technique", s, flags=re.I)
    return re.sub(r"\s+", " ", s).strip(" .,:;")


_MEDIA_SERVICE_ALIASES = {
    "spotify": "spotify",
    "youtube": "youtube",
    "yt": "youtube",
    "you tube": "youtube",
    "soundcloud": "soundcloud",
    "netflix": "netflix",
    "net flix": "netflix",
    "prime": "primevideo",
    "prime video": "primevideo",
    "primevideo": "primevideo",
    "amazon prime": "primevideo",
    "disney": "disneyplus",
    "disney+": "disneyplus",
    "disney plus": "disneyplus",
    "disneyplus": "disneyplus",
    "hulu": "hulu",
    "twitch": "twitch",
}


def _normalise_media_service(target: str) -> str:
    key = _clean_target(target).lower()
    key = re.sub(r"\s+", " ", key)
    return _MEDIA_SERVICE_ALIASES.get(key, key)


# Words that signal the utterance is a question/instruction about an app, not
# a launch command. If any of these appear in the tail, OPEN_APP/CLOSE_APP/etc.
# should NOT capture the entire sentence as the app name.
_APP_TAIL_REJECT_TOKENS = frozenset({
    "and", "or", "but", "so", "then", "tell", "show", "explain", "describe",
    "say", "report", "what", "why", "how", "when", "where", "who", "which",
    "please", "thanks", "thank", "to", "for", "about", "regarding", "if",
    "whether", "could", "would", "should", "can", "may", "might", "do",
    "does", "did", "is", "are", "was", "were", "the",
})


def _looks_like_app_target(target: str) -> bool:
    """
    A real OPEN/CLOSE/RUN target is a short app/binary identifier.
    Reject anything that looks like a sentence: multiple words containing
    natural-language fillers, conjunctions, or wh-words.
    """
    s = str(target or "").strip()
    if not s:
        return False
    tokens = s.split()
    if len(tokens) > 4:
        return False
    if any(tok.lower() in _APP_TAIL_REJECT_TOKENS for tok in tokens):
        return False
    # First token must look like an app/binary name: letters/digits/dot/dash/underscore.
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._\-+]{0,40}", tokens[0]):
        return False
    return True


_SCRIPT_LANGUAGE_ALIASES = {
    "py": "python",
    "python3": "python",
    "node": "javascript",
    "nodejs": "javascript",
    "js": "javascript",
    "ts": "typescript",
    "sh": "bash",
    "shell": "bash",
    "csharp": "c#",
    "rs": "rust",
    "golang": "go",
    "ps": "powershell",
    "pwsh": "powershell",
}

_SCRIPT_LANGUAGE_NAMES = frozenset({
    "python", "bash", "zsh", "javascript", "typescript", "c", "c++", "cpp",
    "c#", "java", "rust", "go", "ruby", "php", "lua", "r", "swift",
    "kotlin", "scala", "sql", "html", "css", "json", "yaml", "yml",
    "julia", "fortran", "perl", "powershell",
})

_SCRIPT_LANGUAGE_REJECTS = frozenset({
    "a", "an", "the", "ide", "labs", "tab", "default", "previous",
    "following", "this", "that", "advanced", "basic", "simple", "new",
    "powerful", "potent",
})


def _normalise_script_language(candidate: str) -> str | None:
    value = str(candidate or "").strip().lower().rstrip(".,:;")
    if not value or value in _SCRIPT_LANGUAGE_REJECTS:
        return None
    value = _SCRIPT_LANGUAGE_ALIASES.get(value, value)
    if value in _SCRIPT_LANGUAGE_NAMES:
        return value
    return None


def infer_script_language(text: str) -> str:
    norm = normalise_voice_text(text)

    m = re.search(
        r"\b(?:generate|write|create|build|make)\s+(?:a|an|the)?\s*([a-z0-9+#.\-]{1,40})\s+(?:script|code|program|module|tool|app)\b",
        norm,
    )
    if m:
        language = _normalise_script_language(m.group(1))
        if language:
            return language

    for m in re.finditer(r"\b(?:in|using|with)\s+([a-z0-9+#.\-]{1,40})\b", norm):
        language = _normalise_script_language(m.group(1))
        if language:
            return language

    if (
        re.search(r"\b(?:generate|write|create|build|make|define)\b", norm)
        and re.search(r"\b(?:script|code|program|class|function|module|object|constructor|inherit)\b", norm)
    ):
        return "python"

    return "auto"


def _looks_like_generation_complaint(norm: str) -> bool:
    if not norm:
        return False
    complaint_starts = (
        "you did not", "you didn't", "you just", "that script", "this script",
        "why did you", "why didn't you", "where is", "where did", "it did not",
        "it didn't", "your code", "your script",
    )
    complaint_phrases = (
        "did not generate", "didn't generate", "never ran", "not generated",
        "nothing to do with", "less in content", "no ide opened",
        "did not open", "didn't open", "dump it into chat", "not provide any path",
        "where is it",
    )
    return norm.startswith(complaint_starts) or any(p in norm for p in complaint_phrases)


def try_route(text: str) -> Optional[dict]:
    if _eli_phase10_blocks_media_intent(text):
        return None
    raw = str(text or "").strip()
    norm = normalise_voice_text(raw)
    if not norm:
        return None

    if re.fullmatch(r"(?:start\s+pomodoro|begin\s+pomodoro|pomodoro\s+start)(?:\s+timer)?", norm):
        return None

    m = re.fullmatch(r"(?:open|opens|launch|start|run)\s+(.+)", norm)
    if m:
        target = _clean_target(m.group(1))
        if _looks_like_app_target(target):
            return {
                "action": "OPEN_APP",
                "args": {"name": target, "target": target},
                "confidence": 0.995,
                "meta": {"matched_by": "portable_intent_contract.open_app"},
            }

    if re.fullmatch(r"(?:close|closed|exit|quit)\s+(?:current\s+|the\s+)?(?:browser\s+)?tab", norm):
        return {
            "action": "KEYBOARD",
            "args": {"key": "ctrl+w"},
            "confidence": 0.995,
            "meta": {"matched_by": "portable_intent_contract.close_current_tab"},
        }

    m = re.fullmatch(r"(?:close|closed|exit|quit)\s+(.+)", norm)
    if m:
        target = _clean_target(m.group(1))
        if _looks_like_app_target(target):
            return {
                "action": "CLOSE_APP",
                "args": {"name": target, "target": target},
                "confidence": 0.995,
                "meta": {"matched_by": "portable_intent_contract.close_app"},
            }

    m = re.fullmatch(r"(?:kill|force close|force quit)\s+(.+)", norm)
    if m:
        target = _clean_target(m.group(1))
        if _looks_like_app_target(target):
            return {
                "action": "CLOSE_APP",
                "args": {"name": target, "target": target, "force": True},
                "confidence": 0.995,
                "meta": {"matched_by": "portable_intent_contract.force_close_app"},
            }

    m = re.fullmatch(r"(?:minimize|minimise|hide)\s+(.+)", norm)
    if m:
        target = _clean_target(m.group(1))
        if _looks_like_app_target(target):
            return {
                "action": "MINIMIZE_APP",
                "args": {"name": target, "target": target},
                "confidence": 0.995,
                "meta": {"matched_by": "portable_intent_contract.minimize_app"},
            }

    m = re.fullmatch(r"(?:set\s+)?volume\s+(?:to\s+)?(\d{1,3})\s*%?", norm)
    if m:
        level = max(0, min(100, int(m.group(1))))
        return {
            "action": "VOLUME",
            "args": {"level": level, "percent": level, "mode": "absolute"},
            "confidence": 0.999,
            "meta": {"matched_by": "portable_intent_contract.volume_absolute"},
        }

    m = re.fullmatch(r"play\s+(.+?)\s+(?:on|using|with)\s+(.+)", norm)
    if m:
        query = _clean_target(m.group(1))
        try:
            raw_m = re.fullmatch(r"play\s+(.+?)[\s,]+(?:on|using|with)\s+(.+)", raw, re.I)
            if raw_m:
                query = _clean_target(raw_m.group(1))
        except Exception:
            pass
        target = _normalise_media_service(m.group(2))
        return {
            "action": "PLAY_MEDIA",
            "args": {"query": query, "target": target, "service": target},
            "confidence": 0.995,
            "meta": {"matched_by": "portable_intent_contract.play_query_on_target"},
        }

    m = re.fullmatch(r"(.+?)\s+by\s+(.+)", norm)
    if m and len(norm.split()) >= 4:
        # Guard against conversational sentences where "by" is a preposition,
        # not a "song by artist" separator.  The title (before "by") must not
        # contain common English function/pronoun/verb words that signal a
        # sentence rather than a media title.  Also block if the text starts
        # with a negation or conversational opener.
        _before_by = m.group(1).strip()
        _before_words = set(_before_by.lower().split())
        _sentence_signals = {
            "you", "will", "would", "could", "should", "can", "me", "my",
            "i", "we", "they", "he", "she", "it", "is", "are", "was",
            "were", "be", "been", "am", "no", "yes", "ok", "okay", "got",
            "get", "go", "did", "do", "does", "done", "please", "that",
            "this", "which", "what", "how", "run", "come", "take", "give",
            "your", "our", "their", "its", "first", "now", "then", "also",
            "just", "not", "never", "always", "but", "and", "or", "so",
        }
        if _before_words & _sentence_signals:
            pass  # "by" is a preposition in a sentence — not a media query
        else:
            query = _clean_target(raw)
            query = re.sub(r"(?i)^\s*play\s+", "", query).strip()
            target = "spotify"
            return {
                "action": "PLAY_MEDIA",
                "args": {"query": query, "target": target, "service": target},
                "confidence": 0.96,
                "meta": {"matched_by": "portable_intent_contract.implied_song_by_artist"},
            }

    wants_generation = re.search(r"\b(?:generate|write|create|build|make)\b", norm)
    wants_code = re.search(r"\b(?:script|code|program|module|tool|app)\b", norm)
    # Reject if a negation word immediately precedes the generation verb —
    # e.g. "not generate a new python script" must not fire GENERATE_SCRIPT.
    _negated_generation = bool(wants_generation and re.search(
        r"\b(?:not|don'?t|never|no|stop|without|rather\s+than|instead\s+of)\b\s+\w*\s*"
        r"(?:generate|write|create|build|make)\b", norm))
    if wants_generation and wants_code and not _looks_like_generation_complaint(norm) and not _negated_generation:
        language = infer_script_language(raw)
        return {
            "action": "GENERATE_SCRIPT",
            "args": {
                "description": raw,
                "prompt": raw,
                "language": language,
                "destination": "labs_sim_ide",
                "open_in_labs": True,
                "open_in_ide": True,
            },
            "confidence": 0.995,
            "meta": {"matched_by": "portable_intent_contract.generate_script"},
        }

    return None


def wrap_router_callable(fn):
    if not callable(fn) or getattr(fn, "_portable_intent_contract_wrapped", False):
        return fn

    def wrapped(*args, **kwargs):
        text = ""
        for item in args:
            if isinstance(item, str) and item.strip():
                text = item
                break
        if not text:
            for key in ("text", "message", "command", "prompt", "query", "utterance"):
                value = kwargs.get(key)
                if isinstance(value, str) and value.strip():
                    text = value
                    break

        route = try_route(text)
        if route is not None:
            return route
        return fn(*args, **kwargs)

    wrapped.__name__ = getattr(fn, "__name__", "wrapped")
    wrapped.__doc__ = getattr(fn, "__doc__", None)
    wrapped._portable_intent_contract_wrapped = True
    return wrapped
