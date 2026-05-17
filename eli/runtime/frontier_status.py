from __future__ import annotations

import json
import importlib.util
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


def _project_root() -> Path:
    try:
        from eli.core.paths import get_paths

        return Path(get_paths().project_root)
    except Exception:
        return Path(__file__).resolve().parents[2]


def _artifacts_dir() -> Path:
    try:
        from eli.core.paths import get_paths

        return Path(get_paths().artifacts_dir)
    except Exception:
        return _project_root() / "artifacts"


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _table_count(db_path: Path, table: str) -> int | None:
    if not db_path.exists():
        return None
    try:
        con = sqlite3.connect(str(db_path))
        try:
            row = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()
            return int((row or [0])[0] or 0)
        finally:
            con.close()
    except Exception:
        return None


def _safe_getattr(obj: Any, name: str, default: Any = None) -> Any:
    try:
        return getattr(obj, name, default)
    except Exception:
        return default


def _runtime_status() -> Dict[str, Any]:
    root = _project_root()
    artifacts = _artifacts_dir()
    snap = _read_json(artifacts / "runtime_snapshot.json")
    settings = _read_json(root / "config" / "settings.json")
    return {
        "snapshot_path": str(artifacts / "runtime_snapshot.json"),
        "settings_path": str(root / "config" / "settings.json"),
        "model_path": str(
            snap.get("model_path")
            or settings.get("model_path")
            or settings.get("custom_model_path")
            or ""
        ),
        "provider": str(
            snap.get("provider")
            or settings.get("provider")
            or ""
        ),
        "n_ctx": snap.get("n_ctx", settings.get("n_ctx")),
        "n_batch": snap.get("n_batch", settings.get("batch_size")),
        "n_gpu_layers": snap.get("n_gpu_layers", settings.get("n_gpu_layers")),
        "n_threads": snap.get("n_threads", settings.get("n_threads")),
    }


def _memory_status() -> Dict[str, Any]:
    artifacts = _artifacts_dir()
    user_db = artifacts / "db" / "user.sqlite3"
    agent_db = artifacts / "db" / "agent.sqlite3"
    counts = {
        "user_memories": _table_count(user_db, "memories"),
        "user_conversation_turns": _table_count(user_db, "conversation_turns"),
        "user_observations": _table_count(user_db, "observations"),
        "agent_failures": _table_count(agent_db, "failures"),
        "agent_improvements": _table_count(agent_db, "improvements"),
        "agent_observations": _table_count(agent_db, "observations"),
    }
    return {
        "user_db": str(user_db),
        "agent_db": str(agent_db),
        "user_db_exists": user_db.exists(),
        "agent_db_exists": agent_db.exists(),
        "counts": counts,
    }


def _awareness_status() -> Dict[str, Any]:
    try:
        from eli.runtime.awareness_boot import get_awareness

        state = get_awareness()
        if state is None:
            return {
                "booted": False,
                "capability_count": 0,
                "code_report_has_changes": False,
                "persona_cleaned": False,
            }
        return {
            "booted": True,
            "capability_count": int(_safe_getattr(state, "capability_count", 0) or 0),
            "code_report_has_changes": bool(_safe_getattr(state, "code_report_has_changes", False)),
            "persona_cleaned": bool(_safe_getattr(state, "persona_cleaned", False)),
            "boot_time": float(_safe_getattr(state, "boot_time", 0.0) or 0.0),
        }
    except Exception as exc:
        return {
            "booted": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _proactive_status() -> Dict[str, Any]:
    artifacts = _artifacts_dir()
    pro_dir = artifacts / "proactive"
    pid_file = pro_dir / "daemon.pid"
    pid = 0
    running = False
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip() or 0)
        except Exception:
            pid = 0
    if pid > 0:
        try:
            os.kill(pid, 0)
            running = True
        except Exception:
            running = False

    summary: Dict[str, Any] = {}
    try:
        from eli.runtime.operator_state import safe_proposal_summary, safe_goal_summary

        summary = {
            "proposal_summary": safe_proposal_summary(),
            "goal_summary": safe_goal_summary(),
        }
    except Exception as exc:
        summary = {"error": f"{type(exc).__name__}: {exc}"}

    return {
        "dir": str(pro_dir),
        "pid_file": str(pid_file),
        "running": running,
        "pid": pid,
        "summary": summary,
    }


def _image_status() -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    try:
        from eli.tools.image_engine.runtime_paths import image_outputs_dir, image_logs_dir
        from eli.tools.image_engine.gui_bridge import (
            discover_local_image_models,
            discover_presets,
            list_recent_outputs,
        )

        models = discover_local_image_models()
        presets = discover_presets()
        recent = list_recent_outputs(limit=6)
        out = {
            "models_detected": len(models),
            "model_paths": [str(p) for p in models[:12]],
            "presets_detected": len(presets),
            "preset_names": list(presets[:12]),
            "recent_outputs": [str(p) for p in recent],
            "outputs_dir": str(image_outputs_dir()),
            "logs_dir": str(image_logs_dir()),
        }
    except Exception as exc:
        out = {
            "error": f"{type(exc).__name__}: {exc}",
            "models_detected": 0,
            "presets_detected": 0,
            "recent_outputs": [],
        }
    return out


def _world_and_labs_status() -> Dict[str, Any]:
    root = _project_root()
    world_tab = root / "eli" / "gui" / "tabs" / "eli_world_tab.py"
    experimental_tab = root / "eli" / "gui" / "tabs" / "experimental_tab.py"
    experimental_root = root / "experimental"
    labs_tab = root / "eli" / "gui" / "labs_tab.py"
    world_model = root / "eli" / "kernel" / "world_model.py"

    runtime_world_path = _artifacts_dir() / "runtime" / "world_model.json"
    runtime_world = _read_json(runtime_world_path)

    return {
        "world_tab_exists": world_tab.exists(),
        "experimental_tab_exists": experimental_tab.exists(),
        "experimental_root_exists": experimental_root.exists(),
        "labs_tab_exists": labs_tab.exists(),
        "world_model_module_exists": world_model.exists(),
        "world_model_runtime_exists": runtime_world_path.exists(),
        "world_model_runtime_path": str(runtime_world_path),
        "world_model_identity_name": (
            (runtime_world.get("identity") or {}).get("preferred_name")
            if isinstance(runtime_world, dict)
            else None
        ),
        "world_model_observation_count": len((runtime_world.get("observations") or [])) if isinstance(runtime_world, dict) else 0,
    }


def _chatflow_wiring_status() -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "router_priority_pipeline": False,
        "router_priority_stage_count": 0,
        "executor_middleware_table": False,
        "executor_middleware_count": 0,
        "grounding_policy_engine": False,
        "orchestrator_step_count": 0,
    }

    try:
        from eli.execution import router_enhanced as router

        result["router_priority_pipeline"] = bool(
            getattr(router, "_ELI_ROUTE_PRIORITY_PIPELINE_V1", False)
        )
        stages = getattr(router, "_ELI_ROUTE_PRIORITY_STAGES", ()) or ()
        result["router_priority_stage_count"] = len(stages)
    except Exception:
        pass

    try:
        from eli.execution import executor_enhanced as executor

        result["executor_middleware_table"] = bool(
            getattr(executor, "_ELI_EXECUTOR_CANONICAL_MIDDLEWARE_TABLE_V1", False)
        )
        mws = getattr(executor, "_ELI_EXECUTOR_MIDDLEWARE_TABLE", ()) or ()
        result["executor_middleware_count"] = len(mws)
    except Exception:
        pass

    try:
        from eli.runtime import deterministic_grounding_gate as gate

        result["grounding_policy_engine"] = bool(
            getattr(gate, "_ELI_DETERMINISTIC_GROUNDING_POLICY_ENGINE_V1", False)
        )
    except Exception:
        pass

    try:
        from eli.kernel.pipeline import STEPS

        result["orchestrator_step_count"] = len(STEPS or [])
        result["orchestrator_steps"] = [str(step.get("name") or "") for step in list(STEPS or [])]
    except Exception:
        result["orchestrator_steps"] = []

    return result


def _module_matrix() -> List[Dict[str, Any]]:
    targets: Iterable[Tuple[str, str]] = (
        ("memory", "eli.memory.memory"),
        ("self_improvement", "eli.runtime.self_improvement"),
        ("awareness", "eli.runtime.awareness_boot"),
        ("proactive", "eli.planning.proactive_daemon"),
        ("image_engine", "eli.tools.image_engine.gui_bridge"),
        ("world_model", "eli.kernel.world_model"),
        ("labs_tab", "eli.gui.labs_tab"),
        ("world_tab", "eli.gui.tabs.eli_world_tab"),
        ("experimental_tab", "eli.gui.tabs.experimental_tab"),
        ("router", "eli.execution.router_enhanced"),
        ("executor", "eli.execution.executor_enhanced"),
        ("engine", "eli.kernel.engine"),
        ("agent_bus", "eli.cognition.agent_bus"),
    )
    out: List[Dict[str, Any]] = []
    for name, mod in targets:
        ok = False
        err = ""
        try:
            ok = importlib.util.find_spec(mod) is not None
            if not ok:
                err = "module_not_found"
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
        out.append({"name": name, "module": mod, "import_ok": ok, "error": err})
    return out


def build_frontier_status_report(query: str = "") -> Dict[str, Any]:
    t0 = time.perf_counter()
    runtime = _runtime_status()
    memory = _memory_status()
    awareness = _awareness_status()
    proactive = _proactive_status()
    image = _image_status()
    world_labs = _world_and_labs_status()
    chatflow = _chatflow_wiring_status()
    modules = _module_matrix()

    ok = (
        bool(chatflow.get("router_priority_pipeline"))
        and bool(chatflow.get("executor_middleware_table"))
        and bool(chatflow.get("grounding_policy_engine"))
    )

    report = {
        "ok": ok,
        "action": "FRONTIER_STATUS",
        "query": str(query or ""),
        "runtime": runtime,
        "memory": memory,
        "awareness": awareness,
        "proactive": proactive,
        "image": image,
        "world_labs": world_labs,
        "chatflow": chatflow,
        "module_matrix": modules,
        "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        "grounded": True,
        "evidence_source": "frontier_status_local_runtime_matrix_v1",
    }
    return report


def format_frontier_status_report(report: Dict[str, Any]) -> str:
    rt = report.get("runtime") or {}
    mem = report.get("memory") or {}
    aw = report.get("awareness") or {}
    pro = report.get("proactive") or {}
    img = report.get("image") or {}
    wl = report.get("world_labs") or {}
    cf = report.get("chatflow") or {}
    mods = report.get("module_matrix") or []

    import_ok = sum(1 for m in mods if isinstance(m, dict) and m.get("import_ok"))
    import_total = len(mods)
    proposal_summary = ((pro.get("summary") or {}).get("proposal_summary") or {}).get("counts") or {}
    goal_summary = ((pro.get("summary") or {}).get("goal_summary") or {}).get("counts") or {}

    lines = [
        "Frontier System Status (grounded local matrix)",
        "",
        "Runtime:",
        f"- model_path: {rt.get('model_path') or 'unknown'}",
        f"- provider: {rt.get('provider') or 'unknown'}",
        f"- n_ctx: {rt.get('n_ctx')}",
        f"- n_batch: {rt.get('n_batch')}",
        f"- n_gpu_layers: {rt.get('n_gpu_layers')}",
        f"- n_threads: {rt.get('n_threads')}",
        "",
        "Chatflow Wiring:",
        f"- router_priority_pipeline: {cf.get('router_priority_pipeline')}",
        f"- router_priority_stage_count: {cf.get('router_priority_stage_count')}",
        f"- executor_middleware_table: {cf.get('executor_middleware_table')}",
        f"- executor_middleware_count: {cf.get('executor_middleware_count')}",
        f"- grounding_policy_engine: {cf.get('grounding_policy_engine')}",
        f"- orchestrator_step_count: {cf.get('orchestrator_step_count')}",
        "",
        "Memory / Self:",
        f"- user_db_exists: {mem.get('user_db_exists')} ({mem.get('user_db')})",
        f"- agent_db_exists: {mem.get('agent_db_exists')} ({mem.get('agent_db')})",
        f"- user_memories: {(mem.get('counts') or {}).get('user_memories')}",
        f"- user_conversation_turns: {(mem.get('counts') or {}).get('user_conversation_turns')}",
        f"- agent_failures: {(mem.get('counts') or {}).get('agent_failures')}",
        f"- agent_improvements: {(mem.get('counts') or {}).get('agent_improvements')}",
        f"- awareness_booted: {aw.get('booted')}",
        f"- awareness_capability_count: {aw.get('capability_count')}",
        "",
        "Proactive / Goals:",
        f"- proactive_daemon_running: {pro.get('running')}",
        f"- proactive_pid: {pro.get('pid')}",
        f"- proposal_counts: {proposal_summary if proposal_summary else '{}'}",
        f"- goal_counts: {goal_summary if goal_summary else '{}'}",
        "",
        "Image / World / Labs:",
        f"- image_models_detected: {img.get('models_detected')}",
        f"- image_presets_detected: {img.get('presets_detected')}",
        f"- image_recent_outputs: {len(img.get('recent_outputs') or [])}",
        f"- world_tab_exists: {wl.get('world_tab_exists')}",
        f"- experimental_tab_exists: {wl.get('experimental_tab_exists')}",
        f"- experimental_root_exists: {wl.get('experimental_root_exists')}",
        f"- labs_tab_exists: {wl.get('labs_tab_exists')}",
        f"- world_model_runtime_exists: {wl.get('world_model_runtime_exists')}",
        "",
        "Module Import Matrix:",
        f"- import_ok: {import_ok}/{import_total}",
        "",
        "Raw report:",
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
    ]
    return "\n".join(lines).strip()
