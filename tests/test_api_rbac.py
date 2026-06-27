"""Integration test: API role-based access control (admin / member).

- Single-operator mode (no users) keeps the legacy behaviour: the loopback operator
  is admin and can bootstrap users.
- Once users are defined, RBAC is enforced: a member reaches member endpoints but is
  403'd from the Admin console; an admin reaches everything; an invalid token is 401'd.
- The loopback operator stays admin (machine owner) so they can never lock themselves out.
- Attribution is AUTHENTICATED: a member cannot spoof another user's id — the token's
  identity is what gets recorded in the audit trail.
- The last admin cannot be removed.

Runs the real FastAPI stack in a clean subprocess (the suite conftest mocks
pydantic/fastapi). Token store + audit DB are isolated to throwaway files.
"""
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

_DRIVER = textwrap.dedent(
    """
    import os, tempfile
    from pathlib import Path
    os.environ["ELI_API_USERS_FILE"] = tempfile.mktemp(suffix=".json")
    os.environ["ELI_API_ALLOW_TOKENLESS"] = "1"   # loopback operator
    os.environ.pop("ELI_API_TOKEN", None)
    art = tempfile.mkdtemp()

    from fastapi.testclient import TestClient
    import api.server as S
    from eli.runtime import evidence_ledger as L
    L._default_db_path = lambda: Path(art) / "audit.sqlite3"
    S.get_engine = lambda: type("E", (), {"process": lambda s, *a, **k: {"response": "hi"}})()
    c = TestClient(S.app)
    H = lambda t: {"Authorization": "Bearer " + t} if t else {}

    # operator bootstraps users (works even after RBAC turns on)
    a = c.post("/v1/admin/users/add", json={"user_id": "alice", "role": "admin"}).json()
    b = c.post("/v1/admin/users/add", json={"user_id": "bob", "role": "member"}).json()
    assert a["ok"] and b["ok"], (a, b)
    ta, tb = a["token"], b["token"]

    # role gating
    assert c.get("/v1/system").status_code == 200                       # loopback operator
    assert c.get("/v1/system", headers=H(tb)).status_code == 200        # member ok
    assert c.get("/v1/admin/overview", headers=H(tb)).status_code == 403  # member denied admin
    assert c.get("/v1/admin/overview", headers=H(ta)).status_code == 200  # admin ok
    assert c.get("/v1/system", headers=H("garbage")).status_code == 401   # bad token

    # viewer (read-only): can read dashboards, cannot act, cannot see the admin console
    v = c.post("/v1/admin/users/add", headers=H(ta), json={"user_id": "val", "role": "viewer"}).json()
    tv = v["token"]
    assert c.get("/v1/me", headers=H(tv)).json()["role"] == "viewer"
    assert c.get("/v1/system", headers=H(tv)).status_code == 200            # read ok
    assert c.get("/v1/research/corpora", headers=H(tv)).status_code == 200  # read ok
    assert c.post("/v1/chat", headers=H(tv), json={"message": "hi"}).status_code == 403
    assert c.post("/v1/devices/control", headers=H(tv),
                  json={"device_id": "x", "command": "on"}).status_code == 403
    assert c.get("/v1/admin/overview", headers=H(tv)).status_code == 403

    # authenticated attribution: bob claims to be alice -> recorded as bob
    c.post("/v1/chat", headers=H(tb), json={"message": "hi", "user_id": "alice"})
    users = {u["user_id"] for u in c.get("/v1/admin/overview", headers=H(ta)).json()["users"]}
    assert "bob" in users and "alice" not in users, users

    # last admin cannot be removed
    r = c.post("/v1/admin/users/remove", headers=H(ta), json={"user_id": "alice"}).json()
    assert r["ok"] is False and "last admin" in r["error"]
    # but a member can be removed, and their token then stops working
    assert c.post("/v1/admin/users/remove", headers=H(ta), json={"user_id": "bob"}).json()["ok"]
    assert c.get("/v1/system", headers=H(tb)).status_code == 401

    print("RBAC_DRIVER_OK")
    """
)


def test_api_rbac_end_to_end():
    r = subprocess.run([sys.executable, "-c", _DRIVER],
                       cwd=str(ROOT), capture_output=True, text=True)
    if r.returncode != 0 or "RBAC_DRIVER_OK" not in r.stdout:
        pytest.fail(f"RBAC driver failed (rc={r.returncode})\n"
                    f"STDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr[-2500:]}")
