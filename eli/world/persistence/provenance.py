from __future__ import annotations
import json
from hashlib import sha1
from pathlib import Path
from time import time
from typing import Any, Dict, Optional

LEDGER_PATH = Path("artifacts/world/ledger/provenance.jsonl")

def make_provenance_id(action_type: str, reason: str, payload: Dict[str, Any]) -> str:
    raw = json.dumps({"action_type": action_type, "reason": reason, "payload": payload, "t": time()}, sort_keys=True, ensure_ascii=False)
    return sha1(raw.encode("utf-8")).hexdigest()[:16]

def record_provenance(*, provenance_id: str, actor: str, trigger_event: Optional[Dict[str, Any]], action: Dict[str, Any], awareness: Dict[str, Any], autonomous: bool) -> None:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    row = {"provenance_id": provenance_id, "actor": actor, "trigger_event": trigger_event, "action": action, "awareness": awareness, "autonomous": autonomous, "timestamp": time()}
    with LEDGER_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
