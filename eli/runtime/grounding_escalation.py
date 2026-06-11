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
# Stage 2: per-mode confidence targets + iterative deepening budget.           #
# Quick stays fast (0 deepen iters); deeper modes try harder and escalate the  #
# reasoning mode one tier per iteration to gather more before answering.       #
# --------------------------------------------------------------------------- #
_MODE_TARGET = {
    "quick": 0.45, "chain_of_thought": 0.55, "self_consistency": 0.65,
    "tree_of_thoughts": 0.75, "constitutional_ai": 0.80,
}
_MODE_MAX_ITERS = {
    "quick": 0, "chain_of_thought": 1, "self_consistency": 2,
    "tree_of_thoughts": 3, "constitutional_ai": 4,
}
_MODE_ORDER = ["quick", "chain_of_thought", "self_consistency",
               "tree_of_thoughts", "constitutional_ai"]


def _canon_mode(mode) -> str:
    try:
        from eli.cognition.reasoning_modes import canonical_mode
        return canonical_mode(mode)
    except Exception:
        return str(mode or "quick").strip().lower() or "quick"


def _mode_target(mode) -> float:
    return float(_MODE_TARGET.get(_canon_mode(mode), _grounding_threshold()))


def _mode_max_iters(mode) -> int:
    return int(_MODE_MAX_ITERS.get(_canon_mode(mode), 1))


def _next_mode(mode) -> str:
    key = _canon_mode(mode)
    try:
        i = _MODE_ORDER.index(key)
        return _MODE_ORDER[min(i + 1, len(_MODE_ORDER) - 1)]
    except ValueError:
        return key


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
# "-" answer (user-reported, 2026-06-05). Treated as NOT a checkable fact.
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
# right move is persona CHAT, never the web/hedge ladder. (user-reported, 2026-06-06:
# frustrated "what the fuck is going on?!" was hedging instead of responding.)
_RELATIONAL_VENT_RE = re.compile(
    r"\bwhat(?:'?s|\s+is|\s+are)?\s+(?:going\s+on|happening|the\s+matter)\b"
    r"(?!\s+(?:in|at|to|on|about|across|around|over)\b)"
    r"|\bwhat(?:'?s|\s+is)?\s+(?:wrong|up)\s+with\s+(?:you|u|this|it|that)\b"
    r"|\bwhat(?:'?s|\s+is)?\s+(?:your|the)\s+(?:problem|deal|issue)\b",
    re.I)
# Conversational meta — questions ABOUT this conversation itself or the user's/ELI's own past
# utterances in it ("when did I ask for that", "what did I say", "I never asked for that",
# "did you mention X earlier"). These are answered from the dialogue transcript (normal CHAT),
# NEVER web-searched or memory-graded: a low grounding score here means "look at what was said",
# not "I can't verify a fact". (user-reported 2026-06-09: "when exactly did i ask for that" was
# mis-routed to REFRESH_USER_INFO and deflected with "I can't check the history".)
_CONV_META_RE = re.compile(
    r"\b(?:when|where|what|how|why|did|do|have|has)\s+(?:exactly\s+)?(?:i|you|we)\s+"
    r"(?:ever\s+|even\s+|actually\s+)?"
    r"(?:ask(?:ed)?|say|said|request(?:ed)?|mention(?:ed)?|tell|told|claim(?:ed)?|"
    r"state[d]?|bring\s+up|brought\s+up|put\s+in|type[d]?|write|wrote)\b"
    r"|\bi\s+(?:never|didn'?t|did\s+not)\s+(?:ask(?:ed)?|say|said|request(?:ed)?|"
    r"mention(?:ed)?|tell|told)\b"
    r"|\bwhen\s+did\s+i\b",
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
# ELI's OWN action / artifact / job STATE — "did you save/create/generate X", "is it
# done", "check job N", "where did you save it", "what's the status/result of the job".
# Asserting any of these without grounding is the worst confabulation (the transcript
# invented "saved to ~/Documents/" and a fake "job complete"). Past-tense/completion
# framing only — bare "do you …" capability questions are deliberately excluded.
_SELF_ACTION_STATE_RE = re.compile(
    r"\b(?:did|have|has)\s+you\s+(?:ever\s+|actually\s+|not\s+|already\s+)*"
    r"(?:save[d]?|creat(?:e|ed)|writ(?:e|ten)|wrote|generat(?:e|ed)|made|stor(?:e|ed)|"
    r"produc(?:e|ed)|compil(?:e|ed)|export(?:ed)?|complet(?:e|ed)|finish(?:ed)?|ran|done)\b"
    r"|\b(?:is|was)\s+(?:it|that|the\s+\w+|job\s*#?\d+)\s+"
    r"(?:saved|done|finished|complete[d]?|ready|created|generated|written|stored|compiled)\b"
    r"|\bcheck\s+job\b|\bstatus\s+report\b"
    r"|\bwhere\s+(?:did\s+you\s+(?:save|put|store)|is\s+the\s+(?:file|doc|document|report|output))\b"
    r"|\bwhat'?s?\s+(?:the\s+)?(?:status|result[s]?|output|outcome)\s+(?:of\s+)?(?:job|the\s+job|it|that)\b",
    re.I)


def _self_claim_floor() -> float:
    """Grounding below this on a self-action/state question → hedge, don't confabulate."""
    try:
        return float(os.environ.get("ELI_SELF_CLAIM_FLOOR", "0.25"))
    except Exception:
        return 0.25


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
            or _RELATIONAL_VENT_RE.search(low_clean)
            or _CONV_META_RE.search(low_clean)):
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
    target = _mode_target(reasoning_mode)

    # ── Self-action / artifact-state confabulation floor ──────────────────────
    # ELI asserting it performed an action or produced an artifact it has NO grounding
    # for (saved a file, finished a job, generated a doc) is the worst confabulation.
    # When such a self-state question reaches CHAT with grounding essentially absent,
    # HEDGE in ANY mode (incl. quick) rather than let synthesis invent a status/path.
    # Real job/file queries route to CHECK_JOB/SUMMARIZE_FILE (grounded actions, not
    # CHAT) and never reach here; this only fires when CHAT is about to guess.
    if _SELF_ACTION_STATE_RE.search((user_input or "").lower()) and grounding < _self_claim_floor():
        try:
            from eli.core.config import network_allowed as _na
            _online = bool(_na())
        except Exception:
            _online = False
        log.debug(f"[ESCALATION] self-action/state claim grounding={grounding:.2f} "
                  f"< floor → honest hedge (no confabulated status/path)")
        return _result(_hedge("local", _online), grounded=False,
                       mode=_canon_mode(reasoning_mode), trace=trace)

    is_fact, domain = classify_factual(user_input)
    if not is_fact:
        return None  # banter/opinion/command/chitchat — never escalate

    try:
        from eli.core.config import network_allowed
        online = bool(network_allowed())
    except Exception:
        online = False

    # Trust the bus grounding ONLY when it actually validates the question. For an
    # OFFLINE EXTERNAL fact the local grounding score is a category error — memory/KG
    # can score high off loose token matches while the actual fact is unverifiable and
    # the web is unreachable — so such a turn MUST fall through to the hedge floor
    # rather than be answered from the model's weights (the confabulation this module
    # exists to prevent; the burkina-faso "third largest city's capital" case scored
    # "grounded" and was guessed instead of hedged). Local facts and online externals
    # still trust a sufficient grounding score.
    if grounding >= target and not (domain == "external" and not online):
        return None

    # Per-mode iterative-deepening budget. Quick = 0 (stays fast).
    max_iters = _mode_max_iters(reasoning_mode)
    # Quick mode skips SYNCHRONOUS *local* deepening — a low-grounding LOCAL fact
    # is handed to the async background-deepening path instead, keeping the turn
    # fast. But EXTERNAL facts still run the web/hedge tiers below in EVERY mode:
    # the honest HEDGE floor must never be skipped just because the turn ran in
    # quick mode, or the model silently confabulates (the bug this module exists
    # to prevent). The local-deepen loop itself also no-ops at 0 iters.
    if domain == "local" and max_iters <= 0:
        return None

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
                # Iterative deepening: re-dispatch the bus broadly, escalating the
                # reasoning mode one tier per iteration (so each pass gets a bigger
                # agent time budget — Stage 1b), until grounding crosses this mode's
                # target or the per-mode iteration budget is spent. Stop early on
                # no improvement. Quick is already excluded (max_iters=0).
                best_deep = None
                best_dg = grounding
                cur_mode = _canon_mode(reasoning_mode)
                for _i in range(max_iters):
                    cur_mode = _next_mode(cur_mode)  # quick→normal→advanced→research→expert
                    # Stage 3a: each iteration also gathers MORE evidence (counts),
                    # not just more time — 1.5×, 2.0×, 2.5×, … (capped).
                    _gather_mult = min(3.0, 1.0 + 0.5 * (_i + 1))
                    deep = _redispatch_broad(engine, user_input, intent,
                                             reasoning_mode=cur_mode,
                                             gather_mult=_gather_mult)
                    if deep is None:
                        break
                    dg = float(getattr(deep, "grounding_confidence", 0.0) or 0.0)
                    log.debug(f"[ESCALATION] deepen iter={_i + 1}/{max_iters} "
                              f"mode={cur_mode} grounding={dg:.2f} target={target:.2f}")
                    if dg > best_dg:
                        best_dg, best_deep = dg, deep
                    if dg >= target:
                        break
                    # no-improvement break: another pass won't help
                    if dg <= grounding:
                        break
                if best_deep is not None and best_dg >= target:
                    evidence = (best_deep.to_context_block()
                                if hasattr(best_deep, "to_context_block") else "")
                    if evidence.strip():
                        answer = engine._synthesize_answer(
                            evidence, user_input, reasoning_mode=cur_mode,
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


def _redispatch_broad(engine: Any, user_input: str, intent: Dict[str, Any],
                      reasoning_mode: Optional[str] = None,
                      gather_mult: float = 1.0):
    """Re-run the AgentBus forcing a broad fan-out (local tier), at the given
    reasoning mode (→ larger agent time budget) and gather multiplier (→ more
    evidence gathered per pass)."""
    try:
        from eli.cognition.agent_bus import get_bus
        _intent = dict(intent or {})
        _meta = dict(_intent.get("meta") or {})
        _meta["_force_broad_agents"] = True
        _intent["meta"] = _meta
        if gather_mult and gather_mult != 1.0:
            _intent["_gather_mult"] = float(gather_mult)
        return get_bus().dispatch(
            user_input, _intent,
            session_id=getattr(engine, "session_id", ""),
            user_id=getattr(engine, "user_id", ""),
            reasoning_mode=reasoning_mode,
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
