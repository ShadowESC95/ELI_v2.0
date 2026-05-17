"""
eli/cognition/working_memory.py
======================================
Session-level Working Memory for ELI.

JARVIS analogy: the "active dossier" J.A.R.V.I.S. maintains for the current
engagement — facts, decisions, and context that need to survive context-window
trimming but are too transient to warrant permanent storage.

Architecture
-----------
WorkingMemory sits between the AgentBus and the system-prompt builder.
It holds a small, ordered set of "pinned facts" — items flagged as
important enough to appear in every remaining turn of the session.

Pinning triggers (auto):
  - Memory with importance >= 0.75 retrieved on current turn
  - User explicitly uses "remember", "note that", "keep in mind"
  - High-confidence structured facts (identity, preference, name)
  - KG entities extracted this session

Pinning triggers (manual):
  - External code calls wm.pin(text, source)

Eviction:
  - LRU by last-referenced turn (keeps the buffer small)
  - Hard cap: MAX_PINS items
  - Items older than MAX_AGE_TURNS turns without a hit are dropped

Context injection:
  - wm.context_block() → compact string for system prompt injection
  - wm.to_memory_store() → writes pinned facts to SQLite on session end
"""

from __future__ import annotations

import re
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional


MAX_PINS = 20          # hard cap on pinned items
MAX_AGE_TURNS = 40     # evict if not referenced for this many turns
IMPORTANCE_THRESHOLD = 0.65  # auto-pin memories above this score


class _PinnedFact:
    __slots__ = ("text", "source", "pinned_at_turn", "last_hit_turn",
                 "hit_count", "importance", "ts")

    def __init__(self, text: str, source: str, turn: int,
                 importance: float = 0.5):
        self.text = text
        self.source = source
        self.pinned_at_turn = turn
        self.last_hit_turn = turn
        self.hit_count = 1
        self.importance = importance
        self.ts = time.time()

    def touch(self, turn: int) -> None:
        self.last_hit_turn = turn
        self.hit_count += 1


class WorkingMemory:
    """
    Session-scoped working memory.  One instance per CognitiveEngine session.

    Usage
    -----
        wm = WorkingMemory()
                try:
                    from eli.kernel.state import get_user_name as _eli_get_user_name
                    _eli_name = (_eli_get_user_name() or "").strip()
                    if _eli_name:
                        wm.pin(f"User's name is {_eli_name}", source="identity")
                except Exception:
                    pass
        wm.absorb_memory_hits(memory_hits, current_turn=5)
        system += wm.context_block()
    """

    def __init__(self):
        self._facts: OrderedDict[str, _PinnedFact] = OrderedDict()
        self._turn: int = 0

    # ── Public API ────────────────────────────────────────────────────────────

    def advance_turn(self) -> None:
        """Call once per request before processing."""
        self._turn += 1
        self._evict_stale()

    def pin(self, text: str, source: str = "auto",
            importance: float = 0.5) -> bool:
        """
        Pin a fact.  Returns True if newly added, False if already present
        (which still refreshes the hit counter).
        """
        key = self._key(text)
        if key in self._facts:
            self._facts[key].touch(self._turn)
            self._facts[key].importance = max(
                self._facts[key].importance, importance)
            return False

        # Enforce cap: evict lowest-importance oldest fact first
        if len(self._facts) >= MAX_PINS:
            self._evict_one()

        self._facts[key] = _PinnedFact(text, source, self._turn, importance)
        return True

    def absorb_memory_hits(
        self, hits: List[Dict[str, Any]], current_turn: Optional[int] = None
    ) -> int:
        """
        Auto-pin high-importance memories from a recall batch.
        Returns the number of newly pinned facts.
        """
        if current_turn is not None:
            self._turn = current_turn
        pinned = 0
        for hit in hits or []:
            imp = float(hit.get("importance", 0.5))
            text = (hit.get("text") or hit.get("content") or "").strip()
            if not text:
                continue
            if imp >= IMPORTANCE_THRESHOLD:
                if self.pin(text, source="memory_recall", importance=imp):
                    pinned += 1
        return pinned

    def absorb_user_message(self, user_input: str) -> None:
        """
        Scan user message for explicit pin triggers and extract
        the fact to be pinned.
        """
        low = (user_input or "").lower().strip()
        # Detect: "remember that X", "note that X", "keep in mind X", etc.
        _triggers = (
            r"(?:please\s+)?remember\s+(?:that\s+)?(.+)",
            r"(?:please\s+)?note\s+that\s+(.+)",
            r"keep\s+in\s+mind\s+(?:that\s+)?(.+)",
            r"don'?t\s+forget\s+(?:that\s+)?(.+)",
            r"make\s+a\s+note\s+(?:that\s+)?(.+)",
            r"store\s+this[:\s]+(.+)",
            r"save\s+this[:\s]+(.+)",
        )
        for pat in _triggers:
            m = re.search(pat, low, re.IGNORECASE)
            if m:
                fact = m.group(1).strip().rstrip(".!?,")
                if len(fact) >= 8:
                    self.pin(fact, source="user_explicit", importance=0.95)
                return  # only process first trigger per message

        # Identity extraction: "my name is X", "I am X", "I work at X"
        _identity = (
            r"my name is (\w[\w\s\-]{1,40})",
            r"i'?m\s+(\w[\w\s\-]{2,30})(?:\s+and|\s*$)",
            r"i\s+work\s+(?:at|for|as)\s+(.+?)(?:\s+and|\.|,|$)",
            r"i\s+prefer\s+(.+?)(?:\s+and|\.|,|$)",
            r"i\s+like\s+(.+?)(?:\s+and|\.|,|$)",
            r"call\s+me\s+(\w[\w\s\-]{1,30})",
        )
        for pat in _identity:
            m = re.search(pat, low, re.IGNORECASE)
            if m:
                raw = m.group(1).strip().rstrip(".!?,")
                if len(raw) >= 2:
                    full = f"User identity: {m.group(0).strip()}"
                    self.pin(full, source="identity_extract", importance=0.85)

    def context_block(self) -> str:
        """
        Return a compact string block for injection into the system prompt.
        Empty string if nothing is pinned.
        """
        if not self._facts:
            return ""
        lines = ["WORKING MEMORY (pinned facts for this session):"]
        for fact in sorted(self._facts.values(),
                           key=lambda f: f.importance, reverse=True):
            src = f"[{fact.source}]" if fact.source != "auto" else ""
            lines.append(f"  • {fact.text} {src}".rstrip())
        return "\n".join(lines)

    def flush_to_memory(self, memory_store: Any) -> int:
        """
        Persist high-importance pinned facts to permanent memory on session end.
        Returns number of facts persisted.
        """
        saved = 0
        for fact in self._facts.values():
            if fact.importance >= 0.8 and fact.hit_count >= 2:
                try:
                    memory_store.store_memory(
                        fact.text,
                        tags=["working_memory", fact.source, "session_pin"],
                        source="working_memory",
                        kind="fact",
                        importance=fact.importance,
                    )
                    saved += 1
                except Exception:
                    pass
        return saved

    def summary(self) -> Dict[str, Any]:
        return {
            "turn": self._turn,
            "pinned_count": len(self._facts),
            "facts": [
                {"text": f.text[:80], "importance": f.importance,
                 "source": f.source, "hits": f.hit_count}
                for f in sorted(self._facts.values(),
                                key=lambda x: x.importance, reverse=True)
            ],
        }

    # ── Internal ──────────────────────────────────────────────────────────────

    @staticmethod
    def _key(text: str) -> str:
        """Normalise text to a dedup key."""
        return re.sub(r"\s+", " ", (text or "").lower().strip())[:120]

    def _evict_stale(self) -> None:
        """Remove facts not referenced in the last MAX_AGE_TURNS turns."""
        stale = [
            k for k, f in self._facts.items()
            if (self._turn - f.last_hit_turn) > MAX_AGE_TURNS
        ]
        for k in stale:
            del self._facts[k]

    def _evict_one(self) -> None:
        """Evict the lowest-salience (importance × recency) fact."""
        if not self._facts:
            return
        worst = min(
            self._facts.keys(),
            key=lambda k: (
                self._facts[k].importance * 0.6
                + (self._turn - self._facts[k].last_hit_turn) * -0.01
            ),
        )
        del self._facts[worst]
