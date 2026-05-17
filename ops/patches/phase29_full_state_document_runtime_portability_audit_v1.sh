#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase29_full_state_document_runtime_portability_audit_${STAMP}"
mkdir -p "$OUT"

say() {
  printf '%s\n' "$*" | tee -a "$OUT/SUMMARY.md"
}

{
  echo "# Phase 29 — Full-State Document / Runtime / Portability Audit"
  echo
  echo "Generated: $(date -Is)"
  echo "Root: $ROOT"
  echo "Mode: audit only — no source files modified"
  echo
} > "$OUT/SUMMARY.md"

say "## Audit intent"
say "This audit captures the current live implementation of:"
say "- Report Builder / Labs document engine"
say "- Picker-first model/runtime setup"
say "- Hardware profiling authority and runtime-truth consistency"
say "- Nomic embedder scoping"
say "- Portability / hard-coded paths"
say "- README / requirements / packaging instruction surfaces"
say "- Failure telemetry and Self-Improvement integration"
say

echo "=== 00. REPO STATUS ===" > "$OUT/00_repo_status.txt"
{
  echo "PWD=$ROOT"
  echo
  echo "--- git status --short ---"
  git status --short 2>&1 || true
  echo
  echo "--- recent tracked modified files if git is available ---"
  git diff --stat 2>&1 || true
} >> "$OUT/00_repo_status.txt"

echo "=== 01. KEY FILE PRESENCE ===" > "$OUT/01_key_file_presence.txt"
for f in \
  eli/gui/labs_tab.py \
  eli/gui/app.py \
  eli/core/hardware_profile.py \
  eli/cognition/gguf_inference.py \
  eli/kernel/engine.py \
  eli/memory/vector_store.py \
  eli/execution/executor_enhanced.py \
  eli/runtime/generated_script_guard.py \
  eli/gui/eli_pro_audio_gui_MKI.py \
  README.md \
  requirements/README_ELI_ENVIRONMENT.md \
  pyproject.toml \
  eli/__main__.py \
  scripts/run_eli_repo_venv.sh
do
  if [[ -f "$f" ]]; then
    printf 'FOUND  %s\n' "$f"
  else
    printf 'MISSING %s\n' "$f"
  fi
done >> "$OUT/01_key_file_presence.txt"

echo "=== 02. PYTHON COMPILE OF CORE TARGETS ===" > "$OUT/02_compile_targets.txt"
python3 -m py_compile \
  eli/gui/labs_tab.py \
  eli/gui/app.py \
  eli/core/hardware_profile.py \
  eli/cognition/gguf_inference.py \
  eli/kernel/engine.py \
  eli/memory/vector_store.py \
  eli/execution/executor_enhanced.py \
  eli/runtime/generated_script_guard.py \
  eli/gui/eli_pro_audio_gui_MKI.py \
  2>&1 | tee -a "$OUT/02_compile_targets.txt" || true

echo "=== 03. IMPORT MATRIX ===" > "$OUT/03_import_matrix.txt"
python3 - <<'PY' >> "$OUT/03_import_matrix.txt"
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
    "eli",
    "eli.gui.app",
    "eli.gui.labs_tab",
    "eli.core.hardware_profile",
    "eli.cognition.gguf_inference",
    "eli.kernel.engine",
    "eli.memory.vector_store",
    "eli.execution.executor_enhanced",
]
for mod in mods:
    print(f"{mod:<38} -> {'FOUND' if importlib.util.find_spec(mod) else 'MISSING'}")
PY

echo "=== 04. PIP CHECK ===" > "$OUT/04_pip_check.txt"
python3 -m pip check >> "$OUT/04_pip_check.txt" 2>&1 || true

echo "=== 05. ACTIVE MODEL TREE ===" > "$OUT/05_model_tree.txt"
{
  echo "--- models/*.gguf tree ---"
  find models -type f -name '*.gguf' -printf '%P\t%s bytes\n' 2>/dev/null | sort || true
  echo
  echo "--- embedding-tagged GGUFs ---"
  find models -type f -name '*.gguf' 2>/dev/null \
    | grep -Ei 'embed|embedding|nomic|bge' || true
} >> "$OUT/05_model_tree.txt"

echo "=== 06. MODEL PICKER / APP STARTUP SURFACES ===" > "$OUT/06_model_picker_app_hits.txt"
rg -n \
  'MODELS_DIR|rglob\("\*\.gguf"\)|discover_models|Pick model number|Available Models|--setup|auto-tuned|n_ctx|n_gpu_layers|batch_size|max_tokens|pre-warm|prewarm|nomic-embed|runtime snapshot|Llama load attempt|preloaded' \
  eli/gui/app.py \
  scripts/run_eli_repo_venv.sh \
  eli/__main__.py \
  pyproject.toml \
  2>&1 >> "$OUT/06_model_picker_app_hits.txt" || true

echo "=== 07. HARDWARE PROFILE SURFACES ===" > "$OUT/07_hardware_profile_hits.txt"
rg -n \
  'recommend|discover_models|_is_embedder_path|gpu_layers|n_gpu_layers|batch|batch_size|n_ctx|threads|VRAM|free|RAM|model_path invalid|embedder|settings exceed profiler|Hardware profile re-applied|recommended' \
  eli/core/hardware_profile.py \
  eli/kernel/engine.py \
  eli/gui/app.py \
  eli/cognition/gguf_inference.py \
  2>&1 >> "$OUT/07_hardware_profile_hits.txt" || true

echo "=== 08. EXACT FUNCTION INVENTORY — REPORT BUILDER ===" > "$OUT/08_report_builder_function_inventory.txt"
python3 - <<'PY' >> "$OUT/08_report_builder_function_inventory.txt"
import ast
from pathlib import Path

p = Path("eli/gui/labs_tab.py")
src = p.read_text(encoding="utf-8")
tree = ast.parse(src)

targets = {
    "_reports_output_dir",
    "_autosave_report",
    "_build_section_prompt",
    "_build_draft_prompt",
    "_build_expand_prompt",
    "_build_critique_prompt",
    "_current_preview_prompt",
    "_copy_preview_prompt",
    "_refresh_prompt_preview",
    "_rb_section_target_words",
    "_rb_section_map",
    "_rb_section_brief",
    "_rb_section_prompt",
    "_rb_generate_section",
    "_rb_section_review_prompt",
    "_rb_section_revision_prompt",
    "_rb_review_and_revise_section",
    "_validate_generated_report",
    "_draft_full_with_eli",
    "_ask_eli_expand_selection",
    "_ask_eli_critique",
}

for node in ast.walk(tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in targets:
        print(f"{node.lineno:>6}  {node.name}")
PY

echo "=== 09. REPORT BUILDER TARGETED CODE WINDOWS ===" > "$OUT/09_report_builder_code_windows.txt"
python3 - <<'PY' >> "$OUT/09_report_builder_code_windows.txt"
import ast
from pathlib import Path

p = Path("eli/gui/labs_tab.py")
lines = p.read_text(encoding="utf-8").splitlines()
tree = ast.parse("\n".join(lines))

targets = [
    "_rb_section_prompt",
    "_rb_generate_section",
    "_rb_section_review_prompt",
    "_rb_section_revision_prompt",
    "_rb_review_and_revise_section",
    "_validate_generated_report",
    "_draft_full_with_eli",
]

defs = {}
for node in ast.walk(tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in targets:
        defs[node.name] = (node.lineno, getattr(node, "end_lineno", node.lineno))

for name in targets:
    print("=" * 110)
    print(name)
    print("=" * 110)
    if name not in defs:
        print("MISSING")
        continue
    start, end = defs[name]
    pad_start = max(1, start - 6)
    pad_end = min(len(lines), end + 6)
    for i in range(pad_start, pad_end + 1):
        print(f"{i:>6}: {lines[i-1]}")
PY

echo "=== 10. REPORT BUILDER PROMPT / BUDGET / LOOP HITS ===" > "$OUT/10_report_builder_budget_loop_hits.txt"
rg -n \
  'ELI_REPORT_BUILDER|target_total_words|target_section_words|chunk_goal_words|max_chunks_per_section|review_section_char_limit|SECTION_EVIDENCE|OUTLINE_EVIDENCE|GLOBAL_POLISH|min_chars|minimum required|continuation|existing_section|assembled =|assembled_sections|section_text|fail-closed|FAIL-CLOSED|validation_detail|_rb_call|generate_from_assembled_prompt|max_tokens' \
  eli/gui/labs_tab.py \
  ops/reports/phase21_frontier_report_builder_engine_*/* \
  2>&1 >> "$OUT/10_report_builder_budget_loop_hits.txt" || true

echo "=== 11. REPORT BUILDER DUPLICATION / RESTART GUARD SEARCH ===" > "$OUT/11_report_builder_guard_search.txt"
rg -n \
  'dedup|de-dup|duplicate|overlap|similarity|jaccard|difflib|SequenceMatcher|heading.*repeat|repeated heading|restart section|starts?with.*##|prefix overlap|paragraph overlap|continuation validation|reject continuation|same subsection|near-duplicate' \
  eli/gui/labs_tab.py \
  eli/cognition \
  eli/runtime \
  2>&1 >> "$OUT/11_report_builder_guard_search.txt" || true

echo "=== 12. MOST RECENT LIVE REPORT-BUILDER / GGUF LOG EXTRACT ===" > "$OUT/12_recent_live_report_builder_log_extract.txt"
LATEST_LOG="$(ls -1t ops/reports/*.log 2>/dev/null | head -1 || true)"
{
  echo "LATEST_LOG=$LATEST_LOG"
  echo
  if [[ -n "$LATEST_LOG" && -f "$LATEST_LOG" ]]; then
    rg -n \
      'REPORT_BUILDER|GGUF\]\[TIMING|GGUF\]\[RAW_TEXT|FAIL-CLOSED|prompt_tokens|max_tokens|Hardware profile re-applied|EFFECTIVE|ADAPTIVE|nomic-embed|COGNITIVE' \
      "$LATEST_LOG" || true
  else
    echo "No ops/reports/*.log found."
  fi
} >> "$OUT/12_recent_live_report_builder_log_extract.txt"

echo "=== 13. RUNTIME SNAPSHOT FILES ===" > "$OUT/13_runtime_snapshot_files.txt"
{
  find . -path '*/runtime_snapshot.json' -type f -printf '%p\n' 2>/dev/null | sort || true
  echo
  for f in artifacts/runtime_snapshot.json "$HOME/.local/share/eli/runtime_snapshot.json"; do
    if [[ -f "$f" ]]; then
      echo "--- $f ---"
      sed -n '1,220p' "$f"
      echo
    fi
  done
} >> "$OUT/13_runtime_snapshot_files.txt"

echo "=== 14. GGUF RUNTIME TRUTH SURFACES ===" > "$OUT/14_gguf_runtime_truth_hits.txt"
rg -n \
  'requested/effective|EFFECTIVE|ADAPTIVE|runtime snapshot|preloaded runtime override|_llm wired|singleton wired|effective ctx|requested ctx|selected ctx|model loaded successfully|Hardware profile re-applied|settings exceed profiler-recommended bounds' \
  eli/cognition/gguf_inference.py \
  eli/gui/app.py \
  eli/kernel/engine.py \
  2>&1 >> "$OUT/14_gguf_runtime_truth_hits.txt" || true

echo "=== 15. NOMIC / EMBEDDER EXACT USAGE ===" > "$OUT/15_nomic_embedder_usage.txt"
rg -n \
  'nomic|embedder|embedding=True|create_embedding|ELI_EMBED_MODEL_PATH|vector_store|FAISS|hyde|HyDE|semantic search|pre-warm|_get_embedder|rebuild.*faiss|rebuild.*vector' \
  eli \
  scripts \
  requirements \
  2>&1 >> "$OUT/15_nomic_embedder_usage.txt" || true

echo "=== 16. VECTOR STORE TARGETED CODE WINDOW ===" > "$OUT/16_vector_store_code_window.txt"
python3 - <<'PY' >> "$OUT/16_vector_store_code_window.txt"
import ast
from pathlib import Path

p = Path("eli/memory/vector_store.py")
lines = p.read_text(encoding="utf-8").splitlines()
tree = ast.parse("\n".join(lines))

targets = [
    "__init__",
    "_init_embedder",
    "_embed",
    "add",
    "search",
    "_load_or_create",
    "flush",
    "rebuild",
]

for node in ast.walk(tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in targets:
        print("=" * 110)
        print(f"{node.name}  lines {node.lineno}-{getattr(node, 'end_lineno', node.lineno)}")
        print("=" * 110)
        start = max(1, node.lineno - 4)
        end = min(len(lines), getattr(node, "end_lineno", node.lineno) + 4)
        for i in range(start, end + 1):
            print(f"{i:>6}: {lines[i-1]}")
PY

echo "=== 17. SELF-IMPROVEMENT / FAILURE TELEMETRY HITS ===" > "$OUT/17_self_improvement_failure_hits.txt"
rg -n \
  'FAIL-CLOSED|failures recorded|failure|record_failure|append_failure|self.?improvement|improvement.*failure|failure_events|failure_log|insert.*failure|report_builder' \
  eli/gui/labs_tab.py \
  eli/gui/eli_pro_audio_gui_MKI.py \
  eli/kernel \
  eli/memory \
  eli/runtime \
  eli/execution \
  2>&1 >> "$OUT/17_self_improvement_failure_hits.txt" || true

echo "=== 18. MEMORY STORAGE / KNOWN-BAD ASSISTANT TURN SURFACES ===" > "$OUT/18_memory_storage_trace_hits.txt"
rg -n \
  'conversation_turns|store.*assistant|save.*assistant|assistant.*memory|recall_log|session narrative stored|store_turn|record_turn|append.*turn|chat_history|memory.*assistant' \
  eli/memory \
  eli/kernel \
  eli/gui/eli_pro_audio_gui_MKI.py \
  2>&1 >> "$OUT/18_memory_storage_trace_hits.txt" || true

echo "=== 19. PORTABILITY — MACHINE-SPECIFIC PATH HITS IN LIVE SOURCE ONLY ===" > "$OUT/19_machine_specific_path_hits_live_source.txt"
rg -n \
  '/home/jay|~/Desktop/ELI_MKXI|ELI_MKXI-main_MAY_NEWEST|/Users/jay|C:\\\\Users\\\\jay' \
  eli scripts packaging requirements README.md pyproject.toml \
  --glob '!ops/**' \
  --glob '!archive/**' \
  --glob '!experimental/**/*backup*' \
  2>&1 >> "$OUT/19_machine_specific_path_hits_live_source.txt" || true

echo "=== 20. PORTABILITY — ABSOLUTE PATH CLASSIFICATION HITS ===" > "$OUT/20_absolute_path_review_hits_live_source.txt"
rg -n \
  '"/tmp/|'\''/tmp/|"/usr/|'\''/usr/|"/var/|'\''/var/|"/home/|'\''/home/|Path\("~/|Path\("/' \
  eli scripts packaging requirements README.md pyproject.toml \
  --glob '!ops/**' \
  --glob '!archive/**' \
  --glob '!experimental/**/*backup*' \
  2>&1 >> "$OUT/20_absolute_path_review_hits_live_source.txt" || true

echo "=== 21. GENERATED SCRIPT GUARD TARGETED WINDOW ===" > "$OUT/21_generated_script_guard_window.txt"
nl -ba eli/runtime/generated_script_guard.py \
  | sed -n '760,835p' \
  >> "$OUT/21_generated_script_guard_window.txt" 2>&1 || true

echo "=== 22. README / REQUIREMENTS / LAUNCH CONTRACT HITS ===" > "$OUT/22_readme_requirements_launch_hits.txt"
rg -n \
  'python -m eli|run_eli_repo_venv|--setup|requirements-full|requirements-windows|requirements-macos|requirements-android|venv|pip install|PyVista|pyvista|optional|full install|launch|ELI_PROJECT_ROOT|phase[0-9]+' \
  README.md \
  requirements/README_ELI_ENVIRONMENT.md \
  pyproject.toml \
  eli/__main__.py \
  scripts/run_eli_repo_venv.sh \
  2>&1 >> "$OUT/22_readme_requirements_launch_hits.txt" || true

echo "=== 23. MANIFEST / REQUIREMENTS INVENTORY ===" > "$OUT/23_manifest_inventory.txt"
find . \
  \( -name 'README.md' -o -name 'requirements*.txt' -o -name 'pyproject.toml' \) \
  -not -path './.venv/*' \
  -not -path './ops/reports/*' \
  -printf '%p\n' | sort \
  >> "$OUT/23_manifest_inventory.txt"

echo "=== 24. EXPERIMENTAL BACKUP TREE INVENTORY ===" > "$OUT/24_experimental_backup_inventory.txt"
find experimental -maxdepth 2 \
  \( -iname '*backup*' -o -iname '*broken*' -o -iname '*polluted*' \) \
  -printf '%p\n' 2>/dev/null | sort \
  >> "$OUT/24_experimental_backup_inventory.txt" || true

echo "=== 25. SOURCE-LINE COUNT SNAPSHOT ===" > "$OUT/25_source_line_count_snapshot.txt"
wc -l \
  eli/gui/labs_tab.py \
  eli/gui/app.py \
  eli/core/hardware_profile.py \
  eli/cognition/gguf_inference.py \
  eli/kernel/engine.py \
  eli/memory/vector_store.py \
  eli/execution/executor_enhanced.py \
  eli/runtime/generated_script_guard.py \
  eli/gui/eli_pro_audio_gui_MKI.py \
  >> "$OUT/25_source_line_count_snapshot.txt" 2>&1 || true

echo "=== 26. HIGH-RISK CODE DUPLICATION / LATE PATCH STACK HITS ===" > "$OUT/26_high_risk_patch_stack_hits.txt"
rg -n \
  'Phase [0-9]+|PHASE[0-9]+|installed|wrapper installed|contract installed|guard installed|compatibility installed|final .* installed|_v[0-9]+|phase[0-9]+' \
  eli \
  --glob '!**/__pycache__/**' \
  2>&1 >> "$OUT/26_high_risk_patch_stack_hits.txt" || true

echo "=== 27. REPORT BUILDER FILE OUTPUT / AUTOSAVE / EXPORT HITS ===" > "$OUT/27_report_builder_output_export_hits.txt"
rg -n \
  '_reports_output_dir|_autosave_report|write_text|out_pdf|out_docx|PDF saved|DOCX saved|pandoc|xelatex|lualatex|latex|export|reports_output' \
  eli/gui/labs_tab.py \
  2>&1 >> "$OUT/27_report_builder_output_export_hits.txt" || true

echo "=== 28. DOCUMENT GENERATOR QUALITY / EVIDENCE CONTRACT HITS ===" > "$OUT/28_document_quality_evidence_contract_hits.txt"
rg -n \
  'Evidence Ledger|Source Coverage Matrix|source needed|assumption|Do not invent citations|citation policy|evidence discipline|peer-review critique|REVISION RULES|FINAL ACCEPTANCE TEST|publication-ready|examiner-ready|grounded|strict' \
  eli/gui/labs_tab.py \
  eli/runtime \
  eli/cognition \
  2>&1 >> "$OUT/28_document_quality_evidence_contract_hits.txt" || true

echo "=== 29. QUICK SUMMARY COUNTS ===" > "$OUT/29_quick_summary_counts.txt"
{
  echo -n "Machine-specific live-source path hits: "
  wc -l < "$OUT/19_machine_specific_path_hits_live_source.txt" || true

  echo -n "Absolute path review hits: "
  wc -l < "$OUT/20_absolute_path_review_hits_live_source.txt" || true

  echo -n "Report-builder guard-search hits: "
  wc -l < "$OUT/11_report_builder_guard_search.txt" || true

  echo -n "Self-improvement/failure hits: "
  wc -l < "$OUT/17_self_improvement_failure_hits.txt" || true

  echo -n "Nomic/embedder usage hits: "
  wc -l < "$OUT/15_nomic_embedder_usage.txt" || true

  echo -n "Patch-stack terminology hits: "
  wc -l < "$OUT/26_high_risk_patch_stack_hits.txt" || true
} >> "$OUT/29_quick_summary_counts.txt"

{
  echo
  echo "## Files produced"
  find "$OUT" -maxdepth 1 -type f -printf '- `%f`\n' | sort
  echo
  echo "## Next-step interpretation target"
  echo "This report is designed to support one consolidated repair pass, not another piecemeal hotfix."
  echo
  echo "PHASE29_OUT=$OUT"
} | tee -a "$OUT/SUMMARY.md"

echo
echo "PHASE29_OUT=$OUT"
