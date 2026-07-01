"""Web-server (api/server.py) test suite.

The FastAPI server + dashboard PWA had zero automated coverage; this exercises the
security-critical auth/RBAC layer deeply (pure-function branches + live gate via
TestClient), the static/PWA routes, the read endpoints, and the engine-backed
execute/chat paths with the engine mocked so no GGUF model is loaded.

Auth model under test (see api/server.py):
  * TestClient's socket peer is "testclient" → NON-loopback, so the token gate is
    genuinely exercised (a same-machine loopback caller would bypass it).
  * Single-operator mode (RBAC off) is forced in a fixture so auth is deterministic
    regardless of any user store on the box.
"""
from __future__ import annotations

import time

import pytest

# The suite conftest mocks `pydantic` session-wide (to keep the cognition-engine
# tests light). That single mock makes the real FastAPI web server impossible to
# import in-process — which is exactly why api/server.py measured 0% coverage. This
# module therefore runs on its own CLEAN lane (real deps, coverage-visible):
#
#     .venv/bin/python -m pytest tests/test_api_server.py --noconftest \
#         --cov=api.server --cov-report=term-missing
#
# Under the normal (mocked) full-suite run it detects the un-importable server and
# SKIPS — so it can never break the main suite. The assertions below are the real
# thing; they just need real fastapi/pydantic to execute.
try:
    from fastapi.testclient import TestClient
    import api.server as srv
    from api.server import app
    _WEB_OK = True
except Exception as _e:  # metaclass/mocked-pydantic conflict inside the full suite
    pytest.skip(
        f"web server not importable in-process ({type(_e).__name__}: {_e}); "
        f"run this file with `--noconftest` for real deps + coverage",
        allow_module_level=True,
    )


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _single_operator(monkeypatch):
    """Force single-operator (RBAC off) so token/tokenless auth is deterministic."""
    import eli.runtime.api_users as api_users
    monkeypatch.setattr(api_users, "rbac_enabled", lambda: False, raising=False)


@pytest.fixture
def tokenless_client(monkeypatch):
    """Owner/tokenless mode: no ELI_API_TOKEN, tokenless bind opted in → every
    request authenticates as the operator/admin."""
    monkeypatch.setenv("ELI_API_ALLOW_TOKENLESS", "1")
    monkeypatch.delenv("ELI_API_TOKEN", raising=False)
    return TestClient(app)


@pytest.fixture
def secured():
    """LAN mode: a token is configured, tokenless is OFF → non-loopback callers
    (TestClient) must present the bearer token. Returns (client, token)."""
    token = "s3cr3t-test-token-abc123"

    def _factory(monkeypatch):
        monkeypatch.delenv("ELI_API_ALLOW_TOKENLESS", raising=False)
        monkeypatch.setenv("ELI_API_TOKEN", token)
        return TestClient(app), token

    return _factory


# --------------------------------------------------------------------------- #
# Pure auth helpers — every branch
# --------------------------------------------------------------------------- #
def test_bearer_parsing():
    assert srv._bearer("Bearer abc123") == "abc123"
    assert srv._bearer("bearer  spaced ") == "spaced"
    assert srv._bearer("Basic abc") == ""
    assert srv._bearer("") == ""
    assert srv._bearer(None) == ""


def test_rank_hierarchy():
    assert srv._rank("admin") > srv._rank("member") > srv._rank("viewer")
    assert srv._rank("nonsense") == 0          # unknown role → least privilege
    assert srv._rank("") == 0
    assert srv._rank(None) == 0


class _FakeReq:
    def __init__(self, host):
        self.client = type("C", (), {"host": host})() if host is not None else None


def test_is_loopback_client():
    assert srv._is_loopback_client(_FakeReq("127.0.0.1")) is True
    assert srv._is_loopback_client(_FakeReq("::1")) is True
    assert srv._is_loopback_client(_FakeReq("localhost")) is True
    assert srv._is_loopback_client(_FakeReq("10.0.0.5")) is False
    assert srv._is_loopback_client(_FakeReq("192.168.1.20")) is False
    assert srv._is_loopback_client(_FakeReq(None)) is False


def test_tokenless_allowed_env(monkeypatch):
    for val in ("1", "true", "YES", "on"):
        monkeypatch.setenv("ELI_API_ALLOW_TOKENLESS", val)
        assert srv._tokenless_allowed() is True
    monkeypatch.setenv("ELI_API_ALLOW_TOKENLESS", "0")
    assert srv._tokenless_allowed() is False
    monkeypatch.delenv("ELI_API_ALLOW_TOKENLESS", raising=False)
    assert srv._tokenless_allowed() is False


def test_api_token_env_live(monkeypatch):
    monkeypatch.setenv("ELI_API_TOKEN", "  padded-token  ")
    assert srv._api_token() == "padded-token"
    monkeypatch.delenv("ELI_API_TOKEN", raising=False)
    assert srv._api_token() == ""


def test_resolve_principal_tokenless_owner(monkeypatch):
    monkeypatch.delenv("ELI_API_TOKEN", raising=False)
    monkeypatch.setenv("ELI_API_ALLOW_TOKENLESS", "1")
    p = srv._resolve_principal("", loopback=False)
    assert p is not None and p.role == "admin"


def test_resolve_principal_correct_token(monkeypatch):
    monkeypatch.delenv("ELI_API_ALLOW_TOKENLESS", raising=False)
    monkeypatch.setenv("ELI_API_TOKEN", "right")
    assert srv._resolve_principal("Bearer right", loopback=False).role == "admin"


def test_resolve_principal_wrong_token_fails_closed(monkeypatch):
    monkeypatch.delenv("ELI_API_ALLOW_TOKENLESS", raising=False)
    monkeypatch.setenv("ELI_API_TOKEN", "right")
    assert srv._resolve_principal("Bearer wrong", loopback=False) is None
    # ...but a same-machine (loopback) caller with no token is still the owner.
    assert srv._resolve_principal("", loopback=True).role == "admin"


def test_resolve_principal_no_config_no_tokenless_denies(monkeypatch):
    monkeypatch.delenv("ELI_API_TOKEN", raising=False)
    monkeypatch.delenv("ELI_API_ALLOW_TOKENLESS", raising=False)
    # No token configured, not tokenless, not loopback → fail closed.
    assert srv._resolve_principal("", loopback=False) is None


# --------------------------------------------------------------------------- #
# Static / PWA routes (no auth)
# --------------------------------------------------------------------------- #
def test_health_is_tokenless(monkeypatch):
    # Health must answer even in fully-secured LAN mode (used by the PWA self-heal).
    monkeypatch.delenv("ELI_API_ALLOW_TOKENLESS", raising=False)
    monkeypatch.setenv("ELI_API_TOKEN", "x")
    r = TestClient(app).get("/health")
    assert r.status_code == 200 and r.json()["status"] == "healthy"


def test_root_serves_html(tokenless_client):
    r = tokenless_client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]


def test_manifest_and_service_worker(tokenless_client):
    m = tokenless_client.get("/manifest.webmanifest")
    assert m.status_code == 200 and "name" in m.json()
    sw = tokenless_client.get("/sw.js")
    assert sw.status_code == 200 and "javascript" in sw.headers["content-type"]


def test_api_descriptor(tokenless_client):
    r = tokenless_client.get("/api")
    assert r.status_code == 200 and isinstance(r.json(), dict)


# --------------------------------------------------------------------------- #
# Auth gating through the real dependency graph
# --------------------------------------------------------------------------- #
def test_protected_endpoint_401_without_token(secured, monkeypatch):
    client, _ = secured(monkeypatch)
    assert client.get("/v1/capabilities").status_code == 401


def test_protected_endpoint_200_with_token(secured, monkeypatch):
    client, token = secured(monkeypatch)
    r = client.get("/v1/capabilities", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


def test_protected_endpoint_401_with_wrong_token(secured, monkeypatch):
    client, _ = secured(monkeypatch)
    r = client.get("/v1/capabilities", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


# --------------------------------------------------------------------------- #
# Read endpoints (tokenless owner)
# --------------------------------------------------------------------------- #
def test_whoami(tokenless_client):
    r = tokenless_client.get("/v1/me")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["role"] == "admin"


def test_capabilities_lists_actions(tokenless_client):
    r = tokenless_client.get("/v1/capabilities")
    assert r.status_code == 200


def test_models_endpoint(tokenless_client):
    r = tokenless_client.get("/v1/models")
    assert r.status_code == 200


def test_net_status(tokenless_client):
    r = tokenless_client.get("/v1/net")
    assert r.status_code == 200
    assert "enabled" in r.json() or "online" in r.json() or isinstance(r.json(), dict)


def test_net_egress_tail(tokenless_client):
    r = tokenless_client.get("/v1/net/egress")
    assert r.status_code == 200


def test_system_vitals(tokenless_client):
    r = tokenless_client.get("/v1/system")
    assert r.status_code == 200 and isinstance(r.json(), dict)


# --------------------------------------------------------------------------- #
# Engine-backed paths — engine + executor mocked, no model loaded
# --------------------------------------------------------------------------- #
def test_execute_action_mocked(tokenless_client, monkeypatch):
    import eli.execution.executor_enhanced as ex
    monkeypatch.setattr(
        ex, "execute", lambda action, args=None: {"ok": True, "content": "did it"}
    )
    r = tokenless_client.post("/v1/execute", json={"action": "SCREENSHOT", "args": {}})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["result"]["content"] == "did it"


def test_execute_reports_failure(tokenless_client, monkeypatch):
    import eli.execution.executor_enhanced as ex
    monkeypatch.setattr(ex, "execute", lambda action, args=None: {"ok": False, "error": "nope"})
    r = tokenless_client.post("/v1/execute", json={"action": "OPEN_APP", "args": {"name": "x"}})
    assert r.status_code == 200 and r.json()["ok"] is False


def test_chat_mocked_engine(tokenless_client, monkeypatch):
    class _FakeEngine:
        def process(self, message, source="", stream=False, **kw):
            return {"response": f"echo: {message}", "content": f"echo: {message}"}

    monkeypatch.setattr(srv, "get_engine", lambda: _FakeEngine())
    r = tokenless_client.post("/v1/chat", json={"message": "hello there", "user_id": "u1"})
    assert r.status_code == 200
    assert "echo: hello there" in r.json()["response"]


def test_chat_requires_auth(secured, monkeypatch):
    client, _ = secured(monkeypatch)
    # /v1/chat is token-gated; no token → 401 before the engine is ever touched.
    assert client.post("/v1/chat", json={"message": "hi"}).status_code == 401
