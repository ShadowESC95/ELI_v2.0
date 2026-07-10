#!/usr/bin/env bash
# Regenerate the SHIPPED blueprint PDFs from their markdown sources.
#
# Only three blueprint PDFs are git-tracked (and therefore bundled into every
# installer): the two user manuals and what_eli_is_and_can_do. This script is
# their single reproducible build path — markdown sources stay local
# (gitignored), PDFs are committed. Requires pandoc + xelatex.
#
#   bash scripts/generate_blueprint_pdfs.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BP="$ROOT/blueprints"
command -v pandoc >/dev/null || { echo "pandoc required" >&2; exit 1; }
command -v xelatex >/dev/null || { echo "xelatex required" >&2; exit 1; }

VERSION="$(grep -E '^version' "$ROOT/pyproject.toml" | head -1 | awk -F'"' '{print $2}')"
DATE="$(date +'%B %Y')"

pdf() { # pdf <out.pdf> <title> <src.md...>
  local out="$1" title="$2"; shift 2
  for f in "$@"; do [ -f "$f" ] || { echo "missing source: $f" >&2; exit 1; }; done
  pandoc "$@" -o "$out" \
    --pdf-engine=xelatex \
    -V geometry:margin=0.9in -V fontsize=10pt -V documentclass=article \
    -V colorlinks=true -V linkcolor=blue -V urlcolor=blue \
    --toc --toc-depth=2 \
    -V title="$title" -V subtitle="ELI v$VERSION" -V date="$DATE"
  echo "[OK] $out"
}

pdf "$BP/ELI_USER_MANUAL.pdf" "ELI — The Complete User Manual" \
    "$BP/ELI_USER_MANUAL.md"

pdf "$BP/what_eli_is_and_can_do.pdf" "What ELI Is — and What It Can Do" \
    "$BP/what_eli_is.md" "$BP/what_eli_can_do.md"

# The FULL (technical) manual = the user manual + the architecture blueprint
# set, in reading order. Sources that are absent are reported, not skipped
# silently — the FULL manual must never quietly thin out.
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
pdf "$BP/ELI_USER_MANUAL_FULL.pdf" "ELI — Complete Technical Manual" "${FULL_PATHS[@]}"
