"""Behaviour locks for web-search safety and query hygiene.

Observed live at 2.3.15:

  * An ordinary technical query returned adult results. None of the seven
    search providers was sent a safe-search parameter, so ELI inherited
    whatever the installed client defaulted to — a value this project never
    set or pinned.
  * The router passed the user's whole sentence through as the query text:
    'please open the browser and search for QFT. OPEN A BROWSER SEARCH PAGE'
    was sent verbatim to the engine, which then matched on "open", "browser"
    and "page" rather than on QFT.

Screening is host-based on purpose. A snippet-keyword blocklist would bury
legitimate medical and biological results, so the locks below assert that
those still come through.
"""
import inspect

import pytest

from eli.plugins.web import plugin as web


# ── every provider must ask for strict filtering ───────────────────────────
@pytest.mark.parametrize("fn_name,marker", [
    ("_duckduckgo_search", "safesearch"),
    ("_searxng_search", "safesearch"),
    ("_duckduckgo_html_search", "kp=1"),
    ("_ddg_lite_search", '"kp"'),
    ("_bing_html_search", "adlt=strict"),
])
def test_provider_requests_safe_search(fn_name, marker):
    src = inspect.getsource(getattr(web, fn_name))
    assert marker in src, f"{fn_name} no longer requests safe search ({marker!r})"


def test_choke_point_filters_and_cleans():
    src = inspect.getsource(web._web_search_results)
    assert "_filter_results(" in src, "results are no longer screened at the choke point"
    assert "_clean_search_query(" in src, "query is no longer cleaned at the choke point"


# ── screening: adult hosts out, everything else untouched ──────────────────
@pytest.mark.parametrize("url", [
    "https://pornhub.com/view", "https://www.xvideos.com/a", "https://xnxx.com/b",
    "https://rule34.xxx/", "https://nhentai.net/g/1", "https://onlyfans.com/u",
    "https://chaturbate.com/", "https://example.adult/x", "https://foo.porn/y",
    "https://hentaihaven.org/z", "https://camgirl-site.com/",
])
def test_adult_hosts_are_screened(url):
    assert web._is_adult_result({"href": url}) is True, f"{url} not screened"


@pytest.mark.parametrize("url", [
    "https://en.wikipedia.org/wiki/Quantum_field_theory",
    "https://plato.stanford.edu/entries/quantum-field-theory/",
    "https://www.essex.ac.uk/departments/physics",       # contains "sex"
    "https://www.sussex.ac.uk/research",                  # contains "sex"
    "https://middlesex.gov.uk/",                          # contains "sex"
    "https://www.nhs.uk/conditions/breast-cancer/",       # medical
    "https://sussex.gov.uk/health/sexual-health",         # public health
    "https://www.cambridge.org/core/books",               # contains "cam"
    "https://pubmed.ncbi.nlm.nih.gov/12345/",
    "https://arxiv.org/abs/hep-th/9711200",
])
def test_legitimate_hosts_are_never_screened(url):
    assert web._is_adult_result({"href": url}) is False, f"{url} wrongly screened"


def test_screening_survives_junk_input():
    for item in ({}, {"href": ""}, {"href": "not a url"}, {"href": None}):
        assert web._is_adult_result(item) is False


def test_filter_removes_only_adult_entries():
    results = [
        {"href": "https://en.wikipedia.org/wiki/QFT", "title": "QFT"},
        {"href": "https://pornhub.com/x", "title": "nope"},
        {"href": "https://arxiv.org/abs/1", "title": "paper"},
    ]
    kept = web._filter_results(results)
    assert [r["title"] for r in kept] == ["QFT", "paper"]


# ── query hygiene ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("raw,expected", [
    ("please open the browser and search for QFT. OPEN A BROWSER SEARCH PAGE", "QFT"),
    ("do a web search on QFT and open the browser", "QFT"),
    ("on QFT and open the browser", "QFT"),
    ("search the web for QFT", "QFT"),
    ("google quantum field theory", "quantum field theory"),
    ("look up the history of quantum field theory", "the history of quantum field theory"),
])
def test_instruction_wrapper_is_stripped(raw, expected):
    assert web._clean_search_query(raw) == expected


@pytest.mark.parametrize("raw", [
    "QFT",
    "what is the boiling point of mercury",
    "Niels Bohr and Max Planck correspondence 1913",
])
def test_plain_queries_are_left_alone(raw):
    assert web._clean_search_query(raw) == raw


def test_cleaning_never_empties_a_query():
    """A short query beats an empty one — an emptied query searches for nothing."""
    for raw in ("search", "open the browser", "please", "find"):
        assert web._clean_search_query(raw).strip(), f"{raw!r} cleaned to nothing"


# ── the toggle has to exist where a user can reach it ──────────────────────
def _gui_src() -> str:
    from pathlib import Path
    return Path("eli/gui/eli_pro_audio_gui_v2_0.py").read_text(encoding="utf-8")


def test_safe_search_has_a_gui_toggle():
    src = _gui_src()
    assert "web_safe_search_checkbox" in src, "no safe-search control in the GUI"
    assert 'self._section_card(vbox, "WEB SEARCH")' in src, "no WEB SEARCH settings card"


def test_safe_search_toggle_is_loaded_and_saved():
    src = _gui_src()
    assert 's.get("web_safe_search", True)' in src, "toggle is never loaded back"
    assert '"web_safe_search": bool(' in src, "toggle is never persisted"


def test_safe_search_toggle_applies_without_a_restart():
    src = _gui_src()
    assert "_apply_web_safe_search" in src, "toggle only takes effect on Save"
    assert '_cfg.set("web_safe_search"' in src, "toggle does not write the setting"


def test_safe_search_defaults_to_on():
    """A redistributable assistant must not ship with filtering off."""
    import inspect
    assert "True" in inspect.getsource(web._safe_search_enabled)
