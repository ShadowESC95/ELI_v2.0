import ast
import importlib
from pathlib import Path


def test_open_url_is_executor_dispatch_backed():
    src = Path("eli/execution/executor_enhanced.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    actions = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue

        test = node.test

        if isinstance(test, ast.Compare):
            for comp in test.comparators:
                if isinstance(comp, ast.Constant) and isinstance(comp.value, str):
                    actions.add(comp.value.upper())

            for op, comp in zip(test.ops, test.comparators):
                if isinstance(op, ast.In) and isinstance(comp, (ast.Tuple, ast.List, ast.Set)):
                    for elt in comp.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            actions.add(elt.value.upper())

    assert "OPEN_URL" in actions


def test_open_url_helper_accepts_bare_domain(monkeypatch):
    ex = importlib.import_module("eli.execution.executor_enhanced")

    opened = {}

    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr(
        "webbrowser.open",
        lambda url, new=2: opened.setdefault("url", url) or True,
    )

    res = ex._eli_open_url_action("github.com")

    assert res["ok"] is True
    assert res["url"] == "https://github.com"
    assert opened["url"] == "https://github.com"


def test_open_url_helper_blocks_unsafe_schemes():
    ex = importlib.import_module("eli.execution.executor_enhanced")

    assert ex._eli_open_url_action("javascript:alert(1)")["ok"] is False
    assert ex._eli_open_url_action("file:///etc/passwd")["ok"] is False
    assert ex._eli_open_url_action("data:text/html,test")["ok"] is False


# ── the address behind a name or a reference ─────────────────────────────────

_TURNS = [
    {"role": "user", "content": "search nasa website"},
    {"role": "assistant", "content": "- *Official site:* https://www.nasa.gov/ (latest news)\n"
                                     "- *Live:* https://www.nasa.gov/nasa-live/ (launches).\n- Mobile: https://www.nasa.gov/?m=0"},
    {"role": "user", "content": "could you open that website in the browser please"},
]
_RESULTS = [
    {"title": "NASA - Wikipedia", "href": "https://en.m.wikipedia.org/wiki/NASA"},
    {"title": "NASA Live - NASA", "href": "https://www.nasa.gov/nasa-live/"},
    {"title": "NASA", "href": "https://www.nasa.gov/"},
]


def _search(results):
    return lambda query, max_results=8: results


def test_that_website_is_the_first_address_of_the_last_turn_that_gave_one():
    from eli.runtime import site_address as sa

    assert sa.referred_to(1, _TURNS) == "https://www.nasa.gov/"
    assert sa.referred_to(2, _TURNS) == "https://www.nasa.gov/nasa-live/"
    assert sa.referred_to(9, _TURNS) == "" and sa.referred_to(1, []) == ""


def test_a_named_site_is_found_in_the_conversation_then_on_the_web():
    from eli.runtime import site_address as sa

    assert sa.named("nasa", _TURNS, search=_search([])) == {"url": "https://www.nasa.gov/", "from": "this conversation"}
    assert sa.named("nasa", [], search=_search(_RESULTS)) == {"url": "https://www.nasa.gov/", "from": "a web search"}


def test_an_article_about_a_site_is_not_the_site():
    from eli.runtime import site_address as sa

    results = [{"title": "The New York Times - Wikipedia", "href": "https://en.wikipedia.org/wiki/The_New_York_Times"},
               {"title": "The New York Times - Breaking News, US News", "href": "https://www.nytimes.com/"}]
    assert sa.named("the new york times", [], search=_search(results))["url"] == "https://www.nytimes.com/"
    assert not sa.carries("nasa", "https://en.wikipedia.org/wiki/NASA")
    assert sa.carries("otter ai", "https://otter.ai/home") and sa.carries("bbc", "https://www.bbc.co.uk/news")


def test_no_address_found_is_said_and_nothing_is_opened(monkeypatch):
    from eli.runtime import site_address as sa
    ex = importlib.import_module("eli.execution.executor_enhanced")

    opened = []
    monkeypatch.setattr(ex, "_eli_open_url_action", lambda url=None, **kw: opened.append(url) or {"ok": True, "content": "x"})
    monkeypatch.setattr(sa, "named", lambda name, **kw: {"why": "a web search turned up no site of that name"})
    monkeypatch.setattr(sa, "referred_to", lambda which=1, **kw: "")

    res = ex._eli_open_named_site({"site": "zzqx"})
    assert res["ok"] is False and "no address for the zzqx website" in res["content"] and "no site of that name" in res["content"]
    res = ex._eli_open_named_site({"refers_to": "that website", "which": 1})
    assert res["ok"] is False and "No web address has come up" in res["content"]
    assert opened == []


def test_the_address_found_is_opened_and_the_reply_says_where_it_came_from(monkeypatch):
    from eli.runtime import site_address as sa
    ex = importlib.import_module("eli.execution.executor_enhanced")

    monkeypatch.setattr(ex, "_eli_open_url_action",
                        lambda url=None, **kw: {"ok": True, "action": "OPEN_URL", "url": url, "content": f"Opened URL: {url}"})
    monkeypatch.setattr(sa, "named", lambda name, **kw: {"url": "https://www.nasa.gov/", "from": "a web search"})

    res = ex._eli_open_named_site({"site": "nasa"})
    assert res["url"] == "https://www.nasa.gov/"
    assert res["content"] == "Opened URL: https://www.nasa.gov/ (the nasa site, from a web search)"
