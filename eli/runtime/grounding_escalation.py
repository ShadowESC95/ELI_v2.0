"""
Tiered grounding escalation.

When a turn is a *checkable factual* question/claim AND the AgentBus grounded it
poorly (no agent contributed real evidence), don't let the model answer from its
weights and confabulate (the "Eminem's real name is Bruce Samuelson" failure).
Instead escalate through tiers of agents — stopping at the first that grounds it —
and if nothing can, HEDGE honestly instead of guessing.

Trigger is grounding, NOT the response-confidence score: a small model is
confidently wrong while confabulating (response≈0.9), but the grounding score is
near-zero because no evidence backs the answer. So we gate on grounding + "is this
a checkable fact", never on the fluent-sounding response score.

Tiers are domain-routed:
  • external-world fact ("who is X", "X's real name")  → web tier  → hedge
  • self / project / file fact ("do you remember…", code) → local tier → hedge
Both fall to an honest hedge floor when exhausted or offline.

Disable with ELI_GROUNDING_ESCALATION=0. Thresholds via env (see _cfg).
"""
from __future__ import annotations

import os
import re
import time
from typing import Any, Dict, Optional, Tuple

from eli.utils.log import get_logger

log = get_logger(__name__)


# --------------------------------------------------------------------------- #
# Config                                                                      #
# --------------------------------------------------------------------------- #
def _enabled() -> bool:
    return os.environ.get("ELI_GROUNDING_ESCALATION", "1").strip().lower() not in (
        "0", "false", "no", "off")


def _grounding_threshold() -> float:
    try:
        return float(os.environ.get("ELI_GROUNDING_ESCALATION_THRESHOLD", "0.55"))
    except Exception:
        return 0.55


# --------------------------------------------------------------------------- #
# Is this a checkable fact, and what domain?                                  #
# --------------------------------------------------------------------------- #
_BANTER_RE = re.compile(
    r"\b(fuck off|shut up|love ya|love you|thanks|thank you|how are you|how'?s the head"
    r"|you good|jump off|kill yourself|good morning|good night|cheers|haha|lol|wyd"
    r"|what'?s up|sup\b|yo\b)\b", re.I)
_OPINION_RE = re.compile(
    r"\b(do you (?:like|think|feel|prefer|reckon|believe)|what do you think"
    r"|your (?:opinion|favourite|favorite|take|thoughts)|how do you feel"
    r"|would you rather)\b", re.I)
_COMMAND_RE = re.compile(
    r"^(play|pause|stop|next|previous|skip|open|close|volume|mute|unmute|shuffle"
    r"|search|summari|analyse|analyze|create|generate|write|fix|run|set|remind"
    r"|read|show|list|take a|screenshot|speak|type|press|click)\b", re.I)
# Self / project / local-knowledge markers → local tier, never the web. Includes
# identity questions directed AT ELI ("who/what are you", "are you running…",
# "yourself") so they never get web-searched.
_LOCAL_RE = re.compile(
    r"\b(my|your|you're|youre|we|our|this (?:project|code|file|repo|machine)"
    r"|do you remember|you (?:said|told)|the code|our conversation|runtime|cognition"
    r"|persona|capabilit|database|sqlite|faiss|memory stack"
    r"|are you|who are you|what are you|you running|about yourself|yourself)\b", re.I)
_LOCAL_PATH_RE = re.compile(r"[~/]\w|\.\w{1,4}\b")
# Self-referential / conversational META — questions about ELI's OWN current
# activity, its just-made statements, or this conversation. These are answered
# from persona + conversation context (normal CHAT); escalating them to the
# web/memory grounding ladder is what produced robotic hedges and a degenerate
# "-" answer (Jason, 2026-06-05). Treated as NOT a checkable fact.
_META_SELF_RE = re.compile(
    r"\bwhat\s+(?:are|were)\s+you\s+(?:doing|busy|working\s+on|up\s+to|fixing|"
    r"talking\s+about|saying|on\s+about|getting\s+at)\b"
    r"|\bwhat'?s?\s+(?:up\s+with|going\s+on\s+with)\s+you\b"
    r"|\bhow\s+(?:do|did|can|could)\s+you\s+not\s+(?:know|remember)\b"
    r"|\bwhat\s+do\s+you\s+mean\b"
    r"|\bwhy\s+(?:did|are|would|do)\s+you\s+(?:say|said|saying|do|doing|think)\b",
    re.I)
# Relational / frustration venting directed at ELI or the situation — NOT a
# checkable fact. "what's/what is going on (with you)?", "what is happening?",
# "what's wrong/up with you?", "what is your problem?". Anchored so it does NOT
# swallow a genuine current-events query ("what is going on in Ukraine"), which
# routes elsewhere anyway. Reached here only on a low-grounding CHAT turn — the
# right move is persona CHAT, never the web/hedge ladder. (Jason, 2026-06-06:
# frustrated "what the fuck is going on?!" was hedging instead of responding.)
_RELATIONAL_VENT_RE = re.compile(
    r"\bwhat(?:'?s|\s+is|\s+are)?\s+(?:going\s+on|happening|the\s+matter)\b"
    r"(?!\s+(?:in|at|to|on|about|across|around|over)\b)"
    r"|\bwhat(?:'?s|\s+is)?\s+(?:wrong|up)\s+with\s+(?:you|u|this|it|that)\b"
    r"|\bwhat(?:'?s|\s+is)?\s+(?:your|the)\s+(?:problem|deal|issue)\b",
    re.I)
# Leading intensifier / profanity that frustrated users inject mid-phrase
# ("what THE FUCK are you talking about"), which otherwise breaks the meta/banter
# patterns and lets pure venting fall through to the factual classifier.
_INTENSIFIER_STRIP_RE = re.compile(
    r"\b(?:the\s+)?(?:fuck(?:ing)?|fuckin|hell|heck|bloody|goddamn(?:it)?|damn(?:ed)?"
    r"|frigging|friggin|freaking|freakin|fricking|frickin|bleeding|sodding)\b",
    re.I)
# Factual signal: third-party "who/what/when … is/was/real name", or a factual
# claim/correction the user is asserting.
_FACT_Q_RE = re.compile(
    r"\b(who|what|when|where|which|whose|how many|how old)\b[^?]*?\b"
    r"(is|are|was|were|did|does|born|real name|called|invented|wrote|won|"
    r"capital|located|founded|released)\b", re.I)
_FACT_KW_RE = re.compile(
    r"\breal name\b|\bborn (?:in|on)\b|\brelease date\b|\bhow old\b|\bhow many\b"
    r"|\bwhen (?:did|was|is)\b|\bcapital of\b|\bwho won\b|\bwho is\b|\bwho was\b", re.I)
_FACT_CLAIM_RE = re.compile(
    r"\b[\w.''-]+(?:'s)?\s+(?:real\s+)?name\s+is\b"          # "X's real name is Y"
    r"|\bit (?:was|is)\s+[\w.''-]+,?\s+not\s+[\w.''-]+",     # "it was X not Y"
    re.I)


def _is_degenerate(text: str) -> bool:
    """True for model output that must never be surfaced as an answer: empty,
    too short, or punctuation/symbol-only (e.g. a lone '-'). Such a generation
    falls through to the honest hedge instead of being shown to the user."""
    t = str(text or "").strip()
    if len(t) < 3:
        return True
    if not re.search(r"[A-Za-z0-9]", t):  # nothing alphanumeric at all
        return True
    return False


def classify_factual(text: str) -> Tuple[bool, str]:
    """Return (is_checkable_fact, domain) where domain ∈ {"external","local","none"}."""
    raw = (text or "").strip()
    low = raw.lower()
    if len(low.split()) < 2:
        return (False, "none")
    # Strip injected intensifiers/profanity so frustration phrased as a question
    # ("what the fuck are you talking about") still matches the meta/banter gates
    # instead of leaking into the factual classifier. Run the gates on the
    # cleaned text; keep `low` for the fact patterns (which are profanity-neutral).
    low_clean = _INTENSIFIER_STRIP_RE.sub(" ", low)
    low_clean = re.sub(r"\s+", " ", low_clean).strip()
    if (_BANTER_RE.search(low_clean) or _OPINION_RE.search(low_clean)
            or _COMMAND_RE.search(low_clean) or _META_SELF_RE.search(low_clean)
            or _RELATIONAL_VENT_RE.search(low_clean)):
        return (False, "none")

    is_fact = bool(
        _FACT_Q_RE.search(low_clean) or _FACT_KW_RE.search(low_clean)
        or _FACT_CLAIM_RE.search(raw)
    )
    if not is_fact:
        return (False, "none")

    if _LOCAL_RE.search(low) or _LOCAL_PATH_RE.search(raw):
        return (True, "local")
    return (True, "external")


# --------------------------------------------------------------------------- #
# Distil a clean web query from a messy/angry utterance                       #
# --------------------------------------------------------------------------- #
_PROFANITY_FILLER_RE = re.compile(
    r"\b(the fuck|what the fuck|who the fuck|idiot|dickhead|retard|stupid|fucking"
    r"|seriously|come on|jesus|christ|i meant|i mean|actually|just|please|now"
    r"|you|use the web to|do a|confirm|verify|search( for)?)\b", re.I)


def distill_query(text: str) -> str:
    q = re.sub(r"[^\w\s'’.-]", " ", text or "")
    q = _PROFANITY_FILLER_RE.sub(" ", q)
    q = re.sub(r"\s+", " ", q).strip(" .?!")
    return q[:120] or (text or "").strip()[:120]


# --------------------------------------------------------------------------- #
# Hedge floor                                                                 #
# --------------------------------------------------------------------------- #
def _hedge(domain: str, online: bool) -> str:
    if domain == "external" and not online:
        return ("I can't verify that right now — the net's off, and I won't guess at a "
                "fact I can't back up. Turn the Net toggle on and I'll look it up.")
    if domain == "local":
        return ("I don't have grounded evidence for that in my own memory/runtime, and I "
                "won't invent it. If you point me at the file or detail, I'll check properly.")
    return ("I'm not certain enough to answer that without confabulating, and I couldn't "
            "ground it just now — so I'd rather not guess. Want me to try a web search?")


# --------------------------------------------------------------------------- #
# The ladder                                                                  #
# --------------------------------------------------------------------------- #
def escalate(
    engine: Any,
    user_input: str,
    intent: Dict[str, Any],
    bus_result: Any,
    reasoning_mode: Optional[str] = None,
    trace: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Return a grounded/hedged result dict to short-circuit the CHAT answer, or
    None to let normal CHAT synthesis proceed."""
    if not _enabled():
        return None
    try:
        grounding = float(getattr(bus_result, "grounding_confidence", 0.0) or 0.0)
    except Exception:
        grounding = 0.0
    if grounding >= _grounding_threshold():
        return None  # already grounded enough — trust it

    is_fact, domain = classify_factual(user_input)
    if not is_fact:
        return None  # banter/opinion/command/chitchat — never escalate

    try:
        from eli.core.config import network_allowed
        online = bool(network_allowed())
    except Exception:
        online = False

    tiers = (["web", "hedge"] if domain == "external" else ["local_deepen", "hedge"])
    log.debug(f"[ESCALATION] factual={is_fact} domain={domain} grounding={grounding:.2f} "
              f"online={online} tiers={tiers}")

    for tier in tiers:
        try:
            if tier == "web":
                if not online:
                    continue  # can't reach the web — fall to hedge
                from eli.execution.executor_enhanced import execute as _execute
                q = distill_query(user_input)
                res = _execute("WEB_SEARCH", {"query": q})
                if isinstance(res, dict) and res.get("web_grounded") and res.get("results"):
                    evidence = str(res.get("content") or "")
                    answer = engine._synthesize_answer(
                        evidence, user_input, reasoning_mode=reasoning_mode,
                        action="WEB_SEARCH")
                    if answer and not _is_degenerate(answer):
                        return _result(answer, grounded=True, mode="escalation_web", trace=trace)
                # web reachable but no usable results → hedge
                continue

            if tier == "local_deepen":
                deep = _redispatch_broad(engine, user_input, intent)
                if deep is not None:
                    dg = float(getattr(deep, "grounding_confidence", 0.0) or 0.0)
                    if dg >= _grounding_threshold():
                        evidence = (deep.to_context_block()
                                    if hasattr(deep, "to_context_block") else "")
                        if evidence.strip():
                            answer = engine._synthesize_answer(
                                evidence, user_input, reasoning_mode=reasoning_mode,
                                action="SELF_REPORT")
                            if answer and not _is_degenerate(answer):
                                return _result(answer, grounded=True,
                                               mode="escalation_local", trace=trace)
                continue

            if tier == "hedge":
                msg = _hedge(domain, online)
                return _result(msg, grounded=False, mode="ungrounded_hedge", trace=trace)
        except Exception as _tier_err:
            log.debug(f"[ESCALATION] tier {tier} failed: {_tier_err}")
            continue
    return None


def _redispatch_broad(engine: Any, user_input: str, intent: Dict[str, Any]):
    """Re-run the AgentBus forcing a broad fan-out (local tier)."""
    try:
        from eli.cognition.agent_bus import get_bus
        _intent = dict(intent or {})
        _meta = dict(_intent.get("meta") or {})
        _meta["_force_broad_agents"] = True
        _intent["meta"] = _meta
        return get_bus().dispatch(
            user_input, _intent,
            session_id=getattr(engine, "session_id", ""),
            user_id=getattr(engine, "user_id", ""),
        )
    except Exception as e:
        log.debug(f"[ESCALATION] broad re-dispatch failed: {e}")
        return None


def _result(text: str, grounded: bool, mode: str, trace: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    text = str(text).strip()
    return {
        "ok": True,
        "action": "CHAT",
        "content": text,
        "response": text,
        "grounded": bool(grounded),
        "evidence_used": bool(grounded),
        "confidence": 0.9 if grounded else 0.5,
        "trace": trace or {},
        "meta": {"response_mode": mode, "grounding_escalated": True},
    }
