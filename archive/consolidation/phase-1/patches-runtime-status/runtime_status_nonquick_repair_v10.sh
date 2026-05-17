#!/usr/bin/env bash
set -Eeuo pipefail

cd ~/Desktop/ELI_MKXI || exit 1

STAMP="$(date +%Y%m%d_%H%M%S)"
ENGINE="eli/kernel/engine.py"
BACKUP="ops/backups/engine.py.before_runtime_status_nonquick_repair_v10_${STAMP}"
REPORT="ops/reports/runtime_status_nonquick_repair_v10_${STAMP}.log"

cp -a "$ENGINE" "$BACKUP"

python3 - <<'PY'
from pathlib import Path
import sys

p = Path("eli/kernel/engine.py")
text = p.read_text(encoding="utf-8")

marker = "[ENGINE] runtime-status nonquick repair validator v10 installed"

if marker in text:
    print("runtime-status nonquick repair validator v10 already installed")
    sys.exit(0)

block = r'''

# =============================================================================
# ELI RUNTIME_STATUS NON-QUICK REPAIR VALIDATOR V10
# Quick mode may return direct evidence.
# Non-Quick modes must attempt normal synthesis, but if synthesis corrupts,
# refuses, leaks chat template/control tokens, or omits grounded runtime fields,
# repair from live runtime evidence instead of surfacing hallucinated output.
# =============================================================================
try:
    _ELI_RUNTIME_STATUS_REPAIR_V10_PREV_PROCESS = CognitiveEngine.process

    def _eli_runtime_v10_mode_key(value):
        return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")

    def _eli_runtime_v10_get_mode(self, args, kwargs):
        mode = kwargs.get("reasoning_mode", None)
        if mode is None:
            mode = kwargs.get("mode", None)

        if mode is None and args:
            for a in args:
                if isinstance(a, str) and a.strip():
                    k = _eli_runtime_v10_mode_key(a)
                    if k in {
                        "quick",
                        "fast",
                        "direct",
                        "chain_of_thought",
                        "cot",
                        "self_consistency",
                        "self_c",
                        "tree_of_thoughts",
                        "tot",
                        "constitutional_ai",
                        "constitutional",
                        "const_ai",
                    }:
                        mode = a
                        break

        if mode is None:
            for attr in (
                "reasoning_mode",
                "current_reasoning_mode",
                "mode",
                "_reasoning_mode",
                "_current_reasoning_mode",
            ):
                try:
                    v = getattr(self, attr, None)
                    if isinstance(v, str) and v.strip():
                        mode = v
                        break
                except Exception:
                    pass

        return _eli_runtime_v10_mode_key(mode or "")

    def _eli_runtime_v10_is_runtime_question(text):
        q = " ".join(str(text or "").lower().split())
        if not q:
            return False

        identity_hit = any(x in q for x in (
            "who are you",
            "what are you running",
            "actually running on",
            "runtime status",
            "runtime truth",
            "model, context size",
        ))

        runtime_hit = any(x in q for x in (
            "model",
            "context",
            "ctx",
            "gpu layer",
            "gpu layers",
            "batch",
            "threads",
            "runtime",
            "running on",
            "everything",
        ))

        return bool(identity_hit and runtime_hit)

    def _eli_runtime_v10_text(result):
        if isinstance(result, dict):
            return str(result.get("content") or result.get("response") or "")
        return str(result or "")

    def _eli_runtime_v10_bad_output(text):
        t = str(text or "")
        low = t.lower()

        if not t.strip():
            return "empty_output"

        poison = (
            "</think>",
            "<|im_",
            "|im_end|",
            ">>>>>>>",
            "<<<<<<<",
            "replace",
            "unable to answer",
            "no suitable response",
            "clarify your request",
            "don't have access to internal system details",
            "do not have access to internal system details",
            "i can't provide real-time data",
            "i cannot provide real-time data",
            "gpt-4",
            "context size: 512b",
            "time complexity: o(1)",
            "memory size: 512 tokens",
        )

        for bad in poison:
            if bad in low:
                return f"poison_token_or_unsupported_claim:{bad}"

        required_hits = 0
        for field in (
            "model",
            "context",
            "ctx",
            "gpu",
            "gpu_layers",
            "gpu layers",
            "batch",
            "threads",
            "cpu_threads",
            "provider",
        ):
            if field in low:
                required_hits += 1

        if required_hits < 4:
            return "missing_runtime_fields"

        return ""

    def _eli_runtime_v10_execute_evidence(question):
        try:
            ev = execute_action("RUNTIME_STATUS", {"question": str(question or "")})
            if isinstance(ev, dict):
                return ev
        except Exception as e:
            return {
                "ok": False,
                "action": "RUNTIME_STATUS",
                "error": f"{type(e).__name__}: {e}",
                "report": {},
            }

        return {
            "ok": False,
            "action": "RUNTIME_STATUS",
            "error": "execute_action did not return a dict",
            "report": {},
        }

    def _eli_runtime_v10_pick(report, *paths, default=None):
        cur = report
        for key in paths:
            if not isinstance(cur, dict):
                return default
            cur = cur.get(key)
        return cur if cur is not None else default

    def _eli_runtime_v10_format_repair(question, mode, ev, reason):
        report = ev.get("report") if isinstance(ev, dict) else {}
        if not isinstance(report, dict):
            report = {}

        runtime = report.get("runtime") or {}
        settings = report.get("settings") or {}
        paths = report.get("paths") or {}

        model_name = (
            runtime.get("model_name")
            or Path(str(runtime.get("model_path") or settings.get("model_path") or "")).name
            or "unknown"
        )

        model_path = (
            runtime.get("model_path")
            or settings.get("model_path")
            or settings.get("gguf_model_path")
            or "unknown"
        )

        provider = runtime.get("provider") or settings.get("provider") or "unknown"
        n_ctx = runtime.get("n_ctx") or settings.get("n_ctx") or settings.get("context_size") or "unknown"
        gpu_layers = runtime.get("n_gpu_layers") or settings.get("n_gpu_layers") or settings.get("gpu_layers") or "unknown"
        batch = runtime.get("n_batch") or settings.get("batch_size") or settings.get("n_batch") or "unknown"
        threads = runtime.get("n_threads") or settings.get("n_threads") or "unknown"
        loaded = runtime.get("loaded")
        pid = runtime.get("pid")
        project_root = paths.get("project_root") or "unknown"
        user_db = paths.get("user_db") or paths.get("memory_db") or "unknown"
        agent_db = paths.get("agent_db") or "unknown"

        gpu_name = "unknown"
        gpu_total = None
        gpu_free = None
        try:
            load_report = runtime.get("adaptive_load_report") or {}
            gpu_probe = load_report.get("gpu_probe") or {}
            gpu_name = gpu_probe.get("name") or gpu_name
            gpu_total = gpu_probe.get("total_mib")
            gpu_free = gpu_probe.get("free_mib")
        except Exception:
            pass

        lines = [
            "Runtime status, repaired from live grounded evidence after non-Quick synthesis failed validation.",
            "",
            "Identity:",
            "- name: ELI / Entropy Logical Interface",
            "- role: local GGUF-backed assistant running inside this ELI MKXI project",
            "",
            "Effective runtime:",
            f"- provider: {provider}",
            f"- model_name: {model_name}",
            f"- model_path: {model_path}",
            f"- context_size: {n_ctx}",
            f"- gpu_layers: {gpu_layers}",
            f"- batch_size: {batch}",
            f"- cpu_threads: {threads}",
            f"- loaded_in_this_process: {loaded}",
            f"- pid: {pid}",
            "",
            "GPU:",
            f"- name: {gpu_name}",
        ]

        if gpu_total is not None:
            lines.append(f"- total_mib: {gpu_total}")
        if gpu_free is not None:
            lines.append(f"- free_mib: {gpu_free}")

        lines.extend([
            "",
            "Project/runtime paths:",
            f"- project_root: {project_root}",
            f"- user_db: {user_db}",
            f"- agent_db: {agent_db}",
            "",
            "Validation note:",
            f"- requested_mode: {mode or 'unknown_nonquick'}",
            f"- repair_reason: {reason}",
            "- Quick mode remains allowed to return direct evidence.",
            "- Non-Quick mode attempted the normal synthesis path first; this repair blocked a bad/refusal/template-leak answer from reaching the GUI.",
        ])

        return "\n".join(lines).strip()

    def _eli_runtime_status_repair_v10_process(self, message="", *args, **kwargs):
        mode = _eli_runtime_v10_get_mode(self, args, kwargs)
        quick = mode in {"quick", "fast", "direct"}

        result = _ELI_RUNTIME_STATUS_REPAIR_V10_PREV_PROCESS(self, message, *args, **kwargs)

        if quick:
            return result

        is_runtime_result = isinstance(result, dict) and str(result.get("action") or "").upper() == "RUNTIME_STATUS"
        is_runtime_question = _eli_runtime_v10_is_runtime_question(message)

        if not (is_runtime_result or is_runtime_question):
            return result

        content = _eli_runtime_v10_text(result)
        reason = _eli_runtime_v10_bad_output(content)

        if not reason:
            if isinstance(result, dict):
                patched = dict(result)
                rep = dict(patched.get("report") or {})
                rep.setdefault("synthesis_validated", True)
                rep.setdefault("runtime_status_validator", "v10_pass")
                patched["report"] = rep
                return patched
            return result

        ev = _eli_runtime_v10_execute_evidence(message)
        repaired = _eli_runtime_v10_format_repair(message, mode, ev, reason)

        return {
            "ok": True,
            "action": "RUNTIME_STATUS",
            "content": repaired,
            "response": repaired,
            "evidence_source": "runtime_status_nonquick_repaired_from_live_evidence_v10",
            "report": {
                "ok": True,
                "mode": mode,
                "synthesis_validated": False,
                "repair_reason": reason,
                "validator": "runtime_status_nonquick_repair_v10",
                "raw_bad_output_head": content[:500],
                "grounding_report": ev.get("report") if isinstance(ev, dict) else {},
            },
        }

    CognitiveEngine.process = _eli_runtime_status_repair_v10_process
    print("[ENGINE] runtime-status nonquick repair validator v10 installed", flush=True)

except Exception as _eli_runtime_status_repair_v10_err:
    print(f"[ENGINE] runtime-status nonquick repair validator v10 failed: {_eli_runtime_status_repair_v10_err}", flush=True)
'''

text = text.rstrip() + "\n\n" + block + "\n"
p.write_text(text, encoding="utf-8")
print("installed runtime-status nonquick repair validator v10")
PY

python3 -m compileall -q "$ENGINE"

{
  echo "=== PATCHED ==="
  date -Is
  echo "backup=$BACKUP"
  echo
  echo "=== MARKERS ==="
  grep -n "runtime-status .*v10\|runtime-status .*intercept\|RUNTIME_STATUS non-quick" "$ENGINE" || true
  echo
  echo "=== GIT DIFF STAT ==="
  git diff --stat -- "$ENGINE" || true
} | tee "$REPORT"

echo
echo "Report: $REPORT"
echo "Backup: $BACKUP"
