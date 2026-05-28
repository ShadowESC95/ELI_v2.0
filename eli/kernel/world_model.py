from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import logging
import threading
import time

log = logging.getLogger(__name__)

from eli.core.paths import get_paths


@dataclass
class IdentityState:
    user_id: str = ""
    preferred_name: str = ""
    aliases: List[str] = field(default_factory=list)
    confidence: float = 0.0
    updated_at: float = field(default_factory=time.time)


@dataclass
class RuntimeState:
    provider: str = ""
    model_path: str = ""
    model_name: str = ""
    n_ctx: int = 0
    n_threads: int = 0
    n_gpu_layers: int = 0
    batch_size: int = 0
    loaded: bool = False
    last_error: str = ""
    snapshot: Dict[str, Any] = field(default_factory=dict)
    updated_at: float = field(default_factory=time.time)


@dataclass
class MemoryState:
    user_db: str = ""
    agent_db: str = ""
    memory_db: str = ""
    stats: Dict[str, Any] = field(default_factory=dict)
    updated_at: float = field(default_factory=time.time)


@dataclass
class GoalState:
    active: List[Dict[str, Any]] = field(default_factory=list)
    queued: List[Dict[str, Any]] = field(default_factory=list)
    completed: List[Dict[str, Any]] = field(default_factory=list)
    updated_at: float = field(default_factory=time.time)


@dataclass
class CapabilityState:
    inventory: Dict[str, Any] = field(default_factory=dict)
    updated_at: float = field(default_factory=time.time)


@dataclass
class WorldModel:
    schema_version: int = 1
    updated_at: float = field(default_factory=time.time)
    identity: IdentityState = field(default_factory=IdentityState)
    runtime: RuntimeState = field(default_factory=RuntimeState)
    memory: MemoryState = field(default_factory=MemoryState)
    goals: GoalState = field(default_factory=GoalState)
    capabilities: CapabilityState = field(default_factory=CapabilityState)
    preferences: Dict[str, Any] = field(default_factory=dict)
    context: Dict[str, Any] = field(default_factory=dict)
    observations: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


_LOCK = threading.RLock()
_WORLD: Optional[WorldModel] = None


def _world_model_path() -> Path:
    p = Path(get_paths().artifacts_dir) / "runtime" / "world_model.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _coerce_identity(d: Dict[str, Any]) -> IdentityState:
    return IdentityState(
        user_id=str(d.get("user_id", "") or ""),
        preferred_name=str(d.get("preferred_name", "") or ""),
        aliases=list(d.get("aliases", []) or []),
        confidence=float(d.get("confidence", 0.0) or 0.0),
        updated_at=float(d.get("updated_at", time.time()) or time.time()),
    )


def _coerce_runtime(d: Dict[str, Any]) -> RuntimeState:
    return RuntimeState(
        provider=str(d.get("provider", "") or ""),
        model_path=str(d.get("model_path", "") or ""),
        model_name=str(d.get("model_name", "") or ""),
        n_ctx=int(d.get("n_ctx", 0) or 0),
        n_threads=int(d.get("n_threads", 0) or 0),
        n_gpu_layers=int(d.get("n_gpu_layers", 0) or 0),
        batch_size=int(d.get("batch_size", 0) or 0),
        loaded=bool(d.get("loaded", False)),
        last_error=str(d.get("last_error", "") or ""),
        snapshot=dict(d.get("snapshot", {}) or {}),
        updated_at=float(d.get("updated_at", time.time()) or time.time()),
    )


def _coerce_memory(d: Dict[str, Any]) -> MemoryState:
    return MemoryState(
        user_db=str(d.get("user_db", "") or ""),
        agent_db=str(d.get("agent_db", "") or ""),
        memory_db=str(d.get("memory_db", "") or ""),
        stats=dict(d.get("stats", {}) or {}),
        updated_at=float(d.get("updated_at", time.time()) or time.time()),
    )


def _coerce_goals(d: Dict[str, Any]) -> GoalState:
    return GoalState(
        active=list(d.get("active", []) or []),
        queued=list(d.get("queued", []) or []),
        completed=list(d.get("completed", []) or []),
        updated_at=float(d.get("updated_at", time.time()) or time.time()),
    )


def _coerce_capabilities(d: Dict[str, Any]) -> CapabilityState:
    return CapabilityState(
        inventory=dict(d.get("inventory", {}) or {}),
        updated_at=float(d.get("updated_at", time.time()) or time.time()),
    )


def _from_dict(d: Dict[str, Any]) -> WorldModel:
    return WorldModel(
        schema_version=int(d.get("schema_version", 1) or 1),
        updated_at=float(d.get("updated_at", time.time()) or time.time()),
        identity=_coerce_identity(dict(d.get("identity", {}) or {})),
        runtime=_coerce_runtime(dict(d.get("runtime", {}) or {})),
        memory=_coerce_memory(dict(d.get("memory", {}) or {})),
        goals=_coerce_goals(dict(d.get("goals", {}) or {})),
        capabilities=_coerce_capabilities(dict(d.get("capabilities", {}) or {})),
        preferences=dict(d.get("preferences", {}) or {}),
        context=dict(d.get("context", {}) or {}),
        observations=list(d.get("observations", []) or []),
    )


def load_world_model(force_reload: bool = False) -> WorldModel:
    global _WORLD
    with _LOCK:
        if _WORLD is not None and not force_reload:
            return _WORLD

        p = _world_model_path()
        if p.exists():
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
                _WORLD = _from_dict(dict(raw or {}))
                return _WORLD
            except Exception as _wm_err:
                log.warning(
                    "[world_model] Failed to parse world model at %s — keeping file intact, "
                    "starting fresh in memory: %s", p, _wm_err
                )
                _WORLD = WorldModel()
                return _WORLD

        _WORLD = WorldModel()
        save_world_model(_WORLD)
        return _WORLD


def get_world_model(force_reload: bool = False) -> WorldModel:
    return load_world_model(force_reload=force_reload)


def save_world_model(model: Optional[WorldModel] = None) -> Path:
    with _LOCK:
        m = model or load_world_model()
        m.updated_at = time.time()
        p = _world_model_path()
        p.write_text(json.dumps(m.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return p


def world_model_snapshot() -> Dict[str, Any]:
    return get_world_model().to_dict()


def set_preferred_name(name: str, confidence: float = 1.0) -> None:
    name = str(name or "").strip()
    if not name:
        return
    with _LOCK:
        wm = get_world_model()
        wm.identity.preferred_name = name
        wm.identity.confidence = float(confidence)
        wm.identity.updated_at = time.time()
        save_world_model(wm)


def merge_runtime_snapshot(snapshot: Dict[str, Any]) -> None:
    snap = dict(snapshot or {})
    with _LOCK:
        wm = get_world_model()
        wm.runtime.provider = str(snap.get("provider", wm.runtime.provider) or wm.runtime.provider)
        wm.runtime.model_path = str(snap.get("model_path", wm.runtime.model_path) or wm.runtime.model_path)
        wm.runtime.model_name = str(snap.get("model_name", wm.runtime.model_name) or wm.runtime.model_name)
        wm.runtime.n_ctx = int(snap.get("n_ctx", wm.runtime.n_ctx) or wm.runtime.n_ctx or 0)
        wm.runtime.n_threads = int(snap.get("n_threads", wm.runtime.n_threads) or wm.runtime.n_threads or 0)
        wm.runtime.n_gpu_layers = int(snap.get("n_gpu_layers", wm.runtime.n_gpu_layers) or wm.runtime.n_gpu_layers or 0)
        wm.runtime.batch_size = int(snap.get("batch_size", wm.runtime.batch_size) or wm.runtime.batch_size or 0)
        wm.runtime.loaded = bool(snap.get("loaded", wm.runtime.loaded))
        wm.runtime.last_error = str(snap.get("last_error", wm.runtime.last_error) or wm.runtime.last_error)
        wm.runtime.snapshot = snap
        wm.runtime.updated_at = time.time()
        save_world_model(wm)


def merge_memory_snapshot(snapshot: Dict[str, Any]) -> None:
    snap = dict(snapshot or {})
    with _LOCK:
        wm = get_world_model()
        wm.memory.user_db = str(snap.get("user_db", wm.memory.user_db) or wm.memory.user_db)
        wm.memory.agent_db = str(snap.get("agent_db", wm.memory.agent_db) or wm.memory.agent_db)
        wm.memory.memory_db = str(snap.get("memory_db", wm.memory.memory_db) or wm.memory.memory_db)
        wm.memory.stats = snap
        wm.memory.updated_at = time.time()
        save_world_model(wm)


def append_observation(kind: str, payload: Dict[str, Any], limit: int = 200) -> None:
    item = {
        "kind": str(kind or "").strip(),
        "payload": dict(payload or {}),
        "ts": time.time(),
    }
    with _LOCK:
        wm = get_world_model()
        wm.observations.append(item)
        if len(wm.observations) > limit:
            wm.observations = wm.observations[-limit:]
        save_world_model(wm)
