"""Longitudinal memory benchmark: LongMemEval-style categories, run against ELI's real memory.

The scenarios are written for ELI (they are not the official LongMemEval questions) and cover the same
abilities: extraction, multi-session recall, temporal reasoning, knowledge updates and abstention, plus
ELI-specific checks for provenance, deletion, destructive merges and self-reinforcing recall.

Everything is deterministic and offline: a temporary database, no model, no vector index.

    python -m tools.eval.memory_bench            # print the table
    python -m tools.eval.memory_bench --json     # machine-readable
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable, Dict, List, Tuple

from eli.runtime.persistence_gate import should_store_memory_text as _GATE  # bound now, before a test can stub it

DAY = 86400.0
Result = Tuple[bool, str]


def _memory(tmp: Path):
    os.environ["ELI_TEST_MODE"] = "1"
    import eli.memory.vector_store as vs
    vs.get_vector_store = lambda: None  # type: ignore[assignment]
    from eli.memory.memory import Memory
    return Memory(db_path=tmp / "user.sqlite3")


def _said(mem, text: str, days_ago: float = 0.0, session: str = "s1") -> int:
    ts = time.time() - days_ago * DAY
    rid = mem.store_memory(text, source="user", metadata={"event_ts": ts})["id"]
    c = sqlite3.connect(mem.db_path)
    c.execute("update memories set ts = ?, timestamp = ?, event_ts = ? where id = ?", (ts, ts, ts, rid))
    c.commit()
    c.close()
    return rid


def _texts(hits) -> str:
    return " ".join(str(h.get("text") or h.get("content") or "") for h in hits).lower()


# ── scenarios: each returns (passed, note) ─────────────────────────────────────────────────────────

def extraction(mem) -> Result:
    _said(mem, "My sister Priya lives in Lisbon and teaches marine biology")
    _said(mem, "The garage code is 4471 and the spare key is under the blue pot")
    got = _texts(mem.recall_memory("where does my sister live", limit=5))
    return "lisbon" in got, got[:80]


def multi_session(mem) -> Result:
    _said(mem, "I started learning the cello last spring", days_ago=200, session="a")
    _said(mem, "My cello teacher moved my lessons to Thursdays", days_ago=20, session="b")
    got = _texts(mem.recall_memory("cello lessons", limit=6))
    return "thursdays" in got and "last spring" in got, got[:80]


def temporal_window(mem) -> Result:
    from eli.cognition.query_planner import parse_window
    from eli.memory.retrieval import retrieve_for_turn
    q = "what was I reading on the train last week"
    start, end = parse_window(q)
    _said(mem, "I am reading the Dune novels on the train", days_ago=(time.time() - (start + end) / 2) / DAY)
    _said(mem, "I am reading a biography of Ada Lovelace on the train", days_ago=60)
    res = retrieve_for_turn(mem, q, window=parse_window(q), use_cache=False, rerank=False)
    got = _texts(res.semantic_hits + res.conv_hits)
    return "dune" in got and "lovelace" not in got, got[:80]


def explicit_date(mem) -> Result:
    from eli.cognition.query_planner import parse_window
    from eli.memory.retrieval import retrieve_for_turn
    when = time.strftime("%Y-%m-%d", time.localtime(time.time() - 40 * DAY))
    _said(mem, "I signed the lease for the new flat today", days_ago=40)
    _said(mem, "I bought a second-hand bike today", days_ago=10)
    q = f"what did I do on {when}"
    res = retrieve_for_turn(mem, q, window=parse_window(q), use_cache=False, rerank=False)
    got = _texts(res.semantic_hits)
    return "lease" in got and "bike" not in got, got[:80]


def knowledge_update(mem) -> Result:
    _said(mem, "I work days at the warehouse most weeks", days_ago=90)
    _said(mem, "I work nights now, the warehouse changed my shift", days_ago=5)
    now = [c["value"] for c in mem.claims_current() if c["relation"] == "work_schedule"]
    history = [c["value"] for c in mem.claim_history("work_schedule")]
    return now == ["nights"] and history == ["days", "nights"], f"{now} {history}"


def abstention(mem) -> Result:
    _said(mem, "I like green tea with a slice of ginger")
    got = _texts(mem.recall_memory("what is my passport number", limit=5))
    return "passport" not in got and "ginger" not in got, got[:80]


def provenance(mem) -> Result:
    from eli.memory import policy
    mem.store_memory("The user probably enjoys jazz and lives in Oslo", source="assistant", kind="summary")
    c = sqlite3.connect(mem.db_path)
    origin = c.execute("select origin from memories order by id desc limit 1").fetchone()[0]
    c.close()
    claims = [c["value"] for c in mem.claims_current()]
    return (not policy.counts_as_evidence_about_user(origin)) and "Oslo" not in claims, f"origin={origin}"


def deletion(mem) -> Result:
    rid = _said(mem, "I moved to Berlin last month for the new job")
    c = mem._claims_conn()
    from eli.memory import claims
    n = claims.retract_from_memory(c, rid)
    c.commit()
    c.close()
    return n >= 1 and not [x for x in mem.claims_current() if x["relation"] == "lives_in"], f"retracted={n}"


def no_destructive_merge(mem) -> Result:
    _said(mem, "I write most of my tools in C++ these days")
    _said(mem, "I write most of my tools in C these days")
    mem.run_upkeep(force=True)
    c = sqlite3.connect(mem.db_path)
    n = c.execute("select count(*) from memories where text like 'I write most of my tools%'").fetchone()[0]
    c.close()
    return n == 2, f"rows={n}"


def no_self_reinforcement(mem) -> Result:
    rid = _said(mem, "My locker number at the gym is 212")
    mem.record_recall_outcome([rid], helped=False)
    c = sqlite3.connect(mem.db_path)
    before = c.execute("select weight, recall_count from memories where id = ?", (rid,)).fetchone()
    c.close()
    for _ in range(4):
        mem.recall_memory("gym locker number", limit=5)
    time.sleep(0.3)
    c = sqlite3.connect(mem.db_path)
    after = c.execute("select weight, recall_count from memories where id = ?", (rid,)).fetchone()
    c.close()
    return before == after, f"{before} -> {after}"


def chatter_is_not_durable(mem) -> Result:
    # The persistence gate is bypassed in test mode, so this scenario runs with the real one on.
    import eli.memory.memory as mm
    prior = mm._eli_should_store_memory_text
    mm._eli_should_store_memory_text = _GATE
    os.environ.pop("ELI_TEST_MODE", None)
    try:
        for t in ("haha", "lol that is funny", "hello there"):
            mem.store_memory(t, source="user")
    finally:
        os.environ["ELI_TEST_MODE"] = "1"
        mm._eli_should_store_memory_text = prior
    c = sqlite3.connect(mem.db_path)
    n = c.execute("select count(*) from memories where lower(text) in ('haha', 'lol that is funny', 'hello there')").fetchone()[0]
    c.close()
    return n == 0, f"rows={n}"


SCENARIOS: Dict[str, Callable] = {
    "extraction": extraction, "multi_session": multi_session, "temporal_window": temporal_window,
    "explicit_date": explicit_date, "knowledge_update": knowledge_update, "abstention": abstention,
    "provenance": provenance, "deletion": deletion, "no_destructive_merge": no_destructive_merge,
    "no_self_reinforcement": no_self_reinforcement, "chatter_is_not_durable": chatter_is_not_durable,
}


def run(names: List[str] | None = None) -> Dict[str, Dict[str, object]]:
    results: Dict[str, Dict[str, object]] = {}
    for name, fn in SCENARIOS.items():
        if names and name not in names:
            continue
        with tempfile.TemporaryDirectory() as d:
            try:
                ok, note = fn(_memory(Path(d)))
            except Exception as exc:
                ok, note = False, f"error: {exc}"
        results[name] = {"passed": bool(ok), "note": note}
    return results


def main(argv: List[str]) -> int:
    results = run()
    if "--json" in argv:
        print(json.dumps(results, indent=1))
    else:
        for name, r in results.items():
            print(f"{'PASS' if r['passed'] else 'FAIL'}  {name:26s} {str(r['note'])[:70]}")
        print(f"\n{sum(bool(r['passed']) for r in results.values())}/{len(results)} passed")
    return 0 if all(r["passed"] for r in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
