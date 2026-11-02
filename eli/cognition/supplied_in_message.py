"""What a message brings with it: facts to reason from, and text that is material rather than orders.

Three parts of the pipeline ask this and used to ask it in their own words: whether a question needs
the outside world (grounding), whether a date in it is a window on history (the planner), and whether
a command in it is an order (the router, and the engine before it runs one).
"""
from __future__ import annotations

from datetime import date, timedelta
import re
from typing import Any, Iterable, Optional, Tuple

_ISO = re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)")
_NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
                 "nine": 9, "ten": 10}
_DATE_OFFSET = re.compile(
    rf"\b(\d{{1,4}}|{'|'.join(_NUMBER_WORDS)})\s+(?:calendar\s+)?(days?|weeks?)\s+"
    r"(later|after|earlier|before)\b", re.I)
_ASKS_FOR_A_DATE = re.compile(
    r"\b(?:date\s+(?:calculation|arithmetic)|calculat(?:e|ing)\s+(?:the\s+)?date|"
    r"(?:what|which)\s+(?:date|day)\s+(?:is|will|would|was)|yyyy-mm-dd)\b", re.I)
_ABOUT_HISTORY = re.compile(
    r"\b(?:what\s+did|what\s+happened|what\s+was\s+recorded|when\s+did|conversation|action\s+ledger|"
    r"history|logs?|recorded\s+actions?|past\s+messages?)\b", re.I)
_OUTSIDE_CHECK = re.compile(
    r"\b(?:verify|fact[- ]check|browse|look\s+up\s+online|search\s+(?:the\s+)?(?:web|internet)|"
    r"latest\s+news|as\s+of\s+now|right\s+now)\b", re.I)
_CURRENT_WORLD = re.compile(r"\b(?:latest|current|today|live)\b", re.I)
_OPERATION = re.compile(
    r"\d\s*(?:[+*×÷^%]|\s-\s|mod(?:ulo)?\b|plus\b|minus\b|times\b|divided\s+by\b|multiplied\s+by\b|"
    r"to\s+the\s+power\s+of\b|percent\s+of\b)\s*\d|"
    r"\b(?:remainder|modulo|sum|product|average|square\s+root)\b[^?]*\d", re.I)
_REPLACED_OLD = re.compile(r"\b(?:old|obsolete|previous|earlier|former)\b", re.I)
_REPLACED_NEW = re.compile(r"\b(?:final|signed|corrected|revised|replacement|updated|new)\b", re.I)
_CORRECTION_WORD = re.compile(r"\b(?:correction|corrected|replaced|obsolete|revised|updated)\b", re.I)
_IF_NOT_SUPPLIED = re.compile(
    r"\bif\s+(?:the\s+)?(?:answer|that|it|this)\s+(?:is\s+|was\s+)?(?:not|isn['’]t|wasn['’]t)\s+"
    r"(?:provided|given|supplied|stated|mentioned|there|in\s+(?:the|this)\s+\w+)\b", re.I)
_FROM_THE_MATERIAL = re.compile(
    r"\b(?:according\s+to|based\s+(?:only\s+|solely\s+)?on|given|from)\s+"
    r"(?:the\s+|this\s+)?(?:above|following|text|passage|excerpt|paragraph|record|information\s+(?:above|supplied|provided))\b",
    re.I)
_RULES = re.compile(r"\brules?\s*:\s*if\b", re.I)
_HYPOTHETICAL = re.compile(r"\b(?:counterfactual|hypothetical)\b", re.I)
_PREMISE = re.compile(r"\b(?:rules?|if|suppose|assume|given)\b", re.I)
_STATED_VALUE = re.compile(r"\b[a-z]+\s*(?:is|=|:)\s*[\w.-]+\b", re.I)
_ENTITY_KEY = re.compile(r"\b[a-z][a-z0-9_]*[-_]\d+\b", re.I)
_GRAMMAR = frozenset("""a an the this that these those is are was were be which what who whom how why when where
    does do did has have had of in on at to for from with and or it its i you your my me we our they their
    please only reply answer say""".split())
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n+")


def date_offset(text: Any) -> Optional[Tuple[str, int]]:
    """(the one ISO date, the one signed offset in days) a message counts from, or None if it holds
    any other number of either: choosing between several would be guessing."""
    said = str(text or "")
    seeds = _ISO.findall(said)
    offsets = list(_DATE_OFFSET.finditer(said))
    if len(set(seeds)) != 1 or len(offsets) != 1:
        return None
    try:
        date.fromisoformat(seeds[0])
    except ValueError:
        return None
    amount, unit, way = offsets[0].groups()
    days = int(amount) if amount.isdigit() else _NUMBER_WORDS[amount.lower()]
    days *= 7 if unit.lower().startswith("week") else 1
    return seeds[0], days if way.lower() in ("later", "after") else -days


def worked_out_date(text: Any) -> Optional[str]:
    """The date a message's own date and offset arrive at."""
    found = date_offset(text)
    if not found:
        return None
    try:
        return (date.fromisoformat(found[0]) + timedelta(days=found[1])).isoformat()
    except OverflowError:
        return None


def is_date_arithmetic(text: Any) -> bool:
    """A date used as the operand of a calculation, not a window on what happened that day."""
    said = str(text or "")
    return bool(date_offset(said) and _ASKS_FOR_A_DATE.search(said) and not _ABOUT_HISTORY.search(said))


_NUMBER = r"(-?\d+(?:\.\d+)?)"
_BINARY = re.compile(
    rf"{_NUMBER}\s*(\+|\*|×|÷|\^|\s-\s|mod(?:ulo)?\b|plus\b|minus\b|times\b|multiplied\s+by\b|divided\s+by\b)\s*{_NUMBER}", re.I)
_REMAINDER = re.compile(rf"\bremainder\s+(?:when|of)\s+{_NUMBER}\s+(?:is\s+)?divided\s+by\s+{_NUMBER}", re.I)
_PERCENT = re.compile(rf"{_NUMBER}\s*(?:%|percent)\s+of\s+{_NUMBER}", re.I)
_OF_TWO = re.compile(rf"\b(sum|product|average)\s+of\s+{_NUMBER}\s+and\s+{_NUMBER}", re.I)
_LARGEST_POWER = 1024       # past this a number has no place in a sentence


def _worked(op: str, a: float, b: float) -> Optional[float]:
    op = op.strip().lower().split()[0]
    if op in ("+", "plus", "sum"):
        return a + b
    if op in ("-", "minus"):
        return a - b
    if op in ("*", "×", "times", "multiplied", "product"):
        return a * b
    if op == "average":
        return (a + b) / 2
    if op in ("÷", "divided"):
        return a / b if b else None
    if op in ("mod", "modulo"):
        return a % b if b else None
    if op == "^":
        return a ** b if abs(b) <= _LARGEST_POWER else None
    return None


def _shown(n: float) -> str:
    return str(int(n)) if float(n).is_integer() else f"{n:.10g}"


def worked_out(text: Any) -> str:
    """The sums and date offsets in a message, worked out here: the model is not a calculator, and
    told what 56 mod 17 is it does not have to guess. Empty when the message holds none."""
    said = str(text or "")
    lines = []
    when = worked_out_date(said)
    if when:
        lines.append(f"{date_offset(said)[0]} {date_offset(said)[1]:+d} days is {when}")
    bare = _ISO.sub(" ", said)
    for a, b in _REMAINDER.findall(bare):
        if float(b):
            lines.append(f"{a} divided by {b} leaves a remainder of {_shown(float(a) % float(b))}")
    for a, b in _PERCENT.findall(bare):
        lines.append(f"{a}% of {b} is {_shown(float(a) * float(b) / 100)}")
    for op, a, b in _OF_TWO.findall(bare):
        lines.append(f"the {op.lower()} of {a} and {b} is {_shown(_worked(op, float(a), float(b)))}")
    for a, op, b in _BINARY.findall(bare):
        value = _worked(op, float(a), float(b))
        if value is not None:
            lines.append(f"{a} {' '.join(op.split())} {b} = {_shown(value)}")
    return "; ".join(dict.fromkeys(lines))


def _question_and_rest(said: str) -> Tuple[str, str]:
    parts = [p for p in _SENTENCE_END.split(said) if p.strip()]
    for i, part in enumerate(parts):
        if part.rstrip().endswith("?"):
            return part, " ".join(parts[:i] + parts[i + 1:])
    return "", said


def _words(text: str) -> Iterable[str]:
    return (w for w in re.findall(r"[a-z0-9][a-z0-9_-]*", text.lower()) if w not in _GRAMMAR)


def _replaced_in_the_message(said: str) -> bool:
    """It says what was replaced by what, and asks about what it said."""
    if not (_REPLACED_OLD.search(said) and _REPLACED_NEW.search(said)):
        return False
    question, rest = _question_and_rest(said)
    return bool(set(_words(question)) & set(_words(rest)))


def holds_its_own_answer(text: Any) -> bool:
    """Whether a question can be reasoned out from what the message itself supplies. It decides only
    whether to go to the outside world: it does not make what the person supplied true."""
    said = str(text or "").strip()
    if "?" not in said or _OUTSIDE_CHECK.search(said):
        return False
    without_dates = _ISO.sub(" ", said)
    if (is_date_arithmetic(said) or _replaced_in_the_message(said) or _IF_NOT_SUPPLIED.search(said)
            or _FROM_THE_MATERIAL.search(said)):
        return True
    if _OPERATION.search(without_dates) and not _CURRENT_WORLD.search(said):
        return True
    if _CURRENT_WORLD.search(said):       # a passage does not settle what is true now
        return False
    return bool(_RULES.search(said) or (_HYPOTHETICAL.search(said) and _PREMISE.search(said))
                or (supplied_as_data(said) and _STATED_VALUE.search(said)))


def corrected_earlier(question: Any, recent_turns: Any) -> bool:
    """The person already corrected the thing this asks about, by name, earlier in the conversation.
    What they said is the evidence here, not the web; ELI's own lines never count as a correction."""
    keys = _ENTITY_KEY.findall(str(question or ""))
    if not keys or not isinstance(recent_turns, (list, tuple)):
        return False
    for turn in reversed(recent_turns):
        if isinstance(turn, dict):
            role, content = turn.get("role") or turn.get("speaker"), turn.get("content") or turn.get("text")
        elif isinstance(turn, (list, tuple)) and len(turn) >= 2:
            role, content = turn[0], turn[1]
        else:
            continue
        if str(role or "").lower() in ("user", "human") and _CORRECTION_WORD.search(str(content or "")) and any(
                re.search(rf"(?<!\w){re.escape(k)}(?!\w)", str(content), re.I) for k in keys):
            return True
    return False


_MATERIAL_LEAD = re.compile(
    r"^\s*(?:please\s+)?(?:analy[sz]e|read|interpret|treat|consider|evaluate)\s+(?:"
    r"(?:(?:this|the\s+following)\s+as\s+)?(?:(?:an?|the)\s+)?(?:untrusted|quoted|supplied|provided)\b|"
    r"(?:this|the\s+following)\s+as\s+(?:(?:an?|the)\s+)?(?:data|text|reference)\b)", re.I)
_NOT_ORDERS = re.compile(
    r"\b(?:without\s+(?:executing|running|following)|do\s+not\s+(?:execute|run|follow)|"
    r"don['’]t\s+(?:execute|run|follow)|not\s+instructions)\b", re.I)
_MATERIAL_WORD = re.compile(r"\b(?:untrusted|quoted)\b", re.I)
_QUOTED_SPAN = re.compile(r'"[^"\n]*"|“[^”\n]*”|`[^`\n]*`')
_REPORTED = re.compile(
    r"\b(?:says?|said|reads?|states?|wrote|writes|following|text|passage|excerpt|memo|email|document|"
    r"analysis|quote)\s*:\s.*$", re.I | re.S)


def supplied_as_data(text: Any) -> bool:
    """The person says this text is something to look at, not something to carry out."""
    said = str(text or "")
    return bool(_MATERIAL_LEAD.match(said) or (_MATERIAL_WORD.search(said) and _NOT_ORDERS.search(said)))


def without_supplied_text(text: Any) -> str:
    """The message without what it quotes or reports: a command in there is what someone else wrote,
    and a question beside it does not make the person's own "open spotify" any less of an order."""
    return _REPORTED.sub(" ", _QUOTED_SPAN.sub(" ", str(text or ""))).strip()
