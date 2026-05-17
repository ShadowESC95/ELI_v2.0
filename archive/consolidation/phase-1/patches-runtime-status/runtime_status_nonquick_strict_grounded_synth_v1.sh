#!/usr/bin/env bash
set -euo pipefail

cd ~/Desktop/ELI_MKXI || exit 1
source .venv/bin/activate || true

python3 - <<'PY'
from pathlib import Path
import re

p = Path("eli/kernel/engine.py")
src = p.read_text(encoding="utf-8")
orig = src

HELPER_MARK = "# === ELI_RUNTIME_STATUS_STRICT_GROUNDED_SYNTH_V1 ==="
INSERT_MARK = "# === ELI_RUNTIME_STATUS_NONQUICK_STRICT_SYNTH_V1 ==="

helper = r'''
# === ELI_RUNTIME_STATUS_STRICT_GROUNDED_SYNTH_V1 ===
def _eli_runtime_status_strict_grounded_synth_v1(ev_result, reasoning_mode="nonquick"):
    """
    Evidence-bounded runtime-status renderer.

    Purpose:
    - Stop RUNTIME_STATUS non-Quick modes from producing raw GGUF candidate
      hallucinations.
    - Preserve router/executor/evidence/finalizer pipeline.
    - Render only live fields already present in the runtime evidence payload.
    - Do not assert dependency/network/privacy/project/memory-usage claims
      unless those exact fields are present in evidence.
    """
    def _as_dict(x):
        return x if isinstance(x, dict) else {}

    def _first(*vals, default="unknown"):
        for v in vals:
            if v is None:
                continue
            if isinstance(v, str) and not v.strip():
                continue
            return v
        return default

    report = _as_dict(_as_dict(ev_result).get("report"))
    runtime = _as_dict(report.get("runtime"))
    settings = _as_dict(report.get("settings"))
    paths = _as_dict(report.get("paths"))

    effective = _as_dict(runtime.get("effective"))
    requested = _as_dict(runtime.get("requested"))
    adaptive = _as_dict(runtime.get("adaptive_load_report"))
    gpu = _as_dict(adaptive.get("gpu_probe"))

    provider = _first(runtime.get("provider"), settings.get("provider"))
    model_name = _first(runtime.get("model_name"))
    model_path = _first(runtime.get("model_path"), report.get("model_path"), settings.get("model_path"), settings.get("gguf_model_path"))

    context_size = _first(effective.get("n_ctx"), runtime.get("n_ctx"), requested.get("n_ctx"), settings.get("n_ctx"))
    gpu_layers = _first(effective.get("n_gpu_layers"), runtime.get("n_gpu_layers"), requested.get("n_gpu_layers"), settings.get("n_gpu_layers"), settings.get("gpu_layers"))
    batch_size = _first(effective.get("n_batch"), runtime.get("n_batch"), runtime.get("batch_size"), requested.get("n_batch"), settings.get("batch_size"))
    cpu_threads = _first(effective.get("n_threads"), runtime.get("n_threads"), requested.get("n_threads"), settings.get("n_threads"))
    loaded = _first(runtime.get("loaded"))
    pid = _first(runtime.get("pid"))

    max_tokens = _first(settings.get("max_tokens"))
    temperature = _first(settings.get("temperature"))
    use_mmap = _first(settings.get("use_mmap"))
    use_mlock = _first(settings.get("use_mlock"))

    project_root = _first(paths.get("project_root"))
    user_db = _first(paths.get("user_db"))
    agent_db = _first(paths.get("agent_db"))

    gpu_name = _first(gpu.get("name"))
    gpu_total = _first(gpu.get("total_mib"))
    gpu_free = _first(gpu.get("free_mib"))

    mode = str(reasoning_mode or "nonquick").strip().lower().replace(" ", "_")

    lines = [
        "Runtime status, synthesized from live grounded evidence.",
        "",
        "Identity:",
        "- name: ELI / Entropy Logical Interface",
        "- role: local GGUF-backed assistant running inside this ELI MKXI project",
        "",
        "Effective runtime:",
        f"- provider: {provider}",
        f"- model_name: {model_name}",
        f"- model_path: {model_path}",
        f"- context_size: {context_size}",
        f"- gpu_layers: {gpu_layers}",
        f"- batch_size: {batch_size}",
        f"- cpu_threads: {cpu_threads}",
        f"- loaded_in_this_process: {loaded}",
        f"- pid: {pid}",
        "",
        "GPU:",
        f"- name: {gpu_name}",
        f"- total_mib: {gpu_total}",
        f"- free_mib: {gpu_free}",
        "",
        "Project/runtime paths:",
        f"- project_root: {project_root}",
        f"- user_db: {user_db}",
        f"- agent_db: {agent_db}",
        "",
        "Generation settings:",
        f"- max_tokens: {max_tokens}",
        f"- temperature: {temperature}",
        f"- use_mmap: {use_mmap}",
        f"- use_mlock: {use_mlock}",
        "",
        "Validation note:",
        f"- requested_mode: {mode}",
        "- response_surface: non-Quick evidence-bounded runtime synthesis",
        "- Router, executor, live evidence collection, finalization, and post-actions still ran.",
        "- Raw GGUF candidate generation was skipped for this closed-world runtime telemetry action.",
        "- repair_reason: strict_runtime_status_grounded_synth_v1",
    ]

    return "\n".join(lines)
# === END ELI_RUNTIME_STATUS_STRICT_GROUNDED_SYNTH_V1 ===
'''

if HELPER_MARK not in src:
    m = re.search(r"\nclass\s+CognitiveEngine\b", src)
    if not m:
        raise SystemExit("[PATCH] Could not find CognitiveEngine class insertion point")
    src = src[:m.start()] + "\n\n" + helper + "\n" + src[m.start():]

if INSERT_MARK not in src:
    lines = src.splitlines()
    idx = None
    for i, line in enumerate(lines):
        if "Non-quick control action" in line and "Stage 11/12 synthesis" in line:
            idx = i
            break

    if idx is None:
        raise SystemExit("[PATCH] Could not find non-Quick control action synthesis marker")

    # Walk upward to the print(...) start, then downward to the end of that print statement.
    start = idx
    while start > 0 and "print(" not in lines[start]:
        start -= 1

    if "print(" not in lines[start]:
        raise SystemExit("[PATCH] Could not locate print statement start")

    bal = 0
    end = None
    for j in range(start, len(lines)):
        bal += lines[j].count("(") - lines[j].count(")")
        if j >= start and bal <= 0:
            end = j + 1
            break

    if end is None:
        raise SystemExit("[PATCH] Could not locate print statement end")

    indent = re.match(r"^(\s*)", lines[start]).group(1)

    insert = f'''
{indent}{INSERT_MARK}
{indent}if str(action or "").upper() == "RUNTIME_STATUS" and isinstance(_ev_result, dict) and _ev_result.get("ok"):
{indent}    try:
{indent}        _synth = _eli_runtime_status_strict_grounded_synth_v1(_ev_result, _ctrl_mode)
{indent}        print(
{indent}            "[COGNITIVE] Runtime-status strict grounded synthesis selected; skipping raw GGUF candidate generation",
{indent}            flush=True,
{indent}        )
{indent}        _final = self._finalize_chat_result(
{indent}            user_input=user_input,
{indent}            response=_synth,
{indent}            trace=trace,
{indent}            score=1.0,
{indent}            threshold=1.0,
{indent}            clarified=False,
{indent}            evidence_used=True,
{indent}            reasoning_mode=_ctrl_mode,
{indent}        )
{indent}        _final["action"] = str(action).upper()
{indent}        _final["tool_result"] = _ev_result
{indent}        _final["grounded"] = True
{indent}        _final["evidence_used"] = True
{indent}        try:
{indent}            _final.setdefault("meta", {{}})["response_mode"] = "strict_runtime_status_grounded_synthesis"
{indent}            _final["meta"]["tool_evidence_source"] = _ev_result.get("evidence_source")
{indent}            _final["meta"]["orchestrator_plan"] = trace.get("orchestrator_plan") if isinstance(trace, dict) else None
{indent}            _final["meta"]["gguf_candidate_generation_skipped"] = True
{indent}        except Exception:
{indent}            pass
{indent}        try:
{indent}            self._learn_from_result(intent, _ev_result)
{indent}        except Exception:
{indent}            pass
{indent}        try:
{indent}            self._execute_post_actions(trace, _ev_result)
{indent}        except Exception as _pa_err:
{indent}            print(f"[COGNITIVE] Control post-actions failed: {{_pa_err}}")
{indent}        return _final
{indent}    except Exception as _eli_rs_strict_synth_err:
{indent}        print(f"[ENGINE][WARN] runtime-status strict grounded synthesis failed: {{_eli_rs_strict_synth_err}}", flush=True)
{indent}# === END ELI_RUNTIME_STATUS_NONQUICK_STRICT_SYNTH_V1 ===
'''.splitlines()

    lines[end:end] = insert
    src = "\n".join(lines) + "\n"

if src == orig:
    print("[PATCH] no changes needed; strict runtime-status non-Quick synthesis already installed")
else:
    p.write_text(src, encoding="utf-8")
    print("[PATCH] installed strict runtime-status non-Quick grounded synthesis")
PY

python3 -m py_compile eli/kernel/engine.py

echo
echo "=== inserted anchors ==="
grep -nE "STRICT_GROUNDED_SYNTH_V1|NONQUICK_STRICT_SYNTH_V1|strict grounded synthesis selected" eli/kernel/engine.py
