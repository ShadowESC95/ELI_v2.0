from __future__ import annotations
import json
from pathlib import Path
from time import time
from typing import Any, Dict
from eli.world.agency.world_constitution import get_world_constitution, get_world_identity
from eli.world.core.ontology import get_default_rooms
from eli.world.core.schemas import AwarenessState, AvatarState, EliWorldState, WorldAction, WorldEvent, WorldObject

WORLD_DIR = Path("artifacts/world")
STATE_PATH = WORLD_DIR / "eli_world_state.json"
EVENTS_PATH = WORLD_DIR / "events.jsonl"
ACTIONS_PATH = WORLD_DIR / "actions.jsonl"

def _ensure() -> None:
    WORLD_DIR.mkdir(parents=True, exist_ok=True)

def _state_from_dict(data: Dict[str, Any]) -> EliWorldState:
    state = EliWorldState()
    state.world_name = data.get("world_name", state.world_name)
    state.identity = data.get("identity") or get_world_identity()
    state.constitution = data.get("constitution") or get_world_constitution()
    state.awareness = AwarenessState(**data.get("awareness", {}))
    state.avatar = AvatarState(**data.get("avatar", {}))
    state.rooms = data.get("rooms") or get_default_rooms()
    state.objects = {k: WorldObject(**v) for k, v in data.get("objects", {}).items()}
    state.events = [WorldEvent(**e) for e in data.get("events", [])[-300:]]
    state.actions = [WorldAction(**a) for a in data.get("actions", [])[-300:]]
    state.goals = data.get("goals", [])
    state.habits = data.get("habits", [])
    state.timestamp = data.get("timestamp", time())
    return state

class EliWorldStorage:
    def __init__(self, state_path: Path = STATE_PATH):
        self.state_path = state_path
        _ensure()

    def load(self) -> EliWorldState:
        if not self.state_path.exists():
            state = EliWorldState(identity=get_world_identity(), constitution=get_world_constitution(), rooms=get_default_rooms())
            self.save(state)
            return state
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            return _state_from_dict(data)
        except Exception:
            corrupt = self.state_path.with_suffix(f".corrupt_{int(time())}.json")
            try:
                self.state_path.rename(corrupt)
            except Exception:
                pass
            state = EliWorldState(identity=get_world_identity(), constitution=get_world_constitution(), rooms=get_default_rooms())
            self.save(state)
            return state

    def save(self, state: EliWorldState) -> None:
        _ensure()
        state.timestamp = time()
        self.state_path.write_text(json.dumps(state.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def append_event(self, event: WorldEvent) -> None:
        _ensure()
        with EVENTS_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event.__dict__, ensure_ascii=False) + "\n")

    def append_action(self, action: WorldAction) -> None:
        _ensure()
        with ACTIONS_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(action.__dict__, ensure_ascii=False) + "\n")
