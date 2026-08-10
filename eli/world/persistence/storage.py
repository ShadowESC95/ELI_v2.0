from __future__ import annotations
import json
import os
import tempfile
import threading
from pathlib import Path
from time import time
from typing import Any, Dict
from eli.world.agency.world_constitution import get_world_constitution, get_world_identity
from eli.world.core.ontology import get_default_rooms
from eli.world.core.schemas import AwarenessState, AvatarState, EliWorldState, WorldAction, WorldEvent, WorldObject

from eli.utils.log import get_logger

log = get_logger(__name__)


def _world_dir() -> Path:
    """Return the absolute path to the world state directory.

    Uses get_paths() so the directory resolves correctly regardless of
    working directory — critical because this module is imported from
    multiple entry points (GUI, daemon, CLI) that may set cwd differently.
    Relative Path("artifacts/world") would fail silently when cwd is not
    the project root, causing load() to create a default state with
    room="core_room" every time, overriding the persisted room placement.
    """
    try:
        from eli.core.paths import get_paths as _gp
        return Path(_gp().artifacts_dir) / "world"
    except Exception:
        # Fallback: resolve relative to this file → project root / artifacts / world
        return Path(__file__).resolve().parents[4] / "artifacts" / "world"


def world_dir() -> Path:
    """Public accessor for the world state directory.

    Exported so journal/provenance/snapshots resolve the same way instead of
    each hardcoding a relative ``Path("artifacts/world/...")`` — three of them
    did, and the docstring on _world_dir above already records why that fails.
    """
    return _world_dir()


WORLD_DIR = _world_dir()
STATE_PATH = WORLD_DIR / "eli_world_state.json"
EVENTS_PATH = WORLD_DIR / "events.jsonl"
ACTIONS_PATH = WORLD_DIR / "actions.jsonl"
_CORRUPT_BACKUP_KEEP = 5
# Serialises the read-modify-write swap across the GUI turn, the proactive
# daemon and the world panel timer, which all touch this file concurrently.
_SAVE_LOCK = threading.RLock()

def _ensure() -> None:
    WORLD_DIR.mkdir(parents=True, exist_ok=True)

# The world fires an action on every autonomy tick and these files are appended
# to forever. Nothing rotated them: actions.jsonl reached 41MB / 80,576 lines and
# events.jsonl 6.2MB on a normal desktop, growing for as long as ELI runs, and
# nothing ever reads them whole — the panel and the journal want the recent tail.
# Corrupt state backups were already pruned here; the logs simply were not.
_JSONL_MAX_LINES = int(os.environ.get("ELI_WORLD_LOG_MAX_LINES", "20000"))
_JSONL_CHECK_EVERY = 250          # stat() cost, not a rewrite, on most appends
_jsonl_since_check: Dict[str, int] = {}


def _trim_jsonl(path: Path, max_lines: int = 0) -> None:
    """Keep the newest `max_lines` of an append-only log. Never raises.

    Counted rather than size-capped so a trim never splits a JSON line in half,
    and checked every N appends so the common path stays a dict increment.

    The counter lives in this process only, so "every N appends" alone leaves a
    hole: a run that appends fewer than N entries never checks at all, and the
    file grows across restarts untouched. events.jsonl was found at 23,179 lines
    against a 20,000 cap for exactly that reason while the busier actions.jsonl
    had been trimmed correctly. So the FIRST append to a path in a given process
    always checks — one stat at startup — and the amortised counter takes over
    from there.
    """
    limit = max_lines or _JSONL_MAX_LINES
    if limit <= 0:
        return
    key = str(path)
    if key in _jsonl_since_check:
        n = _jsonl_since_check[key] + 1
        if n < _JSONL_CHECK_EVERY:
            _jsonl_since_check[key] = n
            return
    _jsonl_since_check[key] = 0
    try:
        if not path.exists():
            return
        with path.open("r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        if len(lines) <= limit:
            return
        keep_lines = lines[-limit:]
        tmp = path.with_suffix(path.suffix + ".trim")
        with tmp.open("w", encoding="utf-8") as f:
            f.writelines(keep_lines)
        os.replace(tmp, path)      # atomic; a crash mid-trim leaves the original
        log.debug("world log %s trimmed %d → %d lines", path.name, len(lines), len(keep_lines))
    except Exception:
        log.debug("world log trim failed for %s", path, exc_info=True)


def _prune_corrupt_backups(keep: int = _CORRUPT_BACKUP_KEEP) -> None:
    """Keep only the newest corrupt-state backups to avoid unbounded disk use."""
    try:
        backups = sorted(
            WORLD_DIR.glob(f"{STATE_PATH.stem}.corrupt_*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in backups[keep:]:
            try:
                old.unlink()
            except Exception:
                pass
    except Exception:
        pass

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
            _prune_corrupt_backups()
            state = EliWorldState(identity=get_world_identity(), constitution=get_world_constitution(), rooms=get_default_rooms())
            self.save(state)
            return state

    def save(self, state: EliWorldState) -> None:
        """Atomically persist the world state.

        The scratch file is unique per write and the swap is serialised. A
        single fixed ".tmp" name raced: the GUI turn, the proactive daemon and
        the world panel all write this file, and every read is a write (see
        EliWorldAutonomyEngine.load), so two writers would create the same tmp,
        the first replace() would consume it, and the second raised
        FileNotFoundError mid-turn — which in turn knocked out the persona
        handoff's self-status injection.
        """
        _ensure()
        state.timestamp = time()
        payload = json.dumps(state.to_dict(), indent=2, ensure_ascii=False)
        with _SAVE_LOCK:
            fd, tmp_name = tempfile.mkstemp(
                dir=str(self.state_path.parent),
                prefix=f"{self.state_path.stem}.",
                suffix=".tmp",
            )
            tmp = Path(tmp_name)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(payload)
                    fh.flush()
                    os.fsync(fh.fileno())
                tmp.replace(self.state_path)
            except Exception:
                try:
                    tmp.unlink(missing_ok=True)
                except Exception:
                    log.debug("world-state scratch cleanup failed", exc_info=True)
                raise

    def append_event(self, event: WorldEvent) -> None:
        _ensure()
        with EVENTS_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event.__dict__, ensure_ascii=False) + "\n")
        _trim_jsonl(EVENTS_PATH)

    def append_action(self, action: WorldAction) -> None:
        _ensure()
        with ACTIONS_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(action.__dict__, ensure_ascii=False) + "\n")
        _trim_jsonl(ACTIONS_PATH)
