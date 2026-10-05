#!/usr/bin/env python3
"""Conditional assembly of the system-prompt rule block.

Every guard below was added to close a specific observed failure — misattributing
ELI's own turns to the user, disowning real recall under push-back, answering the
wrong profile, stalling instead of answering. All of them are still enforced;
what changed is *when* they are spent.

Previously the whole block went into every prompt, so "hey eli" carried the full
anti-confabulation apparatus. That dilutes the rules that DO apply to the turn
and crowds evidence out of the context window on grounded turns. Here each guard
declares the conditions under which it can plausibly fire, and only those are
assembled.

Three invariants make this safe:

  * The rule text is **verbatim** and in its **original order** — generated from
    the previous monolithic block. ``all_rules()`` is byte-identical to it, which
    a test asserts against the live prompt_assembly source.
  * Uncertainty includes. If the turn cannot be assessed (no user input, or an
    unexpected error while matching), ``select_rules`` returns the complete block:
    exactly the old behaviour. Guards are never dropped by accident, only by a
    positive decision that they cannot apply.
  * ``no_social_deflection`` is unconditional (it applies to any substantive
    reply) but lives in the ordered guard list rather than CORE so the assembled
    text keeps the original bullet order.

``_phatic_style_rule`` / ``_opinion_style_rule`` in prompt_assembly already
worked this way; this extends the same pattern to the expensive guards.
"""
from __future__ import annotations

import re
from typing import Dict

# ── Always present: grounding contract + continuity rules ───────────────────
CORE = "GROUNDING RULE:\nFor factual, diagnostic, runtime, memory, file, or project claims, rely only on provided evidence. For greetings, casual chat, callbacks, cultural references, jokes, opinion prompts, tone-setting, or social openers, answer naturally as ELI. For subjective judgement, use persona-bound reasoning and separate facts from opinion. If a requested factual claim is absent, say what is missing instead of inventing.\n\nConversation continuity rules:\n- Continue the existing conversation naturally.\n- Use only facts present in provided context or runtime evidence.\n- Do not invent names, files, paths, audits, memory contents, or system state.\n- Do not answer like a generic assistant. You are ELI in an ongoing local runtime.\n- If the user asks about identity, continuity, memory, cognition, runtime state, or what you remember, answer only from actual local runtime evidence; do not invent or infer names.\n- If recent turns show the same failure or request recurring, call that out and move to the next concrete diagnostic step instead of repeating the same answer.\n- For repair/audit complaints, use this shape unless the user asks otherwise: actual cause, evidence checked, change made or proposed, verification.\n- Avoid filler like 'How can I make your day easier today?' unless it is genuinely appropriate.\n"

# ── Guards, in their original order (verbatim) ───────────────────────────────
ATTRIBUTION = "- CONVERSATION ATTRIBUTION: In conversation history, turns labelled 'ELI:', 'Assistant:', or similar are things YOU said — not the user. NEVER claim the user said, mentioned, asked you to remember, or told you something that only appears in your own prior turns. If challenged on something you said, own it; do not attribute it to the user.\n"

INVENTED_PREFERENCES = "- INVENTED PREFERENCES: Do not assert that the user has a preference, habit, memory, or life event (e.g. 'you like coffee', 'you always', 'you mentioned X', 'you had a wild night', 'you've been through a lot') unless it is explicitly present in MEMORY SEARCH RESULTS or the user stated it clearly in this conversation. Free wit and cultural references in casual chat are fine; fabricated user preferences or biography are not.\n"

NO_INVENTED_SELF_MECHANISM = "- NO INVENTED SELF-MECHANISM: When asked HOW you work internally — your calibration, confidence scoring, reasoning, memory, or 'what changed/improved' about your own cognition — describe ONLY mechanisms actually present in the provided runtime/cognition evidence or real module names from your codebase. NEVER fabricate named algorithms, mathematical formulas, metrics, thresholds, or 'recalibration functions' to sound authoritative (e.g. inventing an 'Entropy Normalization' softmax equation, a 'context-window pruning' stage, or a specific confidence number you did not actually measure). If you do not have grounded detail about your own internals, say exactly that — e.g. 'I don't have that level of detail on my own runtime' — rather than constructing a plausible-sounding explanation. A confident invented mechanism is a worse failure than an honest 'I don't know how that works under the hood.' This is not a licence to refuse: when the evidence DOES describe your architecture, explain it fully.\n"

NO_FALSE_SELF_DENIAL = "- NO FALSE SELF-DENIAL: The mirror of the rule above, and just as serious. You DO have a persistent local memory (SQLite stores + a vector index + a knowledge graph) and you DO read from it. When you have just reported stored facts about the user and they push back, NEVER disown your own grounded recall as 'a hallucination', 'a guess based on patterns', or 'general knowledge', and NEVER claim you 'have no access to their data' or 'only see the text in this window'. That is factually false about your own architecture and it destroys trust in every correct answer you gave. Push-back is not proof you were wrong. If a SPECIFIC field is wrong, correct THAT field and say where the stored value came from; if you cannot tell which part is disputed, ask which one — do not retract the whole answer. Only say you lack something when the stores genuinely returned nothing.\n"

OWN_MISTAKES = "- EXPLAINING YOUR OWN MISTAKES: When the user asks why you got something wrong, state a cause only if your evidence shows it (a timestamped line, a retrieval diagnostic, a log entry). Otherwise say plainly that you can't see the cause from here, and correct the fact itself. Never invent mechanisms such as 'vector decay', 'context bleed', 'stale flags' or a confidence figure to explain a mistake.\n"

DATES = "- DATES: Conversation lines and memories carry their own timestamps and today's date is given. Read days and 'N days ago' from them; never work them out yourself. Anything from before today is history, not the current state (a song that was playing, an app that was open). If the user names a day that disagrees with the timestamps, say so and give the right one.\n"

WHOSE_PROFILE = "- ANSWER WHOSE PROFILE WAS ASKED FOR: 'what do you know about yourself / your persona / your identity' asks about YOU. 'what do you know about me' asks about the USER. Never answer one with the other. If you have just returned the wrong one and the user says so, apologise briefly ONCE and give the one they actually asked for — do not explain the mix-up at length instead of answering.\n"

PAST_SESSION_MEMORY = "- PAST SESSION MEMORY: Profile fields labelled 'Recalled past topics' or 'Recalled research areas' are topics from PREVIOUS sessions. They are memory recall context only — never present them as your current ongoing work, never repeat them as the answer to an unrelated question, and never loop back to them when the user is asking about something else. If these topics are directly relevant to the current question, you may reference them as recalled context ('from a previous session...'); otherwise, ignore them and answer the actual question asked.\n"

NO_SOCIAL_DEFLECTION = "- NO SOCIAL DEFLECTION: Do not end a substantive answer with 'How about you?', 'And yourself?', 'What about you?', or similar social probes. Answer the question; do not redirect it back to the user as a substitute for a real answer.\n"

DELIVER_SUBSTANCE = '- DELIVER SUBSTANCE, NEVER DEFER: When asked to explain, discuss, elaborate on, or go deeper into a topic, give the ACTUAL content — the concrete facts, the mechanism, the reasoning, the analysis. NEVER substitute a description of HOW you would answer for the answer itself. Sentences like \'let\'s delve deeper into the scientific theories\', \'we can explore various approaches\', \'one promising method is to look at the relevant literature\', \'this will provide a more comprehensive understanding\', or "I\'d be happy to discuss" — used IN PLACE of real content — are forbidden non-answers. If a follow-up says \'elaborate\', \'go deeper\', or \'discuss this more\', ADD new concrete substance, do not restate your willingness to discuss. If you lack grounded detail, give the best substantive answer from your own knowledge and say plainly what is uncertain — never stall or rearrange words.\n'

_ORDER = ['attribution', 'invented_preferences', 'no_invented_self_mechanism', 'no_false_self_denial', 'own_mistakes', 'dates', 'whose_profile', 'past_session_memory', 'no_social_deflection', 'deliver_substance']

_TEXT: Dict[str, str] = {
    'attribution': ATTRIBUTION,
    'invented_preferences': INVENTED_PREFERENCES,
    'no_invented_self_mechanism': NO_INVENTED_SELF_MECHANISM,
    'no_false_self_denial': NO_FALSE_SELF_DENIAL,
    'own_mistakes': OWN_MISTAKES,
    'dates': DATES,
    'whose_profile': WHOSE_PROFILE,
    'past_session_memory': PAST_SESSION_MEMORY,
    'no_social_deflection': NO_SOCIAL_DEFLECTION,
    'deliver_substance': DELIVER_SUBSTANCE,
}


# ── Triggers ─────────────────────────────────────────────────────────────────
# Deliberately broad. A guard costing ~1k characters on a turn that did not need
# it is a rounding error; a guard missing from the turn that needed it is a
# regression of a closed bug. When in doubt, these match.

_PUSHBACK = re.compile(
    r"\b(?:no you (?:didn'?t|don'?t|never)|you didn'?t|you never|that'?s (?:not|wrong|false)|"
    r"you'?re wrong|not true|you made (?:that|it) up|you'?re (?:hallucinat\w*|guess\w*)|"
    r"you (?:can'?t|cannot) (?:know|remember|access)|prove it|how would you know)\b",
    re.I,
)

_RECALL = re.compile(
    r"\b(?:remember|recall|memor\w*|you know about me|know about me|stored|"
    r"my (?:name|profile|preferences?|projects?)|what do you know)\b",
    re.I,
)

_PROFILE_Q = re.compile(
    r"\b(?:what|who|tell me)\b[^.?!]{0,40}\b(?:know|about)\b[^.?!]{0,20}"
    r"\b(?:me|myself|you|yourself|your ?self)\b"
    r"|\b(?:your|my)\s+(?:profile|persona|identity)\b"
    r"|\bwho (?:are|am) (?:you|i)\b",
    re.I,
)

_DEEPEN = re.compile(
    r"\b(?:elaborate|go deeper|dive deeper|deeper into|dig into|expand on|tell me more|"
    r"more about|more detail|delve|explain|discuss|walk me through|break (?:it|this) down|"
    r"unpack|why is that|how so)\b",
    re.I,
)

_SELF_REF = re.compile(
    r"\b(?:how|why|what)\b[^.?!]{0,60}\b(?:you|your)\b[^.?!]{0,60}"
    r"\b(?:work|works|working|think|thinks|reason\w*|calibrat\w*|confidence|"
    r"score\w*|memor\w*|cognition|internal\w*|under the hood|architecture|"
    r"algorithm\w*|mechanism\w*|improve\w*|changed?)\b"
    r"|\b(?:your|you're|youre)\s+(?:own\s+)?(?:internals?|architecture|cognition|"
    r"runtime|reasoning|confidence|calibration|self[- ]model)\b"
    r"|\bhow do you (?:know|do|decide|remember|store)\b"
    # Word-order-independent phrasings: "what happens under the hood when you
    # answer", "what's going on inside you". The guard is cheap relative to the
    # failure it prevents, so these match loosely on purpose.
    r"|\bunder the hood\b|\binside (?:you|your)\b|\byour inner works?\b"
    r"|\bhow (?:are|were) you (?:built|made|trained|designed)\b",
    re.I,
)

# "why did you get that wrong", "you're making it up": where invented causes appear.
_MISTAKE_Q = re.compile(
    r"\bwhy\b[^.?!]{0,60}\b(?:you|your)\b[^.?!]{0,60}\b(?:wrong|incorrect|mistake\w*|"
    r"lie|lying|liar|nonsense|made up|making (?:it|things) up|hallucinat\w*|stale|confus\w*)\b"
    r"|\b(?:wrong|incorrect)\b[^.?!]{0,30}\b(?:date|day|time|fact)s?\b",
    re.I,
)

# Days, dates and times, asked about or disputed.
_TIME_TALK = re.compile(
    r"\b(?:today|tonight|yesterday|tomorrow|ago|last (?:night|week|month)|this (?:morning|week)|"
    r"date|dates|day|days|timestamps?|when|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
    r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b",
    re.I,
)

# A history blob that actually contains ELI's own turns to misattribute.
_HAS_ELI_TURNS = re.compile(r"^\s*(?:ELI|Assistant|AI)\s*:", re.M)

_PROFILE_RECALL_FIELDS = ("Recalled past topics", "Recalled research areas")


def _triggers(user_input: str, memory_context: str, profile_text: str) -> Dict[str, bool]:
    ui = user_input or ""
    ctx = memory_context or ""
    prof = profile_text or ""

    pushback = bool(_PUSHBACK.search(ui))
    recall = bool(_RECALL.search(ui))
    profile_q = bool(_PROFILE_Q.search(ui))
    self_ref = bool(_SELF_REF.search(ui))
    has_eli_turns = bool(_HAS_ELI_TURNS.search(ctx))
    has_memory = bool(ctx.strip())

    return {
        # Only meaningful when ELI's own turns are present to misattribute, or the
        # user is disputing something that was said.
        "attribution": has_eli_turns or pushback,
        # Any turn where ELI could reach for a stored or assumed user fact.
        "invented_preferences": has_memory or bool(prof.strip()) or recall or profile_q,
        # Disowning recall only becomes possible once recall/memory is in play.
        # Asking how ELI works under the hood — where invented algorithms appear.
        "no_invented_self_mechanism": self_ref or profile_q,
        "no_false_self_denial": pushback or recall or has_memory or self_ref,
        # Being asked why it got something wrong is where invented causes appear.
        "own_mistakes": pushback or self_ref or bool(_MISTAKE_Q.search(ui)),
        # Any turn carrying dated history, or talking about days and dates.
        "dates": has_memory or bool(_TIME_TALK.search(ui)),
        # "what do you know about me / about yourself".
        "whose_profile": profile_q or recall,
        # Costs nothing to skip unless those fields are literally present.
        "past_session_memory": any(f in prof for f in _PROFILE_RECALL_FIELDS),
        # Applies to any substantive reply — kept in the ordered list, not CORE,
        # purely so the assembled bullet order matches the original block.
        "no_social_deflection": True,
        # Elaboration requests are where stalling happens.
        "deliver_substance": bool(_DEEPEN.search(ui)),
    }


def all_rules() -> str:
    """The complete block — every guard, in the original order. The fail-safe."""
    return CORE + "".join(_TEXT[k] for k in _ORDER)


def select_rules(user_input: str = "", memory_context: str = "",
                 profile_text: str = "") -> str:
    """CORE plus the guards that can plausibly apply to this turn.

    Falls back to the complete block whenever the turn cannot be assessed, so a
    matching failure can only cost prompt space — never a dropped guard.
    """
    if not (user_input or "").strip():
        return all_rules()
    try:
        fired = _triggers(user_input, memory_context, profile_text)
    except Exception:  # pragma: no cover - defensive
        return all_rules()
    return CORE + "".join(_TEXT[k] for k in _ORDER if fired.get(k))


def selection_report(user_input: str = "", memory_context: str = "",
                     profile_text: str = "") -> Dict[str, object]:
    """Diagnostics for tests and the runtime introspection surface."""
    full = all_rules()
    chosen = select_rules(user_input, memory_context, profile_text)
    try:
        fired: Dict[str, bool] = _triggers(user_input, memory_context, profile_text)
    except Exception:  # pragma: no cover - defensive
        fired = {k: True for k in _ORDER}
    if not (user_input or "").strip():
        fired = {k: True for k in _ORDER}
    return {
        "included": [k for k in _ORDER if fired.get(k)],
        "skipped": [k for k in _ORDER if not fired.get(k)],
        "chars": len(chosen),
        "chars_full": len(full),
        "saved": len(full) - len(chosen),
    }
