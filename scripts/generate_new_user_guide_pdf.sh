#!/usr/bin/env bash
# Regenerate blueprints/new_user_install_guide.pdf from the local markdown source.
# Markdown is gitignored; only the PDF is committed.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MD="$ROOT/blueprints/new_user_install_guide.md"
PDF="$ROOT/blueprints/new_user_install_guide.pdf"
command -v pandoc >/dev/null 2>&1 || { echo "pandoc required" >&2; exit 1; }
[ -f "$MD" ] || { echo "missing $MD" >&2; exit 1; }
pandoc "$MD" -o "$PDF" \
  --pdf-engine=xelatex \
  -V geometry:margin=0.9in \
  -V fontsize=10pt \
  -V documentclass=article \
  -V colorlinks=true \
  -V linkcolor=blue \
  -V urlcolor=blue \
  --toc --toc-depth=2 \
  -V title="ELI v2.0 — New User Installation Guide" \
  -V subtitle="Linux · Windows · macOS" \
  -V date="$(date +'%B %Y')"
echo "[OK] $PDF"
