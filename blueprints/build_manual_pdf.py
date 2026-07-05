#!/usr/bin/env python3
"""Build a polished PDF of ELI_USER_MANUAL.md with the Mermaid flowcharts rendered.

Pipeline: extract ```mermaid blocks -> render each to PNG via kroki.io -> swap the fences
for image refs in a PDF-only copy -> map/strip emoji (no colour-emoji font locally) ->
pandoc + xelatex -> PDF. The source .md is untouched (keeps emoji + mermaid for GitHub).

Run:  .venv/bin/python blueprints/build_manual_pdf.py
"""
import base64, re, subprocess, sys, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "ELI_USER_MANUAL.md"
ASSETS = HERE / "manual_assets"
BUILD_MD = HERE / "_manual_pdf_build.md"
OUT_PDF = HERE / "ELI_USER_MANUAL.pdf"

# Emoji -> text (meaningful tags) or "" (decorative). The .md keeps the originals.
EMOJI_MAP = {
    "🟢": "[Anyone] ", "🟡": "[A bit technical] ", "🔴": "[Advanced] ",
    "➡️": "->", "✓": "-", "✗": "x",
}
DECORATIVE = "🎵🪟🔊📄✍️📊🌐⏰🔧🧩"


def render_mermaid(code: str, idx: int) -> Path | None:
    """Render one mermaid block to PNG via kroki. Returns the PNG path, or None on failure."""
    try:
        req = urllib.request.Request(
            "https://kroki.io/mermaid/png", data=code.encode("utf-8"),
            headers={"Content-Type": "text/plain",
                     "User-Agent": "Mozilla/5.0 (ELI-manual-build)"}, method="POST")
        with urllib.request.urlopen(req, timeout=40) as r:
            data = r.read()
        if data[:8] != b"\x89PNG\r\n\x1a\n":
            print(f"  ! block {idx}: not a PNG (kroki may not support this diagram)")
            return None
        ASSETS.mkdir(exist_ok=True)
        p = ASSETS / f"diagram_{idx:02d}.png"
        p.write_bytes(data)
        print(f"  ok block {idx}: {len(data)} bytes -> {p.name}")
        return p
    except Exception as e:
        print(f"  ! block {idx}: {e}")
        return None


def main() -> int:
    text = SRC.read_text(encoding="utf-8")

    # PDF-only de-duplication: pandoc's --title and --toc already render the title and a
    # contents list, so strip the markdown's own H1 title block and the hand-written
    # "## Table of contents" section (which exists for GitHub anchors). The source .md
    # keeps both. Without this the PDF showed the title and a contents list twice.
    text = re.sub(r"^# ELI .*User Manual\s*\n", "", text, count=1, flags=re.M)
    text = re.sub(r"^### Plain-English Edition.*\n", "", text, count=1, flags=re.M)
    text = re.sub(r"^\*A friendly, no-jargon guide.*\n", "", text, count=1, flags=re.M)
    text = re.sub(r"## Table of contents\n.*?\n---\n", "", text, count=1, flags=re.DOTALL)

    blocks = list(re.finditer(r"```mermaid\n(.*?)\n```", text, re.DOTALL))
    print(f"Found {len(blocks)} mermaid blocks; rendering via kroki...")

    # Replace from the end so offsets stay valid.
    out = text
    for i, m in enumerate(reversed(blocks), start=1):
        idx = len(blocks) - i + 1
        png = render_mermaid(m.group(1), idx)
        if png:
            repl = f"\n![]({png.as_posix()})\\\n"
        else:
            # Fallback: keep the diagram source as a readable code block.
            repl = "```\n" + m.group(1) + "\n```"
        out = out[:m.start()] + repl + out[m.end():]

    # Emoji handling (PDF only).
    for e, t in EMOJI_MAP.items():
        out = out.replace(e, t)
    for ch in DECORATIVE:
        out = out.replace(ch + " ", "").replace(ch, "")

    BUILD_MD.write_text(out, encoding="utf-8")

    cmd = [
        "pandoc", str(BUILD_MD), "-o", str(OUT_PDF),
        "--pdf-engine=xelatex", "--toc", "--toc-depth=2", "-V", "geometry:margin=2cm",
        "-V", "mainfont=DejaVu Sans", "-V", "monofont=DejaVu Sans Mono",
        "-V", "colorlinks=true", "-V", "linkcolor=blue", "-V", "toccolor=black",
        "-V", "title=ELI — The Complete User Manual",
        "-V", "subtitle=Plain-English Edition · with flowcharts",
        "--resource-path", str(HERE),
    ]
    print("Running pandoc -> xelatex ...")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("pandoc FAILED:\n", r.stderr[-2500:])
        return 1
    BUILD_MD.unlink(missing_ok=True)
    size = OUT_PDF.stat().st_size
    print(f"\n✅ PDF built: {OUT_PDF}  ({size/1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
