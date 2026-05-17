#!/usr/bin/env bash
set -Eeuo pipefail

cd ~/Desktop/ELI_MKXI || exit 1

STAMP="$(date +%Y%m%d_%H%M%S)"
ENGINE="eli/kernel/engine.py"
BACKUP="ops/backups/engine.py.before_runtime_status_all_modes_fill_blanks_v15_${STAMP}"
REPORT="ops/reports/runtime_status_all_modes_fill_blanks_v15_${STAMP}.log"

cp -a "$ENGINE" "$BACKUP"

python3 - <<'PY'
from pathlib import Path

p = Path("eli/kernel/engine.py")
src = p.read_text(encoding="utf-8")

marker = "# ELI_RUNTIME_STATUS_ALL_MODES_FILL_BLANKS_V15"
if marker in src:
    print("runtime-status all-modes fill blanks v15 already installed")
    raise SystemExit(0)

patch = r'''

# ELI_RUNTIME_STATUS_ALL_MODES_FILL_BLANKS_V15
# Purpose:
# - Fix the remaining V12/V14 visible-output defect.
# - If any RUNTIME_STATUS content contains blank runtime/path/settings fields,
#   rebuild the visible content from live runtime_snapshot + config/settings + project paths.
# - Quick remains direct evidence.
# - Non-Quick still attempts synthesis first; this only repairs failed/blank repair output.
try:
    _ELI_RUNTIME_STATUS_ALL_MODES_FILL_BLANKS_V15_PREV_PROCESS = CognitiveEngine.process

    def _eli_rs_v15_project_root():
        from pathlib import Path
        try:
            return Path(__file__).resolve().parents[2]
        except Exception:
            return Path.cwd().resolve()

    def _eli_rs_v15_load_json(path):
        import json
        try:
            p = path
            if not p.exists():
                return {}
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _eli_rs_v15_first(*values, default="unknown"):
        for value in values:
            if value is None:
                continue
            if isinstance(value, str) and value.strip() == "":
                continue
            return value
        return default

    def _eli_rs_v15_boolish(value):
        if value is True:
            return "True"
        if value is False:
            return "False"
        return value

    def _eli_rs_v15_mode_from_call(args, kwargs):
        mode = kwargs.get("reasoning_mode")
        if mode:
            return str(mode)
        if len(args) >= 2:
            return str(args[1])
        return "quick"

    def _eli_rs_v15_has_blank_runtime_lines(text):
        blank_lines = {
            "- project_root:",
            "- user_db:",
            "- agent_db:",
            "- max_tokens:",
            "- temperature:",
            "- use_mmap:",
            "- use_mlock:",
        }
        for line in str(text or "").splitlines():
            if line.strip() in blank_lines:
                return True
        return False

    def _eli_rs_v15_build_content(result, requested_mode):
        from pathlib import Path

        root = _eli_rs_v15_project_root()
        snap = _eli_rs_v15_load_json(root / "artifacts" / "runtime_snapshot.json")
        config = _eli_rs_v15_load_json(root / "config" / "settings.json")

        report = result.get("report") if isinstance(result, dict) and isinstance(result.get("report"), dict) else {}
        report_paths = report.get("paths") if isinstance(report.get("paths"), dict) else {}
        report_settings = report.get("settings") if isinstance(report.get("settings"), dict) else {}

        runtime = snap.get("runtime") if isinstance(snap.get("runtime"), dict) else snap
        runtime = runtime if isinstance(runtime, dict) else {}

        settings = {}
        settings.update(config if isinstance(config, dict) else {})
        settings.update(report_settings if isinstance(report_settings, dict) else {})

        adaptive = runtime.get("adaptive_load_report") if isinstance(runtime.get("adaptive_load_report"), dict) else {}
        gpu_probe = adaptive.get("gpu_probe") if isinstance(adaptive.get("gpu_probe"), dict) else {}

        provider = _eli_rs_v15_first(
            runtime.get("provider"),
            settings.get("provider"),
            "gguf",
        )

        model_path = _eli_rs_v15_first(
            runtime.get("model_path"),
            report.get("model_path"),
            settings.get("model_path"),
            settings.get("gguf_model_path"),
        )

        model_name = _eli_rs_v15_first(
            runtime.get("model_name"),
            Path(str(model_path)).name if model_path != "unknown" else None,
        )

        context_size = _eli_rs_v15_first(
            runtime.get("n_ctx"),
            runtime.get("context_size"),
            settings.get("n_ctx"),
        )

        gpu_layers = _eli_rs_v15_first(
            runtime.get("n_gpu_layers"),
            runtime.get("gpu_layers"),
            settings.get("n_gpu_layers"),
            settings.get("gpu_layers"),
        )

        batch_size = _eli_rs_v15_first(
            runtime.get("n_batch"),
            runtime.get("batch_size"),
            settings.get("batch_size"),
        )

        cpu_threads = _eli_rs_v15_first(
            runtime.get("n_threads"),
            settings.get("n_threads"),
        )

        loaded = _eli_rs_v15_first(
            runtime.get("loaded"),
            result.get("gguf_loaded") if isinstance(result, dict) else None,
            default="unknown",
        )

        pid = _eli_rs_v15_first(
            runtime.get("pid"),
            default="unknown",
        )

        gpu_name = _eli_rs_v15_first(
            gpu_probe.get("name"),
            default="unknown",
        )

        gpu_total = _eli_rs_v15_first(
            gpu_probe.get("total_mib"),
            default="unknown",
        )

        gpu_free = _eli_rs_v15_first(
            gpu_probe.get("free_mib"),
            default="unknown",
        )

        project_root = _eli_rs_v15_first(
            report_paths.get("project_root"),
            str(root),
        )

        user_db = _eli_rs_v15_first(
            report_paths.get("user_db"),
            str(root / "artifacts" / "db" / "user.sqlite3"),
        )

        agent_db = _eli_rs_v15_first(
            report_paths.get("agent_db"),
            str(root / "artifacts" / "db" / "agent.sqlite3"),
        )

        max_tokens = _eli_rs_v15_first(
            settings.get("max_tokens"),
            runtime.get("max_tokens"),
        )

        temperature = _eli_rs_v15_first(
            settings.get("temperature"),
            runtime.get("temperature"),
        )

        use_mmap = _eli_rs_v15_boolish(_eli_rs_v15_first(
            settings.get("use_mmap"),
            runtime.get("use_mmap"),
        ))

        use_mlock = _eli_rs_v15_boolish(_eli_rs_v15_first(
            settings.get("use_mlock"),
            runtime.get("use_mlock"),
        ))

        if requested_mode == "quick":
            response_surface = "direct structured runtime evidence"
            repair_line = "- Quick mode did not use non-Quick synthesis."
            header = "Runtime status evidence:"
        else:
            response_surface = "non-Quick synthesis attempted first; blank repair fields completed from live evidence"
            repair_line = "- Non-Quick mode attempted normal synthesis first; this visible repair only filled missing grounded fields."
            header = "Runtime status, completed from live grounded evidence after synthesis/repair validation."

        return (
            f"{header}\n\n"
            "Identity:\n"
            "- name: ELI / Entropy Logical Interface\n"
            "- role: local GGUF-backed assistant running inside this ELI MKXI project\n\n"
            "Effective runtime:\n"
            f"- provider: {provider}\n"
            f"- model_name: {model_name}\n"
            f"- model_path: {model_path}\n"
            f"- context_size: {context_size}\n"
            f"- gpu_layers: {gpu_layers}\n"
            f"- batch_size: {batch_size}\n"
            f"- cpu_threads: {cpu_threads}\n"
            f"- loaded_in_this_process: {loaded}\n"
            f"- pid: {pid}\n\n"
            "GPU:\n"
            f"- name: {gpu_name}\n"
            f"- total_mib: {gpu_total}\n"
            f"- free_mib: {gpu_free}\n\n"
            "Project/runtime paths:\n"
            f"- project_root: {project_root}\n"
            f"- user_db: {user_db}\n"
            f"- agent_db: {agent_db}\n\n"
            "Generation settings:\n"
            f"- max_tokens: {max_tokens}\n"
            f"- temperature: {temperature}\n"
            f"- use_mmap: {use_mmap}\n"
            f"- use_mlock: {use_mlock}\n\n"
            "Validation note:\n"
            f"- requested_mode: {requested_mode}\n"
            f"- response_surface: {response_surface}\n"
            f"{repair_line}"
        )

    def _eli_runtime_status_all_modes_fill_blanks_v15_process(self, *args, **kwargs):
        result = _ELI_RUNTIME_STATUS_ALL_MODES_FILL_BLANKS_V15_PREV_PROCESS(self, *args, **kwargs)

        if not isinstance(result, dict):
            return result

        if result.get("action") != "RUNTIME_STATUS":
            return result

        content = str(result.get("content") or result.get("response") or "")
        if not _eli_rs_v15_has_blank_runtime_lines(content):
            return result

        mode = _eli_rs_v15_mode_from_call(args, kwargs)
        rebuilt = _eli_rs_v15_build_content(result, mode)

        result["content"] = rebuilt
        result["response"] = rebuilt

        if mode == "quick":
            source = "runtime_status_quick_completed_from_live_snapshot_v15"
            result["synthesis_validated"] = None
        else:
            source = "runtime_status_nonquick_completed_from_live_snapshot_v15"
            result["synthesis_validated"] = False

        result["evidence_source"] = source
        result["source"] = source
        result["repair_reason"] = "blank_runtime_fields_completed_from_live_snapshot_v15"

        return result

    CognitiveEngine.process = _eli_runtime_status_all_modes_fill_blanks_v15_process
    print("[ENGINE] runtime-status all-modes fill blanks v15 installed", flush=True)

except Exception as _eli_runtime_status_all_modes_fill_blanks_v15_err:
    print(
        f"[ENGINE] runtime-status all-modes fill blanks v15 failed: {_eli_runtime_status_all_modes_fill_blanks_v15_err!r}",
        flush=True,
    )
'''

p.write_text(src.rstrip() + "\n" + patch + "\n", encoding="utf-8")
print("installed runtime-status all-modes fill blanks v15")
PY

python3 -m py_compile "$ENGINE"

{
  echo "=== PATCHED ==="
  date -Is
  echo "backup=$BACKUP"
  echo
  echo "=== MARKERS ==="
  grep -n "runtime-status all-modes fill blanks v15\|ELI_RUNTIME_STATUS_ALL_MODES_FILL_BLANKS_V15" "$ENGINE" || true
  echo
  echo "=== GIT DIFF STAT ==="
  git diff --stat -- "$ENGINE" "ops/patches/runtime_status_all_modes_fill_blanks_v15.sh" || true
} | tee "$REPORT"

echo
echo "Report: $REPORT"
echo "Backup: $BACKUP"
