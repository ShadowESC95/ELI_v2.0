from __future__ import annotations
import shutil
from pathlib import Path
from time import time
from typing import Optional
from eli.world.persistence.storage import STATE_PATH

SNAPSHOT_DIR = Path("artifacts/world/snapshots")

def create_snapshot(label: str = "snapshot") -> Optional[Path]:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    if not STATE_PATH.exists():
        return None
    safe_label = "".join(c if c.isalnum() or c in "-_" else "_" for c in label)[:80]
    out = SNAPSHOT_DIR / f"{int(time())}_{safe_label}.json"
    shutil.copy2(STATE_PATH, out)
    return out

def latest_snapshot() -> Optional[Path]:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    snapshots = sorted(SNAPSHOT_DIR.glob("*.json"))
    return snapshots[-1] if snapshots else None

def restore_snapshot(path: Optional[Path] = None) -> bool:
    target = path or latest_snapshot()
    if not target or not target.exists():
        return False
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, STATE_PATH)
    return True
