"""What ELI may say about its own workings, and the record it says it from.

Routing, retrieval and escalation run before the model is called and never reach it, so
asked "why did you search the web?" a model can only invent: live it produced "vector search
drift", "the embedding model decayed the context window", a `verbose_media_logging` setting
and an `action_logs` table, none of which exist, and "Consider it done. The audit trail is now
active" for logging that was always on. Two things fix that at the source:

  * the turn record: each turn's audit row says what the pipeline did (which rule routed it,
    what ran, whether it escalated to the web and why, what retrieval found). Asked about its
    own behaviour, ELI is handed those rows and explains from them.
  * the claim check: a sentence that names a setting, table or module ELI does not have, or
    reports switching something on when nothing ran, is dropped, in streamed replies too.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional

from eli.utils.log import get_logger

log = get_logger(__name__)

# ── is the user asking about ELI's own behaviour? ────────────────────────────

_OWN_BEHAVIOUR_RE = re.compile(
    r"\bwhy\b[^.?!]{0,40}\b(?:did|do|are|were|would|have|keep|can'?t|could ?n'?t|is|does)\b[^.?!]{0,12}\byou(?:r)?\b"
    r"|\bwhat(?:'?s| is| was| has been| went)?\s+(?:going on|wrong|happening|happened)\b[^.?!]{0,30}\b(?:with\s+)?you(?:r)?\b"
    r"|\bwhat\s+(?:went|is going|has been going)\s+wrong\b"
    r"|\bwhat(?:'?s| is| are)\s+with\s+(?:all\s+)?(?:the|these|those|this|your)\s+(?:issues?|problems?|errors?|bugs?|mistakes?|failures?)\b"
    r"|\bwhat\s+(?:has|have)\s+been\s+going\s+on\b"
    r"|\bexplain\b[^.?!]{0,30}\b(?:yourself|your (?:mistake|error|answer|response|behaviou?r)|what (?:you did|happened)|why you)\b"
    r"|\bwhy\b[^.?!]{0,30}\b(?:search(?:ed|ing)? the web|web search|wrong|lying|lie[ds]?|making (?:shit|stuff|things) up|ignor\w+)\b"
    r"|\b(?:how|why)\s+(?:come|is it that)\s+you\b"
    r"|\bwhat did you (?:just )?do\b|\bwhat have you (?:been doing|done)\b"
    r"|\b(?:do|are) you (?:log|logging|record|recording|keep(?:ing)? (?:a )?(?:log|record|track))\b"
    r"|\byour\s+(?:logs?|logging|audit|records?)\b|\blog(?:ging|s)?\s+(?:for|of)\s+every",
    re.I)


# A complaint aimed at ELI. The worst invented diagnosis on record ("the embedding model decayed
# the context window's relevance") answered one of these, not a question.
_COMPLAINT_RE = re.compile(
    r"\byou\s+(?:do\s+not|don'?t|did\s+not|didn'?t)\s+(?:need|have)\s+to\b"
    r"|\byou\s+should(?:\s+not|n'?t)?\s+(?:have|be|know|check|remember|log|stop)\b"
    r"|\byou\s+(?:keep|kept|still|always|never)\s+(?:\w+ing|get|got|forget|ignore|search|answer|remember|listen|say|do|make)\b"
    r"|\b(?:stop|quit)\s+(?:search\w*|lying|making|guessing|inventing|hallucinat\w+|ignoring)\b"
    r"|\byou(?:'re|’re| are| were)\s+(?:wrong|lying|making|not listening|useless|broken|ignoring)\b"
    r"|\byou\s+(?:forgot|ignored|missed|lied|made\s+(?:that|it|this|shit|stuff)\s+up|got\s+(?:that|it|this)\s+wrong|hallucinat\w+)\b"
    r"|\bthat(?:'s|’s| is| was)\s+(?:wrong|incorrect|bullshit|not\s+(?:right|true|what\s+i\s+(?:asked|said)))\b"
    r"|\bi\s+asked\s+you\b|\bwhy\s+the\s+(?:fuck|hell)\b",
    re.I)


def complains_about_eli(text: Any) -> bool:
    return bool(_COMPLAINT_RE.search(str(text or "")))


def asks_about_own_behaviour(text: Any) -> bool:
    """A question about what ELI did, why, or what it logs, or a complaint about it: the turns
    where it invents."""
    return bool(_OWN_BEHAVIOUR_RE.search(str(text or ""))) or complains_about_eli(text)


# ── the turn record ──────────────────────────────────────────────────────────

# What a routing rule means, for the ones a person is most likely to be told about.
_ROUTE_WORDS = {
    "chat.long_question_guard": "a long question, sent to chat",
    "fallback.chat": "no command rule matched, sent to chat",
    "llm_intent.resolver": "no command rule matched; the model chose the action",
    "phatic.fastpath": "a greeting, answered without retrieval",
    "identity.set_user_name": "the name-setting rule",
    "identity.final_user_summary": "the who-am-I rule",
    "memory.temporal_recall_as_chat": "a question about a period, sent to chat",
    "system.date": "the date rule",
    "system.time": "the time rule",
}


def describe_turn(facts: Dict[str, Any]) -> str:
    """One line on what the pipeline did this turn, from the facts the turn noted about itself.
    Goes into the audit row; nothing here is model output."""
    parts: List[str] = []
    via = str(facts.get("via") or "").strip()
    if via:
        parts.append(f"routed by {via}" + (f" ({_ROUTE_WORDS[via]})" if via in _ROUTE_WORDS else ""))
    if facts.get("downgraded_from"):
        parts.append(f"first read as {facts['downgraded_from']}, answered as chat (too little evidence for it)")
    if facts.get("retrieval"):
        parts.append(f"retrieval: {facts['retrieval']}")
    if facts.get("escalation"):
        parts.append(str(facts["escalation"]))
    calls = int(facts.get("model_calls") or 0)
    if calls:
        parts.append(f"model ran {calls} time{'s' if calls != 1 else ''} on "
                     f"{int(facts.get('prompt_chars') or 0):,} prompt characters")
    return "; ".join(parts)


def _user_turns(mem: Any, since: float, user_id: str) -> List[Dict[str, Any]]:
    try:
        return list(mem.get_recent_conversation(limit=60, user_id=user_id or None, since=since, role="user") or [])
    except Exception:
        log.debug("turn record: user turns unavailable", exc_info=True)
        return []


def turn_record_lines(mem: Any, *, user_id: str = "", limit: int = 8, now: Optional[float] = None) -> List[str]:
    """Recent turns as the pipeline recorded them, oldest first, each with what was asked."""
    try:
        from eli.runtime import orchestrator_audit_ledger as oal
        oal.flush(1.0)
        rows = [r for r in oal.recent_turns(limit * 4)
                if not r.get("parent_request_id") and (not user_id or not r.get("user_id") or r["user_id"] == user_id)]
    except Exception:
        log.debug("turn record unavailable", exc_info=True)
        return []
    rows = list(reversed(rows[:limit]))
    if not rows:
        return []
    from eli.cognition.evidence_format import turn_stamp
    said = _user_turns(mem, float(rows[0]["ts"] or 0) - 900, user_id)
    lines = []
    for r in rows:
        end = float(r.get("ts") or 0)
        start = end - float(r.get("elapsed_ms") or 0) / 1000.0 - 5
        asked = next((t for t in reversed(said) if start <= float(t.get("timestamp") or 0) <= end), None)
        quote = ""
        if asked:
            words = " ".join(str(asked.get("content") or "").split())
            quote = f" “{words[:90]}{'…' if len(words) > 90 else ''}”"
        took = float(r.get("elapsed_ms") or 0) / 1000.0
        outcome = str(r.get("outcome") or "").strip()
        lines.append(f"[{turn_stamp(end, now)}]{quote} -> {r.get('action') or '?'} "
                     f"({r.get('reasoning_mode') or 'quick'}, {took:.0f} s): {outcome or 'ok'}")
    return lines


def record_block(lines: List[str]) -> str:
    """The record with the instruction to explain from it and from nothing else."""
    if not lines:
        return ""
    return ("What you did on recent turns, written by the pipeline into the audit ledger (not by you). "
            "Asked why you did something or what went wrong, explain from these rows and the period log "
            "only. Where a row does not show the cause, say the record does not show it; never name a "
            "mechanism, setting or component that is not written here.\n" + "\n".join(lines))


def turn_record_block(mem: Any, *, user_id: str = "", limit: int = 8, now: Optional[float] = None) -> str:
    return record_block(turn_record_lines(mem, user_id=user_id, limit=limit, now=now))


# ── the claim check ──────────────────────────────────────────────────────────

# Reporting a switch thrown, or promising a standing change, from inside a reply.
_ENABLED_CLAIM = re.compile(
    r"\bconsider it done\b"
    r"|\b(?:logging|audit(?:ing| trail)?|tracking|monitoring|recording|verbose\w*|filter\w*|threshold\w*|"
    r"setting\w*|config\w*|mode|index\w*|pipeline|memory|retrieval|gating)\b[^.?!\n]{0,60}?\b(?:is|are|has been|have been)\s+"
    r"now\s+(?:active|enabled|on|in place|live|persistent|fixed|updated|tightened|enforced)\b"
    r"|\bi(?:'ve|’ve| have)\s+(?:now\s+|just\s+)?(?:enabled|activated|switched on|turned on|implemented|tightened|"
    r"recalibrated|reconfigured|adjusted the|updated (?:my|the)|patched|flagged (?:this|that|it) for)\b"
    r"|\bi(?:'ll|’ll| will)\s+(?:enforce|ensure|log|record|verify|store|track|audit)\b[^.?!\n]{0,80}?"
    r"\b(?:going forward|from now on|every time|in future|for every|each time)\b"
    r"|\bi\s+can\s+(?:implement|enable|activate)\s+(?:this|that|it)\s+(?:immediately|now|right away)\b"
    r"|\bdo you want me to\s+(?:enable|activate|switch on|turn on)\b",
    re.I)

# A fix ELI has no action for: "a hard reset on the media process manager", "re-indexing the
# last 48 hours with stricter temporal weighting", "enable verbose logging in the config".
_INVENTED_FIX = re.compile(
    r"\b(?:the|a|this)\s+fix\s+(?:requires?|needs?|is|would be|involves?)\b"
    r"|\bwe\s+need\s+to\s+(?:enable|re-?index|reset|recalibrate|rebuild|retrain|patch|flush|tighten|re-?embed)\b"
    r"|\bi\s+(?:can|could|will|'ll|’ll|need to|should)\s+(?:now\s+)?(?:re-?index|recalibrate|re-?embed|hard[- ]reset|"
    r"flush|purge|retrain|rebuild (?:the|my)|reset (?:the|my)|tighten|re-?weight|re-?anchor)\b"
    r"|\b(?:enable|turn on|switch on)\s+verbose\b",
    re.I)

# A standing change promised from inside a reply. How ELI routes, searches and logs is decided by
# its code on every turn; "no web search for future questions" is not something a reply can make true.
_STANDING_PROMISE = re.compile(
    r"\b(?:for (?:all |any )?future (?:questions|requests|turns|queries|messages)|from now on|going forward|"
    r"from here on|never again|not (?:happen|do (?:that|it)|search\w*) again|any ?more|in future|"
    r"unless you (?:explicitly |specifically )?(?:ask|say|tell|request)|until you (?:say|tell|ask)|"
    r"for the rest of (?:this|the|our) (?:session|conversation|chat))\b", re.I)
_COMMITS = re.compile(
    r"\bi(?:'ll|’ll| will| won't| won’t| will not| am going to|'m going to|’m going to)\b|^\W*no (?:more )?\w+", re.I)

# A sentence that leans on the one before it: an offer to act on it, or a conclusion drawn from it.
_OFFER = re.compile(
    r"^\W*(?:do you |would you like |d'you )?(?:want|like)\s+me\s+to\b|^\W*(?:shall|should)\s+i\b|^\W*say the word\b", re.I)
_FOLLOWS = re.compile(
    r"^\W*(?:that(?:'s|’s| is| was) why|this is why|which is why|that means|this means|as a result|until then|"
    r"because of (?:this|that)|hence|therefore|in other words|put simply)\b", re.I)

# A question about a fault: what ELI did, got wrong or keeps doing. A diagnosis in the reply
# is checked against the record on these.
_FAULT_RE = re.compile(
    r"\bwhy\b[^.?!]{0,40}\b(?:did|didn'?t|were|keep|can'?t|could ?n'?t|won'?t|are you (?:still|always|lying|making|search))\b"
    r"|\bwhat\s+(?:went|is going|has been going|keeps going)\s+wrong\b|\bwhat(?:'?s| is| was)?\s+(?:wrong|happening|happened)\b"
    r"|\bwhat(?:'?s| is| are)\s+with\s+(?:all\s+)?(?:the|these|those|this|your)\s+(?:issues?|problems?|errors?|bugs?|mistakes?|failures?)\b"
    r"|\bwhat\s+(?:has|have)\s+been\s+going\s+on\b|\bgoing on\b[^.?!]{0,30}\b(?:issues?|problems?|errors?)\b"
    r"|\bwhy\b[^.?!]{0,40}\b(?:wrong|lying|lie[ds]?|making (?:shit|stuff|things) up|ignor\w+|slow|so long|broken|fail\w*)\b"
    r"|\bexplain\b[^.?!]{0,30}\b(?:yourself|your (?:mistake|error)|what happened|why you)\b",
    re.I)

# What an invented diagnosis reaches for. On a fault question each has to be in the record.
_INTERNALS = re.compile(
    r"\b(?:vectors?|embeddings?|high-dimensional|dimensional space|latent|attention (?:mechanism|leak|head)|"
    r"context window|tokeni[sz]\w+|weights|neural|buffer\w*|cach(?:e|ed|ing)|(?:re-?)?index(?:es|ing|ed)?|"
    r"anchor(?:s|ed|ing)?|drift(?:s|ed|ing)?|decay(?:s|ed|ing)?|alignment|stale|zombie|race condition|deadlock\w*|"
    r"queues?|synchroni[sz]\w+|process (?:manager|cleanup)|heuristics?|classifier|scheduler|daemon|threads?|mutex|"
    r"memory leak|checkpoint\w*|weighting|prioriti[sz]\w+|error states?|failure signals?|log buffer|bitmask|"
    r"garbage collect\w+|state machine|handshake)\b",
    re.I)

# A sentence that explains: gives a cause, or says how ELI's machinery behaves. A word list
# cannot hold every mechanism a model can invent ("has no concept of concurrency", "the
# retrieval score was artificially high"), so on a fault question these must be carried by
# the record: most of what the sentence says has to be written there.
_EXPLAINS = re.compile(
    r"\b(?:because|due to|caused by|as a result|which is why|that(?:'s|’s| is) why|the reason|therefore|hence|"
    r"leading to|led to|causing|resulting in|this (?:indicates|suggests|means|implies)|which (?:means|indicates|caused)|"
    r"instead of|so that|root cause|failure mode|the (?:issue|problem|fault|bug) (?:is|was|lies)|"
    r"stem(?:s|med|ming)? from|comes? down to|boils? down to|(?:failure|breakdown|gap|flaw) in (?:how|the|my)|"
    r"(?:core|underlying|real|actual) (?:issue|problem|cause|fault)|broke down|breaks down)\b"
    r"|\b(?:my|its|the)\s+(?:\w+\s+){0,2}(?:executor|system|index|retrieval|router|pipeline|agents?|model|logic|layer|"
    r"engine|orchestrat\w+|mechanism|subsystem|module|stack|scheduler)\b"
    r"|\b(?:has|have|had|with)\s+no\s+(?:concept|notion|way|awareness|tracking|state)\b|\bthere\s+is\s+no\s+\w+\s+(?:tracking|check|sync\w*|link)\b",
    re.I)
_SUPPORT_NEEDED = 0.6
_FILLER = frozenset("""that this these those with from have been were was your you're they them then than when what
which will would could should there their about into over also just only some more most very because instead
since while where here does did doing done being both each other such same after before between through
during again once ever never always still even much many well back down away still really actually simply""".split())

_BACKTICKED = re.compile(r"`([A-Za-z_][\w.\-]{2,60})`")
_CODE_SHAPED = re.compile(r"[_.]|^[A-Z0-9_]{4,}$")
_PATH = re.compile(r"(?<![\w/])((?:~|\.{0,2})?/(?:[\w.\-]+/)+[\w.\-]+\.[A-Za-z0-9]{1,8}|(?:[\w\-]+/)+[\w\-]+\.(?:ya?ml|json|toml|ini|cfg|conf|log|sqlite3?|db))")
_HEADING = re.compile(r"^\s*(?:#{1,6}\s+\S.*|(?:\d+[.)]\s*)?\*\*[^*\n]{2,140}\*\*:?|\*\*\d+[.)][^*\n]{2,140}\*\*:?)\s*$")
_LIST_MARK = re.compile(r"^\s*(?:\*\*)?(?:[-*•]+|\d+[.)])\s*(?:\*\*)?\s*$")
_ELI_SPEAKS = re.compile(r"^\s*(?:\[[^\]]*\]\s*)?(?:ELI|Eli|Assistant)\s*:")
_USER_SPEAKS = re.compile(r"^\s*(?:\[[^\]]*\]\s*)?(?:You|User|Human)\s*:")


def asks_about_fault(text: Any) -> bool:
    return bool(_FAULT_RE.search(str(text or ""))) or complains_about_eli(text)


def without_own_prose(text: Any) -> str:
    """Prompt context minus ELI's earlier replies. They are not evidence about ELI: counted as
    such, an invented setting licenses itself on the next turn."""
    out: List[str] = []
    skipping = False
    for line in str(text or "").splitlines():
        if _ELI_SPEAKS.match(line):
            skipping = True
            continue
        if skipping and (_USER_SPEAKS.match(line) or not line.strip()):
            skipping = False
        if not skipping:
            out.append(line)
    return "\n".join(out)


@lru_cache(maxsize=1)
def known_identifiers() -> frozenset:
    """Every name ELI really has: actions, settings, tunables, agents, tables, modules."""
    names: set = set()
    try:
        from eli.execution.executor_enhanced import SUPPORTED_ACTIONS
        names.update(SUPPORTED_ACTIONS)
    except Exception:
        log.debug("known identifiers: actions unavailable", exc_info=True)
    try:
        from eli.core.runtime_settings import DEFAULTS
        names.update(DEFAULTS)
    except Exception:
        log.debug("known identifiers: settings unavailable", exc_info=True)
    try:
        from eli.core.cognition_tunables import TUNABLES
        names.update(t.key for t in TUNABLES)
    except Exception:
        log.debug("known identifiers: tunables unavailable", exc_info=True)
    try:
        from eli.cognition.agent_bus import _ALL_AGENTS
        names.update(getattr(a, "name", "") for a in _ALL_AGENTS)
    except Exception:
        log.debug("known identifiers: agents unavailable", exc_info=True)
    try:
        import sqlite3
        from eli.core.paths import agent_db_path, user_db_path
        for db in (user_db_path(), agent_db_path()):
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=1.0)
            try:
                names.update(r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'"))
            finally:
                con.close()
    except Exception:
        log.debug("known identifiers: tables unavailable", exc_info=True)
    try:
        from pathlib import Path
        import eli
        for p in Path(eli.__file__).resolve().parent.rglob("*.py"):
            names.add(p.stem)
            names.add(p.name)
    except Exception:
        log.debug("known identifiers: modules unavailable", exc_info=True)
    return frozenset(n.lower() for n in names if n)


def _invented_identifier(sentence: str, evidence_low: str) -> Optional[str]:
    for name in _BACKTICKED.findall(sentence):
        low = name.lower().rstrip(".")
        if not _CODE_SHAPED.search(name):
            continue
        if low in known_identifiers() or low in evidence_low:
            continue
        if low.rsplit(".", 1)[0] in known_identifiers():
            continue
        return name
    return None


def _path_exists(path: str) -> bool:
    from pathlib import Path
    try:
        p = Path(path).expanduser()
        if p.is_absolute():
            return p.exists()
        from eli.core.paths import config_dir, data_dir, project_root
        return any((base / p).exists() for base in (project_root(), data_dir(), config_dir()))
    except Exception:
        return True


def _invented_path(sentence: str, evidence_low: str) -> Optional[str]:
    for path in _PATH.findall(sentence):
        if path.lower() in evidence_low or _path_exists(path):
            continue
        return path
    return None


def _stems(text: str) -> set:
    return {w[:6] for w in re.findall(r"[a-z][a-z0-9_']{3,}", str(text or "").lower())}


def _supported(sentence: str, record_stems: set) -> float:
    """How much of what the sentence says is in the record: the share of its content words found there."""
    words = [w for w in re.findall(r"[a-z][a-z0-9_']{3,}", sentence.lower()) if w not in _FILLER]
    if len(words) < 3:
        return 1.0
    return sum(1 for w in words if w[:6] in record_stems) / len(words)


def _unrecorded_internal(sentence: str, record_low: str) -> Optional[str]:
    for m in _INTERNALS.finditer(sentence):
        term = m.group(0).lower()
        if term[:5] not in record_low:
            return term
    return None


class _Check:
    """One turn's claim check, fed a reply one unit (sentence or line) at a time."""

    def __init__(self, evidence: str = ""):
        facts = _turn_context()
        self._facts = facts
        asked = str(facts.get("user_input") or "")
        self.about_self = asks_about_own_behaviour(asked)
        self._ran_at_start = bool(facts.get("executed_actions"))
        # What the pipeline recorded, plus the user's own words. Not ELI's.
        self._record = str(facts.get("_record") or "").lower()
        self._fault = bool(self._record) and asks_about_fault(asked)
        self._evidence = f"{without_own_prose(evidence)}\n{self._record}\n{asked}".lower()
        self._record_and_asked = f"{self._record}\n{asked.lower()}"
        self._record_stems = _stems(self._record_and_asked) if self._fault else set()
        self._heading: Optional[str] = None
        self._dropped_under_heading = False
        self._last_dropped = False
        self._line_open = False  # served text since the last newline
        self.dropped: List[str] = []
        self.kept_words = 0

    def why(self, unit: str) -> str:
        s = str(unit or "")
        if not s.strip():
            return ""
        ran = self._ran_at_start or bool(self._facts.get("executed_actions"))
        if not ran and _ENABLED_CLAIM.search(s):
            return "reports a change nothing made"
        if not self.about_self:
            return ""
        if not ran and _STANDING_PROMISE.search(s) and _COMMITS.search(s):
            return "promises a standing change a reply cannot make"
        name = _invented_identifier(s, self._evidence)
        if name:
            return f"names `{name}`, which ELI does not have"
        path = _invented_path(s, self._evidence)
        if path:
            return f"names {path}, which does not exist"
        if not ran and _INVENTED_FIX.search(s) and not any(
                w.lower() in known_identifiers() for w in re.findall(r"\b[A-Z][A-Z_]{3,}\b", s)):
            return "proposes a fix ELI has no action for"
        if self._fault:
            term = _unrecorded_internal(s, self._record_and_asked)
            if term:
                return f"gives '{term}' as a cause, which the record does not show"
            if _EXPLAINS.search(s):
                share = _supported(s, self._record_stems)
                if share < _SUPPORT_NEEDED:
                    return f"explains a cause the record does not carry ({share:.0%} of it is there)"
        if self._last_dropped and len(s.split()) <= 30 and (_OFFER.search(s) or _FOLLOWS.search(s)):
            return "rests on a claim that was dropped"
        return ""

    def feed(self, unit: str) -> List[str]:
        """The text to serve now for this unit: nothing, the unit, or a held heading and the unit."""
        out = self._feed(unit)
        for piece in out:
            if piece:
                self._line_open = not piece.endswith("\n")
        return out

    def _dropped(self, unit: str) -> List[str]:
        self.dropped.append(unit)
        # the dropped sentence ended its line: end the line for what was served before it
        return ["\n"] if (self._line_open and "\n" in unit[len(unit.rstrip()):]) else []

    def _feed(self, unit: str) -> List[str]:
        if not unit:
            return []
        if not unit.strip():
            return [unit] if self._heading is None else []
        if _HEADING.match(unit):
            out = [] if (self._heading is None or self._dropped_under_heading) else [self._heading]
            # a heading can carry the invention too ("The Temporal Drift"); its section stands without it
            titled = self.why(unit)
            if titled:
                out += self._dropped(unit)
            self._heading, self._dropped_under_heading, self._last_dropped = (None if titled else unit), False, False
            return out
        reason = self.why(unit)
        if reason:
            log.debug("[SELF-CLAIM] dropped a sentence that %s: %s", reason, unit.strip()[:100])
            self._dropped_under_heading = True
            self._last_dropped = True
            return self._dropped(unit)
        self._last_dropped = False
        self.kept_words += len(unit.split())
        out = [unit] if self._heading is None else [self._heading, unit]
        self._heading = None
        return out

    def close(self) -> List[str]:
        out = [] if (self._heading is None or self._dropped_under_heading) else [self._heading]
        self._heading = None
        return out

    def afterword(self) -> str:
        """What follows a reply that lost sentences: the record when little or nothing true was
        left, a line saying causes were left out when several were, otherwise nothing."""
        if not self.dropped:
            return ""
        lines = self._facts.get("_record_lines") or []
        if self.kept_words < 4:
            if self.about_self and lines:
                return (("\n" if self.kept_words else "")
                        + "I won't guess at a cause or promise a change a reply can't make. This is what the "
                          "audit ledger holds for the last turns:\n" + "\n".join(f"- {x}" for x in lines[-4:]))
            return "" if self.kept_words else "".join(self.dropped)  # never an empty reply
        # A complaint is owed what the record holds as soon as anything was left out.
        complaint = complains_about_eli(self._facts.get("user_input") or "")
        if self._fault and lines and len(self.dropped) >= (1 if complaint else 3):
            return ("\n\nI've left out what I can't back from my own records. What the audit ledger holds "
                    "for the last turns:\n" + "\n".join(f"- {x}" for x in lines[-3:]))
        return ""


_BOUNDARY = re.compile(r"[.!?]+[\"'’”)\]*_]*\s+|\n")


def _next_unit(buf: str, final: bool = False):
    """(unit, rest) for the first complete sentence or line in `buf`, or (None, buf)."""
    at = 0
    while True:
        m = _BOUNDARY.search(buf, at)
        if m is None:
            return (buf, "") if (final and buf) else (None, buf)
        # "1." and "- " open a list item; they are not a sentence of their own.
        if m.group(0) != "\n" and _LIST_MARK.match(buf[:m.end()]):
            at = m.end()
            continue
        return buf[:m.end()], buf[m.end():]


def _turn_context() -> Dict[str, Any]:
    try:
        from eli.kernel.request_context import turn_facts_var
        return turn_facts_var.get() or {}
    except Exception:
        return {}


def gate_stream(chunks: Iterable[str], evidence: str = ""):
    """The claim check on a live stream: each sentence is held until it ends, then served or
    dropped. Text inside ``` fences passes straight through."""
    check = _Check(evidence)
    buf = ""
    in_code = False
    code_served = False
    for piece in chunks:
        buf += str(piece or "")
        while buf:
            if in_code:
                end = buf.find("```")
                if end < 0:
                    if len(buf) > 2:  # the tail could be the start of the closing fence
                        yield buf[:-2]
                        buf = buf[-2:]
                    break
                yield buf[:end + 3]
                buf, in_code = buf[end + 3:], False
                continue
            unit, rest = _next_unit(buf)
            fence = buf.find("```")
            if fence >= 0 and (unit is None or fence < len(unit)):
                yield from check.feed(buf[:fence]) + check.close()
                yield "```"
                buf, in_code, code_served = buf[fence + 3:], True, True
                continue
            if unit is None:
                break
            buf = rest
            yield from check.feed(unit)
    if buf:
        if in_code:
            yield buf
        else:
            yield from check.feed(buf)
    yield from check.close()
    after = "" if code_served else check.afterword()
    if after:
        yield after


def drop_invented_self_claims(text: str, evidence: str = "") -> str:
    """`text` without sentences that invent ELI's settings, files, causes or fixes, or report
    changes it didn't make. Code blocks are left alone. Never returns an empty reply."""
    body = str(text or "")
    if not body.strip():
        return body
    kept = "".join(gate_stream([body], evidence))
    kept = re.sub(r"[ \t]+\n", "\n", kept)
    return re.sub(r"\n{3,}", "\n\n", kept).strip() or body


def invented(sentence: str, *, evidence: str = "") -> str:
    """Why this sentence is an invented claim about ELI itself this turn, or "" when it is fine."""
    return _Check(evidence).why(sentence)
