"""#21 — the plugin manager must respect offline-by-default.

`_fetch_registry` routes through `netguard.http_get_json`, so when the network
is not allowed it fails CLOSED (no socket attempt, no timeout) and drops straight
to the bundled registry. Before the fix it called `urllib.urlopen` directly and
hung on an N-second timeout every call while offline.
"""
import time

from eli.plugins import manager


def test_fetch_registry_offline_uses_bundled_instantly(monkeypatch):
    # Force offline at the policy source netguard consults.
    import eli.core.config as cfg
    monkeypatch.setattr(cfg, "network_allowed", lambda: False)

    t0 = time.time()
    out = manager._fetch_registry(timeout=8)
    elapsed = time.time() - t0

    assert isinstance(out, list)            # graceful fallback, no exception
    assert elapsed < 2.0                    # fails closed — no network timeout
    # The bundled registry ships with plugins, so offline still lists them.
    assert len(out) >= 1


def test_fetch_registry_routes_through_netguard(monkeypatch):
    """It must use the gated helper, not a raw urlopen."""
    called = {"guarded": False}

    def fake_http_get_json(url, headers=None, timeout=20):
        called["guarded"] = True
        return {"plugins": [{"name": "x"}]}

    monkeypatch.setattr("eli.core.netguard.http_get_json", fake_http_get_json)
    out = manager._fetch_registry()
    assert called["guarded"] is True
    assert out == [{"name": "x"}]


def test_web_search_blocks_offline_at_choke_point(monkeypatch):
    """The Net toggle must be enforced INSIDE the web plugin, not only at the executor.

    `ddgs`/`duckduckgo_search` drive libcurl (curl_cffi/primp) at the C/Rust level,
    which bypasses Python's socket layer — so the process-wide socket guard cannot
    see it. If a caller reaches the plugin without the executor's gate, offline must
    still hold. Guard against that regression here.
    """
    import eli.core.netguard as ng
    from eli.plugins.web import plugin as wp

    monkeypatch.setattr(ng, "_net_allowed", lambda: False)  # toggle off, no full-control

    # A backend fetch would mean the network was touched — it must NEVER run offline.
    def _boom(*a, **k):
        raise AssertionError("network backend invoked while offline")
    monkeypatch.setattr(wp, "_searxng_search", _boom)
    monkeypatch.setattr(wp, "_duckduckgo_search", _boom)
    monkeypatch.setattr(wp, "_duckduckgo_html_search", _boom)

    # 1) canonical choke point fails closed (no backend call)
    import pytest
    with pytest.raises(ng.OfflineError):
        wp._web_search_results("anything")

    # 2) public plugin entry returns an honest offline response, not a guess
    out = wp.WebSearchPlugin().web_search({"query": "latest headlines"})
    assert out.get("offline") is True and out.get("ok") is False
    assert "network access is off" in (out.get("content") or "").lower()
