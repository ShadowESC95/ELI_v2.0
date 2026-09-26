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
import hashlib
import json
import re
import threading
from typing import Dict, Any, List

from . import gguf_inference

from eli.utils.log import get_logger
log = get_logger(__name__)

_cache: Dict[str, Any] = {}
_cache_lock = threading.Lock()
_CACHE_MAX = 256  # prevent unbounded growth

# Actions not offered to the model as intent targets: confirm/cancel/internal/no-op surfaces reached
# through dedicated flows. Derived by name, so the catalogue stays the single source of truth.
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
    '{"q":"do you remember what we talked about last week","action":"MEMORY_RECALL",'
    '"args":{"query":"last week conversation topics"},"confidence":0.9}\n'
)


# backend without grammar support (Ollama, remote), so this stays model-agnostic.
_GRAMMAR_CACHE: Dict[str, Any] = {}


def _action_grammar(catalogue: List[str]):
    """A GBNF grammar admitting only {"action": <one of catalogue>, "args": {...},
    "confidence": <number>}. Cached per catalogue signature; None if unavailable."""
    if not catalogue:
        return None
    # Admit exactly what the resolver below accepts — the catalogue plus CHAT. Omitting
    # CHAT would make ordinary small talk unrepresentable and force every greeting to be
    # answered as a command.
    names = sorted(set(catalogue) | {"CHAT"})
    key = hashlib.sha1("|".join(names).encode()).hexdigest()
    if key in _GRAMMAR_CACHE:
        return _GRAMMAR_CACHE[key]
    grammar = None
    try:
        from llama_cpp import LlamaGrammar
        alts = " | ".join('"\\"%s\\""' % a for a in names)
        gbnf = (
            'root    ::= "{" ws "\\"action\\":" ws action ws "," ws "\\"args\\":" ws object'
            ' ws "," ws "\\"confidence\\":" ws number ws "}"\n'
            'action  ::= ' + alts + '\n'
            'object  ::= "{" ws ( string ":" ws value ("," ws string ":" ws value)* )? "}"\n'
            'value   ::= object | array | string | number | "true" | "false" | "null"\n'
            'array   ::= "[" ws ( value ("," ws value)* )? "]"\n'
            'string  ::= "\\"" ([^"\\\\] | "\\\\" ["\\\\/bfnrt])* "\\""\n'
            'number  ::= "-"? [0-9]+ ("." [0-9]+)?\n'
            'ws      ::= [ \\t\\n]*\n'
        )
        grammar = LlamaGrammar.from_string(gbnf, verbose=False)
    except Exception:
        log.debug("llm_intent: grammar unavailable — using free-text JSON", exc_info=True)
        grammar = None
    _GRAMMAR_CACHE[key] = grammar
    return grammar


# Canonical arg key -> names a model plausibly invents for it. The grammar constrains the action
# name, not `args`, so the model gave OPEN_APP {"app_name": ...} where the executor reads
# "name"/"app". Additive only: fill the canonical key if absent, never rename or drop.
_ARG_ALIASES: Dict[str, tuple] = {
    "name":    ("app_name", "application", "app", "program", "target", "title"),
    "path":    ("file_path", "filepath", "file", "directory", "folder", "dir", "location"),
    "query":   ("search_query", "search", "q", "topic", "question"),
    "message": ("text", "content", "body"),
    "level":   ("value", "amount", "percent", "percentage", "volume"),
    "url":     ("link", "address", "website", "site"),
    "command": ("cmd",),
    "device":  ("device_name",),
}


def normalize_args(args: Dict[str, Any]) -> Dict[str, Any]:
    """Fill in canonical arg names alongside whatever the model called them."""
    if not isinstance(args, dict) or not args:
        return args if isinstance(args, dict) else {}
    out = dict(args)
    for canonical, aliases in _ARG_ALIASES.items():
        if str(out.get(canonical) or "").strip():
            continue
        for alias in aliases:
            val = out.get(alias)
            if val is not None and str(val).strip():
                out[canonical] = val
                break
    # An app/file target is read as "target" by some effectors and "name" by
    # others; mirror whichever one we ended up with.
    if str(out.get("name") or "").strip() and not str(out.get("target") or "").strip():
        out["target"] = out["name"]
    return out


_IMPERATIVE = frozenset("""open play pause resume stop set turn show tell make create write run check search find send call remind add remove
delete take start launch close read list get give do look describe explain generate fetch download install update mute unmute
skip next previous volume save store remember forget schedule cancel switch enable disable analyze analyse examine fix improve""".split())


def is_plain_statement(text: str) -> bool:
    """Conversation, not a command: no question, no leading action verb. Nothing for an intent model to resolve."""
    t = " ".join(str(text or "").split())
    if len(t.split()) < 6 or "?" in t:
        return False
    first = re.sub(r"^(?:please|hey|eli|ok|okay|so|well|and|but)[,\s]+", "", t.lower())
    words = re.findall(r"[a-z']+", first)
    return bool(words) and words[0] not in _IMPERATIVE and not re.search(r"\bplease\b", t, re.I)


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
        # Constrain the decoder to the live catalogue when the backend supports it, so the model
        # can't invent a capability or emit unparseable JSON. Without grammar support, fall through
        # to the free-text path below.
        _grammar = _action_grammar(catalogue)
        response = None
        if _grammar is not None:
            try:
                response = gguf_inference.chat_completion(
                    prompt, system=system, max_tokens=200, temperature=0.1,
                    grammar=_grammar,
                )
                log.debug("llm_intent: grammar-constrained decode over %d actions", len(catalogue))
            except TypeError:
                response = None  # backend does not accept a grammar kwarg
            except Exception:
                log.debug("llm_intent: grammar decode failed — falling back", exc_info=True)
                response = None
        if response is None:
            response = gguf_inference.chat_completion(
                prompt, system=system, max_tokens=200, temperature=0.1,
            )

        # Tolerate markdown-fenced JSON (Phi-4 emits ```json, Qwen bare JSON) and leave enough
        # budget that long-arg JSON isn't cut off mid-object. Both made routing collapse to CHAT and
        # the model claim it ran the command.
        _resp = re.sub(r"```(?:json)?|```", " ", response or "")
        m = re.search(r"\{.*\}", _resp, re.DOTALL)
        if not m:
            return {"action": "CHAT", "args": {"message": text}, "confidence": 0.5}
        parsed = json.loads(m.group())
        action = str(parsed.get("action") or "CHAT").strip().upper()
        if action not in valid:
            action = "CHAT"
        args = parsed.get("args")
        if not isinstance(args, dict):
            args = {}
        args = normalize_args(args)
        try:
            conf = float(parsed.get("confidence", 0.6))
        except Exception:
            conf = 0.6
        conf = max(0.0, min(1.0, conf))
        if action == "CHAT":
            args = {"message": text}
        elif action == "MEMORY_RECALL" and not str(args.get("query") or "").strip():
            # Grammar allows {} but MEMORY_RECALL requires a query — use the user turn.
            args["query"] = text
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
