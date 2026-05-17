#!/usr/bin/env bash
set -euo pipefail

cd ~/Desktop/ELI_MKXI || exit 1
source .venv/bin/activate || true

STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="ops/reports/callable_chain_audit_${STAMP}"
mkdir -p "$OUT"
export ELI_CALLABLE_CHAIN_AUDIT_OUT="$OUT"

python3 - <<'PY'
from pathlib import Path
import inspect
import json
import os
import subprocess
import sys
import traceback

OUT = Path(os.environ["ELI_CALLABLE_CHAIN_AUDIT_OUT"])
FAILURES = []
WARNINGS = []

def write(name, text):
    p = OUT / name
    p.write_text(str(text), encoding="utf-8")
    return p

def git(*args):
    try:
        return subprocess.check_output(["git", *args], text=True, stderr=subprocess.STDOUT).strip()
    except Exception as e:
        return f"ERR: {e}"

def describe_callable(fn):
    try:
        file = inspect.getsourcefile(fn)
    except Exception:
        file = None
    try:
        line = fn.__code__.co_firstlineno
    except Exception:
        line = None
    return {
        "id": id(fn),
        "name": getattr(fn, "__name__", None),
        "qualname": getattr(fn, "__qualname__", None),
        "module": getattr(fn, "__module__", None),
        "file": file,
        "line": line,
        "marker_final_alias_sync": bool(getattr(fn, "_eli_final_alias_sync_v1", False)),
    }

def edge_candidates(fn):
    edges = []

    # 1. Closure callables.
    try:
        closure = getattr(fn, "__closure__", None) or ()
        freevars = getattr(getattr(fn, "__code__", None), "co_freevars", ()) or ()
        for idx, cell in enumerate(closure):
            try:
                val = cell.cell_contents
            except Exception:
                continue
            if callable(val):
                name = freevars[idx] if idx < len(freevars) else f"closure_{idx}"
                edges.append((f"closure:{name}", val))
    except Exception:
        pass

    # 2. Positional defaults.
    try:
        defaults = getattr(fn, "__defaults__", None) or ()
        for idx, val in enumerate(defaults):
            if callable(val):
                edges.append((f"default:{idx}", val))
    except Exception:
        pass

    # 3. Keyword-only defaults. This catches _prev=...
    try:
        kwdefaults = getattr(fn, "__kwdefaults__", None) or {}
        for name, val in kwdefaults.items():
            if callable(val):
                edges.append((f"kwdefault:{name}", val))
    except Exception:
        pass

    # 4. Referenced global previous/original callables.
    # This catches wrappers that call globals instead of default-bound _prev.
    try:
        code = getattr(fn, "__code__", None)
        globs = getattr(fn, "__globals__", {}) or {}
        names = getattr(code, "co_names", ()) or ()
        for name in names:
            up = str(name).upper()
            if not any(tok in up for tok in ("PREV", "ORIG", "ORIGINAL", "BASE", "DELEGATE")):
                continue
            val = globs.get(name)
            if callable(val):
                edges.append((f"global:{name}", val))
    except Exception:
        pass

    # De-duplicate by object id while preserving order.
    seen = set()
    clean = []
    for label, val in edges:
        key = id(val)
        if key in seen:
            continue
        seen.add(key)
        clean.append((label, val))
    return clean

def chain_tree(root, max_depth=32):
    rows = []
    seen_path = set()

    def walk(fn, depth, via):
        info = describe_callable(fn)
        info["depth"] = depth
        info["via"] = via
        rows.append(info)

        if depth >= max_depth:
            WARNINGS.append(f"max_depth reached at {info}")
            return

        key = id(fn)
        if key in seen_path:
            rows.append({
                "depth": depth + 1,
                "via": "cycle",
                "cycle_to_id": key,
            })
            return

        seen_path.add(key)
        edges = edge_candidates(fn)

        # Prefer obvious wrapper predecessors first.
        def score(edge):
            label = edge[0].upper()
            if "KWDEFAULT:_PREV" in label:
                return 0
            if "PREV" in label:
                return 1
            if "ORIG" in label or "ORIGINAL" in label:
                return 2
            return 9

        edges = sorted(edges, key=score)

        for label, nxt in edges[:12]:
            walk(nxt, depth + 1, label)

        if len(edges) > 12:
            WARNINGS.append(f"truncated {len(edges)-12} edges from {info}")

        seen_path.remove(key)

    walk(root, 1, "root")
    return rows

def smoke_route(router):
    questions = [
        ("memory_runtime_exact", "Explain exactly how your memory system works internally — which files, which DB tables, which functions.", "EXPLAIN_MEMORY_RUNTIME"),
        ("memory_runtime_plural", "What database files are your memories stored in, and what tables do they use?", "EXPLAIN_MEMORY_RUNTIME"),
        ("runtime_status", "What are you actually running on right now — model, context size, GPU layers?", "RUNTIME_STATUS"),
        ("personal_memory", "What do you know about me from memory?", "PERSONAL_MEMORY_SUMMARY"),
    ]
    rows = []
    for label, q, expected in questions:
        try:
            out = router.route(q)
            action = out.get("action") if isinstance(out, dict) else None
            ok = action == expected
            rows.append({"label": label, "question": q, "expected": expected, "action": action, "ok": ok, "route": out})
            if not ok:
                FAILURES.append(f"route {label}: expected {expected}, got {action}")
        except Exception as e:
            rows.append({"label": label, "error": repr(e), "traceback": traceback.format_exc()})
            FAILURES.append(f"route {label} crashed: {e}")
    return rows

def smoke_executor(ex):
    tests = [
        ("EXPLAIN_MEMORY_RUNTIME", {"question": "What database files are your memories stored in, and what tables do they use?"}),
        ("MEMORY_STATUS", {"question": "How many memories and conversation turns are currently stored?"}),
        ("RUNTIME_STATUS", {}),
    ]
    rows = []

    same = ex.execute is ex.execute_action
    marker = bool(getattr(ex.execute_action, "_eli_final_alias_sync_v1", False))
    if not same:
        FAILURES.append("execute_action is not the same object as execute")
    if not marker:
        FAILURES.append("execute_action missing _eli_final_alias_sync_v1 marker")

    rows.append({
        "execute_is_execute_action": same,
        "alias_marker": marker,
        "execute": describe_callable(ex.execute),
        "execute_action": describe_callable(ex.execute_action),
    })

    for action, args in tests:
        try:
            out = ex.execute_action(action, args)
            text = str(out.get("content") or out.get("response") or "") if isinstance(out, dict) else str(out)
            rows.append({
                "action": action,
                "ok": out.get("ok") if isinstance(out, dict) else None,
                "action_out": out.get("action") if isinstance(out, dict) else None,
                "source": out.get("source") if isinstance(out, dict) else None,
                "evidence_source": out.get("evidence_source") if isinstance(out, dict) else None,
                "head": text[:1400],
            })

            if action == "RUNTIME_STATUS" and isinstance(out, dict) and not out.get("evidence_source"):
                WARNINGS.append("RUNTIME_STATUS executor output has evidence_source=None. Not fatal, but should be normalised later.")
        except Exception as e:
            rows.append({"action": action, "error": repr(e), "traceback": traceback.format_exc()})
            FAILURES.append(f"executor {action} crashed: {e}")
    return rows

def main():
    write("00_git_state.txt", "\n".join([
        "=== git status ===",
        git("status", "-sb"),
        "",
        "=== HEAD ===",
        git("rev-parse", "HEAD"),
        "",
        "=== origin/main ===",
        git("rev-parse", "origin/main"),
        "",
        "=== latest commits ===",
        git("log", "--oneline", "--decorate", "-8"),
        "",
        "=== tags at HEAD ===",
        git("tag", "--points-at", "HEAD"),
    ]))

    import eli.execution.router_enhanced as router
    import eli.execution.executor_enhanced as ex
    import eli.kernel.engine as engine

    targets = {
        "router.route": router.route,
        "router.route_intent": getattr(router, "route_intent", None),
        "router.route_command": getattr(router, "route_command", None),
        "executor.execute": ex.execute,
        "executor.execute_action": ex.execute_action,
        "engine.CognitiveEngine.process": engine.CognitiveEngine.process,
    }

    chains = {}
    for name, fn in targets.items():
        if callable(fn):
            chains[name] = chain_tree(fn)
        else:
            chains[name] = [{"missing_or_not_callable": True, "repr": repr(fn)}]

    write("01_callable_chains.json", json.dumps(chains, indent=2, default=str))

    readable = []
    for name, rows in chains.items():
        readable.append(f"\n\n## {name}")
        for r in rows:
            if "cycle_to_id" in r:
                readable.append(f"{'  ' * r.get('depth', 1)}- CYCLE -> {r['cycle_to_id']} via {r.get('via')}")
                continue
            readable.append(
                f"{'  ' * (int(r.get('depth') or 1)-1)}"
                f"- depth={r.get('depth')} via={r.get('via')} "
                f"{r.get('module')}:{r.get('line')} {r.get('qualname')} "
                f"file={r.get('file')} marker_alias={r.get('marker_final_alias_sync')}"
            )
    write("02_callable_chains_readable.txt", "\n".join(readable).strip() + "\n")

    route_rows = smoke_route(router)
    exec_rows = smoke_executor(ex)

    write("03_route_smoke.json", json.dumps(route_rows, indent=2, default=str))
    write("04_executor_smoke.json", json.dumps(exec_rows, indent=2, default=str))
    write("05_failures.txt", "\n".join(FAILURES) if FAILURES else "NONE\n")
    write("06_warnings.txt", "\n".join(WARNINGS) if WARNINGS else "NONE\n")

    summary = []
    summary.append(f"Callable chain audit: {OUT}")
    summary.append("")
    summary.append("Git:")
    summary.append(git("status", "-sb"))
    summary.append(git("log", "--oneline", "--decorate", "-3"))
    summary.append("")
    summary.append("Critical checks:")
    summary.append(f"- execute is execute_action: {ex.execute is ex.execute_action}")
    summary.append(f"- execute_action alias marker: {bool(getattr(ex.execute_action, '_eli_final_alias_sync_v1', False))}")
    summary.append(f"- route smoke failures: {sum(1 for r in route_rows if not r.get('ok'))}")
    summary.append(f"- executor failures: {len([x for x in FAILURES if x.startswith('executor')])}")
    summary.append("")
    summary.append("Approx chain lengths:")
    for name, rows in chains.items():
        summary.append(f"- {name}: {len(rows)} nodes")
    summary.append("")
    summary.append("Warnings:")
    summary.append("\n".join(f"- {w}" for w in WARNINGS) if WARNINGS else "NONE")
    summary.append("")
    summary.append("Failures:")
    summary.append("\n".join(f"- {f}" for f in FAILURES) if FAILURES else "NONE")

    write("SUMMARY.txt", "\n".join(summary) + "\n")
    print("\n".join(summary))

    if FAILURES:
        sys.exit(1)

if __name__ == "__main__":
    main()
PY

echo
echo "Generated:"
find "$OUT" -maxdepth 1 -type f -printf '%p\n' | sort
