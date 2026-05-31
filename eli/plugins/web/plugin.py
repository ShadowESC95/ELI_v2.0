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

        msg = "\n".join(lines)
        return {
            "ok": True,
            "action": "WEB_SEARCH",
            "query": query,
            "results": results,
            "content": msg,
            "response": msg,
        }


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

    with DDGS() as ddgs:
        for item in ddgs.text(query, max_results=max_results):
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
        {"q": query, "format": "json"}
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


def _web_search_results(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """Canonical web-search entry point: SearXNG (if configured) → DuckDuckGo.

    SearXNG is preferred (self-hosted, not rate-limited, privacy-aligned).
    DuckDuckGo via the ddgs package is the fallback when SearXNG is absent or
    returns nothing.
    """
    try:
        results = _searxng_search(query, max_results=max_results)
    except Exception:
        results = []
    if results:
        return results
    try:
        return _duckduckgo_search(query, max_results=max_results)
    except Exception:
        return []


def execute(action: str, args: Dict[str, Any] | None = None) -> Dict[str, Any]:
    plugin = WebSearchPlugin()
    normalized = str(action or "").strip()
    return plugin.execute(normalized, args or {})


def get_plugin() -> WebSearchPlugin:
    return WebSearchPlugin()
