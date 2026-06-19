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
