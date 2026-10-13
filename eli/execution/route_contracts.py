from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Optional


def _low(text: Any) -> str:
    try:
        return str(text or "").lower()
    except Exception:
        return ""


def wants_memory_internals(text: Any) -> bool:
    low = _low(text)
    return (
        "memory" in low
        and (
            "internally" in low
            or "internal" in low
            or "internals" in low
            or "memory system" in low
            or "db table" in low
            or "db tables" in low
            or "sqlite" in low
            or "which files" in low
            or "which db" in low
            or "which functions" in low
            or "files, which db tables" in low
            or "tables, which functions" in low
        )
    )


def wants_personal_memory(text: Any) -> bool:
    low = _low(text)
    return (
        "memory" in low
        and (
            "about me" in low
            or "remember about me" in low
            or "actually remember about me" in low
            or "what you remember" in low
            or "what do you know about me" in low
            or "my memory" in low
            or "personal memory" in low
            or "personalised" in low
            or "personalized" in low
        )
    )


def wants_personal_memory_deep_explain(text: Any) -> bool:
    if wants_memory_internals(text) and wants_personal_memory(text):
        return True
    return wants_user_model_provenance(text)


def wants_user_model_provenance(text: Any) -> bool:
    """Static template vs dynamic/evolving understanding of the user."""
    low = _low(text)
    if not low:
        return False
    static_markers = (
        "hardcoded", "hard coded", "hard-coded", "template", "stub", "static info",
        "static profile", "about me section",
    )
    dynamic_markers = (
        "dynamic", "emergent", "evolving", "evolve", "update these preference",
        "actually remember", "not updating",
    )
    subject_markers = (
        "about me", "profile", "preference", "memory", "user info", "understanding",
        "who i am", "what you know about me",
    )
    has_static = any(m in low for m in static_markers)
    has_dynamic = any(m in low for m in dynamic_markers)
    has_subject = any(m in low for m in subject_markers)
    return has_subject and (has_static or has_dynamic)


def personal_memory_deep_route(text: Any) -> Dict[str, Any]:
    return {
        "action": "PERSONAL_MEMORY_DEEP_EXPLAIN",
        "args": {"question": str(text or ""), "detail": "full"},
        "confidence": 0.995,
        "meta": {
            "matched_by": "eli.route_contracts.personal_memory_deep_explain",
            "need_grounding": True,
            "allow_chat_without_evidence": False,
            "task_family": "personal_memory",
            "response_contract": "personal_memory_deep_explain_with_runtime_and_user_memory",
        },
    }


def classify_precedence_route(text: Any) -> Optional[Dict[str, Any]]:
    """
    Canonical precedence contract.

    Hybrid question:
      memory internals + what you remember about me
      -> PERSONAL_MEMORY_DEEP_EXPLAIN

    Pure memory internals remains EXPLAIN_MEMORY_RUNTIME elsewhere.

    Pure personal memory remains PERSONAL_MEMORY_SUMMARY elsewhere.

    This module prevents later wrappers from re-implementing contradictory
    phrase tests.
    """
    if wants_personal_memory_deep_explain(text):
        return personal_memory_deep_route(text)
    return None


__all__ = [
    "wants_memory_internals",
    "wants_personal_memory",
    "wants_personal_memory_deep_explain",
    "wants_user_model_provenance",
    "personal_memory_deep_route",
    "classify_precedence_route",
]


def is_command(intent: Any) -> bool:
    """Whether the router's answer for a message is an action to carry out: a rule matched
    (not the chat fallback) and what it names is neither conversation nor nothing."""
    if not isinstance(intent, dict):
        return False
    action = str(intent.get("action") or "").upper()
    matched = str((intent.get("meta") or {}).get("matched_by") or "")
    try:
        confident = float(intent.get("confidence") or 0) > 0.5
    except (TypeError, ValueError):
        confident = False
    return confident and action not in ("", "CHAT", "NOOP") and matched != "fallback.chat"


# ── what kind of thing an action is, by its name ─────────────────────────────
#
# An action either changes something (plays, opens, closes, writes, runs) or reads something and
# reports it. The name says which: a reading action starts with a verb of reading or ends with
# what it reports. Kept by convention, so a new action is classed by how it is named; the few
# names the convention cannot tell are listed. (Five hand-kept sets across the engine each held
# part of this and had drifted from one another.)
_READS_START = ("GET_", "LIST_", "CHECK_", "EXPLAIN_", "SHOW_", "READ_", "ANALYZE_", "ANALYSE_", "SUMMARIZE_",
                "SUMMARISE_", "SEARCH_", "EXAMINE_", "RESOLVE_", "DIAGNOSE_", "OCR_", "TRANSCRIBE")
_READS_END = ("_STATUS", "_STATS", "_USAGE", "_AUDIT", "_REPORT", "_SUMMARY", "_LOG", "_DIAGNOSTICS", "_DIAG",
              "_EXPLAIN", "_LIST", "_TOOLS", "_DOCTOR", "_SEARCH", "_QUERY", "_GRAPH", "_PROFILE", "_FETCH",
              "_RECALL", "_LOCATE", "_PLAYING", "_CHANGES", "_PROPOSALS", "_JOBS", "_PLAYBOOK", "_READ_ANALYZE")
_READS_NAMED = frozenset(("", "CHAT", "ANSWER", "NOOP", "UNKNOWN", "HELP", "TIME", "DATE", "CAPABILITY",
                          "DIRECT_RESPONSE", "ASK_CLARIFY", "SELF_ANALYZE", "SELF_TEST", "MESSAGE_TIME_QUERY"))


def changes_something(action: Any) -> bool:
    """Whether carrying this action out changes anything: the machine, an app, a file, what is
    playing, what ELI is set to. Reading and reporting does not."""
    name = str(action or "").strip().upper()
    return not (name in _READS_NAMED or name.startswith(_READS_START) or name.endswith(_READS_END))


# Words that carry grammar and not content: what is left of a sentence without them and without
# the command's own words is what else the sentence is about.
_GRAMMAR = frozenset("""a an the this that these those my your his her its our their me you u i it he she we they them us
to of in on at by for with from into onto over under about as and or but if then so because while when where which who
whom whose what why how not no nor do does did done doing is are was were be been being am have has had having will
would shall should can could may might must just only also very really quite too more most much many some any each
every all both either neither own same such than now here there again ever never always still yet already please pls
thanks thank ok okay hey hi hello eli up down out off bit little moment second sec minute quick quickly""".split())
_WORD = re.compile(r"[a-z0-9']+")


def _words(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for inner in value.values():
            yield from _words(inner)
    elif isinstance(value, (list, tuple, set)):
        for inner in value:
            yield from _words(inner)
    elif value is not None and not isinstance(value, bool):
        yield from _WORD.findall(str(value).lower())


def _same_word(a: str, b: str) -> bool:
    """One word in two forms: play/playing, stop/stopped, minimise/minimize."""
    a, b = a.replace("z", "s"), b.replace("z", "s")
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    return len(short) >= 3 and long_.startswith(short[:max(3, len(short) - 1)]) and len(long_) - len(short) <= 4


def fits(text: Any, intent: Any) -> bool:
    """Whether a message is telling ELI to do what the router matched in it.

    Asked of actions that change something, which are carried out at once. A rule that fires on a
    word matched them inside sentences that were about something else: a complaint stopped a film,
    and a sentence of ELI's own explanation was run as a command. Two tests of form:

      * a sentence of the message is an instruction (command_splitter.instruction), not a
        statement or a question about what happened;
      * beyond the command's own words (its verb, its action, what it captured) the message says
        little: an instruction is about its action. Long text an action captured as its argument
        (a search, a title, a note) is the command's own words. (A rule that passes the whole
        message along as an argument is therefore held to the first test only.)

    Reading actions always fit: a report given by mistake changes nothing."""
    if not isinstance(intent, dict) or not changes_something(intent.get("action")):
        return True
    from eli.runtime.command_splitter import instruction, sentences, starts_with_command
    own = set(_words(intent.get("args"))) | set(_words((intent.get("meta") or {}).get("entities")))
    own |= set(str(intent.get("action") or "").lower().split("_"))
    said, told_something = [], False
    for sentence in sentences(str(text or "")):
        told = instruction(sentence)
        words = [w for w in _WORD.findall((told or sentence).lower()) if w not in _GRAMMAR]
        if told and (words or starts_with_command(told)):   # "well done." tells nothing; "do it" does
            told_something = True
            own.update(words[:1])                  # the verb the instruction starts with
        said += words
    if not told_something:
        return False
    spare = [w for w in said if w not in own and not any(_same_word(w, o) for o in own)]
    return len(spare) < 6 or len(spare) <= len(said) - len(spare)
