#!/usr/bin/env python3
"""
Screenshot-to-element locator for ELI.

This layer sits above screenshot capture and OCR. It converts OCR boxes into
clickable element candidates, ranks them against a requested label/query, and
returns screen coordinates that the executor or GUI can act on.
"""

from __future__ import annotations

import csv
import re
import shutil
import subprocess
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


Box = Dict[str, Any]


def _norm(text: str) -> str:
    text = str(text or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(text: str) -> List[str]:
    return [tok for tok in _norm(text).split() if tok]


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return default


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _union_box(items: Sequence[Mapping[str, Any]]) -> Tuple[int, int, int, int]:
    left = min(_int(item.get("x")) for item in items)
    top = min(_int(item.get("y")) for item in items)
    right = max(_int(item.get("x")) + _int(item.get("w")) for item in items)
    bottom = max(_int(item.get("y")) + _int(item.get("h")) for item in items)
    return left, top, max(1, right - left), max(1, bottom - top)


def _make_box(text: str, x: Any, y: Any, w: Any, h: Any, **extra: Any) -> Box:
    ix, iy, iw, ih = _int(x), _int(y), max(1, _int(w, 1)), max(1, _int(h, 1))
    out: Box = {
        "text": str(text or "").strip(),
        "x": ix,
        "y": iy,
        "w": iw,
        "h": ih,
        "cx": ix + iw // 2,
        "cy": iy + ih // 2,
    }
    out.update(extra)
    return out


def _score_text(query: str, candidate: str) -> float:
    q = _norm(query)
    c = _norm(candidate)
    if not q or not c:
        return 0.0
    if q == c:
        return 1.0
    if q in c:
        length_bonus = min(len(q), len(c)) / max(len(q), len(c), 1)
        return min(0.98, 0.88 + 0.10 * length_bonus)
    if c in q and len(c) >= 3:
        return min(0.86, 0.55 + 0.30 * (len(c) / max(len(q), 1)))

    q_tokens = set(q.split())
    c_tokens = set(c.split())
    overlap = len(q_tokens & c_tokens) / max(len(q_tokens), 1)
    ratio = SequenceMatcher(None, q, c).ratio()
    return max(overlap * 0.84, ratio * 0.72)


def _word_boxes_from_pytesseract(path: Path, lang: str = "eng", psm: int = 11) -> Tuple[List[Box], str]:
    import pytesseract  # type: ignore
    from PIL import Image  # type: ignore

    img = Image.open(path)
    data = pytesseract.image_to_data(
        img,
        lang=lang,
        config=f"--psm {int(psm)}",
        output_type=pytesseract.Output.DICT,
    )
    boxes: List[Box] = []
    texts: List[str] = []
    count = len(data.get("text", []))
    for idx in range(count):
        text = str(data["text"][idx] or "").strip()
        if not text:
            continue
        conf = _float(data.get("conf", [0])[idx], -1.0)
        if conf < 0:
            continue
        box = _make_box(
            text,
            data.get("left", [0])[idx],
            data.get("top", [0])[idx],
            data.get("width", [1])[idx],
            data.get("height", [1])[idx],
            conf=conf,
            page=_int(data.get("page_num", [0])[idx]),
            block=_int(data.get("block_num", [0])[idx]),
            paragraph=_int(data.get("par_num", [0])[idx]),
            line=_int(data.get("line_num", [0])[idx]),
            word=_int(data.get("word_num", [0])[idx]),
            source="pytesseract",
            kind="word",
        )
        boxes.append(box)
        texts.append(text)
    return boxes, " ".join(texts).strip()


def _word_boxes_from_tesseract_cli(path: Path, lang: str = "eng", psm: int = 11) -> Tuple[List[Box], str]:
    tess = shutil.which("tesseract")
    if not tess:
        return [], ""
    result = subprocess.run(
        [tess, str(path), "stdout", "--psm", str(int(psm)), "-l", lang, "tsv"],
        capture_output=True,
        text=True,
        timeout=35,
    )
    if result.returncode != 0:
        return [], ""

    boxes: List[Box] = []
    texts: List[str] = []
    reader = csv.DictReader(result.stdout.splitlines(), delimiter="\t")
    for row in reader:
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        conf = _float(row.get("conf"), -1.0)
        if conf < 0:
            continue
        box = _make_box(
            text,
            row.get("left"),
            row.get("top"),
            row.get("width"),
            row.get("height"),
            conf=conf,
            page=_int(row.get("page_num")),
            block=_int(row.get("block_num")),
            paragraph=_int(row.get("par_num")),
            line=_int(row.get("line_num")),
            word=_int(row.get("word_num")),
            source="tesseract",
            kind="word",
        )
        boxes.append(box)
        texts.append(text)
    return boxes, " ".join(texts).strip()


def ocr_text_from_image(path: str | Path, lang: str = "eng", psm: int = 11) -> str:
    image_path = Path(path).expanduser().resolve()
    tess = shutil.which("tesseract")
    if tess:
        try:
            result = subprocess.run(
                [tess, str(image_path), "stdout", "--psm", str(int(psm)), "-l", lang],
                capture_output=True,
                text=True,
                timeout=35,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception:
            pass
    try:
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore

        return pytesseract.image_to_string(Image.open(image_path), config=f"--psm {int(psm)}").strip()
    except Exception:
        return ""


def ocr_image_with_boxes(path: str | Path, lang: str = "eng", psm: int = 11) -> Dict[str, Any]:
    image_path = Path(path).expanduser().resolve()
    if not image_path.exists():
        return {
            "ok": False,
            "error": f"Image not found: {image_path}",
            "text": "",
            "boxes": [],
            "path": str(image_path),
        }

    boxes: List[Box] = []
    text = ""
    try:
        boxes, text = _word_boxes_from_pytesseract(image_path, lang=lang, psm=psm)
    except Exception:
        boxes = []
        text = ""

    if not boxes:
        try:
            boxes, text = _word_boxes_from_tesseract_cli(image_path, lang=lang, psm=psm)
        except Exception:
            boxes = []
            text = ""

    if not text:
        text = ocr_text_from_image(image_path, lang=lang, psm=psm)

    return {
        "ok": bool(text or boxes),
        "path": str(image_path),
        "text": text.strip(),
        "boxes": boxes,
    }


def _line_groups(boxes: Iterable[Mapping[str, Any]]) -> Dict[Tuple[int, int, int, int], List[Mapping[str, Any]]]:
    groups: Dict[Tuple[int, int, int, int], List[Mapping[str, Any]]] = {}
    for box in boxes:
        text = str(box.get("text") or "").strip()
        if not text:
            continue
        key = (
            _int(box.get("page")),
            _int(box.get("block")),
            _int(box.get("paragraph")),
            _int(box.get("line")),
        )
        groups.setdefault(key, []).append(box)
    return groups


def _candidate_boxes(boxes: Sequence[Mapping[str, Any]]) -> List[Box]:
    candidates: List[Box] = []
    word_boxes = [box for box in boxes if str(box.get("text") or "").strip()]
    for box in word_boxes:
        candidates.append(
            _make_box(
                str(box.get("text") or ""),
                box.get("x"),
                box.get("y"),
                box.get("w"),
                box.get("h"),
                conf=_float(box.get("conf"), 0.0),
                source=box.get("source", "ocr"),
                kind=box.get("kind", "word"),
            )
        )

    for items in _line_groups(word_boxes).values():
        ordered = sorted(items, key=lambda item: (_int(item.get("x")), _int(item.get("word"))))
        if len(ordered) < 2:
            continue
        text = " ".join(str(item.get("text") or "").strip() for item in ordered).strip()
        x, y, w, h = _union_box(ordered)
        candidates.append(_make_box(text, x, y, w, h, kind="line", source="ocr"))

        max_window = min(8, len(ordered))
        for size in range(2, max_window + 1):
            for start in range(0, len(ordered) - size + 1):
                window = ordered[start : start + size]
                text = " ".join(str(item.get("text") or "").strip() for item in window).strip()
                x, y, w, h = _union_box(window)
                candidates.append(_make_box(text, x, y, w, h, kind="phrase", source="ocr"))
    return candidates


def _find_matches(
    query: str,
    boxes: Sequence[Mapping[str, Any]],
    *,
    max_matches: int = 8,
    min_score: float = 0.50,
) -> List[Box]:
    query = str(query or "").strip()
    if not query:
        return []

    seen: set[Tuple[str, int, int, int, int]] = set()
    matches: List[Box] = []
    for candidate in _candidate_boxes(boxes):
        text = str(candidate.get("text") or "").strip()
        score = _score_text(query, text)
        if score < min_score:
            continue
        key = (_norm(text), _int(candidate.get("x")), _int(candidate.get("y")), _int(candidate.get("w")), _int(candidate.get("h")))
        if key in seen:
            continue
        seen.add(key)
        candidate["score"] = round(float(score), 3)
        matches.append(candidate)

    matches.sort(key=lambda item: (-_float(item.get("score")), _int(item.get("y")), _int(item.get("x"))))
    return matches[: max(1, int(max_matches))]


def locate_in_image(
    path: str | Path,
    query: str,
    *,
    lang: str = "eng",
    psm: int = 11,
    max_matches: int = 8,
    min_score: float = 0.50,
) -> Dict[str, Any]:
    ocr = ocr_image_with_boxes(path, lang=lang, psm=psm)
    matches = _find_matches(query, ocr.get("boxes") or [], max_matches=max_matches, min_score=min_score)
    best = matches[0] if matches else None
    text = str(ocr.get("text") or "").strip()

    if best:
        content = (
            f"Located '{query}' on screen. Best match: '{best.get('text')}' "
            f"at ({best.get('cx')}, {best.get('cy')}); box={best.get('x')},"
            f"{best.get('y')},{best.get('w')}x{best.get('h')}; score={best.get('score')}."
        )
    else:
        content = f"Could not locate '{query}' in screenshot OCR."
    if text:
        content += f"\n\nScreen OCR:\n{text[:3000]}"

    return {
        "ok": bool(best),
        "action": "SCREEN_LOCATE",
        "query": str(query or "").strip(),
        "path": str(ocr.get("path") or Path(path).expanduser().resolve()),
        "screenshot_path": str(ocr.get("path") or Path(path).expanduser().resolve()),
        "ocr_text": text,
        "boxes": ocr.get("boxes") or [],
        "matches": matches,
        "best": best,
        "content": content,
        "response": content,
    }


def locate_on_screen(
    query: str,
    *,
    region: str = "full",
    lang: str = "eng",
    psm: int = 11,
    max_matches: int = 8,
    min_score: float = 0.50,
) -> Dict[str, Any]:
    from eli.perception.os_controller import take_screenshot

    screenshot = take_screenshot(region=region)
    path = screenshot.get("path") or screenshot.get("file") or ""
    if not screenshot.get("ok") or not path:
        error = str(screenshot.get("error") or "Screenshot failed")
        return {
            "ok": False,
            "action": "SCREEN_LOCATE",
            "query": str(query or "").strip(),
            "error": error,
            "content": f"Screenshot failed before locating '{query}': {error}",
            "response": f"Screenshot failed before locating '{query}': {error}",
        }
    return locate_in_image(path, query, lang=lang, psm=psm, max_matches=max_matches, min_score=min_score)


__all__ = [
    "locate_in_image",
    "locate_on_screen",
    "ocr_image_with_boxes",
    "ocr_text_from_image",
    "_find_matches",
    "_score_text",
]
