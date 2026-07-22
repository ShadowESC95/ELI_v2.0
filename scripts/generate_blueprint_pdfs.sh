#!/usr/bin/env bash
# Regenerate the SHIPPED blueprint PDFs from their markdown sources.
#
# The git-tracked PDFs (allowlisted in .gitignore) are bundled into every
# installer, so this is their single reproducible build path — markdown sources
# stay local (gitignored), PDFs are committed. Requires pandoc + xelatex.
#
# Every PDF is stamped with the version from pyproject.toml and today's date, so
# "rebuild the manuals" is one command and no document can drift on its own.
#
#   bash scripts/generate_blueprint_pdfs.sh                # all of them
#   bash scripts/generate_blueprint_pdfs.sh installation   # just one (by stem)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BP="$ROOT/blueprints"
command -v pandoc >/dev/null || { echo "pandoc required" >&2; exit 1; }
command -v xelatex >/dev/null || { echo "xelatex required" >&2; exit 1; }

VERSION="$(grep -E '^version' "$ROOT/pyproject.toml" | head -1 | awk -F'"' '{print $2}')"
DATE="$(date +'%B %Y')"
ONLY="${1:-}"

# Latin Modern (xelatex's default) has no box-drawing or symbol glyphs, so the
# ASCII architecture diagrams came out full of holes and warnings like
# "Missing character: There is no ─ (U+2500)". DejaVu covers both, so use it
# where it matters and fall back silently if it isn't installed on this box.
# Capture once into a variable rather than piping into `grep -q`: under
# `set -o pipefail`, grep -q exits at the first match, fc-list dies on SIGPIPE,
# and the whole pipeline reports failure — so the check silently never fired.
FONT_ARGS=()
FONTS_AVAILABLE="$(fc-list 2>/dev/null || true)"
case "$FONTS_AVAILABLE" in
  *DejaVuSansMono*) FONT_ARGS+=(-V monofont="DejaVu Sans Mono" -V monofontoptions="Scale=0.85") ;;
esac
case "$FONTS_AVAILABLE" in
  # Only symbol coverage matters for body text (⚠, arrows, ·); DejaVu Serif
  # keeps a serif look close to the previous editions.
  *DejaVuSerif*) FONT_ARGS+=(-V mainfont="DejaVu Serif" -V mainfontoptions="Scale=0.92") ;;
esac

# NOTE: '&' is a LaTeX alignment character — never put one in a title string.
pdf() { # pdf <out-stem> <title> <subtitle> <src.md...>
  local stem="$1" title="$2" subtitle="$3"; shift 3
  if [ -n "$ONLY" ] && [ "$ONLY" != "$stem" ]; then return 0; fi
  for f in "$@"; do [ -f "$f" ] || { echo "missing source: $f" >&2; exit 1; }; done
  pandoc "$@" -o "$BP/$stem.pdf" \
    --pdf-engine=xelatex \
    --lua-filter="$ROOT/scripts/pandoc_pdf_glyphs.lua" \
    "${FONT_ARGS[@]}" \
    -V geometry:margin=0.9in -V fontsize=10pt -V documentclass=article \
    -V colorlinks=true -V linkcolor=blue -V urlcolor=blue \
    --toc --toc-depth=2 \
    -V title="$title" -V subtitle="$subtitle" -V date="$DATE"
  echo "[OK] $stem.pdf"
}

# ── User-facing manuals ────────────────────────────────────────────────────
pdf ELI_USER_MANUAL "ELI — The Complete User Manual" "ELI v$VERSION" \
    "$BP/ELI_USER_MANUAL.md"

pdf what_eli_is_and_can_do "What ELI Is — and What It Can Do" "ELI v$VERSION" \
    "$BP/what_eli_is.md" "$BP/what_eli_can_do.md"

# ── Install / operate guides ───────────────────────────────────────────────
pdf installation "ELI — Installation" "ELI v$VERSION" \
    "$BP/installation.md"

pdf new_user_install_guide "ELI — New User Installation Guide" \
    "ELI v$VERSION · Linux · Windows · macOS" \
    "$BP/new_user_install_guide.md"

pdf full_setup_guide "ELI — Full Setup Guide" "ELI v$VERSION" \
    "$BP/full_setup_guide.md"

pdf commands_and_installers "ELI — Commands and Installers" "ELI v$VERSION" \
    "$BP/commands_and_installers.md"

pdf portable_scripts_guide "ELI — Portable Scripts Guide" "ELI v$VERSION" \
    "$BP/portable_scripts_guide.md"

pdf common_errors_and_fixes "ELI — Common Errors and Fixes" "ELI v$VERSION" \
    "$BP/common_errors_and_fixes.md"

# ── FULL technical manual ──────────────────────────────────────────────────
# = the user manual + the architecture blueprint set, in reading order. Sources
# that are absent are reported, not skipped silently — the FULL manual must
# never quietly thin out.
FULL_SOURCES=(
  ELI_USER_MANUAL.md
  architecture.md architecture_ascii.md dag_orchestrator.md
  orchestration_and_agents.md agent_algorithms.md memory.md perception.md
  grounding_and_evidence.md code_mode_execution_layer.md coding_agent.md
  inference_and_hardware.md adaptive_inference_governor.md learning.md
  lora_pipeline.md background_tasks.md runtime_planning_world.md
  operations.md running_eli_at_scale.md security.md diagrams.md
  capabilities_and_actions.md
)
FULL_PATHS=()
for f in "${FULL_SOURCES[@]}"; do
  if [ -f "$BP/$f" ]; then FULL_PATHS+=("$BP/$f"); else echo "[WARN] FULL manual source missing: $f" >&2; fi
done
[ "${#FULL_PATHS[@]}" -ge 10 ] || { echo "too few FULL-manual sources present (${#FULL_PATHS[@]})" >&2; exit 1; }
pdf ELI_USER_MANUAL_FULL "ELI — Complete Technical Manual" "ELI v$VERSION" "${FULL_PATHS[@]}"
