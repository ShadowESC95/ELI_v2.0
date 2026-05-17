#!/usr/bin/env bash
set -euo pipefail

cd ~/Desktop/ELI_MKXI || exit 1
source .venv/bin/activate || true

python3 - <<'PY'
from pathlib import Path

p = Path("eli/kernel/engine.py")
src = p.read_text(encoding="utf-8")
orig = src

tag = "ELI_RUNTIME_STATUS_NONQUICK_STRICT_NO_RAW_GGUF_V2"
if tag in src:
    print("[PATCH] strict runtime-status no-raw-GGUF path already installed")
    raise SystemExit(0)

anchor = "Non-quick control action RUNTIME_STATUS kept for Stage 11/12 synthesis; direct evidence return skipped"
idx = src.find(anchor)
if idx < 0:
    raise SystemExit("[PATCH] could not find current non-Quick runtime-status control marker")

# Find the end of the print(...) statement containing the anchor.
line_start = src.rfind("\n", 0, idx) + 1
stmt_start = src.rfind("\n", 0, line_start - 1) + 1

# Walk from the start of the print statement to its closing parenthesis.
# This is intentionally simple but handles multiline print(...).
pos = stmt_start
paren = 0
seen = False
end = None
while pos < len(src):
    ch = src[pos]
    if ch == "(":
        paren += 1
        seen = True
    elif ch == ")":
        paren -= 1
        if seen and paren <= 0:
            # include trailing newline
            nl = src.find("\n", pos)
            end = len(src) if nl < 0 else nl + 1
            break
    pos += 1

if end is None:
    raise SystemExit("[PATCH] could not determine end of runtime-status marker print")

indent = src[stmt_start:line_start]
if not indent.strip() == "":
    # fallback: infer leading whitespace from line containing the print
    marker_line = src[line_start:src.find("\n", line_start)]
    indent = marker_line[:len(marker_line) - len(marker_line.lstrip())]

block = f'''
{indent}# === {tag} ===
{indent}# Runtime-status is deterministic live telemetry. In non-Quick modes we still
{indent}# return a grounded synthesized surface, but we do not send this control
{indent}# action through the general GGUF final-loop candidate path because that path
{indent}# repeatedly invents unsupported runtime claims in raw telemetry.
{indent}try:
{indent}    if str(action or "").upper() == "RUNTIME_STATUS" and isinstance(_ev_result, dict) and _ev_result.get("ok"):
{indent}        _rs_report = dict(_ev_result.get("report") or {{}})
{indent}        _rs_runtime = dict(_rs_report.get("runtime") or {{}})
{indent}        _rs_paths = dict(_rs_report.get("paths") or {{}})
{indent}        _rs_settings = dict(_rs_report.get("settings") or {{}})
{indent}        try:
{indent}            _rs_gpu = dict(((_rs_runtime.get("adaptive_load_report") or {{}}).get("gpu_probe")) or {{}})
{indent}        except Exception:
{indent}            _rs_gpu = {{}}
{indent}
{indent}        def _rs_val(*vals, default="unknown"):
{indent}            for _v in vals:
{indent}                if _v is not None and str(_v) != "":
{indent}                    return _v
{indent}            return default
{indent}
{indent}        _rs_provider = _rs_val(_rs_runtime.get("provider"), _rs_settings.get("provider"))
{indent}        _rs_model_path = _rs_val(_rs_runtime.get("model_path"), _rs_settings.get("model_path"), _rs_settings.get("gguf_model_path"))
{indent}        _rs_model_name = _rs_val(_rs_runtime.get("model_name"))
{indent}        _rs_ctx = _rs_val(_rs_runtime.get("n_ctx"), _rs_settings.get("n_ctx"))
{indent}        _rs_gpu_layers = _rs_val(_rs_runtime.get("n_gpu_layers"), _rs_settings.get("n_gpu_layers"), _rs_settings.get("gpu_layers"))
{indent}        _rs_batch = _rs_val(_rs_runtime.get("n_batch"), _rs_runtime.get("batch_size"), _rs_settings.get("batch_size"))
{indent}        _rs_threads = _rs_val(_rs_runtime.get("n_threads"), _rs_settings.get("n_threads"))
{indent}        _rs_loaded = _rs_val(_rs_runtime.get("loaded"))
{indent}        _rs_pid = _rs_val(_rs_runtime.get("pid"))
{indent}        _rs_max_tokens = _rs_val(_rs_settings.get("max_tokens"))
{indent}        _rs_temp = _rs_val(_rs_settings.get("temperature"))
{indent}        _rs_mmap = _rs_val(_rs_settings.get("use_mmap"))
{indent}        _rs_mlock = _rs_val(_rs_settings.get("use_mlock"))
{indent}
{indent}        _rs_text = "\\n".join([
{indent}            "Runtime status, synthesized from live grounded evidence without raw GGUF candidate telemetry.",
{indent}            "",
{indent}            "Identity:",
{indent}            "- name: ELI / Entropy Logical Interface",
{indent}            "- role: local GGUF-backed assistant running inside this ELI MKXI project",
{indent}            "",
{indent}            "Effective runtime:",
{indent}            f"- provider: {{_rs_provider}}",
{indent}            f"- model_name: {{_rs_model_name}}",
{indent}            f"- model_path: {{_rs_model_path}}",
{indent}            f"- context_size: {{_rs_ctx}}",
{indent}            f"- gpu_layers: {{_rs_gpu_layers}}",
{indent}            f"- batch_size: {{_rs_batch}}",
{indent}            f"- cpu_threads: {{_rs_threads}}",
{indent}            f"- loaded_in_this_process: {{_rs_loaded}}",
{indent}            f"- pid: {{_rs_pid}}",
{indent}            "",
{indent}            "GPU:",
{indent}            f"- name: {{_rs_val(_rs_gpu.get('name'))}}",
{indent}            f"- total_mib: {{_rs_val(_rs_gpu.get('total_mib'))}}",
{indent}            f"- free_mib: {{_rs_val(_rs_gpu.get('free_mib'))}}",
{indent}            "",
{indent}            "Project/runtime paths:",
{indent}            f"- project_root: {{_rs_val(_rs_paths.get('project_root'))}}",
{indent}            f"- user_db: {{_rs_val(_rs_paths.get('user_db'))}}",
{indent}            f"- agent_db: {{_rs_val(_rs_paths.get('agent_db'))}}",
{indent}            "",
{indent}            "Generation settings:",
{indent}            f"- max_tokens: {{_rs_max_tokens}}",
{indent}            f"- temperature: {{_rs_temp}}",
{indent}            f"- use_mmap: {{_rs_mmap}}",
{indent}            f"- use_mlock: {{_rs_mlock}}",
{indent}            "",
{indent}            "Validation note:",
{indent}            f"- requested_mode: {{str(locals().get('_ctrl_mode') or locals().get('reasoning_mode') or 'nonquick')}}",
{indent}            "- response_surface: non-Quick strict grounded synthesis; general GGUF candidate telemetry skipped for this control action",
{indent}            "- repair_reason: strict_grounded_no_raw_gguf",
{indent}        ])
{indent}
{indent}        _rs_trace = trace if isinstance(trace, dict) else {{}}
{indent}        _rs_mode = str(locals().get("_ctrl_mode") or locals().get("reasoning_mode") or getattr(self, "_reasoning_mode", None) or "nonquick")
{indent}        _rs_final = self._finalize_chat_result(
{indent}            user_input=user_input,
{indent}            response=_rs_text,
{indent}            trace=_rs_trace,
{indent}            score=1.0,
{indent}            threshold=1.0,
{indent}            clarified=False,
{indent}            evidence_used=True,
{indent}            reasoning_mode=_rs_mode,
{indent}        )
{indent}        _rs_final["action"] = "RUNTIME_STATUS"
{indent}        _rs_final["tool_result"] = _ev_result
{indent}        _rs_final["grounded"] = True
{indent}        _rs_final["evidence_used"] = True
{indent}        _rs_final["content"] = _rs_text
{indent}        _rs_final["response"] = _rs_text
{indent}        _rs_final["source"] = "runtime_status_nonquick_canonical_contract"
{indent}        _rs_final["evidence_source"] = "runtime_status_nonquick_canonical_contract"
{indent}        _rs_final["synthesis_validated"] = False
{indent}        _rs_final["repair"] = "strict_grounded_no_raw_gguf"
{indent}        _rs_final["repair_reason"] = "strict_grounded_no_raw_gguf"
{indent}        try:
{indent}            _rs_final.setdefault("meta", {{}})["response_mode"] = "runtime_status_nonquick_strict_grounded_no_raw_gguf"
{indent}            _rs_final["meta"]["raw_gguf_candidates_skipped"] = True
{indent}            _rs_final["meta"]["tool_evidence_source"] = _ev_result.get("evidence_source")
{indent}        except Exception:
{indent}            pass
{indent}        try:
{indent}            self._learn_from_result(intent, _ev_result)
{indent}        except Exception:
{indent}            pass
{indent}        try:
{indent}            self._execute_post_actions(_rs_trace, _ev_result)
{indent}        except Exception as _rs_pa_err:
{indent}            print(f"[COGNITIVE] Runtime-status strict post-actions failed: {{_rs_pa_err}}", flush=True)
{indent}        return _rs_final
{indent}except Exception as _rs_strict_err:
{indent}    print(f"[COGNITIVE][WARN] runtime-status strict no-raw-GGUF path failed: {{_rs_strict_err}}", flush=True)
{indent}# === END {tag} ===
'''

src = src[:end] + block + src[end:]

p.write_text(src, encoding="utf-8")
print("[PATCH] installed strict non-Quick RUNTIME_STATUS grounded no-raw-GGUF path")
PY

python3 -m py_compile eli/kernel/engine.py
echo
grep -n "ELI_RUNTIME_STATUS_NONQUICK_STRICT_NO_RAW_GGUF_V2" eli/kernel/engine.py
