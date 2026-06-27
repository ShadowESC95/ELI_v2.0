"""Integration tests: API server security guarantees.

Two independent server-side guarantees that must never regress:

1. The auth gate fails CLOSED. With no ELI_API_TOKEN and no explicit
   ELI_API_ALLOW_TOKENLESS opt-out (i.e. an ASGI-direct launch such as
   `uvicorn api.server:app` / a Docker CMD that never runs main()), every gated
   endpoint returns 401 — it does NOT serve unauthenticated. Liveness endpoints
   (/health, /api) stay open by design. With a token set, the right Bearer header
   is required.

2. The research ingest primitive is confined to a configured root. A caller cannot
   make the server read arbitrary host files (path traversal / absolute paths /
   home dir all rejected); and a directory walk is bounded by file-count /
   total-byte caps.

The auth checks run the real FastAPI/pydantic stack in a clean subprocess, because
the test-suite conftest mocks pydantic/fastapi/faiss (it targets the cognition
engine, not the web server) — so `import api.server` can't load in-process here.
The research-confinement checks run in-process: every assertion returns before any
real FAISS use, so the mocked faiss is irrelevant.
"""
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# 1. Auth gate fails closed  (real FastAPI stack, clean subprocess)
# ---------------------------------------------------------------------------

_AUTH_DRIVER = textwrap.dedent(
    """
    import os, sys
    os.environ.pop("ELI_API_TOKEN", None)
    os.environ.pop("ELI_API_ALLOW_TOKENLESS", None)
    from fastapi.testclient import TestClient
    import api.server as S

    GATED = ["/v1/system", "/v1/voice/voices", "/v1/research/corpora",
             "/v1/devices", "/v1/capabilities", "/v1/status/me"]

    # (a) tokenless + no opt-out -> every gated endpoint 401 (fail closed)
    c = TestClient(S.app)
    for p in GATED:
        r = c.get(p)
        assert r.status_code == 401, f"FAIL-OPEN {p}: {r.status_code}"
    # device control (POST) also denied
    assert c.post("/v1/devices/control",
                  json={"device_id": "x", "command": "on"}).status_code == 401
    # research ingest (the file-read primitive) denied
    assert c.post("/v1/research/ingest", json={"corpus": "x", "path": "/etc"}).status_code == 401

    # (b) liveness stays open by design
    assert c.get("/health").status_code == 200
    assert c.get("/api").status_code == 200

    # (c) explicit loopback opt-out allows tokenless serving
    os.environ["ELI_API_ALLOW_TOKENLESS"] = "1"
    assert c.get("/v1/voice/voices").status_code == 200
    os.environ.pop("ELI_API_ALLOW_TOKENLESS", None)

    # (d) when a token is set, the correct Bearer header is required
    os.environ["ELI_API_TOKEN"] = "secret-xyz"
    assert c.get("/v1/voice/voices").status_code == 401
    assert c.get("/v1/voice/voices",
                 headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert c.get("/v1/voice/voices",
                 headers={"Authorization": "Bearer secret-xyz"}).status_code == 200

    print("AUTH_DRIVER_OK")
    """
)


def test_auth_gate_fails_closed_and_enforces_token():
    env = {k: v for k, v in os.environ.items() if not k.startswith("ELI_API_")}
    r = subprocess.run([sys.executable, "-c", _AUTH_DRIVER],
                       cwd=str(ROOT), env=env, capture_output=True, text=True)
    if r.returncode != 0 or "AUTH_DRIVER_OK" not in r.stdout:
        pytest.fail(f"auth security driver failed (rc={r.returncode})\n"
                    f"STDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr[-2000:]}")


# ---------------------------------------------------------------------------
# 2. Research ingest is confined to the research root  (in-process)
# ---------------------------------------------------------------------------

@pytest.fixture()
def research_root(monkeypatch):
    root = tempfile.mkdtemp(prefix="eli_research_root_")
    monkeypatch.setenv("ELI_RESEARCH_ROOT", root)
    import importlib
    import eli.runtime.research_corpus as rc
    importlib.reload(rc)  # pick up the env-configured root + caps
    yield root, rc


def test_absolute_path_outside_root_rejected(research_root):
    _root, rc = research_root
    outside = tempfile.mkdtemp(prefix="eli_secret_")
    with open(os.path.join(outside, "secret.txt"), "w") as fh:
        fh.write("SSH KEYS AND PASSWORDS")
    res = rc.ingest("x", os.path.join(outside, "secret.txt"))
    assert res["ok"] is False
    assert "outside the research root" in res["error"]


def test_traversal_escape_rejected(research_root):
    _root, rc = research_root
    res = rc.ingest("x", "../../../../etc/hostname")
    assert res["ok"] is False
    assert "outside the research root" in res["error"]


def test_home_dir_rejected(research_root):
    _root, rc = research_root
    res = rc.ingest("x", os.path.expanduser("~"))
    assert res["ok"] is False
    assert "outside the research root" in res["error"]


def test_file_count_cap_enforced(monkeypatch, research_root):
    root, rc = research_root
    monkeypatch.setenv("ELI_RESEARCH_MAX_FILES", "3")
    import importlib
    importlib.reload(rc)
    sub = os.path.join(root, "many")
    os.makedirs(sub)
    for i in range(10):
        with open(os.path.join(sub, f"d{i}.txt"), "w") as fh:
            fh.write("x")
    res = rc.ingest("cap", "many")
    assert res["ok"] is False
    assert "too many" in res["error"]


def test_byte_cap_enforced(monkeypatch, research_root):
    root, rc = research_root
    monkeypatch.setenv("ELI_RESEARCH_MAX_BYTES", "10")
    import importlib
    importlib.reload(rc)
    with open(os.path.join(root, "big.txt"), "w") as fh:
        fh.write("y" * 5000)
    res = rc.ingest("cap2", "big.txt")
    assert res["ok"] is False
    assert "exceeds" in res["error"]
