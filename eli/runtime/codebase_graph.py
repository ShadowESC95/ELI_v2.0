"""Codebase self-graph — ELI's live, grounded model of how its OWN code connects.

Nodes are ELI's canonical subsystems (router, executor, engine, agent bus, GGUF
inference, DAG orchestrator, memory, vector store, GUI, plugins, perception,
planning, world, netguard). **Edges are the REAL import relationships between
them, parsed from source with `ast`** — an edge ``A -> B`` means code in A imports
(depends on / calls into) code in B. So the graph reflects what the code actually
does, not a hand-drawn diagram that rots as the tree grows: add a module and the
edges simply appear.

ELI answers questions about its own architecture from this — see the
``CODEBASE_GRAPH`` action and ``AwarenessState``. Everything is read fresh from
disk and cached; a missing path yields an empty node, never a crash.
"""
from __future__ import annotations

import ast
import logging
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

log = logging.getLogger(__name__)

# component -> (path relative to repo root, one-line role). Paths are verified-real
# (a file or a package dir). Order matters only for readability; matching picks the
# LONGEST path prefix so eli/memory/vector_store.py resolves to vector_store, not memory.
_COMPONENTS: Dict[str, Tuple[str, str]] = {
    "router":         ("eli/execution/router_enhanced.py",
                       "Maps user input to an action + args (regex-first priority pipeline, LLM-intent fallback)."),
    "executor":       ("eli/execution/executor_enhanced.py",
                       "Runs an action and produces the side effects / grounded result."),
    "engine":         ("eli/kernel/engine.py",
                       "CognitiveEngine.process() — the spine; runs the 12-stage cognitive pipeline."),
    "agent_bus":      ("eli/cognition/agent_bus.py",
                       "Dispatches specialist agents over a dependency DAG and aggregates grounding."),
    "gguf_inference": ("eli/cognition/gguf_inference.py",
                       "Loads the GGUF model and runs local inference (model-agnostic)."),
    "orchestrator":   ("eli/core/dag.py",
                       "Parallel / retry / fallback DAG execution engine the agents run on."),
    "memory":         ("eli/memory",
                       "SQLite + FTS5 + knowledge graph + working memory."),
    "vector_store":   ("eli/memory/vector_store.py",
                       "FAISS vector index for semantic recall."),
    "gui":            ("eli/gui",
                       "PySide6 desktop app, panels, first-boot wizard, animated face."),
    "plugins":        ("eli/plugins",
                       "Plugin manager + bundled plugins."),
    "perception":     ("eli/perception",
                       "Vision, STT, TTS, wake word, voice/tone, OS control."),
    "planning":       ("eli/planning",
                       "Proactive daemon, habit scheduler, goal / proposal queues."),
    "world":          ("eli/world",
                       "EliWorld event bus, avatar, symbolic rooms."),
    "netguard":       ("eli/core/netguard.py",
                       "Process-wide offline-by-default socket failsafe."),
}


def _repo_root() -> Path:
    try:
        from eli.core.paths import get_paths
        return Path(get_paths().project_root)
    except Exception:
        return Path(__file__).resolve().parents[2]


def _dotted(rel_path: str) -> str:
    """'eli/cognition/agent_bus.py' -> 'eli.cognition.agent_bus'; a dir -> its package."""
    p = rel_path[:-3] if rel_path.endswith(".py") else rel_path
    return p.replace("/", ".")


def _component_of(module: str) -> Optional[str]:
    """Map a dotted module to a component by LONGEST matching path prefix."""
    best: Optional[str] = None
    best_len = -1
    for name, (rel, _role) in _COMPONENTS.items():
        base = _dotted(rel)
        if module == base or module.startswith(base + "."):
            if len(base) > best_len:
                best, best_len = name, len(base)
    return best


def _iter_py_files(root: Path, rel: str) -> List[Path]:
    target = root / rel
    if target.is_file():
        return [target]
    if target.is_dir():
        return sorted(p for p in target.rglob("*.py") if "__pycache__" not in p.parts)
    return []


def _resolve_relative(file_pkg: str, level: int, module: Optional[str]) -> Optional[str]:
    """Resolve a relative import ('from ..kernel import x') to an absolute dotted module."""
    if level <= 0:
        return module
    parts = file_pkg.split(".")
    if level - 1 > len(parts):
        return module
    base = parts[: len(parts) - (level - 1)]
    if module:
        base = base + module.split(".")
    return ".".join(base) if base else module


def _imports_of(pyfile: Path, root: Path) -> Set[str]:
    """Absolute dotted modules imported by one file (absolute + resolved-relative). Never raises."""
    out: Set[str] = set()
    try:
        src = pyfile.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(src, filename=str(pyfile))
    except Exception:
        log.debug("codebase_graph: parse failed for %s", pyfile, exc_info=True)
        return out
    try:
        rel = pyfile.relative_to(root).with_suffix("")
        file_pkg = ".".join(rel.parts[:-1])  # package the file lives in
    except Exception:
        file_pkg = ""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            resolved = _resolve_relative(file_pkg, node.level or 0, node.module)
            if resolved:
                out.add(resolved)
    return out


@lru_cache(maxsize=1)
def build_graph() -> Dict[str, object]:
    """Build the component graph from real imports. Cached; call ``refresh()`` to rebuild.

    Returns ``{"nodes": {name: {role, files}}, "edges": {(src,dst): weight}, "root": str}``
    where an edge weight is the number of import sites in ``src`` that reach ``dst``.
    """
    root = _repo_root()
    nodes: Dict[str, Dict[str, object]] = {}
    edges: Dict[Tuple[str, str], int] = {}
    for name, (rel, role) in _COMPONENTS.items():
        files = _iter_py_files(root, rel)
        nodes[name] = {"role": role, "path": rel, "files": len(files)}
        for f in files:
            for mod in _imports_of(f, root):
                dst = _component_of(mod)
                if dst and dst != name:
                    edges[(name, dst)] = edges.get((name, dst), 0) + 1
    return {"nodes": nodes, "edges": edges, "root": str(root)}


def refresh() -> Dict[str, object]:
    build_graph.cache_clear()
    return build_graph()


def components() -> List[str]:
    return list(_COMPONENTS.keys())


def describe_component(name: str) -> Dict[str, object]:
    """Role + what it depends on (out-edges) + what uses it (in-edges), all grounded."""
    name = (name or "").strip().lower()
    g = build_graph()
    nodes: Dict = g["nodes"]  # type: ignore[assignment]
    edges: Dict[Tuple[str, str], int] = g["edges"]  # type: ignore[assignment]
    if name not in nodes:
        return {"ok": False, "error": f"unknown component '{name}'", "known": list(nodes)}
    depends_on = sorted(((dst, w) for (src, dst), w in edges.items() if src == name),
                        key=lambda x: -x[1])
    used_by = sorted(((src, w) for (src, dst), w in edges.items() if dst == name),
                     key=lambda x: -x[1])
    return {
        "ok": True,
        "component": name,
        "role": nodes[name]["role"],
        "path": nodes[name]["path"],
        "depends_on": depends_on,   # [(component, import_sites)]
        "used_by": used_by,
    }


def neighbors(name: str) -> Dict[str, List[str]]:
    d = describe_component(name)
    if not d.get("ok"):
        return {"depends_on": [], "used_by": []}
    return {
        "depends_on": [c for c, _ in d["depends_on"]],  # type: ignore[index]
        "used_by": [c for c, _ in d["used_by"]],        # type: ignore[index]
    }


def paths(src: str, dst: str, max_depth: int = 4) -> List[List[str]]:
    """All simple directed dependency paths src -> … -> dst up to max_depth (BFS)."""
    src, dst = (src or "").strip().lower(), (dst or "").strip().lower()
    g = build_graph()
    adj: Dict[str, Set[str]] = {}
    for (a, b) in g["edges"]:  # type: ignore[union-attr]
        adj.setdefault(a, set()).add(b)
    if src not in g["nodes"] or dst not in g["nodes"]:  # type: ignore[operator]
        return []
    found: List[List[str]] = []
    queue: List[List[str]] = [[src]]
    while queue:
        path = queue.pop(0)
        if len(path) > max_depth:
            continue
        for nxt in sorted(adj.get(path[-1], ())):
            if nxt in path:
                continue
            if nxt == dst:
                found.append(path + [nxt])
            else:
                queue.append(path + [nxt])
    return found


def _mention(text: str) -> List[str]:
    """Which components a free-text question names (aliases included)."""
    t = (text or "").lower()
    aliases = {
        "router": ["router", "routing"], "executor": ["executor", "execute"],
        "engine": ["engine", "cognitive engine", "process"], "agent_bus": ["agent bus", "agent_bus", "agents", "bus"],
        "gguf_inference": ["gguf", "inference", "model load", "llama"], "orchestrator": ["orchestrator", "dag"],
        "memory": ["memory", "sqlite", "recall"], "vector_store": ["vector", "faiss", "embedding"],
        "gui": ["gui", "interface", "window"], "plugins": ["plugin", "plugins"],
        "perception": ["perception", "vision", "voice", "stt", "tts"], "planning": ["planning", "proactive", "habit", "scheduler"],
        "world": ["world", "avatar", "room"], "netguard": ["netguard", "network guard", "offline", "socket guard"],
    }
    hit: List[str] = []
    for comp, keys in aliases.items():
        if any(k in t for k in keys) and comp not in hit:
            hit.append(comp)
    return hit


def explain(question: str = "") -> str:
    """Grounded natural-language answer about ELI's own architecture.

    - names two components -> report the real dependency path(s) + direction between them
    - names one -> describe it (role, depends-on, used-by)
    - names none -> a whole-graph summary
    """
    g = build_graph()
    nodes: Dict = g["nodes"]      # type: ignore[assignment]
    edges: Dict = g["edges"]      # type: ignore[assignment]
    mentioned = _mention(question)

    if len(mentioned) >= 2:
        a, b = mentioned[0], mentioned[1]
        out: List[str] = []
        # 1) A direct import edge is the clearest, truest answer.
        for x, y in ((a, b), (b, a)):
            w = edges.get((x, y))
            if w:
                out.append(f"{x} imports {y} directly ({w} import site(s)).")
        if out:
            return (f"How {a} and {b} connect (import/call edges, read live from source):\n  "
                    + "\n  ".join(out))
        # 2) No direct edge either way — find the components that import BOTH; those are
        #    the real mediators (e.g. the engine wires the router to the executor).
        mediators = sorted(
            m for m in nodes
            if m not in (a, b) and (m, a) in edges and (m, b) in edges
        )
        if mediators:
            return (f"Neither {a} nor {b} imports the other directly. "
                    f"{', '.join(mediators)} import(s) both and wire(s) them together "
                    f"— that's the real link (read live from source).")
        # 3) Fall back to the shortest transitive dependency path, labelled as such.
        for x, y in ((a, b), (b, a)):
            ps = paths(x, y)
            if ps:
                out.append(f"{x} reaches {y} transitively: {' → '.join(min(ps, key=len))}")
        return ("How they connect (import/call edges, read live from source):\n  "
                + ("\n  ".join(out) if out else
                   f"{a} and {b} have no import path either way; they interact only at runtime."))

    if len(mentioned) == 1:
        d = describe_component(mentioned[0])
        dep = ", ".join(f"{c}({w})" for c, w in d["depends_on"]) or "—"
        use = ", ".join(f"{c}({w})" for c, w in d["used_by"]) or "—"
        return (f"{d['component']} — {d['role']}\n"
                f"  path: {d['path']}\n"
                f"  depends on: {dep}\n"
                f"  used by:    {use}\n"
                f"  (numbers = import sites; read live from source)")

    return summary_text()


def summary_text() -> str:
    """Whole-graph one-screen summary — nodes + the strongest edges. Grounded."""
    g = build_graph()
    nodes: Dict = g["nodes"]                # type: ignore[assignment]
    edges: Dict[Tuple[str, str], int] = g["edges"]  # type: ignore[assignment]
    lines = [f"ELI codebase graph — {len(nodes)} core components, "
             f"{len(edges)} dependency edges (import-derived, read live):", ""]
    for name, meta in nodes.items():
        outs = [dst for (src, dst) in edges if src == name]
        lines.append(f"  • {name} ({meta['path']}) → {', '.join(sorted(outs)) or '—'}")
    lines.append("")
    lines.append("Edge A → B means: code in A imports/calls into B. Nothing here is hand-drawn.")
    return "\n".join(lines)
