#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase27_restore_picker_first_boot_remove_forced_model_env_${STAMP}"
mkdir -p "$OUT"

echo "# Phase 27 — Restore Picker-First Boot + Remove Forced Model Env" | tee "$OUT/SUMMARY.md"
echo "Generated: $(date -Is)" | tee -a "$OUT/SUMMARY.md"
echo "Root: $ROOT" | tee -a "$OUT/SUMMARY.md"
echo | tee -a "$OUT/SUMMARY.md"

echo "=== 1. BACK UP CURRENT LAUNCHER / ENV / README ===" | tee "$OUT/01_backup.txt"

for f in \
  scripts/run_eli_repo_venv.sh \
  .env.mkxi \
  requirements/README_ELI_ENVIRONMENT.md
do
  if [ -f "$f" ]; then
    cp -a "$f" "$OUT/$(basename "$f").before_phase27.bak"
    echo "BACKED_UP $f" | tee -a "$OUT/01_backup.txt"
  else
    echo "MISSING $f" | tee -a "$OUT/01_backup.txt"
  fi
done

echo
echo "=== 2. REWRITE RUNNER TO USE PICKER-FIRST APP ENTRYPOINT ==="

cat > scripts/run_eli_repo_venv.sh <<'RUN'
#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -x "$ROOT/.venv/bin/python3" ]]; then
  echo "ELI launch failed: missing project venv at:"
  echo "  $ROOT/.venv"
  exit 1
fi

# Activate the project-local environment.
# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"

# Portable project root for all runtime path resolution.
export ELI_PROJECT_ROOT="$ROOT"

# Ensure ELI imports resolve from the repo root.
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

# Load optional project environment settings, but do not allow them
# to force a model selection before the picker stage.
if [[ -f "$ROOT/.env.mkxi" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT/.env.mkxi"
fi

# Model choice must be controlled by the picker flow, not stale shell vars.
unset ELI_GGUF_MODEL_PATH
unset ELI_MODEL_PATH
unset ELI_MODEL
unset GGUF_MODEL_PATH

# Canonical launch route:
# app.py owns the model picker / startup orchestration.
exec python3 -m eli.gui.app "$@"
RUN

chmod +x scripts/run_eli_repo_venv.sh

sed -n '1,220p' scripts/run_eli_repo_venv.sh | tee "$OUT/02_new_runner.txt"

echo
echo "=== 3. REMOVE MACHINE-SPECIFIC FORCED MODEL EXPORTS FROM .env.mkxi ==="

if [[ -f .env.mkxi ]]; then
  python3 - <<'PY'
from pathlib import Path

p = Path(".env.mkxi")
text = p.read_text(encoding="utf-8", errors="replace")
lines = text.splitlines()

kill_prefixes = (
    "export ELI_GGUF_MODEL_PATH=",
    "export ELI_MODEL_PATH=",
    "export ELI_MODEL=",
    "export GGUF_MODEL_PATH=",
)

kept = []
removed = []

for line in lines:
    stripped = line.strip()
    if any(stripped.startswith(prefix) for prefix in kill_prefixes):
        removed.append(line)
        continue
    kept.append(line)

p.write_text("\n".join(kept).rstrip() + "\n", encoding="utf-8")

print("REMOVED_MODEL_ENV_EXPORTS =", len(removed))
for line in removed:
    print("REMOVED:", line)
PY
else
  echo ".env.mkxi not present; nothing to sanitize."
fi | tee "$OUT/03_env_model_force_cleanup.txt"

echo
echo "=== 4. SANITIZE /home/jay PATHS IN REQUIREMENTS README ==="

if [[ -f requirements/README_ELI_ENVIRONMENT.md ]]; then
  python3 - <<'PY'
from pathlib import Path

p = Path("requirements/README_ELI_ENVIRONMENT.md")
text = p.read_text(encoding="utf-8", errors="replace")

old = "/home/jay/Desktop/ELI_MKXI-main_MAY_NEWEST"
text = text.replace(old, "${ELI_PROJECT_ROOT:-<project-root>}")

p.write_text(text, encoding="utf-8")
print("README_PATH_SANITIZE_DONE")
PY
else
  echo "README missing; skipped."
fi | tee "$OUT/04_readme_portability_cleanup.txt"

echo
echo "=== 5. VERIFY NO RUNTIME /JAY PATHS REMAIN IN TARGETED PORTABLE SURFACES ==="

rg -n \
  '/home/jay|ELI_GGUF_MODEL_PATH=|ELI_MODEL_PATH=|export ELI_MODEL=|GGUF_MODEL_PATH=' \
  scripts/run_eli_repo_venv.sh .env.mkxi requirements/README_ELI_ENVIRONMENT.md \
  2>/dev/null \
  | tee "$OUT/05_remaining_targeted_path_hits.txt" \
  || true

echo
echo "=== 6. PYTHON IMPORT PROBE FOR PICKER ENTRYPOINT ==="

python3 - <<'PY' | tee "$OUT/06_picker_import_probe.txt"
import importlib.util

for mod in ("eli", "eli.gui.app", "eli.gui.eli_pro_audio_gui_MKI"):
    spec = importlib.util.find_spec(mod)
    print(f"{mod:34s} -> {'FOUND' if spec else 'MISSING'}")
PY

echo
echo "=== 7. COMPILE KEY FILES ==="

python3 -m py_compile \
  eli/gui/app.py \
  eli/gui/eli_pro_audio_gui_MKI.py \
  eli/cognition/gguf_inference.py \
  2>&1 | tee "$OUT/07_compile.txt"

echo "PHASE27_COMPILE_OK" | tee -a "$OUT/07_compile.txt"

echo
echo "=== 8. SUMMARY ==="

cat >> "$OUT/SUMMARY.md" <<EOF

## Changes applied
1. Rewrote \`scripts/run_eli_repo_venv.sh\` so ELI launches via:
   \`python3 -m eli.gui.app\`
2. Preserved project-local venv activation and portable \`ELI_PROJECT_ROOT\`.
3. Removed pre-picker forced model environment exports from \`.env.mkxi\`.
4. Sanitized known \`/home/jay/Desktop/ELI_MKXI-main_MAY_NEWEST\` paths from:
   \`requirements/README_ELI_ENVIRONMENT.md\`
5. Compiled key GUI / GGUF files after the launcher patch.

## Expected next behavior
Running:

\`\`\`bash
./scripts/run_eli_repo_venv.sh
\`\`\`

should open the model-picker boot flow before any GGUF model load begins.

If GGUF load attempts still occur before a picker appears, then a deeper autoload path remains inside the app/bootstrap code and must be patched next.
EOF

cat "$OUT/SUMMARY.md"

echo
echo "PHASE27_OUT=$OUT"
