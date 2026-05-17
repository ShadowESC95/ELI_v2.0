from __future__ import annotations

def _route(text: str):
    from eli.execution import router_enhanced
    if hasattr(router_enhanced, "route"):
        return router_enhanced.route(text)
    return router_enhanced.route_intent(text)

def test_reasoning_mode_question_is_not_runtime_status():
    r = _route("what is your reasoning mode")
    assert isinstance(r, dict)
    assert r.get("action") == "REASONING_MODE_STATUS"
    assert r.get("action") != "RUNTIME_STATUS"

def test_reasoning_mode_with_eli_suffix_is_not_runtime_status():
    r = _route("what is your reasoning mode, eli?")
    assert isinstance(r, dict)
    assert r.get("action") == "REASONING_MODE_STATUS"

def test_cognition_pipeline_routes_to_cognition_runtime():
    r = _route("explain the cognition pipeline input to output")
    assert isinstance(r, dict)
    assert r.get("action") == "EXPLAIN_COGNITION_RUNTIME"

def test_optimize_screen_routes_tile_windows():
    r = _route("optimize my screen")
    assert isinstance(r, dict)
    assert r.get("action") == "TILE_WINDOWS"

def test_bare_grid_reply_routes_tile_windows():
    r = _route("4x2")
    assert isinstance(r, dict)
    assert r.get("action") == "TILE_WINDOWS"
    args = r.get("args") or {}
    assert args.get("cols") == 4
    assert args.get("rows") == 2

def test_stt_tree_means_three_for_grid_reply():
    r = _route("2x tree")
    assert isinstance(r, dict)
    assert r.get("action") == "TILE_WINDOWS"
    args = r.get("args") or {}
    assert args.get("cols") == 2
    assert args.get("rows") == 3

def test_reasoning_mode_executor_surface():
    from eli.execution import executor_enhanced
    fn = getattr(executor_enhanced, "execute_action", None) or getattr(executor_enhanced, "execute")
    out = fn("REASONING_MODE_STATUS", {})
    assert isinstance(out, dict)
    assert out.get("ok") is True
    assert "Current reasoning mode:" in (out.get("content") or out.get("response") or "")
