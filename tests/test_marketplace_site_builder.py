"""The public shopfront is built from the same index.json the client fetches.

Two properties matter here and neither is cosmetic:

  * **The page cannot install anything.** A website that could trigger an install
    would make the browser the attack surface and the consent dialog spoofable.
    The page hands out an id; the desktop client does the fetching, verifying,
    scanning and asking.
  * **The page and the client read one file.** If the shopfront were generated
    from a separate source it could advertise a plugin the client refuses, or
    show permissions that differ from the ones the consent dialog asks for.

It is also fully self-contained: a store that distributes executable code should
not ship third-party JavaScript to the people evaluating it.
"""
from __future__ import annotations

import json
import re

import pytest

from tools.marketplace import build_site


REGISTRY = {
    "version": "1",
    "name": "Test registry",
    "plugins": [
        {"id": "risky_one", "name": "Risky", "version": "1.0.0",
         "description": "Runs things.", "author": "a", "license": "MIT",
         "permissions": ["process_exec"], "signature": "x", "publisher_id": "eli-marketplace"},
        {"id": "safe_one", "name": "Safe", "version": "2.0.0",
         "description": "Converts units.", "author": "b", "license": "MIT",
         "permissions": []},
    ],
}


@pytest.fixture()
def site(tmp_path):
    idx = tmp_path / "index.json"
    idx.write_text(json.dumps(REGISTRY), encoding="utf-8")
    out = tmp_path / "site"
    build_site.build(str(idx), str(out), "ELI Marketplace",
                     "plugins.geteli.tech", "https://github.com/x/y")
    return (out / "index.html").read_text(encoding="utf-8"), out


def test_the_page_has_no_install_button(site):
    html, _ = site
    lowered = html.lower()
    for forbidden in ("<form", "install-now", 'href="eli:', "onclick"):
        assert forbidden not in lowered, f"the shopfront must not be able to act: {forbidden}"
    assert "cannot install anything, by design" in html


def test_no_external_resources(site):
    """No CDN, no fonts, no analytics — nothing that phones home from the store."""
    html, _ = site
    for pat in (r'src=["\']https?://', r'href=["\']https?://fonts\.',
                r'@import\s+url\(', r'<link[^>]+stylesheet[^>]+https?://'):
        assert not re.search(pat, html, re.I), f"external resource matched {pat}"


def test_client_and_page_share_one_index(site):
    """The generator emits the same index.json it built the page from."""
    _, out = site
    shipped = json.loads((out / "index.json").read_text(encoding="utf-8"))
    assert shipped == REGISTRY


def test_permissions_are_shown_in_plain_english(site):
    html, _ = site
    assert "Runs other programs — unlimited access" in html
    assert "Asks for no permissions." in html


def test_high_risk_is_marked_and_sorted_last(site):
    html, _ = site
    assert 'data-risk="high"' in html and 'data-risk="low"' in html
    # Low risk sorts before high, so the safest listings are seen first.
    assert html.index('data-risk="low"') < html.index('data-risk="high"')


def test_unsigned_listings_are_visibly_flagged(site):
    """The client refuses these on the curated registry, so the shop window must
    not present one as ordinary."""
    html, _ = site
    assert "unsigned" in html and "signed" in html


def test_registry_url_uses_the_configured_domain(site):
    html, _ = site
    assert "plugins.geteli.tech/index.json" in html


def test_an_empty_registry_still_builds(tmp_path):
    idx = tmp_path / "index.json"
    idx.write_text(json.dumps({"version": "1", "plugins": []}), encoding="utf-8")
    out = tmp_path / "site"
    build_site.build(str(idx), str(out), "ELI Marketplace", "plugins.geteli.tech",
                     "https://github.com/x/y")
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "No plugins are listed yet" in html


def test_the_store_links_back_to_the_main_site(site):
    """The marketplace is a room in ELI's house, not a separate building. A visitor
    who lands on a plugin page must have an obvious way back to the product."""
    html, _ = site
    assert html.count("https://geteli.tech") >= 3, (
        "the store should link home from the brand, the nav and the footer")
    assert "geteli.tech#private" in html, "the privacy section should be reachable"


def test_the_brand_mark_is_a_link_home(site):
    html, _ = site
    i = html.index('class="brand"')
    assert 'href="https://geteli.tech"' in html[i - 120:i + 120]


def test_the_logo_is_embedded_not_linked(tmp_path):
    """The brand mark must not become the one outbound request on the page."""
    from pathlib import Path

    logo = Path("blueprints/Eli_Icon.png")
    if not logo.is_file():
        import pytest as _pt
        _pt.skip("logo not present in this checkout")

    idx = tmp_path / "index.json"
    idx.write_text(json.dumps(REGISTRY), encoding="utf-8")
    out = tmp_path / "site"
    build_site.build(str(idx), str(out), "ELI Marketplace", "plugins.geteli.tech",
                     "https://github.com/x/y", "https://geteli.tech", str(logo))
    html = (out / "index.html").read_text(encoding="utf-8")

    assert 'src="data:image/png;base64,' in html
    assert not re.search(r'<img[^>]+src=["\']https?://', html, re.I)


def test_a_missing_logo_falls_back_rather_than_failing(tmp_path, capsys):
    """A broken path must not take the whole deploy down."""
    idx = tmp_path / "index.json"
    idx.write_text(json.dumps(REGISTRY), encoding="utf-8")
    out = tmp_path / "site"
    build_site.build(str(idx), str(out), "ELI Marketplace", "plugins.geteli.tech",
                     "https://github.com/x/y", "https://geteli.tech",
                     str(tmp_path / "nope.png"))
    html = (out / "index.html").read_text(encoding="utf-8")
    assert '<span class="mark"' in html, "should fall back to the plain mark"
