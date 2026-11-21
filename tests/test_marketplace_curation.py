"""The official registry is curated, and curation is enforced rather than claimed.

ELI's marketplace is run by the maintainer: submissions are quarantined, evaluated,
and signed at approval. That review is the product, so the client has to be able to
tell an approved listing from one that merely *says* it is approved.

The enforcement that matters is asymmetric, and easy to get wrong by treating both
registries the same:

  * on a COMMUNITY registry an unsigned plugin is ordinary — warn, let the operator
    decide;
  * on the CURATED registry an unsigned plugin is evidence of tampering, because
    nothing reaches that index unsigned. Warning there would let anyone who can
    rewrite the index or intercept the download strip the signature and be waved
    through with a yellow badge.
"""
from __future__ import annotations

import base64

import pytest

from eli.plugins import integrity, marketplace


KEY_ENV = "ELI_MARKETPLACE_PUBLISHER_KEY"
URL_ENV = "ELI_MARKETPLACE_URL"


@pytest.fixture()
def official(monkeypatch, tmp_path):
    """A build with a real official key and registry address."""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives import serialization
    except Exception:  # pragma: no cover - build without 'cryptography'
        pytest.skip("signing unavailable in this build")

    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw)
    monkeypatch.setenv(KEY_ENV, base64.b64encode(pub).decode("ascii"))
    monkeypatch.setenv(URL_ENV, "https://plugins.example.org/index.json")
    monkeypatch.setenv("ELI_CONFIG_DIR", str(tmp_path))
    return priv


def _sign(priv, data: bytes) -> str:
    return base64.b64encode(priv.sign(data)).decode("ascii")


# ── the registry itself ──────────────────────────────────────────────────────

def test_official_registry_appears_and_is_curated(official):
    ids = {r["id"]: r for r in marketplace.list_registries()}
    assert marketplace.OFFICIAL_REGISTRY_ID in ids
    assert ids[marketplace.OFFICIAL_REGISTRY_ID]["curated"] is True
    assert marketplace.is_curated(marketplace.OFFICIAL_REGISTRY_ID) is True


def test_no_registry_ships_when_no_address_is_configured(monkeypatch):
    """A build that has not been pointed at a marketplace must not invent one."""
    monkeypatch.delenv(URL_ENV, raising=False)
    monkeypatch.setattr(marketplace, "OFFICIAL_REGISTRY_URL", "", raising=False)
    ids = {r["id"] for r in marketplace.list_registries()}
    assert marketplace.OFFICIAL_REGISTRY_ID not in ids


def test_community_registries_cannot_claim_to_be_curated(official, tmp_path, monkeypatch):
    """`curated` is what makes a signature mandatory, so a config file that could
    set it could also award itself the official badge."""
    import json
    p = tmp_path / "plugin_registries.json"
    p.write_text(json.dumps({"version": 1, "registries": [
        {"id": "sneaky", "url": "https://evil.example/index.json",
         "label": "Totally Official", "enabled": True,
         "curated": True, "official": True}]}), encoding="utf-8")
    monkeypatch.setattr(marketplace, "_registries_path", lambda: p)

    entry = next(r for r in marketplace.list_registries() if r["id"] == "sneaky")
    assert not entry.get("curated"), "a stored registry must not be able to set curated"
    assert not entry.get("official")
    assert marketplace.is_curated("sneaky") is False


def test_a_stored_entry_cannot_hijack_the_official_id(official, tmp_path, monkeypatch):
    import json
    p = tmp_path / "plugin_registries.json"
    p.write_text(json.dumps({"version": 1, "registries": [
        {"id": marketplace.OFFICIAL_REGISTRY_ID, "url": "https://evil.example/index.json",
         "label": "Hijacked", "enabled": True}]}), encoding="utf-8")
    monkeypatch.setattr(marketplace, "_registries_path", lambda: p)

    entries = [r for r in marketplace.list_registries()
               if r["id"] == marketplace.OFFICIAL_REGISTRY_ID]
    assert len(entries) == 1, "the official id must not be duplicated by a config file"
    assert entries[0]["url"] == "https://plugins.example.org/index.json"


# ── the key ──────────────────────────────────────────────────────────────────

def test_official_key_is_trusted_without_the_operator_adding_it(official):
    pubs = integrity.trusted_publishers()
    assert integrity.OFFICIAL_PUBLISHER_ID in pubs
    assert pubs[integrity.OFFICIAL_PUBLISHER_ID]["builtin"] is True


def test_operator_file_cannot_shadow_the_official_key(official, monkeypatch):
    """Otherwise 'signed by the maintainer' becomes 'signed by whoever edited your
    config', which is the one claim curation exists to make unforgeable."""
    fake = {integrity.OFFICIAL_PUBLISHER_ID: {
        "public_key": base64.b64encode(b"\x01" * 32).decode("ascii"),
        "label": "attacker", "fingerprint": "dead", "added": "now"}}
    monkeypatch.setattr(integrity, "_load_publishers", lambda: fake)

    got = integrity.trusted_publishers()[integrity.OFFICIAL_PUBLISHER_ID]
    assert got["label"] == "ELI Marketplace (official)"
    assert got["builtin"] is True


def test_the_official_key_cannot_be_untrusted(official):
    res = integrity.untrust_publisher(integrity.OFFICIAL_PUBLISHER_ID)
    assert res["ok"] is False
    assert "cannot be removed" in " ".join(res["problems"])


# ── enforcement ──────────────────────────────────────────────────────────────

SOURCE = b'"""t."""\nNAME = "testplugin"\ndef run(**kw):\n    return 1\n'


def _listing(**over):
    base = {
        "id": "testplugin", "name": "T", "version": "1.0.0",
        "description": "A test plugin.",
        "author": "a", "license": "MIT", "permissions": [],
        "sha256": integrity.sha256_of(SOURCE),
        "source": "https://plugins.example.org/plugins/testplugin.py",
        "registry": marketplace.OFFICIAL_REGISTRY_ID,
        "registry_label": "ELI Marketplace",
    }
    base.update(over)
    return base


def _preview(monkeypatch, listing):
    monkeypatch.setattr(marketplace, "_download",
                        lambda *a, **k: SOURCE, raising=False)
    return marketplace.preview_install(listing)


def test_signed_curated_listing_is_accepted(official, monkeypatch):
    listing = _listing(publisher_id=integrity.OFFICIAL_PUBLISHER_ID,
                       signature=_sign(official, SOURCE))
    res = _preview(monkeypatch, listing)
    # Assert it got PAST the curation gate, not merely that it failed elsewhere —
    # an invalid test manifest fails at stage 'listing' and would pass a bare
    # "stage != curation" check while proving nothing.
    assert res.get("stage") not in ("listing", "curation", "integrity"), (
        f"a correctly signed listing was refused: {res}")


def test_unsigned_curated_listing_is_refused(official, monkeypatch):
    res = _preview(monkeypatch, _listing())
    assert res["ok"] is False
    assert res["stage"] == "curation"
    assert "altered after approval" in " ".join(res["problems"])


def test_curated_listing_signed_by_the_wrong_key_is_refused(official, monkeypatch):
    """A valid signature from the wrong signer is still the wrong signer."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    other = Ed25519PrivateKey.generate()
    listing = _listing(publisher_id=integrity.OFFICIAL_PUBLISHER_ID,
                       signature=_sign(other, SOURCE))
    res = _preview(monkeypatch, listing)
    assert res["ok"] is False
    assert res["stage"] in ("integrity", "curation")


def test_tampered_file_under_a_valid_signature_is_refused(official, monkeypatch):
    listing = _listing(publisher_id=integrity.OFFICIAL_PUBLISHER_ID,
                       signature=_sign(official, SOURCE))
    monkeypatch.setattr(marketplace, "_download",
                        lambda *a, **k: SOURCE + b"\nimport os\n", raising=False)
    res = marketplace.preview_install(listing)
    assert res["ok"] is False, "an altered download must not install"


def test_community_listing_is_not_held_to_the_curated_bar(official, monkeypatch):
    """Unsigned on a community registry is ordinary, and must stay a warning."""
    listing = _listing(registry="somecommunity", registry_label="Some Community")
    res = _preview(monkeypatch, listing)
    assert res.get("stage") != "curation"


# ── switching the shipped registries off ─────────────────────────────────────

def _registry_file(tmp_path, monkeypatch, registries=()):
    import json
    p = tmp_path / "plugin_registries.json"
    if registries:
        p.write_text(json.dumps({"version": 1, "registries": list(registries)}),
                     encoding="utf-8")
    monkeypatch.setattr(marketplace, "_registries_path", lambda: p)
    return p


def _entry(registry_id):
    return next((r for r in marketplace.list_registries() if r["id"] == registry_id), None)


def test_switching_the_official_registry_off_sticks(official, tmp_path, monkeypatch):
    """It used to report success and change nothing: the switch was never written, and
    a stored entry under the official id is dropped on read."""
    _registry_file(tmp_path, monkeypatch, [
        {"id": "other", "url": "https://registry.example.org/index.json",
         "label": "Other", "enabled": True}])
    official_id = marketplace.OFFICIAL_REGISTRY_ID

    assert marketplace.set_registry_enabled(official_id, False)["ok"] is True
    assert _entry(official_id)["enabled"] is False
    # Another change rewrites the file; the switch must survive it.
    assert marketplace.remove_registry("other")["ok"] is True
    assert _entry(official_id)["enabled"] is False

    fetched = []
    monkeypatch.setattr(marketplace, "_fetch_one",
                        lambda reg, timeout=10: fetched.append(reg["id"]) or
                        {"ok": True, "plugins": [], "offline": False})
    marketplace.browse()
    assert official_id not in fetched, "a switched-off registry was still fetched"

    assert marketplace.set_registry_enabled(official_id, True)["ok"] is True
    assert _entry(official_id)["enabled"] is True


def test_removing_the_official_registry_sticks_until_it_is_added_back(
        official, tmp_path, monkeypatch):
    _registry_file(tmp_path, monkeypatch)
    official_id = marketplace.OFFICIAL_REGISTRY_ID

    assert marketplace.remove_registry(official_id)["ok"] is True
    assert _entry(official_id) is None
    assert marketplace.set_registry_enabled(marketplace.BUNDLED_REGISTRY_ID, True)["ok"]
    assert _entry(official_id) is None, "a later rewrite brought the removed registry back"

    wrong = marketplace.add_registry(official_id, "https://elsewhere.example.org/index.json")
    assert wrong["ok"] is False, "the official id must not name another address"
    back = marketplace.add_registry(official_id, marketplace.official_registry_url())
    assert back["ok"] is True
    entry = _entry(official_id)
    assert entry and entry["enabled"] is True and entry["curated"] is True


# ── MCP server listings ──────────────────────────────────────────────────────

def _mcp_listing(**over):
    base = {
        "id": "files_mcp", "kind": "mcp", "name": "Files (MCP)", "version": "1.0.0",
        "description": "Reads files under one folder.", "author": "a", "license": "MIT",
        "permissions": ["filesystem_read"],
        "mcp": {"transport": "stdio", "command": "npx",
                "args": ["-y", "example-files-server", "/srv/shared"]},
        "registry": marketplace.OFFICIAL_REGISTRY_ID,
        "registry_label": "ELI Marketplace",
    }
    base.update(over)
    return base


@pytest.fixture()
def started(monkeypatch):
    """Record install_server calls instead of starting anything."""
    from eli.plugins import mcp
    calls = []
    monkeypatch.setattr(mcp, "install_server",
                        lambda spec, **kw: calls.append(spec) or {"ok": True, "id": spec["id"]})
    return calls


def _signed_mcp(priv, **over):
    listing = _mcp_listing(**over)
    payload = integrity.mcp_listing_payload(listing)
    listing.update(sha256=integrity.sha256_of(payload),
                   publisher_id=integrity.OFFICIAL_PUBLISHER_ID,
                   signature=_sign(priv, payload))
    return listing


def test_unsigned_curated_mcp_listing_is_refused_before_it_starts(official, started):
    res = marketplace.install_mcp(_mcp_listing())
    assert res["ok"] is False and res["stage"] == "curation"
    assert started == [], "an unverified server definition was started"


def test_signed_curated_mcp_listing_is_installed(official, started):
    res = marketplace.install_mcp(_signed_mcp(official))
    assert res["ok"] is True, res
    assert [s["id"] for s in started] == ["files_mcp"]


def test_a_changed_server_definition_under_a_valid_signature_is_refused(official, started):
    """The signature covers the command, its arguments and the permissions."""
    listing = _signed_mcp(official)
    listing["mcp"] = dict(listing["mcp"], args=["-y", "example-files-server", "/"])
    assert marketplace.install_mcp(listing)["ok"] is False
    listing = _signed_mcp(official)
    listing["permissions"] = ["filesystem_read", "network"]
    assert marketplace.install_mcp(listing)["ok"] is False
    assert started == []


def test_community_mcp_listing_gets_the_plugin_integrity_check(official, started):
    unsigned = _mcp_listing(registry="somecommunity", registry_label="Some Community")
    assert marketplace.install_mcp(unsigned)["ok"] is True
    stale = dict(unsigned, sha256="0" * 64)
    res = marketplace.install_mcp(stale)
    assert res["ok"] is False and res["stage"] == "integrity"
    assert len(started) == 1


def test_an_mcp_listings_integrity_messages_name_an_mcp_server_and_its_definition(official, started):
    """An MCP listing has no file and is not a plugin; its warnings said 'This plugin is not signed'
    and spoke of the file the publisher intended."""
    unsigned = _mcp_listing(registry="somecommunity", registry_label="Some Community")
    told = [marketplace.install_mcp(unsigned)["warnings"],
            marketplace.install_mcp(dict(unsigned, sha256="0" * 64))["problems"],
            marketplace.install_mcp(_mcp_listing())["problems"]]          # curated, unsigned
    for lines in told:
        text = " ".join(lines).replace(unsigned["name"], "")                # the listing's own name
        assert "MCP server" in text or "server definition" in text, lines
        assert "plugin" not in text.lower() and "file" not in text.lower(), lines
    assert any("This MCP server is not signed" in w for w in told[0])
    plugin = integrity.assess(b"print('hi')\n", {"id": "p", "kind": "plugin"})
    assert any("This plugin is not signed" in w for w in plugin["warnings"])
    assert "server definition" in integrity.status_summary(integrity.VERIFIED_HASH_ONLY, unsigned)
