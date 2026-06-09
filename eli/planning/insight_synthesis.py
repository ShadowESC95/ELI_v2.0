"""Cached, background-synthesised reflection insight.

The reflection + proactive bus agents must surface SYNTHESISED, actionable insight — not a raw
dump of recent observations. LLM synthesis on every turn would add latency, so it is computed in
the BACKGROUND (proactive daemon tick), gated on a resident model + throttled to once per window,
and cached to disk; the agents read the cache for free.

100% local (inference broker / GGUF), model-agnostic. Never raises into callers.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

_MIN_REFRESH_INTERVAL = 1800.0  # 30 min — don't re-synthesise more often than this


def _cache_path() -> Path:
    from eli.core.paths import get_paths
    return Path(get_paths().artifacts_dir) / "runtime" / "reflection_insight.json"


def get_cached_insight() -> str:
    """Return the most recently synthesised insight (fast, no LLM). '' if none."""
    try:
        p = _cache_path()
        if p.exists():
            d = json.loads(p.read_text(encoding="utf-8"))
            return str(d.get("insight") or "").strip()
    except Exception:
        pass
    return ""


def refresh_insight(memory: Any = None, force: bool = False) -> str:
    """LLM-synthesise recent observations + session summaries into 1-2 concrete, actionable
    insight sentences; cache + return. Throttled to _MIN_REFRESH_INTERVAL and gated on a
    resident model so the background daemon never thrashes the GGUF. Never raises."""
    try:
        p = _cache_path()
        if not force and p.exists():
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                if time.time() - float(d.get("ts", 0)) < _MIN_REFRESH_INTERVAL:
                    return str(d.get("insight") or "")
            except Exception:
                pass
        # Yield to the user: never run a background synthesis while a foreground request is (or
        # was just) generating — on a slow/CPU-offloaded model this insight call otherwise wedges
        # itself between the user's turns / a document's sections.
        if not force:
            try:
                from eli.cognition.inference_broker import foreground_recently_active
                if foreground_recently_active():
                    return get_cached_insight()
            except Exception:
                pass
        # Gate: only synthesise with an already-resident model (never cold-load).
        try:
            import eli.cognition.gguf_inference as _gi
            if not getattr(_gi, "is_loaded", lambda: False)():
                return get_cached_insight()
        except Exception:
            return get_cached_insight()
        from eli.cognition.inference_broker import get_inference_broker
        broker = get_inference_broker()
        if broker is None or not getattr(broker, "gguf_ready", False):
            return get_cached_insight()

        if memory is None:
            from eli.memory import get_memory
            memory = get_memory()
        try:
            obs = [str((r or {}).get("observation") or (r or {}).get("content") or "").strip()
                   for r in (memory.get_recent_observations(limit=10) or [])]
        except Exception:
            obs = []
        obs = [o for o in obs if o][:10]
        try:
            sums = [str((r or {}).get("summary") or "").strip()
                    for r in (memory.get_session_summaries(limit=3) or [])]
        except Exception:
            sums = []
        sums = [s for s in sums if s][:3]
        if not obs and not sums:
            return ""

        material = "OBSERVATIONS:\n" + "\n".join(f"- {o[:200]}" for o in obs)
        if sums:
            material += "\n\nRECENT SESSIONS:\n" + "\n".join(f"- {s[:200]}" for s in sums)
        system = (
            "You are ELI reflecting on your OWN recent activity and how the user works. "
            "Synthesise 1-2 SHORT, concrete, actionable insights — a pattern worth noting or "
            "something to do differently. No preamble, no raw event list, invent nothing."
        )
        out = (broker.infer(
            "From the material below, give your synthesised reflection.\n\n" + material,
            system=system, max_tokens=160, temperature=0.4, background=True) or "").strip()
        if len(out) < 15:
            return get_cached_insight()
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"insight": out, "ts": time.time()}, indent=2),
                         encoding="utf-8")
        except Exception:
            pass
        return out
    except Exception:
        return get_cached_insight()
