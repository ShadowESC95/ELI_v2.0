"""
eli/cognition/engagement_tracker.py
==========================================
Engagement / salience tracker — JARVIS-style topic-depth awareness.

Tracks how intellectually engaged the current session is and provides
a hint to the reasoning mode selector so ELI automatically escalates
from quick → chain_of_thought → tree_of_thoughts as the conversation
deepens, without the user having to request it.

Engagement signals
------------------
  +high    multi-sentence questions, technical vocabulary, follow-ups
  +medium  questions with "why", "how", "explain", "difference between"
  +low     single-word commands, greetings, simple lookups
  -low     user is satisfied (acks, "thanks", "got it")

The tracker maintains a rolling window of the last N turns and computes
a session_depth score (0.0–1.0).  CognitiveEngine can call:

    tracker.record_turn(user_input, response_score)
    hint = tracker.reasoning_mode_hint()   # "quick" | "chain_of_thought" | "tree_of_thoughts"
    summary = tracker.session_narrative()  # compact "what we've been working on" string
"""

from __future__ import annotations

import re
import time
from collections import deque
from typing import Deque, Dict, List, Optional, Tuple


_DEEP_KEYWORDS = frozenset({
    "explain", "why", "how does", "difference", "compare", "analyse", "analyze",
    "elaborate", "detail", "in depth", "step by step", "walk me through",
    "architecture", "design", "algorithm", "implement", "build", "create",
    "research", "investigation", "theorem", "proof", "hypothesis",
    "philosophy", "ethics", "consequences", "implications", "trade-off",
    "trade off", "pros and cons", "breakdown", "comprehensive", "thorough",
})

_ACK_PHRASES = frozenset({
    "ok", "okay", "thanks", "thank you", "got it", "understood", "makes sense",
    "cool", "great", "nice", "perfect", "cheers", "alright", "sounds good",
    "sure", "yep", "yes", "no", "nope", "right", "fair",
})

_TECH_PATTERN = re.compile(
    r"\b(?:api|sql|json|http|async|thread|memory|database|model|vector|"
    r"inference|llm|neural|gpu|cpu|pipeline|function|class|module|import|"
    r"algorithm|recursive|complexity|binary|matrix|gradient|embedding)\b",
    re.I,
)


class _TurnRecord:
    __slots__ = ("query", "depth", "confidence", "ts", "topics")

    def __init__(self, query: str, depth: float, confidence: float, topics: List[str]):
        self.query = query[:120]
        self.depth = depth
        self.confidence = confidence
        self.ts = time.time()
        self.topics = topics[:6]


class EngagementTracker:
    """
    Lightweight session engagement monitor.

    Usage in CognitiveEngine
    ------------------------
        # at start of process():
        self._engagement.record_turn(user_input)

        # before choosing reasoning mode:
        hint = self._engagement.reasoning_mode_hint()

        # in system prompt builder:
        narrative = self._engagement.session_narrative()
    """

    WINDOW = 12    # rolling window of recent turns

    def __init__(self):
        self._turns: Deque[_TurnRecord] = deque(maxlen=self.WINDOW)
        self._topic_freq: Dict[str, int] = {}
        self._session_start = time.time()

    # ── Public API ────────────────────────────────────────────────────────────

    def record_turn(self, user_input: str, response_confidence: float = 0.6) -> float:
        """
        Record a user turn and return its depth score (0.0–1.0).
        """
        depth, topics = self._score_depth(user_input)
        for t in topics:
            self._topic_freq[t] = self._topic_freq.get(t, 0) + 1
        self._turns.append(_TurnRecord(user_input, depth, response_confidence, topics))
        return depth

    def session_depth(self) -> float:
        """
        Recency-weighted depth score for the session window.

        The most recent turn carries 40 % of the weight; the remainder is
        spread linearly across older turns.  This means a single substantive
        query immediately raises the score, rather than being diluted by
        earlier phatic turns.
        """
        if not self._turns:
            return 0.0
        turns = list(self._turns)
        n = len(turns)
        if n == 1:
            return turns[0].depth

        # Build a linearly-increasing weight vector, then double the last one
        # so the current turn always gets at least 40 % share.
        weights = list(range(1, n + 1))       # [1, 2, 3, …, n]
        weights[-1] = weights[-1] * 2         # current turn gets 2× its linear weight
        total = sum(weights)
        return sum(t.depth * w for t, w in zip(turns, weights)) / total

    def reasoning_mode_hint(self) -> str:
        """
        Returns a recommended reasoning mode based on session depth.

        Uses the recency-weighted session_depth() so a single substantive
        query in an otherwise phatic session still triggers escalation.

        Thresholds (tunable):
          depth < 0.35  → "quick"
          depth < 0.60  → "chain_of_thought"
          depth < 0.80  → "self_consistency"
          depth >= 0.80 → "tree_of_thoughts"

        Additionally, if the *current* turn depth alone crosses a threshold,
        that floor is applied — ensuring even the very first deep query in a
        session escalates reasoning mode immediately.

        Note: this is only a HINT.  CognitiveEngine may override it.
        """
        d = self.session_depth()

        # Current-turn floor: don't let a deep present query be suppressed by
        # a shallow history.
        if self._turns:
            current_depth = self._turns[-1].depth
            # Apply a floor: current turn depth contributes at least 50 % to
            # the effective depth used for mode selection.
            d = max(d, current_depth * 0.5)

        if d >= 0.80:
            return "tree_of_thoughts"
        if d >= 0.60:
            return "self_consistency"
        if d >= 0.35:
            return "chain_of_thought"
        return "quick"

    def update_confidence(self, confidence: float) -> None:
        """
        Back-fill the actual response confidence into the most recent turn.
        Call this after _finalize_chat_result() has a real score.
        """
        if self._turns:
            self._turns[-1].confidence = float(confidence)

    def top_topics(self, n: int = 5) -> List[str]:
        """Return the most-discussed topics this session."""
        return sorted(self._topic_freq, key=self._topic_freq.get, reverse=True)[:n]

    def session_narrative(self) -> str:
        """
        Compact 1–2 sentence summary of what the session has been about.
        Suitable for injection into the system prompt as a "session context" line.
        """
        if not self._turns:
            return ""
        topics = self.top_topics(4)
        depth = self.session_depth()
        n_turns = len(self._turns)

        depth_label = "deep" if depth >= 0.6 else "moderate" if depth >= 0.35 else "light"
        if topics:
            topic_str = ", ".join(topics)
            return (
                f"Session context: {n_turns} exchanges, {depth_label} engagement. "
                f"Active topics: {topic_str}."
            )
        return f"Session context: {n_turns} exchanges, {depth_label} engagement."

    # ── Internal ──────────────────────────────────────────────────────────────

    def _score_depth(self, text: str) -> Tuple[float, List[str]]:
        """Score query depth and extract topic keywords."""
        low = (text or "").lower().strip()
        words = low.split()
        n = len(words)
        topics: List[str] = []

        if n == 0:
            return 0.0, []

        score = 0.0

        # Length signal
        if n >= 30:
            score += 0.30
        elif n >= 15:
            score += 0.20
        elif n >= 6:
            score += 0.10

        # Ack / short phrase → reduce depth
        if n <= 3 and low in _ACK_PHRASES:
            return 0.05, []

        # Deep keyword hit
        deep_hits = sum(1 for kw in _DEEP_KEYWORDS if kw in low)
        score += min(0.35, deep_hits * 0.12)

        # Technical vocabulary
        tech_hits = len(_TECH_PATTERN.findall(low))
        score += min(0.20, tech_hits * 0.08)
        if tech_hits:
            topics += [m for m in _TECH_PATTERN.findall(low)][:4]

        # Question complexity
        if "?" in text:
            score += 0.05
        if text.count("?") >= 2:
            score += 0.05

        # Follow-up signal ("also", "and", "but", "what about", "how about")
        if any(p in low for p in ("what about", "how about", "also,", " but ", " and ")):
            score += 0.08

        # Topic extraction (nouns/concepts from long words)
        for w in words:
            if (len(w) >= 6 and w.isalpha()
                    and w not in {"please", "should", "would", "could", "really",
                                  "actual", "really", "might", "there", "their",
                                  "before", "after", "about", "which", "where"}):
                topics.append(w)

        return min(1.0, max(0.0, score)), list(dict.fromkeys(topics))[:6]
