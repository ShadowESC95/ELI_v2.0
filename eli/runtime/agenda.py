"""The agenda: ELI's own calendar and reminders.

ADD_EVENT and LIST_EVENTS used to return "Calendar integration is not configured" as a
success, and a reminder was a sleeping thread with no label that died with the app. This is
the local store both now use: events and reminders in one SQLite file, mirrored to a standard
.ics file any calendar app can open, with a notifier that fires them and picks up again after
a restart. No account, provider or network is involved.

Also here: reading a day and a time out of ordinary wording ("not until 7.30pm", "tomorrow at
3", "in 20 minutes", "friday morning"), and a title out of the rest of the sentence.
"""
from __future__ import annotations

import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from eli.utils.log import get_logger

log = get_logger(__name__)

# Before an event with a time: a nudge this long ahead, and one as it starts.
DEFAULT_REMIND_BEFORE_MIN = (30, 0)
# A reminder that came due while ELI was shut is still delivered if it is this recent.
_MISSED_WINDOW_S = 18 * 3600
_DEFAULT_EVENT_MIN = 60

_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september",
           "october", "november", "december")
_MONTH_RE = "|".join(f"{m}|{m[:3]}" for m in _MONTHS) + "|sept"
_PART_OF_DAY = {"morning": 9, "afternoon": 14, "evening": 18, "night": 20, "tonight": 20, "lunchtime": 13}

_CLOCK = re.compile(
    r"(?<![\w.:/])(?:(?P<h>\d{1,2})[:.](?P<m>\d{2})\s*(?P<ap>a\.?m\.?|p\.?m\.?)?"      # 7.30pm, 19:30
    r"|(?P<h2>\d{1,2})\s*(?P<ap2>a\.?m\.?|p\.?m\.?)"                                    # 7pm
    r"|(?P<word>noon|midday|midnight))(?![\w:])", re.I)
_BARE_HOUR = re.compile(r"\b(?:at|by|until|till|from|for|@)\s+(?P<h>\d{1,2})(?:\s*o'?clock)?(?![\w:.]|\s*(?:am|pm|minutes?|mins?|hours?|hrs?|days?|weeks?|%))", re.I)
_HALF = re.compile(r"\b(?:half(?:\s+past)?|(?P<q>quarter)\s+(?P<pt>past|to))\s+(?P<h>\d{1,2})\b", re.I)
_RELATIVE = re.compile(
    r"\bin\s+(?:(?P<n>\d+|an?|half an?|a couple of|a few)\s+)?(?P<unit>minutes?|mins?|hours?|hrs?|days?|weeks?)\b"
    r"|\bin\s+half\s+an\s+hour\b", re.I)
_NUMERIC_DATE = re.compile(r"\b(?P<a>\d{1,4})[-/](?P<b>\d{1,2})[-/](?P<c>\d{1,4})\b")
_NAMED_DATE = re.compile(
    rf"\b(?:(?P<d>\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?(?P<mon>{_MONTH_RE})\.?|(?P<mon2>{_MONTH_RE})\.?\s+(?P<d2>\d{{1,2}})(?:st|nd|rd|th)?)"
    r"(?:,?\s+(?P<y>\d{4}))?\b", re.I)
_WEEKDAY = re.compile(rf"\b(?:(?P<mod>next|this|on|coming)\s+)?(?P<wd>{'|'.join(_WEEKDAYS)})\b", re.I)
_DAY_WORD = re.compile(r"\b(?P<w>day after tomorrow|tomorrow|tonight|today|this (?:morning|afternoon|evening)|tmrw|tomoz)\b", re.I)
_PART = re.compile(r"\b(?:in the |this |that )?(?P<p>morning|afternoon|evening|night|lunchtime)\b", re.I)
# "not until 7.30", "moved to 3pm", "it's actually at 4": the time that replaces the one before it.
_CORRECTS = re.compile(r"\b(?:not\s+(?:until|till)|until|till|actually|instead|moved\s+to|pushed\s+to|changed\s+to|"
                       r"now\s+at|rather|turns?\s+out)\b[^.;!?]{0,24}$", re.I)

_EVENT_NOUN = (r"presentation|meeting|appointment|interview|exam|test|class|lecture|call|session|dinner|lunch|breakfast|"
               r"brunch|party|flight|train|bus|gig|concert|match|game|deadline|viva|seminar|workshop|shift|birthday|"
               r"wedding|funeral|check-?up|review|demo|stand-?up|webinar|tutorial|lab|haircut|dentist|doctor|gp|"
               r"physio|vet|collection|delivery|pickup|pick-up|drinks|date|trip|hearing|rehearsal|training|practice")
_EVENT_PHRASE = re.compile(
    rf"\b(?:(?:a|an|my|the|our|that|this)\s+)?(?P<pre>(?:[A-Za-z][\w'&-]*\s+){{0,2}}?)(?P<noun>{_EVENT_NOUN})\b"
    rf"(?:\s+(?P<prep>for|with|about|on)\s+(?P<obj>(?:(?:the|my|our|a|an)\s+)?[A-Za-z0-9][\w'&-]*(?:\s+[A-Z0-9][\w'&-]*){{0,3}}))?", re.I)
# Words that sit in front of an event's name without being part of it.
_NOT_NAME = frozenset("""i i've i'm we you had have has got a an the my our your that this thought think is was be been
to about me for of at on and but some another upcoming new next it its there so then just also add put create make
schedule book set log save note remember pencil in with please""".split())
_ASIDE = re.compile(r"\([^)]*\)")
_CAL_TARGET = re.compile(r"\b(?:in|into|to|on|onto)\s+(?:my|the|your|our)\s+(?:calendar|calender|diary|agenda|schedule)\b", re.I)
_WHEN_LEAD = re.compile(r"\b(?:not\s+(?:until|till)|at|by|until|till|from|around|about|for|on|@)\s+(?:the\s+)?$|\bthe\s+$", re.I)
_REMIND = re.compile(r"\b(?:remind(?:\s+(?:me|us))?|(?:set(?:ting)?|add|create)\s+(?:(?:a|an|another|the)\s+)?reminders?|reminders?)\b(?P<body>.*)$", re.I | re.S)
_LEAD_CMD = re.compile(
    r"^(?:(?:please|pls|can you|could you|would you|will you|eli|hey|ok(?:ay)?|and|then|also|just|you|i need to|i have to|"
    r"consider|maybe|let'?s|no|sorry|wait|actually|cancel that|i meant?|make (?:it|that)|it'?s|it is|that'?s)\b[\s,.!]*"
    r"|(?:add|put|create|make|schedule|book|pencil in|set(?: up)?|setting|log|save|note|remember)\b\s*"
    r"|(?:(?:a|an|the|my|another|new)\s+)*(?:event|entry|reminder|alarm)s?\b\s*"
    r"|(?:to|about|of|for|that|me|us|you|called|named|titled|saying|as|is)\b\s*"
    r"|(?:alert|notify|tell|warn|nudge|ping)\s+(?:me|you|us)\b\s*)+", re.I)
_TRAIL_GLUE = re.compile(r"(?:[\s,]+(?:to|at|on|by|for|from|until|till|and|but|is|it|not|haha+|lol|please|pls|as))+\s*$", re.I)
# A label that names nothing ("the upcoming meeting", "a final check-in point").
_GENERIC_LABEL = re.compile(
    r"^(?:(?:a|an|the|my|your|this|that|another|final|upcoming|next|quick|last)\s+)*"
    r"(?:reminder|check-?in(?:\s+point)?|meeting|event|appointment|presentation|thing|it|alert|heads-?up|point)?$", re.I)


class When:
    """A parsed moment: when, whether the wording gave a time of day, and what text said it."""
    __slots__ = ("start", "has_time", "has_date", "spans")

    def __init__(self, start: datetime, has_time: bool, has_date: bool, spans: List[Tuple[int, int]]):
        self.start, self.has_time, self.has_date, self.spans = start, has_time, has_date, spans


def _ampm(text: Optional[str]) -> Optional[str]:
    t = (text or "").lower().replace(".", "")
    return t if t in ("am", "pm") else None


def _clock_candidates(text: str) -> List[Tuple[int, int, int, int, Optional[str]]]:
    """(start, end, hour, minute, am/pm) for each time of day in `text`."""
    out = []
    for m in _CLOCK.finditer(text):
        if m.group("word"):
            w = m.group("word").lower()
            out.append((m.start(), m.end(), 0 if w == "midnight" else 12, 0, "am" if w == "midnight" else "pm"))
            continue
        h = int(m.group("h") or m.group("h2"))
        mi = int(m.group("m") or 0)
        ap = _ampm(m.group("ap") or m.group("ap2"))
        if h > 23 or mi > 59 or (ap and h > 12):
            continue
        # "7.30" with no am/pm and no cue in front is as likely a version number or a score
        if m.group("m") and not ap and "." in m.group(0) and not re.search(
                r"\b(?:at|by|until|till|from|for|around|about|@)\s*$", text[:m.start()], re.I):
            continue
        # "06:45" is the morning as written; only an unpadded hour is open to "which half of the day"
        if not ap and (m.group("h") or "").startswith("0"):
            ap = "am"
        out.append((m.start(), m.end(), h, mi, ap))
    for m in _HALF.finditer(text):
        h = int(m.group("h"))
        if not 1 <= h <= 12:
            continue
        if m.group("q"):
            h, mi = (h, 15) if m.group("pt").lower() == "past" else ((h - 1) or 12, 45)
        else:
            mi = 30
        out.append((m.start(), m.end(), h, mi, None))
    taken = [(a, b) for a, b, *_ in out]
    for m in _BARE_HOUR.finditer(text):
        h = int(m.group("h"))
        if 0 <= h <= 23 and not any(a <= m.start("h") < b for a, b in taken):
            out.append((m.start(), m.end(), h, 0, None))
    return sorted(out)


def parse_when(text: Any, now: Optional[datetime] = None) -> Optional[When]:
    """The day and time a sentence names, as its next future occurrence. None when it names neither."""
    raw = str(text or "")
    now = now or datetime.now()
    spans: List[Tuple[int, int]] = []

    rel = _RELATIVE.search(raw)
    if rel:
        n_txt = (rel.group("n") or "").lower() if rel.groupdict().get("n") else ""
        unit = (rel.group("unit") or "hour").lower()
        if "half" in rel.group(0).lower() and not rel.group("unit"):
            delta = timedelta(minutes=30)
        else:
            n = {"": 1.0, "a": 1.0, "an": 1.0, "half a": 0.5, "half an": 0.5, "a couple of": 2.0, "a few": 3.0}.get(
                n_txt, float(n_txt) if n_txt.isdigit() else 1.0)
            delta = (timedelta(minutes=n) if unit.startswith("min") else timedelta(hours=n) if unit.startswith(("hour", "hr"))
                     else timedelta(days=n) if unit.startswith("day") else timedelta(weeks=n))
        return When((now + delta).replace(second=0, microsecond=0), True, True, [rel.span()])

    day: Optional[datetime] = None
    part_hour: Optional[int] = None
    weekday_named = False
    m = _DAY_WORD.search(raw)
    if m:
        w = m.group("w").lower()
        day = now + timedelta(days=2 if "after" in w else 1 if w in ("tomorrow", "tmrw", "tomoz") else 0)
        if w == "tonight":
            part_hour = _PART_OF_DAY["tonight"]
        elif w.startswith("this "):
            part_hour = _PART_OF_DAY[w.split()[1]]
        spans.append(m.span())
    if day is None:
        m = _NAMED_DATE.search(raw)
        if m:
            mon = (m.group("mon") or m.group("mon2")).lower()[:3]
            month = [x[:3] for x in _MONTHS].index("sep" if mon == "sep" else mon) + 1
            d = int(m.group("d") or m.group("d2"))
            year = int(m.group("y") or now.year)
            try:
                day = now.replace(year=year, month=month, day=d)
                if not m.group("y") and day.date() < now.date():
                    day = day.replace(year=year + 1)
                spans.append(m.span())
            except ValueError:
                day = None
    if day is None:
        m = _NUMERIC_DATE.search(raw)
        if m:
            a, b, c = int(m.group("a")), int(m.group("b")), int(m.group("c"))
            try:
                # 2026-10-05, else day first (05/10/2026); month first only when day first is impossible
                if a > 31:
                    day = now.replace(year=a, month=b, day=c)
                elif b > 12:
                    day = now.replace(year=c if c > 99 else 2000 + c, month=a, day=b)
                else:
                    day = now.replace(year=c if c > 99 else 2000 + c, month=b, day=a)
                spans.append(m.span())
            except ValueError:
                day = None
    if day is None:
        m = _WEEKDAY.search(raw)
        if m:
            ahead = (_WEEKDAYS.index(m.group("wd").lower()) - now.weekday()) % 7
            if (m.group("mod") or "").lower() == "next" and ahead < 7:
                ahead = ahead or 7
            day = now + timedelta(days=ahead)
            weekday_named = True
            spans.append(m.span())
    pm = _PART.search(raw)
    if pm and part_hour is None:
        part_hour = _PART_OF_DAY[pm.group("p").lower()]
        if not any(a <= pm.start() < b for a, b in spans):
            spans.append(pm.span())

    clocks = _clock_candidates(raw)
    chosen = None
    if clocks:
        corrected = [c for c in clocks if _CORRECTS.search(raw[:c[0]])]
        chosen = (corrected or clocks)[-1] if corrected else clocks[0]
        spans.extend((c[0], c[1]) for c in clocks)
    has_date = day is not None
    if chosen is None and part_hour is None and not has_date:
        return None

    base = (day or now).replace(second=0, microsecond=0)
    if chosen is not None:
        _, _, h, mi, ap = chosen
        if ap == "pm" and h < 12:
            h += 12
        elif ap == "am" and h == 12:
            h = 0
        elif ap is None and h <= 12:
            # no am/pm: the part of day decides; else 1-6 is the afternoon ("half 1", "at 3"), and
            # with no day named it is the next time the clock shows that hour
            if part_hour is not None:
                if part_hour >= 12 and h < 12:
                    h += 12
            elif 1 <= h <= 6:
                h += 12
            elif not has_date:
                first = base.replace(hour=h % 24, minute=mi)
                if first <= now and h < 12 and base.replace(hour=h + 12, minute=mi) > now:
                    h += 12
        start = base.replace(hour=h % 24, minute=mi)
        if start <= now and not has_date:
            start += timedelta(days=1)
        elif start <= now and weekday_named:
            start += timedelta(days=7)  # "monday at 9", said on a Monday after 9
        return When(start, True, has_date, spans)
    if part_hour is not None:
        start = base.replace(hour=part_hour, minute=0)
        if start <= now and not has_date:
            start += timedelta(days=1)
        return When(start, True, has_date, spans)
    start = base.replace(hour=0, minute=0)
    if start.date() < now.date():
        start += timedelta(days=7)
    return When(start, False, True, spans)


def _without_when(raw: str, when: Optional[When]) -> str:
    """`raw` with the words that gave the day and time taken out, along with the preposition
    in front of each ("at 10am", "on friday") and any bracketed aside."""
    cut = raw
    for a, b in sorted((when.spans if when else []), reverse=True):
        lead = _WHEN_LEAD.search(cut[:a])
        cut = cut[:lead.start() if lead else a] + " " + cut[b:]
    return re.sub(r"\s+", " ", _ASIDE.sub(" ", cut)).strip()


def title_from(text: Any, when: Optional[When] = None) -> str:
    """What the event or reminder is, from the sentence that named it. "" when it names nothing."""
    raw = str(text or "")
    quoted = re.search(r"[\"“]([^\"”]{2,80})[\"”]", raw)
    if quoted:
        return _tidy(quoted.group(1))
    cut = _CAL_TARGET.sub(" ", _without_when(raw, when))
    named = re.search(r"\b(?:called|named|titled)\s+(.{2,80}?)(?:[.!?]|$)", cut, re.I)
    if named:
        return _tidy(named.group(1))
    remind = _REMIND.search(cut)
    if remind:
        return _tidy(_TRAIL_GLUE.sub("", _LEAD_CMD.sub("", remind.group("body").strip(" ,.;:!?"))))
    for m in _EVENT_PHRASE.finditer(cut):
        lead = m.group(0)[:m.start("noun") - m.start()].split()
        article = any(w.lower() in ("a", "an", "my", "the", "our", "that", "this") for w in lead)
        # the name is what sits directly on the noun ("RAIMS presentation"), not words further back
        pre_words = (m.group("pre") or "").split()
        while pre_words and any(w.lower() in _NOT_NAME for w in pre_words):
            pre_words.pop(0)
        pre = " ".join(pre_words)
        obj = re.sub(r"^(?:the|my|our|a|an)\s+", "", (m.group("obj") or "").strip(), flags=re.I)
        obj = re.sub(r"\s+(?:but|and|so|haha+|lol|is|it|at|on|until|then)\b.*$", "", obj, flags=re.I).strip(" ,.;")
        obj = "" if obj.lower() in ("the", "a", "an", "my") else obj
        noun = m.group("noun")
        more = re.match(rf"\s+({_EVENT_NOUN})\b", cut[m.end("noun"):], re.I)
        if more and not obj:
            return _tidy(f"{pre} {noun} {more.group(1)}")
        if not (pre or obj or article):
            continue  # "call the bank": a verb here, not "a call"
        if obj and (m.group("prep") or "").lower() == "for" and len(obj.split()) <= 3:
            return _tidy(f"{obj} {pre} {noun}")
        return _tidy(f"{pre} {noun} {m.group('prep')} {obj}" if obj else f"{pre} {noun}")
    return _tidy(_TRAIL_GLUE.sub("", _LEAD_CMD.sub("", cut.strip(" ,.;:!?"))))


def generic_label(title: Any) -> bool:
    """The label names nothing of its own ("the upcoming meeting"), so an event's name serves better."""
    return bool(_GENERIC_LABEL.match(str(title or "").strip()))


def _tidy(title: str) -> str:
    t = re.sub(r"\s+", " ", str(title or "")).strip(" ,.;:!?-\"'")
    t = re.sub(r"^(?:(?:a|an|the)\s+)", "", t, flags=re.I) if len(t.split()) > 1 else t
    return (t[:1].upper() + t[1:])[:120] if t else ""


def describe(ts: float, now: Optional[datetime] = None, *, has_time: bool = True) -> str:
    """"today (Mon 5 Oct) at 19:30", "tomorrow (Tue 6 Oct) at 09:00", "Fri 9 Oct, all day"."""
    now = now or datetime.now()
    dt = datetime.fromtimestamp(ts)
    days = (dt.date() - now.date()).days
    day = f"{dt.strftime('%a')} {dt.day} {dt.strftime('%b')}" + (f" {dt.year}" if dt.year != now.year else "")
    lead = "today" if days == 0 else "tomorrow" if days == 1 else "yesterday" if days == -1 else ""
    where = f"{lead} ({day})" if lead else day
    return f"{where} at {dt.strftime('%H:%M')}" if has_time else f"{where}, all day"


# ── the store ────────────────────────────────────────────────────────────────

def _db_path() -> Path:
    from eli.core.paths import agenda_db_path
    return agenda_db_path()


def _connect() -> sqlite3.Connection:
    p = _db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(p), timeout=10.0)
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE IF NOT EXISTS agenda(
            id INTEGER PRIMARY KEY,
            kind TEXT NOT NULL,                 -- 'event' or 'reminder'
            title TEXT NOT NULL,
            start_ts REAL NOT NULL,
            end_ts REAL,
            has_time INTEGER NOT NULL DEFAULT 1,
            event_id INTEGER,                   -- a reminder that belongs to an event
            user_id TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT '',
            created_ts REAL NOT NULL,
            fired_ts REAL,
            cancelled_ts REAL);
        CREATE INDEX IF NOT EXISTS agenda_due ON agenda(kind, start_ts);
    """)
    return con


_lock = threading.RLock()
_wake = threading.Event()
_thread: Optional[threading.Thread] = None
_deliver: Optional[Callable[[Dict[str, Any], bool], None]] = None


def _scope(user_id: str) -> Tuple[str, tuple]:
    uid = str(user_id or "")
    try:
        from eli.kernel.state import get_active_user_id
        owner = (not uid) or uid == str(get_active_user_id())
    except Exception:
        owner = True
    return ("user_id IN (?, '')", (uid,)) if owner else ("user_id = ?", (uid,))


def add_event(title: str, start_ts: float, *, has_time: bool = True, duration_min: int = _DEFAULT_EVENT_MIN,
              remind_before_min: Sequence[int] = DEFAULT_REMIND_BEFORE_MIN, user_id: str = "",
              source: str = "") -> Dict[str, Any]:
    """Put an event on the calendar, with its reminders. Returns the stored event."""
    title = _tidy(title) or "Event"
    now = time.time()
    end_ts = start_ts + (duration_min * 60 if has_time else 86400)
    with _lock:
        con = _connect()
        try:
            same = con.execute(
                "SELECT id FROM agenda WHERE kind='event' AND cancelled_ts IS NULL AND user_id=? AND lower(title)=? "
                "AND abs(start_ts - ?) < 60", (str(user_id or ""), title.lower(), start_ts)).fetchone()
            if same:
                return {**get(int(same["id"])), "already": True}
            cur = con.execute(
                "INSERT INTO agenda(kind, title, start_ts, end_ts, has_time, user_id, source, created_ts) VALUES "
                "('event',?,?,?,?,?,?,?)", (title, start_ts, end_ts, int(has_time), str(user_id or ""), str(source or ""), now))
            event_id = int(cur.lastrowid)
            reminders = []
            for mins in (sorted(set(int(x) for x in remind_before_min), reverse=True) if has_time else ()):
                at = start_ts - mins * 60
                if at > now + 5:
                    con.execute(
                        "INSERT INTO agenda(kind, title, start_ts, has_time, event_id, user_id, source, created_ts) VALUES "
                        "('reminder',?,?,1,?,?,?,?)",
                        (title if mins == 0 else f"{title} in {mins} minutes", at, event_id, str(user_id or ""), "event", now))
                    reminders.append(at)
            con.commit()
        finally:
            con.close()
    _export_ics()
    _ledger("ADD_EVENT", title, describe(start_ts, has_time=has_time), user_id)
    _arm()
    return {"id": event_id, "kind": "event", "title": title, "start_ts": start_ts, "end_ts": end_ts,
            "has_time": has_time, "reminders": reminders}


def add_reminder(title: str, at_ts: float, *, user_id: str = "", source: str = "") -> Dict[str, Any]:
    """A reminder on its own: delivered at `at_ts`, and kept across restarts until then."""
    title = _tidy(title) or "Reminder"
    with _lock:
        con = _connect()
        try:
            cur = con.execute(
                "INSERT INTO agenda(kind, title, start_ts, has_time, user_id, source, created_ts) VALUES ('reminder',?,?,1,?,?,?)",
                (title, at_ts, str(user_id or ""), str(source or ""), time.time()))
            con.commit()
            rid = int(cur.lastrowid)
        finally:
            con.close()
    _ledger("SET_REMINDER", title, describe(at_ts), user_id)
    _arm()
    return {"id": rid, "kind": "reminder", "title": title, "start_ts": at_ts, "has_time": True}


def get(item_id: int) -> Dict[str, Any]:
    con = _connect()
    try:
        r = con.execute("SELECT * FROM agenda WHERE id=?", (int(item_id),)).fetchone()
        return dict(r) if r else {}
    finally:
        con.close()


def between(since_ts: float, until_ts: float, *, user_id: str = "", kinds: Sequence[str] = ("event", "reminder"),
            own_reminders_only: bool = True) -> List[Dict[str, Any]]:
    """What is on the agenda in a period, earliest first. An event's own reminders are left out
    unless asked for: the event line already says when it is."""
    where, args = _scope(user_id)
    marks = ",".join("?" * len(kinds))
    con = _connect()
    try:
        rows = con.execute(
            f"SELECT * FROM agenda WHERE cancelled_ts IS NULL AND kind IN ({marks}) AND start_ts < ? AND "
            f"COALESCE(end_ts, start_ts) >= ? AND {where}"
            + (" AND event_id IS NULL" if own_reminders_only else "") + " ORDER BY start_ts",
            (*kinds, until_ts, since_ts, *args)).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def cancel(ids: Sequence[int], *, user_id: str = "") -> List[Dict[str, Any]]:
    """Take events or reminders off the agenda (an event's reminders go with it)."""
    where, args = _scope(user_id)
    wanted = [int(i) for i in ids or []]
    if not wanted:
        return []
    marks = ",".join("?" * len(wanted))
    with _lock:
        con = _connect()
        try:
            gone = [dict(r) for r in con.execute(
                f"SELECT * FROM agenda WHERE id IN ({marks}) AND cancelled_ts IS NULL AND {where}", (*wanted, *args))]
            if gone:
                now = time.time()
                hit = [g["id"] for g in gone]
                m2 = ",".join("?" * len(hit))
                con.execute(f"UPDATE agenda SET cancelled_ts=? WHERE id IN ({m2}) OR event_id IN ({m2})", (now, *hit, *hit))
                con.commit()
        finally:
            con.close()
    if gone:
        _export_ics()
        for g in gone:
            _ledger("CANCEL", g["title"], describe(g["start_ts"], has_time=bool(g["has_time"])), user_id)
        _arm()
    return gone


def latest_event(*, user_id: str = "", within_s: float = 1800.0) -> Optional[Dict[str, Any]]:
    """The event most recently put on the calendar, if that was in the last half hour: what
    "it" means in "move it to 8pm"."""
    where, args = _scope(user_id)
    con = _connect()
    try:
        r = con.execute(
            f"SELECT * FROM agenda WHERE kind='event' AND cancelled_ts IS NULL AND created_ts >= ? AND {where} "
            "ORDER BY created_ts DESC, id DESC LIMIT 1", (time.time() - within_s, *args)).fetchone()
        return dict(r) if r else None
    finally:
        con.close()


def move_event(event_id: int, start_ts: float, *, has_time: bool = True,
               remind_before_min: Sequence[int] = DEFAULT_REMIND_BEFORE_MIN) -> Dict[str, Any]:
    """Give an event a new time. Its old reminders are replaced by ones for the new time."""
    now = time.time()
    with _lock:
        con = _connect()
        try:
            ev = con.execute("SELECT * FROM agenda WHERE id=? AND kind='event' AND cancelled_ts IS NULL",
                             (int(event_id),)).fetchone()
            if not ev:
                return {}
            length = float(ev["end_ts"] or ev["start_ts"] + 3600) - float(ev["start_ts"])
            con.execute("UPDATE agenda SET start_ts=?, end_ts=?, has_time=?, created_ts=? WHERE id=?",
                        (start_ts, start_ts + (length if has_time else 86400), int(has_time), now, int(event_id)))
            con.execute("UPDATE agenda SET cancelled_ts=? WHERE event_id=? AND fired_ts IS NULL AND cancelled_ts IS NULL",
                        (now, int(event_id)))
            reminders = []
            for mins in (sorted(set(int(x) for x in remind_before_min), reverse=True) if has_time else ()):
                at = start_ts - mins * 60
                if at > now + 5:
                    con.execute(
                        "INSERT INTO agenda(kind, title, start_ts, has_time, event_id, user_id, source, created_ts) VALUES "
                        "('reminder',?,?,1,?,?,?,?)",
                        (ev["title"] if mins == 0 else f"{ev['title']} in {mins} minutes", at, int(event_id),
                         ev["user_id"], "event", now))
                    reminders.append(at)
            con.commit()
        finally:
            con.close()
    _export_ics()
    _ledger("MOVE_EVENT", ev["title"], describe(start_ts, has_time=has_time), ev["user_id"])
    _arm()
    return {**get(int(event_id)), "reminders": reminders}


def find(query: str, *, user_id: str = "", include_past: bool = False) -> List[Dict[str, Any]]:
    """Live agenda items whose title shares a word with `query`."""
    words = {w for w in re.findall(r"[a-z0-9]{3,}", str(query or "").lower())
             if w not in ("the", "event", "events", "reminder", "reminders", "calendar", "cancel", "delete", "remove", "for", "from")}
    if not words:
        return []
    rows = between(0 if include_past else time.time() - 3600, time.time() + 366 * 86400, user_id=user_id)
    return [r for r in rows if words & set(re.findall(r"[a-z0-9]{3,}", r["title"].lower()))]


def _narrow(matches: Sequence[Dict[str, Any]], text: str, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Fewer of `matches`, where the words say which: a title in quotes, the entry sharing the
    most words with the request, the one on the day it names."""
    rows = list(matches)
    if len(rows) < 2:
        return rows
    quoted = re.search(r'"([^"]{2,})"', str(text or ""))
    if quoted:
        exact = [r for r in rows if r["title"].strip().lower() == quoted.group(1).strip().lower()]
        rows = exact or rows
    if len(rows) > 1:
        said = set(re.findall(r"[a-z0-9]{3,}", str(text or "").lower()))
        score = [len(said & set(re.findall(r"[a-z0-9]{3,}", r["title"].lower()))) for r in rows]
        rows = [r for r, n in zip(rows, score) if n == max(score)]
    if len(rows) > 1:
        when = parse_when(re.sub(r'"[^"]*"', " ", str(text or "")), now)
        if when is not None and when.has_date:
            day = [r for r in rows if datetime.fromtimestamp(r["start_ts"]).date() == when.start.date()]
            rows = day or rows
    return rows


def _choices(matches: Sequence[Dict[str, Any]], text: str, *, dated: bool) -> List[Dict[str, Any]]:
    """The entries a request could mean, each as the request that means only it, so "the
    second one" or "the friday one" picks."""
    titles = [m["title"].strip().lower() for m in matches]
    out = []
    for n, m in enumerate(matches, 1):
        at = datetime.fromtimestamp(m["start_ts"])
        command = f'{text} "{m["title"]}"'
        if dated and titles.count(m["title"].strip().lower()) > 1:
            command += f" on {at.strftime('%Y-%m-%d')}"
        out.append({"n": n, "command": command, "kind": "action",
                    "label": f"{m['title']} {at.strftime('%A %B %d %H:%M')}"})
    return out


# ── telling the user ─────────────────────────────────────────────────────────

def format_period(rows: Sequence[Dict[str, Any]], label: str, now: Optional[datetime] = None) -> str:
    """The answer to "what's on today": every event and reminder in the period, or that there is none."""
    now = now or datetime.now()
    if not rows:
        return f"Nothing on your calendar {label}."
    lines = [f"On your calendar {label}:"]
    for r in rows:
        when = describe(r["start_ts"], now, has_time=bool(r["has_time"]))
        lines.append(f"- {when}: {r['title']}" + (" (reminder)" if r["kind"] == "reminder" else ""))
    return "\n".join(lines)


def period_from(text: Any, now: Optional[datetime] = None) -> Tuple[float, float, str]:
    """(since, until, label) for "today", "tomorrow", "this week", a named day, else the next 7 days."""
    now = now or datetime.now()
    low = str(text or "").lower()
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if re.search(r"\b(?:this|the) week\b", low):
        end = day0 + timedelta(days=7 - now.weekday())
        return now.timestamp(), end.timestamp(), "for the rest of this week"
    if re.search(r"\bnext week\b", low):
        start = day0 + timedelta(days=7 - now.weekday())
        return start.timestamp(), (start + timedelta(days=7)).timestamp(), "next week"
    if re.search(r"\b(?:today|tonight|this (?:morning|afternoon|evening))\b", low):
        return day0.timestamp(), (day0 + timedelta(days=1)).timestamp(), "today"
    month = re.search(r"\b(this|next|the) month\b", low)
    if month:
        first = day0.replace(day=1)
        following = (first + timedelta(days=32)).replace(day=1)
        if month.group(1) == "next":
            return following.timestamp(), (following + timedelta(days=32)).replace(day=1).timestamp(), "next month"
        return now.timestamp(), following.timestamp(), "for the rest of this month"
    when = parse_when(low, now)
    if when is not None and when.has_date:
        d = when.start.replace(hour=0, minute=0, second=0, microsecond=0)
        days = (d.date() - now.date()).days
        label = "tomorrow" if days == 1 else f"on {d.strftime('%a')} {d.day} {d.strftime('%b')}"
        return d.timestamp(), (d + timedelta(days=1)).timestamp(), label
    return now.timestamp() - 3600, (day0 + timedelta(days=8)).timestamp(), "in the next 7 days"


_AGENDA_WORDS = re.compile(r"\b(?:calendar|calender|diary|agenda|schedule|reminders?|appointments?|alarms?)\b", re.I)


def about_agenda(text: Any, *, user_id: str = "") -> bool:
    """The message is about the user's calendar: it says so, or names something that is on it."""
    raw = str(text or "")
    if _AGENDA_WORDS.search(raw):
        return True
    try:
        return bool(find(raw, user_id=user_id))
    except Exception:
        return False


def prompt_line(user_id: str = "", now: Optional[datetime] = None, *, hours: int = 36, limit: int = 6) -> str:
    """What is coming up, for the model to know on every turn: each event and reminder in the
    next day and a half with how far off it is. "" when there is nothing."""
    now = now or datetime.now()
    try:
        rows = between(now.timestamp(), now.timestamp() + hours * 3600, user_id=user_id)[:limit]
    except Exception:
        log.debug("agenda: prompt line unavailable", exc_info=True)
        return ""
    if not rows:
        return ""
    parts = []
    for r in rows:
        mins = max(0, int(round((r["start_ts"] - now.timestamp()) / 60.0)))
        gap = f"{mins // 60} h {mins % 60} min" if mins >= 60 else f"{mins} min"
        parts.append(f"{describe(r['start_ts'], now, has_time=bool(r['has_time']))}: {r['title']}"
                     + (" (reminder)" if r["kind"] == "reminder" else "")
                     + (f", in {gap}" if r["has_time"] else ""))
    return ("ON THE USER'S CALENDAR (ELI's own, kept locally; these are facts, use them): " + "; ".join(parts) + ".")


# ── firing ───────────────────────────────────────────────────────────────────

def set_delivery(fn: Optional[Callable[[Dict[str, Any], bool], None]]) -> None:
    """Replace how a due reminder reaches the user (tests; a headless server)."""
    global _deliver
    _deliver = fn


def _default_delivery(item: Dict[str, Any], missed: bool) -> None:
    at = datetime.fromtimestamp(item["start_ts"]).strftime("%H:%M")
    body = f"{item['title']}" + (f" (was due at {at}; ELI was not running)" if missed else f" ({at})")
    if os.environ.get("ELI_AGENDA_NOTIFY", "1").strip().lower() in ("0", "false", "off", "no"):
        return
    try:
        from eli.utils.platform_compat import notify, play_alarm_sound
        notify("ELI reminder", body)
        if not missed:
            play_alarm_sound()
    except Exception:
        log.debug("agenda: desktop notification failed", exc_info=True)
    try:
        from eli.planning.proactive_daemon import get_daemon
        q = getattr(get_daemon(), "suggestion_queue", None)
        if q is not None:
            q.put(("reminder", {"suggestion": f"Reminder: {body}", "title": item["title"], "at": item["start_ts"]}))
    except Exception:
        log.debug("agenda: in-app delivery failed", exc_info=True)


def fire_due(now_ts: Optional[float] = None) -> List[Dict[str, Any]]:
    """Deliver every reminder that has come due and has not been delivered. Returns them."""
    now_ts = time.time() if now_ts is None else float(now_ts)
    with _lock:
        con = _connect()
        try:
            due = [dict(r) for r in con.execute(
                "SELECT * FROM agenda WHERE kind='reminder' AND cancelled_ts IS NULL AND fired_ts IS NULL AND start_ts <= ? "
                "ORDER BY start_ts", (now_ts,))]
            if due:
                con.execute(f"UPDATE agenda SET fired_ts=? WHERE id IN ({','.join('?' * len(due))})",
                            (now_ts, *[d["id"] for d in due]))
                con.commit()
        finally:
            con.close()
    delivered = []
    for item in due:
        late = now_ts - item["start_ts"]
        if late > _MISSED_WINDOW_S:
            continue  # too old to be worth interrupting anyone for
        try:
            (_deliver or _default_delivery)(item, late > 120)
            delivered.append(item)
            log.debug("[AGENDA] reminder delivered: %s", item["title"])
        except Exception:
            log.debug("agenda: delivery failed", exc_info=True)
    return delivered


def _next_due() -> Optional[float]:
    con = _connect()
    try:
        r = con.execute("SELECT MIN(start_ts) FROM agenda WHERE kind='reminder' AND cancelled_ts IS NULL "
                        "AND fired_ts IS NULL").fetchone()
        return float(r[0]) if r and r[0] is not None else None
    finally:
        con.close()


def _run() -> None:
    while True:
        try:
            fire_due()
            nxt = _next_due()
        except Exception:
            log.debug("agenda: notifier pass failed", exc_info=True)
            nxt = None
        # woken early whenever the agenda changes; otherwise check at least once a minute so a
        # suspended laptop catches up soon after it wakes
        wait = 60.0 if nxt is None else max(0.5, min(60.0, nxt - time.time()))
        _wake.wait(wait)
        _wake.clear()


def _arm() -> None:
    """Make sure the notifier is running and has seen the latest change."""
    global _thread
    with _lock:
        if _thread is None or not _thread.is_alive():
            _thread = threading.Thread(target=_run, name="eli-agenda", daemon=True)
            _thread.start()
    _wake.set()


def restore() -> int:
    """At start-up: deliver what came due while ELI was shut and re-arm what is still to come."""
    try:
        pending = 0 if _next_due() is None else 1
        _arm()
        return pending
    except Exception:
        log.debug("agenda: restore failed", exc_info=True)
        return 0


# ── the .ics mirror ──────────────────────────────────────────────────────────

def _ics_escape(text: str) -> str:
    return str(text).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _export_ics() -> None:
    """Write every live event to a standard calendar file, so any calendar app can show them."""
    try:
        from eli.core.paths import calendar_ics_path
        path = calendar_ics_path()
        con = _connect()
        try:
            rows = con.execute("SELECT * FROM agenda WHERE kind='event' AND cancelled_ts IS NULL ORDER BY start_ts").fetchall()
        finally:
            con.close()
        out = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//ELI//Agenda//EN", "CALSCALE:GREGORIAN"]
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        for r in rows:
            out += ["BEGIN:VEVENT", f"UID:eli-agenda-{r['id']}@local", f"DTSTAMP:{stamp}"]
            if r["has_time"]:
                out += [f"DTSTART:{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime(r['start_ts']))}",
                        f"DTEND:{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime(r['end_ts'] or r['start_ts'] + 3600))}"]
            else:
                d = datetime.fromtimestamp(r["start_ts"])
                out += [f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}",
                        f"DTEND;VALUE=DATE:{(d + timedelta(days=1)).strftime('%Y%m%d')}"]
            out += [f"SUMMARY:{_ics_escape(r['title'])}", "END:VEVENT"]
        out.append("END:VCALENDAR")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".ics.tmp")
        tmp.write_text("\r\n".join(out) + "\r\n", encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        log.debug("agenda: calendar file not written", exc_info=True)


def _ledger(action: str, title: str, what: str, user_id: str) -> None:
    try:
        from eli.runtime.evidence_ledger import record_event
        record_event("agenda", source="agenda", action=action, subject=title, content=what,
                     user_id=str(user_id or ""), reusable=False)
    except Exception:
        log.debug("agenda: ledger write skipped", exc_info=True)


# ── from a sentence to an entry ──────────────────────────────────────────────

# What kind of thing an event is, as opposed to which one: two "appointments" are not one event.
_KIND_WORDS = frozenset((
    "event", "appointment", "meeting", "presentation", "interview", "exam", "class", "lecture", "call", "session",
    "dinner", "lunch", "breakfast", "party", "flight", "seminar", "workshop", "review", "demo", "reminder", "the",
))


def from_text(text: Any, *, earlier: Sequence[str] = (), now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """{"title", "start_ts", "has_time"} for what a request describes.

    "add it to my calendar" names nothing itself, so `earlier` (the user's recent messages,
    newest first) is searched for the event being talked about."""
    now = now or datetime.now()
    when = parse_when(text, now)
    title = title_from(text, when) if when else ""
    source = str(text or "")
    if when is None or not title:
        # What the request itself names. A time is taken from an earlier message only for the
        # same event, or when the request names none ("add it"): "add dentist appointment to my
        # calendar" said after mentioning a 7.30pm presentation is not a dentist at 7.30pm.
        own = title or title_from(text, None)
        own = "" if generic_label(own) else own
        for prior in earlier:
            w2 = parse_when(prior, now)
            t2 = title_from(prior, w2) if w2 else ""
            if when is None and w2 is not None:
                if own and not _same_event(own, t2):
                    continue
                when, source = w2, prior
                title = title or own or t2
            elif when is not None and not title and (t2 or _EVENT_PHRASE.search(str(prior))):
                title = t2 or title_from(prior, None)
            if when is not None and title:
                break
    if when is None:
        return None
    return {"title": title or "Event", "start_ts": when.start.timestamp(), "has_time": when.has_time, "said": source}


def _same_event(a: str, b: str) -> bool:
    """Two titles name one event: they share a word that is not just the kind of event."""
    wa, wb = (set(re.findall(r"[a-z0-9]{3,}", str(x or "").lower())) for x in (a, b))
    shared = wa & wb
    if not shared:
        return False
    return bool(shared - _KIND_WORDS) or wa <= wb or wb <= wa


# ── noticing an event the user mentioned ─────────────────────────────────────

_ASKS = re.compile(r"\?\s*$|^\s*(?:what|when|where|who|why|how|which|is|are|was|were|do|does|did|can|could|should|would|will)\b", re.I)


def _known_event(title: str, start_ts: float, user_id: str) -> bool:
    """An event of this name around that day has been on the calendar, cancelled ones included:
    one the user moved to 8pm or removed is not offered again at its old time."""
    where, args = _scope(user_id)
    con = _connect()
    try:
        return con.execute(
            f"SELECT 1 FROM agenda WHERE kind='event' AND lower(title)=? AND abs(start_ts - ?) < 86400 AND {where} LIMIT 1",
            (str(title).lower(), float(start_ts), *args)).fetchone() is not None
    finally:
        con.close()


def mentioned_event(texts: Sequence[str], *, user_id: str = "", now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """An upcoming event one of these messages (newest first) describes that is not on the
    calendar yet: "I thought I had a presentation at 10am for RAIMS, but it's not until 7.30pm".
    Returned with the sentence that offers to add it and the command that adds it."""
    now = now or datetime.now()
    for text in texts:
        raw = str(text or "")
        if not raw.strip() or len(raw) > 400 or _ASKS.search(raw) or not _EVENT_PHRASE.search(raw):
            continue
        when = parse_when(raw, now)
        if when is None or not when.has_time or when.start <= now:
            continue
        # "tonight" and "this evening" are given an hour so they can be sorted; that hour is
        # not something the user said, so it is not offered back as the time of their event.
        if not (_clock_candidates(raw) or _RELATIVE.search(raw)):
            continue
        title = title_from(raw, when)
        if not title or generic_label(title):
            continue
        start = when.start.timestamp()
        if _known_event(title, start, user_id):
            return None  # already there, or was there and the user moved or removed it
        day = when.start.strftime("%Y-%m-%d")
        return {"title": title, "start_ts": start,
                "command": f'add "{title}" on {day} at {when.start.strftime("%H:%M")} to my calendar',
                "sentence": f"Want me to put {title} in your calendar for {describe(start, now)}, and remind you before it?"}
    return None


# ── the actions ──────────────────────────────────────────────────────────────

_REPEATS = re.compile(r"\b(?:every|each|daily|weekly|monthly|fortnightly)\b", re.I)


def _reply(action: str, ok: bool, text: str, **extra: Any) -> Dict[str, Any]:
    out = {"ok": ok, "action": action, "content": text, "response": text, **extra}
    if not ok:
        # every not-ok reply here is a question or an instruction for the user ("When is it?",
        # "Which should go?", "Nothing matches that"), not a fault to recover from
        out["asks_user"] = True
    return {k: v for k, v in out.items() if v is not None}


def do_add_event(args: Dict[str, Any], *, user_id: str = "", earlier: Sequence[str] = (),
                 now: Optional[datetime] = None) -> Dict[str, Any]:
    """ADD_EVENT: put what the request describes on the calendar and say exactly what was added."""
    now = now or datetime.now()
    args = args or {}
    text = str(args.get("text") or args.get("event") or args.get("raw") or "").strip()
    given = " ".join(str(args.get(k) or "") for k in ("title", "summary", "name")).strip()
    if args.get("date") or args.get("time") or args.get("start"):
        text = f"{given} on {args.get('date') or args.get('start') or 'today'} at {args.get('time') or ''}".strip()
    if args.get("move"):
        moved = _do_move(text, user_id=user_id, now=now)
        if moved is not None:
            return moved
    parsed = from_text(text, earlier=earlier, now=now)
    if parsed is None:
        return _reply("ADD_EVENT", False, "I can add that. When is it? Give me the day and the time.", error="need_time",
                      awaiting={"command": text, "action": "ADD_EVENT", "needs": "when"} if text else None)
    title = _tidy(given) or parsed["title"]
    start = parsed["start_ts"]
    if start < now.timestamp() - 60:
        return _reply("ADD_EVENT", False,
                      f"{describe(start, now, has_time=parsed['has_time'])} has already passed. Which day did you mean?",
                      error="in_the_past")
    ev = add_event(title, start, has_time=parsed["has_time"], duration_min=int(args.get("duration") or _DEFAULT_EVENT_MIN),
                   user_id=user_id, source="ADD_EVENT")
    when = describe(start, now, has_time=parsed["has_time"])
    if ev.get("already"):
        return _reply("ADD_EVENT", True, f"That is already on your calendar: {ev['title']}, {when}.", event=ev)
    msg = f"Added to your calendar: {ev['title']}, {when}."
    times = [datetime.fromtimestamp(t).strftime("%H:%M") for t in ev.get("reminders") or []]
    if times:
        msg += f" I'll remind you at {' and '.join(times)}."
    if _REPEATS.search(text):
        msg += " That is the next one only; repeating events are not supported yet."
    return _reply("ADD_EVENT", True, msg, event=ev)


def _do_move(text: str, *, user_id: str, now: datetime) -> Optional[Dict[str, Any]]:
    """"I meant 8pm", "move the dentist to friday at 3": change the event that is there. None
    when there is nothing to move, so the request can be read as a new event instead."""
    when = parse_when(text, now)
    if when is None:
        return None
    named = [e for e in find(title_from(text, when) or text, user_id=user_id) if e["kind"] == "event"]
    quoted = re.search(r'"([^"]{2,})"', text)
    if quoted:
        named = [e for e in named if e["title"].strip().lower() == quoted.group(1).strip().lower()] or named
    target = named[0] if len(named) == 1 else (latest_event(user_id=user_id) if not named else None)
    if target is None:
        if len(named) > 1:
            return _reply("ADD_EVENT", False, "Which one do you mean?\n" + "\n".join(
                f"{n}. {describe(e['start_ts'], now, has_time=bool(e['has_time']))}: {e['title']}"
                for n, e in enumerate(named, 1)),
                error="ambiguous", choices=_choices(named, text, dated=False))
        return None
    old = datetime.fromtimestamp(target["start_ts"])
    start = when.start
    if when.has_time and not when.has_date:
        start = old.replace(hour=start.hour, minute=start.minute, second=0, microsecond=0)   # same day, new time
    elif when.has_date and not when.has_time and target["has_time"]:
        start = start.replace(hour=old.hour, minute=old.minute)                               # new day, same time
    has_time = bool(when.has_time or target["has_time"])
    if start.timestamp() < now.timestamp() - 60:
        return _reply("ADD_EVENT", False, f"{describe(start.timestamp(), now, has_time=has_time)} has already passed. "
                                          "Which day did you mean?", error="in_the_past")
    ev = move_event(target["id"], start.timestamp(), has_time=has_time)
    msg = f"Moved {ev['title']} to {describe(start.timestamp(), now, has_time=has_time)}."
    times = [datetime.fromtimestamp(t).strftime("%H:%M") for t in ev.get("reminders") or []]
    if times:
        msg += f" I'll remind you at {' and '.join(times)}."
    return _reply("ADD_EVENT", True, msg, event=ev)


_CLEAR_ALL = re.compile(r"\b(?:clear|delete|remove|cancel|wipe)\s+(?:all\s+)?(?:of\s+)?(?:my|the)\s+(?P<what>reminders|alarms|events|calendar|appointments)\b", re.I)


def do_remove(args: Dict[str, Any], *, user_id: str = "", now: Optional[datetime] = None) -> Dict[str, Any]:
    """REMOVE_EVENT: take an event or reminder off the calendar, by what it is called."""
    now = now or datetime.now()
    text = str((args or {}).get("text") or "").strip()
    everything = _CLEAR_ALL.search(text)
    if everything:
        what = everything.group("what").lower()
        kinds = ("reminder",) if what in ("reminders", "alarms") else ("event",)
        rows = between(now.timestamp(), now.timestamp() + 5 * 366 * 86400, user_id=user_id, kinds=kinds)
        gone = cancel([r["id"] for r in rows], user_id=user_id)
        if not gone:
            return _reply("REMOVE_EVENT", True, f"There are no {what if what != 'calendar' else 'events'} to clear.")
        return _reply("REMOVE_EVENT", True, f"Cleared {len(gone)}:\n" + "\n".join(
            f"- {describe(g['start_ts'], now, has_time=bool(g['has_time']))}: {g['title']}" for g in gone), removed=gone)
    matches = find(text, user_id=user_id)
    if not matches and re.search(r"\b(?:that|it|this|the last one)\b", text, re.I):
        last = latest_event(user_id=user_id)
        matches = [last] if last else []
    if not matches:
        return _reply("REMOVE_EVENT", False, "Nothing on your calendar matches that. Say \"what's on my calendar\" "
                                             "to see what is there.", error="not_found")
    matches = _narrow(matches, text, now)
    if len(matches) > 1:
        return _reply("REMOVE_EVENT", False, "More than one matches. Which should go?\n" + "\n".join(
            f"{n}. {describe(m['start_ts'], now, has_time=bool(m['has_time']))}: {m['title']}"
            for n, m in enumerate(matches, 1)),
            error="ambiguous", choices=_choices(matches, text, dated=True))
    gone = cancel([matches[0]["id"]], user_id=user_id)
    g = gone[0] if gone else matches[0]
    return _reply("REMOVE_EVENT", bool(gone), f"Removed from your calendar: {g['title']}, "
                                              f"{describe(g['start_ts'], now, has_time=bool(g['has_time']))}.", removed=gone)


def do_list_events(args: Dict[str, Any], *, user_id: str = "", earlier: Sequence[str] = (),
                   now: Optional[datetime] = None) -> Dict[str, Any]:
    """LIST_EVENTS: what is on the calendar for the period asked about. If the user has just
    mentioned an event that is not there, say so and offer to add it."""
    now = now or datetime.now()
    since, until, label = period_from((args or {}).get("text") or "", now)
    rows = between(since, until, user_id=user_id)
    text = format_period(rows, label, now)
    missing = mentioned_event(earlier, user_id=user_id, now=now)
    if missing:
        text += f"\n\nYou mentioned {missing['title']} ({describe(missing['start_ts'], now)}); it is not on your calendar. " \
                + missing["sentence"]
        return _reply("LIST_EVENTS", True, text, events=rows, offer=missing["command"])
    return _reply("LIST_EVENTS", True, text, events=rows)


def do_remind(args: Dict[str, Any], *, user_id: str = "", earlier: Sequence[str] = (),
              now: Optional[datetime] = None) -> Dict[str, Any]:
    """SET_ALARM for a reminder in words: "remind me at 4pm to prepare for the presentation"."""
    now = now or datetime.now()
    text = str((args or {}).get("text") or "").strip()
    when = parse_when(text, now)
    if when is None:
        return _reply("SET_ALARM", False, "When should I remind you? Give me a time, or say something like "
                                          "\"in 20 minutes\".", error="need_time",
                      awaiting={"command": text, "action": "SET_ALARM", "needs": "when"} if text else None)
    if not when.has_time:
        when = When(when.start.replace(hour=9, minute=0), True, True, when.spans)
    label = str((args or {}).get("label") or "") or title_from(text, when)
    if generic_label(label):
        # "a reminder at 4" with an event later that day is a reminder about that event
        day_end = when.start.replace(hour=23, minute=59).timestamp()
        ahead = [r for r in between(when.start.timestamp(), day_end, user_id=user_id, kinds=("event",))]
        if len(ahead) == 1:
            label = f"{ahead[0]['title']} at {datetime.fromtimestamp(ahead[0]['start_ts']).strftime('%H:%M')}"
        else:
            # or about the event they have just been talking about
            for prior in earlier:
                w2 = parse_when(prior, now)
                t2 = title_from(prior, w2) if (w2 and _EVENT_PHRASE.search(str(prior))) else ""
                if t2 and not generic_label(t2):
                    label = f"{t2} at {w2.start.strftime('%H:%M')}" if w2.has_time else t2
                    break
    rem = add_reminder(label or "Reminder", when.start.timestamp(), user_id=user_id, source="SET_ALARM")
    return _reply("SET_ALARM", True, f"Reminder set for {describe(when.start.timestamp(), now)}: {rem['title']}.", reminder=rem)
