#!/usr/bin/env bash
set -euo pipefail

cd ~/Desktop/ELI_MKXI || exit 1
source .venv/bin/activate || true

STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="ops/reports/wrapper_stack_audit_${STAMP}"
mkdir -p "$OUT"

export ELI_WRAPPER_AUDIT_OUT="$OUT"

python3 - <<'PY'
from pathlib import Path
import ast
import json
import os
import re
import subprocess
import traceback

ROOT = Path(".")
OUT = Path(os.environ["ELI_WRAPPER_AUDIT_OUT"])
OUT.mkdir(parents=True, exist_ok=True)

TARGET_FILES = [
    Path("eli/execution/router_enhanced.py"),
    Path("eli/execution/executor_enhanced.py"),
    Path("eli/kernel/engine.py"),
    Path("eli/cognition/agent_bus.py"),
    Path("eli/runtime/deterministic_grounding_gate.py"),
    Path("eli/runtime/control_contracts.py"),
    Path("eli/contracts/runtime_status.py"),
]

CONTROL_ACTIONS = [
    "RUNTIME_STATUS",
    "EXPLAIN_MEMORY_RUNTIME",
    "MEMORY_STATUS",
    "EXPLAIN_COGNITION_RUNTIME",
    "PERSONAL_MEMORY_SUMMARY",
    "PERSONAL_MEMORY_DEEP_EXPLAIN",
    "USER_IDENTITY_SUMMARY",
    "SELF_REPORT",
    "GUI_RUNTIME_AUDIT",
    "RUNTIME_AUDIT",
    "IMPORT_AUDIT",
    "RESOLVE_RUNTIME_PATHS",
    "EXPLAIN_LAST_RESPONSE",
    "NAME_SOURCE_AUDIT",
    "ROUTING_FAULT_EXPLAIN",
]

REBIND_NAMES = {
    "route",
    "route_intent",
    "route_command",
    "execute",
    "execute_action",
    "process",
}

WRAPPER_NAME_RE = re.compile(
    r"(_ELI_|_PHASE|_PREV|_ORIG|ORIGINAL|WRAP|WRAPPED|LOCK|CONTRACT|GUARD|SANITIZER|STRICT|NO_RAW|V\d+)",
    re.I,
)

RISK_TERMS = [
    "CognitiveEngine.process",
    "_PREV_PROCESS",
    "_ORIG_PROCESS",
    "_PREV_ROUTE",
    "_ORIG_ROUTE",
    "_PREV_EXECUTE",
    "_ORIG_EXECUTE",
    "def route(",
    "def route_intent(",
    "def route_command(",
    "def execute(",
    "def execute_action(",
]


def run(cmd):
    return subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    ).stdout


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return f"<<READ_ERROR {exc!r}>>"


def write(name: str, text: str):
    target = OUT / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def node_target_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = node_target_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Subscript):
        return node_target_name(node.value)
    if isinstance(node, ast.Tuple):
        return ",".join(filter(None, (node_target_name(x) for x in node.elts)))
    return ""


git_state = []
git_state.append("=== git status ===")
git_state.append(run(["git", "status", "-sb"]).strip())
git_state.append("")
git_state.append("=== git head ===")
git_state.append(run(["git", "log", "--oneline", "--decorate", "-8"]).strip())
git_state.append("")
git_state.append("=== tags at HEAD ===")
git_state.append(run(["git", "tag", "--points-at", "HEAD"]).strip())
write("00_git_state.txt", "\n".join(git_state) + "\n")


rebinding_rows = []
function_rows = []
class_rows = []
parse_errors = []

for path in TARGET_FILES:
    src = read(path)
    if src.startswith("<<READ_ERROR"):
        parse_errors.append(f"{path}: {src}")
        continue

    try:
        tree = ast.parse(src, filename=str(path))
    except Exception as exc:
        parse_errors.append(f"{path}: AST_PARSE_ERROR {type(exc).__name__}: {exc}")
        continue

    lines = src.splitlines()

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name = node.name
            if WRAPPER_NAME_RE.search(name) or name in REBIND_NAMES:
                function_rows.append({
                    "file": str(path),
                    "line": node.lineno,
                    "end": getattr(node, "end_lineno", node.lineno),
                    "name": name,
                    "kind": type(node).__name__,
                })

        elif isinstance(node, ast.ClassDef):
            if "Memory" in node.name or "Agent" in node.name or "Engine" in node.name:
                class_rows.append({
                    "file": str(path),
                    "line": node.lineno,
                    "end": getattr(node, "end_lineno", node.lineno),
                    "name": node.name,
                })

        elif isinstance(node, ast.Assign):
            targets = [node_target_name(t) for t in node.targets]
            val = ast.unparse(node.value) if hasattr(ast, "unparse") else ""
            for target in targets:
                short = target.split(".")[-1]
                if short in REBIND_NAMES or "CognitiveEngine.process" in target or WRAPPER_NAME_RE.search(target):
                    rebinding_rows.append({
                        "file": str(path),
                        "line": node.lineno,
                        "target": target,
                        "value": val[:240],
                        "source": lines[node.lineno - 1].strip() if 0 < node.lineno <= len(lines) else "",
                    })

        elif isinstance(node, ast.AnnAssign):
            target = node_target_name(node.target)
            short = target.split(".")[-1]
            val = ast.unparse(node.value) if getattr(node, "value", None) is not None and hasattr(ast, "unparse") else ""
            if short in REBIND_NAMES or "CognitiveEngine.process" in target or WRAPPER_NAME_RE.search(target):
                rebinding_rows.append({
                    "file": str(path),
                    "line": node.lineno,
                    "target": target,
                    "value": val[:240],
                    "source": lines[node.lineno - 1].strip() if 0 < node.lineno <= len(lines) else "",
                })


rebinding_rows.sort(key=lambda r: (r["file"], r["line"], r["target"]))
function_rows.sort(key=lambda r: (r["file"], r["line"], r["name"]))
class_rows.sort(key=lambda r: (r["file"], r["line"], r["name"]))

write("01_rebinding_assignments.json", json.dumps(rebinding_rows, indent=2, ensure_ascii=False))
write(
    "01_rebinding_assignments.txt",
    "\n".join(
        f'{r["file"]}:{r["line"]}: {r["target"]} = {r["value"]}\n    {r["source"]}'
        for r in rebinding_rows
    ) + "\n"
)

write("02_wrapper_function_inventory.json", json.dumps(function_rows, indent=2, ensure_ascii=False))
write(
    "02_wrapper_function_inventory.txt",
    "\n".join(
        f'{r["file"]}:{r["line"]}-{r["end"]}: {r["kind"]} {r["name"]}'
        for r in function_rows
    ) + "\n"
)

write(
    "03_relevant_class_inventory.txt",
    "\n".join(
        f'{r["file"]}:{r["line"]}-{r["end"]}: class {r["name"]}'
        for r in class_rows
    ) + "\n"
)

if parse_errors:
    write("99_parse_errors.txt", "\n".join(parse_errors) + "\n")


action_lines = []
action_counts = {a: {} for a in CONTROL_ACTIONS}
risk_hits = []

for path in TARGET_FILES:
    src = read(path)
    lines = src.splitlines()

    for i, line in enumerate(lines, 1):
        for action in CONTROL_ACTIONS:
            if action in line:
                action_counts[action][str(path)] = action_counts[action].get(str(path), 0) + 1
                action_lines.append(f"{path}:{i}: {line.strip()}")

        for term in RISK_TERMS:
            if term in line:
                risk_hits.append(f"{path}:{i}: [{term}] {line.strip()}")

write("04_control_action_mentions.txt", "\n".join(action_lines) + "\n")

action_summary = []
for action, files in sorted(action_counts.items()):
    total = sum(files.values())
    if total:
        action_summary.append(f"{action}: total={total}")
        for file, count in sorted(files.items(), key=lambda kv: (-kv[1], kv[0])):
            action_summary.append(f"  {count:4d}  {file}")

write("05_control_action_density.txt", "\n".join(action_summary) + "\n")
write("06_wrapper_risk_hits.txt", "\n".join(risk_hits) + "\n")


dyn = []
dyn_failures = []


def closure_chain(fn, max_depth=25):
    out = []
    seen = set()
    cur = fn
    depth = 0

    while callable(cur) and id(cur) not in seen and depth < max_depth:
        seen.add(id(cur))
        depth += 1

        item = {
            "depth": depth,
            "name": getattr(cur, "__name__", ""),
            "qualname": getattr(cur, "__qualname__", ""),
            "module": getattr(cur, "__module__", ""),
            "file": getattr(getattr(cur, "__code__", None), "co_filename", ""),
            "line": getattr(getattr(cur, "__code__", None), "co_firstlineno", None),
            "closure_callables": [],
        }

        nxt = None
        closure = getattr(cur, "__closure__", None) or []

        for cell in closure:
            try:
                obj = cell.cell_contents
            except Exception:
                continue

            if callable(obj):
                desc = {
                    "name": getattr(obj, "__name__", ""),
                    "qualname": getattr(obj, "__qualname__", ""),
                    "module": getattr(obj, "__module__", ""),
                    "line": getattr(getattr(obj, "__code__", None), "co_firstlineno", None),
                }
                item["closure_callables"].append(desc)

                if getattr(obj, "__name__", "") in {
                    "route",
                    "route_intent",
                    "route_command",
                    "execute",
                    "execute_action",
                }:
                    if nxt is None:
                        nxt = obj

        out.append(item)
        cur = nxt

    return out


try:
    import eli.execution.router_enhanced as router

    dyn.append("=== router dynamic closure chains ===")
    for name in ("route", "route_intent", "route_command"):
        fn = getattr(router, name, None)
        dyn.append(f"\n## {name}")
        dyn.append(json.dumps(closure_chain(fn), indent=2, ensure_ascii=False, default=str))

    tests = [
        "Explain exactly how your memory system works internally — which files, which DB tables, which functions.",
        "What database files are your memories stored in, and what tables do they use?",
        "Run EXPLAIN_MEMORY_RUNTIME.",
        "What are you actually running on right now — model, context size, GPU layers?",
        "What do you know about me from memory?",
    ]

    dyn.append("\n=== router action tests ===")
    for q in tests:
        try:
            r = router.route(q)
            dyn.append(f"QUESTION: {q}")
            dyn.append(f"ROUTE: {json.dumps(r, ensure_ascii=False, default=str)}")

            expected = None
            low = q.lower()
            if "memory system" in low or "database files" in low or "explain_memory_runtime" in low:
                expected = "EXPLAIN_MEMORY_RUNTIME"
            if "running on right now" in low:
                expected = "RUNTIME_STATUS"

            if expected and str((r or {}).get("action")) != expected:
                dyn_failures.append(f"route expected {expected}, got {(r or {}).get('action')} for {q!r}")

        except Exception as exc:
            dyn_failures.append(f"router route failed for {q!r}: {type(exc).__name__}: {exc}")

except Exception as exc:
    dyn_failures.append(f"router import/probe failed: {type(exc).__name__}: {exc}")
    dyn.append(traceback.format_exc())


try:
    import eli.execution.executor_enhanced as executor

    dyn.append("\n=== executor dynamic closure chains ===")
    for name in ("execute", "execute_action"):
        fn = getattr(executor, name, None)
        dyn.append(f"\n## {name}")
        dyn.append(json.dumps(closure_chain(fn), indent=2, ensure_ascii=False, default=str))

    dyn.append("\n=== executor smoke tests ===")
    for action, args in [
        ("EXPLAIN_MEMORY_RUNTIME", {"question": "audit", "detail": "full"}),
        ("MEMORY_STATUS", {"question": "How many memories and conversation turns are currently stored?"}),
        ("RUNTIME_STATUS", {}),
    ]:
        try:
            out = executor.execute(action, args)
            text = str((out or {}).get("content") or (out or {}).get("response") or "")[:1600]
            dyn.append(f"\nACTION: {action}")
            dyn.append(f"OK: {(out or {}).get('ok')}")
            dyn.append(f"EVIDENCE_SOURCE: {(out or {}).get('evidence_source')}")
            dyn.append(f"HEAD:\n{text}")

            if action == "EXPLAIN_MEMORY_RUNTIME":
                required = [
                    "artifacts/db/user.sqlite3",
                    "artifacts/db/agent.sqlite3",
                    "memories",
                    "conversation_turns",
                    "recall_log",
                    "runtime_events",
                ]
                missing = [x for x in required if x not in text]
                if missing:
                    dyn_failures.append(f"executor EXPLAIN_MEMORY_RUNTIME missing {missing}")

        except Exception as exc:
            dyn_failures.append(f"executor {action} failed: {type(exc).__name__}: {exc}")

except Exception as exc:
    dyn_failures.append(f"executor import/probe failed: {type(exc).__name__}: {exc}")
    dyn.append(traceback.format_exc())


write("07_dynamic_router_executor_probe.txt", "\n".join(dyn) + "\n")
write("08_dynamic_failures.txt", "\n".join(dyn_failures) + ("\n" if dyn_failures else ""))


summary = []
summary.append(f"Wrapper stack audit: {OUT}")
summary.append("")
summary.append("Git:")
summary.append(run(["git", "status", "-sb"]).strip())
summary.append(run(["git", "log", "--oneline", "--decorate", "-1"]).strip())
summary.append("")
summary.append("Static counts:")
summary.append(f"- rebinding assignments: {len(rebinding_rows)}")
summary.append(f"- wrapper-like function defs: {len(function_rows)}")
summary.append(f"- relevant class defs: {len(class_rows)}")
summary.append(f"- risk-term hits: {len(risk_hits)}")
summary.append(f"- parse errors: {len(parse_errors)}")
summary.append("")
summary.append("Highest-density control actions:")
for line in action_summary[:30]:
    summary.append(line)
summary.append("")
summary.append("Dynamic failures:")
summary.append("NONE" if not dyn_failures else "\n".join(f"- {x}" for x in dyn_failures))
summary.append("")
summary.append("Generated files:")
for name in [
    "00_git_state.txt",
    "01_rebinding_assignments.txt",
    "02_wrapper_function_inventory.txt",
    "03_relevant_class_inventory.txt",
    "04_control_action_mentions.txt",
    "05_control_action_density.txt",
    "06_wrapper_risk_hits.txt",
    "07_dynamic_router_executor_probe.txt",
    "08_dynamic_failures.txt",
]:
    summary.append(f"- {OUT / name}")

write("SUMMARY.txt", "\n".join(summary) + "\n")
print("\n".join(summary))

if dyn_failures:
    raise SystemExit(1)
PY
