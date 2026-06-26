"""Real, measured self-status for ELI.

So the persona cites TRUE telemetry — GPU temperature / utilisation / VRAM,
process uptime, and the actually-loaded model — instead of fabricating it
("thermal throttling stayed at 43°C", "overnight diagnostics ran clean") when
the user asks how it's doing. ELI has no thermal sensor of its own; the only
real source is the GPU driver. If that's unavailable, the honest answer is "I
don't track that", never an invented number.

100% local, offline (nvidia-smi is a local driver query, no network), and
model/hardware-agnostic. Never raises into callers.
"""
from __future__ import annotations

import json
import logging
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

# Module import happens at process boot, so this approximates ELI's uptime.
_PROC_START = time.time()


def _run(cmd: list[str], timeout: float = 2.0) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if out.returncode == 0:
            return (out.stdout or "").strip()
    except Exception:
        log.debug("self-status command failed: %s", cmd[:1], exc_info=True)
    return ""


def _gpu() -> Optional[dict[str, Any]]:
    """Real GPU telemetry via the local driver. None when no NVIDIA GPU / no smi."""
    out = _run([
        "nvidia-smi",
        "--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total",
        "--format=csv,noheader,nounits",
    ])
    if not out:
        return None
    parts = [p.strip() for p in out.splitlines()[0].split(",")]
    if len(parts) < 5:
        return None
    try:
        return {
            "name": parts[0],
            "temp_c": int(float(parts[1])),
            "util_pct": int(float(parts[2])),
            "vram_used_mb": int(float(parts[3])),
            "vram_total_mb": int(float(parts[4])),
        }
    except Exception:
        return None


def _uptime_str() -> str:
    s = max(0, int(time.time() - _PROC_START))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {sec}s"
    return f"{sec}s"


def _model() -> dict[str, Any]:
    try:
        from eli.core.paths import get_paths
        p = Path(get_paths().artifacts_dir) / "runtime_snapshot.json"
        if not p.exists():
            return {}
        d = json.loads(p.read_text(encoding="utf-8"))
        return {k: d.get(k) for k in ("model_path", "n_ctx", "n_gpu_layers", "n_batch")
                if d.get(k) is not None}
    except Exception:
        return {}


def get_self_status() -> dict[str, Any]:
    """Real measured status. Always returns a dict; fields absent when unavailable."""
    st: dict[str, Any] = {"uptime": _uptime_str()}
    g = _gpu()
    if g:
        st["gpu"] = g
    m = _model()
    if m:
        st["model"] = m
    return st


def render_self_status_block() -> str:
    """Compact, prompt-ready lines of REAL self-status. '' if nothing measurable."""
    st = get_self_status()
    lines: list[str] = []
    g = st.get("gpu")
    if isinstance(g, dict):
        lines.append(
            f"  GPU: {g['name']} — {g['temp_c']}°C, {g['util_pct']}% util, "
            f"{g['vram_used_mb']}/{g['vram_total_mb']} MB VRAM"
        )
    m = st.get("model")
    if isinstance(m, dict) and m:
        name = Path(str(m.get("model_path", ""))).name or "unknown"
        lines.append(
            f"  Model: {name} (ctx={m.get('n_ctx', '?')}, gpu_layers={m.get('n_gpu_layers', '?')})"
        )
    lines.append(
        f"  Process uptime: {st['uptime']} (ELI does not sleep — it idles between turns)"
    )
    if not isinstance(g, dict):
        lines.append(
            "  GPU telemetry: unavailable (no nvidia-smi) — say you don't track it; "
            "do NOT invent a temperature"
        )
    return "\n".join(lines)
