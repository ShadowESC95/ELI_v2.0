"""Codebase self-graph — the graph is grounded in real imports, not hand-drawn."""
from __future__ import annotations

from eli.runtime import codebase_graph as cg


def test_graph_has_the_canonical_components():
    g = cg.build_graph()
    nodes = g["nodes"]
    for expected in ("router", "executor", "engine", "agent_bus", "gguf_inference",
                     "orchestrator", "memory", "vector_store", "gui", "plugins"):
        assert expected in nodes, f"{expected} missing from the graph"
    assert g["edges"], "graph has no edges — import extraction is broken"


def test_every_edge_endpoint_is_a_known_component():
    g = cg.build_graph()
    nodes = set(g["nodes"])
    for (src, dst) in g["edges"]:
        assert src in nodes and dst in nodes, f"edge {src}->{dst} references an unknown node"
        assert src != dst, "self-edges should not be recorded"


def test_edges_are_real_imports_not_fabricated():
    # memory genuinely imports the vector store — a concrete, checkable edge.
    g = cg.build_graph()
    assert ("memory", "vector_store") in g["edges"], "expected memory -> vector_store import edge"
    # the engine is the spine: it must import several subsystems.
    engine_out = [dst for (src, dst) in g["edges"] if src == "engine"]
    assert len(engine_out) >= 4, f"engine should depend on many subsystems, got {engine_out}"


def test_describe_component_reports_role_and_edges():
    d = cg.describe_component("engine")
    assert d["ok"] and d["role"] and d["path"] == "eli/kernel/engine.py"
    assert isinstance(d["depends_on"], list) and isinstance(d["used_by"], list)


def test_describe_unknown_component_is_graceful():
    d = cg.describe_component("does_not_exist")
    assert d["ok"] is False and "known" in d


def test_explain_two_components_reports_direct_or_mediator():
    out = cg.explain("how does the router connect to the executor").lower()
    # either a direct import edge or the engine/a mediator wiring them — never a crash
    assert "import" in out or "wire" in out or "→" in out


def test_explain_single_component_and_whole_graph():
    one = cg.explain("engine")
    assert "engine" in one.lower() and "depends on" in one.lower()
    whole = cg.explain("")
    assert "codebase graph" in whole.lower()


def test_paths_are_simple_and_bounded():
    for p in cg.paths("gui", "memory"):
        assert p[0] == "gui" and p[-1] == "memory"
        assert len(p) == len(set(p)), "path must be simple (no repeats)"
