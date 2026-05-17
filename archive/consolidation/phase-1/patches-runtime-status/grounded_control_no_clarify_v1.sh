#!/usr/bin/env bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

mkdir -p eli/contracts ops/reports

cat > eli/contracts/grounded_control.py <<'PY'
"""
Grounded-control synthesis guard for ELI.

Purpose:
- Prevent final-loop clarification fallback when a routed grounded/control action
  already has complete executor evidence.
- Preserve normal non-Quick synthesis: this guard does not bypass the first
  synthesis attempt.
- It only blocks the later "ask the user to clarify" fallback when evidence is
  already complete.
"""

from __future__ import annotations

from typing import Any, Mapping
import re


GROUNDED_CONTROL_ACTIONS = {
    "RUNTIME_STATUS",
    "MEMORY_COUNT",
    "MEMORY_STATUS",
    "MEMORY_RECALL",
    "GUI_RUNTIME_AUDIT",
    "EXPLAIN_MEMORY_RUNTIME",
    "EXPLAIN_LAST_RESPONSE",
    "SELF_REPORT",
}


RUNTIME_STATUS_REQUIRED_TERMS = (
    "provider",
    "model_name",
    "model_path",
    "context_size",
    "gpu_layers",
    "batch_size",
    "cpu_threads",
    "max_tokens",
    "temperature",
    "use_mmap",
    "use_mlock",
)


BAD_CLARIFY_PATTERNS = (
    "what specific details",
    "what specific aspects",
    "could you please clarify",
    "please clarify",
    "what do you need to know specifically",
    "model, context size, gpu layers",
)


def _safe_str(value: Any, *, limit: int = 6000) -> str:
    try:
        if value is None:
            return ""
        if isinstance(value, str):
            return value[:limit]
        return repr(value)[:limit]
    except Exception:
        return ""


def _collect_text(value: Any, *, limit: int = 50000, depth: int = 0) -> str:
    if value is None or depth > 5 or limit <= 0:
        return ""

    if isinstance(value, str):
        return value[:limit]

    if isinstance(value, Mapping):
        parts: list[str] = []
        for key, val in value.items():
            if len("\n".join(parts)) >= limit:
                break
            k = _safe_str(key, limit=200)
            if k:
                parts.append(k)
            parts.append(_collect_text(val, limit=max(1000, limit // 4), depth=depth + 1))
        return "\n".join(p for p in parts if p)[:limit]

    if isinstance(value, (list, tuple, set)):
        parts = []
        for item in value:
            if len("\n".join(parts)) >= limit:
                break
            parts.append(_collect_text(item, limit=max(1000, limit // 4), depth=depth + 1))
        return "\n".join(p for p in parts if p)[:limit]

    return _safe_str(value, limit=limit)


def _lookup_action(local_vars: Mapping[str, Any]) -> str:
    direct_names = (
        "action",
        "final_action",
        "route_action",
        "control_action",
        "intent_action",
        "routed_action",
    )

    for name in direct_names:
        value = local_vars.get(name)
        if value:
            return str(value).strip().upper()

    container_names = (
        "route",
        "router_result",
        "parsed",
        "intent",
        "agent_result",
        "bus_result",
        "result",
        "executor_result",
        "control",
    )

    for name in container_names:
        value = local_vars.get(name)
        if isinstance(value, Mapping):
            for key in ("action", "final_action", "routed_action"):
                if value.get(key):
                    return str(value.get(key)).strip().upper()

    blob = _collect_text(local_vars, limit=20000).upper()
    for action in GROUNDED_CONTROL_ACTIONS:
        if action in blob:
            return action

    return ""


def _looks_like_runtime_status_complete(text: str) -> bool:
    low = text.lower()

    # Accept either structured contract terms or executor/report terms.
    hits = sum(1 for term in RUNTIME_STATUS_REQUIRED_TERMS if term.lower() in low)

    has_model = "qwen" in low or ".gguf" in low or "model_name" in low or "model path" in low
    has_ctx = "context_size" in low or "context size" in low or "n_ctx" in low
    has_gpu = "gpu_layers" in low or "gpu layers" in low or "n_gpu_layers" in low
    has_batch = "batch_size" in low or "batch size" in low or "n_batch" in low
    has_threads = "cpu_threads" in low or "cpu threads" in low or "n_threads" in low

    return hits >= 7 or (has_model and has_ctx and has_gpu and has_batch and has_threads)


def _looks_like_memory_count_complete(text: str) -> bool:
    low = text.lower()
    return (
        ("memory" in low or "memories" in low)
        and any(x in low for x in ("count", "total", "rows", "records"))
        and any(ch.isdigit() for ch in low)
    )


def evidence_complete_for_action(action: str, local_vars: Mapping[str, Any]) -> bool:
    action = str(action or "").strip().upper()
    if action not in GROUNDED_CONTROL_ACTIONS:
        return False

    text = _collect_text(local_vars, limit=70000)

    if action == "RUNTIME_STATUS":
        return _looks_like_runtime_status_complete(text)

    if action in {"MEMORY_COUNT", "MEMORY_STATUS"}:
        return _looks_like_memory_count_complete(text)

    # Conservative generic rule for other grounded controls:
    # only suppress clarification when the executor returned ok evidence/content.
    low = text.lower()
    return (
        "ok" in low
        and any(x in low for x in ("content", "response", "report", "evidence"))
        and not any(x in low for x in ("traceback", "exception", "error:"))
    )


def should_suppress_clarification(local_vars: Mapping[str, Any]) -> bool:
    """
    Called from the final synthesis confidence branch.

    Return True only when:
    - the routed action is grounded/control;
    - evidence is already complete;
    - therefore asking the user to clarify would be wrong.
    """
    if not isinstance(local_vars, Mapping):
        return False

    action = _lookup_action(local_vars)
    if action not in GROUNDED_CONTROL_ACTIONS:
        return False

    return evidence_complete_for_action(action, local_vars)


def looks_like_bad_clarification(text: str) -> bool:
    low = str(text or "").lower().strip()
    if not low:
        return False
    if not low.endswith("?"):
        return False
    return any(pattern in low for pattern in BAD_CLARIFY_PATTERNS)
PY

python3 - <<'PY'
from pathlib import Path
import re

p = Path("eli/kernel/engine.py")
src = p.read_text(encoding="utf-8")

import_line = "from eli.contracts.grounded_control import should_suppress_clarification as _eli_grounded_control_no_clarify_v1\n"

if import_line not in src:
    marker = "from eli.cognition.context_synthesiser import build_persona_handoff\n"
    if marker not in src:
        raise SystemExit("Could not find import insertion marker in eli/kernel/engine.py")
    src = src.replace(marker, marker + import_line, 1)

if "grounded-control no-clarify v1" in src:
    p.write_text(src, encoding="utf-8")
    print("grounded-control no-clarify v1 already installed")
    raise SystemExit(0)

lines = src.splitlines()
target_index = None
score_var = None
threshold_var = None

for i, line in enumerate(lines):
    if "[COGNITIVE][FINAL] confidence" in line and "score=" in line and "threshold=" in line:
        target_index = i

        score_match = re.search(r"score=\{([A-Za-z_][A-Za-z0-9_]*)", line)
        threshold_match = re.search(r"threshold=\{([A-Za-z_][A-Za-z0-9_]*)", line)

        if score_match:
            score_var = score_match.group(1)
        if threshold_match:
            threshold_var = threshold_match.group(1)

        break

if target_index is None:
    print("Could not find confidence print line. Nearby FINAL lines:")
    for n, line in enumerate(lines, 1):
        if "[COGNITIVE][FINAL]" in line:
            print(f"{n}: {line}")
    raise SystemExit(1)

if not score_var or not threshold_var:
    print("Could not infer score/threshold variable names from:")
    print(lines[target_index])
    raise SystemExit(1)

indent = re.match(r"^(\s*)", lines[target_index]).group(1)

insert = [
    f"{indent}if _eli_grounded_control_no_clarify_v1(locals()):",
    f"{indent}    {score_var} = max({score_var}, {threshold_var})",
    f"{indent}    print(\"[COGNITIVE][FINAL] grounded-control no-clarify v1: complete evidence; clarification fallback suppressed\", flush=True)",
]

lines[target_index + 1:target_index + 1] = insert
new_src = "\n".join(lines) + "\n"
p.write_text(new_src, encoding="utf-8")

print("Patched eli/kernel/engine.py")
print("Inserted after line:", target_index + 1)
print("score_var:", score_var)
print("threshold_var:", threshold_var)
PY

python3 -m py_compile \
  eli/contracts/grounded_control.py \
  eli/kernel/engine.py

PYTHONPATH="$PWD" python3 - <<'PY'
from eli.contracts.grounded_control import should_suppress_clarification, looks_like_bad_clarification

fake_locals = {
    "action": "RUNTIME_STATUS",
    "context": """
Runtime status evidence:
- provider: gguf
- model_name: qwen2.5-3b-instruct-q4_k_m.gguf
- model_path: /home/jay/Desktop/ELI_MKXI/models/qwen2.5-3b-instruct-q4_k_m.gguf
- context_size: 32768
- gpu_layers: 21
- batch_size: 512
- cpu_threads: 4
- max_tokens: 512
- temperature: 0.7
- use_mmap: True
- use_mlock: True
""",
}
assert should_suppress_clarification(fake_locals), "runtime-status complete evidence was not detected"
assert looks_like_bad_clarification("What specific details are you looking for regarding the model, context size, GPU layers?"), "bad clarification detector failed"
assert not should_suppress_clarification({"action": "CHAT", "context": fake_locals["context"]}), "non-control chat was incorrectly suppressed"
print("grounded_control_no_clarify_v1 self-test PASS")
PY
