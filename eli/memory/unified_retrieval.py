"""Unified memory retrieval for orchestrator and agent bus.

Single authority: ``retrieve_for_turn`` owns semantic + conversation recall.
Orchestrator keyword/semantic stages consume this module instead of parallel
``recall_memory_query`` / FAISS paths that diverged in budget and verification.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from eli.memory.retrieval import TurnRetrievalResult, retrieve_for_turn
from eli.runtime.memory_provenance import is_explicit_memory_audit_query

_VERIFIED_MARKER = "Verified stored memories"


def split_verified_evidence_packet(text: str) -> Tuple[str, str]:
    """Split the verified-memory block from the rest of agent/bus context."""
    ctx = str(text or "").strip()
    if not ctx or _VERIFIED_MARKER not in ctx:
        return "", ctx
    start = ctx.find(_VERIFIED_MARKER)
    if start < 0:
        return "", ctx
    # Block runs until the next blank-line section header or end.
    rest = ctx[start:]
    end = rest.find("\n\n[")
    if end > 0:
        verified = rest[:end].strip()
        remainder = (ctx[:start] + rest[end:]).strip()
    else:
        verified = rest.strip()
        remainder = ctx[:start].strip()
    return verified, remainder


def _normalize_hit(hit: Dict[str, Any], *, default_source: str) -> Dict[str, Any]:
    text = (hit.get("text") or hit.get("content") or "").strip()
    src = str(hit.get("_source") or default_source or "fts").lower()
    score = float(hit.get("weight") or hit.get("importance") or hit.get("score") or 0.5)
    return {
        "source": "fts5" if src in ("fts", "like") else "vector" if src == "vector" else src,
        "score": score,
        "text": text,
        "meta": dict(hit),
        **_row_fields(hit),
    }


def _row_fields(row: Dict[str, Any]) -> Dict[str, Any]:
    """The fields ranking and dating read from the top level of a hit."""
    return {k: row[k] for k in ("id", "ts", "timestamp", "event_ts", "importance", "weight", "origin", "role")
            if row.get(k) is not None}


def orchestrator_retrieve(
    engine: Any,
    user_input: str,
    hyde_query: str,
    retrieval_plan: Dict[str, Any],
    *,
    session_id: str = "",
    user_id: str = "",
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], TurnRetrievalResult]:
    """Run unified recall; return (keyword_hits, semantic_hits, turn_result)."""
    mem = getattr(engine, "memory", None)
    empty = TurnRetrievalResult()
    if mem is None:
        return [], [], empty

    try:
        from eli.core.cognition_tunables import snapshot as _cog_snapshot
        _tn = _cog_snapshot()
    except Exception:
        _tn = {}

    def _plan(key: str, tunable: str, fallback: int) -> int:
        return int(retrieval_plan.get(key) or _tn.get(tunable, fallback))

    kw_limit = _plan("keyword_limit", "cog.orch_keyword_limit", 32)
    # 0 here (fast mode) does not mean "no semantic search": recall_memory runs the
    # vector search either way, and sequential_retrieve keeps those hits when the
    # turn's evidence comes back thin. So 0 falls back to the normal width.
    sem_limit = _plan("semantic_limit", "cog.orch_semantic_limit", 32)
    merge_limit = max(kw_limit, sem_limit, 8)
    verified_only = not is_explicit_memory_audit_query(user_input)

    need_keyword = bool(retrieval_plan.get("need_keyword", True))
    need_semantic = bool(retrieval_plan.get("need_semantic", True))
    if not need_keyword and not need_semantic:
        return [], [], empty

    tr = retrieve_for_turn(
        mem,
        str(hyde_query or user_input or "").strip(),
        user_id=user_id or str(getattr(engine, "user_id", "") or ""),
        session_id=session_id or str(getattr(engine, "session_id", "") or ""),
        semantic_limit=merge_limit,
        conv_limit=max(4, merge_limit // 2),
        recent_limit=_plan("recent_limit", "cog.mem_recent_turns", 30),
        summary_limit=_plan("summary_limit", "cog.mem_summaries_recall", 40),
        hop2_limit=_plan("hop2_limit", "cog.mem_hop2_recall", 20),
        merge_cap=_plan("merge_cap", "cog.mem_merge_cap", 40),
        enable_hop2=bool(retrieval_plan.get("enable_hop2", True)),
        rerank=True,
        use_cache=True,
        verified_only=verified_only,
        window=retrieval_plan.get("window"),
    )

    keyword_hits: List[Dict[str, Any]] = []
    semantic_hits: List[Dict[str, Any]] = []

    if need_keyword or need_semantic:
        for h in tr.semantic_hits:
            src = str(h.get("_source") or "fts").lower()
            norm = _normalize_hit(h, default_source=src)
            if not norm["text"]:
                continue
            if src in ("fts", "like") and need_keyword:
                keyword_hits.append(norm)
            elif need_semantic:
                semantic_hits.append(norm)

    # A period's turns go to the period log (format_period_log), whole and in order. Mixed in
    # here they were cut to the semantic limit and, in quick mode, thrown away with it.
    for h in ([] if tr.window_stats else tr.conv_hits):
        text = (h.get("content") or h.get("text") or "").strip()
        if not text:
            continue
        role = str(h.get("role") or "?")
        prefix = "User said: " if role == "user" else "Assistant said: "
        semantic_hits.append({
            "source": "conversation",
            "score": 0.85,
            "text": f"{prefix}{text}",
            "meta": dict(h),
            **_row_fields(h),
        })

    return keyword_hits[:kw_limit], semantic_hits[:sem_limit], tr


def format_verified_memory_block(
    tr: TurnRetrievalResult,
    *,
    shown: int = 6,
) -> str:
    """Format verified semantic hits the same way BusMemoryAgent does."""
    hits = list(getattr(tr, "semantic_hits", None) or [])
    if not hits:
        return ""
    lines: List[str] = []
    try:
        from eli.runtime.memory_provenance import format_grounding_memory_line
    except Exception:
        format_grounding_memory_line = None  # type: ignore
    import time as _time
    for h in hits[:shown]:
        if format_grounding_memory_line:
            line = format_grounding_memory_line(h)
            raw_ts = h.get("ts") or h.get("timestamp") or 0
            try:
                ts_str = _time.strftime(
                    "%Y-%m-%d %H:%M", _time.localtime(float(raw_ts)),
                ) if raw_ts else ""
            except Exception:
                ts_str = str(raw_ts or "")
            if ts_str:
                line = line.replace("] ", f"] [{ts_str}] ", 1)
            lines.append(line)
            continue
        txt = (h.get("text") or h.get("content") or "").strip()
        if txt:
            lines.append(f"  - {txt[:240]}")
    if not lines:
        return ""
    return (
        f"Verified stored memories ({len(hits)} found — "
        f"{VERIFIED_SCOPE_NOTE}):\n"
        + "\n".join(lines)
    )


# "ONLY from these rows" made the model deny the period log sitting right below it: Thursday's
# plays were in the prompt and the answer was "no record of any Spotify activity on Thursday".
VERIFIED_SCOPE_NOTE = ("ground user-specific claims only in these rows and in any dated period log "
                       "of what was said and done")

_STOP = frozenset("""a an the and or but of to in on at for with from by about as is are was were be been
do did does i me my we our you your it its this that these those all any what which who when where
how can could would should will just please tell give name list show exact past last day days
yesterday today week""".split())


def _terms(text: str) -> set:
    import re as _re
    return {w[:5] for w in _re.findall(r"[a-z0-9]{3,}", str(text or "").lower()) if w not in _STOP}


# What a question is about, by the actions that answer it. A question about music is answered
# by the media rows; listed first and on their own, a small model stops skipping one of five
# plays in a fifty-line log.
_FAMILIES = (
    (r"\b(?:songs?|music|tracks?|albums?|artists?|playlists?|listen\w*|play(?:ed|ing)?|spotify|youtube)\b",
     lambda a: "MEDIA" in a or a == "NOW_PLAYING"),
    (r"\b(?:apps?|applications?|programs?|open(?:ed)?|launch\w*|closed?)\b",
     lambda a: a.startswith(("OPEN_", "CLOSE_", "FOCUS_"))),
    (r"\b(?:search\w*|web|google\w*|looked?\s+up|news|websites?|sites?)\b",
     lambda a: a in ("WEB_SEARCH", "NEWS_FETCH", "OPEN_URL", "OPEN_BROWSER", "MORNING_REPORT")),
    (r"\b(?:timers?|alarms?|remind\w*|schedul\w*)\b",
     lambda a: a in ("SET_TIMER", "SET_ALARM", "SCHEDULE_TASK") or a.startswith("POMODORO")),
    (r"\b(?:files?|documents?|pdfs?|notes?|scripts?)\b",
     lambda a: a.startswith(("READ_", "WRITE_", "CREATE_", "ANALYZE_", "GENERATE_", "SUMMARIZE_", "FIX_"))
     or a in ("NEW_NOTE", "LIST_NOTES", "SEARCH_NOTES")),
)


def _asked_about(query: str):
    """Predicate over action names for what the question is about, or None."""
    import re as _re
    low = str(query or "").lower()
    tests = [t for pat, t in _FAMILIES if _re.search(pat, low)]
    return (lambda action: any(t(action) for t in tests)) if tests else None


_TITLE_FILLER = frozenset("the a an by of on and album song track".split())


def _tracks_in(rows, lines_fmt) -> str:
    """The distinct tracks named in media rows, worked out here: asked to list five plays from
    seven rows, a 35B model listed three and decided the now-playing ones didn't count.
    Reads the executor's own result formats: “query”, (Artist — Title), "Playing: Artist — Title"."""
    import re as _re
    seen: Dict[frozenset, List[Any]] = {}     # words -> [time, title, confirmed]
    for ts, text, _is_action, _name in rows:
        body = text.split(": ", 1)[-1]
        m = (_re.search(r"\(([^()]{2,80} — [^()]{1,80})\)", body)
             or _re.search(r"Playing:\s*(.+? — .+?)(?: — [\w/ ]+)?\.?\s*$", body))
        title, confirmed = (m.group(1).strip(), True) if m else ("", False)
        if not title:
            q = _re.search(r"“([^”]{2,80})”", body)
            if not q:
                continue
            title = "“" + q.group(1).strip() + "”"
            confirmed = not _re.search(r"couldn.t confirm|didn.t start|not start", body)
        key = frozenset(_re.findall(r"[a-z0-9]+", title.lower())) - _TITLE_FILLER
        if not key:
            continue
        entry = seen.get(key)
        if entry is None:
            seen[key] = [ts, title, confirmed]
            continue
        if confirmed and not entry[2]:
            entry[0], entry[2] = ts, True     # timed from when it actually played
        if title[0] != "“" and entry[1][0] == "“":
            entry[1] = title                  # the player's own "Artist — Title" over the search words
    if not seen:
        return ""
    items = "; ".join(f"{lines_fmt(ts)} {title}" + ("" if ok else " (search opened, playback not confirmed)")
                      for ts, title, ok in sorted(seen.values()))
    return f"Distinct tracks in those actions ({len(seen)}): {items}."


def format_period_log(tr: TurnRetrievalResult, query: str = "", *, max_chars: int = 6000) -> str:
    """The period a question asks about, in order: what the user said and what ELI ran.

    ELI's own prose replies are left out on purpose (a made-up reply would turn into history);
    each action line is the executor's own report, e.g. "Paused — spotify (Mos Def — Sunshine)".
    The actions the question is about come first; when the rest doesn't fit, each day keeps an
    equal share and the header says what was left out."""
    stats = getattr(tr, "window_stats", None) or {}
    if not stats:
        return ""
    import time as _time
    rows: List[Tuple[float, str, bool, str]] = []
    for t in getattr(tr, "conv_hits", None) or []:
        txt = " ".join(str(t.get("content") or t.get("text") or "").split())
        ts = t.get("timestamp") or t.get("ts")
        if txt and ts:
            rows.append((float(ts), f"You: {txt[:200]}", False, ""))
    for a in getattr(tr, "actions", None) or []:
        txt = " ".join(str(a.get("content") or "").split())[:140]
        failed = "" if str(a.get("outcome") or "ok") == "ok" else " (failed)"
        rows.append((float(a["ts"]), f"ELI ran {a['action']}{failed}: {txt}", True, str(a["action"])))
    if not rows:
        return ""

    def _line(r) -> str:
        return f"[{_time.strftime('%a %d %b %H:%M', _time.localtime(r[0]))}] {r[1]}"

    rows.sort(key=lambda r: r[0])
    lines = [_line(r) for r in rows]
    about = _asked_about(query)
    focus = [i for i, r in enumerate(rows) if about and r[2] and about(r[3])]
    keep: set = set()
    used = 0
    for i in focus:  # what the question is about is kept first, oldest first
        if used + len(lines[i]) + 1 > max_chars:
            break
        keep.add(i)
        used += len(lines[i]) + 1
    others = [i for i in range(len(rows)) if i not in keep]
    if used + sum(len(lines[i]) + 1 for i in others) <= max_chars:
        keep.update(others)
    else:
        # Each day gets an equal share of what is left, so a three-day question isn't answered
        # from the last afternoon alone; within a day, what matches the question, then actions.
        want = _terms(query)
        score = {i: len(want & _terms(rows[i][1])) + (1.0 if rows[i][2] else 0.0) for i in others}
        by_day: Dict[str, List[int]] = {}
        for i in others:
            by_day.setdefault(_time.strftime("%Y-%m-%d", _time.localtime(rows[i][0])), []).append(i)
        share = max(0, max_chars - used) // max(1, len(by_day))
        for idxs in by_day.values():
            spent = 0
            for i in sorted(idxs, key=lambda i: (-score[i], rows[i][0])):
                if spent + len(lines[i]) + 1 > share:
                    continue
                keep.add(i)
                spent += len(lines[i]) + 1
            used += spent
        for i in sorted(others, key=lambda i: (-score[i], -rows[i][0])):
            if i in keep or used + len(lines[i]) + 1 > max_chars:
                continue
            keep.add(i)
            used += len(lines[i]) + 1
    since = _time.strftime("%a %d %b %H:%M", _time.localtime(float(stats["since"])))
    until = _time.strftime("%a %d %b %H:%M", _time.localtime(float(stats["until"])))
    note = ""
    if len(keep) != len(rows):
        # What was left out, by day, so the answer can say what it is not showing.
        tally: Dict[str, Dict[str, Any]] = {}
        for ts, _text, is_action, name in rows:
            d = tally.setdefault(_time.strftime("%a %d %b", _time.localtime(ts)), {"said": 0, "ran": {}})
            if is_action:
                d["ran"][name] = d["ran"].get(name, 0) + 1
            else:
                d["said"] += 1
        days = "; ".join(
            f"{day}: {d['said']} messages" + (", ELI ran " + ", ".join(
                f"{a}×{n}" for a, n in sorted(d["ran"].items(), key=lambda kv: -kv[1])[:6]) if d["ran"] else "")
            for day, d in tally.items())
        note = (f" Showing {len(keep)} of {len(rows)} entries, the ones closest to the question; say so "
                f"if asked for everything. Whole period: {days}.")
    day_key = ""
    try:
        from eli.cognition.evidence_format import age_label
        firsts: Dict[str, float] = {}
        for r in rows:
            firsts.setdefault(_time.strftime("%a %d %b", _time.localtime(r[0])), r[0])
        if len(firsts) > 1:
            day_key = " Days: " + "; ".join(f"{d} = {age_label(t)}" for d, t in firsts.items()) + "."
    except Exception:
        day_key = ""
    head = (f"What happened in that period ({since} to {until}), from the conversation log and the "
            f"action ledger, which records every action ELI runs with what the executor reported. "
            f"This is the record of that period; answer from it and give the times.{day_key}{note}")
    focus_kept = [i for i in focus if i in keep]
    if focus_kept and len(focus_kept) < len(keep):
        rest = [i for i in sorted(keep) if i not in set(focus_kept)]
        multi_day = len({_time.strftime("%j", _time.localtime(rows[i][0])) for i in focus_kept}) > 1
        stamp = lambda ts: _time.strftime("%a %d %b %H:%M" if multi_day else "%H:%M", _time.localtime(ts))
        tracks = _tracks_in([rows[i] for i in focus_kept if "MEDIA" in rows[i][3] or rows[i][3] == "NOW_PLAYING"],
                            stamp)
        return (head + f"\nThe {len(focus_kept)} actions the question is about, in order (every one counts):\n"
                + "\n".join(lines[i] for i in focus_kept)
                + (f"\n{tracks}" if tracks else "")
                + "\nEverything else said and done in that period:\n"
                + "\n".join(lines[i] for i in rest))
    return head + "\n" + "\n".join(lines[i] for i in sorted(keep))
