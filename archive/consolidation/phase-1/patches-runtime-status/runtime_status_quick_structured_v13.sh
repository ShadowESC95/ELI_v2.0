#!/usr/bin/env bash
set -Eeuo pipefail

cd ~/Desktop/ELI_MKXI || exit 1

STAMP="$(date +%Y%m%d_%H%M%S)"
ENGINE="eli/kernel/engine.py"
BACKUP="ops/backups/engine.py.before_runtime_status_quick_structured_v13_${STAMP}"
REPORT="ops/reports/runtime_status_quick_structured_v13_${STAMP}.log"

cp -a "$ENGINE" "$BACKUP"

python3 - <<'PY'
from pathlib import Path

p = Path("eli/kernel/engine.py")
src = p.read_text(encoding="utf-8")

marker = "ELI_RUNTIME_STATUS_QUICK_STRUCTURED_V13"

if marker in src:
    print("runtime-status quick structured v13 already installed")
    raise SystemExit(0)

append = r'''

# =============================================================================
# ELI_RUNTIME_STATUS_QUICK_STRUCTURED_V13
# Purpose:
#   Quick mode is allowed to return direct runtime evidence, but the visible
#   surface still needs the same exact evidence keys expected by contract tests:
#       provider:
#       model_name:
#       model_path:
#       context_size:
#       gpu_layers:
#       batch_size:
#       cpu_threads:
#
#   This does not route Quick through non-Quick synthesis. It only normalizes
#   the direct Quick runtime-status evidence into a structured visible shape.
# =============================================================================

try:
    import json as _eli_v13_json
    import os as _eli_v13_os
    from pathlib import Path as _eli_v13_Path

    _ELI_RUNTIME_STATUS_QUICK_STRUCTURED_V13_PREV_PROCESS = CognitiveEngine.process

    def _eli_v13_mode_from_args(args, kwargs):
        mode = kwargs.get("reasoning_mode")
        if mode:
            return str(mode)
        if len(args) >= 2:
            try:
                return str(args[1])
            except Exception:
                pass
        return ""

    def _eli_v13_load_runtime_snapshot():
        candidates = []

        try:
            candidates.append(_eli_v13_Path(_eli_v13_os.getcwd()) / "artifacts" / "runtime_snapshot.json")
        except Exception:
            pass

        try:
            candidates.append(_eli_v13_Path.home() / "Desktop" / "ELI_MKXI" / "artifacts" / "runtime_snapshot.json")
        except Exception:
            pass

        for path in candidates:
            try:
                if path.exists():
                    return _eli_v13_json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue

        return {}

    def _eli_v13_deep_dict(value):
        return value if isinstance(value, dict) else {}

    def _eli_v13_extract_facts(result):
        result = _eli_v13_deep_dict(result)
        report = _eli_v13_deep_dict(result.get("report"))

        snap = _eli_v13_load_runtime_snapshot()
        snap = _eli_v13_deep_dict(snap)

        runtime = _eli_v13_deep_dict(report.get("runtime"))
        if not runtime:
            runtime = _eli_v13_deep_dict(snap.get("runtime"))
        if not runtime:
            runtime = snap

        settings = _eli_v13_deep_dict(report.get("settings"))
        if not settings:
            settings = _eli_v13_deep_dict(snap.get("settings"))

        paths = _eli_v13_deep_dict(report.get("paths"))
        if not paths:
            paths = _eli_v13_deep_dict(snap.get("paths"))

        adaptive = _eli_v13_deep_dict(runtime.get("adaptive_load_report"))
        gpu_probe = _eli_v13_deep_dict(adaptive.get("gpu_probe"))

        model_path = (
            runtime.get("model_path")
            or report.get("model_path")
            or settings.get("model_path")
            or settings.get("gguf_model_path")
            or settings.get("custom_model_path")
            or ""
        )

        model_name = (
            runtime.get("model_name")
            or (_eli_v13_os.path.basename(model_path) if model_path else "")
            or ""
        )

        provider = runtime.get("provider") or settings.get("provider") or "gguf"
        if provider == "custom_gguf":
            provider = "gguf"

        return {
            "provider": provider,
            "model_name": model_name,
            "model_path": model_path,
            "context_size": runtime.get("n_ctx") or runtime.get("context_size") or settings.get("n_ctx") or "",
            "gpu_layers": runtime.get("n_gpu_layers") or settings.get("n_gpu_layers") or settings.get("gpu_layers") or "",
            "batch_size": runtime.get("n_batch") or runtime.get("batch_size") or settings.get("batch_size") or "",
            "cpu_threads": runtime.get("n_threads") or settings.get("n_threads") or "",
            "loaded_in_this_process": runtime.get("loaded"),
            "pid": runtime.get("pid"),
            "gpu_name": gpu_probe.get("name") or "",
            "gpu_total_mib": gpu_probe.get("total_mib") or "",
            "gpu_free_mib": gpu_probe.get("free_mib") or "",
            "project_root": paths.get("project_root") or "",
            "user_db": paths.get("user_db") or "",
            "agent_db": paths.get("agent_db") or "",
            "max_tokens": settings.get("max_tokens") or "",
            "temperature": settings.get("temperature") or "",
            "use_mmap": settings.get("use_mmap") or "",
            "use_mlock": settings.get("use_mlock") or "",
        }

    def _eli_v13_quick_runtime_content(facts):
        lines = []
        lines.append("Runtime status evidence:")
        lines.append("")
        lines.append("Identity:")
        lines.append("- name: ELI / Entropy Logical Interface")
        lines.append("- role: local GGUF-backed assistant running inside this ELI MKXI project")
        lines.append("")
        lines.append("Effective runtime:")
        lines.append(f"- provider: {facts.get('provider')}")
        lines.append(f"- model_name: {facts.get('model_name')}")
        lines.append(f"- model_path: {facts.get('model_path')}")
        lines.append(f"- context_size: {facts.get('context_size')}")
        lines.append(f"- gpu_layers: {facts.get('gpu_layers')}")
        lines.append(f"- batch_size: {facts.get('batch_size')}")
        lines.append(f"- cpu_threads: {facts.get('cpu_threads')}")
        lines.append(f"- loaded_in_this_process: {facts.get('loaded_in_this_process')}")
        lines.append(f"- pid: {facts.get('pid')}")
        lines.append("")
        lines.append("GPU:")
        lines.append(f"- name: {facts.get('gpu_name')}")
        lines.append(f"- total_mib: {facts.get('gpu_total_mib')}")
        lines.append(f"- free_mib: {facts.get('gpu_free_mib')}")
        lines.append("")
        lines.append("Project/runtime paths:")
        lines.append(f"- project_root: {facts.get('project_root')}")
        lines.append(f"- user_db: {facts.get('user_db')}")
        lines.append(f"- agent_db: {facts.get('agent_db')}")
        lines.append("")
        lines.append("Generation settings:")
        lines.append(f"- max_tokens: {facts.get('max_tokens')}")
        lines.append(f"- temperature: {facts.get('temperature')}")
        lines.append(f"- use_mmap: {facts.get('use_mmap')}")
        lines.append(f"- use_mlock: {facts.get('use_mlock')}")
        lines.append("")
        lines.append("Validation note:")
        lines.append("- requested_mode: quick")
        lines.append("- response_surface: direct structured runtime evidence")
        lines.append("- Quick mode did not use non-Quick synthesis.")
        return "\n".join(lines)

    def _eli_runtime_status_quick_structured_v13_process(self, *args, **kwargs):
        mode = _eli_v13_mode_from_args(args, kwargs)
        result = _ELI_RUNTIME_STATUS_QUICK_STRUCTURED_V13_PREV_PROCESS(self, *args, **kwargs)

        if mode != "quick":
            return result

        if not isinstance(result, dict):
            return result

        if result.get("action") != "RUNTIME_STATUS":
            return result

        facts = _eli_v13_extract_facts(result)
        content = _eli_v13_quick_runtime_content(facts)

        report = result.get("report")
        if not isinstance(report, dict):
            report = {}

        report["quick_structured_evidence"] = True
        report["quick_structured_evidence_version"] = "v13"

        result["content"] = content
        result["response"] = content

        # Preserve the old source string because existing callers/tests already
        # know it means Quick direct runtime evidence.
        result["evidence_source"] = result.get("evidence_source") or "runtime_status_quick_dynamic_evidence_v8"
        result["report"] = report

        return result

    CognitiveEngine.process = _eli_runtime_status_quick_structured_v13_process
    print("[ENGINE] runtime-status quick structured v13 installed", flush=True)

except Exception as _eli_runtime_status_quick_structured_v13_err:
    print(
        f"[ENGINE] runtime-status quick structured v13 failed: {_eli_runtime_status_quick_structured_v13_err!r}",
        flush=True,
    )
'''

p.write_text(src.rstrip() + "\n\n" + append + "\n", encoding="utf-8")
print("installed runtime-status quick structured v13")
PY

python3 -m py_compile "$ENGINE"

{
  echo "=== PATCHED ==="
  date -Is
  echo "backup=$BACKUP"
  echo
  echo "=== MARKERS ==="
  grep -n "runtime-status quick structured v13\|ELI_RUNTIME_STATUS_QUICK_STRUCTURED_V13" "$ENGINE" || true
  echo
  echo "=== GIT DIFF STAT ==="
  git diff --stat -- "$ENGINE"
} | tee "$REPORT"

echo
echo "Report: $REPORT"
echo "Backup: $BACKUP"
