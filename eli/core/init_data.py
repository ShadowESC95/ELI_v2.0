"""First-run data initialiser — build ELI's FULL database architecture up front.

Goal: a fresh install is *complete and runnable at full efficiency* with no manual
fix-up, while staying a true blank slate — **every table across every store exists,
but no personal memories/profile/history are written**. Running ELI then only adds
the user's own data on top.

This is deliberately idempotent (every creator uses ``CREATE TABLE IF NOT EXISTS``)
and side-effect-free: it constructs the schema owners and closes them; it never
inserts conversation turns, memories, habits, or profile facts. Safe to call from
the installer AND on every boot.

Stores covered (see eli/core/paths.py for locations):
  • user.sqlite3         — memory, conversations, habits, patterns, user_model,
                           observations, session_summaries, knowledge-graph
  • system_index.sqlite3 — desktop apps / executables / recent files / user dirs
  • coding_memory.sqlite3 — code bug-fix memory
  • agent.sqlite3        — agent dispatch + metrics telemetry

Usage:
    python -m eli.core.init_data            # build everything, print a report
    from eli.core.init_data import init_all_data
    init_all_data()
"""

from __future__ import annotations

from typing import List, Tuple


def init_all_data(verbose: bool = False) -> List[Tuple[str, bool, str]]:
    """Create every store + table with no personal data. Returns per-store results
    as (name, ok, detail). Never raises — a store that can't init is reported, not
    fatal, so the installer/boot continues."""
    results: List[Tuple[str, bool, str]] = []

    def _step(name: str, fn) -> None:
        try:
            detail = fn() or ""
            results.append((name, True, str(detail)))
        except Exception as e:  # pragma: no cover - defensive
            results.append((name, False, f"{type(e).__name__}: {e}"))

    # 0) Data directories (idempotent mkdir via platformdirs/paths).
    def _paths():
        from eli.core.paths import get_paths
        get_paths()
        return "data/config/cache/models dirs ready"
    _step("paths", _paths)

    # 1) user.sqlite3 — core memory schema (memories, conversations, habits, ...).
    def _memory():
        from eli.memory import get_memory
        get_memory()
        return "memory schema"
    _step("user.memory", _memory)

    # 2) user.sqlite3 — profile/User-Model schema (user_patterns, user_model,
    #    observations, session_summaries). Tables only; no profile rows written.
    def _profile():
        from eli.runtime.profile_extractor import ensure_profile_tables
        ensure_profile_tables()
        return "user_patterns, user_model, observations, session_summaries"
    _step("user.profile", _profile)

    # 3) user.sqlite3 — knowledge-graph schema (kg_entities/*, kg_relations).
    def _kg():
        from eli.memory.knowledge_graph import KnowledgeGraph
        KnowledgeGraph()
        return "kg_entities, kg_relations"
    _step("user.knowledge_graph", _kg)

    # 4) system_index.sqlite3 — desktop apps / executables / recent files / dirs.
    #    Unlike the personal stores, this one is POPULATED on a fresh install:
    #    it indexes the machine's own software inventory (installed apps, $PATH
    #    executables, standard user directories) so "open <app>" / path lookups
    #    work out of the box — that is regenerable ENVIRONMENT data, not personal
    #    memory/profile/history, so it's consistent with the blank-slate promise.
    #    Scanned only when empty: idempotent, avoids re-scanning on every call,
    #    and self-heals an existing install whose index was left schema-only.
    def _sysindex():
        from eli.memory.system_index import SystemIndex
        idx = SystemIndex()  # ensures schema
        try:
            _n = int(idx.conn.execute("SELECT COUNT(*) FROM executables").fetchone()[0] or 0)
        except Exception:
            _n = -1
        if _n == 0:
            try:
                idx.refresh()
                return "desktop_apps, executables, recent_files, user_dirs (scanned)"
            except Exception as _e:
                return f"schema ready; inventory scan deferred ({type(_e).__name__})"
        return "desktop_apps, executables, recent_files, user_dirs"
    _step("system_index", _sysindex)

    # 5) coding_memory.sqlite3 — code bug-fix memory.
    def _coding():
        from eli.coding.bug_memory import BugMemory
        BugMemory()
        return "coding_bug_fixes"
    _step("coding_memory", _coding)

    # 6) agent.sqlite3 — agent dispatch + metrics telemetry.
    def _agent():
        from eli.cognition.agent_bus import ensure_agent_tables
        ensure_agent_tables()
        return "agent_dispatches, agent_metrics"
    _step("agent", _agent)

    # 7) user.sqlite3 — news cache schema (news_articles + FTS) and reflections.
    #    Constructing NewsFetcher only ensures the schema; it does NOT fetch (no
    #    network), so a fresh install carries the table up front instead of waiting
    #    for the first news query to lazily create it.
    def _news():
        from eli.tools.news.news_fetcher import NewsFetcher
        NewsFetcher()  # __init__ → _ensure_db(): news_articles, news_fts, triggers
        from eli.tools.news import news_synthesis as _ns
        _ns._conn().close()  # creates news_reflections
        return "news_articles, news_fts, news_reflections"
    _step("user.news", _news)

    # 8) user.sqlite3 — runtime-events evidence ledger (telemetry signatures used by
    #    autonomy/goal-genesis). Schema only; no events written.
    def _events():
        from eli.runtime.evidence_ledger import _connect, ensure_schema
        conn = _connect()
        try:
            ensure_schema(conn)
            conn.commit()
        finally:
            conn.close()
        return "runtime_events"
    _step("user.runtime_events", _events)

    if verbose:
        for name, ok, detail in results:
            mark = "OK " if ok else "ERR"
            print(f"  [{mark}] {name:24s} {detail}")
    return results


_BOOTSTRAPPED = False


def bootstrap_once(verbose: bool = False) -> None:
    """Idempotent, run-at-most-once-per-process initialiser for the app entry
    points. The installer calls ``init_data`` directly, but a launch that did NOT
    go through ``install.sh`` (a copied tree, the prebuilt portable bundle, or a
    bare ``eli`` console-script run) would otherwise never build the full schema
    or populate the machine inventory. Calling this at boot makes "complete and
    runnable on first launch" true regardless of how ELI was started, and
    self-heals an install whose index was left schema-only. Never raises."""
    global _BOOTSTRAPPED
    if _BOOTSTRAPPED:
        return
    _BOOTSTRAPPED = True
    try:
        init_all_data(verbose=verbose)
    except Exception:  # pragma: no cover - boot must never fail on this
        pass


def main() -> int:
    print("[..] Initialising ELI's full database architecture (blank slate)...")
    results = init_all_data(verbose=True)
    failed = [r for r in results if not r[1]]
    if failed:
        print(f"[WARN] {len(failed)} store(s) deferred to first launch: "
              + ", ".join(n for n, _, _ in failed))
        return 0  # non-fatal: stores self-build lazily on first use
    print(f"[OK] All {len(results)} architecture steps ready — no personal data written.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
