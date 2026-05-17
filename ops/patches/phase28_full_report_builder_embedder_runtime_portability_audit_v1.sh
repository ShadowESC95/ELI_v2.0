#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase28_full_report_builder_embedder_runtime_portability_audit_${STAMP}"
mkdir -p "$OUT"

LOG="$OUT/FULL_PHASE28_AUDIT.txt"
exec > >(tee "$LOG") 2>&1

echo "# Phase 28 — Full Report Builder + Embedder + Runtime Truth + Portability Audit"
echo "Generated: $(date -Is)"
echo "Root: $ROOT"
echo "Python: $(python3 --version 2>&1)"
echo

echo "================================================================================"
echo "1. LIVE PROJECT STATE"
echo "================================================================================"
echo

echo "--- Git status if available ---"
git status --short 2>/dev/null || echo "NO_GIT_METADATA_OR_NOT_A_GIT_TREE"
echo

echo "--- Key files present ---"
for f in \
  eli/gui/labs_tab.py \
  eli/gui/app.py \
  eli/cognition/gguf_inference.py \
  eli/cognition/context_synthesiser.py \
  eli/memory/vector_store.py \
  eli/kernel/engine.py \
  eli/core/hardware_profile.py \
  eli/planning/proactive_daemon.py \
  eli/execution/executor_enhanced.py \
  config/settings.json \
  requirements/README_ELI_ENVIRONMENT.md \
  README.md
do
  if [ -f "$f" ]; then
    echo "FOUND   $f"
  else
    echo "MISSING $f"
  fi
done
echo

echo "================================================================================"
echo "2. RECENT REPORT BUILDER FAILURE / TIMING EVIDENCE"
echo "================================================================================"
echo

echo "--- Search logs for REPORT_BUILDER failure / fail-close / revise events ---"
grep -RInE \
  'REPORT_BUILDER|Report Builder|section_[0-9]+_revise|FAIL-CLOSED|fail-closed|returned [0-9]+ chars|minim' \
  ops/reports 2>/dev/null \
  | tail -400 \
  | tee "$OUT/02_report_builder_failure_log_hits.txt" || true
echo

echo "--- Search logs for report-builder GGUF prompt/token progression ---"
grep -RInE \
  '\[GGUF\]\[TIMING\] prompt_tokens=|\[GGUF\]\[RAW_TEXT\]|REPORT_BUILDER|section_[0-9]+_' \
  ops/reports 2>/dev/null \
  | tail -1200 \
  | tee "$OUT/03_report_builder_prompt_growth_hits.txt" || true
echo

echo "================================================================================"
echo "3. REPORT BUILDER SOURCE SURFACE"
echo "================================================================================"
echo

echo "--- labs_tab.py report-builder symbols ---"
grep -nE \
  'Report Builder|REPORT_BUILDER|report_builder|Draft Full Report|Expand Selected Section|Peer-Review Critique|section_|revise|draft|generation plan|generation_plan|fail.?closed|minimum|returned.*chars|autosave|source materials' \
  eli/gui/labs_tab.py \
  | tee "$OUT/04_labs_report_builder_symbol_hits.txt" || true
echo

echo "--- Other source references to report builder ---"
grep -RInE \
  'REPORT_BUILDER|report_builder|Report Builder|section_[0-9]+_revise|fail.?closed|returned.*chars|minimum_chars|min_chars|draft_full_report|peer.?review|expand_selected' \
  eli \
  | tee "$OUT/05_project_report_builder_symbol_hits.txt" || true
echo

echo "--- Candidate functions around report-builder generation/revision ---"
python3 - <<'PY' | tee "$OUT/06_report_builder_function_inventory.txt"
from pathlib import Path
import ast

targets = [
    Path("eli/gui/labs_tab.py"),
    Path("eli/execution/executor_enhanced.py"),
    Path("eli/kernel/engine.py"),
]
needles = (
    "report",
    "section",
    "draft",
    "revise",
    "review",
    "builder",
    "critique",
    "expand",
)

for path in targets:
    print("=" * 88)
    print(path)
    print("=" * 88)
    if not path.exists():
        print("MISSING")
        continue
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception as e:
        print("AST_PARSE_FAILED", e)
        continue
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name = node.name
            low = name.lower()
            if any(n in low for n in needles):
                print(f"{node.lineno:6d}  {name}")
PY
echo

echo "================================================================================"
echo "4. REPORT BUILDER APPEND / REPLACE / DOCUMENT ASSEMBLY RISK"
echo "================================================================================"
echo

echo "--- Search for append/insert/setPlainText/setText/write patterns near report builder ---"
grep -RInE \
  'append\(|insertPlainText|setPlainText|setText|document_view|draft_view|output_view|current_document|assembled|sections\[|section_text|replace\(|\+=|join\(' \
  eli/gui/labs_tab.py \
  | tee "$OUT/07_report_builder_append_replace_risk_hits.txt" || true
echo

echo "--- Extract local source windows around report-builder failure and document update hits ---"
python3 - <<'PY' | tee "$OUT/08_report_builder_source_windows.txt"
from pathlib import Path
import re

path = Path("eli/gui/labs_tab.py")
text = path.read_text(encoding="utf-8", errors="replace").splitlines()

patterns = [
    r"REPORT_BUILDER",
    r"fail.?closed",
    r"returned.*chars",
    r"minimum",
    r"section_.*revise",
    r"Draft Full Report",
    r"Expand Selected Section",
    r"Peer-Review Critique",
    r"setPlainText",
    r"append\(",
    r"insertPlainText",
]

seen = set()
for i, line in enumerate(text, 1):
    if any(re.search(p, line, re.I) for p in patterns):
        start = max(1, i - 5)
        end = min(len(text), i + 8)
        key = (start, end)
        if key in seen:
            continue
        seen.add(key)
        print("\n" + "=" * 100)
        print(f"LINES {start}-{end}")
        print("=" * 100)
        for j in range(start, end + 1):
            print(f"{j:6d}: {text[j-1]}")
PY
echo

echo "================================================================================"
echo "5. NOMIC EMBEDDER: ACTUAL USAGE INVENTORY"
echo "================================================================================"
echo

echo "--- All direct nomic/embed/embedder references ---"
grep -RInE \
  'nomic|embed-text|embedder|embedding_model|embedding model|models/embeddings|_embed\(|embed\(|FAISS|faiss|vector_store|hyde|HyDE|query embedding|semantic retrieval' \
  eli config scripts requirements \
  | tee "$OUT/09_nomic_embedder_usage_hits.txt" || true
echo

echo "--- Specific vector_store.py hits ---"
grep -nE \
  'nomic|embed|embedder|llama|gguf|faiss|index|vector|n_gpu_layers' \
  eli/memory/vector_store.py \
  | tee "$OUT/10_vector_store_embedder_hits.txt" || true
echo

echo "--- Runtime logs confirming embedder activation ---"
grep -RInE \
  'VECTOR_STORE|Embedder ready|nomic-embed|pre-warmed|embedding' \
  ops/reports 2>/dev/null \
  | tail -400 \
  | tee "$OUT/11_embedder_runtime_log_hits.txt" || true
echo

echo "--- Model picker enumeration code: does it filter embedder GGUFs? ---"
grep -RInE \
  'glob\(.*gguf|rglob\(.*gguf|models_dir|Available Models|Pick model number|embed|embedding|nomic|exclude|filter' \
  eli/gui/app.py eli/core/hardware_profile.py scripts \
  | tee "$OUT/12_model_picker_enumeration_hits.txt" || true
echo

echo "================================================================================"
echo "6. RUNTIME TUNING TRUTH / SPLIT-STATE AUDIT"
echo "================================================================================"
echo

echo "--- Live runtime snapshot, if present ---"
for f in \
  artifacts/runtime_snapshot.json \
  "$HOME/.local/share/eli/runtime_snapshot.json"
do
  echo
  echo "FILE: $f"
  if [ -f "$f" ]; then
    python3 - "$f" <<'PY'
import json, sys
p = sys.argv[1]
d = json.load(open(p, "r", encoding="utf-8"))
keys = [
    "provider", "model_path", "model_name", "loaded", "runtime_contract",
    "n_ctx", "n_gpu_layers", "n_threads", "n_batch", "batch_size",
    "requested_n_ctx", "requested_n_gpu_layers", "requested_n_threads", "requested_n_batch",
]
for k in keys:
    print(f"{k} = {d.get(k)!r}")
print("requested =", d.get("requested"))
print("effective =", d.get("effective"))
PY
  else
    echo "MISSING"
  fi
done | tee "$OUT/13_runtime_snapshot_dump.txt"
echo

echo "--- Runtime conflict log hits: picker vs hardware-profile reapply ---"
grep -RInE \
  'Hardware profile re-applied|profiler-recommended|n_gpu_layers: .*→|batch_size: .*→|Effective llama.cpp runtime|Parameters confirmed|auto-tuned|Llama load OK|\[GGUF\]\[EFFECTIVE\]' \
  ops/reports 2>/dev/null \
  | tail -800 \
  | tee "$OUT/14_runtime_conflict_log_hits.txt" || true
echo

echo "--- hardware_profile.py relevant policy lines ---"
grep -nE \
  'gpu_layers|batch_size|n_ctx|max_tokens|free_vram|profile|recommend|apply|settings exceed|re-applied|chosen_layers|n_gpu_layers' \
  eli/core/hardware_profile.py \
  | tee "$OUT/15_hardware_profile_policy_hits.txt" || true
echo

echo "--- engine.py reapplication / live runtime lines ---"
grep -nE \
  'Hardware profile re-applied|hardware_profile|gpu_layers|batch_size|settings exceed|_live_runtime_snapshot|_gpu_layers|runtime_snapshot' \
  eli/kernel/engine.py \
  | tee "$OUT/16_engine_runtime_reapply_hits.txt" || true
echo

echo "--- app.py picker/load/runtime lines ---"
grep -nE \
  'Available Models|Pick model|Parameters|auto-tuned|n_gpu_layers|batch_size|runtime|preloaded|Llama load OK|write.*snapshot|_PRELOADED|hardware' \
  eli/gui/app.py \
  | tee "$OUT/17_app_picker_runtime_hits.txt" || true
echo

echo "================================================================================"
echo "7. SELF-IMPROVEMENT / FAILURE CAPTURE AUDIT"
echo "================================================================================"
echo

echo "--- Failure/improvement recording source hits ---"
grep -RInE \
  'failure|failures|record_failure|improvement|self-improvement|Self-Improvement|improvement cycle|report_builder|REPORT_BUILDER|FAIL-CLOSED' \
  eli \
  | tee "$OUT/18_failure_improvement_source_hits.txt" || true
echo

echo "--- Runtime logs: visible failures vs stored failure handling ---"
grep -RInE \
  'REPORT_BUILDER FAIL-CLOSED|FAIL-CLOSED|Failed|failure|Self-improvement cycle|No failures recorded|No new improvement records' \
  ops/reports 2>/dev/null \
  | tail -1000 \
  | tee "$OUT/19_failure_improvement_runtime_hits.txt" || true
echo

echo "================================================================================"
echo "8. RAPPORT / QUICK CHAT CONTEXT LEAK AUDIT"
echo "================================================================================"
echo

echo "--- Source hits for rapport, persona handoff, memory skip, proactive/context leakage ---"
grep -RInE \
  'rapport|skipping memory/HyDE|HyDE|persona handoff|Persona handoff|topic_focus|active_project|proactive|brief|quick|greeting|casual' \
  eli \
  | tee "$OUT/20_rapport_context_source_hits.txt" || true
echo

echo "--- Relevant runtime logs around rapport greeting path ---"
grep -RInE \
  "What's the story pal|how is the head|rapport prompt|skipping memory/HyDE|Persona handoff|topic_focus|active_project|entropy|coherence" \
  ops/reports 2>/dev/null \
  | tail -800 \
  | tee "$OUT/21_rapport_context_runtime_hits.txt" || true
echo

echo "================================================================================"
echo "9. HARD-CODED PATH / PORTABILITY AUDIT"
echo "================================================================================"
echo

echo "--- /home/jay or other machine-specific absolute paths in redistributable surfaces ---"
grep -RInE \
  '/home/jay|/Users/jay|Desktop/ELI|ELI_MKXI-main_MAY_NEWEST|/mnt/|/media/' \
  eli scripts config requirements packaging README.md pyproject.toml setup.py .env.mkxi 2>/dev/null \
  | tee "$OUT/22_machine_specific_path_hits.txt" || true
echo

echo "--- Absolute Linux paths that may be legitimate or may need review ---"
grep -RInE \
  '"/(home|usr|opt|var|tmp|etc)/|'\''/(home|usr|opt|var|tmp|etc)/' \
  eli scripts config requirements packaging README.md pyproject.toml setup.py .env.mkxi 2>/dev/null \
  | tee "$OUT/23_absolute_path_review_hits.txt" || true
echo

echo "--- Environment/path helpers currently used ---"
grep -RInE \
  'ELI_PROJECT_ROOT|get_paths\(|Path\(__file__\)|artifacts_dir|models_dir|config_dir|Path\.home\(|XDG|platformdirs' \
  eli scripts config \
  | tee "$OUT/24_portable_path_helper_hits.txt" || true
echo

echo "================================================================================"
echo "10. REQUIREMENTS / README / REDISTRIBUTION INSTRUCTION AUDIT"
echo "================================================================================"
echo

echo "--- Requirement files discovered ---"
find . -maxdepth 3 -type f \
  \( -iname 'requirements*.txt' -o -iname 'pyproject.toml' -o -iname 'setup.py' -o -iname 'README*.md' \) \
  | sort \
  | tee "$OUT/25_manifest_inventory.txt"
echo

echo "--- README / environment docs relevant hits ---"
grep -RInE \
  'install|setup|venv|python|PySide6|PyQt|CUDA|llama-cpp|CUDA toolkit|nvidia|Piper|tesseract|ffmpeg|requirements|model picker|first run|redistribut|commercial|Linux|Ubuntu' \
  README*.md requirements/*.md docs/*.md packaging/* 2>/dev/null \
  | tee "$OUT/26_readme_requirements_instruction_hits.txt" || true
echo

echo "--- Current pip integrity ---"
python3 -m pip check | tee "$OUT/27_pip_check.txt" || true
echo

echo "--- Key import availability matrix ---"
python3 - <<'PY' | tee "$OUT/28_import_matrix.txt"
import importlib.util

mods = [
    "PySide6",
    "llama_cpp",
    "faiss",
    "numpy",
    "psutil",
    "cv2",
    "PIL",
    "pypdf",
    "pdfplumber",
    "faster_whisper",
    "sounddevice",
    "speech_recognition",
    "pyvista",
    "torch",
    "transformers",
]
for mod in mods:
    print(f"{mod:24s} -> {'FOUND' if importlib.util.find_spec(mod) else 'MISSING'}")
PY
echo

echo "================================================================================"
echo "11. COMPILE KEY SURFACES"
echo "================================================================================"
echo

python3 -m py_compile \
  eli/gui/app.py \
  eli/gui/labs_tab.py \
  eli/cognition/gguf_inference.py \
  eli/cognition/context_synthesiser.py \
  eli/memory/vector_store.py \
  eli/kernel/engine.py \
  eli/core/hardware_profile.py \
  eli/planning/proactive_daemon.py \
  eli/execution/executor_enhanced.py \
  && echo "PHASE28_COMPILE_OK" \
  | tee "$OUT/29_compile_key_surfaces.txt"

echo
echo "================================================================================"
echo "12. SUMMARY FILE"
echo "================================================================================"
echo

cat > "$OUT/SUMMARY.md" <<EOF
# Phase 28 — Full Analysis Summary

## Purpose
Evidence-only audit of:
1. Report Builder duplication, token inflation, and fail-close behavior.
2. Nomic embedder usage and incorrect visibility in the main model picker.
3. Runtime tuning split-state between picker, hardware profiler, and GGUF live snapshot.
4. Failure/self-improvement recording gaps.
5. Quick/rapport context contamination.
6. Hard-coded path portability risks.
7. README / requirements / redistribution documentation completeness.

## Primary outputs
- \`02_report_builder_failure_log_hits.txt\`
- \`03_report_builder_prompt_growth_hits.txt\`
- \`04_labs_report_builder_symbol_hits.txt\`
- \`05_project_report_builder_symbol_hits.txt\`
- \`06_report_builder_function_inventory.txt\`
- \`07_report_builder_append_replace_risk_hits.txt\`
- \`08_report_builder_source_windows.txt\`
- \`09_nomic_embedder_usage_hits.txt\`
- \`10_vector_store_embedder_hits.txt\`
- \`11_embedder_runtime_log_hits.txt\`
- \`12_model_picker_enumeration_hits.txt\`
- \`13_runtime_snapshot_dump.txt\`
- \`14_runtime_conflict_log_hits.txt\`
- \`15_hardware_profile_policy_hits.txt\`
- \`16_engine_runtime_reapply_hits.txt\`
- \`17_app_picker_runtime_hits.txt\`
- \`18_failure_improvement_source_hits.txt\`
- \`19_failure_improvement_runtime_hits.txt\`
- \`20_rapport_context_source_hits.txt\`
- \`21_rapport_context_runtime_hits.txt\`
- \`22_machine_specific_path_hits.txt\`
- \`23_absolute_path_review_hits.txt\`
- \`24_portable_path_helper_hits.txt\`
- \`25_manifest_inventory.txt\`
- \`26_readme_requirements_instruction_hits.txt\`
- \`27_pip_check.txt\`
- \`28_import_matrix.txt\`
- \`29_compile_key_surfaces.txt\`

## No source modifications
This phase performs no project code edits.
EOF

cat "$OUT/SUMMARY.md"

echo
echo "PHASE28_OUT=$OUT"
echo "PRIMARY_LOG=$LOG"
