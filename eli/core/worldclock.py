"""Place-aware wall-clock answers.

Resolves a place named in a question ("what time is it in Shimla?") to an IANA
zone and formats the current day/date/time for it. Standard library only:
``zoneinfo`` carries the full tz database on disk, so nothing here touches the
network (ELI is offline by default — see ``eli.core.netguard``).

The two rules this module exists to enforce:

* A named place is never silently ignored. Answering "what time is it in
  Shimla?" with the local clock is worse than saying nothing.
* An unresolvable place is reported as unresolvable, never guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from zoneinfo import ZoneInfo, available_timezones

__all__ = [
    "DateTimeRequest",
    "describe",
    "parse_request",
    "resolve_zone",
]

# Places people name that are not IANA zone leaves. The tz database keys on a
# representative city per zone, so "Shimla" or "Wexford" resolve to nothing
# without this table. Curated entries win over the derived index below.
_PLACE_ALIASES: dict[str, str] = {
    # Ireland
    "ireland": "Europe/Dublin",
    "republic of ireland": "Europe/Dublin",
    "eire": "Europe/Dublin",
    "wexford": "Europe/Dublin",
    "cork": "Europe/Dublin",
    "galway": "Europe/Dublin",
    "limerick": "Europe/Dublin",
    "waterford": "Europe/Dublin",
    "kilkenny": "Europe/Dublin",
    "sligo": "Europe/Dublin",
    "drogheda": "Europe/Dublin",
    "dundalk": "Europe/Dublin",
    # UK
    "uk": "Europe/London",
    "united kingdom": "Europe/London",
    "britain": "Europe/London",
    "great britain": "Europe/London",
    "england": "Europe/London",
    "scotland": "Europe/London",
    "wales": "Europe/London",
    "northern ireland": "Europe/Belfast",
    "manchester": "Europe/London",
    "birmingham": "Europe/London",
    "liverpool": "Europe/London",
    "leeds": "Europe/London",
    "bristol": "Europe/London",
    "glasgow": "Europe/London",
    "edinburgh": "Europe/London",
    "cardiff": "Europe/London",
    "newcastle": "Europe/London",
    "sheffield": "Europe/London",
    "oxford": "Europe/London",
    "cambridge": "Europe/London",
    # India
    "india": "Asia/Kolkata",
    "shimla": "Asia/Kolkata",
    "simla": "Asia/Kolkata",
    "mumbai": "Asia/Kolkata",
    "bombay": "Asia/Kolkata",
    "delhi": "Asia/Kolkata",
    "new delhi": "Asia/Kolkata",
    "bangalore": "Asia/Kolkata",
    "bengaluru": "Asia/Kolkata",
    "chennai": "Asia/Kolkata",
    "madras": "Asia/Kolkata",
    "hyderabad": "Asia/Kolkata",
    "pune": "Asia/Kolkata",
    "ahmedabad": "Asia/Kolkata",
    "jaipur": "Asia/Kolkata",
    "goa": "Asia/Kolkata",
    "kerala": "Asia/Kolkata",
    "punjab": "Asia/Kolkata",
    # Europe
    "france": "Europe/Paris",
    "germany": "Europe/Berlin",
    "spain": "Europe/Madrid",
    "italy": "Europe/Rome",
    "portugal": "Europe/Lisbon",
    "netherlands": "Europe/Amsterdam",
    "holland": "Europe/Amsterdam",
    "belgium": "Europe/Brussels",
    "switzerland": "Europe/Zurich",
    "austria": "Europe/Vienna",
    "poland": "Europe/Warsaw",
    "sweden": "Europe/Stockholm",
    "norway": "Europe/Oslo",
    "denmark": "Europe/Copenhagen",
    "finland": "Europe/Helsinki",
    "greece": "Europe/Athens",
    "czechia": "Europe/Prague",
    "czech republic": "Europe/Prague",
    "hungary": "Europe/Budapest",
    "romania": "Europe/Bucharest",
    "ukraine": "Europe/Kyiv",
    "munich": "Europe/Berlin",
    "frankfurt": "Europe/Berlin",
    "hamburg": "Europe/Berlin",
    "cologne": "Europe/Berlin",
    "barcelona": "Europe/Madrid",
    "valencia": "Europe/Madrid",
    "seville": "Europe/Madrid",
    "milan": "Europe/Rome",
    "florence": "Europe/Rome",
    "naples": "Europe/Rome",
    "venice": "Europe/Rome",
    "turin": "Europe/Rome",
    "porto": "Europe/Lisbon",
    "nice": "Europe/Paris",
    "lyon": "Europe/Paris",
    "marseille": "Europe/Paris",
    # Americas
    "san francisco": "America/Los_Angeles",
    "silicon valley": "America/Los_Angeles",
    "seattle": "America/Los_Angeles",
    "portland": "America/Los_Angeles",
    "san diego": "America/Los_Angeles",
    "las vegas": "America/Los_Angeles",
    "boston": "America/New_York",
    "philadelphia": "America/New_York",
    "washington": "America/New_York",
    "washington dc": "America/New_York",
    "miami": "America/New_York",
    "atlanta": "America/New_York",
    "orlando": "America/New_York",
    "austin": "America/Chicago",
    "dallas": "America/Chicago",
    "houston": "America/Chicago",
    "san antonio": "America/Chicago",
    "new orleans": "America/Chicago",
    "nyc": "America/New_York",
    "new york city": "America/New_York",
    "la": "America/Los_Angeles",
    "montreal": "America/Toronto",
    "ottawa": "America/Toronto",
    "calgary": "America/Edmonton",
    "rio": "America/Sao_Paulo",
    "rio de janeiro": "America/Sao_Paulo",
    # Asia / Oceania / Africa
    "japan": "Asia/Tokyo",
    "china": "Asia/Shanghai",
    "beijing": "Asia/Shanghai",
    "shenzhen": "Asia/Shanghai",
    "guangzhou": "Asia/Shanghai",
    "south korea": "Asia/Seoul",
    "korea": "Asia/Seoul",
    "thailand": "Asia/Bangkok",
    "vietnam": "Asia/Ho_Chi_Minh",
    "philippines": "Asia/Manila",
    "malaysia": "Asia/Kuala_Lumpur",
    "pakistan": "Asia/Karachi",
    "bangladesh": "Asia/Dhaka",
    "nepal": "Asia/Kathmandu",
    "sri lanka": "Asia/Colombo",
    "israel": "Asia/Jerusalem",
    "turkey": "Europe/Istanbul",
    "uae": "Asia/Dubai",
    "abu dhabi": "Asia/Dubai",
    "saudi arabia": "Asia/Riyadh",
    "egypt": "Africa/Cairo",
    "south africa": "Africa/Johannesburg",
    "cape town": "Africa/Johannesburg",
    "nigeria": "Africa/Lagos",
    "kenya": "Africa/Nairobi",
    "morocco": "Africa/Casablanca",
    "new zealand": "Pacific/Auckland",
    "sydney": "Australia/Sydney",
    "melbourne": "Australia/Melbourne",
    "brisbane": "Australia/Brisbane",
    "perth": "Australia/Perth",
    "adelaide": "Australia/Adelaide",
}

# Regions spanning several zones: asking for one clock has no single right
# answer, so ask which city rather than picking a plausible-looking one.
_AMBIGUOUS_REGIONS: dict[str, str] = {
    "usa": "the United States",
    "us": "the United States",
    "america": "the United States",
    "united states": "the United States",
    "canada": "Canada",
    "australia": "Australia",
    "russia": "Russia",
    "brazil": "Brazil",
    "mexico": "Mexico",
    "indonesia": "Indonesia",
    "argentina": "Argentina",
    "kazakhstan": "Kazakhstan",
}

# "in the morning" / "in a minute" are not places.
_NOT_PLACES = frozenset({
    "the morning", "the afternoon", "the evening", "the night", "the moment",
    "the future", "the past", "the meantime", "the day", "the week", "fact",
    "a bit", "a minute", "a moment", "a second", "a while", "an hour",
    "your timezone", "my timezone", "this timezone", "here", "total", "general",
    "the world", "the system", "the log", "the logs", "particular", "short",
})

_PLACE_CANDIDATE_RX = re.compile(
    r"\b(?:in|at|for|over\s+in|out\s+in)\s+([A-Za-z][A-Za-z .'’\-]{1,38}(?:,\s*[A-Za-z][A-Za-z .'’\-]{1,38})?)",
    re.IGNORECASE,
)
_TIME_WORD_RX = re.compile(r"\b(time|clock|o'?clock|hour)\b", re.IGNORECASE)
_DATE_WORD_RX = re.compile(r"\b(date|day|weekday|month)\b", re.IGNORECASE)
_TODAY_RX = re.compile(r"\btoday\b", re.IGNORECASE)


def _norm(value: object) -> str:
    text = re.sub(r"[^\w\s,'\-]", " ", str(value or "").lower())
    text = re.sub(r"\s+", " ", text).strip(" ,")
    return re.sub(r"^the\s+", "", text)


@lru_cache(maxsize=1)
def _zone_index() -> dict[str, str]:
    """Lowercased place name → IANA zone, derived from the tz database."""
    index: dict[str, str] = {}
    for zone in available_timezones():
        leaf = zone.rsplit("/", 1)[-1].replace("_", " ").lower()
        index.setdefault(leaf, zone)
        index.setdefault(zone.replace("_", " ").lower(), zone)
    index.update(_PLACE_ALIASES)  # curated entries are authoritative
    return index


def resolve_zone(place: object) -> str | None:
    """Return the IANA zone for ``place``, or None if it isn't a known place."""
    key = _norm(place)
    if not key or key in _NOT_PLACES:
        return None
    index = _zone_index()
    if key in index:
        return index[key]
    # "shimla, india" → try each component before giving up.
    for part in (p.strip() for p in re.split(r"[,/]|\bin\b", key)):
        if part and part not in _NOT_PLACES and part in index:
            return index[part]
    return None


@dataclass(frozen=True)
class DateTimeRequest:
    """What a clock question is actually asking for."""

    wants_date: bool
    wants_time: bool
    place: str | None = None
    zone: str | None = None
    ambiguous_region: str | None = None

    @property
    def unresolved_place(self) -> bool:
        return bool(self.place) and not self.zone and not self.ambiguous_region


def parse_request(text: object, *, default_date: bool, default_time: bool) -> DateTimeRequest:
    """Read wants-date / wants-time / place out of a clock question.

    ``default_date`` / ``default_time`` apply when the text carries no explicit
    signal — the caller's action already implies an intent (TIME vs DATE).
    """
    raw = str(text or "")
    low = raw.lower()

    wants_time = bool(_TIME_WORD_RX.search(low))
    wants_date = bool(_DATE_WORD_RX.search(low)) or (
        bool(_TODAY_RX.search(low)) and not wants_time
    )
    if not wants_time and not wants_date:
        wants_date, wants_time = default_date, default_time

    place = zone = ambiguous = None
    for match in _PLACE_CANDIDATE_RX.finditer(raw):
        candidate = match.group(1).strip(" .,")
        key = _norm(candidate)
        if not key or key in _NOT_PLACES:
            continue
        if key in _AMBIGUOUS_REGIONS:
            place, ambiguous = candidate, _AMBIGUOUS_REGIONS[key]
            break
        found = resolve_zone(candidate)
        if found:
            place, zone = candidate, found
            break
        # Keep the first proper-noun-looking candidate so an unknown place is
        # reported honestly instead of silently answered with the local clock.
        if place is None and re.match(r"[A-Z]", candidate) and not raw.startswith(candidate):
            place = candidate

    return DateTimeRequest(
        wants_date=wants_date,
        wants_time=wants_time,
        place=place,
        zone=zone,
        ambiguous_region=ambiguous,
    )


def _format_now(request: DateTimeRequest) -> str:
    now = datetime.now(ZoneInfo(request.zone)) if request.zone else datetime.now().astimezone()

    parts: list[str] = []
    if request.wants_date:
        # Built by hand rather than with %-d/%#d, which are platform-specific.
        parts.append(f"{now.strftime('%A')}, {now.day} {now.strftime('%B %Y')}")
    if request.wants_time:
        parts.append(now.strftime("%H:%M"))
    stamp = ", ".join(parts) or now.strftime("%H:%M")

    if not request.zone:
        return stamp
    offset = now.strftime("%z")
    offset = f"UTC{offset[:3]}:{offset[3:]}" if offset else "UTC"
    where = request.place.strip() if request.place else request.zone
    if where.islower():  # user typed "shimla, india" — echo it back as a place
        where = where.title()
    return f"{stamp} in {where} ({request.zone}, {offset})"


def describe(text: object, *, default_date: bool = False, default_time: bool = True) -> str:
    """Answer a clock question, honouring any place named in it."""
    request = parse_request(text, default_date=default_date, default_time=default_time)

    if request.ambiguous_region:
        return (
            f"{request.ambiguous_region} spans several time zones, so there's no single "
            f"clock to read. Name a city and I'll give you the exact time."
        )
    if request.unresolved_place:
        return (
            f"I don't have a timezone for \"{request.place}\", so I can't give you its "
            f"time without guessing. Give me the country or a nearby major city."
        )
    return _format_now(request)
