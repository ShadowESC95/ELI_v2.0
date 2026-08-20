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
