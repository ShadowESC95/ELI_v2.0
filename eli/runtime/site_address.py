"""The address behind a name or a reference.

"open nasa website" was offered as a program to install, and "open that website in the
browser", said straight after a reply that listed https://www.nasa.gov/, opened a search for
the words "that website". An address is never guessed (NASA is nasa.gov, not nasa.com). It is
taken from what was said in the conversation, then from a web search whose result carries the
name, and when neither has it the caller is told so.
"""
from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from eli.utils.log import get_logger

log = get_logger(__name__)

_ADDRESS = re.compile(r"https?://[^\s<>\"'`\]\[)(}{|\\^]+", re.I)
_RECENT_S = 1800.0
_SMALL_WORDS = frozenset(("the", "a", "an", "of", "and", "for", "official", "my", "our"))


def addresses_in(text: Any) -> List[str]:
    """The web addresses written in a text, in order, each once."""
    found: List[str] = []
    for hit in _ADDRESS.findall(str(text or "")):
        url = hit.rstrip(".,;:!?*_'\"”’…")
        if url not in found and urlparse(url).hostname:
            found.append(url)
    return found


def _recent_turns() -> List[Dict[str, Any]]:
    try:
        from eli.kernel import request_context
        from eli.memory import get_memory
        who = str(request_context.user_id_var.get() or "") or None
        return list(get_memory().get_recent_conversation(limit=12, user_id=who, since=time.time() - _RECENT_S) or [])
    except Exception:
        log.debug("recent conversation unavailable for an address", exc_info=True)
        return []


def referred_to(which: int = 1, turns: Optional[List[Dict[str, Any]]] = None) -> str:
    """The address "that website" points at: of the latest turn that named any, the first, or
    the `which`-th when the reference counts ("the second link"). "" when none was named."""
    for turn in reversed(_recent_turns() if turns is None else turns):
        named = addresses_in((turn or {}).get("content"))
        if named:
            return named[which - 1] if 0 < which <= len(named) else ""
    return ""


def _words(name: Any) -> List[str]:
    return [w for w in re.findall(r"[a-z0-9]+", str(name or "").lower()) if w not in _SMALL_WORDS]


def _site_forms(url: str) -> List[str]:
    """The host's own name, without and with its ending: "www.nasa.gov" -> nasa, nasagov;
    "otter.ai" -> otter, otterai."""
    labels = (urlparse(url).hostname or "").lower().split(".")
    if labels and labels[0] in ("www", "m", "mobile"):
        labels = labels[1:]
    bare = list(labels)
    while len(bare) > 1 and len(bare[-1]) <= 3:  # gov, com, co.uk, org.au
        bare = bare[:-1]
    return ["".join(re.findall(r"[a-z0-9]+", "".join(part))) for part in (bare, labels)]


def carries(name: Any, url: str) -> bool:
    """Whether the address is the named site's own: its host is the name, or holds it."""
    whole = "".join(_words(name))
    if not whole:
        return False
    bare, full = _site_forms(url)
    return whole in (bare, full) or (len(whole) >= 3 and len(bare) >= 2 and whole in bare)


def _root(url: str) -> str:
    at = urlparse(url)
    return f"{at.scheme}://{at.netloc}/"


def named(name: Any, turns: Optional[List[Dict[str, Any]]] = None, search=None) -> Dict[str, str]:
    """{"url", "from"} for a site known by name, or {"why": ...} when no address was found.

    The conversation is read first, then the web. A search result counts when its host carries
    the name; failing that, when its title holds every word of the name and it is a site's
    front page ("The New York Times" at nytimes.com), which an article about the site is not.
    """
    words = _words(name)
    if not words:
        return {"why": "no site was named"}
    for turn in reversed(_recent_turns() if turns is None else turns):
        own = [u for u in addresses_in((turn or {}).get("content")) if carries(name, u)]
        if own:
            return {"url": min(own, key=len), "from": "this conversation"}
    try:
        if search is None:
            from eli.plugins.web.plugin import _web_search_results as search
        results = list(search(f"{' '.join(words)} official website", max_results=8) or [])
    except Exception as exc:
        log.debug("no web search for the address of %s", name, exc_info=True)
        off = type(exc).__name__ == "OfflineError"
        return {"why": "network access is switched off" if off else "the web search did not run"}
    urls = [(str(r.get("href") or r.get("url") or ""), str(r.get("title") or "").lower()) for r in results if isinstance(r, dict)]
    for url, _title in urls:
        if url.startswith("http") and carries(name, url):
            return {"url": _root(url), "from": "a web search"}
    for url, title in urls:
        front_page = url.startswith("http") and urlparse(url).path in ("", "/")
        if front_page and all(re.search(rf"\b{re.escape(w)}\b", title) for w in words):
            return {"url": url, "from": "a web search"}
    return {"why": "a web search turned up no site of that name"}


__all__ = ["addresses_in", "referred_to", "carries", "named"]
