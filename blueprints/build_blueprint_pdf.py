#!/usr/bin/env python3
"""Convert blueprint .md files to styled PDFs (manual-style), rendering any ```mermaid
flowcharts to PNG via kroki. Reusable for any doc.

  .venv/bin/python blueprints/build_blueprint_pdf.py <file.md> [file2.md ...]
  .venv/bin/python blueprints/build_blueprint_pdf.py --amended   # the docs changed this session

Handles: mermaid → kroki PNG, emoji → text (no colour-emoji font locally), 4-column table
width weighting, dropping the markdown's own H1/subtitle (pandoc --title renders it), and
escaping LaTeX-hostile chars in the title.
"""
import re, subprocess, sys, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "pdf_assets"

EMOJI_MAP = {"🟢": "[basic] ", "🟡": "[intermediate] ", "🔴": "[advanced] ",
             "➡️": "->", "✅": "[yes]", "❌": "[no]", "⚠️": "[!]", "✓": "-", "✗": "x", "⚛️": ""}
DECORATIVE = "📓🧠🧮📂🖥️🔬🧭🧪📄🗓️💬🎯🖼️⚡🌍⚙️🔧🎵🪟🔊✍️📊🌐⏰🧩🔍↻▶▶️"

AMENDED = [
    "gui.md", "what_eli_can_do.md", "project_overview.md", "state_snapshot.md",
    "capability_catalogue.md", "session_2026-06-18_hardening_scaling_and_release.md",
    "code_mode_execution_layer.md", "what_eli_is.md",
    "local_model_bakeoff_2026-06-17.md", "model_bakeoff_dossier.md",
]


def _render_mermaid(code: str, idx: int) -> Path | None:
    try:
        req = urllib.request.Request("https://kroki.io/mermaid/png", data=code.encode(),
                                     headers={"Content-Type": "text/plain",
                                              "User-Agent": "Mozilla/5.0 (eli-pdf)"}, method="POST")
        with urllib.request.urlopen(req, timeout=40) as r:
            data = r.read()
        if data[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        ASSETS.mkdir(exist_ok=True)
        p = ASSETS / f"{idx}.png"; p.write_bytes(data); return p
    except Exception:
        return None


def _weight_tables(text: str) -> str:
    def w(line: str) -> str:
        s = line.strip()
        if s.startswith("|") and s.endswith("|") and set(s) <= set("|-: ") and s.count("|") == 5:
            return "|:--------------------|:------------------|:--------------------------|:------|"
        return line
    return "\n".join(w(ln) for ln in text.split("\n"))


def convert(md: Path) -> bool:
    text = md.read_text(encoding="utf-8")
    # Title = first H1; strip it + an italic subtitle so pandoc --title isn't duplicated.
    m = re.search(r"^#\s+(.+)$", text, flags=re.M)
    title = (m.group(1) if m else md.stem).replace("&", "and").replace("`", "")
    title = re.sub(r"[*_]", "", title)
    text = re.sub(r"^#\s+.+\n", "", text, count=1, flags=re.M)
    text = re.sub(r"^\*[^*\n].*\*\s*\n", "", text, count=1, flags=re.M)

    # Render mermaid blocks → images (replace from the end to keep offsets valid).
    blocks = list(re.finditer(r"```mermaid\n(.*?)\n```", text, re.DOTALL))
    for i, blk in enumerate(reversed(blocks), 1):
        idx = f"{md.stem}_{len(blocks)-i+1}"
        png = _render_mermaid(blk.group(1), idx)
        repl = (f"\n![]({png.as_posix()})\\\n" if png else "```\n" + blk.group(1) + "\n```")
        text = text[:blk.start()] + repl + text[blk.end():]

    for e, t in EMOJI_MAP.items():
        text = text.replace(e, t)
    for ch in DECORATIVE:
        text = text.replace(ch + " ", "").replace(ch, "")
    text = _weight_tables(text)

    build = HERE / f"_{md.stem}_build.md"; build.write_text(text, encoding="utf-8")
    out = md.with_suffix(".pdf")
    base = ["pandoc", str(build), "-o", str(out), "--pdf-engine=xelatex",
            "--toc", "--toc-depth=2", "-V", "geometry:margin=1.7cm",
            "-V", "mainfont=DejaVu Sans", "-V", "monofont=DejaVu Sans Mono",
            "-V", "fontsize=10pt", "-V", "colorlinks=true", "-V", "linkcolor=blue",
            "-V", f"title={title}", "--resource-path", str(HERE)]
    r = subprocess.run(base, capture_output=True, text=True)
    if r.returncode != 0:
        # Common failure: literal `$` (prices) or `$VAR` (shell) parsed as TeX math. Retry
        # with math/raw-tex disabled so those are treated as plain text.
        r = subprocess.run(base + ["-f", "markdown-raw_tex-tex_math_dollars-tex_math_single_backslash"],
                           capture_output=True, text=True)
    build.unlink(missing_ok=True)
    if r.returncode != 0:
        print(f"  ✗ {md.name}: {r.stderr.strip().splitlines()[-1] if r.stderr.strip() else 'pandoc failed'}")
        return False
    print(f"  ✓ {md.name} → {out.name} ({out.stat().st_size//1024} KB)")
    return True


def main() -> int:
    args = sys.argv[1:]
    files = ([HERE / f for f in AMENDED] if (not args or args[0] == "--amended")
             else [Path(a) for a in args])
    ok = 0
    for f in files:
        if f.is_file() and convert(f):
            ok += 1
        elif not f.is_file():
            print(f"  ? missing: {f}")
    print(f"\n{ok}/{len(files)} converted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
