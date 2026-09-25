"""Deterministic query planning: the time window a question asks about."""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from typing import Optional, Tuple

Window = Tuple[float, float]

_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august",
           "september", "october", "november", "december")
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_NUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
        "eight": 8, "nine": 9, "ten": 10, "couple": 2, "few": 3, "several": 4}
_UNIT_DAYS = {"day": 1, "week": 7, "fortnight": 14, "month": 30, "year": 365}
_N = r"(\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|couple of|few|several)"
_U = r"(day|week|fortnight|month|year)s?"


def _start_of_day(d: datetime) -> datetime:
    return d.replace(hour=0, minute=0, second=0, microsecond=0)


def _ts(d: datetime) -> float:
    return d.timestamp()


def _n(tok: str) -> int:
    tok = tok.replace(" of", "").strip()
    return int(tok) if tok.isdigit() else _NUM.get(tok, 1)


def parse_window(text: str, now: Optional[float] = None) -> Optional[Window]:
    """(start, end) epoch seconds for the period a question refers to, or None if it names none."""
    low = str(text or "").lower()
    n = datetime.fromtimestamp(time.time() if now is None else float(now))
    sod = _start_of_day(n)
    end_now = _ts(n)

    def span(days_back: float, until: Optional[datetime] = None) -> Window:
        return _ts(sod - timedelta(days=days_back)), _ts(until) if until else end_now

    if re.search(r"\blast night\b", low):
        return _ts(sod - timedelta(hours=6)), _ts(sod + timedelta(hours=5))
    if re.search(r"\b(?:this morning)\b", low):
        return _ts(sod), _ts(sod + timedelta(hours=12))
    if re.search(r"\b(?:today|tonight|this afternoon|this evening)\b", low):
        return _ts(sod), end_now
    if re.search(r"\bday before yesterday\b", low):
        return _ts(sod - timedelta(days=2)), _ts(sod - timedelta(days=1))
    if re.search(r"\byesterday\b", low):
        return _ts(sod - timedelta(days=1)), _ts(sod)
    if re.search(r"\bthis week\b", low):
        return _ts(sod - timedelta(days=sod.weekday())), end_now
    if re.search(r"\blast week\b", low):
        mon = sod - timedelta(days=sod.weekday())
        return _ts(mon - timedelta(days=7)), _ts(mon)
    if re.search(r"\bthis month\b", low):
        return _ts(sod.replace(day=1)), end_now
    if re.search(r"\blast month\b", low):
        first = sod.replace(day=1)
        return _ts((first - timedelta(days=1)).replace(day=1)), _ts(first)
    if re.search(r"\b(?:recently|lately|the other day)\b", low):
        return span(14)

    m = re.search(rf"\b(?:past|last|previous)\s+(?:{_N}\s+)?{_U}(?:\s+or\s+(so|{_N}))?", low)
    if m:
        unit = _UNIT_DAYS[m.group(2)]
        count = _n(m.group(1)) if m.group(1) else 1
        if m.group(3) and m.group(3) != "so":
            count = _n(m.group(3))
        return span(max(count * unit, 1))
    m = re.search(rf"\b{_N}\s+{_U}\s+ago\b", low)
    if m:
        days = _n(m.group(1)) * _UNIT_DAYS[m.group(2)]
        pad = max(1, days // 7)
        return span(days + pad, sod - timedelta(days=max(days - pad, 0)))
    m = re.search(r"\b(?:on|last)\s+(" + "|".join(_WEEKDAYS) + r")\b", low)
    if m:
        back = (sod.weekday() - _WEEKDAYS.index(m.group(1))) % 7 or 7
        day = sod - timedelta(days=back)
        return _ts(day), _ts(day + timedelta(days=1))
    m = re.search(r"\bin (" + "|".join(_MONTHS) + r")\b", low)
    if m:
        month = _MONTHS.index(m.group(1)) + 1
        year = n.year if month <= n.month else n.year - 1
        first = datetime(year, month, 1)
        nxt = datetime(year + (month == 12), month % 12 + 1, 1)
        return _ts(first), _ts(nxt)
    return None
