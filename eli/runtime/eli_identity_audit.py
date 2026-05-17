from __future__ import annotations

import importlib.util
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from eli.runtime.experimental_inventory import build_experimental_inventory


REASONING_MODE_KEYS = (
    "quick",
    "chain_of_thought",
    "self_consistency",
    "tree_of_thoughts",
    "constitutional_ai",
)


def _project_root() -> Path:
    try:
        from eli.core.paths import get_paths

        return Path(get_paths().project_root)
    except Exception:
        return Path(__file__).resolve().parents[2]


def _module_exists(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except Exception:
        return False


def _source_inventory(root: Path) -> Dict[str, Any]:
    eli_dir = root / "eli"
    if not eli_dir.exists():
        return {
            "eli_dir": str(eli_dir),
            "exists": False,
            "python_files": 0,
            "total_files": 0,
            "top_level_packages": [],
        }
    py_files = [p for p in eli_dir.rglob("*.py") if p.is_file()]
    all_files = [p for p in eli_dir.rglob("*") if p.is_file()]
    packages = sorted(p.name for p in eli_dir.iterdir() if p.is_dir() and not p.name.startswith("__"))
    return {
        "eli_dir": str(eli_dir),
        "exists": True,
        "python_files": len(py_files),
        "total_files": len(all_files),
        "top_level_packages": packages,
    }


def _contract_counts() -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "control_action_count": 0,
        "supported_action_count": 0,
        "agent_count": 0,
        "system_action_count": 0,
        "router_priority_pipeline": False,
        "router_priority_stage_count": 0,
        "executor_middleware_table": False,
        "executor_middleware_count": 0,
        "grounding_policy_engine": False,
    }
    try:
        from eli.runtime.control_contracts import CONTROL_ACTIONS

        out["control_action_count"] = len(CONTROL_ACTIONS)
        out["has_identity_audit_action"] = "ELI_IDENTITY_AUDIT" in CONTROL_ACTIONS
    except Exception as exc:
        out["control_error"] = f"{type(exc).__name__}: {exc}"

    try:
        from eli.execution.executor_enhanced import SUPPORTED_ACTIONS

        out["supported_action_count"] = len(SUPPORTED_ACTIONS)
        out["executor_supports_identity_audit"] = "ELI_IDENTITY_AUDIT" in SUPPORTED_ACTIONS
    except Exception as exc:
        out["executor_error"] = f"{type(exc).__name__}: {exc}"

    try:
        from eli.cognition.agent_bus import SystemAgent, _ALL_AGENTS

        out["agent_count"] = len(_ALL_AGENTS)
        out["system_action_count"] = len(SystemAgent.SYSTEM_ACTIONS)
        out["agent_bus_supports_identity_audit"] = "ELI_IDENTITY_AUDIT" in SystemAgent.SYSTEM_ACTIONS
    except Exception as exc:
        out["agent_bus_error"] = f"{type(exc).__name__}: {exc}"

    try:
        from eli.execution import router_enhanced as router

        stages = getattr(router, "_ELI_ROUTE_PRIORITY_STAGES", ()) or ()
        out["router_priority_pipeline"] = bool(getattr(router, "_ELI_ROUTE_PRIORITY_PIPELINE_V1", False))
        out["router_priority_stage_count"] = len(stages)
        out["router_stage_names"] = [str(name) for name, _fn in stages]
    except Exception as exc:
        out["router_error"] = f"{type(exc).__name__}: {exc}"

    try:
        from eli.execution import executor_enhanced as executor

        table = getattr(executor, "_ELI_EXECUTOR_MIDDLEWARE_TABLE", ()) or ()
        out["executor_middleware_table"] = bool(getattr(executor, "_ELI_EXECUTOR_CANONICAL_MIDDLEWARE_TABLE_V1", False))
        out["executor_middleware_count"] = len(table)
    except Exception as exc:
        out["executor_middleware_error"] = f"{type(exc).__name__}: {exc}"

    try:
        from eli.runtime import deterministic_grounding_gate as gate

        out["grounding_policy_engine"] = bool(getattr(gate, "_ELI_DETERMINISTIC_GROUNDING_POLICY_ENGINE_V1", False))
    except Exception as exc:
        out["grounding_error"] = f"{type(exc).__name__}: {exc}"

    return out


def _world_status() -> Dict[str, Any]:
    try:
        from eli.world.local_world_bridge import get_world_state

        state = get_world_state()
        avatar = state.get("avatar") or {}
        return {
            "ok": True,
            "room_count": len(state.get("rooms") or {}),
            "object_count": len(state.get("objects") or {}),
            "event_count": len(state.get("events") or []),
            "action_count": len(state.get("actions") or []),
            "goal_count": len(state.get("goals") or []),
            "habit_count": len(state.get("habits") or []),
            "avatar_room": avatar.get("room"),
            "avatar_activity": avatar.get("activity"),
            "avatar_expression": avatar.get("expression"),
            "identity_keys": sorted((state.get("identity") or {}).keys()),
        }
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _runtime_snapshot_from_frontier(report: Dict[str, Any]) -> Dict[str, Any]:
    rt = report.get("runtime") or {}
    return {
        "n_ctx": rt.get("n_ctx") or 16384,
        "n_batch": rt.get("n_batch") or 256,
        "n_gpu_layers": rt.get("n_gpu_layers") or 0,
        "n_threads": rt.get("n_threads") or 8,
    }


def _reasoning_modes(runtime_snapshot: Dict[str, Any], query: str) -> List[Dict[str, Any]]:
    try:
        from eli.cognition.reasoning_modes import build_mode_execution_contract
        from eli.core import runtime_settings

        settings = runtime_settings.load_settings() or {}
        presets = settings.get("mode_presets") or {}
        hardware_presets = ((settings.get("hardware_profile") or {}).get("mode_presets") or {})

        rows: List[Dict[str, Any]] = []
        for mode in REASONING_MODE_KEYS:
            profile = dict(presets.get(mode) or {})
            if not profile and mode == "chain_of_thought":
                profile = dict(hardware_presets.get("cot") or {})
            if not profile:
                profile = dict(hardware_presets.get(mode) or {})
            if mode == "self_consistency":
                hp = dict(hardware_presets.get("self_consistency") or {})
                profile.setdefault("max_tokens_per_sample", hp.get("max_tokens_per_sample"))
                profile.setdefault("max_tokens_final", hp.get("max_tokens_final") or settings.get("max_tokens", 4096))
            if not profile:
                profile = {"max_tokens": settings.get("max_tokens", 4096), "temperature": settings.get("temperature", 0.7), "top_p": settings.get("top_p", 0.9)}

            contract = build_mode_execution_contract(
                mode,
                profile=profile,
                runtime_snapshot=runtime_snapshot,
                query_text=query or "fully analyse ELI and classify the system",
                memory_context="",
            )
            rows.append(
                {
                    "mode": contract.get("mode"),
                    "display": contract.get("display"),
                    "private": contract.get("private"),
                    "instructions": contract.get("instructions") or [],
                    "tasks": contract.get("tasks") or [],
                    "generation_overrides": contract.get("generation_overrides") or {},
                    "runtime": contract.get("runtime") or {},
                }
            )
        return rows
    except Exception as exc:
        return [{"mode": "error", "error": f"{type(exc).__name__}: {exc}"}]


def _capability_matrix(frontier: Dict[str, Any], contracts: Dict[str, Any], world: Dict[str, Any], experimental: Dict[str, Any]) -> List[Dict[str, str]]:
    mem = frontier.get("memory") or {}
    aw = frontier.get("awareness") or {}
    pro = frontier.get("proactive") or {}
    img = frontier.get("image") or {}
    wl = frontier.get("world_labs") or {}
    cf = frontier.get("chatflow") or {}
    modules = frontier.get("module_matrix") or []
    import_ok = sum(1 for m in modules if isinstance(m, dict) and m.get("import_ok"))

    matrix: Iterable[Tuple[str, bool, str, str]] = (
        (
            "Intent routing and control contracts",
            bool(contracts.get("router_priority_pipeline")),
            f"{contracts.get('router_priority_stage_count')} explicit router stages; {contracts.get('control_action_count')} control actions",
            "routes user intent into grounded actions before synthesis",
        ),
        (
            "Executor/middleware path",
            bool(contracts.get("executor_middleware_table")),
            f"{contracts.get('executor_middleware_count')} executor middleware entries; {contracts.get('supported_action_count')} supported actions",
            "runs tool/runtime actions and returns evidence packets",
        ),
        (
            "Grounding gate",
            bool(contracts.get("grounding_policy_engine")),
            "immutable deterministic grounding policy engine present",
            "decides when evidence is required and blocks unsupported fabrication",
        ),
        (
            "Persistent memory",
            bool(mem.get("user_db_exists")),
            f"user_db={mem.get('user_db_exists')} counts={(mem.get('counts') or {})}",
            "stores and recalls user/profile/conversation evidence locally",
        ),
        (
            "Self model and awareness",
            bool(aw.get("booted")) or _module_exists("eli.runtime.awareness_boot"),
            f"awareness_booted={aw.get('booted')} capability_count={aw.get('capability_count')}",
            "keeps capability/persona/runtime awareness surfaces",
        ),
        (
            "Proactive agency",
            _module_exists("eli.planning.proactive_daemon"),
            f"daemon_running={pro.get('running')} pid={pro.get('pid')}",
            "background goals/proposals are implemented, running state may vary",
        ),
        (
            "Reasoning modes",
            _module_exists("eli.cognition.reasoning_modes"),
            "quick, chain-of-thought, self-consistency, tree-of-thoughts, constitutional-ai contracts exist",
            "selects private synthesis topology and dynamic token/runtime plans",
        ),
        (
            "Image generation surface",
            _module_exists("eli.tools.image_engine.gui_bridge"),
            f"models_detected={img.get('models_detected')} presets_detected={img.get('presets_detected')}",
            "local visual generation/control surface is present",
        ),
        (
            "Embodied world model",
            bool(wl.get("world_tab_exists")) and bool(world.get("ok")),
            f"rooms={world.get('room_count')} objects={world.get('object_count')} current_room={world.get('avatar_room')}",
            "maps internal state into rooms, objects, avatar state, and reflection artifacts",
        ),
        (
            "Labs and experimental workbench",
            bool(wl.get("labs_tab_exists")) and bool(experimental.get("exists")),
            f"labs_tab={wl.get('labs_tab_exists')} experimental_projects={(experimental.get('counts') or {}).get('projects')}",
            "houses prototypes such as AR/avatar experiments without auto-executing them",
        ),
        (
            "Module import surface",
            import_ok == len(modules) and len(modules) > 0,
            f"frontier module matrix import_ok={import_ok}/{len(modules)}",
            "core audited modules are discoverable in the current checkout",
        ),
    )

    return [
        {
            "surface": surface,
            "status": "verified_wired" if ok else "present_with_gap",
            "verified_signal": signal,
            "capability_meaning": meaning,
        }
        for surface, ok, signal, meaning in matrix
    ]


def _classification(matrix: List[Dict[str, str]]) -> Dict[str, Any]:
    verified = sum(1 for row in matrix if row.get("status") == "verified_wired")
    total = len(matrix)
    return {
        "current_classification": "local persistent agentic cognitive-runtime and embodied AI workbench prototype",
        "recommended_classification": "pre-AGI cognitive OS layer for a single local machine, with persona, memory, tools, grounding, world-model, labs, and experimental embodiment surfaces",
        "not_classified_as": [
            "not verified AGI",
            "not sentient or conscious by evidence",
            "not an unrestricted autonomous operating system",
            "not a pure chatbot wrapper",
        ],
        "classification_confidence": "high",
        "verified_surface_ratio": f"{verified}/{total}",
        "why": [
            "It has local memory, grounded runtime introspection, tool execution, routing, and non-quick synthesis contracts.",
            "It has persistent persona/world-model surfaces and experimental embodiment assets.",
            "Its cognition is still engineered pipeline orchestration, not independent general intelligence.",
        ],
    }


def build_eli_identity_audit(query: str = "") -> Dict[str, Any]:
    t0 = time.perf_counter()
    root = _project_root()
    from eli.runtime.frontier_status import build_frontier_status_report

    frontier = build_frontier_status_report(query)
    contracts = _contract_counts()
    world = _world_status()
    experimental = build_experimental_inventory(root / "experimental")
    source = _source_inventory(root)
    reasoning = _reasoning_modes(_runtime_snapshot_from_frontier(frontier), query)
    matrix = _capability_matrix(frontier, contracts, world, experimental)

    report = {
        "ok": True,
        "action": "ELI_IDENTITY_AUDIT",
        "query": str(query or ""),
        "classification": _classification(matrix),
        "capability_matrix": matrix,
        "source_inventory": source,
        "contracts": contracts,
        "frontier_status": frontier,
        "world": world,
        "experimental": experimental,
        "reasoning_modes": reasoning,
        "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        "grounded": True,
        "evidence_source": "eli_identity_audit_local_verified_matrix_v1",
    }
    return report


def _fmt_bool(value: Any) -> str:
    return "yes" if bool(value) else "no"


def format_eli_identity_audit(report: Dict[str, Any]) -> str:
    cls = report.get("classification") or {}
    source = report.get("source_inventory") or {}
    contracts = report.get("contracts") or {}
    world = report.get("world") or {}
    experimental = report.get("experimental") or {}
    exp_counts = experimental.get("counts") or {}
    matrix = report.get("capability_matrix") or []
    reasoning = report.get("reasoning_modes") or []

    lines = [
        "ELI Identity Audit (verified local evidence)",
        "",
        "Classification:",
        f"- current: {cls.get('current_classification')}",
        f"- should be classified as: {cls.get('recommended_classification')}",
        f"- not classified as: {', '.join(cls.get('not_classified_as') or [])}",
        f"- confidence: {cls.get('classification_confidence')} ({cls.get('verified_surface_ratio')} verified surfaces)",
        "",
        "Verified Project Shape:",
        f"- eli python files: {source.get('python_files')}",
        f"- eli total files: {source.get('total_files')}",
        f"- top-level eli packages: {', '.join((source.get('top_level_packages') or [])[:18])}",
        "",
        "Runtime/Contract Wiring:",
        f"- router priority pipeline: {_fmt_bool(contracts.get('router_priority_pipeline'))} ({contracts.get('router_priority_stage_count')} stages)",
        f"- executor middleware table: {_fmt_bool(contracts.get('executor_middleware_table'))} ({contracts.get('executor_middleware_count')} entries)",
        f"- grounding policy engine: {_fmt_bool(contracts.get('grounding_policy_engine'))}",
        f"- control actions: {contracts.get('control_action_count')}; supported executor actions: {contracts.get('supported_action_count')}",
        "",
        "World/Embodiment:",
        f"- world ok: {_fmt_bool(world.get('ok'))}",
        f"- rooms: {world.get('room_count')}; objects: {world.get('object_count')}; current room: {world.get('avatar_room')}",
        f"- current activity/expression: {world.get('avatar_activity')} / {world.get('avatar_expression')}",
        f"- experimental projects: {exp_counts.get('projects')} ({exp_counts.get('active_projects')} active candidates, {exp_counts.get('backup_projects')} backups)",
        f"- experimental scripts/assets/archives: {exp_counts.get('scripts')} / {exp_counts.get('assets')} / {exp_counts.get('archives')}",
        "",
        "Capability Matrix:",
    ]
    for row in matrix:
        lines.append(
            f"- {row.get('surface')}: {row.get('status')} | {row.get('verified_signal')} | {row.get('capability_meaning')}"
        )

    lines.extend(["", "Reasoning Mode Contracts:"])
    for row in reasoning:
        if row.get("mode") == "error":
            lines.append(f"- reasoning contract error: {row.get('error')}")
            continue
        rt = row.get("runtime") or {}
        gen = row.get("generation_overrides") or {}
        lines.append(
            f"- {row.get('display')}: tasks={len(row.get('tasks') or [])}, "
            f"instructions={len(row.get('instructions') or [])}, "
            f"max_tokens={gen.get('max_tokens')}, "
            f"target_batch={rt.get('target_n_batch')}, target_gpu_layers={rt.get('target_n_gpu_layers')}"
        )

    return "\n".join(lines).strip()


__all__ = [
    "REASONING_MODE_KEYS",
    "build_eli_identity_audit",
    "format_eli_identity_audit",
]
