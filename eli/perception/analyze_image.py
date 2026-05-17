#!/usr/bin/env python3
"""
ELI image analysis helper.

Analyzes an image file and writes a Markdown report.
Supports: PIL/Pillow metadata extraction, optional OCR via tesseract.

Usage (module):
    from eli.perception.analyze_image import analyze_image_file
    result = analyze_image_file("/path/to/img.png", "/path/to/report.md")

Usage (CLI):
    python3 -m eli.perception.analyze_image --path img.png --out report.md
"""

from __future__ import annotations

import json
import subprocess
import shutil
import time
from pathlib import Path
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tesseract_ocr(path: Path, max_chars: int = 2000) -> str:
    """Run tesseract OCR on an image; return extracted text (empty if unavailable)."""
    if not shutil.which("tesseract"):
        return ""
    try:
        txt_stem = path.with_suffix("")
        subprocess.run(
            ["tesseract", str(path), str(txt_stem)],
            timeout=30,
            check=False,
            capture_output=True,
        )
        out = txt_stem.with_suffix(".txt")
        if out.exists():
            text = out.read_text(encoding="utf-8", errors="replace")
            return " ".join(text.split())[:max_chars]
    except Exception:
        pass
    return ""


def _pil_info(path: Path) -> Dict[str, Any]:
    """Extract basic metadata via Pillow; return {} if not installed."""
    try:
        from PIL import Image  # type: ignore
        with Image.open(path) as img:
            return {
                "format": img.format or path.suffix.lstrip(".").upper(),
                "mode": img.mode,
                "width": img.width,
                "height": img.height,
            }
    except Exception:
        return {
            "format": path.suffix.lstrip(".").upper() or "unknown",
            "mode": "unknown",
            "width": None,
            "height": None,
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_image_file(
    path: str,
    out_md: str,
    *,
    ocr: bool = True,
    max_ocr_chars: int = 2000,
) -> Dict[str, Any]:
    """
    Analyze an image file and write a Markdown report.

    Returns a dict with keys: ok, path, format, width, height, ocr_text,
    artifacts_dir, out_md, analyzed_at.
    """
    p = Path(path).expanduser().resolve()
    outp = Path(out_md).expanduser().resolve()
    outp.parent.mkdir(parents=True, exist_ok=True)

    if not p.exists():
        return {"ok": False, "error": f"File not found: {p}", "path": str(p)}

    artifacts_dir = outp.parent / f"analyze_image_{time.strftime('%Y%m%d_%H%M%S')}"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    info = _pil_info(p)
    file_size = p.stat().st_size

    ocr_text = ""
    if ocr:
        ocr_text = _tesseract_ocr(p, max_chars=max_ocr_chars)

    report = {
        "ok": True,
        "path": str(p),
        "format": info.get("format", "unknown"),
        "mode": info.get("mode", "unknown"),
        "width": info.get("width"),
        "height": info.get("height"),
        "size_bytes": file_size,
        "ocr_text": ocr_text,
        "artifacts_dir": str(artifacts_dir),
        "out_md": str(outp),
        "analyzed_at": time.time(),
    }

    (artifacts_dir / "report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )

    # Build Markdown
    md: list[str] = []
    md.append(f"# Image analysis: `{p.name}`\n\n")
    md.append(f"- **Format**: {report['format']}  \n")
    if report["width"] and report["height"]:
        md.append(f"- **Dimensions**: {report['width']} × {report['height']} px  \n")
    md.append(f"- **File size**: {file_size:,} bytes  \n")
    md.append(f"- **Color mode**: {report['mode']}  \n")
    if ocr_text:
        md.append("\n## OCR text\n\n")
        md.append(ocr_text[:1500])
        if len(ocr_text) > 1500:
            md.append("\n\n*(truncated)*")
        md.append("\n")
    else:
        md.append("\n*No OCR text extracted (tesseract not available or no text detected).*\n")

    outp.write_text("".join(md), encoding="utf-8")
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Analyze an image file")
    ap.add_argument("--path", required=True, help="Path to image file")
    ap.add_argument("--out", default="artifacts/image_report_latest.md", help="Output Markdown path")
    ap.add_argument("--no-ocr", action="store_true", help="Disable OCR")
    ns = ap.parse_args()
    result = analyze_image_file(ns.path, ns.out, ocr=not ns.no_ocr)
    print(json.dumps(result, indent=2))
