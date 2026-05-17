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
            priority=20,
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
        "the user three pointed follow-up questions that would be worth their "
        "attention today — questions tied to the actual content, not generic. "
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
