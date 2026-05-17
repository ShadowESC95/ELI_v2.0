#!/usr/bin/env bash
set -Eeuo pipefail

cd ~/Desktop/ELI_MKXI || exit 1

STAMP="$(date +%Y%m%d_%H%M%S)"
ENGINE="eli/kernel/engine.py"
BACKUP="ops/backups/engine.py.before_runtime_status_quick_paths_v14_${STAMP}"
REPORT="ops/reports/runtime_status_quick_paths_v14_${STAMP}.log"

cp -a "$ENGINE" "$BACKUP"

python3 - <<'PY'
from pathlib import Path

p = Path("eli/kernel/engine.py")
src = p.read_text(encoding="utf-8")

marker = "# ELI_RUNTIME_STATUS_QUICK_PATHS_V14"
if marker in src:
    print("runtime-status quick paths v14 already installed")
    raise SystemExit(0)

patch = r'''

# ELI_RUNTIME_STATUS_QUICK_PATHS_V14
# Purpose:
# - Keep Quick mode direct/evidence-based.
# - Prevent blank project/runtime path fields in RUNTIME_STATUS visible output.
# - Rebuild Quick RUNTIME_STATUS content from live runtime snapshot + project-root-derived paths.
try:
    _ELI_RUNTIME_STATUS_QUICK_PATHS_V14_PREV_PROCESS = CognitiveEngine.process

    def _eli_runtime_status_v14_project_root():
        from pathlib import Path
        try:
            return Path(__file__).resolve().parents[2]
        except Exception:
            return Path.cwd().resolve()

    def _eli_runtime_status_v14_load_runtime_snapshot():
        import json
        root = _eli_runtime_status_v14_project_root()
        snap_path = root / "artifacts" / "runtime_snapshot.json"
        if not snap_path.exists():
            return {}
        try:
            data = json.loads(snap_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _eli_runtime_status_v14_first(*values, default="unknown"):
        for value in values:
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            return value
        return default

    def _eli_runtime_status_v14_nested_get(obj, path, default=None):
        cur = obj
        for key in path:
            if not isinstance(cur, dict):
                return default
            cur = cur.get(key)
        return cur if cur is not None else default

    def _eli_runtime_status_v14_mode_from_call(args, kwargs):
        mode = kwargs.get("reasoning_mode")
        if mode:
            return str(mode)
        if len(args) >= 2:
            return str(args[1])
        return "quick"

    def _eli_runtime_status_v14_build_content(result, requested_mode):
        from pathlib import Path

        root = _eli_runtime_status_v14_project_root()
        snap = _eli_runtime_status_v14_load_runtime_snapshot()

        # runtime_snapshot may either be the runtime dict directly or contain a nested runtime dict.
        runtime = snap.get("runtime") if isinstance(snap.get("runtime"), dict) else snap
        report = result.get("report") if isinstance(result, dict) and isinstance(result.get("report"), dict) else {}
        settings = report.get("settings") if isinstance(report.get("settings"), dict) else {}

        paths = report.get("paths") if isinstance(report.get("paths"), dict) else {}
        adaptive = runtime.get("adaptive_load_report") if isinstance(runtime.get("adaptive_load_report"), dict) else {}
        gpu_probe = adaptive.get("gpu_probe") if isinstance(adaptive.get("gpu_probe"), dict) else {}

        provider = _eli_runtime_status_v14_first(
            runtime.get("provider"),
            settings.get("provider"),
            "gguf",
        )

        model_path = _eli_runtime_status_v14_first(
            runtime.get("model_path"),
            report.get("model_path"),
            settings.get("model_path"),
            settings.get("gguf_model_path"),
        )

        model_name = _eli_runtime_status_v14_first(
            runtime.get("model_name"),
            Path(str(model_path)).name if model_path != "unknown" else None,
        )

        context_size = _eli_runtime_status_v14_first(
            runtime.get("n_ctx"),
            runtime.get("context_size"),
            settings.get("n_ctx"),
        )

        gpu_layers = _eli_runtime_status_v14_first(
            runtime.get("n_gpu_layers"),
            runtime.get("gpu_layers"),
            settings.get("n_gpu_layers"),
            settings.get("gpu_layers"),
        )

        batch_size = _eli_runtime_status_v14_first(
            runtime.get("n_batch"),
            runtime.get("batch_size"),
            settings.get("batch_size"),
        )

        cpu_threads = _eli_runtime_status_v14_first(
            runtime.get("n_threads"),
            settings.get("n_threads"),
        )

        loaded = _eli_runtime_status_v14_first(
            runtime.get("loaded"),
            result.get("gguf_loaded") if isinstance(result, dict) else None,
            default="unknown",
        )

        pid = _eli_runtime_status_v14_first(
            runtime.get("pid"),
            default="unknown",
        )

        gpu_name = _eli_runtime_status_v14_first(
            gpu_probe.get("name"),
            default="unknown",
        )

        gpu_total = _eli_runtime_status_v14_first(
            gpu_probe.get("total_mib"),
            default="unknown",
        )

        gpu_free = _eli_runtime_status_v14_first(
            gpu_probe.get("free_mib"),
            default="unknown",
        )

        project_root = _eli_runtime_status_v14_first(
            paths.get("project_root"),
            str(root),
        )

        user_db = _eli_runtime_status_v14_first(
            paths.get("user_db"),
            str(root / "artifacts" / "db" / "user.sqlite3"),
        )

        agent_db = _eli_runtime_status_v14_first(
            paths.get("agent_db"),
            str(root / "artifacts" / "db" / "agent.sqlite3"),
        )

        max_tokens = _eli_runtime_status_v14_first(
            settings.get("max_tokens"),
            runtime.get("max_tokens"),
        )

        temperature = _eli_runtime_status_v14_first(
            settings.get("temperature"),
            runtime.get("temperature"),
        )

        use_mmap = _eli_runtime_status_v14_first(
            settings.get("use_mmap"),
            runtime.get("use_mmap"),
        )

        use_mlock = _eli_runtime_status_v14_first(
            settings.get("use_mlock"),
            runtime.get("use_mlock"),
        )

        return (
            "Runtime status evidence:\n\n"
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
            "- response_surface: direct structured runtime evidence\n"
            "- Quick mode did not use non-Quick synthesis."
        )

    def _eli_runtime_status_quick_paths_v14_process(self, *args, **kwargs):
        result = _ELI_RUNTIME_STATUS_QUICK_PATHS_V14_PREV_PROCESS(self, *args, **kwargs)

        if not isinstance(result, dict):
            return result

        action = result.get("action")
        if action != "RUNTIME_STATUS":
            return result

        mode = _eli_runtime_status_v14_mode_from_call(args, kwargs)
        content = str(result.get("content") or result.get("response") or "")

        needs_rebuild = (
            mode == "quick"
            and (
                "- project_root: \n" in content
                or "- user_db: \n" in content
                or "- agent_db: \n" in content
                or "- max_tokens: \n" in content
                or "- temperature: \n" in content
                or "- use_mmap: \n" in content
                or "- use_mlock: \n" in content
            )
        )

        if needs_rebuild:
            rebuilt = _eli_runtime_status_v14_build_content(result, mode)
            result["content"] = rebuilt
            result["response"] = rebuilt
            result["evidence_source"] = "runtime_status_quick_structured_paths_v14"
            result["source"] = "runtime_status_quick_structured_paths_v14"
            result["synthesis_validated"] = None
            result["repair_reason"] = "quick_blank_runtime_fields_rebuilt_from_live_snapshot_v14"

        return result

    CognitiveEngine.process = _eli_runtime_status_quick_paths_v14_process
    print("[ENGINE] runtime-status quick paths v14 installed", flush=True)

except Exception as _eli_runtime_status_quick_paths_v14_err:
    print(
        f"[ENGINE] runtime-status quick paths v14 failed: {_eli_runtime_status_quick_paths_v14_err!r}",
        flush=True,
    )
'''

p.write_text(src.rstrip() + "\n" + patch + "\n", encoding="utf-8")
print("installed runtime-status quick paths v14")
PY

python3 -m py_compile "$ENGINE"

{
  echo "=== PATCHED ==="
  date -Is
  echo "backup=$BACKUP"
  echo
  echo "=== MARKERS ==="
  grep -n "runtime-status quick paths v14\|ELI_RUNTIME_STATUS_QUICK_PATHS_V14" "$ENGINE" || true
  echo
  echo "=== GIT DIFF STAT ==="
  git diff --stat -- "$ENGINE" "ops/patches/runtime_status_quick_paths_v14.sh" || true
} | tee "$REPORT"

echo
echo "Report: $REPORT"
echo "Backup: $BACKUP"
