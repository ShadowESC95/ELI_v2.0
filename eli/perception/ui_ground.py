"""Optional UI grounding backends — 100% local by default.

Precision click and computer-use agents run in-process against local GGUF
models discovered under models/. No HTTP URLs, no cloud — unless the user
has explicitly enabled the Net toggle AND allow_remote_grounding (off by default).

Architecture:
  A) Precision: screenshot + query → local grounding model → (x,y) box → click
  B) Agent: screenshot + instruction → local UI-TARS-style model → action loop

Moondream/Qwen-VL in vision.py remain describe-only unless a dedicated
grounding model path is configured.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from eli.utils.log import get_logger

log = get_logger(__name__)

_PRECISION_BACKENDS = frozenset({"none", "local_gguf", "auto", "phi_ground", "os_atlas", "uground"})
_AGENT_BACKENDS = frozenset({"none", "local_gguf", "auto", "ui_tars_2", "ui_tars"})
# Legacy names map to local GGUF discovery.
_ALIASES = {
    "phi_ground": "local_gguf",
    "os_atlas": "local_gguf",
    "uground": "local_gguf",
    "ui_tars_2": "local_gguf",
    "ui_tars": "local_gguf",
}


def _setting(key: str, default: str = "") -> str:
    env_key = f"ELI_{key.upper()}"
    if os.environ.get(env_key):
        return str(os.environ[env_key]).strip()
    try:
        from eli.core.runtime_settings import load_settings
        return str(load_settings().get(key, default) or default).strip()
    except Exception:
        return default


def _remote_allowed() -> bool:
    """True only when user opted into network AND remote grounding."""
    if not bool(_setting("allow_remote_grounding", "false").lower() in ("1", "true", "yes")):
        return False
    try:
        from eli.runtime import netguard
        return bool(getattr(netguard, "network_enabled", lambda: False)())
    except Exception:
        return False


def configured_precision_backend() -> str:
    raw = _setting("ui_ground_backend", "none").lower()
    if raw in ("none", "", "off"):
        return ""
    resolved = _ALIASES.get(raw, raw)
    if resolved == "auto":
        if _discover_ground_model_path():
            return "local_gguf"
        try:
            from eli.perception import vision as _v
            ok, _ = _v.vision_available()
            fok, _ = _v.fast_vision_available()
            if ok or fok:
                return "local_gguf"
        except Exception:
            pass
        return ""
    return resolved if resolved in _PRECISION_BACKENDS else ""


def configured_agent_backend() -> str:
    raw = _setting("computer_use_backend", "none").lower()
    if raw in ("none", "", "off"):
        return ""
    resolved = _ALIASES.get(raw, raw)
    if resolved == "auto":
        return "local_gguf" if _discover_agent_model_path() else ""
    return resolved if resolved in _AGENT_BACKENDS else ""


def _discover_ground_model_path() -> str:
    explicit = _setting("ui_ground_model_path")
    if explicit and Path(explicit).expanduser().is_file():
        return str(Path(explicit).expanduser().resolve())
    try:
        from eli.core.paths import models_dir
        root = Path(models_dir())
        hints = ("ground", "phi-ground", "os-atlas", "uground", "ui-ground")
        for gguf in sorted(root.rglob("*.gguf")):
            name = gguf.name.lower()
            if any(h in name for h in hints):
                return str(gguf.resolve())
    except Exception:
        log.debug("ground model discovery failed", exc_info=True)
    return ""


def _discover_agent_model_path() -> str:
    explicit = _setting("computer_use_model_path")
    if explicit and Path(explicit).expanduser().is_file():
        return str(Path(explicit).expanduser().resolve())
    try:
        from eli.core.paths import models_dir
        root = Path(models_dir())
        hints = ("ui-tars", "uitars", "tars-2", "computer-use", "computer_use")
        for gguf in sorted(root.rglob("*.gguf")):
            name = gguf.name.lower()
            if any(h in name for h in hints):
                return str(gguf.resolve())
    except Exception:
        log.debug("agent model discovery failed", exc_info=True)
    return ""


def _parse_boxes(payload: Any) -> list[dict[str, Any]]:
    if not payload:
        return []
    if isinstance(payload, dict):
        if "boxes" in payload:
            items = payload["boxes"]
        elif "matches" in payload:
            items = payload["matches"]
        elif all(k in payload for k in ("x", "y")):
            items = [payload]
        else:
            items = payload.get("results") or []
    elif isinstance(payload, list):
        items = payload
    else:
        return []
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            x = int(item.get("x", item.get("left", 0)))
            y = int(item.get("y", item.get("top", 0)))
            w = int(item.get("w", item.get("width", max(1, int(item.get("right", x + 1)) - x))))
            h = int(item.get("h", item.get("height", max(1, int(item.get("bottom", y + 1)) - y))))
            if w <= 0 or h <= 0:
                continue
            cx = int(item.get("cx", x + w // 2))
            cy = int(item.get("cy", y + h // 2))
            out.append({
                "text": str(item.get("text") or item.get("label") or ""),
                "x": x, "y": y, "w": w, "h": h, "cx": cx, "cy": cy,
                "score": float(item.get("score", item.get("confidence", 0.75))),
                "source": str(item.get("source") or "local_gguf"),
            })
        except (TypeError, ValueError):
            continue
    return out


def _parse_boxes_from_text(text: str) -> list[dict[str, Any]]:
    """Extract JSON or [x,y,w,h] tuples from a local model response."""
    raw = str(text or "").strip()
    if not raw:
        return []
    for block in re.findall(r"\{[^{}]+\}", raw):
        try:
            obj = json.loads(block)
            boxes = _parse_boxes(obj if isinstance(obj, dict) else {"boxes": [obj]})
            if boxes:
                return boxes
        except json.JSONDecodeError:
            continue
    m = re.search(
        r"\[\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\]", raw
    )
    if m:
        x, y, w, h = (int(m.group(i)) for i in range(1, 5))
        return _parse_boxes({"x": x, "y": y, "w": w, "h": h, "score": 0.7})
    return []


def _local_gguf_ground(query: str, image_path: str, model_path: str) -> dict[str, Any]:
    """Run a local VL/grounding GGUF in-process via vision.describe_image."""
    from eli.perception import vision as _vision

    prompt = (
        f'Locate "{query}" in this screenshot. Reply with ONLY a JSON object: '
        '{"boxes":[{"x":left,"y":top,"w":width,"h":height,"text":"label","score":0.0-1.0}]} '
        "Use pixel coordinates relative to the image. If not found, reply "
        '{"boxes":[]}.'
    )
    res = _vision.describe_image(
        image_path,
        prompt=prompt,
        prefer_fast=not bool(model_path),
    )
    if not res.get("ok"):
        return {"ok": False, "error": str(res.get("error") or "local grounding model failed")}
    boxes = _parse_boxes_from_text(str(res.get("text") or ""))
    if not boxes:
        return {
            "ok": False,
            "error": (
                f"Local grounding model did not return coordinates for '{query}'. "
                "Install a UI-grounding GGUF in models/ or use AT-SPI/OCR click paths."
            ),
        }
    return {"ok": True, "boxes": boxes, "backend": "local_gguf"}


def locate_with_precision_backend(
    query: str,
    image_path: str,
    *,
    backend: str | None = None,
    max_matches: int = 8,
    min_score: float = 0.45,
) -> dict[str, Any]:
    name = (backend or configured_precision_backend() or "").lower()
    if not name:
        return {"ok": False, "error": "no precision grounding backend configured"}

    model_path = _discover_ground_model_path()
    if name == "local_gguf":
        if not model_path:
            return {
                "ok": False,
                "error": (
                    "No local UI grounding model found. Drop a Phi-Ground / OS-Atlas / "
                    "UGround GGUF into models/ or set ui_ground_model_path in Screen settings."
                ),
            }
        result = _local_gguf_ground(query, image_path, model_path)
    else:
        return {"ok": False, "error": f"unknown ui_ground backend: {name}"}

    if not result.get("ok"):
        return result

    boxes = [b for b in (result.get("boxes") or []) if float(b.get("score", 0)) >= min_score]
    boxes.sort(key=lambda b: float(b.get("score", 0)), reverse=True)
    boxes = boxes[:max_matches]
    if not boxes:
        return {"ok": False, "error": f"{name} found nothing above score threshold"}

    q = str(query or "").strip().lower()
    if q:
        for b in boxes:
            label = str(b.get("text") or "").lower()
            if label and q in label:
                b["score"] = min(1.0, float(b.get("score", 0)) + 0.1)

    return {
        "ok": True,
        "backend": result.get("backend", name),
        "matches": boxes,
        "best": boxes[0],
    }


def run_computer_use_step(instruction: str, image_path: str) -> dict[str, Any]:
    """Single local agent step — in-process, no HTTP."""
    backend = configured_agent_backend()
    if not backend:
        return {
            "ok": False,
            "error": (
                "Computer-use agent is off. Enable it in Screen settings and add a "
                "UI-TARS-style GGUF to models/, or set computer_use_model_path."
            ),
        }
    model_path = _discover_agent_model_path()
    if not model_path:
        return {
            "ok": False,
            "error": (
                "No local computer-use model found. Add a UI-TARS GGUF to models/ "
                "or set computer_use_model_path in Screen settings."
            ),
        }
    from eli.perception import vision as _vision

    prompt = (
        f'You are a desktop agent. Instruction: "{instruction}". '
        "Reply with ONLY JSON: "
        '{"action":"click|type|scroll|wait|done","x":0,"y":0,"text":"","reasoning":"..."} '
        "Use pixel coordinates for click. Only propose actions justified by the screenshot."
    )
    res = _vision.describe_image(
        image_path, prompt=prompt, prefer_fast=False,
    )
    if not res.get("ok"):
        return {"ok": False, "error": str(res.get("error") or "local agent model failed")}
    raw_text = str(res.get("text") or "")
    try:
        m = re.search(r"\{[^{}]+\}", raw_text)
        raw = json.loads(m.group(0) if m else raw_text)
    except Exception:
        return {"ok": False, "error": "local agent model returned unparseable JSON"}
    action = str(raw.get("action") or raw.get("type") or "").lower()
    return {
        "ok": bool(action),
        "backend": "local_gguf",
        "action": action,
        "x": raw.get("x"),
        "y": raw.get("y"),
        "text": raw.get("text"),
        "reasoning": raw.get("reasoning") or raw.get("thought"),
        "raw": raw,
    }


__all__ = [
    "configured_agent_backend",
    "configured_precision_backend",
    "locate_with_precision_backend",
    "run_computer_use_step",
]
