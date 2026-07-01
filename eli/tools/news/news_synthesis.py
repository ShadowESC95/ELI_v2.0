"""
News synthesis cadence
======================
Every 3 hours we summarise the news fetched during that window and store the
summary as a "news reflection" in user memory. The morning report consolidates
the eight 3-hour reflections from the prior 24h into a single digest, then
hands that digest to ELI for expansion + follow-up questions.

Storage (all in canonical user.sqlite3):
  table news_reflections
    id INTEGER PRIMARY KEY
    started_at  REAL    -- unix ts of window start
    ended_at    REAL    -- unix ts of synthesis (window end)
    article_count INTEGER
    summary     TEXT
    sources     TEXT    -- JSON list of source names

Article ingestion is unchanged (handled by news_fetcher).
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


WINDOW_SECONDS = 3 * 3600  # 3 hours
DAY_SECONDS = 24 * 3600


_CREATE_REFLECTIONS = """
CREATE TABLE IF NOT EXISTS news_reflections (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    REAL    NOT NULL,
    ended_at      REAL    NOT NULL,
    article_count INTEGER NOT NULL DEFAULT 0,
    summary       TEXT    NOT NULL,
    sources       TEXT
)
"""


# Max age (days) for an interest-matched ("relevant to you") article. The top-stories
# half is already current; this keeps the interest half from surfacing a stale niche
# match (e.g. a 2-week-old arXiv paper the FTS-rank fallback loved) as if it were fresh.
# Slightly looser than same-day because academic/niche feeds publish less often.
_INTEREST_MAX_AGE_DAYS = 4


def _user_db() -> Path:
    from eli.core.paths import user_db_path
    return Path(user_db_path())


def _conn() -> sqlite3.Connection:
    db = _user_db()
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    conn.execute(_CREATE_REFLECTIONS)
    conn.commit()
    return conn


def _last_reflection_end() -> float:
    try:
        conn = _conn()
        row = conn.execute(
            "SELECT MAX(ended_at) FROM news_reflections"
        ).fetchone()
        conn.close()
        return float(row[0] or 0.0)
    except Exception:
        return 0.0


def _fetch_window_articles(start_ts: float, end_ts: float) -> List[Dict[str, Any]]:
    """Pull articles from news_articles between [start_ts, end_ts]."""
    try:
        from eli.tools.news.news_fetcher import _get_db
        db = _get_db()
        conn = sqlite3.connect(str(db))
        rows = conn.execute(
            "SELECT source, title, url, summary, category, fetched_at, score "
            "FROM news_articles WHERE fetched_at >= ? AND fetched_at <= ? "
            "ORDER BY fetched_at ASC",
            (start_ts, end_ts),
        ).fetchall()
        conn.close()
        out: List[Dict[str, Any]] = []
        for source, title, url, summary, category, fetched, score in rows:
            out.append({
                "source": source, "title": title, "url": url,
                "summary": summary, "category": category,
                "fetched_at": fetched, "score": score,
            })
        return out
    except Exception:
        return []


def _llm_summarise(articles: List[Dict[str, Any]], window_label: str) -> str:
    """Ask the local LLM to compress the window into a structured digest."""
    if not articles:
        return ""
    bullets: List[str] = []
    for a in articles[:60]:
        title = (a.get("title") or "").strip()
        src = (a.get("source") or "").strip()
        cat = (a.get("category") or "").strip()
        gist = (a.get("summary") or "").strip().replace("\n", " ")
        bullets.append(f"- [{src}/{cat}] {title} :: {gist[:240]}")
    body = "\n".join(bullets)

    prompt = (
        "Summarise the news window below as ELI. Group items by theme, surface "
        "patterns and contradictions, flag anything load-bearing for the user "
        "(tech / AI / safety / policy that would change their decisions). "
        "Cite sources inline as [source/category]. Stay grounded — never invent "
        "items that are not in the list. End with one short paragraph "
        "describing what should be revisited later in the day.\n\n"
        f"WINDOW: {window_label}\n"
        f"ARTICLES ({len(articles)}):\n{body}\n\nDIGEST:"
    )
    try:
        from eli.cognition.inference_broker import get_broker
        broker = get_broker()
        text = broker.infer(
            prompt,
            system="You are ELI. Produce grounded, themed news digests; no filler.",
            max_tokens=900,
            temperature=0.35,
        )
        return (text or "").strip()
    except Exception as ex:
        # Fallback: deterministic compact list — no canned creative reply.
        return (
            f"[news synthesis offline: {ex}]\n"
            + "\n".join(bullets[:25])
        )


def synthesise_window(force: bool = False) -> Dict[str, Any]:
    """
    Run a 3-hour synthesis if at least WINDOW_SECONDS have elapsed since the
    last one (or `force` is set). Returns metadata about what was stored.
    """
    now = time.time()
    last_end = _last_reflection_end()
    elapsed = now - last_end
    if not force and last_end > 0 and elapsed < WINDOW_SECONDS:
        return {"ok": True, "skipped": True, "elapsed": elapsed}

    start_ts = last_end if last_end > 0 else (now - WINDOW_SECONDS)
    articles = _fetch_window_articles(start_ts, now)

    if not articles:
        # Still record an empty reflection so the cadence advances.
        summary = "(no new articles in this window)"
        sources_json = "[]"
    else:
        from datetime import datetime
        label = (
            f"{datetime.fromtimestamp(start_ts).strftime('%Y-%m-%d %H:%M')} → "
            f"{datetime.fromtimestamp(now).strftime('%H:%M')}"
        )
        summary = _llm_summarise(articles, label)
        sources_json = json.dumps(sorted({a.get("source", "?") for a in articles}))

    conn = _conn()
    cur = conn.execute(
        "INSERT INTO news_reflections (started_at, ended_at, article_count, summary, sources) "
        "VALUES (?, ?, ?, ?, ?)",
        (start_ts, now, len(articles), summary, sources_json),
    )
    rid = cur.lastrowid
    conn.commit()
    conn.close()

    # Mirror into user-memory so the agent bus can recall it later.
    try:
        from eli.memory import get_memory
        mem = get_memory()
        if mem and hasattr(mem, "store_memory"):
            mem.store_memory(
                summary[:1800],
                tags=["news_reflection", "proactive"],
                source="news_synthesis",
                kind="news_reflection",
            )
    except Exception:
        pass

    return {
        "ok": True,
        "skipped": False,
        "id": rid,
        "started_at": start_ts,
        "ended_at": now,
        "article_count": len(articles),
        "summary_length": len(summary),
    }


def recent_reflections(hours: int = 24) -> List[Dict[str, Any]]:
    """Return reflections from the last `hours` hours, oldest first."""
    cutoff = time.time() - hours * 3600
    try:
        conn = _conn()
        rows = conn.execute(
            "SELECT id, started_at, ended_at, article_count, summary, sources "
            "FROM news_reflections WHERE ended_at >= ? ORDER BY ended_at ASC",
            (cutoff,),
        ).fetchall()
        conn.close()
        out: List[Dict[str, Any]] = []
        for rid, st, en, n, summary, sources in rows:
            try:
                src_list = json.loads(sources or "[]")
            except Exception:
                src_list = []
            out.append({
                "id": rid, "started_at": st, "ended_at": en,
                "article_count": n, "summary": summary,
                "sources": src_list,
            })
        return out
    except Exception:
        return []


def build_morning_digest(hours: int = 24) -> Dict[str, Any]:
    """
    Compile the eight 3-hour reflections from the prior 24h into a single
    digest the engine can hand to ELI for expansion + follow-up questions.
    """
    reflections = recent_reflections(hours=hours)
    if not reflections:
        return {
            "ok": True,
            "reflection_count": 0,
            "article_count": 0,
            "digest": "",
            "follow_up_prompt": "",
        }

    from datetime import datetime
    parts: List[str] = []
    total_articles = 0
    for r in reflections:
        st = datetime.fromtimestamp(r["started_at"]).strftime("%H:%M")
        en = datetime.fromtimestamp(r["ended_at"]).strftime("%H:%M")
        total_articles += int(r.get("article_count") or 0)
        parts.append(
            f"[{st}-{en} | {r.get('article_count',0)} articles | sources={','.join(r.get('sources') or [])}]"
            f"\n{r.get('summary','').strip()}"
        )

    digest = "\n\n---\n\n".join(parts)

    follow_up_prompt = (
        "You are ELI delivering the morning briefing. Below are the eight "
        "(or fewer) 3-hour news reflections compiled across the last 24 hours. "
        "Synthesise across them: identify the dominant threads, contradictions "
        "between sources, and signals worth tracking. THEN expand on the most "
        "load-bearing item with the depth a researcher would expect. THEN ask "
        "the user one or two pointed follow-up questions worth their attention "
        "today (just one unless there are genuinely distinct threads worth "
        "pursuing) — tied to the actual content, not generic — and offer to go "
        "deeper if they want to discuss something at length. "
        "Cite the reflection windows (e.g. [09:00-12:00]) when you reference "
        "them. Stay grounded; do not invent stories.\n\n"
        f"=== 24H NEWS REFLECTIONS ({len(reflections)} windows, "
        f"{total_articles} articles total) ===\n{digest}\n\n"
        "MORNING SYNTHESIS:"
    )

    return {
        "ok": True,
        "reflection_count": len(reflections),
        "article_count": total_articles,
        "digest": digest,
        "follow_up_prompt": follow_up_prompt,
    }


# Self-referential / ELI-development / interaction-style noise — these describe
# how the user works WITH ELI, not external subjects they'd want news about. They
# are filtered out so news queries reflect genuine interests (physics, AI, etc.).
# NOTE: this is noise removal, not a hardcoded interest list — interests are
# derived per-user from their own profile.
_INTEREST_NOISE = {
    "eli", "sqlite", "gguf", "runtime", "memory", "recall", "debugging", "debug",
    "tuning", "tune", "parameters", "parameter", "system", "systems", "code",
    "coding", "local", "model", "models", "pipeline", "agent", "agents", "active",
    "last", "user", "work", "works", "working", "material", "framework",
    "frameworks", "involving", "references", "focuses", "focus", "backed",
    "with", "that", "this", "your", "from", "into", "about", "uses", "using",
    "humor", "banter", "detail", "details", "vague", "wants", "prefers", "prefer",
    "responds", "welcome", "step", "technical", "explanations", "light", "wit",
    "actively", "currently", "recently", "recent", "various", "different",
}


def _derive_interest_terms(user_id=None, limit: int = 5) -> list:
    """Distinctive interest keywords derived from the user's OWN profile
    (research + active projects). No hardcoded topics — per-user, per-machine.
    """
    import re as _re
    from collections import Counter
    try:
        from eli.kernel.state import load_user_profile
        prof = load_user_profile(user_id) or {}
    except Exception:
        prof = {}
    parts = []
    for key in ("research", "active_projects"):
        v = prof.get(key)
        if isinstance(v, list):
            parts += [str(x) for x in v]
        elif v:
            parts.append(str(v))
    if not parts:
        return []
    blob = " ".join(parts).lower()
    words = _re.findall(r"[a-z][a-z\-]{3,}", blob)
    counts = Counter(w for w in words if w not in _INTEREST_NOISE)
    # Preserve first-seen order among the most common to keep it stable.
    return [w for w, _ in counts.most_common(limit)]


def interest_news_block(user_id=None, max_items: int = 4) -> str:
    """A short, personalised news section for the morning report.

    Interests are derived from the user's profile (ELI-driven, not hardcoded);
    fetching is network-gated (offline → empty string, never fabricated). Returns
    a ready-to-print block or '' when there's nothing to show.
    """
    try:
        from eli.core.config import network_allowed
        if not network_allowed():
            return ""
    except Exception:
        return ""

    terms = _derive_interest_terms(user_id)
    if not terms:
        return ""

    try:
        from eli.tools.news.news_fetcher import fetch_news, search_stored_news
    except Exception:
        return ""

    seen: set = set()
    articles: list = []
    for term in terms[:3]:
        try:
            fetch_news(topic=term)          # populate store (gated; no-op offline)
        except Exception:
            pass
        try:
            hits = search_stored_news(term, limit=4) or []
        except Exception:
            hits = []
        for art in hits:
            title = str(art.get("title") or "").strip()
            if not title or title.lower() in seen:
                continue
            seen.add(title.lower())
            articles.append(art)
            if len(articles) >= max_items:
                break
        if len(articles) >= max_items:
            break

    if not articles:
        return ""

    lines = ["I have found the following news articles that may be of interest to you:"]
    for art in articles[:max_items]:
        title = str(art.get("title") or "").strip()
        src = str(art.get("source") or "").strip()
        url = str(art.get("url") or "").strip()
        line = f"  • {title}"
        if src:
            line += f" — {src}"
        if url:
            line += f"\n    {url}"
        lines.append(line)
    return "\n".join(lines)


# ── Ad-hoc conversational news briefing ──────────────────────────────────────
# "What's the news?" should NOT raw-dump headlines. ELI reads a bounded set —
# ~half top stories spread across domains, ~half matched to the user's own
# interests — and synthesises a spoken read with a sentence of context each and
# one or two content-tied follow-ups. Bounded input ⇒ no 10k-token OOM. No
# timestamps in the output.

def _one_sentence_gist(summary: str, max_sentences: int = 1, cap: int = 240) -> str:
    """First sentence(s) of an article summary, whitespace-collapsed and capped."""
    import re as _re
    s = " ".join(str(summary or "").strip().split())
    if not s:
        return ""
    parts = _re.split(r"(?<=[.!?])\s+", s)
    gist = " ".join(parts[:max_sentences]).strip()
    return gist[:cap].rstrip()


def _spread_across_domains(articles: List[Dict[str, Any]], n: int) -> List[Dict[str, Any]]:
    """Pick up to n articles maximising category/source diversity, newest first.

    Round-robins one article per domain before taking a second from any domain,
    so a single busy category can't dominate the top stories.
    """
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    order: List[str] = []
    for a in articles:
        key = str(a.get("category") or a.get("source") or "").strip().lower() or "_"
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(a)

    picked: List[Dict[str, Any]] = []
    seen: set = set()
    while len(picked) < n:
        progressed = False
        for key in order:
            bucket = buckets.get(key) or []
            while bucket:
                a = bucket.pop(0)
                t = str(a.get("title") or "").strip().lower()
                if not t or t in seen:
                    continue
                seen.add(t)
                picked.append(a)
                progressed = True
                break
            if len(picked) >= n:
                break
        if not progressed:
            break
    return picked


def build_news_briefing(user_id=None, topic: str = "", top_n: int = 5,
                        interest_n: int = 3, refresh: bool = True) -> Dict[str, Any]:
    """Assemble a bounded, synthesisable briefing + the prompt ELI reads from.

    General ask (no topic): ~half top stories spread across domains, ~half
    matched to the user's OWN profile-derived interests.
    Topic ask (e.g. "news about physics"): just that topic's stories, no
    interest half.
    Each article carries a one-sentence gist; bounded so it never bloats the
    prompt. Does NOT call the LLM — see synthesise_news_briefing.
    """
    try:
        from eli.tools.news.news_fetcher import NewsFetcher, search_stored_news
    except Exception:
        return {"ok": False, "top": [], "interest": [], "synthesis_prompt": ""}

    topic = str(topic or "").strip()
    fetcher = NewsFetcher()
    # Capture whether the refresh actually brought anything LIVE. Offline (the Net
    # toggle off) makes fetch() a no-op, so the read below is served entirely from the
    # cached store — which can be days or weeks old. We record this so the synthesis
    # DISCLOSES the staleness instead of narrating a stale cache as "the latest".
    try:
        from eli.core.config import network_allowed as _net_allowed
        _online = bool(_net_allowed())
    except Exception:
        _online = True
    _fetched_new = 0
    if refresh:
        try:
            _fr = fetcher.fetch(sources=None, topic=topic)
            if isinstance(_fr, dict):
                _fetched_new = int(_fr.get("stored_new") or 0)
        except Exception:
            pass

    import datetime as _dt
    _today = _dt.date.today()

    def _parse_pub(s):
        """Parse the article's stored `published` field (ISO-8601 from arXiv/HN/Reddit, or
        RFC-822 <pubDate> from RSS) into a naive local-ish datetime, or None."""
        s = str(s or "").strip()
        if not s:
            return None
        try:
            return _dt.datetime.fromisoformat(
                s.replace("Z", "+00:00").replace("z", "+00:00")).replace(tzinfo=None)
        except Exception:
            pass
        try:
            from email.utils import parsedate_to_datetime as _pdt
            d = _pdt(s)
            return d.replace(tzinfo=None) if d else None
        except Exception:
            return None

    def _block(items: List[Dict[str, Any]]) -> str:
        out = []
        for a in items:
            title = str(a.get("title") or "").strip()
            src = str(a.get("source") or "").strip()
            gist = _one_sentence_gist(a.get("summary"))
            # Prefer the article's actual PUBLICATION date/time (what "when was it released"
            # means). Fall back to the fetch time ONLY when the source gave no usable pubDate
            # — and then label it 'fetched' so it is never mistaken for the release time.
            ts = ""
            _pub = _parse_pub(a.get("published"))
            if _pub:
                if _pub.date() == _today:
                    ts = _pub.strftime("%H:%M")
                elif _pub.year == _today.year:
                    ts = _pub.strftime("%d %b")
                else:
                    ts = _pub.strftime("%d %b %Y")
            else:
                try:
                    _f = a.get("fetched_at")
                    if _f:
                        _d = _dt.datetime.fromtimestamp(float(_f))
                        ts = ("fetched " + (_d.strftime("%H:%M") if _d.date() == _today
                                            else _d.strftime("%d %b")))
                except Exception:
                    ts = ""
            _tag = f"{src} — {ts}" if (src and ts) else (src or ts)
            line = f"- {title} [{_tag}]" if _tag else f"- {title}"
            if gist:
                line += f" :: {gist}"
            out.append(line)
        return "\n".join(out)

    def _dedupe(items: List[Dict[str, Any]], n: int) -> List[Dict[str, Any]]:
        out, seen = [], set()
        for a in items:
            t = str(a.get("title") or "").strip().lower()
            if not t or t in seen:
                continue
            seen.add(t)
            out.append(a)
            if len(out) >= n:
                break
        return out

    if topic:
        # Topic-focused read — the topic's stories only, no interest half.
        # Prefer get_recent(topic=…) (fetched_at-DESC = CURRENT) over search_stored_news,
        # which orders by FTS RANK and kept returning the SAME week-old articles on a
        # topic ask (the science/physics read came back a week stale). This mirrors the
        # exact fix already applied to the interest half below.
        try:
            arts = fetcher.get_recent(limit=top_n + interest_n + 4, topic=topic) or []
        except Exception:
            arts = []
        if not arts:
            try:
                arts = search_stored_news(topic, limit=top_n + interest_n + 4) or []
            except Exception:
                arts = []
        top = _dedupe(arts, top_n + interest_n)
        interest: List[Dict[str, Any]] = []
        interest_terms: List[str] = []
        prompt = (
            f"You are ELI giving the user a focused news read on \"{topic}\". Do NOT open with a greeting (no 'Good day'/'Hello') — this is mid-conversation. "
            "Use ONLY the articles below — never invent. For EACH story, include "
            "its source AND its publication date exactly as shown in the "
            "[source — time] bracket (e.g. \"[BBC — 14:23]\") so the reader can "
            "see how fresh each item is. Cover the stories conversationally, "
            "giving each roughly a sentence of real context (not just the "
            "headline). Close with one or two pointed follow-up questions tied "
            "to the actual stories (just one unless there are genuinely distinct "
            "threads worth pursuing), and offer to go deeper if they want to "
            "discuss something at length.\n\n"
            f"STORIES ON \"{topic}\":\n{_block(top) or '(none found)'}\n\n"
            "ELI'S NEWS READ:"
        )
    else:
        recent = fetcher.get_recent(limit=60) or []
        top = _spread_across_domains(recent, top_n)
        seen = {str(a.get("title") or "").strip().lower() for a in top}
        interest_terms = _derive_interest_terms(user_id)
        interest = []
        # The interest ("relevant to you") half must be as FRESH as the top half.
        # Both retrieval paths can surface a stale niche match — get_recent filters
        # recent-fetched rows by topic (an old-published arXiv paper can slip in), and
        # the search_stored_news fallback orders by FTS rank (documented to return the
        # same week-old items). Gate every candidate on age: drop anything older than
        # the window rather than parade a two-week-old paper as current. Better to show
        # fewer fresh items than pad with stale ones.
        _now_dt = _dt.datetime.now()

        def _art_age_days(art):
            d = _parse_pub(art.get("published"))
            if d is None:
                try:
                    _f = art.get("fetched_at")
                    d = _dt.datetime.fromtimestamp(float(_f)) if _f else None
                except Exception:
                    d = None
            return (_now_dt - d).days if d else None

        for term in interest_terms[:3]:
            # Pull FRESH, term-specific news, then take the most RECENT matches
            # (NOT relevance-ranked). Fetch is network-gated (no-op offline).
            try:
                if refresh:
                    fetcher.fetch(sources=None, topic=term)
            except Exception:
                pass
            try:
                hits = fetcher.get_recent(limit=8, topic=term) or []
            except Exception:
                hits = []
            if not hits:
                try:
                    hits = search_stored_news(term, limit=6) or []
                except Exception:
                    hits = []
            for art in hits:
                t = str(art.get("title") or "").strip().lower()
                if not t or t in seen:
                    continue
                _age = _art_age_days(art)
                if _age is not None and _age > _INTEREST_MAX_AGE_DAYS:
                    continue  # stale niche match — never surface it as "relevant now"
                seen.add(t)
                interest.append(art)
                if len(interest) >= interest_n:
                    break
            if len(interest) >= interest_n:
                break
        prompt = (
            "You are ELI giving the user a quick, natural news read. Do NOT open with a "
            "greeting (no 'Good day'/'Hello') — this is mid-conversation. Use ONLY the "
            "articles below — never invent. For EACH story, include its source "
            "AND its publication date exactly as shown in the [source — time] "
            "bracket (e.g. \"[BBC — 14:23]\") so the reader can see how fresh "
            "each item is. Present "
            "the TOP STORIES conversationally across the "
            "different domains, giving each roughly a sentence of real context "
            "(not just the headline). THEN, if there are interest matches, say "
            "something like \"I also found these articles that might interest you\" "
            "and cover them the same way. Close with one or two pointed follow-up "
            "questions tied to the actual stories (just one unless there are "
            "genuinely distinct threads worth pursuing), and offer to go deeper if "
            "they want to discuss something at length.\n\n"
            f"TOP STORIES (across domains):\n{_block(top) or '(none available)'}\n\n"
            f"MATCHED TO THEIR INTERESTS ({', '.join(interest_terms[:3]) or 'n/a'}):\n"
            f"{_block(interest) or '(none found)'}\n\n"
            "ELI'S NEWS READ:"
        )

    # ── Freshness disclosure ─────────────────────────────────────────────────
    # Never let a stale cache be narrated as "the latest". Find the age of the freshest
    # SELECTED item; when offline, or the newest item is >=2 days old, prepend a
    # mandatory disclosure the persona must surface — and which forbids implying any
    # story is from "today" (the exact confabulation that dressed a 2-week cache as live).
    def _newest_dt(items):
        newest = None
        for a in items:
            d = _parse_pub(a.get("published"))
            if d is None:
                try:
                    _f = a.get("fetched_at")
                    if _f:
                        d = _dt.datetime.fromtimestamp(float(_f))
                except Exception:
                    d = None
            if d and (newest is None or d > newest):
                newest = d
        return newest

    _newest = _newest_dt(list(top) + list(interest))
    _age_days = (_dt.datetime.now() - _newest).days if _newest else None
    _stale = (not _online) or (_age_days is not None and _age_days >= 2)
    if not _online:
        _when = (f"from {_newest.strftime('%d %b %Y')}" if _newest else "of unknown date")
        _age = f" ({_age_days} day(s) old)" if _age_days is not None else ""
        _freshness = (
            "FRESHNESS — CRITICAL: the network is OFF, so I could NOT fetch live news. "
            f"Everything below is CACHED; the most recent item is {_when}{_age}. You MUST "
            "open by telling the user this is cached and NOT live, and state the age of the "
            "newest item. You MUST NOT imply any story is from today or is breaking. Tell "
            "them to turn the Net toggle on for a live fetch."
        )
    elif _age_days is not None and _age_days >= 2:
        _freshness = (
            f"FRESHNESS: a live refresh found nothing newer than {_age_days} day(s) ago "
            f"(newest item from {_newest.strftime('%d %b %Y')}). Say up front you couldn't "
            "find anything more recent, and do NOT imply any story is from today."
        )
    else:
        _freshness = ""
    if _freshness:
        prompt = _freshness + "\n\n" + prompt

    return {
        "ok": True,
        "topic": topic,
        "top": top,
        "interest": interest,
        "interest_terms": interest_terms[:3] if interest_terms else [],
        "synthesis_prompt": prompt,
        "article_count": len(top) + len(interest),
        "stale": _stale,
        "offline": (not _online),
        "newest_age_days": _age_days,
    }


def synthesise_news_briefing(user_id=None, topic: str = "", top_n: int = 5,
                             interest_n: int = 3, refresh: bool = True) -> str:
    """ELI's spoken read of the news: bounded selection → LLM synthesis.

    General ask = 50/50 top + interests; topic ask = that topic's stories.
    Returns the synthesised text, or '' when there's nothing to read (offline /
    no articles) so the caller can fall back. Never raw-dumps.
    """
    import logging as _log
    _logger = _log.getLogger(__name__)
    brief = build_news_briefing(user_id, topic=topic, top_n=top_n,
                                interest_n=interest_n, refresh=refresh)
    if not brief.get("ok") or brief.get("article_count", 0) == 0:
        _logger.warning(
            "[NEWS_BRIEFING] no briefing built (ok=%s articles=%s) — caller falls back to raw",
            brief.get("ok"), brief.get("article_count", 0))
        return ""
    try:
        from eli.cognition.inference_broker import get_broker
        broker = get_broker()
        # If the model isn't lazy-loaded yet (e.g. news is the FIRST query of the
        # session), broker.infer would raise before triggering the load → we'd
        # fall back to a raw dump. Trigger the canonical load first (idempotent /
        # cached — the same loader the chat path uses, so no double-load).
        if not broker.gguf_ready:
            try:
                from eli.cognition import gguf_inference as _gi
                _gi.load_model()
                _logger.debug("[NEWS_BRIEFING] triggered model load (broker was not ready)")
            except Exception as _le:
                _logger.warning("[NEWS_BRIEFING] model load attempt failed: %r", _le)
        text = broker.infer(
            brief["synthesis_prompt"],
            system="You are ELI. Give a grounded, natural news read — no filler, do NOT open with a greeting (no 'Good day', 'Hello', 'Hi there') — this is mid-conversation, not a fresh start; "
                   "no timestamps, no inventing.",
            max_tokens=700,
            temperature=0.4,
        )
        return (text or "").strip()
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "[NEWS_BRIEFING] synthesis failed (%r) — caller will fall back to raw list",
            exc,
        )
        return ""
