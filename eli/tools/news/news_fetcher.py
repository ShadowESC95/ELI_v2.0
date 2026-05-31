"""
ELI Web Learning Module — News & Current Events Fetcher
=========================================================
100% offline-capable after fetch. Uses only stdlib urllib.
No API keys required for the free sources.

Sources (all free, no auth):
  • HackerNews (Algolia API)      — tech/startup news
  • Reddit JSON (r/worldnews etc) — world/tech/science
  • arXiv API                     — research papers
  • Open RSS feeds via feedparser  — general news (BBC, Reuters etc)

Stores everything in user.sqlite3 in a `news_articles` table.
ELI can then search/recall news via the memory system.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional


# ── DB path ──────────────────────────────────────────────────────────────────

def _get_db() -> Path:
    try:
        from eli.core.paths import memory_db_path
        return Path(memory_db_path())
    except Exception:
        return Path(__file__).resolve().parents[3] / "artifacts" / "db" / "user.sqlite3"


# ── Schema ────────────────────────────────────────────────────────────────────

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS news_articles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT    NOT NULL,
    title       TEXT    NOT NULL,
    url         TEXT,
    summary     TEXT,
    category    TEXT,
    fetched_at  REAL    NOT NULL,
    published   TEXT,
    score       INTEGER DEFAULT 0,
    UNIQUE(url)
)
"""

_CREATE_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS news_fts USING fts5(
    title, summary, source, category,
    content='news_articles', content_rowid='id'
)
"""

_CREATE_TRIGGER_INSERT = """
CREATE TRIGGER IF NOT EXISTS news_ai AFTER INSERT ON news_articles BEGIN
    INSERT INTO news_fts(rowid, title, summary, source, category)
    VALUES (new.id, new.title, new.summary, new.source, new.category);
END
"""


def _init_db(conn: sqlite3.Connection) -> None:
    conn.execute(_CREATE_TABLE)
    try:
        conn.execute(_CREATE_FTS)
        conn.execute(_CREATE_TRIGGER_INSERT)
    except Exception:
        pass
    conn.commit()


# ── HTTP helpers ──────────────────────────────────────────────────────────────

_HEADERS = {
    "User-Agent": "ELI-AI-Assistant/1.0 (local; educational)",
    "Accept": "application/json,text/html,*/*",
}


def _fetch_json(url: str, timeout: int = 6) -> Any:
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))


def _fetch_text(url: str, timeout: int = 6) -> str:
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&quot;", '"', text)
    text = re.sub(r"&#\d+;", "", text)
    return re.sub(r"\s+", " ", text).strip()


# ── Individual source fetchers ────────────────────────────────────────────────

def _fetch_hackernews(limit: int = 20) -> List[Dict]:
    """HackerNews top stories via Algolia API — no auth."""
    url = (
        "https://hn.algolia.com/api/v1/search?"
        + urllib.parse.urlencode({
            "tags": "front_page",
            "hitsPerPage": limit,
        })
    )
    data = _fetch_json(url)
    articles = []
    for hit in data.get("hits", []):
        articles.append({
            "source": "HackerNews",
            "title": hit.get("title", ""),
            "url": hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
            "summary": _strip_html(hit.get("story_text") or ""),
            "category": "tech",
            "published": hit.get("created_at", ""),
            "score": hit.get("points", 0),
        })
    return articles


def _fetch_reddit(subreddits: Optional[List[str]] = None, limit: int = 10) -> List[Dict]:
    """Reddit JSON API — no auth needed, rate-limited."""
    if subreddits is None:
        subreddits = ["worldnews", "technology", "science", "MachineLearning"]
    articles = []
    for sub in subreddits:
        try:
            url = f"https://www.reddit.com/r/{sub}/top.json?t=day&limit={limit}"
            data = _fetch_json(url)
            for post in data.get("data", {}).get("children", []):
                d = post.get("data", {})
                if d.get("is_self") or d.get("stickied"):
                    continue
                articles.append({
                    "source": f"Reddit/r/{sub}",
                    "title": _strip_html(d.get("title", "")),
                    "url": d.get("url", ""),
                    "summary": _strip_html(d.get("selftext", ""))[:500],
                    "category": sub,
                    "published": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                              time.gmtime(d.get("created_utc", 0))),
                    "score": d.get("score", 0),
                })
        except Exception:
            continue
    return articles


def _fetch_arxiv(query: str = "artificial intelligence", limit: int = 10) -> List[Dict]:
    """arXiv API — free, no auth. Returns recent ML/AI papers."""
    url = (
        "https://export.arxiv.org/api/query?"
        + urllib.parse.urlencode({
            "search_query": f"ti:{query}",
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "max_results": limit,
        })
    )
    text = _fetch_text(url)
    articles = []
    # Parse Atom XML minimally (no external deps)
    entries = re.findall(r"<entry>(.*?)</entry>", text, re.DOTALL)
    for entry in entries:
        title = re.search(r"<title>(.*?)</title>", entry, re.DOTALL)
        summary = re.search(r"<summary>(.*?)</summary>", entry, re.DOTALL)
        link = re.search(r'<id>(.*?)</id>', entry)
        published = re.search(r"<published>(.*?)</published>", entry)
        articles.append({
            "source": "arXiv",
            "title": _strip_html(title.group(1) if title else ""),
            "url": (link.group(1) if link else "").strip(),
            "summary": _strip_html(summary.group(1) if summary else "")[:600],
            "category": "research",
            "published": (published.group(1) if published else "").strip(),
            "score": 0,
        })
    return articles


def _fetch_rss(feed_url: str, source_name: str, category: str = "news",
               limit: int = 15) -> List[Dict]:
    """Generic RSS/Atom reader using only stdlib."""
    text = _fetch_text(feed_url)
    articles = []
    # Items (RSS)
    items = re.findall(r"<item>(.*?)</item>", text, re.DOTALL)
    # Entries (Atom)
    if not items:
        items = re.findall(r"<entry>(.*?)</entry>", text, re.DOTALL)
    for item in items[:limit]:
        title = re.search(r"<title[^>]*><!\[CDATA\[(.*?)\]\]></title>|<title[^>]*>(.*?)</title>",
                          item, re.DOTALL)
        link = re.search(r"<link[^>]*>(.*?)</link>|<link href=['\"]([^'\"]+)['\"]", item)
        desc = re.search(r"<description[^>]*><!\[CDATA\[(.*?)\]\]></description>|"
                         r"<description[^>]*>(.*?)</description>|"
                         r"<summary[^>]*>(.*?)</summary>",
                         item, re.DOTALL)
        pub = re.search(r"<pubDate>(.*?)</pubDate>|<published>(.*?)</published>", item)
        t = _strip_html(title.group(1) or title.group(2) if title else "")
        u = (link.group(1) or link.group(2) if link else "").strip()
        s = _strip_html((desc.group(1) or desc.group(2) or desc.group(3))
                        if desc else "")[:500]
        if not t:
            continue
        articles.append({
            "source": source_name,
            "title": t,
            "url": u,
            "summary": s,
            "category": category,
            "published": (pub.group(1) or pub.group(2) if pub else "").strip(),
            "score": 0,
        })
    return articles


# ── Source registry ───────────────────────────────────────────────────────────

# Free RSS feeds — no API key, no login
_RSS_FEEDS = [
    ("https://feeds.bbci.co.uk/news/rss.xml",              "BBC News",       "world"),
    ("https://feeds.bbci.co.uk/news/science_and_environment/rss.xml", "BBC Science", "science"),
    ("https://feeds.arstechnica.com/arstechnica/index",    "Ars Technica",   "tech"),
    ("https://feeds.feedburner.com/TechCrunch",            "TechCrunch",     "tech"),
    ("https://www.nasa.gov/rss/dyn/breaking_news.rss",     "NASA News",      "science"),
    ("https://phys.org/rss-feed/",                         "Phys.org",       "science"),
    ("https://physicsworld.com/feed/",                     "Physics World",  "physics"),
    ("https://www.sciencedaily.com/rss/matter_energy/physics.xml", "ScienceDaily Physics", "physics"),
]


_TOPIC_TERMS = {
    "physics": {
        "physics", "quantum", "particle", "cosmology", "astrophysics",
        "relativity", "neutrino", "electron", "photon", "collider",
        "cern", "dark matter", "black hole", "gravity", "gravitational",
    },
    "science": {
        "science", "physics", "biology", "chemistry", "space", "nasa",
        "climate", "research", "study", "scientist",
    },
    "ai": {
        "ai", "artificial intelligence", "machine learning", "llm",
        "model", "neural", "robot", "agent",
    },
    "technology": {
        "technology", "software", "hardware", "cyber", "security",
        "startup", "developer", "programming",
    },
}


def _topic_terms(topic: str) -> List[str]:
    t = (topic or "").strip().lower()
    if not t:
        return []
    terms = {t}
    for key, values in _TOPIC_TERMS.items():
        if t == key or t in values:
            terms.update(values)
            break
    terms.update(w for w in re.split(r"\W+", t) if len(w) >= 4)
    return sorted(terms, key=len, reverse=True)


def _article_matches_topic(article: Dict[str, Any], topic: str) -> bool:
    terms = _topic_terms(topic)
    if not terms:
        return True
    haystack = " ".join(str(article.get(k) or "") for k in (
        "source", "title", "summary", "category", "url"
    )).lower()
    return any(term in haystack for term in terms)


def _topic_default_sources(topic: str, sources: Optional[List[str]]) -> Optional[List[str]]:
    if sources is not None and "all" not in sources:
        return sources
    t = (topic or "").strip().lower()
    if t in {"physics", "science", "space", "astronomy", "cosmology"}:
        return ["reddit", "arxiv", "rss"]
    if t in {"ai", "artificial intelligence", "machine learning", "llm"}:
        return ["hn", "reddit", "arxiv", "rss"]
    return sources


def _rss_feeds_for_topic(topic: str) -> List[tuple[str, str, str]]:
    t = (topic or "").strip().lower()
    if not t:
        return _RSS_FEEDS
    if t in {"physics", "science", "space", "astronomy", "cosmology"}:
        keep = {"science", "physics"}
        return [feed for feed in _RSS_FEEDS if feed[2] in keep]
    if t in {"ai", "artificial intelligence", "machine learning", "llm", "technology", "tech"}:
        keep = {"tech", "science"}
        return [feed for feed in _RSS_FEEDS if feed[2] in keep]
    return _RSS_FEEDS


# ── Main public API ───────────────────────────────────────────────────────────

class NewsFetcher:
    """Fetch current events from free sources and store in ELI's memory DB."""

    def __init__(self):
        self.db_path = _get_db()
        self._ensure_db()

    def _ensure_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(self.db_path)) as conn:
            _init_db(conn)

    def _store(self, articles: List[Dict]) -> int:
        stored = 0
        now = time.time()
        with sqlite3.connect(str(self.db_path)) as conn:
            _init_db(conn)
            for a in articles:
                url = (a.get("url") or "").strip()
                title = (a.get("title") or "").strip()
                if not title:
                    continue
                try:
                    conn.execute(
                        "INSERT OR IGNORE INTO news_articles "
                        "(source, title, url, summary, category, fetched_at, published, score) "
                        "VALUES (?,?,?,?,?,?,?,?)",
                        (
                            a.get("source", "unknown"),
                            title[:500],
                            url[:1000] if url else None,
                            (a.get("summary") or "")[:1000],
                            a.get("category", "general"),
                            now,
                            (a.get("published") or "")[:64],
                            int(a.get("score") or 0),
                        ),
                    )
                    if conn.execute("SELECT changes()").fetchone()[0]:
                        stored += 1
                except Exception:
                    continue
            conn.commit()
        return stored

    def fetch(
        self,
        sources: Optional[List[str]] = None,
        topic: str = "",
        limit_per_source: int = 15,
    ) -> Dict[str, Any]:
        """
        Fetch news from selected sources.
        sources: list of any of ['hn', 'reddit', 'arxiv', 'rss', 'all']
        Returns summary dict.
        """
        try:
            from eli.core.config import network_allowed
            if not network_allowed():
                return {"skipped": "offline_mode", "fetched": 0, "stored_new": 0, "errors": []}
        except Exception:
            return {"skipped": "offline_mode", "fetched": 0, "stored_new": 0, "errors": []}
        sources = _topic_default_sources(topic, sources)
        if sources is None or "all" in sources:
            sources = ["hn", "reddit", "arxiv", "rss"]

        all_articles: List[Dict] = []
        errors: List[str] = []

        if "hn" in sources:
            try:
                all_articles += _fetch_hackernews(limit=limit_per_source)
            except Exception as e:
                errors.append(f"HackerNews: {e}")

        if "reddit" in sources:
            try:
                subs = None
                if topic:
                    subs = [topic.replace(" ", ""), "worldnews", "technology"]
                all_articles += _fetch_reddit(subreddits=subs, limit=10)
            except Exception as e:
                errors.append(f"Reddit: {e}")

        if "arxiv" in sources:
            try:
                q = topic or "artificial intelligence machine learning"
                all_articles += _fetch_arxiv(query=q, limit=limit_per_source)
            except Exception as e:
                errors.append(f"arXiv: {e}")

        if "rss" in sources:
            for feed_url, name, cat in _rss_feeds_for_topic(topic):
                try:
                    all_articles += _fetch_rss(feed_url, name, cat, limit=limit_per_source)
                except Exception as e:
                    errors.append(f"{name}: {e}")

        matched_articles = [a for a in all_articles if _article_matches_topic(a, topic)]
        stored = self._store(all_articles)
        return {
            "ok": True,
            "fetched": len(all_articles),
            "matched": len(matched_articles),
            "stored_new": stored,
            "sources_used": sources,
            "errors": errors,
        }

    def search(self, query: str, limit: int = 10) -> List[Dict]:
        """Full-text search stored articles."""
        with sqlite3.connect(str(self.db_path)) as conn:
            _init_db(conn)
            try:
                rows = conn.execute(
                    "SELECT n.source, n.title, n.url, n.summary, n.category, n.published "
                    "FROM news_fts f JOIN news_articles n ON f.rowid = n.id "
                    "WHERE news_fts MATCH ? ORDER BY rank LIMIT ?",
                    (query, limit),
                ).fetchall()
            except Exception:
                # FTS not available — fallback to LIKE
                rows = conn.execute(
                    "SELECT source, title, url, summary, category, published "
                    "FROM news_articles "
                    "WHERE title LIKE ? OR summary LIKE ? "
                    "ORDER BY fetched_at DESC LIMIT ?",
                    (f"%{query}%", f"%{query}%", limit),
                ).fetchall()
        return [
            {"source": r[0], "title": r[1], "url": r[2],
             "summary": r[3], "category": r[4], "published": r[5]}
            for r in rows
        ]

    def get_recent(self, limit: int = 20, category: str = "", topic: str = "") -> List[Dict]:
        """Return most recently fetched articles."""
        with sqlite3.connect(str(self.db_path)) as conn:
            _init_db(conn)
            if topic:
                rows = conn.execute(
                    "SELECT source, title, url, summary, category, published, fetched_at "
                    "FROM news_articles ORDER BY fetched_at DESC LIMIT ?",
                    (max(limit * 8, 80),),
                ).fetchall()
            elif category:
                rows = conn.execute(
                    "SELECT source, title, url, summary, category, published, fetched_at "
                    "FROM news_articles WHERE category=? "
                    "ORDER BY fetched_at DESC LIMIT ?",
                    (category, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT source, title, url, summary, category, published, fetched_at "
                    "FROM news_articles ORDER BY fetched_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [
            {"source": r[0], "title": r[1], "url": r[2],
             "summary": r[3], "category": r[4], "published": r[5], "fetched_at": r[6]}
            for r in rows
            if not topic or _article_matches_topic({
                "source": r[0], "title": r[1], "url": r[2],
                "summary": r[3], "category": r[4],
            }, topic)
        ][:limit]

    def get_relevant(self, topic: str, limit: int = 20) -> List[Dict]:
        """Return stored articles relevant to a topic, newest first."""
        if not (topic or "").strip():
            return self.get_recent(limit=limit)
        hits = self.search(topic, limit=limit)
        if len(hits) >= min(3, limit):
            return hits[:limit]
        seen = {h.get("url") or h.get("title") for h in hits}
        for article in self.get_recent(limit=limit * 2, topic=topic):
            key = article.get("url") or article.get("title")
            if key not in seen:
                hits.append(article)
                seen.add(key)
            if len(hits) >= limit:
                break
        return hits[:limit]

    def stats(self) -> Dict[str, Any]:
        """Return DB stats."""
        with sqlite3.connect(str(self.db_path)) as conn:
            _init_db(conn)
            total = conn.execute("SELECT COUNT(*) FROM news_articles").fetchone()[0]
            sources = conn.execute(
                "SELECT source, COUNT(*) FROM news_articles GROUP BY source"
            ).fetchall()
            latest = conn.execute(
                "SELECT MAX(fetched_at) FROM news_articles"
            ).fetchone()[0]
        return {
            "total_articles": total,
            "by_source": dict(sources),
            "last_fetched": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(latest)) if latest else "never",
        }


# ── Module-level convenience functions ────────────────────────────────────────

_fetcher: Optional[NewsFetcher] = None


def _get_fetcher() -> NewsFetcher:
    global _fetcher
    if _fetcher is None:
        _fetcher = NewsFetcher()
    return _fetcher


def fetch_news(topic: str = "", sources: Optional[List[str]] = None) -> Dict[str, Any]:
    """Fetch current news and store in ELI's DB. Returns summary.

    Gated by network_allowed() — returns immediately in offline mode (the default).
    """
    return _get_fetcher().fetch(sources=sources, topic=topic)


def search_stored_news(query: str, limit: int = 10) -> List[Dict]:
    """Search previously fetched news articles."""
    return _get_fetcher().search(query, limit=limit)
