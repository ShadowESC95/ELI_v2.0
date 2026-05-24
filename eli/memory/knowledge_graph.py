from __future__ import annotations

import os
from eli.core.paths import get_paths
"""
ELI Knowledge Graph — SQLite-backed entity-relation store.
Lives inside user.sqlite3 alongside the memories/FTS5 tables.

Schema
------
  kg_entities  (id, name, type, aliases, description, confidence, ts)
  kg_relations (id, subject_id, predicate, object_id, weight, source, ts)

Predicate vocabulary (open — any string is valid, these are conventions):
  is_a, has_name, nickname, works_on, uses, prefers, knows, located_in,
  created_by, part_of, related_to, caused_by, contradicts

Query API
---------
  kg = get_knowledge_graph()
          kg.search_entities("developer")     # → fuzzy name/description match
  """


import sqlite3
import threading
import time
import re

# Common English words that should never become KG entities
_STOPWORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "must", "shall", "can", "not", "no", "nor",
    "and", "or", "but", "if", "in", "on", "at", "to", "for", "of", "with",
    "by", "from", "up", "about", "into", "through", "after", "it", "its",
    "this", "that", "these", "those", "i", "me", "my", "we", "us", "our",
    "you", "your", "he", "him", "his", "she", "her", "they", "them", "their",
    "what", "which", "who", "whom", "when", "where", "why", "how", "all",
    "just", "so", "then", "than", "also", "very", "too", "some", "any",
    "also", "yes", "yeah", "ok", "okay", "hey", "hi", "hello", "well",
})
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


from eli.utils.log import get_logger
log = get_logger(__name__)

_INSTANCE: Optional["KnowledgeGraph"] = None
_LOCK = threading.Lock()


# ── Schema ──────────────────────────────────────────────────────────────────

_DDL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS kg_entities (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    type        TEXT    DEFAULT 'concept',
    aliases     TEXT    DEFAULT '',
    description TEXT    DEFAULT '',
    confidence  REAL    DEFAULT 1.0,
    ts          REAL    NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS kg_entities_name ON kg_entities(LOWER(name));

CREATE TABLE IF NOT EXISTS kg_relations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id  INTEGER NOT NULL REFERENCES kg_entities(id) ON DELETE CASCADE,
    predicate   TEXT    NOT NULL,
    object_id   INTEGER NOT NULL REFERENCES kg_entities(id) ON DELETE CASCADE,
    weight      REAL    DEFAULT 1.0,
    source      TEXT    DEFAULT 'inferred',
    ts          REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS kg_rel_subj ON kg_relations(subject_id);
CREATE INDEX IF NOT EXISTS kg_rel_obj  ON kg_relations(object_id);
CREATE UNIQUE INDEX IF NOT EXISTS kg_rel_unique
    ON kg_relations(subject_id, LOWER(predicate), object_id);

CREATE VIRTUAL TABLE IF NOT EXISTS kg_entities_fts
    USING fts5(name, aliases, description, content='kg_entities', content_rowid='id');

CREATE TRIGGER IF NOT EXISTS kg_ent_ai AFTER INSERT ON kg_entities BEGIN
    INSERT INTO kg_entities_fts(rowid, name, aliases, description)
    VALUES (new.id, new.name, COALESCE(new.aliases,''), COALESCE(new.description,''));
END;
CREATE TRIGGER IF NOT EXISTS kg_ent_au AFTER UPDATE ON kg_entities BEGIN
    INSERT INTO kg_entities_fts(kg_entities_fts, rowid, name, aliases, description)
    VALUES ('delete', old.id, old.name, COALESCE(old.aliases,''), COALESCE(old.description,''));
    INSERT INTO kg_entities_fts(rowid, name, aliases, description)
    VALUES (new.id, new.name, COALESCE(new.aliases,''), COALESCE(new.description,''));
END;
CREATE TRIGGER IF NOT EXISTS kg_ent_ad AFTER DELETE ON kg_entities BEGIN
    INSERT INTO kg_entities_fts(kg_entities_fts, rowid, name, aliases, description)
    VALUES ('delete', old.id, old.name, COALESCE(old.aliases,''), COALESCE(old.description,''));
END;
"""


def _db_path() -> Path:
    try:
        from eli.core.paths import knowledge_graph_db_path
        return Path(knowledge_graph_db_path())
    except Exception:
        return Path(os.environ.get("ELI_MEMORY_DB", os.environ.get("ELI_MEMORY_DB_PATH", str(get_paths().user_db))))


# ── Connection helper ────────────────────────────────────────────────────────

def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


# ── KnowledgeGraph class ─────────────────────────────────────────────────────

class KnowledgeGraph:
    """SQLite-backed entity-relation knowledge graph."""

    def __init__(self, db_path: Optional[Path] = None):
        self._path = Path(db_path) if db_path else _db_path()
        self._lock = threading.Lock()
        self._init_schema()

    @property
    def db_path(self) -> Path:
        """Canonical SQLite file backing the active knowledge graph."""
        return self._path

    @property
    def path(self) -> Path:
        """Compatibility alias for callers that inspect store locations."""
        return self._path

    def _init_schema(self) -> None:
        # executescript() handles multi-statement DDL including triggers that
        # contain internal semicolons (which a naive split(";") would mangle).
        conn = _connect(self._path)
        try:
            conn.executescript(_DDL)
        finally:
            conn.close()

    def _conn(self) -> sqlite3.Connection:
        return _connect(self._path)

    # ── Entity CRUD ──────────────────────────────────────────────────────────

    def upsert_entity(
        self,
        name: str,
        entity_type: str = "concept",
        aliases: Optional[List[str]] = None,
        description: str = "",
        confidence: float = 1.0,
    ) -> int:
        """Insert or update an entity. Returns its id."""
        name = name.strip()
        if not name:
            return -1
        aliases_str = ", ".join(a.strip() for a in (aliases or []) if a.strip())
        now = time.time()
        with self._lock:
            conn = self._conn()
            try:
                row = conn.execute(
                    "SELECT id, aliases, description FROM kg_entities WHERE LOWER(name)=LOWER(?)",
                    (name,)
                ).fetchone()
                if row:
                    eid = row["id"]
                    # Merge aliases
                    existing_aliases = set(a.strip() for a in (row["aliases"] or "").split(",") if a.strip())
                    new_aliases = set(a.strip() for a in aliases_str.split(",") if a.strip())
                    merged = ", ".join(sorted(existing_aliases | new_aliases))
                    desc = description or row["description"] or ""
                    conn.execute(
                        "UPDATE kg_entities SET aliases=?, description=?, confidence=?, ts=? WHERE id=?",
                        (merged, desc, confidence, now, eid)
                    )
                else:
                    cur = conn.execute(
                        "INSERT INTO kg_entities(name, type, aliases, description, confidence, ts) "
                        "VALUES (?,?,?,?,?,?)",
                        (name, entity_type, aliases_str, description, confidence, now)
                    )
                    eid = cur.lastrowid
                conn.commit()
                return eid
            finally:
                conn.close()

    def get_entity_id(self, name: str) -> Optional[int]:
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT id FROM kg_entities WHERE LOWER(name)=LOWER(?)", (name,)
            ).fetchone()
            if row:
                return row["id"]
            # Check aliases
            row = conn.execute(
                "SELECT id FROM kg_entities WHERE LOWER(aliases) LIKE ?",
                (f"%{name.lower()}%",)
            ).fetchone()
            return row["id"] if row else None
        finally:
            conn.close()

    # ── Relation CRUD ─────────────────────────────────────────────────────────

    def add_relation(
        self,
        subject: str,
        predicate: str,
        obj: str,
        weight: float = 1.0,
        source: str = "inferred",
        auto_create: bool = True,
    ) -> bool:
        """Add (subject)-[predicate]->(object) triple. Returns True if new."""
        predicate = predicate.strip().lower().replace(" ", "_")
        now = time.time()
        sid = self.get_entity_id(subject)
        oid = self.get_entity_id(obj)
        if sid is None and auto_create:
            sid = self.upsert_entity(subject)
        if oid is None and auto_create:
            oid = self.upsert_entity(obj)
        if sid is None or oid is None:
            return False
        if sid == oid:
            return False  # skip self-loops (e.g. alias resolving to same entity)
        with self._lock:
            conn = self._conn()
            try:
                existing = conn.execute(
                    "SELECT id FROM kg_relations WHERE subject_id=? AND LOWER(predicate)=? AND object_id=?",
                    (sid, predicate, oid)
                ).fetchone()
                if existing:
                    conn.execute(
                        "UPDATE kg_relations SET weight=MAX(weight,?), ts=? WHERE id=?",
                        (weight, now, existing["id"])
                    )
                    conn.commit()
                    return False
                conn.execute(
                    "INSERT INTO kg_relations(subject_id, predicate, object_id, weight, source, ts) "
                    "VALUES (?,?,?,?,?,?)",
                    (sid, predicate, oid, weight, source, now)
                )
                conn.commit()
                return True
            finally:
                conn.close()

    # ── Query ─────────────────────────────────────────────────────────────────

    def query_entity(self, name: str) -> Optional[Dict[str, Any]]:
        """Return entity dict with all outbound and inbound relations."""
        eid = self.get_entity_id(name)
        if eid is None:
            return None
        conn = self._conn()
        try:
            ent = conn.execute("SELECT * FROM kg_entities WHERE id=?", (eid,)).fetchone()
            if not ent:
                return None
            result = dict(ent)

            out_rows = conn.execute(
                """SELECT r.predicate, e.name AS object, r.weight
                   FROM kg_relations r JOIN kg_entities e ON r.object_id=e.id
                   WHERE r.subject_id=? ORDER BY r.weight DESC""",
                (eid,)
            ).fetchall()
            in_rows = conn.execute(
                """SELECT e.name AS subject, r.predicate, r.weight
                   FROM kg_relations r JOIN kg_entities e ON r.subject_id=e.id
                   WHERE r.object_id=? ORDER BY r.weight DESC""",
                (eid,)
            ).fetchall()

            result["outbound"] = [dict(r) for r in out_rows]
            result["inbound"] = [dict(r) for r in in_rows]
            return result
        finally:
            conn.close()

    def related(self, name: str, hops: int = 2) -> List[Dict[str, Any]]:
        """
        Multi-hop BFS from entity `name`. Returns all reachable entities
        within `hops` steps, with their relations.
        """
        start_id = self.get_entity_id(name)
        if start_id is None:
            return []
        conn = self._conn()
        try:
            visited: set = {start_id}
            frontier = [start_id]
            results: List[Dict[str, Any]] = []

            for _ in range(hops):
                if not frontier:
                    break
                placeholders = ",".join("?" * len(frontier))
                rows = conn.execute(
                    f"""SELECT r.predicate, e_s.name AS subject, e_o.name AS object,
                               r.subject_id, r.object_id, r.weight
                        FROM kg_relations r
                        JOIN kg_entities e_s ON r.subject_id=e_s.id
                        JOIN kg_entities e_o ON r.object_id=e_o.id
                        WHERE r.subject_id IN ({placeholders})
                           OR r.object_id  IN ({placeholders})""",
                    frontier + frontier
                ).fetchall()
                new_frontier = []
                for row in rows:
                    results.append(dict(row))
                    for nid in (row["subject_id"], row["object_id"]):
                        if nid not in visited:
                            visited.add(nid)
                            new_frontier.append(nid)
                frontier = new_frontier
            return results
        finally:
            conn.close()

    def search_entities(self, query: str, limit: int = 8) -> List[Dict[str, Any]]:
        """FTS5 search over entity names, aliases, and descriptions."""
        q = query.strip()
        if not q:
            return []
        conn = self._conn()
        try:
            # FTS5 attempt
            try:
                fts_q = " OR ".join(
                    f'"{t}"' for t in re.split(r"[^a-zA-Z0-9_]+", q) if len(t) > 1
                )
                if fts_q:
                    rows = conn.execute(
                        """SELECT e.* FROM kg_entities e
                           JOIN kg_entities_fts f ON e.id=f.rowid
                           WHERE kg_entities_fts MATCH ?
                           ORDER BY e.confidence DESC LIMIT ?""",
                        (fts_q, limit)
                    ).fetchall()
                    return [dict(r) for r in rows]
            except Exception:
                pass
            # LIKE fallback
            like = f"%{q.lower()}%"
            rows = conn.execute(
                """SELECT * FROM kg_entities
                   WHERE LOWER(name) LIKE ? OR LOWER(aliases) LIKE ? OR LOWER(description) LIKE ?
                   ORDER BY confidence DESC LIMIT ?""",
                (like, like, like, limit)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # Patterns that imply the user is asking about their own identity
    _IDENTITY_RE = re.compile(
        r"\b(who am i|my name|know me|who i am|do you know|what('?s| is) my|"
        r"remember me|you know me|call me|am i|i am)\b",
        re.I,
    )

    def context_for_prompt(self, query: str, max_chars: int = 800) -> str:
        """
        Return a compact KG context block suitable for LLM injection.
        Searches entities matching `query`, then expands one hop.
        Tries the full query first, then individual tokens (skipping stopwords).
        For identity queries, seeds with user identity context if explicitly stored.
        """
        hits = self.search_entities(query, limit=4)
        if not hits:
            # Seed with identity entities for first-person queries
            if self._IDENTITY_RE.search(query):
                for seed in ("User",):
                    for h in self.search_entities(seed, limit=2):
                        if h not in hits:
                            hits.append(h)

        if not hits:
            # Try individual tokens (proper nouns / meaningful words only)
            tokens = [
                t for t in re.split(r"[^a-zA-Z0-9_]+", query)
                if len(t) > 1 and t.lower() not in _STOPWORDS
            ]
            seen_ids: set = set()
            for tok in tokens:
                for h in self.search_entities(tok, limit=3):
                    if h["id"] not in seen_ids:
                        seen_ids.add(h["id"])
                        hits.append(h)
                if len(hits) >= 6:
                    break
        if not hits:
            return ""

        lines: List[str] = []
        seen_triples: set = set()

        for ent in hits:
            name = ent["name"]
            ent_detail = self.query_entity(name)
            if not ent_detail:
                continue
            desc = ent_detail.get("description", "").strip()
            aliases = ent_detail.get("aliases", "").strip()
            header = f"[{name}]"
            if ent_detail.get("type") and ent_detail["type"] != "concept":
                header += f" ({ent_detail['type']})"
            if desc:
                header += f": {desc}"
            if aliases:
                header += f" — also known as: {aliases}"
            lines.append(header)
            for rel in (ent_detail.get("outbound") or [])[:5]:
                triple = (name, rel["predicate"], rel["object"])
                if triple not in seen_triples:
                    seen_triples.add(triple)
                    lines.append(f"  {name} —[{rel['predicate']}]→ {rel['object']}")
            for rel in (ent_detail.get("inbound") or [])[:3]:
                triple = (rel["subject"], rel["predicate"], name)
                if triple not in seen_triples:
                    seen_triples.add(triple)
                    lines.append(f"  {rel['subject']} —[{rel['predicate']}]→ {name}")

        text = "\n".join(lines)
        if len(text) > max_chars:
            text = text[:max_chars].rsplit("\n", 1)[0]
        return text

    def stats(self) -> Dict[str, int]:
        conn = self._conn()
        try:
            e = conn.execute("SELECT COUNT(*) FROM kg_entities").fetchone()[0]
            r = conn.execute("SELECT COUNT(*) FROM kg_relations").fetchone()[0]
            return {"entities": e, "relations": r}
        finally:
            conn.close()

    # ── Automatic extraction from memory text ────────────────────────────────

    def extract_from_memory(self, text: str, source: str = "memory") -> int:
        """
        Lightweight rule-based triple extraction from a memory string.
        Returns number of triples added.
        """
        added = 0
        text = text.strip()
        if not text or len(text) < 10:
            return 0

        patterns: List[Tuple[str, str]] = [
            # "User's name is X" / "my name is X"
            (r"(?:user(?:'s)?\s+name\s+is|my\s+name\s+is)\s+([A-Za-z][a-zA-Z ]{1,24})", "has_name"),
            # "nickname: X" / "also known as X" / "call me X"
            (r"(?:nickname[:\s]+|also\s+known\s+as\s+|call\s+me\s+)([A-Za-z][a-zA-Z ]{1,20})", "nickname"),
            # "X works on Y" — relaxed: any word, any case
            (r"([A-Za-z][a-zA-Z0-9]{1,20})\s+works\s+on\s+([A-Za-z0-9 _\-\.]{2,50})(?:[.,]|$)", "works_on"),
            # "prefers X" / "user prefers X"
            (r"(?:user\s+)?prefers?\s+([A-Za-z0-9 _\-\.]{2,40})(?:[.,]|$)", "prefers"),
            # "likes X" / "user likes X"
            (r"(?:user\s+)?likes?\s+([A-Za-z0-9 _\-\.]{2,40})(?:[.,]|$)", "prefers"),
            # "X uses Y" — relaxed: any word, any case
            (r"([A-Za-z][a-zA-Z0-9]{1,20})\s+uses?\s+([A-Za-z0-9 _\-\.]{2,40})(?:[.,]|$)", "uses"),
            # "I am a X" / "I'm a X"
            (r"(?:i\s+am|i'm)\s+(?:a\s+|an\s+)?([A-Za-z][a-zA-Z ]{2,30})(?:[.,]|$)", "is_a"),
        ]

        # Only extract identity predicates from user-authored text, never from
        # assistant turns or internal memory synthesis, to prevent hallucinated
        # assistant responses from poisoning the knowledge graph.
        _identity_predicates = {"has_name", "nickname"}
        _trusted_sources = {"user", "user_explicit", "identity_extract"}

        for pattern, predicate in patterns:
            if predicate in _identity_predicates and source not in _trusted_sources:
                continue
            for m in re.finditer(pattern, text, re.I):
                groups = m.groups()
                if predicate in ("has_name", "nickname", "prefers", "is_a"):
                    # subject is implicit "User"
                    obj = groups[-1].strip()
                    if (obj and len(obj) > 1
                            and obj.lower() not in _STOPWORDS):
                        self.upsert_entity("User", "person")
                        self.upsert_entity(obj, "value")
                        # Contradiction detection for identity predicates:
                        # if User already has a different has_name/nickname, retire
                        # the old relation by lowering its weight before adding new.
                        if predicate in _identity_predicates:
                            try:
                                uid = self.get_entity_id("User")
                                if uid is not None:
                                    conn = self._conn()
                                    try:
                                        old_rels = conn.execute(
                                            "SELECT r.id, e.name FROM kg_relations r "
                                            "JOIN kg_entities e ON e.id = r.object_id "
                                            "WHERE r.subject_id=? AND LOWER(r.predicate)=? AND r.weight > 0.1",
                                            (uid, predicate),
                                        ).fetchall()
                                        for _rid, _old_name in old_rels:
                                            if _old_name.lower() != obj.lower():
                                                # Conflict: demote old relation weight
                                                conn.execute(
                                                    "UPDATE kg_relations SET weight = 0.05 WHERE id = ?",
                                                    (_rid,),
                                                )
                                        conn.commit()
                                    finally:
                                        conn.close()
                            except Exception:
                                pass
                        if self.add_relation("User", predicate, obj, source=source):
                            added += 1
                elif len(groups) >= 2:
                    subj = groups[0].strip()
                    obj = groups[1].strip()
                    if (subj and obj
                            and len(subj) > 1 and len(obj) > 1
                            and subj.lower() not in _STOPWORDS
                            and obj.lower() not in _STOPWORDS):
                        self.upsert_entity(subj)
                        self.upsert_entity(obj)
                        if self.add_relation(subj, predicate, obj, source=source):
                            added += 1
        return added


# ── Singleton ────────────────────────────────────────────────────────────────

def get_knowledge_graph() -> KnowledgeGraph:
    global _INSTANCE
    if _INSTANCE is None:
        with _LOCK:
            if _INSTANCE is None:
                try:
                    _INSTANCE = KnowledgeGraph()
                except Exception as e:
                    log.debug(f"[KG] init failed: {e}")
                    raise
    return _INSTANCE


def reset_knowledge_graph() -> None:
    global _INSTANCE
    with _LOCK:
        _INSTANCE = None
