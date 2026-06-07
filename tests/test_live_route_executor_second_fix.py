from __future__ import annotations

def _route(text: str):
    from eli.execution import router_enhanced
    fn = getattr(router_enhanced, "route", None) or getattr(router_enhanced, "route_intent")
    return fn(text)

def test_trailing_grid_routes_to_tile_windows():
    r = _route("2x tree grid")
    assert r["action"] == "TILE_WINDOWS"
    assert r["args"]["cols"] == 2
    assert r["args"]["rows"] == 3

def test_numeric_grid_routes_to_tile_windows():
    r = _route("4x2")
    assert r["action"] == "TILE_WINDOWS"
    assert r["args"]["grid"] == [4, 2]

def test_reasoning_mode_status_not_runtime_status():
    r = _route("what is your reasoning mode")
    assert r["action"] == "REASONING_MODE_STATUS"

def test_memory_internals_do_not_become_search_chat():
    r = _route("Tell me exactly how your memory system works internally — which files, which DB tables, which functions.")
    assert r["action"] in {"EXPLAIN_MEMORY_RUNTIME", "PERSONAL_MEMORY_DEEP_EXPLAIN"}

def test_reasoning_status_override_label():
    # The internal key 'tree_of_thoughts' surfaces under its user-facing name
    # 'Research' after the reasoning-mode rename (quick/normal/advanced/research/
    # expert). Assert the displayed label, not the internal key.
    from eli.runtime.reasoning_status import current_reasoning_mode_text
    s = current_reasoning_mode_text(override="tree_of_thoughts")
    assert "Research" in s
