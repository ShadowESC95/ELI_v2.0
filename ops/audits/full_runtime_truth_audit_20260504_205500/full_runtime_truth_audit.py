from __future__ import annotations

from pathlib import Path
import ast
import importlib.util
import json
import os
import pickle
import platform
import py_compile
import re
import shutil
import sqlite3
import subprocess
import sys
import textwrap
import time
from collections import Counter, defaultdict

ROOT = Path.cwd()
OUT = Path(os.environ.get("ELI_AUDIT_DIR", "ops/audits/full_runtime_truth_audit_manual")).resolve()
OUT.mkdir(parents=True, exist_ok=True)

REPORT = []
JSON_OUT = {
    "root": str(ROOT),
    "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    "python": sys.executable,
    "platform": platform.platform(),
    "sections": {},
}

def line(s=""):
    print(s)
    REPORT.append(str(s))

def write_text(name: str, text: str):
    p = OUT / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", errors="replace")
    return p

def run_cmd(name, cmd, timeout=30):
    line(f"\n=== CMD: {name} ===")
    line(" ".join(map(str, cmd)))
    try:
        cp = subprocess.run(
            cmd,
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        text = ""
        text += f"RC={cp.returncode}\n"
        if cp.stdout:
            text += "\n--- STDOUT ---\n" + cp.stdout
        if cp.stderr:
            text += "\n--- STDERR ---\n" + cp.stderr
        line(text.rstrip())
        write_text(f"cmd/{name}.txt", text)
        JSON_OUT["sections"][f"cmd_{name}"] = {
            "rc": cp.returncode,
            "stdout_chars": len(cp.stdout or ""),
            "stderr_chars": len(cp.stderr or ""),
        }
        return cp
    except subprocess.TimeoutExpired as exc:
        text = f"TIMEOUT after {timeout}s\nstdout={exc.stdout}\nstderr={exc.stderr}"
        line(text)
        write_text(f"cmd/{name}.txt", text)
        JSON_OUT["sections"][f"cmd_{name}"] = {"timeout": timeout}
        return None
    except Exception as exc:
        text = f"ERROR: {type(exc).__name__}: {exc}"
        line(text)
        write_text(f"cmd/{name}.txt", text)
        JSON_OUT["sections"][f"cmd_{name}"] = {"error": text}
        return None

def py_files():
    roots = [ROOT / "eli", ROOT / "tests"]
    out = []
    for base in roots:
        if base.exists():
            out.extend(sorted(p for p in base.rglob("*.py") if ".venv" not in p.parts))
    return out

def rel(p: Path):
    try:
        return str(p.relative_to(ROOT))
    except Exception:
        return str(p)

line("=== FULL RUNTIME TRUTH AUDIT ===")
line(f"ROOT={ROOT}")
line(f"OUT={OUT}")
line(f"PYTHON={sys.executable}")
line(f"PLATFORM={platform.platform()}")

# ---------------------------------------------------------------------
# 1. Git and working tree truth.
# ---------------------------------------------------------------------
run_cmd("git_status_short", ["git", "status", "--short"], timeout=20)
run_cmd("git_branch_vv", ["git", "branch", "-vv"], timeout=20)
run_cmd("git_log_head", ["git", "log", "--oneline", "--decorate", "-8"], timeout=20)
run_cmd("git_diff_stat", ["git", "diff", "--stat"], timeout=20)
run_cmd("git_diff_name_status", ["git", "diff", "--name-status"], timeout=20)
run_cmd("git_ls_untracked", ["git", "ls-files", "--others", "--exclude-standard"], timeout=20)

# ---------------------------------------------------------------------
# 2. Compile truth.
# ---------------------------------------------------------------------
compile_errors = []
for p in py_files():
    try:
        py_compile.compile(str(p), doraise=True)
    except Exception as exc:
        compile_errors.append({"file": rel(p), "error": str(exc)})

line("\n=== PY_COMPILE SUMMARY ===")
line(f"FILES_CHECKED={len(py_files())}")
line(f"COMPILE_ERRORS={len(compile_errors)}")
for item in compile_errors[:80]:
    line(f"{item['file']}: {item['error']}")
write_text("compile_errors.json", json.dumps(compile_errors, indent=2))
JSON_OUT["sections"]["compile"] = {
    "files_checked": len(py_files()),
    "compile_errors": compile_errors,
}

run_cmd("compileall_eli_tests", [sys.executable, "-m", "compileall", "-q", "eli", "tests"], timeout=120)

# ---------------------------------------------------------------------
# 3. Static import audit.
# ---------------------------------------------------------------------
internal_imports = []
external_imports = []
parse_errors = []

for p in py_files():
    try:
        tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        parse_errors.append({"file": rel(p), "error": str(exc)})
        continue

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                top = name.split(".")[0]
                rec = {"file": rel(p), "line": node.lineno, "import": name}
                if top == "eli":
                    internal_imports.append(rec)
                else:
                    external_imports.append(rec)

        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            top = mod.split(".")[0] if mod else ""
            names = [a.name for a in node.names]
            rec = {"file": rel(p), "line": node.lineno, "from": mod, "names": names}
            if top == "eli":
                internal_imports.append(rec)
            elif mod:
                external_imports.append(rec)

missing_external = []
for imp in external_imports:
    mod = imp.get("import") or imp.get("from") or ""
    top = mod.split(".")[0]
    if not top:
        continue
    if importlib.util.find_spec(top) is None:
        missing_external.append(imp)

missing_internal = []
for imp in internal_imports:
    mod = imp.get("import") or imp.get("from") or ""
    if not mod.startswith("eli"):
        continue
    parts = mod.split(".")
    candidate_file = ROOT.joinpath(*parts).with_suffix(".py")
    candidate_pkg = ROOT.joinpath(*parts, "__init__.py")
    if not candidate_file.exists() and not candidate_pkg.exists():
        missing_internal.append(imp)

line("\n=== IMPORT AUDIT ===")
line(f"INTERNAL_IMPORTS={len(internal_imports)}")
line(f"MISSING_INTERNAL_IMPORT_TARGETS={len(missing_internal)}")
for x in missing_internal[:120]:
    line(f"{x}")
line(f"EXTERNAL_IMPORTS={len(external_imports)}")
line(f"MISSING_EXTERNAL_TOP_LEVEL={len(missing_external)}")
for x in missing_external[:120]:
    line(f"{x}")

write_text("missing_internal_imports.json", json.dumps(missing_internal, indent=2))
write_text("missing_external_imports.json", json.dumps(missing_external, indent=2))
JSON_OUT["sections"]["imports"] = {
    "missing_internal_count": len(missing_internal),
    "missing_external_count": len(missing_external),
    "missing_internal": missing_internal,
    "missing_external": missing_external,
}

# ---------------------------------------------------------------------
# 4. Selected runtime import probes in isolated subprocesses.
# ---------------------------------------------------------------------
selected_modules = [
    "eli.execution.router_enhanced",
    "eli.execution.executor_enhanced",
    "eli.execution.portable_intent_contract",
    "eli.system.portable_app_control",
    "eli.kernel.engine",
    "eli.cognition.gguf_inference",
    "eli.cognition.context_synthesiser",
    "eli.memory.vector_store",
    "eli.gui.labs_tab",
    "eli.gui.eli_pro_audio_gui_MKI",
]

import_probe_results = []
for mod in selected_modules:
    cp = run_cmd(
        "import_" + mod.replace(".", "_"),
        [sys.executable, "-c", f"import {mod}; print('IMPORT_OK {mod}')"],
        timeout=25,
    )
    import_probe_results.append({
        "module": mod,
        "rc": None if cp is None else cp.returncode,
    })
JSON_OUT["sections"]["selected_imports"] = import_probe_results

# ---------------------------------------------------------------------
# 5. Duplicate definitions, wrappers, monkey patches, and suspicious hooks.
# ---------------------------------------------------------------------
defs_by_file = defaultdict(list)
defs_global = defaultdict(list)
assign_hooks = []
wrapper_markers = []

for p in py_files():
    text = p.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    try:
        tree = ast.parse(text)
    except Exception:
        continue

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            kind = "class" if isinstance(node, ast.ClassDef) else "def"
            rec = {"file": rel(p), "line": node.lineno, "kind": kind, "name": node.name}
            defs_by_file[rel(p)].append(rec)
            defs_global[node.name].append(rec)

    for i, l in enumerate(lines, start=1):
        low = l.lower()
        if any(s in low for s in [
            "phase_", "contract", "portable_runtime", "schema_guard",
            "_orig_", "wrapped", "monkey", "override", "fallback path",
            "compatibility", "shim",
        ]):
            wrapper_markers.append({"file": rel(p), "line": i, "text": l[:220]})

        if re.search(r"^\s*(route|execute|execute_action|chat|generate)\s*=", l):
            assign_hooks.append({"file": rel(p), "line": i, "text": l[:220]})

duplicate_defs_same_file = []
for f, defs in defs_by_file.items():
    c = Counter((d["kind"], d["name"]) for d in defs)
    for (kind, name), n in c.items():
        if n > 1:
            duplicate_defs_same_file.append({
                "file": f,
                "kind": kind,
                "name": name,
                "count": n,
                "lines": [d["line"] for d in defs if d["kind"] == kind and d["name"] == name],
            })

critical_names = [
    "route",
    "execute",
    "execute_action",
    "process",
    "generate",
    "_engine_ask",
    "build_persona_handoff",
    "build_memory_context",
    "get_engine",
]
critical_defs = {name: defs_global.get(name, []) for name in critical_names}

line("\n=== DUPLICATE / WRAPPER AUDIT ===")
line(f"DUPLICATE_DEFS_SAME_FILE={len(duplicate_defs_same_file)}")
for x in duplicate_defs_same_file[:120]:
    line(str(x))
line(f"ASSIGN_HOOKS={len(assign_hooks)}")
for x in assign_hooks[:120]:
    line(str(x))
line(f"WRAPPER_MARKERS={len(wrapper_markers)}")
for x in wrapper_markers[:160]:
    line(str(x))
line("CRITICAL_DEF_LOCATIONS:")
for name, items in critical_defs.items():
    line(f"{name}: {len(items)}")
    for item in items[:40]:
        line(f"  {item}")

write_text("duplicate_defs_same_file.json", json.dumps(duplicate_defs_same_file, indent=2))
write_text("assign_hooks.json", json.dumps(assign_hooks, indent=2))
write_text("wrapper_markers.json", json.dumps(wrapper_markers, indent=2))
write_text("critical_def_locations.json", json.dumps(critical_defs, indent=2))
JSON_OUT["sections"]["duplicates_wrappers"] = {
    "duplicate_defs_same_file_count": len(duplicate_defs_same_file),
    "assign_hooks_count": len(assign_hooks),
    "wrapper_markers_count": len(wrapper_markers),
    "critical_defs": critical_defs,
}

# ---------------------------------------------------------------------
# 6. Hardcoded paths, app-specific routing, templates, stubs, generated text.
# ---------------------------------------------------------------------
scan_patterns = {
    "absolute_user_paths": r"(/home/[A-Za-z0-9._-]+|/Users/[A-Za-z0-9._-]+|C:\\Users\\|Desktop/ELI_MKXI|jay@|/mnt/[A-Za-z0-9._-]+)",
    "target_app_names": r"\b(spotify|youtube|netflix|primevideo|prime video|soundcloud|firefox|chrome|gnome-control-center|wmctrl|xdotool|osascript|powershell|cmd\.exe)\b",
    "stubs_templates_placeholders": r"\b(TODO|FIXME|stub|placeholder|template|not implemented|dummy|fake|mock|hardcoded|This is a generated text document)\b",
    "dangerous_silent_except": r"except Exception:\s*(?:pass)?$",
    "broad_pass": r"^\s*pass\s*(?:#.*)?$",
}

scan_hits = {k: [] for k in scan_patterns}
for p in py_files():
    text = p.read_text(encoding="utf-8", errors="replace")
    for i, l in enumerate(text.splitlines(), start=1):
        for name, pat in scan_patterns.items():
            if re.search(pat, l, re.IGNORECASE):
                scan_hits[name].append({"file": rel(p), "line": i, "text": l[:260]})

line("\n=== HARDCODE / STUB / SILENT FAILURE SCAN ===")
for name, hits in scan_hits.items():
    line(f"{name}: {len(hits)}")
    for h in hits[:160]:
        line(str(h))
    write_text(f"scan_{name}.json", json.dumps(hits, indent=2))

JSON_OUT["sections"]["scan_hits"] = {k: len(v) for k, v in scan_hits.items()}

# ---------------------------------------------------------------------
# 7. Runtime snapshot, config, env truth.
# ---------------------------------------------------------------------
runtime_files = [
    ROOT / "artifacts/runtime_snapshot.json",
    ROOT / "config/settings.json",
    ROOT / ".env.mkxi",
    ROOT / ".env",
]
runtime_truth = {}

for p in runtime_files:
    if not p.exists():
        runtime_truth[rel(p)] = {"exists": False}
        continue

    raw = p.read_text(encoding="utf-8", errors="replace")
    info = {"exists": True, "size": len(raw)}
    if p.suffix == ".json":
        try:
            info["json"] = json.loads(raw)
        except Exception as exc:
            info["json_error"] = str(exc)
    else:
        interesting = []
        for l in raw.splitlines():
            if re.search(r"(CTX|N_CTX|GPU|LAYERS|THREAD|BATCH|MODEL|GGUF|RUNTIME)", l, re.I):
                interesting.append(l)
        info["interesting_lines"] = interesting
    runtime_truth[rel(p)] = info

line("\n=== RUNTIME SNAPSHOT / CONFIG TRUTH ===")
for k, v in runtime_truth.items():
    line(f"{k}: {json.dumps(v, indent=2)[:3000]}")

write_text("runtime_truth.json", json.dumps(runtime_truth, indent=2))
JSON_OUT["sections"]["runtime_truth"] = runtime_truth

# ---------------------------------------------------------------------
# 8. Memory DB and vector store truth.
# ---------------------------------------------------------------------
db_report = {}
for db_path in [ROOT / "artifacts/db/user.sqlite3", ROOT / "artifacts/db/agent.sqlite3"]:
    key = rel(db_path)
    info = {"exists": db_path.exists()}
    if db_path.exists():
        try:
            con = sqlite3.connect(str(db_path))
            cur = con.cursor()
            tables = [r[0] for r in cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()]
            info["tables"] = tables
            info["counts"] = {}
            for t in tables:
                try:
                    info["counts"][t] = cur.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                except Exception as exc:
                    info["counts"][t] = f"ERROR: {exc}"
            con.close()
        except Exception as exc:
            info["error"] = str(exc)
    db_report[key] = info

vector_report = {}
vector_paths = [
    ROOT / "artifacts/vectors/index.faiss",
    ROOT / "artifacts/vectors/meta.pkl",
]
for p in vector_paths:
    vector_report[rel(p)] = {"exists": p.exists(), "size": p.stat().st_size if p.exists() else 0}

meta = ROOT / "artifacts/vectors/meta.pkl"
if meta.exists():
    try:
        with meta.open("rb") as f:
            obj = pickle.load(f)
        vector_report[rel(meta)]["type"] = type(obj).__name__
        try:
            vector_report[rel(meta)]["len"] = len(obj)
        except Exception:
            pass
        if isinstance(obj, dict):
            vector_report[rel(meta)]["keys"] = list(obj.keys())[:30]
    except Exception as exc:
        vector_report[rel(meta)]["pickle_error"] = str(exc)

try:
    import faiss
    idx_path = ROOT / "artifacts/vectors/index.faiss"
    if idx_path.exists():
        idx = faiss.read_index(str(idx_path))
        vector_report[rel(idx_path)]["faiss_ntotal"] = int(idx.ntotal)
        vector_report[rel(idx_path)]["faiss_d"] = int(idx.d)
except Exception as exc:
    vector_report["faiss_probe_error"] = str(exc)

line("\n=== MEMORY DB / VECTOR TRUTH ===")
line(json.dumps(db_report, indent=2)[:12000])
line(json.dumps(vector_report, indent=2)[:4000])
write_text("memory_db_report.json", json.dumps(db_report, indent=2))
write_text("vector_store_report.json", json.dumps(vector_report, indent=2))
JSON_OUT["sections"]["memory"] = {"db_report": db_report, "vector_report": vector_report}

# ---------------------------------------------------------------------
# 9. Router truth matrix.
# ---------------------------------------------------------------------
route_inputs = [
    "who are you and what are you actually running on right now model context size gpu layers everything",
    "what is your confidence in your last response and which agents contributed to it",
    "how many memories do you have what do you know about me from memory give me everything",
    "explain exactly how your memory system works internally which files which db tables which functions",
    "what imports are failing or missing right now",
    "why did your last response cut off incomplete",
    "open firefox",
    "open settings",
    "closed settings",
    "close spotify",
    "minimize spotify",
    "minimize terminal",
    "volume 90%",
    "generate a python script to determine redshift from a supernova spectrum",
    "generate a rust program to parse log files",
    "write a c++ module for matrix multiplication",
]

route_results = []
try:
    from eli.execution.router_enhanced import route
    for q in route_inputs:
        try:
            r = route(q)
            route_results.append({"input": q, "result": r})
        except Exception as exc:
            route_results.append({"input": q, "error": str(exc)})
except Exception as exc:
    route_results.append({"router_import_error": str(exc)})

line("\n=== ROUTER MATRIX ===")
for r in route_results:
    line(json.dumps(r, indent=2, default=str))
write_text("router_matrix.json", json.dumps(route_results, indent=2, default=str))
JSON_OUT["sections"]["router_matrix"] = route_results

# ---------------------------------------------------------------------
# 10. Engine/action mismatch targeted static scan.
# ---------------------------------------------------------------------
target_files = [
    ROOT / "eli/kernel/engine.py",
    ROOT / "eli/cognition/context_synthesiser.py",
    ROOT / "eli/execution/router_enhanced.py",
    ROOT / "eli/execution/executor_enhanced.py",
]
target_terms = [
    "EXPLAIN_MEMORY_RUNTIME",
    "EXPLAIN_LAST_RESPONSE",
    "SELF_REPORT",
    "USER_IDENTITY_SUMMARY",
    "EXPLAIN_COGNITION_RUNTIME",
    "allow_chat_without_evidence",
    "Generating response with GGUF",
    "Using broker path",
    "max_tokens=128",
    "max_tokens",
    "confidence",
    "agents_used",
    "files_scanned",
]
target_scan = []
for p in target_files:
    if not p.exists():
        continue
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    for i, l in enumerate(lines, start=1):
        if any(t in l for t in target_terms):
            target_scan.append({"file": rel(p), "line": i, "text": l[:300]})

line("\n=== TARGETED ENGINE/ACTION SCAN ===")
for x in target_scan[:300]:
    line(str(x))
write_text("targeted_engine_action_scan.json", json.dumps(target_scan, indent=2))
JSON_OUT["sections"]["targeted_engine_action_scan_count"] = len(target_scan)

# ---------------------------------------------------------------------
# 11. Package dependency truth.
# ---------------------------------------------------------------------
run_cmd("pip_check", [sys.executable, "-m", "pip", "check"], timeout=60)

# ---------------------------------------------------------------------
# 12. Summary markdown.
# ---------------------------------------------------------------------
summary = f"""# ELI Full Runtime Truth Audit

Generated: {JSON_OUT["time"]}

## Immediate truth flags

- Compile errors: {len(compile_errors)}
- Missing internal import targets: {len(missing_internal)}
- Missing external top-level imports: {len(missing_external)}
- Duplicate definitions within same file: {len(duplicate_defs_same_file)}
- Assignment hooks / wrapper-style route-execute overrides: {len(assign_hooks)}
- Wrapper/contract/compatibility markers: {len(wrapper_markers)}
- Absolute/user path hits: {len(scan_hits["absolute_user_paths"])}
- Target-app hardcode hits: {len(scan_hits["target_app_names"])}
- Stub/template/placeholder hits: {len(scan_hits["stubs_templates_placeholders"])}
- Silent broad except hits: {len(scan_hits["dangerous_silent_except"])}

## Main files to inspect first

1. `eli/kernel/engine.py`
2. `eli/execution/router_enhanced.py`
3. `eli/execution/executor_enhanced.py`
4. `eli/execution/portable_intent_contract.py`
5. `eli/system/portable_app_control.py`
6. `eli/cognition/context_synthesiser.py`
7. `eli/cognition/gguf_inference.py`
8. `eli/gui/eli_pro_audio_gui_MKI.py`
9. `eli/gui/labs_tab.py`

## Why ELI gave inconsistent answers

1. Runtime self-report appears to read requested/preloaded settings rather than effective loaded llama runtime.
2. Grounded diagnostic routes still fall through to GGUF generation.
3. Agent confidence is being reported as answer confidence.
4. Some agent contributions are named even when evidence says `files_scanned=0` or no snippets.
5. Memory count questions are not using direct SQLite/vector counts.
6. Long introspection answers are capped/truncated by small `max_tokens`.
7. Router action and agentbus action may diverge for memory/introspection routes.
8. Direct-execution commands and cognitive response generation are not cleanly separated.

## Output files

- `compile_errors.json`
- `missing_internal_imports.json`
- `missing_external_imports.json`
- `duplicate_defs_same_file.json`
- `assign_hooks.json`
- `wrapper_markers.json`
- `runtime_truth.json`
- `memory_db_report.json`
- `vector_store_report.json`
- `router_matrix.json`
- `targeted_engine_action_scan.json`
- `full_runtime_truth_audit.json`
"""
write_text("AUDIT_SUMMARY.md", summary)
JSON_OUT["summary"] = summary

write_text("full_runtime_truth_audit.json", json.dumps(JSON_OUT, indent=2, default=str))
write_text("FULL_AUDIT_REPORT.txt", "\n".join(REPORT))

line("\n=== AUDIT OUTPUTS ===")
line(str(OUT))
for name in [
    "AUDIT_SUMMARY.md",
    "FULL_AUDIT_REPORT.txt",
    "full_runtime_truth_audit.json",
    "compile_errors.json",
    "missing_internal_imports.json",
    "missing_external_imports.json",
    "duplicate_defs_same_file.json",
    "assign_hooks.json",
    "wrapper_markers.json",
    "runtime_truth.json",
    "memory_db_report.json",
    "vector_store_report.json",
    "router_matrix.json",
    "targeted_engine_action_scan.json",
]:
    p = OUT / name
    line(f"{name}: exists={p.exists()} size={p.stat().st_size if p.exists() else 0}")
