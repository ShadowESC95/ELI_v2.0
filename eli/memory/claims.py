"""Bitemporal claims: what ELI believes about the user, when it was true, and when ELI learned it.

Each claim has a valid interval (valid_from .. valid_to, open while it still holds) and a record
interval (recorded_at .. superseded_at, open while ELI still believes it). A single-valued fact such
as where someone lives supersedes the old value instead of sitting beside it, and the old claim is
kept, so "what did I do for work last spring" and "what did you think on 1 March" both have answers.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple

SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL DEFAULT 'user',
    relation TEXT NOT NULL,
    value TEXT NOT NULL,
    single_valued INTEGER NOT NULL DEFAULT 1,
    valid_from REAL,
    valid_to REAL,
    recorded_at REAL NOT NULL,
    superseded_at REAL,
    status TEXT NOT NULL DEFAULT 'current',
    supersedes INTEGER,
    source_memory_id INTEGER,
    source_text TEXT,
    origin TEXT,
    confidence REAL DEFAULT 0.7,
    confirmations INTEGER DEFAULT 1,
    last_confirmed REAL,
    source_roots TEXT,
    contested INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_claims_rel ON memory_claims(subject, relation, status);
"""

_KEY = re.compile(r"\s+")

# What the user is doing at the moment. These change often, so a newer value replaces the old one
# whoever reported it, instead of the two standing side by side as a dispute.
CHANGES_OFTEN = frozenset({"watching", "playing", "reading", "listening_to"})

# Bumped when extraction changes, so the history is read again (Memory.backfill_claims).
EXTRACT_VERSION = "2"


def ensure_schema(conn) -> None:
    conn.executescript(SCHEMA)
    have = {r[1] for r in conn.execute("PRAGMA table_info(memory_claims)")}
    for name, decl in (("source_roots", "TEXT"), ("contested", "INTEGER DEFAULT 0")):
        if name not in have:
            conn.execute(f"ALTER TABLE memory_claims ADD COLUMN {name} {decl}")


def _norm(value: str) -> str:
    return _KEY.sub(" ", str(value or "").strip().lower()).strip(" .,!?\"'")


def _same(a: str, b: str) -> bool:
    """The same value, or one is the other's initials: "GOT" is "Game of Thrones", "TWD" "The Walking Dead"."""
    na, nb = _norm(a), _norm(b)
    if na == nb or sorted(re.findall(r"[a-z0-9]+", na)) == sorted(re.findall(r"[a-z0-9]+", nb)):
        return True
    for short, long_ in ((na, nb), (nb, na)):
        words = re.findall(r"[a-z0-9]+", long_)
        if " " not in short and 2 <= len(short) <= 6 and len(words) >= 2 and short == "".join(w[0] for w in words):
            return True
    return False


def record(conn, relation: str, value: str, *, subject: str = "user", single_valued: bool = True,
           valid_from: Optional[float] = None, source_memory_id: Optional[int] = None,
           source_text: str = "", origin: str = "user_said", confidence: float = 0.7,
           now: Optional[float] = None, historical: bool = False, root_id: Optional[int] = None) -> Optional[int]:
    """Add a claim. Returns its id, or None when there was nothing to add.

    The same value again confirms the standing claim, but only a source with a different root counts as
    another confirmation (a summary of the same statement is not corroboration). A different value on a
    single-valued relation closes the standing claim at valid_from and replaces it, unless the newcomer
    is not the user's own word and the standing claim is: then both stand, marked as disputed.
    ``historical`` records something that was true and no longer is ("I used to work nights").
    """
    ensure_schema(conn)
    now = float(now if now is not None else time.time())
    vfrom = float(valid_from if valid_from is not None else now)
    value = str(value or "").strip()
    if not relation or not value:
        return None
    root = root_id if root_id is not None else source_memory_id
    cur = conn.execute(
        "SELECT id, value, origin, source_roots, valid_from FROM memory_claims "
        "WHERE subject = ? AND relation = ? AND status = 'current'",
        (subject, relation)).fetchall()
    if not historical:
        for cid, cval, _o, roots_json, _vf in cur:
            if _same(cval, value):
                roots = json.loads(roots_json or "[]")
                if root is not None and root not in roots:
                    roots.append(root)
                    conn.execute("UPDATE memory_claims SET confirmations = ?, source_roots = ?, last_confirmed = ?, "
                                 "confidence = MIN(0.99, confidence + 0.05) WHERE id = ?", (max(len(roots), 1), json.dumps(roots), now, cid))
                return int(cid)
    # Said before what ELI already holds (history read back in order, or a late report): it held until
    # the newer value took over, and it does not replace it.
    standing_from = max((float(r[4] or 0.0) for r in cur), default=0.0)
    if not historical and single_valued and cur and vfrom < standing_from:
        cursor = conn.execute(
            "INSERT INTO memory_claims (subject, relation, value, single_valued, valid_from, valid_to, recorded_at, "
            "superseded_at, status, source_memory_id, source_text, origin, confidence, last_confirmed, source_roots) "
            "VALUES (?,?,?,1,?,?,?,?,'superseded',?,?,?,?,?,?)",
            (subject, relation, value, vfrom, standing_from, now, now, source_memory_id, str(source_text or "")[:400],
             origin, float(confidence), now, json.dumps([root] if root is not None else [])))
        return int(cursor.lastrowid)
    if (not historical and single_valued and cur and relation not in CHANGES_OFTEN and origin != "user_said"
            and any(o == "user_said" for _c, _v, o, _r, _f in cur)):
        conn.execute("UPDATE memory_claims SET contested = 1 WHERE subject = ? AND relation = ? AND status = 'current'", (subject, relation))
        cursor = conn.execute(
            "INSERT INTO memory_claims (subject, relation, value, single_valued, valid_from, recorded_at, status, "
            "source_memory_id, source_text, origin, confidence, last_confirmed, source_roots, contested) "
            "VALUES (?,?,?,?,?,?,'disputed',?,?,?,?,?,?,1)",
            (subject, relation, value, 1 if single_valued else 0, vfrom, now, source_memory_id,
             str(source_text or "")[:400], origin, min(float(confidence), 0.4), now, json.dumps([root] if root is not None else [])))
        return int(cursor.lastrowid)
    superseded = None
    if not historical and single_valued and cur:
        superseded = int(cur[-1][0])
        conn.execute("UPDATE memory_claims SET status = 'superseded', valid_to = ?, superseded_at = ? "
                     "WHERE subject = ? AND relation = ? AND status = 'current'", (vfrom, now, subject, relation))
    cursor = conn.execute(
        "INSERT INTO memory_claims (subject, relation, value, single_valued, valid_from, valid_to, recorded_at, "
        "status, supersedes, source_memory_id, source_text, origin, confidence, last_confirmed, source_roots) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (subject, relation, value, 1 if single_valued else 0, vfrom, vfrom if historical else None, now,
         "former" if historical else "current", superseded, source_memory_id, str(source_text or "")[:400],
         origin, float(confidence), now, json.dumps([root] if root is not None else [])))
    return int(cursor.lastrowid)


def retire(conn, relation: str, *, subject: str = "user", at: Optional[float] = None,
           now: Optional[float] = None) -> int:
    """The standing claim on this relation stopped being true ("I no longer work nights")."""
    ensure_schema(conn)
    now = float(now if now is not None else time.time())
    at = float(at if at is not None else now)
    cur = conn.execute("UPDATE memory_claims SET status = 'superseded', valid_to = ?, superseded_at = ? "
                       "WHERE subject = ? AND relation = ? AND status = 'current'", (at, now, subject, relation))
    return int(cur.rowcount or 0)


def retract_from_memory(conn, memory_id: int) -> int:
    """A source memory was deleted: claims resting only on it are withdrawn, not left as orphans."""
    ensure_schema(conn)
    cur = conn.execute("UPDATE memory_claims SET status = 'retracted', superseded_at = ? "
                       "WHERE source_memory_id = ? AND status IN ('current', 'former')", (time.time(), int(memory_id)))
    return int(cur.rowcount or 0)


_COLS = ("id, subject, relation, value, valid_from, valid_to, recorded_at, superseded_at, status, "
         "supersedes, source_memory_id, confidence, confirmations, contested")


def _rows(conn, sql: str, args: Tuple[Any, ...]) -> List[Dict[str, Any]]:
    names = [c.strip() for c in _COLS.split(",")]
    return [dict(zip(names, r)) for r in conn.execute(sql, args).fetchall()]


def current(conn, subject: str = "user") -> List[Dict[str, Any]]:
    ensure_schema(conn)
    return _rows(conn, f"SELECT {_COLS} FROM memory_claims WHERE subject = ? AND status = 'current' "
                       "ORDER BY relation, id", (subject,))


def history(conn, relation: str, subject: str = "user") -> List[Dict[str, Any]]:
    ensure_schema(conn)
    return _rows(conn, f"SELECT {_COLS} FROM memory_claims WHERE subject = ? AND relation = ? "
                       "AND status != 'retracted' ORDER BY valid_from, id", (subject, relation))


def valid_during(conn, start: float, end: float, subject: str = "user") -> List[Dict[str, Any]]:
    """Claims that held at any point in [start, end)."""
    ensure_schema(conn)
    return _rows(conn, f"SELECT {_COLS} FROM memory_claims WHERE subject = ? AND status != 'retracted' "
                       "AND COALESCE(valid_from, 0) < ? AND (valid_to IS NULL OR valid_to > ?) "
                       "ORDER BY relation, valid_from", (subject, float(end), float(start)))


def known_at(conn, when: float, subject: str = "user") -> List[Dict[str, Any]]:
    """What ELI believed at `when`: claims already recorded then and not yet superseded then."""
    ensure_schema(conn)
    return _rows(conn, f"SELECT {_COLS} FROM memory_claims WHERE subject = ? AND status != 'retracted' "
                       "AND recorded_at <= ? AND (superseded_at IS NULL OR superseded_at > ?) "
                       "ORDER BY relation, id", (subject, float(when), float(when)))


def open_conflicts(conn, subject: str = "user") -> List[Dict[str, Any]]:
    """Relations where the user's standing claim is contested by something that is not their own word."""
    ensure_schema(conn)
    out = []
    for rel, in conn.execute("SELECT DISTINCT relation FROM memory_claims WHERE subject = ? AND status = 'disputed'", (subject,)).fetchall():
        rows = _rows(conn, f"SELECT {_COLS} FROM memory_claims WHERE subject = ? AND relation = ? AND status IN ('current', 'disputed') "
                           "ORDER BY status DESC, id", (subject, rel))
        out.append({"relation": rel, "standing": [r for r in rows if r["status"] == "current"], "disputed": [r for r in rows if r["status"] == "disputed"]})
    return out


def conflict_question(conflict: Dict[str, Any]) -> str:
    rel = str(conflict["relation"]).replace("_", " ")
    mine = ", ".join(str(r["value"]) for r in conflict["standing"])
    other = ", ".join(str(r["value"]) for r in conflict["disputed"])
    return f"I have your {rel} as {mine}, but something else says {other}. Which is right?"


def resolve_conflict(conn, relation: str, value: str, subject: str = "user", now: Optional[float] = None) -> int:
    """The user said which one is right: that value stands, the others are closed as superseded."""
    ensure_schema(conn)
    now = float(now if now is not None else time.time())
    keep = _norm(value)
    n = 0
    for cid, cval, status in conn.execute("SELECT id, value, status FROM memory_claims WHERE subject = ? AND relation = ? "
                                          "AND status IN ('current', 'disputed')", (subject, relation)).fetchall():
        if _norm(cval) == keep:
            conn.execute("UPDATE memory_claims SET status = 'current', contested = 0, confidence = MAX(confidence, 0.8) WHERE id = ?", (cid,))
        else:
            conn.execute("UPDATE memory_claims SET status = 'superseded', valid_to = ?, superseded_at = ?, contested = 0 WHERE id = ?", (now, now, cid))
            n += 1
    return n


def describe(claim: Dict[str, Any]) -> str:
    def day(ts):
        return time.strftime("%Y-%m-%d", time.localtime(float(ts))) if ts else "?"
    rel = str(claim["relation"]).replace("_", " ")
    span = f"since {day(claim['valid_from'])}" if not claim.get("valid_to") else \
        f"{day(claim['valid_from'])} to {day(claim['valid_to'])}"
    flag = "; DISPUTED, unresolved" if claim.get("status") == "disputed" else ("; contested" if claim.get("contested") else "")
    return f"{rel}: {claim['value']} ({span}; learned {day(claim['recorded_at'])}{flag})"


# ── extraction: a small, exact set of first-person statements ──────────────────────────────────────

_SCHEDULE = r"(nights?|days?|evenings?|weekends?|mornings?|part[- ]time|full[- ]time|from home|remotely|shifts?)"
_PLACE = r"([A-Z][\w'’-]*(?:\s+[A-Z][\w'’-]*){0,3})"
_PATTERNS: List[Tuple[str, str, bool, "re.Pattern"]] = [
    ("work_schedule", "single", True, re.compile(rf"\bI(?:'m| am)?\s+(?:now\s+|currently\s+)?work(?:ing)?\s+{_SCHEDULE}\b", re.I)),
    ("employer", "single", True, re.compile(rf"\bI\s+(?:now\s+)?work\s+(?:at|for)\s+{_PLACE}")),
    ("occupation", "single", True, re.compile(r"\bI\s+work\s+as\s+(?:an?\s+)?([a-z][a-z -]{2,40}?)(?=[.,;!?]|\s+(?:at|for|in|now|but|and)\b|$)", re.I)),
    ("lives_in", "single", True, re.compile(rf"\bI(?:'ve| have)?\s+(?:now\s+)?(?:live in|moved to|relocated to|am based in|'m based in)\s+{_PLACE}")),
]
_PET = re.compile(r"\bmy\s+(dog|cat|rabbit|parrot|horse)(?:'s name is|\s+is\s+(?:called|named)|,?\s+named|\s+is)\s+([A-Z][\w'-]{1,20})\b")
_PAST = re.compile(r"\b(?:I\s+used\s+to|I\s+no\s+longer|I\s+don'?t\s+.{0,20}\s+any\s*more|I\s+stopped|I\s+quit)\b", re.I)
_NO_LONGER = re.compile(r"\bI\s+(?:no longer|don'?t\s+(?:work|live)\b.{0,30}\bany\s*more|stopped working|quit working)\b", re.I)


_HEDGED = re.compile(r"\b(?:maybe|might|perhaps|thinking of|considering|planning to|hoping to|hope to|would like to|if i|when i|imagine|suppose|what if)\b", re.I)


# "I'm watching X", "still watching X", "I've been playing X", "X is on in the background". Present tense
# only: "going to play", "was watching" and "watching it was days ago" are not what is happening now.
_VERBS = (("watching", r"w[a-z]{0,2}tch(?:ing|in)"), ("playing", r"pla?y(?:ing|in)"),
          ("reading", r"read(?:ing|in)"), ("listening_to", r"listen(?:ing|in)\s+to"))
_ADVERBS = r"(?:(?:still|currently|now|just|actually|also|literally|only|really)\s+)*"
_VALUE = r"(?P<v>[^,.;:!?()\n]{1,60})"
_ACTIVITY = [(rel, re.compile(
    rf"(?:\bi(?:'m|\s+am|'ve\s+been|\s+have\s+been)\s+{_ADVERBS}|\bi\s+(?:just\s+)?(?:started|began)\s+|^{_ADVERBS}"
    rf"|,\s*(?:still|currently|now|just|actually)\s+{_ADVERBS}){verb}\s+{_VALUE}",
    re.I)) for rel, verb in _VERBS]
_ON_SCREEN = re.compile(r"(?:^|[,;:]\s*|\band\s+)(?P<v>[^,.;:!?()\n]{1,40}?)\s+is\s+on\s+"
                        r"(?:in\s+the\s+b\w+|the\s+(?:tv|telly|box|television)|tv|telly)\b", re.I)
_TAIL = re.compile(r"\s+(?:and|but|though|tho|with|while|whilst|because|cos|so|haha\w*|lol|lmao|now|tonight|today|"
                   r"again|atm|lately|right now|at the (?:moment|minute)|in the b\w+|for (?:a|the) \w+|for ages|"
                   r"all (?:week|day|night|morning|evening|weekend)|this (?:week|morning|evening|weekend)|since \w+|"
                   r"on (?:netflix|prime(?: video)?|amazon|disney\+?|hulu|youtube|now tv|sky|the (?:tv|telly)|tv|telly|my \w+))\b.*$",
                   re.I)
_NOT_A_TITLE = {"it", "that", "this", "them", "something", "nothing", "stuff", "tv", "telly", "the tv", "the telly",
                "a film", "a movie", "a show", "films", "movies", "shows", "youtube", "videos", "music", "a game",
                "games", "some tv", "a bit", "around", "with you", "you", "me", "along", "out", "the news",
                "please", "pls", "plz", "mate", "bud", "now", "again"}
# "check what series I am watching" asks; it does not tell.
_ASKED = re.compile(r"\b(?:what|which|whatever|whichever)\b[^.!?]{0,80}$", re.I)
_TAG_QUESTION = re.compile(r",\s*(?:and\s+)?(?:you|u|yourself|how about you|what about you|wbu|hbu)\s*\?+\s*$", re.I)
# A season and episode: "season 3, episode 6", "S1 E10", "S02E05". Also read by grounding_escalation.
EPISODE_MARKER = r"\b(?:season|s)\s*\d{1,2}\s*[,·x]?\s*(?:episode|ep|e)\.?\s*\d{1,3}\b"
_EPISODE = re.compile(rf"^\s*(?P<show>[^—–|]+?)\s*(?:[—–:|-]+\s*)?{EPISODE_MARKER}", re.I)


def _title(raw: str) -> str:
    value = " ".join(str(raw or "").split())
    while True:
        cut = _TAIL.sub("", value).strip()
        if cut == value:
            break
        value = cut
    value = value.strip(" -'\"")
    if (not re.search(r"[A-Za-z]", value) or value.lower() in _NOT_A_TITLE or len(value.split()) > 6
            or value.lower().startswith(("to ", "for ", "at ", "the fact"))):
        return ""
    return value


def activities(text: str) -> List[Dict[str, Any]]:
    """What the user says they are doing now, sentence by sentence (a question is not a statement)."""
    out: List[Dict[str, Any]] = []
    for sentence in re.split(r"(?<=[.!?])\s+", str(text or "").strip()):
        sentence = _TAG_QUESTION.sub("", sentence.strip())
        if not sentence or sentence.endswith("?") or _HEDGED.search(sentence):
            continue
        found = [(rel, m.group("v")) for rel, pat in _ACTIVITY for m in [pat.search(sentence)]
                 if m and not _ASKED.search(sentence[:m.start()])]
        m = _ON_SCREEN.search(sentence)
        if m:
            found.append(("watching", m.group("v")))
        for rel, raw in found:
            value = _title(raw)
            if value and not any(o["relation"] == rel for o in out):
                out.append({"relation": rel, "value": value, "single_valued": True, "historical": False, "retire": False})
    return out


def observed_show(title: str) -> str:
    """The show in a player's title when it is an episode ("Game of Thrones — S2 E5 – ..."), else ""."""
    m = _EPISODE.match(str(title or ""))
    return _title(m.group("show")) if m else ""


def extract(text: str) -> List[Dict[str, Any]]:
    """Claims stated in one user message. Each is {relation, value, single_valued, historical, retire}."""
    t = str(text or "").strip()
    now_doing = activities(t)
    if len(t.split()) < 3 or t.endswith("?") or _HEDGED.search(t):
        return now_doing
    stop = bool(_NO_LONGER.search(t))
    past = bool(_PAST.search(t)) and not stop
    # Take the negating or past marker out so the same patterns read what the statement is about.
    body = re.sub(r"\b(?:used to|no longer|stopped|quit|don'?t)\b\s*", "", t, flags=re.I) if (stop or past) else t
    out: List[Dict[str, Any]] = []
    for relation, _kind, single, pat in _PATTERNS:
        m = pat.search(body)
        if not m:
            continue
        value = m.group(1).strip()
        if relation == "work_schedule":
            value = re.sub(r"^night$", "nights", value.lower())
        out.append({"relation": relation, "value": value, "single_valued": single,
                    "historical": past, "retire": stop})
    m = _PET.search(t)
    if m:
        out.append({"relation": f"{m.group(1).lower()}_name", "value": m.group(2), "single_valued": True,
                    "historical": past, "retire": False})
    return out + [a for a in now_doing if not any(o["relation"] == a["relation"] for o in out)]


def record_from_text(conn, text: str, *, source_memory_id: Optional[int] = None, when: Optional[float] = None,
                     origin: str = "user_said", root_id: Optional[int] = None) -> List[int]:
    ids: List[int] = []
    for c in extract(text):
        if c["retire"]:
            retire(conn, c["relation"], at=when)
            continue
        cid = record(conn, c["relation"], c["value"], single_valued=c["single_valued"], valid_from=when,
                     source_memory_id=source_memory_id, source_text=text, origin=origin,
                     historical=c["historical"], root_id=root_id)
        if cid:
            ids.append(cid)
    return ids
