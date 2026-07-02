"""Stable LAN API token — env override, persist-and-reuse, rotate, 0600 perms.

Pure logic (env + a file under config_dir); isolated to a temp config dir. This is the
module that stops a paired phone being stranded on every server restart, so its
persistence contract is worth pinning down.
"""
from __future__ import annotations

import os
import stat

import pytest

from api import api_token


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    # Point the token file at a temp config dir; clear any env override first.
    import eli.core.paths as paths
    monkeypatch.setattr(paths, "config_dir", lambda: tmp_path)
    monkeypatch.delenv("ELI_API_TOKEN", raising=False)
    yield


def test_env_override_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("ELI_API_TOKEN", "explicit-token")
    assert api_token.get_stable_token() == "explicit-token"
    # An env override must NOT write a file — it's used as-is.
    assert not (tmp_path / "api_token").exists()


def test_mints_and_persists_and_is_stable(tmp_path):
    t1 = api_token.get_stable_token()
    assert isinstance(t1, str) and t1
    assert (tmp_path / "api_token").exists()
    # Second call returns the SAME token (the whole point — no stranding).
    assert api_token.get_stable_token() == t1


def test_reads_existing_file(tmp_path):
    (tmp_path / "api_token").write_text("saved-token\n", encoding="utf-8")
    assert api_token.get_stable_token() == "saved-token"


def test_rotate_changes_and_exports(tmp_path, monkeypatch):
    t1 = api_token.get_stable_token()
    t2 = api_token.rotate_token()
    assert t2 and t2 != t1
    assert os.environ.get("ELI_API_TOKEN") == t2          # exported to env
    assert (tmp_path / "api_token").read_text().strip() == t2  # persisted
    # After rotation, the stable getter returns the new one (env precedence).
    assert api_token.get_stable_token() == t2


def test_file_permissions_are_owner_only(tmp_path):
    api_token.get_stable_token()
    mode = stat.S_IMODE((tmp_path / "api_token").stat().st_mode)
    assert mode == 0o600
