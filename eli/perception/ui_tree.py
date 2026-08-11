"""Accessibility-tree UI targeting (Linux / AT-SPI).

Why this exists
---------------
`screen_locator` finds things on screen by OCR: screenshot → pytesseract word boxes →
fuzzy text match → click the centre point. That works on anything that renders text,
which is its real strength, but it is blind to everything that makes a UI a UI:

* it cannot tell a **button** named "Save" from the word "Save" in a changelog;
* it cannot see whether a control is **disabled**, checked, or focused;
* icon-only toolbars and custom-drawn widgets are invisible to it;
* it clicks a **coordinate**, so a window moving between locate and click mis-clicks;
* and it can never confirm the click did anything — the same "claimed without
  verifying" failure mode that has bitten this codebase repeatedly.

AT-SPI exposes the real widget tree: role, name, bounds, state, and the actions a
control advertises. Asking for "the button named Save" either resolves or does not.

Scope and honesty
-----------------
This is a **strategy**, not a replacement. Coverage is uneven in the wild — GTK is
good, Electron often needs `--force-renderer-accessibility`, some Qt apps expose
almost nothing — so `screen_locator` tries this first and falls back to OCR. Every
entry point degrades to an empty result rather than raising, so a machine without
AT-SPI (or a Wayland session that restricts it) behaves exactly as before.

Returns the same Box shape `screen_locator` already produces (`text/x/y/w/h/cx/cy`
plus extras), so nothing downstream needs to know which strategy answered.
"""
from __future__ import annotations

import difflib
import re
from typing import Any, Dict, List, Optional, Tuple

from eli.utils.log import get_logger

log = get_logger(__name__)

Box = Dict[str, Any]

# Roles worth treating as "actionable" when the caller wants to click something.
# Deliberately narrow: matching a label or a whole panel by name is how you click the
# wrong thing with great confidence.
ACTIONABLE_ROLES = {
    "push button", "button", "toggle button", "check box", "radio button",
    "menu item", "check menu item", "radio menu item", "menu", "list item",
    "tab", "page tab", "link", "combo box", "entry", "text", "spin button",
    "slider", "tree item", "table cell", "icon",
}

# Hard cap on tree walking. An accessibility tree can be enormous (a browser exposes
# every DOM node), and this runs on a user-facing "click X" path.
_MAX_NODES = 4000
_MAX_DEPTH = 24

_UNAVAILABLE_REASON = ""


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def available() -> bool:
    """True when the AT-SPI stack can actually be used on this machine."""
    return _atspi() is not None


def unavailable_reason() -> str:
    """Why the backend is unusable, or "" when it is fine.

    Exposed because a bare False is what made an entire class of failures in this
    codebase undiagnosable — a caller could not tell "not installed" from "installed
    but broken".
    """
    _atspi()
    return _UNAVAILABLE_REASON


def _system_gi_path() -> Optional[str]:
    """Where the distro keeps PyGObject, when the venv has no copy.

    PyGObject cannot be pip-installed without gobject-introspection dev headers, so
    on a normal desktop it exists ONLY in the system interpreter's dist-packages.
    ELI runs from a venv, which by default cannot see it — so the accessibility
    backend would report "not installed" on a machine where AT-SPI works perfectly.
    Only used as a fallback, and only when the ABI matches (same major.minor), since
    a compiled extension built for another Python will not load.
    """
    import sys
    from pathlib import Path as _P
    ver = f"{sys.version_info.major}.{sys.version_info.minor}"
    for base in ("/usr/lib/python3/dist-packages",
                 f"/usr/lib/python{ver}/site-packages",
                 f"/usr/lib64/python{ver}/site-packages"):
        gi_dir = _P(base) / "gi"
        if gi_dir.is_dir():
            return base
    return None


def _atspi():
    """Import Atspi, or return None with the reason recorded. Never raises."""
    global _UNAVAILABLE_REASON
    try:
        try:
            import gi  # noqa: F401
        except ModuleNotFoundError:
            import sys
            extra = _system_gi_path()
            if extra and extra not in sys.path:
                sys.path.append(extra)
                log.debug("ui_tree: added system PyGObject path %s", extra)
        import gi
        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi  # type: ignore
        Atspi.init()
        _UNAVAILABLE_REASON = ""
        return Atspi
    except Exception as exc:
        _UNAVAILABLE_REASON = f"{type(exc).__name__}: {exc}"
        log.debug("ui_tree: AT-SPI unavailable — %s", _UNAVAILABLE_REASON)
        return None


def _score(query: str, name: str) -> float:
    """Same scoring philosophy as screen_locator: exact > prefix > fuzzy."""
    q, n = _norm(query), _norm(name)
    if not q or not n:
        return 0.0
    if q == n:
        return 1.0
    if n.startswith(q) or q in n.split():
        return 0.92
    if q in n:
        return 0.80
    return difflib.SequenceMatcher(None, q, n).ratio()


def _node_box(node, score: float, query: str) -> Optional[Box]:
    """Build a Box from an accessible, or None when it has no usable geometry."""
    try:
        comp = node.get_component_iface()
        if comp is None:
            return None
        ext = comp.get_extents(0)          # 0 = ATSPI_COORD_TYPE_SCREEN
        x, y, w, h = int(ext.x), int(ext.y), int(ext.width), int(ext.height)
    except Exception:
        return None
    if w <= 0 or h <= 0 or x < 0 or y < 0:
        return None                        # offscreen / not rendered
    try:
        role = node.get_role_name() or ""
        name = node.get_name() or ""
    except Exception:
        return None
    states, enabled, checked = set(), True, None
    try:
        st = node.get_state_set()
        from gi.repository import Atspi  # type: ignore
        enabled = bool(st.contains(Atspi.StateType.ENABLED))
        if st.contains(Atspi.StateType.CHECKED):
            checked = True
        states = {"enabled": enabled, "showing": bool(st.contains(Atspi.StateType.SHOWING))}
    except Exception:
        states = {}
    return {
        "text": name,
        "x": x, "y": y, "w": w, "h": h,
        "cx": x + w // 2, "cy": y + h // 2,
        "score": round(float(score), 4),
        "role": role,
        "enabled": enabled,
        "checked": checked,
        "states": states,
        "source": "atspi",
        "query": query,
        "_node": node,                     # kept for invoke(); never serialised
    }


def _walk(node, query: str, out: List[Box], seen: List[int], depth: int = 0) -> None:
    """Depth-first walk, bounded. Never raises — a broken app must not kill the search."""
    if depth > _MAX_DEPTH or seen[0] >= _MAX_NODES:
        return
    seen[0] += 1
    try:
        name = node.get_name() or ""
    except Exception:
        return
    if name:
        s = _score(query, name)
        if s >= 0.5:
            box = _node_box(node, s, query)
            if box is not None:
                out.append(box)
    try:
        n_children = node.get_child_count()
    except Exception:
        return
    for i in range(min(n_children, 512)):
        try:
            child = node.get_child_at_index(i)
        except Exception:
            continue
        if child is not None:
            _walk(child, query, out, seen, depth + 1)


def find(query: str, *, actionable_only: bool = True, max_matches: int = 8,
         min_score: float = 0.5) -> List[Box]:
    """Accessible widgets whose name matches `query`, best first.

    `actionable_only` keeps the result to things a click means something for — a
    label reading "Save" is not the Save button, and clicking it is the confident
    wrong answer OCR would give.
    """
    atspi = _atspi()
    if atspi is None:
        return []
    q = _norm(query)
    if not q:
        return []
    found: List[Box] = []
    seen = [0]
    try:
        desktop = atspi.get_desktop(0)
        for i in range(min(desktop.get_child_count(), 64)):
            try:
                app = desktop.get_child_at_index(i)
            except Exception:
                continue
            if app is not None:
                _walk(app, query, found, seen)
    except Exception as exc:
        log.debug("ui_tree: desktop walk failed — %s", exc, exc_info=True)
        return []
    if actionable_only:
        found = [b for b in found if str(b.get("role") or "").lower() in ACTIONABLE_ROLES]
    # Prefer higher score, then enabled, then smaller area (a tighter target is the
    # control itself rather than the panel containing it).
    found.sort(key=lambda b: (-float(b.get("score") or 0),
                              not bool(b.get("enabled")),
                              int(b.get("w") or 0) * int(b.get("h") or 0)))
    return [b for b in found if float(b.get("score") or 0) >= min_score][:max_matches]


def invoke(box: Box) -> Dict[str, Any]:
    """Activate a widget through its OWN action, not a synthetic click at a point.

    This is the capability OCR cannot have. A coordinate click races window motion,
    can land on an overlay, and reports success whether or not anything happened.
    `do_action` targets the widget itself and tells us whether it ran.
    """
    node = box.get("_node") if isinstance(box, dict) else None
    if node is None:
        return {"ok": False, "error": "no accessible node on this match"}
    try:
        action = node.get_action_iface()
        if action is None:
            return {"ok": False, "error": "widget exposes no actions"}
        n = action.get_n_actions()
        for idx in range(n):
            try:
                nm = (action.get_action_name(idx) or "").lower()
            except Exception:
                nm = ""
            if nm in ("click", "press", "activate", "jump", "open"):
                ok = bool(action.do_action(idx))
                return {"ok": ok, "action_used": nm,
                        "error": "" if ok else f"do_action('{nm}') returned false"}
        if n > 0:
            ok = bool(action.do_action(0))
            return {"ok": ok, "action_used": action.get_action_name(0) or "0",
                    "error": "" if ok else "do_action(0) returned false"}
        return {"ok": False, "error": "widget advertises zero actions"}
    except Exception as exc:
        log.debug("ui_tree: invoke failed — %s", exc, exc_info=True)
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def describe(box: Box) -> str:
    """One-line human description — used when reporting what was clicked."""
    if not isinstance(box, dict):
        return ""
    role = box.get("role") or "widget"
    name = box.get("text") or "(unnamed)"
    state = "" if box.get("enabled", True) else " [disabled]"
    return f"{role} '{name}'{state} at ({box.get('cx')},{box.get('cy')})"


def public_matches(boxes: List[Box]) -> List[Box]:
    """Strip the live accessible handles so a result can be serialised/logged."""
    return [{k: v for k, v in b.items() if k != "_node"} for b in (boxes or [])]
