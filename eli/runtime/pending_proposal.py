"""
eli/runtime/pending_proposal.py
================================
What ELI's last reply left open, so the user's next message can be read against it.

Three things can be open:

- steps ELI offered ("Want me to set a reminder?", a numbered list followed by "shall I go
  ahead with these?"). Each is either an action the router has a rule for, or a task ELI does
  by writing (explain, draft, compare, plan). "yes", "do 1-3", "the second one" run them.
- a question ELI asked. A short reply is its answer; the engine tells the model so.
- a detail an action asked for ("When is it?"). The reply completes the original request.

Distinct from runtime.grounded_remediation (which handles "install X?" repair offers).

State is a single JSON file, replaced by every reply, with a time limit so a "yes" long
afterwards cannot trigger an old offer.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from eli.utils.log import get_logger

log = get_logger(__name__)

# How long an offer stays open. Every reply replaces it, so this only bounds a reply to the
# last thing ELI said. Five minutes was shorter than reading a long answer and saying yes.
_TTL_SECONDS = 1800.0


def _path() -> Path:
    try:
        from eli.core.paths import get_paths
        base = Path(get_paths().artifacts_dir) / "runtime"
    except Exception:
        base = Path(__file__).resolve().parents[2] / "artifacts" / "runtime"
    base.mkdir(parents=True, exist_ok=True)
    return base / "pending_proposal.json"


def set_pending_proposal(command: str, summary: str = "", *, items: Optional[List[Dict[str, Any]]] = None,
                         from_reply: bool = False, question: str = "",
                         awaiting: Optional[Dict[str, Any]] = None) -> None:
    """Record what ELI's reply left open. `command` is the phrase to re-route if the user
    affirms (e.g. "set a reminder for the rick and morty premiere"); `items` is every step it
    offered, each with the number it was listed under; `question` is the question the reply
    ended on; `awaiting` is {"command", "action"} when an action asked for a missing detail.

    An action that asks for confirmation (forgetting memories) sets its own proposal; that one
    is marked on the turn so the capture of the reply text does not wipe it."""
    command = (command or "").strip()
    items = [dict(i) for i in (items or []) if isinstance(i, dict) and i.get("command")]
    if not command:
        first = next((i for i in items if i.get("kind") != "task"), None)
        command = str(first["command"]).strip() if first else ""
    question = " ".join(str(question or "").split())[:400]
    awaiting = dict(awaiting) if isinstance(awaiting, dict) and awaiting.get("command") else None
    if not (command or items or question or awaiting):
        return
    try:
        _path().write_text(
            json.dumps({"command": command, "summary": summary or command, "ts": time.time(),
                        "items": items, "question": question, "awaiting": awaiting}),
            encoding="utf-8",
        )
        log.debug("[PENDING_PROPOSAL] stored: %r%s%s", (command or question)[:120],
                  f" ({len(items)} steps)" if len(items) > 1 else "", " (awaiting a detail)" if awaiting else "")
        if not from_reply:
            from eli.kernel.request_context import note_turn_fact
            note_turn_fact("proposal_set_by_action", True)
    except Exception as e:
        log.debug("[PENDING_PROPOSAL] store failed: %s", e)


def get_follow_up() -> Optional[Dict[str, Any]]:
    """Everything the last reply left open (steps, a question, a detail asked for), or None."""
    p = _path()
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    if time.time() - float(data.get("ts", 0) or 0) > _TTL_SECONDS:
        clear_pending_proposal()
        return None
    if not (data.get("command") or data.get("items") or data.get("question") or data.get("awaiting")):
        return None
    return data


def get_pending_proposal() -> Optional[Dict[str, Any]]:
    """Return the live pending proposal dict, or None if absent/expired or it offers no command."""
    data = get_follow_up()
    return data if data and data.get("command") else None


def clear_pending_proposal() -> None:
    try:
        p = _path()
        if p.exists():
            p.unlink()
    except Exception:
        log.debug("suppressed exception", exc_info=True)


# Offer / proposal extraction from an ELI response. Returns the proposed
# command phrase (first concrete option) or "" if the text contains no offer.
import re as _re

# Strong offer stems. "want me to" isn't always a question: "Want me to update the profile?" is
# an offer but "You want me to keep a deeper persona." is a statement, and it armed a bogus
# proposal for 300s. The caller enforces question form per sentence (see extract_proposal). The
# captured phrase stops at the first clause boundary.
_STRONG_OFFER_RE = _re.compile(
    r"\b(?:want me to|shall i|should i|would you like me to|do you want me to|do you need me to|need me to|"
    r"like me to|how about i|why don'?t i|would it help if i)\s+"
    r"(.+?)(?:[.?!]|,| or |$)",
    _re.I,
)

# An offer made as a statement: "let me know if you'd like me to draft it", "if you want, I can
# check the calendar", "I can send you the summary if you'd like". No question mark, but there
# is nothing else "yes" could be the answer to.
_STATED_OFFER_RE = _re.compile(
    r"\b(?:let me know if you(?:'d| would)? (?:like|want|need) me to|"
    r"if you(?:'d| would)? (?:like|want|prefer)(?: me to)?,?\s+i(?: can| could| will|'ll)|"
    r"(?:just )?say the word and i(?:'ll| will| can))\s+(?P<a>.+?)(?:[.!]|,| or |$)"
    r"|\b(?:i (?:can|could)(?: also)?|i(?:'d| would) be (?:happy|glad|pleased) to|happy to|glad to)\s+(?P<b>.+?)"
    r"\s+if you(?:'d| would)? (?:like|want)(?: me to)?\b",
    _re.I,
)
# "Can I help with anything else?" offers nothing in particular: there is nothing to carry out.
_VACUOUS_OFFER = _re.compile(
    r"^(?:help|assist|do)(?: you)?(?: with| on)?(?: anything| something)?(?: else| further| more)?$"
    r"|\banything else\b|\bsomething else\b", _re.I)

# Weak declarative stems ("I can ...", "I'll ...") are an offer only when phrased as a question.
# "I can appreciate the absurdity of existence" is narrative and let a later "yes" trigger a bogus
# command. The "?" must close the same unbroken clause, so "I can run that for you?" works and a
# "?" from another sentence doesn't.
_WEAK_OFFER_RE = _re.compile(
    r"\b(?:i can|i could|i'?ll|i'd be happy to|happy to)\s+([^,;?!.]+)\?",
    _re.I,
)

# A real queued action phrase is short and imperative — a runaway multi-clause
# capture is prose, not an offer.
_MAX_PROPOSAL_WORDS = 12

# Sentence boundaries, so interrogative form is judged per sentence rather than
# per reply: "Here is the summary. Want me to save it?" must still be caught.
_SENTENCES_RE = _re.compile(r"(?<=[.!?])\s+")

# Phrases that are conversational, not real actions worth queuing.
_NON_ACTION = _re.compile(
    r"^(help|assist|explain|tell you|let you know|clarify|answer|continue|"
    r"keep going|elaborate|go on|see|check back|be here|appreciate|understand|"
    r"remember|think|know|be honest|admit|note|"
    # Grounded remediation owns "Would you like me to download/install it?" —
    # arming that as a proposal re-routes "yes" into nonsense CHAT instead of
    # CONFIRM_PENDING_REMEDIATION / apt install.
    r"download/?install(?:\s+it)?|install it|download it)\b",
    _re.I,
)


def extract_proposal(response_text: str) -> str:
    """Pull the first concrete actionable offer out of an ELI reply, if any.

    Only genuine offers the user can affirm are returned: question-form "want me
    to …" / "shall I …", or a declarative "I can/I'll …" clause that is itself a
    question. Declarative narrative is never treated as a queued action."""
    text = (response_text or "").strip()
    if not text:
        return ""
    for sentence in _SENTENCES_RE.split(text):
        sentence = sentence.strip()
        # Only an interrogative is something the user can answer "yes" to. A
        # declarative that merely contains an offer stem is ELI describing, not
        # offering, and queuing it turns the next "yes" into a fabricated action.
        if not sentence.endswith("?"):
            continue
        m = _STRONG_OFFER_RE.search(sentence) or _WEAK_OFFER_RE.search(sentence)
        if not m:
            continue
        phrase = " ".join(m.group(1).split()).strip(" .,;:")
        if not phrase or len(phrase) < 3:
            continue
        if len(phrase.split()) > _MAX_PROPOSAL_WORDS:
            continue
        if _NON_ACTION.match(phrase):
            continue
        return phrase
    return ""


# ── every step a reply offers ───────────────────────────────────────────────

_LIST_MARK = _re.compile(r"^(?P<indent>\s*)(?:(?P<n>\d{1,2})[.)]|[-*•])\s+")
_BOLD_LEAD = _re.compile(r"^\*\*([^*\n]{1,80})\*\*\s*(.*)$")
_PLAIN_LABEL = _re.compile(r"^[A-Z][\w '&/-]{1,40}:\s+(?=[A-Z])")
_COMMIT_LEAD = _re.compile(
    r"^(?:(?:for thoroughness|first(?:ly)?|then|next|also|finally|to help(?: you)?(?: with this)?)[,:]?\s+)?"
    r"(?:i'?ll|i will|i can|i could|let'?s|let me|we'?ll|we can|consider|you (?:can|could|might))\b", _re.I)
_MAX_ITEMS = 8
# A list item is a step when it says what to do ("Check the calendar", "Open the report"), not
# when it describes something: "I need the executor to stop returning NOOP when it should send
# PAUSE_MEDIA" routed to STOP_MEDIA and sat waiting for a "yes".
# "provider: gguf", "context_size: 16128": a field and its value in a listing, not a step. A status
# dump's "- provider: gguf" was kept as a step for a "yes"; so was a dated record from a memory dump,
# "[2026-10-08 18:06] Top topics: spotify, play, ...".
_FIELD_LINE = _re.compile(r"^(?:[a-z][a-z0-9_ ]{0,30}:\s+\S|\[[^\]]{1,40}\]\s)")
_DESCRIBES = _re.compile(
    r"^(?:i(?!'ll\b|\s+will\b|\s+can\b|\s+could\b)\b|i'm|i've|i'd|my|me|we(?!'ll\b|\s+can\b)\b|our|you|"
    r"your|it|its|it's|this|that|these|those|there|here|a|an|the|since|if|when|while|because|"
    r"as|so|but|and|or|which|what|why|how|who|maybe|perhaps)\b", _re.I)
# Never run because ELI offered it: these change ELI or the system and need the user's own words.
_NOT_OFFERABLE = frozenset((
    "CHAT", "UNKNOWN", "NOOP", "MULTI_COMMAND", "SEQUENCE", "TIME", "DATE", "GET_TIME", "GET_DATE",
    "SELF_REPORT", "RUNTIME_STATUS", "ROUTING_FAULT_EXPLAIN", "DETERMINISTIC_INTROSPECTION", "MEMORY_STATUS",
    "PERSONAL_MEMORY_SUMMARY", "USER_IDENTITY_SUMMARY", "EXPLAIN_MEMORY_RUNTIME", "EXPLAIN_COGNITION_RUNTIME",
    "AWARENESS_STATUS", "META_DIAGNOSTIC", "SELF_ANALYZE", "RUNTIME_AUDIT", "REASONING_MODE_STATUS",
    "EXPLAIN_ALL_REASONING_MODES", "CAPABILITY", "CAPABILITY_STATUS", "LIST_CAPABILITIES", "HABIT_STATUS",
    "ORCHESTRATION_STATUS", "EXAMINE_CODE", "FILE_AUDIT", "HELP", "PERSONAL_MEMORY_DEEP_EXPLAIN",
))
# An offer that points at what was just listed ("go ahead with any of these", "proceed") rather
# than naming a thing of its own.
_REFERS_BACK = _re.compile(
    r"\b(?:these|those|them|that|this|it|any of|either|both|all of|one of|the above|the following|each)\b", _re.I)
_BARE_GO_AHEAD = _re.compile(
    r"^(?:proceed|go ahead|continue|carry on|go on|start|begin|get started|do (?:that|so|it|this)|help)\b", _re.I)
_WHICH_ONE = _re.compile(
    r"\b(?:which (?:one|of (?:these|those|them)|option|would|should)|shall we|should we)\b", _re.I)
# Grounded remediation owns "Would you like me to download/install it?".
_REMEDIATION = _re.compile(r"^(?:download/?install(?:\s+it)?|install it|download it)\b", _re.I)


_NOT_AN_ACTION = ("", "CHAT", "UNKNOWN", "NOOP")
# What a plain "yes" may run when ELI asked outright ("Want me to check my memory status?"). A
# status report is fine there; a compound of several commands is not taken from ELI's sentence.
_NOT_FROM_A_QUESTION = frozenset(("MULTI_COMMAND", "SEQUENCE"))
# A wh-question asks for a choice or a detail; "yes" does not answer it.
_WH_BEFORE_OFFER = _re.compile(
    r"\b(?:which|what|how|when|where|who|whom|whose|why)\b[^?]*?"
    r"\b(?:want me to|shall i|should i|would you like me to|do you want me to|do you need me to|need me to|"
    r"like me to|how about i|why don'?t i|would it help if i|i can|i could|i'?ll)\b", _re.I)


def _explicit_only(action: str) -> bool:
    try:
        from eli.cognition.llm_intent import _EXPLICIT_ONLY_ACTIONS
        return str(action or "").upper() in _EXPLICIT_ONLY_ACTIONS
    except Exception:
        return True


def _offerable(action: str) -> bool:
    act = str(action or "").upper()
    return bool(act) and act not in _NOT_OFFERABLE and not _explicit_only(act)


def _route_of(phrase: str) -> Dict[str, Any]:
    """What the router's own rules make of a phrase."""
    try:
        from eli.execution.router_enhanced import route
        return route(phrase) or {}
    except Exception:
        log.debug("[PENDING_PROPOSAL] route probe failed", exc_info=True)
        return {}


def _routed(phrase: str) -> Optional[Dict[str, Any]]:
    """The action the router's own rules give this phrase, if it is one ELI may offer."""
    got = _route_of(phrase)
    return got if _offerable(got.get("action")) else None


def _unlabel(text: str) -> tuple:
    """(what the line says, its label). "**Schedule check**: look at the calendar" says the
    second part; "**Draft the abstract**" on its own is only a label, and may be the step."""
    text = str(text or "").strip()
    m = _BOLD_LEAD.match(text)
    if m:
        head, rest = m.group(1).strip(), m.group(2).strip()
        if not rest or rest in (":", "-", "–", "—"):
            return "", head
        if rest[0] in ":-–—":
            return rest.lstrip(":-–— ").strip(), head
        return f"{head} {rest}".strip(), ""
    return _PLAIN_LABEL.sub("", text), ""


_OBJECT_YOU = _re.compile(
    r"\b(for|to|with|through|give|show|tell|send|walk|help|remind|take|bring|get|teach|guide|ask|email|message|"
    r"update|keep|write|draft|find|make|build|talk|point|fill|let)\s+you\b", _re.I)


def _as_request(text: str) -> str:
    """ELI's offer in the user's voice: "walk you through your options" is "walk me through my
    options" when the user is the one asking for it."""
    out = _COMMIT_LEAD.sub("", str(text or "").strip(), count=1).strip() or str(text or "").strip()
    out = _OBJECT_YOU.sub(lambda m: f"{m.group(1)} me", out)
    out = _re.sub(r"\byourself\b", "myself", out, flags=_re.I)
    out = _re.sub(r"\byours\b", "mine", out, flags=_re.I)
    out = _re.sub(r"\byour\b", "my", out, flags=_re.I)
    return out.strip(" .,;:")


def read_reply(response_text: str, *, offers_only: bool = False) -> Dict[str, Any]:
    """What a reply leaves open: {"items": [...], "question": str}.

    An item is a step ELI offered. kind "action": the router has a rule for it and it runs
    through the executor. kind "task": ELI does it by writing (explain, draft, compare), so it
    is carried out by a turn of its own whose message is the task. Each keeps the number it was
    listed under, so "do 2 and 3" can pick.

    A step with an action is kept wherever ELI names it: an offer, a list item, "I'll check
    the calendar". A task is kept only where ELI asked for a go-ahead: its own offer ("Want me
    to walk you through it?"), or the items of a list its question points at ("Shall I go ahead
    with any of these?"). A list of facts followed by an unrelated offer is not a set of tasks.
    kind "explicit": ELI offered something that changes ELI or the system. A "yes" never runs
    those and never has the model pretend to; the user is told the words to say.

    `offers_only` is for the result of an action: "I'll remind you at 19:00" there reports what
    was done, so only a question counts as an offer.

    `question` is the question the reply ends on, if it ends on one."""
    cands: List[Dict[str, Any]] = []
    points_back = False
    number: Optional[int] = None
    last_sentence = ""
    # Stored replies have had their blank lines closed up, which leaves the first item on the
    # line that introduces the list ("three ways: 1. Draft ...") and a closing question on the
    # line of the last item.
    laid_out = _re.sub(r"(?<=[:.!?])[ \t]+(?=\d{1,2}[.)][ \t]+\S)", "\n", str(response_text or ""))
    for line in laid_out.splitlines():
        if not line.strip():
            continue
        mark = _LIST_MARK.match(line)
        if mark:
            if mark.group("n") and not mark.group("indent"):
                number = int(mark.group("n"))
        elif not line.startswith((" ", "\t")):
            number = None  # back to prose: no longer under a numbered item
        body, label = _unlabel(_LIST_MARK.sub("", line).strip())
        if label and not body and mark:
            cands.append({"n": number, "text": label, "src": "label"})
        first = True
        for sentence in _SENTENCES_RE.split(body):
            # a list flattened onto one line leaves its dashes and labels inside the sentence
            inline = bool(_re.match(r"\s*[-*•]\s+", sentence))
            sentence, inner = _unlabel(sentence.strip().lstrip("-*• ").strip())
            named = (label if first else "") or inner
            first_of_line, first = first, False
            if sentence:
                last_sentence = sentence
            if len(sentence) < 8:
                continue
            if sentence.endswith("?"):
                if mark and not first_of_line:
                    number = None      # a question after a list item's own sentence closes the list
                m = _STRONG_OFFER_RE.search(sentence) or _WEAK_OFFER_RE.search(sentence)
                if _WH_BEFORE_OFFER.search(sentence) or (not m and _WHICH_ONE.search(sentence)):
                    points_back = points_back or bool(_WHICH_ONE.search(sentence))
                elif m:
                    phrase = " ".join(m.group(1).split()).strip(" .,;:")
                    if phrase and not _REMEDIATION.match(phrase) and not _VACUOUS_OFFER.search(phrase):
                        cands.append({"n": number, "text": phrase, "src": "offer", "said": sentence})
            elif _STATED_OFFER_RE.search(sentence):
                st = _STATED_OFFER_RE.search(sentence)
                phrase = " ".join((st.group("a") or st.group("b") or "").split()).strip(" .,;:")
                if phrase and not _REMEDIATION.match(phrase) and not _VACUOUS_OFFER.search(phrase):
                    cands.append({"n": None, "text": phrase, "src": "offer", "said": sentence})
            elif (not offers_only and (mark or inline) and not _DESCRIBES.match(sentence.lstrip("*_ "))
                  and not _FIELD_LINE.match(sentence)):
                cands.append({"n": number, "text": sentence.rstrip(".! "), "src": "list", "said": sentence,
                              "label": named})
            elif not offers_only and _COMMIT_LEAD.match(sentence):
                cands.append({"n": number, "text": sentence.rstrip(".! "), "src": "said", "said": sentence})

    listed = [c for c in cands if c["src"] in ("list", "label")]
    for c in cands:
        if c["src"] == "offer" and listed and (_REFERS_BACK.search(c["text"]) or _BARE_GO_AHEAD.match(c["text"])):
            c["points_back"] = True
            points_back = True

    items: List[Dict[str, Any]] = []
    seen = set()

    def _task(c: Dict[str, Any]) -> None:
        text = c["text"]
        if c.get("label") and c["label"].lower() not in text.lower():
            text = f"{c['label']}: {text}"      # "Write the abstract: about 200 words"
        task = _as_request(text)
        key = ("CHAT", _re.sub(r"\W+", " ", task.lower()).strip()[:60])
        if task and key not in seen:
            seen.add(key)
            items.append({"n": c["n"], "command": task, "action": "CHAT", "kind": "task",
                          "said": str(c.get("said") or c["text"])[:300]})

    for c in cands:
        text = c["text"]
        if not text or len(text.split()) > 40:
            continue
        asked = c["src"] == "offer"
        if c["src"] == "label" and any(o is not c and o["n"] == c["n"] and o["src"] == "list" for o in cands):
            continue  # the label of a step whose lines say what the step is
        route = {} if (asked and _NON_ACTION.match(text)) else _route_of(text)
        act = str(route.get("action") or "").upper()
        if act in _NOT_AN_ACTION:
            # something ELI does by writing: only where it asked for a go-ahead
            if asked and not c.get("points_back"):
                _task(c)
            elif c["src"] in ("list", "label") and points_back and not offers_only:
                _task(c)
        elif _explicit_only(act):
            key = (act, "")
            if asked and key not in seen:
                seen.add(key)
                items.append({"n": c["n"], "command": _as_request(text), "action": act, "kind": "explicit"})
        elif (asked and act not in _NOT_FROM_A_QUESTION) or act not in _NOT_OFFERABLE:
            key = (act, _re.sub(r"\W+", " ", text.lower()).strip()[:60])
            same_read = (act, "") if act in ("LIST_EVENTS", "NEWS_FETCH") else key
            if key in seen or same_read in seen:
                continue
            seen.update((key, same_read))
            items.append({"n": c["n"], "command": text, "action": act, "kind": "action"})
        if len(items) >= _MAX_ITEMS:
            break
    return {"items": items, "question": last_sentence if last_sentence.endswith("?") else ""}


def actionable_items(response_text: str, *, offers_only: bool = False) -> List[Dict[str, Any]]:
    """The steps in a reply that have a real action behind them (see read_reply)."""
    return [{"n": i["n"], "command": i["command"], "action": i["action"]}
            for i in read_reply(response_text, offers_only=offers_only)["items"] if i["kind"] == "action"]


# ── the user's reply to it ───────────────────────────────────────────────────

_CONSENT_WORDS = _re.compile(
    r"\b(?:yes|yeah|yep|yup|aye|sure|ok|okay|alright|please|pls|do|did|go|ahead|proceed|carry|on|it|that|them|those|this|"
    r"all|of|the|both|every|one|ones|steps?|items?|options?|numbers?|i|said|already|told|you|just|then|now|so|and|to|"
    r"through|with|for|me|eli|first|second|third|fourth|fifth|last|three|two|four|five|six|thanks|thank|go|run|"
    r"sounds|good|great|perfect|fine|definitely|absolutely|correct|right|yea|ya|works|would|be|i'd|like|love|"
    r"brilliant|grand|lovely|agreed|deal|let's|lets|if|could|can|will)\b", _re.I)
_CONSENT_CUE = _re.compile(
    r"\b(?:yes|yeah|yep|yup|aye|sure|ok|okay|alright|do|go|proceed|please|definitely|absolutely|agreed|deal|both|"
    r"sounds (?:good|great|fine|perfect|lovely)|that works|works for me|perfect|brilliant|"
    r"i'?d (?:like|love) that|that would be (?:good|great|lovely|perfect)|let'?s do (?:it|that|them|this))\b", _re.I)
_ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6}
_ASKING = _re.compile(
    r"^(?:what|why|how|when|where|who|which|whose|is|are|was|were|can|could|do|does|did|will|would|should|shall)\b", _re.I)
_PICK_FILLER = _re.compile(
    r"\b(?:the|a|an|one|ones|option|options|number|numbers|item|items|step|steps|first|second|third|fourth|fifth|"
    r"sixth|and|just|only|go|with|for|me|let'?s|i'?ll|take|pick|choose|have|do|please|then|that|this)\b", _re.I)


def is_consent(text: str) -> bool:
    """The message agrees to what was offered and asks for nothing new: "yes please", "I said
    yes already", "YES! DO 1-3", "do it then", "sounds good", "go ahead with all of them"."""
    low = _re.sub(r"\s+", " ", str(text or "").strip().lower())
    low = _re.sub(r"\bwhy not\b", "yes", low)
    if not low or len(low.split()) > 12:
        return False
    if not _CONSENT_CUE.search(low):
        return False
    rest = _re.sub(r"[\d\-–,.!?&/+]+", " ", _CONSENT_WORDS.sub(" ", low))
    rest = _re.sub(r"['’][a-z]{0,2}\b", " ", rest)          # what is left of "i'd", "that's", "let's"
    return not rest.strip()


def chosen_numbers(text: str) -> Optional[set]:
    """The list numbers a reply picks ("1-3", "2 and 3", "the second one"); None when it picks none."""
    low = str(text or "").lower()
    picked: set = set()
    for a, b in _re.findall(r"\b(\d{1,2})\s*(?:-|–|to|through)\s*(\d{1,2})\b", low):
        lo, hi = sorted((int(a), int(b)))
        if hi - lo <= 12:
            picked.update(range(lo, hi + 1))
    for n in _re.findall(r"(?<![\d:.])\b(\d{1,2})\b(?![\d:.]|\s*(?:am|pm))", low):
        picked.add(int(n))
    for word, n in _ORDINALS.items():
        if _re.search(rf"\b{word}\b", low):
            picked.add(n)
    return picked or None


def _offered(prop: Dict[str, Any]) -> List[Dict[str, Any]]:
    items = [dict(i) for i in (prop.get("items") or []) if isinstance(i, dict) and i.get("command")]
    if not items and str(prop.get("command") or "").strip():
        items = [{"n": None, "command": str(prop["command"]).strip(), "kind": "action"}]
    return items


def _words(text: str) -> set:
    return {w[:-1] if len(w) > 3 and w.endswith("s") else w for w in _re.findall(r"[a-z0-9']{2,}", str(text or "").lower())}


def _by_number(items: List[Dict[str, Any]], picked: set) -> List[Dict[str, Any]]:
    if any(i.get("n") is not None for i in items):
        return [i for i in items if i.get("n") in picked]
    return [i for at, i in enumerate(items, 1) if at in picked]   # an unnumbered list: by position


def _by_name(items: List[Dict[str, Any]], reply: str) -> List[Dict[str, Any]]:
    """The one step the reply names by its own words ("the abstract one"), if exactly one."""
    low = _CONSENT_WORDS.sub(" ", _PICK_FILLER.sub(" ", str(reply or "").lower()))
    said = _words(low)
    if not said:
        return []
    hits = [i for i in items if said <= _words(f"{i.get('command', '')} {i.get('said', '')} {i.get('label', '')}")]
    return hits if len(hits) == 1 else []


def chosen_items(prop: Dict[str, Any], reply: str) -> List[Dict[str, Any]]:
    """What a consent covers: the steps the user picked by number or by name, else all of them."""
    items = _offered(prop)
    if len(items) <= 1:
        return items
    picked = chosen_numbers(reply)
    if picked:
        by_number = _by_number(items, picked)
        if by_number:
            return by_number
    return _by_name(items, reply) or items


def selection(prop: Dict[str, Any], reply: str) -> List[Dict[str, Any]]:
    """A short reply that picks from what was offered without saying yes: "the second one",
    "2 and 3", "the abstract one". Empty when it is anything else."""
    low = _re.sub(r"\s+", " ", str(reply or "").strip().lower())
    if not low or "?" in low or len(low.split()) > 8 or _ASKING.match(low):
        return []
    items = _offered(prop)
    if len(items) < 2:
        return []
    picked = chosen_numbers(low)
    if picked and not _re.sub(r"[\d\-–,.!&/+]+", " ", _PICK_FILLER.sub(" ", low)).strip():
        return _by_number(items, picked)
    return _by_name(items, low)


def commands_for(prop: Dict[str, Any], reply: str) -> List[str]:
    """The commands a consent runs through the executor (see chosen_items)."""
    return [i["command"] for i in chosen_items(prop, reply) if i.get("kind", "action") == "action"]


def agreed(chosen: List[Dict[str, Any]], *, offer: str = "") -> Dict[str, Any]:
    """The steps a "yes" covers, sorted by how each is carried out."""
    return {
        "commands": [i["command"] for i in chosen if i.get("kind", "action") == "action"],
        "tasks": [i["command"] for i in chosen if i.get("kind") == "task"],
        "explicit": [i["command"] for i in chosen if i.get("kind") == "explicit"],
        "offer": " ".join(str(offer or "").split())[:400],
    }


def own_words_line(commands: List[str]) -> str:
    """What ELI says when "yes" was the answer to an offer only the user's own words can start."""
    said = " or ".join(f'"{c}"' for c in commands if c)
    return f"That one I only do on your own words, not on a yes to mine. Say {said} and I will." if said else ""


def task_message(tasks: List[str]) -> str:
    """The message the turn that carries out agreed tasks is run with."""
    tasks = [t.strip() for t in tasks if str(t or "").strip()]
    if len(tasks) == 1:
        return tasks[0]
    return "Do each of these in full, in this order:\n" + "\n".join(f"{n}. {t}" for n, t in enumerate(tasks, 1))


def is_short_answer(text: str) -> bool:
    """A reply short enough to be the answer to a question, and not a question itself."""
    low = _re.sub(r"\s+", " ", str(text or "").strip().lower())
    return bool(low) and "?" not in low and len(low.split()) <= 12 and not _ASKING.match(low)


def is_the_detail(reply: str, needs: str) -> bool:
    """The reply is the detail an action asked for and nothing else. "when": a day or a time
    ("friday at 3pm", "in 20 minutes"), not a request that happens to contain one."""
    if not is_short_answer(reply):
        return False
    if str(needs or "") == "when":
        try:
            from eli.runtime.agenda import parse_when
            when = parse_when(reply)
        except Exception:
            return False
        if when is None:
            return False
        left = str(reply)
        for a, b in sorted(when.spans, reverse=True):
            left = left[:a] + " " + left[b:]
        left = _re.sub(r"\b(?:on|at|in|for|by|the|it'?s|its|it is|make it|say|around|about|maybe|please|then|"
                       r"this|next|coming)\b", " ", left, flags=_re.I)
        return not _re.search(r"[a-z]{2,}", left, _re.I)
    if str(needs or "") == "place":
        low = _re.sub(r"^(?:in|at|near|it'?s|its)\s+", "", str(reply or "").strip().lower()).strip(" .!")
        if not low or len(low.split()) > 4 or not _re.fullmatch(r"[a-z][a-z ,.'-]*", low):
            return False
        return not is_consent(low) and not _re.search(
            r"\b(?:no|nope|nah|never ?mind|cancel|stop|skip|leave it|forget it|nowhere|dunno|idk|what|why|how)\b", low)
    return False
