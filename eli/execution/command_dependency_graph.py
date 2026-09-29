"""Dependency edges between an already-split command list — mirrors eli/coding/plan_graph.py's
decompose_dag() shape (same LLM-optional, fallback-to-independent philosophy, same eli.core.dag
validation), applied to MULTI_COMMAND instead of code subtasks."""
from __future__ import annotations

import json
import os
import re
from typing import Dict, List

from eli.utils.log import get_logger

log = get_logger(__name__)


def infer_dependencies(commands: List[str]) -> Dict[int, List[int]]:
    """index -> indices it depends on. Empty (all independent) unless the model identifies
    a real dependency and it validates as an acyclic graph. Never raises."""
    n = len(commands)
    if n < 2:
        return {}
    if os.environ.get("ELI_MULTI_COMMAND_DAG", "1").strip().lower() in ("0", "false", "no", "off"):
        return {}
    try:
        from eli.cognition.inference_broker import get_broker
        brk = get_broker()
        if brk is None or not getattr(brk, "gguf_ready", False):
            return {}
        numbered = "\n".join(f"{i}: {c}" for i, c in enumerate(commands))
        prompt = (
            "These commands will run for a user. Most are independent — only mark a "
            "dependency when one command's target clearly requires another to run first. "
            "When in doubt, independent.\n\n" + numbered +
            "\n\nRespond with ONLY JSON: {\"edges\": [[dependent_index, depends_on_index], "
            "...]}. Empty list if all independent."
        )
        raw = brk.infer(prompt, system="You identify real execution dependencies, nothing more.",
                        max_tokens=200) or ""
        m = re.search(r"\{[\s\S]+\}", raw)
        if not m:
            return {}
        edges = json.loads(m.group(0)).get("edges") or []

        deps: Dict[int, List[int]] = {}
        for pair in edges:
            if not (isinstance(pair, (list, tuple)) and len(pair) == 2):
                continue
            dep, on = int(pair[0]), int(pair[1])
            if 0 <= dep < n and 0 <= on < n and dep != on:
                deps.setdefault(dep, []).append(on)
        if not deps:
            return {}

        from eli.core.dag import build_dag
        g = build_dag({str(i): [str(d) for d in deps.get(i, [])] for i in range(n)})
        g.topological_layers()   # raises DAGCycleError on a cycle
        return deps
    except Exception as exc:
        log.debug(f"[MULTI_COMMAND] dependency inference failed, treating as independent: {exc}")
        return {}
