#!/usr/bin/env bash
# Rebuild EVERY PDF in blueprints/ from its markdown source, so no PDF is stale.
#
# Two passes:
#   1. Every blueprints/<stem>.md that already has a <stem>.pdf is rebuilt 1:1
#      (the ~25 internal architecture docs — architecture, perception, memory, …).
#   2. scripts/generate_blueprint_pdfs.sh then rebuilds the 9 shipped/composite
#      PDFs (the two user manuals + what_eli_is_and_can_do) with their proper
#      titles. Running it second means the shipped set wins its nicer formatting.
#
# Same rendering as the shipped builder: DejaVu fonts + the print-safe glyph Lua
# filter + a version/date stamp. Requires pandoc + xelatex.
#
#   bash scripts/generate_all_blueprint_pdfs.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BP="$ROOT/blueprints"
command -v pandoc >/dev/null || { echo "pandoc required" >&2; exit 1; }
command -v xelatex >/dev/null || { echo "xelatex required" >&2; exit 1; }

VERSION="$(grep -E '^version' "$ROOT/pyproject.toml" | head -1 | awk -F'"' '{print $2}')"
DATE="$(date +'%B %Y')"

FONT_ARGS=()
FONTS="$(fc-list 2>/dev/null || true)"
case "$FONTS" in *DejaVuSansMono*) FONT_ARGS+=(-V monofont="DejaVu Sans Mono" -V monofontoptions="Scale=0.85") ;; esac
case "$FONTS" in *DejaVuSerif*) FONT_ARGS+=(-V mainfont="DejaVu Serif" -V mainfontoptions="Scale=0.92") ;; esac

# Composite sources that only exist inside a combined PDF — never build standalone.
SKIP_STEMS=" what_eli_is what_eli_can_do "

title_from_stem() {  # architecture_ascii -> "Architecture Ascii"
  echo "$1" | tr '_-' '  ' | awk '{for(i=1;i<=NF;i++) $i=toupper(substr($i,1,1)) substr($i,2)} 1'
}

built=0
for md in "$BP"/*.md; do
  stem="$(basename "$md" .md)"
  case "$SKIP_STEMS" in *" $stem "*) continue ;; esac
  [ -f "$BP/$stem.pdf" ] || continue   # only refresh PDFs that already exist (don't invent new ones)
  title="ELI — $(title_from_stem "$stem")"
  pandoc "$md" -o "$BP/$stem.pdf" \
    --pdf-engine=xelatex \
    --lua-filter="$ROOT/scripts/pandoc_pdf_glyphs.lua" \
    "${FONT_ARGS[@]}" \
    -V geometry:margin=0.9in -V fontsize=10pt -V documentclass=article \
    -V colorlinks=true -V linkcolor=blue -V urlcolor=blue \
    --toc --toc-depth=2 \
    -V title="$title" -V subtitle="ELI v$VERSION" -V date="$DATE" 2>/dev/null \
    && { echo "[OK] $stem.pdf"; built=$((built+1)); } \
    || echo "[WARN] $stem.pdf failed (kept previous)" >&2
done
echo "[pass 1] rebuilt $built standalone PDFs"

# Pass 2: the shipped/composite PDFs with their curated titles.
bash "$ROOT/scripts/generate_blueprint_pdfs.sh"
echo "[done] every blueprints PDF regenerated at v$VERSION"
