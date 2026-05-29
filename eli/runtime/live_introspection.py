from __future__ import annotations

import importlib
import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def _artifacts() -> Path:
    return _root() / "artifacts"


def _runtime_dir() -> Path:
    return _artifacts() / "runtime"


def _db_path() -> Path:
    return _artifacts() / "db" / "user.sqlite3"


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def runtime_snapshot() -> Dict[str, Any]:
    return _read_json(_artifacts() / "runtime_snapshot.json")


def last_trace() -> Dict[str, Any]:
    return _read_json(_runtime_dir() / "last_trace.json")


def _active_user_id() -> str:
    try:
        from eli.kernel.state import get_active_user_id
        return str(get_active_user_id() or "")
    except Exception:
        return ""


def _state_profile() -> tuple[Dict[str, Any], Dict[str, Any]]:
    state = {}
    profile = {}
    try:
        from eli.kernel.state import load_state, load_user_profile
        state = dict(load_state() or {})
        profile = dict(load_user_profile() or {})
    except Exception:
        pass
    return state, profile


def stored_user_name() -> str:
    try:
        from eli.kernel.state import get_user_name
        return str(get_user_name("") or "").strip()
    except Exception:
        st, pr = _state_profile()
        return str(pr.get("name") or "").strip()


def _conn() -> sqlite3.Connection | None:
    db = _db_path()
    if not db.exists():
        return None
    try:
        return sqlite3.connect(str(db))
    except Exception:
        return None


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        return bool(row)
    except Exception:
        return False


def _count(conn: sqlite3.Connection, table: str) -> int:
    try:
        if _table_exists(conn, table):
            return int(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] or 0)
    except Exception:
        pass
    return 0


def _columns(conn: sqlite3.Connection, table: str) -> List[str]:
    try:
        if _table_exists(conn, table):
            return [str(r[1]) for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    except Exception:
        pass
    return []


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return set(_columns(conn, table))


def _sql_coalesce_expr(cols: set[str], names: list[str], fallback: str = "''") -> str:
    present = [n for n in names if n in cols]
    if not present:
        return fallback
    return "COALESCE(" + ", ".join(present + [fallback]) + ")"


def _sql_time_expr(cols: set[str]) -> str:
    return _sql_coalesce_expr(cols, ["created_at", "timestamp", "ts", "id"], "0")


_BAD_FACT_VALUES = {"asking", "not asking", "unknown", "none", "null"}


def _clean_value(v: str) -> str:
    s = re.sub(r"\s+", " ", str(v or "")).strip(" .,:;!?-")
    return s


def _accept_value(v: str) -> bool:
    s = _clean_value(v).lower()
    if not s:
        return False
    if s in _BAD_FACT_VALUES:
        return False
    if len(s) > 60:
        return False
    return True


def mine_user_fact_candidates(limit: int = 12) -> List[str]:
    facts: List[str] = []
    seen = set()
    active_uid = _active_user_id()

    def add(line: str) -> None:
        item = _clean_value(line)
        if not item:
            return
        key = item.lower()
        if key in seen:
            return
        seen.add(key)
        facts.append(item)

    # Profile/state name remains dynamic and active-user scoped through eli.kernel.state.
    name = stored_user_name()
    if name:
        add(f"name: {name}")

    rows: List[str] = []
    conn = _conn()

    try:
        if conn is not None:
            # Highest-priority structured profile signals.
            if _table_exists(conn, "user_patterns"):
                cols = _table_columns(conn, "user_patterns")
                if active_uid and "user_id" in cols:
                    text_expr = _sql_coalesce_expr(cols, ["pattern_data", "text", "content", "value"], "''")
                    type_expr = _sql_coalesce_expr(cols, ["pattern_type", "kind", "tags"], "''")
                    time_expr = _sql_time_expr(cols)

                    for r in conn.execute(
                        f"""
                        SELECT {text_expr} AS text, {type_expr} AS typ
                        FROM user_patterns
                        WHERE COALESCE(user_id,'') = ?
                          AND COALESCE({text_expr}, '') != ''
                        ORDER BY {time_expr} DESC
                        LIMIT 300
                        """,
                        (active_uid,),
                    ).fetchall():
                        txt = _clean_value(r[0])
                        typ = _clean_value(r[1]).lower()
                        if not txt:
                            continue
                        if typ.startswith("identity."):
                            add(txt if ":" in txt else f"identity: {txt}")
                        elif typ.startswith("preference."):
                            add(txt if txt.lower().startswith("preference") else f"preference: {txt}")
                        elif typ.startswith("project."):
                            add(txt if txt.lower().startswith("project") else f"project: {txt}")
                        elif typ.startswith("research."):
                            add(txt if txt.lower().startswith("research") else f"research: {txt}")

            # User turns, scoped by active user_id when available.
            if _table_exists(conn, "conversation_turns"):
                cols = _table_columns(conn, "conversation_turns")
                if "content" in cols:
                    where = "WHERE LOWER(COALESCE(role,''))='user' AND COALESCE(content,'') != ''"
                    params: list[Any] = []

                    if active_uid and "user_id" in cols:
                        where += " AND COALESCE(user_id,'') = ?"
                        params.append(active_uid)

                    time_expr = _sql_time_expr(cols)

                    rows.extend(
                        str(r[0] or "")
                        for r in conn.execute(
                            f"""
                            SELECT COALESCE(content,'')
                            FROM conversation_turns
                            {where}
                            ORDER BY {time_expr} DESC
                            LIMIT 500
                            """,
                            tuple(params),
                        ).fetchall()
                    )

            # Stable memory rows, now safely scoped after migration.
            if _table_exists(conn, "memories"):
                cols = _table_columns(conn, "memories")
                if active_uid and "user_id" in cols:
                    text_expr = _sql_coalesce_expr(cols, ["text", "value", "content"], "''")
                    time_expr = _sql_time_expr(cols)

                    rows.extend(
                        str(r[0] or "")
                        for r in conn.execute(
                            f"""
                            SELECT {text_expr}
                            FROM memories
                            WHERE COALESCE(user_id,'') = ?
                              AND COALESCE({text_expr}, '') != ''
                            ORDER BY {time_expr} DESC
                            LIMIT 500
                            """,
                            (active_uid,),
                        ).fetchall()
                    )
    finally:
        if conn is not None:
            conn.close()

    for raw in rows:
        text = _clean_value(raw)

        # Avoid turning questions into stored identity facts.
        if "?" in text:
            continue

        for m in re.finditer(r"\bmy name is\s+([A-Za-z][A-Za-z' -]{1,30})\b", text, flags=re.I):
            val = _clean_value(m.group(1))
            if _accept_value(val):
                add(f"name: {val}")

        for m in re.finditer(r"\b(?:call me|i go by)\s+([A-Za-z][A-Za-z' -]{1,30})\b", text, flags=re.I):
            val = _clean_value(m.group(1))
            if _accept_value(val):
                add(f"preferred_name: {val}")

        for m in re.finditer(
            r"\bit is\s+([A-Za-z][A-Za-z' -]{1,30})\s*,?\s*or\s*([A-Za-z][A-Za-z' -]{1,30})\s*\(nickname\)",
            text,
            flags=re.I,
        ):
            a = _clean_value(m.group(1))
            b = _clean_value(m.group(2))
            if _accept_value(a):
                add(f"name: {a}")
            if _accept_value(b):
                add(f"nickname: {b}")

        for m in re.finditer(r"\bnickname\s*[:=-]?\s*([A-Za-z][A-Za-z' -]{1,30})\b", text, flags=re.I):
            val = _clean_value(m.group(1))
            if _accept_value(val):
                add(f"nickname: {val}")

        for m in re.finditer(r"\bi prefer\s+([^.!?\n]{3,120})", text, flags=re.I):
            val = _clean_value(m.group(1))
            if val and "who " not in val.lower() and "what " not in val.lower():
                add(f"preference: {val}")

        for m in re.finditer(r"\bi use\s+([^.!?\n]{3,120})", text, flags=re.I):
            val = _clean_value(m.group(1))
            if val:
                add(f"uses: {val}")

        for m in re.finditer(r"\bi work on\s+([^.!?\n]{3,160})", text, flags=re.I):
            val = _clean_value(m.group(1))
            if val:
                add(f"work: {val}")

        if len(facts) >= limit:
            break

    return facts[:limit]


def _runtime_core() -> Dict[str, Any]:
    snap = runtime_snapshot()
    runtime = dict(snap.get("runtime") or {})
    return {
        "provider": runtime.get("provider") or snap.get("provider") or "unknown",
        "model_name": runtime.get("model_name") or snap.get("model_name") or "unknown",
        "model_path": runtime.get("model_path") or snap.get("model_path") or "unknown",
        "n_ctx": runtime.get("n_ctx") or snap.get("n_ctx") or "unknown",
        "n_gpu_layers": runtime.get("n_gpu_layers") or snap.get("n_gpu_layers") or "unknown",
        "n_threads": runtime.get("n_threads") or snap.get("n_threads") or "unknown",
        "batch_size": runtime.get("n_batch") or runtime.get("batch_size") or snap.get("n_batch") or snap.get("batch_size") or "unknown",
        "loaded": bool(runtime.get("loaded") or snap.get("loaded")),
    }


def _paths_core() -> Dict[str, Any]:
    root = _root()
    return {
        "project_root": str(root),
        "artifacts_dir": str(root / "artifacts"),
        "user_db": str(root / "artifacts/db/user.sqlite3"),
        "agent_db": str(root / "artifacts/db/agent.sqlite3"),
    }


def _format_lines(title: str, items: List[tuple[str, Any]]) -> str:
    lines = [title]
    for k, v in items:
        lines.append(f"- {k}: {v}")
    return "\n".join(lines)


def build_report(action: str, user_input: str = "") -> Dict[str, Any]:
    act = str(action or "").strip().upper()
    rt = _runtime_core()
    paths = _paths_core()

    if act in {"SELF_REPORT", "RUNTIME_STATUS"}:
        report = {
            "ok": True,
            "identity": "ELI",
            "user_name": stored_user_name(),
            "runtime": rt,
            "paths": paths,
        }
        content = _format_lines(
            "Control evidence packet:" if act == "SELF_REPORT" else "Runtime evidence packet:",
            [
                ("identity", "ELI"),
                ("provider", rt["provider"]),
                ("model_name", rt["model_name"]),
                ("model_path", rt["model_path"]),
                ("context_size", rt["n_ctx"]),
                ("gpu_layers", rt["n_gpu_layers"]),
                ("cpu_threads", rt["n_threads"]),
                ("batch_size", rt["batch_size"]),
                ("gguf_loaded_in_this_process", rt["loaded"]),
                ("project_root", paths["project_root"]),
                ("user_db", paths["user_db"]),
                ("agent_db", paths["agent_db"]),
                ("stored_user_name", stored_user_name() or "none"),
            ],
        )
        return {"ok": True, "action": act, "report": report, "content": content, "response": content}

    if act == "USER_IDENTITY_SUMMARY":
        facts = mine_user_fact_candidates(limit=12)
        report = {
            "ok": True,
            "active_user_id": _active_user_id(),
            "stored_name": stored_user_name(),
            "fact_candidates": facts,
        }
        lines = ["User identity evidence packet:"]
        lines.append(f"- active_user_id: {_active_user_id() or 'unknown'}")
        lines.append(f"- stored_name: {stored_user_name() or 'none'}")
        if facts:
            lines.append("- stable_fact_candidates:")
            for fact in facts:
                lines.append(f"  - {fact}")
        else:
            lines.append("- stable_fact_candidates: none")
        content = "\n".join(lines)
        return {"ok": True, "action": act, "report": report, "content": content, "response": content}

    if act == "LAST_TRACE_REPORT":
        tr = last_trace()
        agents = tr.get("agents_used") or tr.get("agents") or []
        report = {
            "ok": True,
            "trace_available": bool(tr),
            "request_id": tr.get("request_id"),
            "reasoning_mode": tr.get("reasoning_mode"),
            "route_action": tr.get("route_action"),
            "result_action": tr.get("result_action"),
            "confidence": tr.get("confidence"),
            "agents": agents,
            "plan": tr.get("plan") or "none",
            "route_meta": tr.get("route_meta") or {},
            "result_meta": tr.get("result_meta") or {},
        }
        content = _format_lines(
            "Last trace:",
            [
                ("trace_available", report["trace_available"]),
                ("request_id", report["request_id"]),
                ("reasoning_mode", report["reasoning_mode"]),
                ("route_action", report["route_action"]),
                ("result_action", report["result_action"]),
                ("confidence", report["confidence"]),
                ("agents", report["agents"]),
                ("plan", report["plan"]),
                ("route_meta", report["route_meta"]),
                ("result_meta", report["result_meta"]),
            ],
        )
        return {"ok": True, "action": act, "report": report, "content": content, "response": content}

    if act == "PERSONA_AUTO_REPORT":
        p = _root() / "eli/cognition/persona.auto.txt"
        body = ""
        if p.exists():
            try:
                body = p.read_text(encoding="utf-8", errors="replace").strip()
            except Exception as e:
                body = f"<read_error: {e}>"
        report = {"ok": True, "path": str(p), "exists": p.exists(), "size_bytes": p.stat().st_size if p.exists() else 0}
        content = "\n".join(
            [
                f"persona.auto.txt exists: {report['exists']}",
                f"path: {report['path']}",
                f"size_bytes: {report['size_bytes']}",
                body[:4000],
            ]
        ).strip()
        return {"ok": True, "action": act, "report": report, "content": content, "response": content}

    if act == "IMPORT_AUDIT":
        modules = [
            "eli.kernel.engine",
            "eli.cognition.orchestrator",
            "eli.cognition.agent_bus",
            "eli.cognition.gguf_inference",
            "eli.memory.memory",
            "eli.execution.router_enhanced",
            "eli.execution.executor_enhanced",
            "eli.gui.eli_pro_audio_gui_MKI",
            "eli.planning.proactive_daemon",
        ]
        entries = []
        for mod in modules:
            try:
                importlib.import_module(mod)
                entries.append({"module": mod, "status": "PASS", "error": "", "suggested_fix": ""})
            except Exception as e:
                entries.append({"module": mod, "status": "FAIL", "error": repr(e), "suggested_fix": "inspect import path and syntax"})
        content = "\n".join(f"{e['module']} | {e['status']} | {e['error'] or '-'} | {e['suggested_fix'] or '-'}" for e in entries)
        return {"ok": True, "action": act, "report": {"ok": True, "entries": entries}, "content": content, "response": content}

    if act == "RUNTIME_AUDIT":
        import re as _re_audit

        _audit_files = [
            "eli/kernel/engine.py",
            "eli/cognition/orchestrator.py",
            "eli/cognition/agent_bus.py",
            "eli/cognition/context_synthesiser.py",
            "eli/cognition/working_memory.py",
            "eli/cognition/gguf_inference.py",
            "eli/cognition/output_governor.py",
            "eli/execution/router_enhanced.py",
            "eli/execution/executor_enhanced.py",
            "eli/runtime/live_introspection.py",
            "eli/gui/eli_pro_audio_gui_MKI.py",
            "eli/planning/proactive_daemon.py",
            "eli/memory/memory.py",
            "eli/world/agency/autonomy_engine.py",
            "eli/world/world_event_bus.py",
            "eli/core/paths.py",
        ]

        def _live_audit_file(rel: str) -> Dict[str, Any]:
            p = _root() / rel
            entry: Dict[str, Any] = {
                "path": rel, "status": "PASS", "issues": [],
                "checks": ["existence", "syntax", "merge_markers",
                           "hardcoded_paths", "stubs"],
            }
            if not p.exists():
                entry["status"] = "FAIL"
                entry["issues"].append({"type": "missing_file", "line": 0,
                                        "message": "file not found on disk"})
                return entry
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except Exception as exc:
                entry["status"] = "FAIL"
                entry["issues"].append({"type": "read_error", "line": 0,
                                        "message": str(exc)})
                return entry
            lines_list = text.splitlines()
            # 1. Syntax
            try:
                compile(text, str(p), "exec")
            except SyntaxError as exc:
                entry["issues"].append({
                    "type": "syntax_error",
                    "line": int(getattr(exc, "lineno", 0) or 0),
                    "message": str(exc),
                })
            # 2. Merge conflict markers
            for i, ln in enumerate(lines_list, 1):
                if any(m in ln for m in ("<<<<<<< ", "=======", ">>>>>>> ")):
                    entry["issues"].append({
                        "type": "merge_conflict_marker", "line": i,
                        "message": ln.strip()[:80],
                    })
            # 3. Hardcoded absolute user-home paths in non-comment lines
            for i, ln in enumerate(lines_list, 1):
                stripped = ln.strip()
                if stripped.startswith("#"):
                    continue
                if _re_audit.search(r'["\'/](home/[a-zA-Z_][a-zA-Z0-9_]*/(?!Desktop/ELI)[^\s"\']{4,})', ln):
                    entry["issues"].append({
                        "type": "hardcoded_user_path", "line": i,
                        "message": ln.strip()[:90],
                    })
            # 4. Obvious stubs / dead code
            _stub_pat = _re_audit.compile(
                r'raise\s+NotImplementedError|'
                r'\bpass\b\s*#\s*(?:TODO|stub|placeholder|fake|decorat|FIXME)',
                _re_audit.I)
            for i, ln in enumerate(lines_list, 1):
                if _stub_pat.search(ln):
                    entry["issues"].append({
                        "type": "stub_or_not_implemented", "line": i,
                        "message": ln.strip()[:80],
                    })
            if entry["issues"]:
                severe = [x for x in entry["issues"]
                          if x["type"] in ("syntax_error", "merge_conflict_marker",
                                           "missing_file", "read_error")]
                entry["status"] = "FAIL" if severe else "WARN"
            return entry

        entries = [_live_audit_file(rel) for rel in _audit_files]
        n_fail = sum(1 for e in entries if e["status"] == "FAIL")
        n_warn = sum(1 for e in entries if e["status"] == "WARN")
        n_pass = sum(1 for e in entries if e["status"] == "PASS")
        methodology = (
            "WHAT THIS AUDIT CHECKS: (1) file existence, (2) Python syntax "
            "compilation, (3) merge conflict markers, (4) hardcoded absolute "
            "user-home paths outside the project root, (5) NotImplementedError/"
            "stub patterns.\n"
            "WHAT THIS AUDIT DOES NOT CHECK: live agent execution, runtime "
            "wiring correctness, whether agents are actively querying files, "
            "semantic logic, or pipeline completeness.\n"
            "A PASS means the file is structurally clean. It does NOT confirm "
            "that all functionality is working correctly at runtime."
        )
        content_lines = [methodology, ""]
        for e in entries:
            content_lines.append(f"{e['status']}  {e['path']}")
            for issue in e.get("issues", []):
                content_lines.append(
                    f"  [{issue['type']}] line {issue.get('line','?')}: "
                    f"{issue.get('message','')}"
                )
        content_lines.append(
            f"\nSummary: {n_pass} PASS / {n_warn} WARN / {n_fail} FAIL "
            f"across {len(entries)} files."
        )
        content = "\n".join(content_lines)
        report = {
            "ok": True, "entries": entries,
            "summary": {"pass": n_pass, "warn": n_warn, "fail": n_fail,
                        "total": len(entries)},
            "methodology": methodology,
        }
        return {"ok": True, "action": act, "report": report,
                "content": content, "response": content}

    if act == "EXPLAIN_COGNITION_RUNTIME":
        stage_names = [
            "1. PERCEIVE + INGEST",
            "2. INPUT NORMALIZATION + GUARDS",
            "3. ROUTER + TASK DECOMPOSER",
            "4. TRUTH / GROUNDING GATE",
            "5. EXECUTIVE CONTROLLER / PLANNER",
            "6. AGENT BUS",
            "7. WORKING MEMORY / CONTEXT ASSEMBLER",
            "8. SINGLE INFERENCE BROKER",
            "9. REASONING / SYNTHESIS LAYER",
            "10. OUTPUT GOVERNOR",
            "11. RESPONSE DELIVERY",
            "12. LEARNING + STATE UPDATE",
        ]
        files = [
            "eli/kernel/engine.py",
            "eli/cognition/orchestrator.py",
            "eli/cognition/agent_bus.py",
            "eli/cognition/working_memory.py",
            "eli/cognition/gguf_inference.py",
            "eli/execution/router_enhanced.py",
            "eli/execution/executor_enhanced.py",
            "eli/gui/eli_pro_audio_gui_MKI.py",
            "eli/kernel/pipeline.py",
            "eli/planning/proactive_daemon.py",
        ]
        import ast as _ast_li
        _engine_path = _root() / "eli/kernel/engine.py"
        _cognitive_engine_class = False
        _process_method = False
        _orchestrator_ref = False
        if _engine_path.exists():
            try:
                _engine_src = _engine_path.read_text(errors="replace")
                _ast_tree = _ast_li.parse(_engine_src)
                _cognitive_engine_class = any(
                    isinstance(n, _ast_li.ClassDef) and n.name == "CognitiveEngine"
                    for n in _ast_li.walk(_ast_tree)
                )
                _process_method = any(
                    isinstance(n, _ast_li.FunctionDef) and n.name == "process"
                    for n in _ast_li.walk(_ast_tree)
                )
                _orchestrator_ref = (
                    "_orchestrator" in _engine_src or "self.orchestrator" in _engine_src
                )
            except Exception:
                pass
        report = {
            "ok": True,
            "live_orchestration_surface": str(_engine_path),
            "cognitive_engine_class_in_engine_py": _cognitive_engine_class,
            "process_method_in_engine_py": _process_method,
            "internal_orchestrator_ref": _orchestrator_ref,
            "pipeline_stage_count": 12,
            "pipeline_stage_names": stage_names,
            "files": [{"path": str(_root() / f), "exists": (_root() / f).exists()} for f in files],
        }
        content = "\n".join(
            [
                "Cognition runtime surface:",
                f"- live_orchestration_surface: {report['live_orchestration_surface']}",
                "- note: the live CognitiveEngine class is inside eli/kernel/engine.py",
                f"- pipeline_stage_count: {report['pipeline_stage_count']}",
                f"- pipeline_stage_names: {report['pipeline_stage_names']}",
                f"- files: {report['files']}",
            ]
        )
        return {"ok": True, "action": act, "report": report, "content": content, "response": content}

    if act == "EXPLAIN_MEMORY_RUNTIME":
        conn = _conn()
        tables = {}
        counts = {}
        if conn is not None:
            try:
                for t in ["memories", "conversation_turns", "observations", "recall_log", "habits", "improvements", "memories_fts"]:
                    if _table_exists(conn, t):
                        tables[t] = _columns(conn, t)
                        counts[t] = _count(conn, t)
            finally:
                conn.close()

        files = [
            "eli/memory/memory.py",
            "eli/memory/memory_adapter.py",
            "eli/memory/memory_service.py",
            "eli/memory/knowledge_graph.py",
            "eli/memory/vector_store.py",
            "eli/kernel/state.py",
            "eli/kernel/world_model.py",
            "eli/runtime/persistence_gate.py",
            "eli/planning/proactive_daemon.py",
        ]
        report = {
            "ok": True,
            "files": [{"path": str(_root() / f), "exists": (_root() / f).exists()} for f in files],
            "tables": tables,
            "counts": counts,
            "stored_name": stored_user_name(),
        }
        content = "\n".join(
            [
                "Memory runtime surface:",
                f"- files: {report['files']}",
                f"- tables: {report['tables']}",
                f"- counts: {report['counts']}",
                f"- stored_name: {report['stored_name'] or 'none'}",
            ]
        )
        return {"ok": True, "action": act, "report": report, "content": content, "response": content}

    if act == "SMALL_TALK_GREETING":
        content = f"Online. identity=ELI; user={stored_user_name() or 'unknown'}; model={rt['model_name']}; ctx={rt['n_ctx']}; gpu_layer_param={rt['n_gpu_layers']}."
        return {"ok": True, "action": act, "report": {"ok": True}, "content": content, "response": content}

    content = f"Unhandled live introspection action: {act}"
    return {"ok": False, "action": act, "report": {"ok": False}, "content": content, "response": content}


def agents_for_action(action: str) -> List[str]:
    act = str(action or "").strip().upper()
    if act in {"SELF_REPORT", "RUNTIME_STATUS", "IMPORT_AUDIT", "RUNTIME_AUDIT"}:
        return ["introspection", "file_code"]
    if act in {"USER_IDENTITY_SUMMARY", "EXPLAIN_MEMORY_RUNTIME"}:
        return ["introspection", "memory", "file_code"]
    if act == "EXPLAIN_COGNITION_RUNTIME":
        return ["introspection", "file_code", "reflection"]
    if act == "LAST_TRACE_REPORT":
        return ["introspection"]
    if act == "PERSONA_AUTO_REPORT":
        return ["introspection", "file_code"]
    if act == "SMALL_TALK_GREETING":
        return ["introspection"]
    return ["introspection"]
