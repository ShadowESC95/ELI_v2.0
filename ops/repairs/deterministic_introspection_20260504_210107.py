from pathlib import Path
import ast
import json
import py_compile
import re
import shutil
import textwrap
import time
import traceback

ROOT = Path.cwd()
STAMP = time.strftime("%Y%m%d_%H%M%S")
BACKUP = ROOT / "ops" / "backups" / f"{STAMP}.deterministic_introspection"
BACKUP.mkdir(parents=True, exist_ok=True)

TARGETS = [
    ROOT / "eli/kernel/engine.py",
    ROOT / "eli/runtime/__init__.py",
    ROOT / "eli/runtime/truth_report.py",
    ROOT / "eli/runtime/deterministic_introspection.py",
    ROOT / "eli/memory/memory_truth.py",
]

def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except Exception:
        return str(path)

def backup(path: Path) -> None:
    if path.exists():
        dst = BACKUP / path.relative_to(ROOT)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dst)
        print(f"BACKUP {rel(path)} -> {dst}")
    else:
        print(f"NEW_FILE {rel(path)}")

def write_if_changed(path: Path, text: str) -> None:
    old = path.read_text(encoding="utf-8", errors="replace") if path.exists() else None
    if old != text:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"PATCHED {rel(path)}")
    else:
        print(f"UNCHANGED {rel(path)}")

def compile_one(path: Path) -> bool:
    try:
        py_compile.compile(str(path), doraise=True)
        print(f"COMPILE_OK {rel(path)}")
        return True
    except Exception as exc:
        print(f"COMPILE_BAD {rel(path)}: {exc}")
        return False

for p in TARGETS:
    backup(p)

# ---------------------------------------------------------------------
# eli/runtime/__init__.py
# ---------------------------------------------------------------------
runtime_init = ROOT / "eli/runtime/__init__.py"
if not runtime_init.exists():
    write_if_changed(runtime_init, '"""Runtime inspection and control helpers for ELI."""\n')

# ---------------------------------------------------------------------
# eli/memory/memory_truth.py
# ---------------------------------------------------------------------
memory_truth = r'''
from __future__ import annotations

import json
import pickle
import sqlite3
from pathlib import Path
from typing import Any, Dict


def _project_root() -> Path:
    try:
        from eli.core.paths import project_root
        value = project_root() if callable(project_root) else project_root
        return Path(value).expanduser().resolve()
    except Exception:
        return Path(__file__).resolve().parents[2]


def _artifact_path(*parts: str) -> Path:
    root = _project_root()
    try:
        from eli.core import paths as _paths
        for fn_name in ("get_paths", "get_project_paths"):
            fn = getattr(_paths, fn_name, None)
            if callable(fn):
                obj = fn()
                val = getattr(obj, "artifacts_dir", None)
                if val:
                    return Path(val).expanduser().resolve().joinpath(*parts)
        val = getattr(_paths, "ARTIFACTS_DIR", None)
        if val:
            return Path(val).expanduser().resolve().joinpath(*parts)
    except Exception:
        pass
    return root.joinpath("artifacts", *parts)


def _count_table(cur: sqlite3.Cursor, table: str) -> int | None:
    try:
        safe = '"' + table.replace('"', '""') + '"'
        row = cur.execute(f"SELECT COUNT(*) FROM {safe}").fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return None


def inspect_sqlite(path: Path) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "tables": [],
        "counts": {},
        "errors": [],
    }
    if not path.exists():
        return out

    try:
        con = sqlite3.connect(str(path))
        cur = con.cursor()
        tables = [
            str(r[0])
            for r in cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        ]
        out["tables"] = tables
        for table in tables:
            out["counts"][table] = _count_table(cur, table)
        con.close()
    except Exception as exc:
        out["errors"].append(type(exc).__name__ + ": " + str(exc))
    return out


def inspect_vector_store() -> Dict[str, Any]:
    index_path = _artifact_path("vectors", "index.faiss")
    meta_path = _artifact_path("vectors", "meta.pkl")
    out: Dict[str, Any] = {
        "index_path": str(index_path),
        "index_exists": index_path.exists(),
        "index_size": index_path.stat().st_size if index_path.exists() else 0,
        "faiss_ntotal": None,
        "faiss_d": None,
        "meta_path": str(meta_path),
        "meta_exists": meta_path.exists(),
        "meta_size": meta_path.stat().st_size if meta_path.exists() else 0,
        "meta_type": None,
        "meta_len": None,
        "errors": [],
    }

    if index_path.exists():
        try:
            import faiss  # type: ignore
            index = faiss.read_index(str(index_path))
            out["faiss_ntotal"] = int(getattr(index, "ntotal", -1))
            out["faiss_d"] = int(getattr(index, "d", -1))
        except Exception as exc:
            out["errors"].append("faiss: " + type(exc).__name__ + ": " + str(exc))

    if meta_path.exists():
        try:
            with meta_path.open("rb") as f:
                meta = pickle.load(f)
            out["meta_type"] = type(meta).__name__
            try:
                out["meta_len"] = len(meta)
            except Exception:
                out["meta_len"] = None
        except Exception as exc:
            out["errors"].append("meta: " + type(exc).__name__ + ": " + str(exc))

    return out


def memory_truth_report() -> Dict[str, Any]:
    user_db = _artifact_path("db", "user.sqlite3")
    agent_db = _artifact_path("db", "agent.sqlite3")
    user = inspect_sqlite(user_db)
    agent = inspect_sqlite(agent_db)
    vectors = inspect_vector_store()

    user_counts = user.get("counts", {}) if isinstance(user.get("counts"), dict) else {}
    agent_counts = agent.get("counts", {}) if isinstance(agent.get("counts"), dict) else {}

    summary = {
        "user_memories": int(user_counts.get("memories") or 0),
        "user_memory_fts": int(user_counts.get("memories_fts") or 0),
        "user_conversation_turns": int(user_counts.get("conversation_turns") or 0),
        "user_conversations": int(user_counts.get("conversations") or 0),
        "user_observations": int(user_counts.get("observations") or 0),
        "user_recall_log": int(user_counts.get("recall_log") or 0),
        "agent_memories": int(agent_counts.get("memories") or 0),
        "agent_observations": int(agent_counts.get("observations") or 0),
        "vector_ntotal": vectors.get("faiss_ntotal"),
        "vector_dim": vectors.get("faiss_d"),
        "vector_meta_len": vectors.get("meta_len"),
    }

    return {
        "summary": summary,
        "databases": {
            "user": user,
            "agent": agent,
        },
        "vectors": vectors,
    }


def format_memory_truth(report: Dict[str, Any] | None = None) -> str:
    report = report or memory_truth_report()
    s = report.get("summary", {})
    dbs = report.get("databases", {})
    vectors = report.get("vectors", {})

    lines = []
    lines.append("Memory truth report")
    lines.append("")
    lines.append(f"- User DB memories: {s.get('user_memories')}")
    lines.append(f"- User DB memory FTS rows: {s.get('user_memory_fts')}")
    lines.append(f"- Conversation turns: {s.get('user_conversation_turns')}")
    lines.append(f"- Conversations: {s.get('user_conversations')}")
    lines.append(f"- Observations: {s.get('user_observations')}")
    lines.append(f"- Recall log entries: {s.get('user_recall_log')}")
    lines.append(f"- Agent DB memories: {s.get('agent_memories')}")
    lines.append(f"- Agent DB observations: {s.get('agent_observations')}")
    lines.append(f"- Vector index entries: {s.get('vector_ntotal')}")
    lines.append(f"- Vector dimension: {s.get('vector_dim')}")
    lines.append(f"- Vector metadata entries: {s.get('vector_meta_len')}")
    lines.append("")
    user = dbs.get("user", {})
    agent = dbs.get("agent", {})
    lines.append(f"- User DB path: {user.get('path')}")
    lines.append(f"- Agent DB path: {agent.get('path')}")
    lines.append(f"- Vector index path: {vectors.get('index_path')}")
    lines.append("")
    errors = []
    for block in (user, agent, vectors):
        errors.extend(block.get("errors", []) if isinstance(block, dict) else [])
    if errors:
        lines.append("Errors:")
        for err in errors:
            lines.append(f"- {err}")
    else:
        lines.append("Errors: none detected by deterministic memory inspection.")
    return "\n".join(lines)
'''
write_if_changed(ROOT / "eli/memory/memory_truth.py", textwrap.dedent(memory_truth).lstrip())

# ---------------------------------------------------------------------
# eli/runtime/truth_report.py
# ---------------------------------------------------------------------
truth_report = r'''
from __future__ import annotations

import importlib
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict


def _project_root() -> Path:
    try:
        from eli.core.paths import project_root
        value = project_root() if callable(project_root) else project_root
        return Path(value).expanduser().resolve()
    except Exception:
        return Path(__file__).resolve().parents[2]


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        pass
    return {}


def _git_info(root: Path) -> Dict[str, Any]:
    def run(args: list[str]) -> str:
        try:
            return subprocess.check_output(args, cwd=str(root), text=True, stderr=subprocess.DEVNULL).strip()
        except Exception:
            return ""

    return {
        "branch": run(["git", "branch", "--show-current"]),
        "commit": run(["git", "rev-parse", "--short", "HEAD"]),
        "dirty_files": run(["git", "status", "--short"]).splitlines(),
    }


def _nvidia_info() -> Dict[str, Any]:
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.free,driver_version",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=3,
        ).strip()
        if not out:
            return {"available": False}
        first = out.splitlines()[0]
        parts = [p.strip() for p in first.split(",")]
        return {
            "available": True,
            "name": parts[0] if len(parts) > 0 else "",
            "memory_total_mib": int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else parts[1] if len(parts) > 1 else None,
            "memory_free_mib": int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else parts[2] if len(parts) > 2 else None,
            "driver": parts[3] if len(parts) > 3 else "",
        }
    except Exception as exc:
        return {"available": False, "error": type(exc).__name__ + ": " + str(exc)}


def _safe_getattr(obj: Any, names: list[str]) -> Any:
    for name in names:
        try:
            val = getattr(obj, name, None)
            if val is not None:
                return val
        except Exception:
            continue
    return None


def _gguf_runtime() -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "module_imported": False,
        "llm_exists": False,
        "effective": {},
        "live_override": {},
        "errors": [],
    }
    try:
        from eli.cognition import gguf_inference as gg
        out["module_imported"] = True
        llm = getattr(gg, "_llm", None)
        out["llm_exists"] = llm is not None
        out["live_override"] = (
            getattr(gg, "_live_runtime_override", None)
            or getattr(gg, "_live_runtime_params", None)
            or {}
        )

        effective = {}
        for key, names in {
            "n_ctx": ["n_ctx", "_n_ctx", "context_size"],
            "n_gpu_layers": ["n_gpu_layers", "_n_gpu_layers"],
            "n_threads": ["n_threads", "_n_threads"],
            "n_batch": ["n_batch", "batch_size", "_n_batch"],
            "model_path": ["model_path", "_model_path"],
        }.items():
            val = _safe_getattr(gg, names)
            if val is not None:
                effective[key] = str(val) if isinstance(val, Path) else val

        if llm is not None:
            for key, names in {
                "llm_n_ctx": ["n_ctx", "_n_ctx", "context_params"],
                "llm_model_path": ["model_path", "model"],
            }.items():
                val = _safe_getattr(llm, names)
                if val is not None:
                    effective[key] = str(val)

            # llama-cpp-python exposes metadata inconsistently across versions.
            try:
                if hasattr(llm, "n_ctx") and callable(llm.n_ctx):
                    effective["llm_n_ctx_callable"] = llm.n_ctx()
            except Exception:
                pass

        out["effective"] = effective
    except Exception as exc:
        out["errors"].append(type(exc).__name__ + ": " + str(exc))
    return out


def import_health(modules: list[str] | None = None) -> Dict[str, Any]:
    modules = modules or [
        "eli.kernel.engine",
        "eli.execution.router_enhanced",
        "eli.execution.executor_enhanced",
        "eli.cognition.gguf_inference",
        "eli.cognition.orchestrator",
        "eli.cognition.context_synthesiser",
        "eli.cognition.response_governance",
        "eli.memory.memory_truth",
        "eli.runtime.truth_report",
    ]
    results = {}
    for name in modules:
        try:
            importlib.import_module(name)
            results[name] = {"ok": True}
        except Exception as exc:
            results[name] = {"ok": False, "error": type(exc).__name__ + ": " + str(exc)}
    return results


def runtime_truth_report(engine: Any = None) -> Dict[str, Any]:
    root = _project_root()
    settings_path = root / "config" / "settings.json"
    snapshot_path = root / "artifacts" / "runtime_snapshot.json"
    settings = _read_json(settings_path)
    snapshot = _read_json(snapshot_path)

    env_keys = [
        "ELI_PROJECT_ROOT",
        "ELI_DATA_DIR",
        "ELI_CONFIG_DIR",
        "ELI_GGUF_MODEL",
        "ELI_GGUF_MODEL_PATH",
        "ELI_GGUF_N_CTX",
        "ELI_GGUF_N_GPU_LAYERS",
        "ELI_GGUF_N_THREADS",
        "ELI_GGUF_N_BATCH",
        "ELI_GGUF_MAX_TOKENS",
        "ELI_LOCAL_STT_MODEL",
        "ELI_WHISPER_MODEL",
        "ELI_WHISPER_MODEL_DIR",
    ]

    engine_info: Dict[str, Any] = {}
    if engine is not None:
        engine_info = {
            "class": type(engine).__name__,
            "reasoning_mode": getattr(engine, "reasoning_mode", None),
            "mode": getattr(engine, "mode", None),
            "last_action": getattr(engine, "_last_action", None),
            "last_trace_exists": getattr(engine, "_last_trace", None) is not None,
        }

    return {
        "project_root": str(root),
        "python": sys.version.split()[0],
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "git": _git_info(root),
        "settings_path": str(settings_path),
        "settings_exists": settings_path.exists(),
        "settings": {
            k: settings.get(k)
            for k in (
                "provider",
                "model_path",
                "gguf_model_path",
                "n_ctx",
                "n_gpu_layers",
                "n_threads",
                "batch_size",
                "max_tokens",
                "temperature",
                "top_p",
            )
            if k in settings
        },
        "runtime_snapshot_path": str(snapshot_path),
        "runtime_snapshot_exists": snapshot_path.exists(),
        "runtime_snapshot": snapshot,
        "environment": {k: os.environ.get(k) for k in env_keys if os.environ.get(k) is not None},
        "gpu": _nvidia_info(),
        "gguf": _gguf_runtime(),
        "engine": engine_info,
        "import_health": import_health(),
    }


def format_runtime_truth(report: Dict[str, Any] | None = None) -> str:
    report = report or runtime_truth_report()
    settings = report.get("settings", {})
    snapshot = report.get("runtime_snapshot", {})
    gguf = report.get("gguf", {})
    gpu = report.get("gpu", {})
    git = report.get("git", {})
    imports = report.get("import_health", {})

    lines = []
    lines.append("Runtime truth report")
    lines.append("")
    lines.append(f"- Project root: {report.get('project_root')}")
    lines.append(f"- Python: {report.get('python')}")
    plat = report.get("platform", {})
    lines.append(f"- Platform: {plat.get('system')} {plat.get('release')} {plat.get('machine')}")
    lines.append(f"- Git branch: {git.get('branch')}")
    lines.append(f"- Git commit: {git.get('commit')}")
    lines.append(f"- Dirty files: {len(git.get('dirty_files') or [])}")
    lines.append("")
    lines.append("Requested/configured runtime:")
    lines.append(f"- Provider: {settings.get('provider')}")
    lines.append(f"- Model path: {settings.get('model_path') or settings.get('gguf_model_path')}")
    lines.append(f"- n_ctx: {settings.get('n_ctx')}")
    lines.append(f"- n_gpu_layers: {settings.get('n_gpu_layers')}")
    lines.append(f"- n_threads: {settings.get('n_threads')}")
    lines.append(f"- batch_size: {settings.get('batch_size')}")
    lines.append(f"- max_tokens: {settings.get('max_tokens')}")
    lines.append("")
    lines.append("Runtime snapshot:")
    lines.append(f"- Path: {report.get('runtime_snapshot_path')}")
    lines.append(f"- Exists: {report.get('runtime_snapshot_exists')}")
    lines.append(f"- n_ctx: {snapshot.get('n_ctx')}")
    lines.append(f"- n_gpu_layers: {snapshot.get('n_gpu_layers')}")
    lines.append(f"- n_threads: {snapshot.get('n_threads')}")
    lines.append("")
    lines.append("Effective GGUF inspection:")
    lines.append(f"- GGUF module imported: {gguf.get('module_imported')}")
    lines.append(f"- LLM object exists: {gguf.get('llm_exists')}")
    lines.append(f"- Effective fields: {json.dumps(gguf.get('effective', {}), ensure_ascii=False, sort_keys=True)}")
    lines.append(f"- Live override: {json.dumps(gguf.get('live_override', {}), ensure_ascii=False, sort_keys=True)}")
    lines.append("")
    lines.append("GPU:")
    lines.append(f"- Available: {gpu.get('available')}")
    if gpu.get("available"):
        lines.append(f"- Name: {gpu.get('name')}")
        lines.append(f"- Total MiB: {gpu.get('memory_total_mib')}")
        lines.append(f"- Free MiB: {gpu.get('memory_free_mib')}")
        lines.append(f"- Driver: {gpu.get('driver')}")
    elif gpu.get("error"):
        lines.append(f"- Error: {gpu.get('error')}")
    lines.append("")
    bad_imports = {k: v for k, v in imports.items() if not v.get("ok")}
    lines.append(f"Import health: {len(imports) - len(bad_imports)}/{len(imports)} OK")
    if bad_imports:
        for name, info in bad_imports.items():
            lines.append(f"- {name}: {info.get('error')}")
    return "\n".join(lines)
'''
write_if_changed(ROOT / "eli/runtime/truth_report.py", textwrap.dedent(truth_report).lstrip())

# ---------------------------------------------------------------------
# eli/runtime/deterministic_introspection.py
# ---------------------------------------------------------------------
deterministic = r'''
from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional


DIAGNOSTIC_ACTIONS = {
    "SELF_REPORT",
    "RUNTIME_STATUS",
    "MEMORY_STATUS",
    "USER_IDENTITY_SUMMARY",
    "EXPLAIN_MEMORY_RUNTIME",
    "EXPLAIN_COGNITION_RUNTIME",
    "EXPLAIN_LAST_RESPONSE",
    "IMPORT_AUDIT",
    "GUI_RUNTIME_AUDIT",
    "AGENTBUS_STATUS",
    "ORCHESTRATOR_STATUS",
    "OUTPUT_GOVERNOR_STATUS",
}


def classify_diagnostic_action(text: str) -> Optional[str]:
    low = str(text or "").strip().lower()
    if not low:
        return None

    if re.search(r"\b(who are you|what are you running|runtime status|model.*context|gpu layers|context size)\b", low):
        return "RUNTIME_STATUS"

    if re.search(r"\b(how many memories|memory system|memory runtime|what do you know about me from memory|memory count|stored memories)\b", low):
        return "EXPLAIN_MEMORY_RUNTIME"

    if re.search(r"\b(imports? failing|missing imports?|import audit|what imports are failing|missing code)\b", low):
        return "IMPORT_AUDIT"

    if re.search(r"\b(cognition pipeline|reasoning mode|input to output|cognition runtime)\b", low):
        return "EXPLAIN_COGNITION_RUNTIME"

    if re.search(r"\b(confidence in your last|which agents contributed|last response|last answer|why.*cut off|why.*incomplete)\b", low):
        return "EXPLAIN_LAST_RESPONSE"

    if re.search(r"\b(agent bus|agentbus)\b", low):
        return "AGENTBUS_STATUS"

    if re.search(r"\b(orchestrator)\b", low):
        return "ORCHESTRATOR_STATUS"

    if re.search(r"\b(output governor|response governance|governor)\b", low):
        return "OUTPUT_GOVERNOR_STATUS"

    return None


def _route_action(text: str) -> Optional[str]:
    try:
        from eli.execution.router_enhanced import route
        routed = route(text)
        if isinstance(routed, dict):
            action = str(routed.get("action") or "").strip().upper()
            if action in DIAGNOSTIC_ACTIONS:
                return action
    except Exception:
        pass
    return classify_diagnostic_action(text)


def _last_trace(engine: Any) -> Dict[str, Any]:
    for name in ("_last_trace", "last_trace", "_last_response_trace", "last_response_trace"):
        try:
            val = getattr(engine, name, None)
            if isinstance(val, dict):
                return val
        except Exception:
            pass
    return {}


def _last_response(engine: Any) -> str:
    for name in ("_last_response", "last_response", "_last_answer", "last_answer"):
        try:
            val = getattr(engine, name, None)
            if val is not None and str(val).strip():
                return str(val)
        except Exception:
            pass
    return ""


def _format_jsonish(obj: Any) -> str:
    try:
        return json.dumps(obj, indent=2, ensure_ascii=False, default=str)
    except Exception:
        return str(obj)


def _explain_last_response(engine: Any) -> str:
    trace = _last_trace(engine)
    response = _last_response(engine)
    lines = []
    lines.append("Last-response truth report")
    lines.append("")
    if response:
        lines.append(f"- Last response chars: {len(response)}")
        lines.append(f"- Last response preview: {response[:500]}")
    else:
        lines.append("- Last response: no stored last-response text was found on the engine object.")

    if trace:
        lines.append("")
        lines.append("Trace fields:")
        for key in sorted(trace.keys()):
            val = trace.get(key)
            if isinstance(val, (str, int, float, bool)) or val is None:
                lines.append(f"- {key}: {val}")
            else:
                lines.append(f"- {key}: {type(val).__name__}")

        agents = (
            trace.get("agents_used")
            or trace.get("agents")
            or trace.get("agent_results")
            or trace.get("bus_agents")
        )
        lines.append("")
        lines.append("Agent contribution evidence:")
        if agents:
            lines.append(_format_jsonish(agents))
        else:
            lines.append("- No explicit agent contribution list found in stored trace.")

        confidence = (
            trace.get("answer_confidence")
            or trace.get("evidence_confidence")
            or trace.get("confidence")
            or trace.get("bus_confidence")
            or trace.get("route_confidence")
        )
        lines.append("")
        lines.append(f"Confidence evidence field: {confidence}")
        lines.append("Important: route/bus confidence is not the same thing as factual answer confidence.")
    else:
        lines.append("")
        lines.append("No structured trace was found. This means ELI cannot honestly claim which agents contributed unless the engine stores that packet.")
    return "\n".join(lines)


def _cognition_report(engine: Any) -> str:
    lines = []
    lines.append("Cognition runtime report")
    lines.append("")
    lines.append("Deterministic pipeline currently enforced for diagnostic actions:")
    lines.append("1. Receive text from GUI/STT/chat.")
    lines.append("2. Route/classify the action.")
    lines.append("3. If the action is diagnostic, bypass GGUF generation.")
    lines.append("4. Read runtime/memory/import state directly from Python, SQLite, FAISS metadata, settings, env, and engine attributes.")
    lines.append("5. Return the report directly.")
    lines.append("")
    lines.append("For non-diagnostic actions, existing router/executor/orchestrator flow remains active.")
    lines.append("")
    lines.append(f"Engine class: {type(engine).__name__ if engine is not None else None}")
    for attr in ("reasoning_mode", "mode", "_reasoning_mode", "_last_action"):
        try:
            if hasattr(engine, attr):
                lines.append(f"{attr}: {getattr(engine, attr)}")
        except Exception:
            pass
    return "\n".join(lines)


def _module_status(module_name: str) -> str:
    try:
        mod = __import__(module_name, fromlist=["*"])
        path = getattr(mod, "__file__", None)
        return f"{module_name}: OK ({path})"
    except Exception as exc:
        return f"{module_name}: FAIL {type(exc).__name__}: {exc}"


def _import_audit() -> str:
    modules = [
        "eli.kernel.engine",
        "eli.execution.router_enhanced",
        "eli.execution.executor_enhanced",
        "eli.execution.portable_intent_contract",
        "eli.system.portable_app_control",
        "eli.cognition.gguf_inference",
        "eli.cognition.orchestrator",
        "eli.cognition.context_synthesiser",
        "eli.cognition.response_governance",
        "eli.memory.memory_truth",
        "eli.runtime.truth_report",
    ]
    lines = ["Import audit", ""]
    for mod in modules:
        lines.append("- " + _module_status(mod))
    return "\n".join(lines)


def _component_status(name: str) -> str:
    lookup = {
        "AGENTBUS_STATUS": [
            "eli.cognition.agent_bus",
            "eli.cognition.orchestrator",
        ],
        "ORCHESTRATOR_STATUS": [
            "eli.cognition.orchestrator",
        ],
        "OUTPUT_GOVERNOR_STATUS": [
            "eli.cognition.response_governance",
            "eli.cognition.output_governor",
        ],
    }
    lines = [name.replace("_", " ").title(), ""]
    for mod in lookup.get(name, []):
        lines.append("- " + _module_status(mod))
    return "\n".join(lines)


def handle_diagnostic_action(action: str, text: str, engine: Any = None) -> Optional[str]:
    action = str(action or "").strip().upper()
    if action not in DIAGNOSTIC_ACTIONS:
        return None

    if action in {"SELF_REPORT", "RUNTIME_STATUS", "GUI_RUNTIME_AUDIT"}:
        from eli.runtime.truth_report import runtime_truth_report, format_runtime_truth
        return format_runtime_truth(runtime_truth_report(engine=engine))

    if action in {"MEMORY_STATUS", "USER_IDENTITY_SUMMARY", "EXPLAIN_MEMORY_RUNTIME"}:
        from eli.memory.memory_truth import memory_truth_report, format_memory_truth
        return format_memory_truth(memory_truth_report())

    if action == "EXPLAIN_LAST_RESPONSE":
        return _explain_last_response(engine)

    if action == "EXPLAIN_COGNITION_RUNTIME":
        return _cognition_report(engine)

    if action == "IMPORT_AUDIT":
        return _import_audit()

    if action in {"AGENTBUS_STATUS", "ORCHESTRATOR_STATUS", "OUTPUT_GOVERNOR_STATUS"}:
        return _component_status(action)

    return None


def maybe_handle(text: str, engine: Any = None) -> Optional[str]:
    action = _route_action(text)
    if not action:
        return None
    return handle_diagnostic_action(action, text, engine=engine)
'''
write_if_changed(ROOT / "eli/runtime/deterministic_introspection.py", textwrap.dedent(deterministic).lstrip())

# ---------------------------------------------------------------------
# Patch engine.py early in CognitiveEngine.process.
# ---------------------------------------------------------------------
engine = ROOT / "eli/kernel/engine.py"
src = engine.read_text(encoding="utf-8", errors="replace")
marker = "deterministic_introspection_engine_gate_v1"

if marker in src:
    print("ENGINE_GATE_ALREADY_PRESENT")
else:
    tree = ast.parse(src)
    target = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "CognitiveEngine":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "process":
                    target = item
                    break
    if target is None:
        print("ENGINE_PROCESS_NOT_FOUND")
    else:
        lines = src.splitlines(keepends=True)
        insert_line = target.body[0].lineno - 1
        indent = " " * (target.body[0].col_offset)
        block = f'''
{indent}# {marker}
{indent}try:
{indent}    _eli_diag_text = None
{indent}    for _eli_diag_name in ("user_input", "prompt", "message", "text", "query", "input_text"):
{indent}        if _eli_diag_name in locals():
{indent}            _eli_diag_text = locals().get(_eli_diag_name)
{indent}            break
{indent}    if _eli_diag_text is not None:
{indent}        from eli.runtime.deterministic_introspection import maybe_handle as _eli_det_maybe_handle
{indent}        _eli_det_response = _eli_det_maybe_handle(str(_eli_diag_text), engine=self)
{indent}        if _eli_det_response is not None:
{indent}            try:
{indent}                self._last_response = str(_eli_det_response)
{indent}                self._last_trace = {{
{indent}                    "action": "DETERMINISTIC_INTROSPECTION",
{indent}                    "generation_invoked": False,
{indent}                    "source": "eli.runtime.deterministic_introspection",
{indent}                }}
{indent}            except Exception:
{indent}                pass
{indent}            return str(_eli_det_response)
{indent}except Exception as _eli_det_err:
{indent}    print(f"[DETERMINISTIC_INTROSPECTION] bypass unavailable: {{_eli_det_err}}")
'''
        lines[insert_line:insert_line] = [block]
        write_if_changed(engine, "".join(lines))

# ---------------------------------------------------------------------
# Compile targets.
# ---------------------------------------------------------------------
ok = True
for path in TARGETS:
    if path.exists():
        ok = compile_one(path) and ok

print(f"BACKUP={BACKUP}")
print(f"PATCH_OK={ok}")
