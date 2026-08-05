"""Behaviour locks for self-upgrade on a frozen (AppImage) install.

The shipped product is an AppImage, but self-upgrade was written for a git
checkout: it fetched a wheel no release has ever published, then ran `git pull`
and `pip install` inside a bundle that has neither. All three failed, the four
local index rebuilds succeeded, and the user was told "Upgrade complete.
4 / 7 steps succeeded" while still running the previous build.
"""
import hashlib
import os
from pathlib import Path

import pytest

from eli.kernel import self_upgrade as su


NEW_VERSION = su._DEFAULT_RELEASE_TAG.lstrip("v")
ASSET = f"ELI_v2-{NEW_VERSION}-x86_64.AppImage"
PAYLOAD = b"new-appimage-bytes"
PAYLOAD_SHA = hashlib.sha256(PAYLOAD).hexdigest()


@pytest.fixture
def appimage(tmp_path, monkeypatch):
    """A fake running AppImage with a versioned filename, as shipped."""
    running = tmp_path / "ELI_v2-2.1.46-x86_64.AppImage"
    running.write_bytes(b"old-appimage-bytes")
    running.chmod(0o755)
    monkeypatch.setenv("APPIMAGE", str(running))
    monkeypatch.setattr(su.SelfUpgrader, "_local_version", lambda self: "2.1.46")
    return running


def _stub_network(monkeypatch, *, sums=None, payload=PAYLOAD, latest=None):
    """Serve the latest-tag lookup, SHA256SUMS.txt and the asset, offline."""
    if sums is None:
        sums = f"{hashlib.sha256(payload).hexdigest()}  {ASSET}\n"

    monkeypatch.setattr(su.SelfUpgrader, "_latest_tag",
                        lambda self: latest or su._DEFAULT_RELEASE_TAG)
    monkeypatch.setattr(su.SelfUpgrader, "_fetch_bytes",
                        lambda self, url, timeout=60: sums.encode())

    def fake_download(self, url, dest, expected_sha, timeout=900):
        digest = hashlib.sha256(payload).hexdigest()
        if expected_sha and digest != expected_sha.lower():
            Path(dest).unlink(missing_ok=True)
            return False, "checksum mismatch — refusing to install an unverified build."
        Path(dest).write_bytes(payload)
        return True, digest

    monkeypatch.setattr(su.SelfUpgrader, "_download_verified", fake_download)


# ── install-kind detection ──────────────────────────────────────────────────

def test_appimage_env_selects_the_appimage_path(monkeypatch):
    monkeypatch.setenv("APPIMAGE", "/tmp/ELI.AppImage")
    assert su._install_kind() == "appimage"


def test_source_checkout_still_detected(monkeypatch):
    monkeypatch.delenv("APPIMAGE", raising=False)
    monkeypatch.setattr(su.sys, "frozen", False, raising=False)
    assert su._install_kind() == "source"


def test_frozen_without_appimage_is_not_treated_as_a_checkout(monkeypatch):
    monkeypatch.delenv("APPIMAGE", raising=False)
    monkeypatch.setattr(su.sys, "frozen", True, raising=False)
    assert su._install_kind() == "frozen"


# ── the upgrade itself ──────────────────────────────────────────────────────

def test_versioned_name_places_new_build_and_keeps_the_running_one(appimage, monkeypatch):
    _stub_network(monkeypatch)
    ok, detail = su.SelfUpgrader()._appimage_upgrade()

    assert ok is True, detail
    new = appimage.with_name(ASSET)
    assert new.exists() and new.read_bytes() == PAYLOAD
    assert os.access(new, os.X_OK), "new AppImage must be executable"
    # The build the user is currently running must survive an upgrade.
    assert appimage.exists() and appimage.read_bytes() == b"old-appimage-bytes"
    assert not appimage.with_name(ASSET + ".part").exists()


def test_checksum_mismatch_refuses_and_leaves_nothing_behind(appimage, monkeypatch):
    _stub_network(monkeypatch, sums=f"{'0' * 64}  {ASSET}\n")
    ok, detail = su.SelfUpgrader()._appimage_upgrade()

    assert ok is False
    assert "checksum" in detail.lower()
    assert not appimage.with_name(ASSET).exists()
    assert appimage.read_bytes() == b"old-appimage-bytes"


def test_missing_checksum_entry_refuses(appimage, monkeypatch):
    _stub_network(monkeypatch, sums="deadbeef  something-else.AppImage\n")
    ok, detail = su.SelfUpgrader()._appimage_upgrade()

    assert ok is False
    assert "SHA256SUMS" in detail
    assert not appimage.with_name(ASSET).exists()


def test_already_current_is_not_a_failure(appimage, monkeypatch):
    _stub_network(monkeypatch)
    monkeypatch.setattr(su.SelfUpgrader, "_local_version", lambda self: NEW_VERSION)
    ok, detail = su.SelfUpgrader()._appimage_upgrade()

    assert ok is None, "already-current must be 'not applicable', not a failure"
    assert "already on" in detail


def test_never_downgrades(appimage, monkeypatch):
    """A yanked or mis-tagged release must not talk a newer build backwards."""
    _stub_network(monkeypatch, latest="v2.1.40")
    monkeypatch.setattr(su.SelfUpgrader, "_local_version", lambda self: "2.1.46")
    ok, detail = su.SelfUpgrader()._appimage_upgrade()

    assert ok is None
    assert "already on 2.1.46" in detail
    assert not appimage.with_name("ELI_v2-2.1.40-x86_64.AppImage").exists()


def test_upgrade_target_is_the_latest_release_not_the_pinned_tag(appimage, monkeypatch):
    """The pinned tag equals the running build's own version, so keying off it
    would make every build believe it was already current, forever."""
    seen = {}

    def fake_json(url, headers=None, timeout=20):
        seen["url"] = url
        return {"tag_name": "v2.9.9"}

    from eli.core import netguard
    monkeypatch.setattr(netguard, "http_get_json", fake_json)
    assert su.SelfUpgrader()._latest_tag() == "v2.9.9"
    assert "releases/latest" in seen["url"]


def test_latest_tag_falls_back_when_the_api_is_unreachable(monkeypatch):
    from eli.core import netguard

    def boom(url, headers=None, timeout=20):
        raise OSError("no network")

    monkeypatch.setattr(netguard, "http_get_json", boom)
    assert su.SelfUpgrader()._latest_tag() == su._DEFAULT_RELEASE_TAG


def test_version_ordering():
    assert su._ver_tuple("2.1.47") > su._ver_tuple("2.1.46")
    assert su._ver_tuple("2.1.9") < su._ver_tuple("2.1.10"), "must not compare as strings"
    assert su._ver_tuple("garbage") == (0,)


def test_stable_filename_swaps_in_place_and_keeps_a_backup(tmp_path, monkeypatch):
    running = tmp_path / ASSET          # name already matches the release asset
    running.write_bytes(b"old-appimage-bytes")
    monkeypatch.setenv("APPIMAGE", str(running))
    monkeypatch.setattr(su.SelfUpgrader, "_local_version", lambda self: "2.1.46")
    _stub_network(monkeypatch)

    ok, detail = su.SelfUpgrader()._appimage_upgrade()

    assert ok is True, detail
    assert running.read_bytes() == PAYLOAD
    backup = running.with_name(running.name + ".bak")
    assert backup.exists() and backup.read_bytes() == b"old-appimage-bytes"


def test_frozen_build_without_appimage_var_says_so(monkeypatch):
    monkeypatch.delenv("APPIMAGE", raising=False)
    _stub_network(monkeypatch)
    monkeypatch.setattr(su.SelfUpgrader, "_local_version", lambda self: "2.1.46")
    ok, detail = su.SelfUpgrader()._appimage_upgrade()

    assert ok is False
    assert "APPIMAGE" in detail and "http" in detail, "must point the user somewhere real"


# ── honest reporting ────────────────────────────────────────────────────────

def test_appimage_run_skips_git_and_pip(appimage, monkeypatch):
    _stub_network(monkeypatch)
    for name in ("_rebuild_faiss", "_rebuild_kg", "_update_manifest", "_refresh_system_index"):
        monkeypatch.setattr(su.SelfUpgrader, name, lambda self: (True, "stubbed"))

    def _boom(self):
        raise AssertionError("git/pip must not run inside an AppImage")

    monkeypatch.setattr(su.SelfUpgrader, "_git_pull", _boom)
    monkeypatch.setattr(su.SelfUpgrader, "_pip_upgrade", _boom)

    up = su.SelfUpgrader()
    report = up.upgrade()

    assert up.upgrade_state == "upgraded"
    assert "Git pull" not in report and "Pip upgrade" not in report
    assert "restart" in report.lower()


def test_failed_upgrade_is_not_reported_as_complete(appimage, monkeypatch):
    """The exact regression: maintenance steps pass, the build does not change."""
    _stub_network(monkeypatch, sums=f"{'0' * 64}  {ASSET}\n")
    for name in ("_rebuild_faiss", "_rebuild_kg", "_update_manifest", "_refresh_system_index"):
        monkeypatch.setattr(su.SelfUpgrader, name, lambda self: (True, "stubbed"))

    up = su.SelfUpgrader()
    report = up.upgrade()

    assert up.upgraded is False
    assert up.upgrade_state == "failed"
    assert "NOT upgraded" in report
    assert "Upgrade complete" not in report


def test_wheelless_release_is_not_applicable_not_a_failure(monkeypatch):
    """No v2 release has ever shipped a wheel; stop calling that a failed step."""
    monkeypatch.setattr(su, "_run", lambda *a, **k: {"ok": False, "stdout": "",
                                                    "stderr": "no assets matched", "returncode": 1})
    ok, detail = su.SelfUpgrader()._release_upgrade()

    assert ok is None
    assert "not applicable" in detail
