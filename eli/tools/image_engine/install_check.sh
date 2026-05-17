#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-$(pwd)}"

echo "[image_engine installer] Target: $ROOT"
cd "$ROOT"

if [[ ! -d image_engine ]]; then
  echo "[error] Run this from eli/tools/image_engine or pass that directory as the first argument."
  exit 1
fi

STAMP="$(date +%Y%m%d_%H%M%S)"
echo "[image_engine installer] Backing up existing image_engine -> image_engine_backup_$STAMP"
cp -r image_engine "image_engine_backup_$STAMP"

echo "[image_engine installer] Removing stale bytecode"
find . -type d -name __pycache__ -prune -exec rm -rf {} +
find . -type f -name '*.pyc' -delete

echo "[image_engine installer] Installing runtime dependencies"
python -m pip install -r requirements.txt

echo "[image_engine installer] Verifying CLI"
python -m image_engine --help | head -40
python - <<'PY'
import image_engine
from image_engine.cli import build_parser
p = build_parser()
subs = sorted(p._subparsers._group_actions[0].choices.keys())
print("image_engine import:", image_engine.__file__)
print("available subcommands:", ", ".join(subs))
assert "generate" in subs and "plot" in subs and "find" in subs
PY

echo "[image_engine installer] Done."
