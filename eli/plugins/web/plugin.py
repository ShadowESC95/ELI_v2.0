from __future__ import annotations

from typing import Any, Dict, List


try:
    from eli.plugins.base.base import Plugin
except Exception:
    class Plugin:
        actions: Dict[str, Any] = {}

        def execute(self, action: str, args: Dict[str, Any] | None = None) -> Dict[str, Any]:
            args = args or {}
            key = str(action or "").strip()
            handler = self.actions.get(key) or self.actions.get(key.upper()) or self.actions.get(key.lower())
            if not handler:
                return {
                    "ok": False,
                    "action": action,
                    "error": f"Unsupported plugin action: {action}",
                    "content": f"Unsupported plugin action: {action}",
                    "response": f"Unsupported plugin action: {action}",
                }
            return handler(args)


PLUGIN_ID = "web"
ACTIONS = ["WEB_SEARCH"]


class WebSearchPlugin(Plugin):
    name = "web"
    description = "DuckDuckGo web search plugin"

    def __init__(self):
        # Include both canonical and manager-normalised aliases.
        # manager.execute("web", "WEB_SEARCH", args) may pass "web_search".
        self.actions = {
            "WEB_SEARCH": self.web_search,
            "web_search": self.web_search,
            "search": self.web_search,
            "web": self.web_search,
        }

    def web_search(self, args: Dict[str, Any] | None = None) -> Dict[str, Any]:
        args = args or {}
        query = (
            args.get("query")
            or args.get("q")
            or args.get("text")
            or args.get("search")
            or ""
        )
        query = str(query).strip()

        if not query:
            msg = "No web search query provided."
            return {
                "ok": False,
                "action": "WEB_SEARCH",
                "error": msg,
                "content": msg,
                "response": msg,
            }

        max_results = args.get("max_results", args.get("limit", 5))
        try:
            max_results = int(max_results)
        except Exception:
            max_results = 5
        max_results = max(1, min(max_results, 10))

        # Net gate first — never touch the network (or confabulate) when offline.
        # netguard is a core module (always importable) and should_block_network()
        # already fails closed, so this needs no defensive try/except.
        from eli.core.netguard import should_block_network, offline_response
        if should_block_network():
            return offline_response("WEB_SEARCH", "search the web")

        try:
            results = _web_search_results(query, max_results=max_results)
        except Exception as exc:
            msg = f"Web search failed: {exc}"
            return {
                "ok": False,
                "action": "WEB_SEARCH",
                "query": query,
                "error": msg,
                "content": msg,
                "response": msg,
            }

        if not results:
            msg = f"No web results found for: {query}"
            return {
                "ok": True,
                "action": "WEB_SEARCH",
                "query": query,
                "results": [],
                "content": msg,
                "response": msg,
            }

        lines = [f"Web results for: {query}"]
        for i, item in enumerate(results, 1):
            title = item.get("title") or item.get("name") or "Untitled"
            href = item.get("href") or item.get("url") or ""
            body = item.get("body") or item.get("snippet") or ""
            if href and body:
                lines.append(f"{i}. {title}\n   {href}\n   {body}")
            elif href:
                lines.append(f"{i}. {title}\n   {href}")
            else:
                lines.append(f"{i}. {title}")

        # ALSO open the results in a real browser — "search the web" summarises AND opens
        # the page so the user can click through. Best-effort; never fails the search.
        import urllib.parse as _up
        open_url = "https://duckduckgo.com/?q=" + _up.quote(query)
        opened = _open_in_browser(open_url)
        if opened:
            lines.append(f"\n(Opened the search page in your browser: {open_url})")

        msg = "\n".join(lines)
        return {
            "ok": True,
            "action": "WEB_SEARCH",
            "query": query,
            "results": results,
            "opened_url": open_url,   # web UI can also open this in a new tab
            "browser_opened": opened,
            "content": msg,
            "response": msg,
        }


def _open_in_browser(url: str) -> bool:
    """Open a URL in the user's default browser on the ELI host. Tries ELI's os_controller
    (knows the desktop session), then stdlib webbrowser. Best-effort → bool."""
    if not url:
        return False
    try:
        from eli.perception import os_controller as _osc
        for _m in ("open_url", "open_browser", "launch_url", "open_in_browser"):
            fn = getattr(_osc, _m, None)
            if callable(fn):
                try:
                    fn(url)
                    return True
                except Exception:
                    pass
    except Exception:
        pass
    try:
        import webbrowser
        return bool(webbrowser.open(url, new=2))
    except Exception:
        return False


# ─────────────────────────── SAFE SEARCH ───────────────────────────────────
# Live at 2.3.15 an ordinary technical query returned adult results. None of
# the seven providers below was sent a safe-search parameter, so ELI inherited
# whatever the installed client happened to default to — a value this project
# neither sets nor pins. Two layers now apply: every provider is asked for
# strict filtering, and the merged results are screened again at the single
# choke point in _web_search_results, because a scraped endpoint can ignore
# the request entirely.
#
# Screening is deliberately host-based rather than body-keyword based. A
# keyword blocklist over snippets would suppress legitimate medical,
# anatomical and biological results, which is precisely the kind of query
# this assistant exists to answer.

def _safe_search_enabled() -> bool:
    try:
        from eli.core.config import get as _cfg_get
        return bool(_cfg_get("web_safe_search", True))
    except Exception:
        return True


# Host *labels* (split on dots/hyphens) that identify adult sites. Matching
# whole labels rather than substrings keeps "essex.ac.uk", "sussex.gov.uk"
# and "cambridge.org" out of the filter.
_ADULT_LABELS = frozenset({
    "porn", "porno", "pornos", "xxx", "sex", "sexy", "nsfw", "hentai",
    "nude", "nudes", "camgirl", "camgirls", "escort", "escorts", "fetish",
    "milf", "boobs", "tits", "adultfilm", "cumshots",
})
# Label prefixes — "pornhub", "xhamster", "hentaihaven" are single labels.
_ADULT_LABEL_PREFIXES = ("porn", "hentai", "xxx", "camgirl", "sexcam", "nsfw")
_ADULT_TLDS = (".xxx", ".adult", ".porn", ".sex")
_ADULT_HOSTS = frozenset({
    "pornhub.com", "xvideos.com", "xnxx.com", "redtube.com", "youporn.com",
    "xhamster.com", "spankbang.com", "eporner.com", "tube8.com",
    "motherless.com", "chaturbate.com", "stripchat.com", "bongacams.com",
    "onlyfans.com", "fansly.com", "brazzers.com", "nhentai.net",
    "e-hentai.org", "rule34.xxx", "erome.com", "fapello.com", "thothub.to",
})


def _is_adult_result(item: Dict[str, Any]) -> bool:
    """True when a result's URL identifies an adult site."""
    import urllib.parse as _up
    href = str((item or {}).get("href") or (item or {}).get("url") or "").strip()
    if not href:
        return False
    try:
        host = (_up.urlparse(href).hostname or "").lower()
    except Exception:
        return False
    if not host:
        return False
    if host.startswith("www."):
        host = host[4:]
    if host in _ADULT_HOSTS:
        return True
    if any(host.endswith(tld) for tld in _ADULT_TLDS):
        return True
    import re as _re
    for label in _re.split(r"[.\-_]", host):
        if not label:
            continue
        if label in _ADULT_LABELS:
            return True
        if any(label.startswith(p) for p in _ADULT_LABEL_PREFIXES):
            return True
    return False


def _filter_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Backstop screen applied to whatever a provider actually returned."""
    if not _safe_search_enabled():
        return results
    return [r for r in (results or []) if not _is_adult_result(r)]


# Command wrappers the router leaves attached to the query. Live examples:
#   "please open the browser and search for QFT. OPEN A BROWSER SEARCH PAGE"
#   "on QFT and open the browser"
# were sent verbatim to the search engine as the query text.
_QUERY_LEAD_PATTERNS = (
    r"^(?:hey\s+)?(?:eli|assistant)[,\s]+",
    r"^(?:please|pls|kindly)\s+",
    r"^(?:can|could|would|will)\s+you\s+(?:please\s+)?",
    r"^(?:go\s+)?(?:and\s+)?(?:do|run|perform|make|start)\s+(?:a|an|the)?\s*",
    r"^(?:open|launch|start)\s+(?:up\s+)?(?:a|an|the)?\s*(?:web\s+)?browser\s*"
    r"(?:and\s+)?(?:search|look\s*up|find)?\s*(?:for|about|on)?\s*",
    r"^(?:web|google|internet|online|duckduckgo|ddg)\s+",
    r"^(?:search|look\s*up|lookup|find|google|browse)\s+",
    r"^(?:for|about|on|the\s+web\s+for)\s+",
)
_QUERY_TAIL_PATTERNS = (
    r"\s*(?:,|\.|and)?\s*(?:then\s+)?open\s+(?:a|an|the)?\s*(?:web\s+)?browser"
    r"(?:\s+search)?(?:\s+page)?\s*\.?$",
    r"\s*(?:,|\.|and)?\s*(?:then\s+)?(?:show|display)\s+(?:it|them|the\s+results)"
    r"(?:\s+in\s+(?:a|the)\s+browser)?\s*\.?$",
    r"\s*(?:please|thanks|thank\s+you|ta)\s*[.!]*$",
)


def _clean_search_query(text: str) -> str:
    """Strip the instruction wrapper so the engine receives the actual subject.

    Falls back to the original whenever cleaning would leave nothing useful —
    a short query is worth more than an empty one.
    """
    import re as _re
    original = str(text or "").strip()
    if not original:
        return ""
    q = original
    # A shouted restatement tacked onto the end ("… OPEN A BROWSER SEARCH PAGE")
    # is an instruction to ELI, not part of the subject.
    q = _re.sub(r"[.!?]\s+[A-Z][A-Z\s]{6,}$", "", q).strip()
    for _ in range(4):
        before = q
        for pat in _QUERY_LEAD_PATTERNS:
            q = _re.sub(pat, "", q, flags=_re.I).strip()
        for pat in _QUERY_TAIL_PATTERNS:
            q = _re.sub(pat, "", q, flags=_re.I).strip()
        if q == before:
            break
    q = _re.sub(r"\s+", " ", q).strip(" \t\n,.;:!?-").strip()
    if len(q) < 2:
        return original
    return q


def _duckduckgo_search(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """
    Supports both newer and older duckduckgo-search package layouts.
    """
    try:
        from duckduckgo_search import DDGS
    except Exception as first_exc:
        try:
            from ddgs import DDGS
        except Exception:
            raise first_exc

    out: List[Dict[str, Any]] = []

    safe = "on" if _safe_search_enabled() else "off"
    with DDGS() as ddgs:
        try:
            items = ddgs.text(query, max_results=max_results, safesearch=safe)
        except TypeError:
            # Older/newer layouts that do not expose the keyword — the
            # choke-point filter in _web_search_results still applies.
            items = ddgs.text(query, max_results=max_results)
        for item in items:
            out.append(dict(item))

    return out


def _searxng_search(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """Query a configured SearXNG instance via its JSON API.

    Returns [] when no instance is configured or the request fails, so the
    caller falls back to DuckDuckGo. Instance URL comes from the ELI_SEARXNG_URL
    env var or the `searxng_url` setting (e.g. "http://localhost:8888").
    """
    import os
    import json as _json
    import urllib.parse
    import urllib.request

    base = (os.environ.get("ELI_SEARXNG_URL") or "").strip()
    if not base:
        try:
            from eli.core.config import get as _cfg_get
            base = str(_cfg_get("searxng_url", "") or "").strip()
        except Exception:
            base = ""
    if not base:
        return []

    url = base.rstrip("/") + "/search?" + urllib.parse.urlencode(
        {"q": query, "format": "json",
         "safesearch": "2" if _safe_search_enabled() else "0"}
    )
    req = urllib.request.Request(
        url, headers={"User-Agent": "ELI-AI-Assistant/1.0 (local; educational)"}
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            data = _json.loads(r.read().decode("utf-8", errors="replace"))
    except Exception:
        return []

    out: List[Dict[str, Any]] = []
    for item in (data.get("results") or [])[:max_results]:
        href = item.get("url") or item.get("href") or ""
        title = item.get("title") or ""
        body = item.get("content") or item.get("snippet") or ""
        if title or href:
            out.append({"title": title, "href": href, "body": body})
    return out


def _duckduckgo_html_search(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """Stdlib-only DuckDuckGo HTML scrape — NO pip package required, so web search
    works on a fresh install without `duckduckgo_search`/`ddgs`. Network-gated via
    netguard (offline → OfflineError propagates; caller is already gated)."""
    import re as _re
    import html as _html
    import urllib.parse as _up
    import urllib.request as _ur
    try:
        from eli.core.netguard import guarded_urlopen as _open
    except Exception:
        _open = lambda req, timeout=10: _ur.urlopen(req, timeout=timeout)

    url = ("https://html.duckduckgo.com/html/?q=" + _up.quote(query)
           + ("&kp=1" if _safe_search_enabled() else ""))
    req = _ur.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0",
    })
    with _open(req, timeout=10) as r:
        page = r.read().decode("utf-8", errors="replace")

    def _strip(s: str) -> str:
        return _html.unescape(_re.sub(r"<[^>]+>", "", s or "")).strip()

    # Pull the snippet that follows each result title. DDG renders it as
    # <a class="result__snippet">…</a> (sometimes a <div>). Without it the
    # result is just a bare title/URL and the model has nothing to ground on —
    # which is exactly how an "album release date" query came back with no real
    # info and the model then guessed. Index snippet positions so each title is
    # paired with the snippet that comes right after it.
    _snips = [(mm.start(), _strip(mm.group(1)))
              for mm in _re.finditer(
                  r'<(?:a|div)[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</(?:a|div)>',
                  page, _re.S)]

    out: List[Dict[str, Any]] = []
    for m in _re.finditer(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', page, _re.S):
        href = _html.unescape(m.group(1))
        title = _strip(m.group(2))
        # DDG wraps real URLs in a redirect: //duckduckgo.com/l/?uddg=<encoded>
        _mu = _re.search(r"uddg=([^&]+)", href)
        if _mu:
            href = _up.unquote(_mu.group(1))
        # First snippet appearing after this title in the page.
        body = ""
        for _pos, _txt in _snips:
            if _pos > m.start() and _txt:
                body = _txt
                break
        if title and href:
            out.append({"title": title, "href": href, "body": body})
        if len(out) >= max_results:
            break
    return out


def _http_get(url: str, timeout: int = 10, data: bytes | None = None) -> str:
    """Guarded HTTP GET/POST → decoded text. Routes through netguard so offline is
    enforced; a realistic browser UA reduces bot-blocking. Returns "" on any failure."""
    import urllib.request as _ur
    try:
        from eli.core.netguard import guarded_urlopen as _open
    except Exception:
        _open = lambda req, timeout=10: _ur.urlopen(req, timeout=timeout)
    req = _ur.Request(url, data=data, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0",
        "Accept-Language": "en-US,en;q=0.9",
    })
    try:
        with _open(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def _strip_html(s: str) -> str:
    import re as _re, html as _html
    return _html.unescape(_re.sub(r"<[^>]+>", "", s or "")).strip()


def _ddg_lite_search(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """lite.duckduckgo.com — a stripped endpoint that survives when the main DDG is
    rate-limited. Independent enough to be worth trying before non-DDG engines."""
    import re as _re, html as _html, urllib.parse as _up
    _form = {"q": query}
    if _safe_search_enabled():
        _form["kp"] = "1"
    page = _http_get("https://lite.duckduckgo.com/lite/", data=_up.urlencode(_form).encode())
    out: List[Dict[str, Any]] = []
    for m in _re.finditer(r'<a[^>]+class="result-link"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', page, _re.S):
        href = _html.unescape(m.group(1)); _mu = _re.search(r"uddg=([^&]+)", href)
        if _mu: href = _up.unquote(_mu.group(1))
        t = _strip_html(m.group(2))
        if t and href.startswith("http"):
            out.append({"title": t, "href": href, "body": ""})
        if len(out) >= max_results: break
    return out


def _bing_html_search(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """Bing HTML — a fully independent index from DuckDuckGo, so it works when DDG
    blocks the IP. Bing wraps real URLs in a /ck/a?…&u=a1<base64url> redirect, which we
    decode back to the destination. Titles come from the result <h2>."""
    import re as _re, urllib.parse as _up, base64 as _b64, html as _html
    page = _http_get("https://www.bing.com/search?q=" + _up.quote(query) + "&setlang=en"
                     + ("&adlt=strict" if _safe_search_enabled() else ""))
    def _real(href: str) -> str:
        mu = _re.search(r'[?&]u=a1([^&]+)', href)
        if not mu:
            return href
        b = mu.group(1); b += "=" * (-len(b) % 4)
        try:
            return _b64.urlsafe_b64decode(b).decode("utf-8", "replace")
        except Exception:
            return ""
    out: List[Dict[str, Any]] = []
    # Each organic result is an <li class="b_algo"> … <h2><a href="…">Title</a></h2> … <p>snippet</p>
    for blk in _re.finditer(r'<li class="b_algo".*?</li>', page, _re.S):
        b = blk.group(0)
        m = _re.search(r'<h2>.*?<a [^>]*href="([^"]+)"[^>]*>(.*?)</a>', b, _re.S)
        if not m:
            continue
        href = _real(_html.unescape(m.group(1))); title = _strip_html(m.group(2))
        ps = _re.search(r'<p[^>]*>(.*?)</p>', b, _re.S)
        body = _strip_html(ps.group(1)) if ps else ""
        if title and href.startswith("http"):
            out.append({"title": title, "href": href, "body": body})
        if len(out) >= max_results:
            break
    return out


def _ddg_instant_answer(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """DuckDuckGo Instant Answer JSON API — a DIFFERENT endpoint from the search scrape,
    far less rate-limited, returns clean structured facts. The Abstract + RelatedTopics
    are excellent grounding, so this catches the exact 'model would otherwise guess a
    fact' case even when the HTML search paths are blocked."""
    import json as _json, urllib.parse as _up
    raw = _http_get("https://api.duckduckgo.com/?" + _up.urlencode(
        {"q": query, "format": "json", "no_html": 1, "no_redirect": 1, "t": "eli"}))
    if not raw:
        return []
    try:
        d = _json.loads(raw)
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    if d.get("AbstractText"):
        out.append({"title": d.get("Heading") or query,
                    "href": d.get("AbstractURL") or "",
                    "body": d.get("AbstractText")})
    for t in (d.get("RelatedTopics") or []):
        if len(out) >= max_results:
            break
        if isinstance(t, dict) and t.get("Text"):
            out.append({"title": (t.get("Text") or "")[:80],
                        "href": (t.get("FirstURL") or ""),
                        "body": t.get("Text") or ""})
    return out


def _wikipedia_search(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """Wikipedia API — not a general web search, but rock-solid and never rate-limited
    for factual/definitional queries ('what is X'), which is exactly where the model
    otherwise guesses. Great grounding source of last resort."""
    import json as _json, urllib.parse as _up
    raw = _http_get("https://en.wikipedia.org/w/api.php?" + _up.urlencode({
        "action": "query", "list": "search", "srsearch": query,
        "format": "json", "srlimit": max_results, "srprop": "snippet",
    }))
    if not raw:
        return []
    try:
        hits = (_json.loads(raw).get("query") or {}).get("search") or []
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for h in hits[:max_results]:
        title = h.get("title") or ""
        out.append({
            "title": title,
            "href": "https://en.wikipedia.org/wiki/" + _up.quote((title).replace(" ", "_")),
            "body": _strip_html(h.get("snippet") or ""),
        })
    return out


def _web_search_results(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """Canonical web-search entry point: SearXNG (if configured) → DuckDuckGo
    package → stdlib DuckDuckGo HTML scrape (no dependency).

    SearXNG is preferred (self-hosted, not rate-limited, privacy-aligned).
    DuckDuckGo via the ddgs package is the fallback when SearXNG is absent or
    returns nothing.

    OFFLINE GATE (defense-in-depth): this is the single choke point every web-search
    caller funnels through, so the Net toggle is enforced HERE — not only at the
    executor. The `ddgs`/`duckduckgo_search` package drives libcurl (curl_cffi/primp)
    at the C/Rust level, which does NOT pass through Python's socket layer, so the
    process-wide socket guard cannot see it. Without this check an offline box would
    still reach the network via that path. Fail closed.
    """
    from eli.core.netguard import should_block_network, OfflineError
    if should_block_network():
        raise OfflineError("web search blocked: network access is off (Net toggle)")

    # Try INDEPENDENT providers in order until one returns results. This is what makes
    # search bulletproof: when DuckDuckGo rate-limits the IP (every DDG-based path fails
    # at once), the non-DDG engines (Bing, Mojeek) and Wikipedia still deliver. Order =
    # best-quality/least-limited first; Wikipedia last as a factual safety net.
    providers = (
        ("searxng",   _searxng_search),          # self-hosted, unlimited (if configured)
        ("ddg",       _duckduckgo_search),        # ddgs package, if installed
        ("ddg_html",  _duckduckgo_html_search),   # stdlib DDG scrape
        ("ddg_lite",  _ddg_lite_search),          # DDG lite endpoint (survives some blocks)
        ("ddg_ia",    _ddg_instant_answer),       # DDG JSON API (clean facts, less limited)
        ("bing",      _bing_html_search),         # independent index (best-effort scrape)
        ("wikipedia", _wikipedia_search),         # factual safety net (never rate-limited)
    )
    # The router hands through whatever the user said, wrapper and all, so the
    # instruction is stripped here — once, for every provider and every caller.
    query = _clean_search_query(query)

    import time as _t
    # Two passes: first quick sweep, then a single retry of the transient engines with a
    # short backoff (covers momentary rate-limit blips) before giving up.
    for _attempt in range(2):
        for _name, _fn in providers:
            try:
                results = _fn(query, max_results=max_results)
            except Exception:
                results = []
            # Screen before accepting: a provider that ignored the safe-search
            # request must not be able to short-circuit the remaining engines.
            results = _filter_results(results)
            if results:
                return results
        if _attempt == 0:
            _t.sleep(1.2)
    return []


def execute(action: str, args: Dict[str, Any] | None = None) -> Dict[str, Any]:
    plugin = WebSearchPlugin()
    normalized = str(action or "").strip()
    return plugin.execute(normalized, args or {})


def get_plugin() -> WebSearchPlugin:
    return WebSearchPlugin()
