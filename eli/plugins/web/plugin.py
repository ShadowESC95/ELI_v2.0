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
            results = _duckduckgo_search(query, max_results=max_results)
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


def execute(action: str, args: Dict[str, Any] | None = None) -> Dict[str, Any]:
    plugin = WebSearchPlugin()
    normalized = str(action or "").strip()
    return plugin.execute(normalized, args or {})


def get_plugin() -> WebSearchPlugin:
    return WebSearchPlugin()
