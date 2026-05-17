#!/usr/bin/env bash
set -Eeuo pipefail

cd ~/Desktop/ELI_MKXI || exit 1

STAMP="$(date +%Y%m%d_%H%M%S)"
ENGINE="eli/kernel/engine.py"
BACKUP="ops/backups/engine.py.before_runtime_status_semantic_validator_v12_${STAMP}"
REPORT="ops/reports/runtime_status_semantic_validator_v12_${STAMP}.log"

cp -a "$ENGINE" "$BACKUP"

python3 - <<'PY'
from pathlib import Path

p = Path("eli/kernel/engine.py")
src = p.read_text(encoding="utf-8")

marker = "ELI_RUNTIME_STATUS_SEMANTIC_VALIDATOR_V12"

if marker in src:
    print("runtime-status semantic validator v12 already installed")
    raise SystemExit(0)

append = r'''

# =============================================================================
# ELI_RUNTIME_STATUS_SEMANTIC_VALIDATOR_V12
# Purpose:
#   Runtime-status answers can be token-clean but still semantically false.
#
#   V11 sanitized visible poison tokens.
#   V12 rejects fabricated/unsupported runtime-status synthesis such as:
#       - SOURCE: None + SYNTHESIS_VALIDATED: True
#       - "Memory: empty"
#       - "Storage: not implemented"
#       - "Weight: 0.7"
#       - "Bias: 0.3"
#       - fake VRAM / GPT / TPU claims
#
#   Quick mode may still return direct live evidence.
#   Non-Quick modes may attempt normal synthesis first, but the final visible
#   result must be grounded or repaired from live runtime evidence.
# =============================================================================

try:
    import json as _eli_v12_json
    import os as _eli_v12_os
    import re as _eli_v12_re
    from pathlib import Path as _eli_v12_Path

    _ELI_RUNTIME_STATUS_SEMANTIC_VALIDATOR_V12_PREV_PROCESS = CognitiveEngine.process

    _ELI_V12_RUNTIME_STATUS_ALLOWED_SOURCES = {
        "runtime_status_quick_dynamic_evidence_v8",
        "runtime_status_nonquick_repaired_from_live_evidence_v10",
        "runtime_status_nonquick_repaired_from_live_evidence_v12",
    }

    _ELI_V12_REQUIRED_RUNTIME_TERMS = (
        "provider",
        "model_name",
        "model_path",
        "context_size",
        "gpu_layers",
        "batch_size",
        "cpu_threads",
    )

    _ELI_V12_UNSUPPORTED_RUNTIME_CLAIMS = (
        "memory: empty",
        "storage: not implemented",
        "weight:",
        "bias:",
        "384gb",
        "512m tokens",
        "gpt-4",
        "gpt-7b",
        "tpu",
        "time complexity: o(1)",
        "json-based",
        "groundless ai",
        "fully local, self-initializes",
        "you are deepseek-r1-distill",
    )

    _ELI_V12_POISON_OR_TEMPLATE = (
        "</think>",
        "<|im_",
        "|im_end|",
        ">>>>>>>",
        "<<<<<<<",
        "unable to answer",
        "no suitable response",
        "clarify your request",
        "don't have access to internal system details",
        "do not have access to internal system details",
        "i can't provide real-time data",
    )

    def _eli_v12_lower_text(_value):
        try:
            return str(_value or "").lower()
        except Exception:
            return ""

    def _eli_v12_deep_get(_obj, *_path, default=None):
        cur = _obj
        for key in _path:
            if isinstance(cur, dict):
                cur = cur.get(key)
            else:
                return default
        return cur if cur is not None else default

    def _eli_v12_load_runtime_snapshot():
        candidates = []

        try:
            root = _eli_v12_os.getcwd()
            candidates.append(_eli_v12_Path(root) / "artifacts" / "runtime_snapshot.json")
        except Exception:
            pass

        try:
            candidates.append(_eli_v12_Path.home() / "Desktop" / "ELI_MKXI" / "artifacts" / "runtime_snapshot.json")
        except Exception:
            pass

        for path in candidates:
            try:
                if path.exists():
                    return _eli_v12_json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue

        return {}

    def _eli_v12_extract_runtime_facts(_result):
        report = _result.get("report") if isinstance(_result, dict) else {}
        if not isinstance(report, dict):
            report = {}

        snap = _eli_v12_load_runtime_snapshot()

        runtime = report.get("runtime")
        if not isinstance(runtime, dict):
            runtime = snap.get("runtime") if isinstance(snap.get("runtime"), dict) else snap

        settings = report.get("settings")
        if not isinstance(settings, dict):
            settings = snap.get("settings") if isinstance(snap.get("settings"), dict) else {}

        paths = report.get("paths")
        if not isinstance(paths, dict):
            paths = snap.get("paths") if isinstance(snap.get("paths"), dict) else {}

        adaptive = runtime.get("adaptive_load_report") if isinstance(runtime, dict) else {}
        if not isinstance(adaptive, dict):
            adaptive = {}

        gpu_probe = adaptive.get("gpu_probe")
        if not isinstance(gpu_probe, dict):
            gpu_probe = {}

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
            or (_eli_v12_os.path.basename(model_path) if model_path else "")
            or ""
        )

        facts = {
            "provider": runtime.get("provider") or settings.get("provider") or "gguf",
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

        return facts

    def _eli_v12_runtime_status_invalid_reason(_result, _mode):
        if not isinstance(_result, dict):
            return "non_dict_runtime_status_result"

        content = str(_result.get("content") or _result.get("response") or "")
        low = _eli_v12_lower_text(content)

        source = _result.get("evidence_source")
        report = _result.get("report") if isinstance(_result.get("report"), dict) else {}
        synthesis_validated = report.get("synthesis_validated")

        for token in _ELI_V12_POISON_OR_TEMPLATE:
            if token in low:
                return "poison_or_template_token"

        for claim in _ELI_V12_UNSUPPORTED_RUNTIME_CLAIMS:
            if claim in low:
                return "unsupported_runtime_claim"

        missing = [term for term in _ELI_V12_REQUIRED_RUNTIME_TERMS if term not in low]
        if missing:
            return "missing_runtime_fields:" + ",".join(missing)

        # Runtime status is a grounded control action. SOURCE None is not enough
        # unless a stricter validator has attached a defensible evidence source.
        if _mode != "quick" and source not in _ELI_V12_RUNTIME_STATUS_ALLOWED_SOURCES:
            return "missing_or_untrusted_evidence_source"

        # If some earlier validator says True but source is None, that is not enough.
        if _mode != "quick" and synthesis_validated is True and not source:
            return "validated_without_source"

        return ""

    def _eli_v12_build_runtime_status_content(_facts, _mode, _reason):
        lines = []
        lines.append("Runtime status, repaired from live grounded evidence after non-Quick synthesis failed semantic validation.")
        lines.append("")
        lines.append("Identity:")
        lines.append("- name: ELI / Entropy Logical Interface")
        lines.append("- role: local GGUF-backed assistant running inside this ELI MKXI project")
        lines.append("")
        lines.append("Effective runtime:")
        lines.append(f"- provider: {_facts.get('provider')}")
        lines.append(f"- model_name: {_facts.get('model_name')}")
        lines.append(f"- model_path: {_facts.get('model_path')}")
        lines.append(f"- context_size: {_facts.get('context_size')}")
        lines.append(f"- gpu_layers: {_facts.get('gpu_layers')}")
        lines.append(f"- batch_size: {_facts.get('batch_size')}")
        lines.append(f"- cpu_threads: {_facts.get('cpu_threads')}")
        lines.append(f"- loaded_in_this_process: {_facts.get('loaded_in_this_process')}")
        lines.append(f"- pid: {_facts.get('pid')}")
        lines.append("")
        lines.append("GPU:")
        lines.append(f"- name: {_facts.get('gpu_name')}")
        lines.append(f"- total_mib: {_facts.get('gpu_total_mib')}")
        lines.append(f"- free_mib: {_facts.get('gpu_free_mib')}")
        lines.append("")
        lines.append("Project/runtime paths:")
        lines.append(f"- project_root: {_facts.get('project_root')}")
        lines.append(f"- user_db: {_facts.get('user_db')}")
        lines.append(f"- agent_db: {_facts.get('agent_db')}")
        lines.append("")
        lines.append("Generation settings:")
        lines.append(f"- max_tokens: {_facts.get('max_tokens')}")
        lines.append(f"- temperature: {_facts.get('temperature')}")
        lines.append(f"- use_mmap: {_facts.get('use_mmap')}")
        lines.append(f"- use_mlock: {_facts.get('use_mlock')}")
        lines.append("")
        lines.append("Validation note:")
        lines.append(f"- requested_mode: {_mode}")
        lines.append(f"- repair_reason: {_reason}")
        lines.append("- Quick mode remains allowed to return direct runtime evidence.")
        lines.append("- Non-Quick mode attempted the normal synthesis path first; this semantic guard blocked a fabricated or unsupported runtime-status answer from reaching the GUI.")
        return "\n".join(lines)

    def _eli_v12_get_requested_mode(args, kwargs):
        mode = kwargs.get("reasoning_mode")
        if mode:
            return str(mode)
        if len(args) >= 2:
            try:
                return str(args[1])
            except Exception:
                pass
        return ""

    def _eli_runtime_status_semantic_validator_v12_process(self, *args, **kwargs):
        mode = _eli_v12_get_requested_mode(args, kwargs)
        result = _ELI_RUNTIME_STATUS_SEMANTIC_VALIDATOR_V12_PREV_PROCESS(self, *args, **kwargs)

        if not isinstance(result, dict):
            return result

        if result.get("action") != "RUNTIME_STATUS":
            return result

        if mode == "quick":
            return result

        reason = _eli_v12_runtime_status_invalid_reason(result, mode)

        if not reason:
            return result

        facts = _eli_v12_extract_runtime_facts(result)
        repaired = _eli_v12_build_runtime_status_content(facts, mode, reason)

        report = result.get("report")
        if not isinstance(report, dict):
            report = {}

        report["synthesis_validated"] = False
        report["semantic_validation_failed"] = True
        report["repair_reason"] = reason
        report["semantic_validator"] = "runtime_status_semantic_validator_v12"

        result["content"] = repaired
        result["response"] = repaired
        result["evidence_source"] = "runtime_status_nonquick_repaired_from_live_evidence_v12"
        result["report"] = report

        return result

    CognitiveEngine.process = _eli_runtime_status_semantic_validator_v12_process
    print("[ENGINE] runtime-status semantic validator v12 installed", flush=True)

except Exception as _eli_runtime_status_semantic_validator_v12_err:
    print(
        f"[ENGINE] runtime-status semantic validator v12 failed: {_eli_runtime_status_semantic_validator_v12_err!r}",
        flush=True,
    )
'''

p.write_text(src.rstrip() + "\n\n" + append + "\n", encoding="utf-8")
print("installed runtime-status semantic validator v12")
PY

python3 -m py_compile "$ENGINE"

{
  echo "=== PATCHED ==="
  date -Is
  echo "backup=$BACKUP"
  echo
  echo "=== MARKERS ==="
  grep -n "runtime-status semantic validator v12\|ELI_RUNTIME_STATUS_SEMANTIC_VALIDATOR_V12" "$ENGINE" || true
  echo
  echo "=== GIT DIFF STAT ==="
  git diff --stat -- "$ENGINE"
} | tee "$REPORT"

echo
echo "Report: $REPORT"
echo "Backup: $BACKUP"
