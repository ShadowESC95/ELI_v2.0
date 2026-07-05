#!/usr/bin/env python3
"""Build a polished PDF of capabilities_and_actions.md, matching the user-manual style.

The capabilities doc is pure markdown tables (no diagrams) and uses only DejaVu-covered
glyphs (curly quotes, middot, arrow, em-dash), so this is a straight pandoc + xelatex
render: a title page, an auto table of contents, and the tables wrapped via longtable.
The source .md's own H1 is dropped (pandoc --title renders it) to avoid a duplicate.

Run:  .venv/bin/python blueprints/build_capabilities_pdf.py
"""
import re, subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "capabilities_and_actions.md"
BUILD_MD = HERE / "_capabilities_pdf_build.md"
OUT_PDF = HERE / "capabilities_and_actions.pdf"


def main() -> int:
    text = SRC.read_text(encoding="utf-8")
    # Drop the H1 title + the italic subtitle line (pandoc --title/--subtitle render them),
    # so the PDF doesn't show the title twice.
    text = re.sub(r"^# ELI — Capabilities & Actions.*\n", "", text, count=1, flags=re.M)
    text = re.sub(r"^\*Auto-generated.*\n", "", text, count=1, flags=re.M)

    # Give the 4-column tables weighted widths so long action names (e.g.
    # CONFIRM_PENDING_REMEDIATION) and the phrases column don't overflow. Pandoc derives
    # pipe-table column widths from the dash counts in the separator row, which the
    # generator emits as equal "|---|---|---|---|". Rewrite those separators only.
    def _weight(line: str) -> str:
        s = line.strip()
        if s.startswith("|") and s.endswith("|") and set(s) <= set("|-: ") and s.count("|") == 5:
            # Action | What it does | Example phrase(s) | Source
            return "|:--------------------|:------------------|:--------------------------|:------|"
        return line
    text = "\n".join(_weight(ln) for ln in text.split("\n"))
    BUILD_MD.write_text(text, encoding="utf-8")

    subtitle = "Every routable action + representative activation phrases"
    cmd = [
        "pandoc", str(BUILD_MD), "-o", str(OUT_PDF),
        "--pdf-engine=xelatex", "--toc", "--toc-depth=2",
        "-V", "geometry:margin=1.6cm",
        "-V", "mainfont=DejaVu Sans", "-V", "monofont=DejaVu Sans Mono",
        "-V", "fontsize=10pt", "-V", "colorlinks=true", "-V", "linkcolor=blue",
        "-V", "title=ELI — Capabilities and Actions",
        "-V", f"subtitle={subtitle}",
    ]
    print("Running pandoc -> xelatex ...")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("pandoc FAILED:\n", r.stderr[-2500:])
        return 1
    BUILD_MD.unlink(missing_ok=True)
    print(f"\n✅ PDF built: {OUT_PDF}  ({OUT_PDF.stat().st_size/1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
