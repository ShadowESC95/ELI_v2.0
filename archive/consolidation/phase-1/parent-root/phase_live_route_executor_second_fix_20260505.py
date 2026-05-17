from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path.cwd()
STAMP = time.strftime("%Y%m%d_%H%M%S")
PHASE = f"phase_live_route_executor_second_fix_{STAMP}"
BACKUP = ROOT / "ops" / "backups" / PHASE
REPORT = ROOT / "ops" / "reports" / PHASE
BACKUP.mkdir(parents=True, exist_ok=True)
REPORT.mkdir(parents=True, exist_ok=True)

FILES = [
    ROOT / "eli/runtime/reasoning_status.py",
    ROOT / "eli/execution/router_enhanced.py",
    ROOT / "eli/execution/executor_enhanced.py",
    ROOT / "eli/kernel/engine.py",
    ROOT / "tests/test_live_route_executor_second_fix.py",
]

def backup(path: Path):
    if path.exists():
        dst = BACKUP / path.relative_to(ROOT)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dst)

def write(path: Path, text: str):
    backup(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")

def patch(path: Path, fn):
    backup(path)
    old = path.read_text(encoding="utf-8", errors="replace")
    new = fn(old)
    if new != old:
        path.write_text(new, encoding="utf-8")
        print(f"[PATCHED] {path.relative_to(ROOT)}")
    else:
        print(f"[UNCHANGED] {path.relative_to(ROOT)}")

# ------------------------------------------------------------------
# 1. Replace reasoning_status with a live-aware version.
# ------------------------------------------------------------------

write(ROOT / "eli/runtime/reasoning_status.py", r'''from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

_MODE_LABELS = {
    "quick": "Quick",
    "chain_of_thought": "Chain of Thought",
    "cot": "Chain of Thought",
    "self_consistency": "Self-Consistency",
    "tree_of_thoughts": "Tree of Thoughts",
    "tot": "Tree of Thoughts",
    "constitutional_ai": "Constitutional AI",
    "const_ai": "Constitutional AI",
}

_ATTRS = (
    "reasoning_mode",
    "active_reasoning_mode",
    "current_reasoning_mode",
    "selected_reasoning_mode",
    "_reasoning_mode",
    "_active_reasoning_mode",
    "_current_reasoning_mode",
    "_selected_reasoning_mode",
    "_last_reasoning_mode",
    "_trace_reasoning_mode",
)

_SETTING_KEYS = (
    "reasoning_mode",
    "active_reasoning_mode",
    "current_reasoning_mode",
    "default_reasoning_mode",
)

def _norm(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    raw = raw.replace("⚡", "").replace("🔗", "").replace("🔄", "").replace("🌳", "").replace("⚖️", "").strip()
    low = raw.lower().replace("-", "_").replace(" ", "_")

    if "tree" in low or low in {"tot"}:
        return "tree_of_thoughts"
    if "constitutional" in low or "const" in low:
        return "constitutional_ai"
    if "self" in low and "consistency" in low:
        return "self_consistency"
    if "chain" in low or low in {"cot", "co_t"}:
        return "chain_of_thought"
    if "quick" in low or "fast" in low:
        return "quick"

    return low

def _label(key: str) -> str:
    key = _norm(key) or "quick"
    try:
        from eli.cognition.reasoning_modes import mode_display
        val = mode_display(key)
        if val:
            return str(val)
    except Exception:
        pass
    return _MODE_LABELS.get(key, key.replace("_", " ").title())

def _project_root() -> Path:
    return Path(os.environ.get("ELI_PROJECT_ROOT", Path.cwd())).resolve()

def _read_json(path: Path) -> dict:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}
    return {}

def _from_trace_files() -> str:
    root = _project_root()
    candidates = [
        root / "artifacts" / "runtime" / "last_trace.json",
        root / "artifacts" / "runtime" / "state.json",
        root / "artifacts" / "runtime_snapshot.json",
    ]
    for path in candidates:
        data = _read_json(path)
        stack = [data]
        while stack:
            obj = stack.pop()
            if isinstance(obj, dict):
                for k, v in obj.items():
                    lk = str(k).lower()
                    if ("reasoning" in lk and "mode" in lk) or lk in {"mode", "reasoning_mode"}:
                        n = _norm(v)
                        if n:
                            return n
                    if isinstance(v, (dict, list)):
                        stack.append(v)
            elif isinstance(obj, list):
                stack.extend(obj)
    return ""

def _from_settings() -> str:
    root = _project_root()
    for path in [root / "config" / "settings.json", Path.cwd() / "config" / "settings.json"]:
        data = _read_json(path)
        for key in _SETTING_KEYS:
            n = _norm(data.get(key))
            if n:
                return n
        modes = data.get("reasoning_modes")
        if isinstance(modes, dict):
            n = _norm(modes.get("active") or modes.get("default"))
            if n:
                return n
    return ""

def _from_engine(engine: Any) -> str:
    if engine is None:
        return ""

    for attr in _ATTRS:
        try:
            n = _norm(getattr(engine, attr, None))
        except Exception:
            n = ""
        if n:
            return n

    try:
        d = vars(engine)
    except Exception:
        d = {}

    for k, v in d.items():
        lk = str(k).lower()
        if "reason" in lk and "mode" in lk:
            n = _norm(v)
            if n:
                return n

    return ""

def current_reasoning_mode(engine: Any = None, override: Any = None) -> str:
    n = _norm(override)
    if n:
        return n

    n = _from_engine(engine)
    if n:
        return n

    for env_key in ("ELI_REASONING_MODE", "ELI_ACTIVE_REASONING_MODE", "ELI_CURRENT_REASONING_MODE"):
        n = _norm(os.environ.get(env_key))
        if n:
            return n

    n = _from_trace_files()
    if n:
        return n

    n = _from_settings()
    if n:
        return n

    return "quick"

def current_reasoning_mode_label(engine: Any = None, override: Any = None) -> str:
    return _label(current_reasoning_mode(engine, override=override))

def current_reasoning_mode_text(engine: Any = None, override: Any = None, explain: bool = True) -> str:
    label = current_reasoning_mode_label(engine, override=override)
    if not explain:
        return f"Current reasoning mode: {label}"
    return (
        f"Current reasoning mode: {label}\n\n"
        "Why it matters: this controls the routing depth, retrieval breadth, synthesis strategy, "
        "and whether the answer should be fast/direct or fully assembled. It does not mean private "
        "scratchpad, hidden branches, or chain-of-thought are exposed."
    )

__all__ = [
    "current_reasoning_mode",
    "current_reasoning_mode_label",
    "current_reasoning_mode_text",
]
''')

# ------------------------------------------------------------------
# 2. Router wrapper: grid trailing words, memory-internals, reasoning status.
# ------------------------------------------------------------------

def patch_router(text: str) -> str:
    marker = "ELI_LIVE_ROUTE_SECOND_FIX_20260505"
    if marker in text:
        return text

    text += r'''

# ELI_LIVE_ROUTE_SECOND_FIX_20260505
# High-priority route wrapper for cases the base router currently lets fall into CHAT/search.
import re as _eli_lrf_re

_ELI_LRF_ORIG_ROUTE = globals().get("route")
_ELI_LRF_ORIG_ROUTE_INTENT = globals().get("route_intent")

def _eli_lrf_mk(action, args=None, confidence=0.99, matched_by="eli.live_route_second_fix"):
    mk = globals().get("_mk")
    if callable(mk):
        try:
            return mk(action, args or {}, confidence, matched_by=matched_by, allow_chat_without_evidence=False)
        except TypeError:
            try:
                return mk(action, args or {}, confidence, matched_by=matched_by)
            except TypeError:
                pass
    return {
        "action": action,
        "args": args or {},
        "confidence": confidence,
        "meta": {"matched_by": matched_by, "allow_chat_without_evidence": False},
    }

def _eli_lrf_word_to_int(s):
    s = str(s or "").strip().lower()
    table = {
        "one": 1, "two": 2, "to": 2, "too": 2,
        "three": 3, "tree": 3, "free": 3,
        "four": 4, "for": 4, "fore": 4,
        "five": 5, "six": 6, "seven": 7, "eight": 8,
    }
    if s.isdigit():
        return int(s)
    return table.get(s)

def _eli_lrf_pre_route(text):
    raw = str(text or "").strip()
    low = raw.lower().strip()
    low = low.replace("×", "x")

    # Exact/near-exact mode query: status action only, not full RUNTIME_STATUS.
    if "reasoning mode" in low and not _eli_lrf_re.search(
        r"\b(cognition pipeline|input to output|every step|memory system|db tables|functions|files|runtime audit|diagnostic|diagnostics|full audit)\b",
        low,
    ):
        return _eli_lrf_mk("REASONING_MODE_STATUS", {}, 0.995, "reasoning.mode_status.second_fix")

    # Internal memory architecture question must not become document/search plugin output.
    if _eli_lrf_re.search(r"\b(memory system|memory internally|memory.*db tables|db tables|which files|which functions)\b", low) and _eli_lrf_re.search(r"\b(memory|db|sqlite|faiss|functions?|files?|internally|runtime)\b", low):
        return _eli_lrf_mk(
            "EXPLAIN_MEMORY_RUNTIME",
            {"question": raw, "detail": "full"},
            0.985,
            "memory.runtime_architecture.second_fix",
        )

    # Bare grid follow-up, including STT's "tree" for "three" and optional trailing "grid/layout/windows".
    m = _eli_lrf_re.fullmatch(
        r"\s*(\d{1,2}|one|two|three|tree|four|five|six|seven|eight)\s*(?:x|by)\s*(\d{1,2}|one|two|three|tree|four|five|six|seven|eight)\s*(?:grid|layout|windows?)?\s*",
        low,
    )
    if m:
        cols = _eli_lrf_word_to_int(m.group(1))
        rows = _eli_lrf_word_to_int(m.group(2))
        if cols and rows and 1 <= cols <= 8 and 1 <= rows <= 8:
            return _eli_lrf_mk(
                "TILE_WINDOWS",
                {"cols": cols, "rows": rows, "grid": [cols, rows]},
                0.995,
                "window.grid_followup.second_fix",
            )

    return None

def route(text, *args, **kwargs):
    pre = _eli_lrf_pre_route(text)
    if pre is not None:
        return pre
    if callable(_ELI_LRF_ORIG_ROUTE):
        return _ELI_LRF_ORIG_ROUTE(text, *args, **kwargs)
    if callable(_ELI_LRF_ORIG_ROUTE_INTENT):
        return _ELI_LRF_ORIG_ROUTE_INTENT(text, *args, **kwargs)
    return _eli_lrf_mk("CHAT", {"message": str(text or "")}, 0.5, "router.fallback.second_fix")

def route_intent(text, *args, **kwargs):
    pre = _eli_lrf_pre_route(text)
    if pre is not None:
        return pre
    if callable(_ELI_LRF_ORIG_ROUTE_INTENT):
        return _ELI_LRF_ORIG_ROUTE_INTENT(text, *args, **kwargs)
    if callable(_ELI_LRF_ORIG_ROUTE):
        return _ELI_LRF_ORIG_ROUTE(text, *args, **kwargs)
    return _eli_lrf_mk("CHAT", {"message": str(text or "")}, 0.5, "router_intent.fallback.second_fix")
'''
    return text

patch(ROOT / "eli/execution/router_enhanced.py", patch_router)

# ------------------------------------------------------------------
# 3. Executor wrapper: terminal REASONING_MODE_STATUS + visible-window TILE_WINDOWS.
# ------------------------------------------------------------------

def patch_executor(text: str) -> str:
    marker = "ELI_EXECUTOR_VISIBLE_TILE_SECOND_FIX_20260505"
    if marker in text:
        return text

    text += r'''

# ELI_EXECUTOR_VISIBLE_TILE_SECOND_FIX_20260505
# Terminal action wrappers. Must sit late in file to override previous execute wrappers.
import math as _eli_tile_math
import os as _eli_tile_os
import re as _eli_tile_re
import subprocess as _eli_tile_subprocess

_ELI_TILE_ORIG_EXECUTE = globals().get("execute")
_ELI_TILE_ORIG_EXECUTE_ACTION = globals().get("execute_action")

def _eli_tile_run(cmd, timeout=2):
    try:
        return _eli_tile_subprocess.run(
            cmd,
            text=True,
            stdout=_eli_tile_subprocess.PIPE,
            stderr=_eli_tile_subprocess.PIPE,
            timeout=timeout,
        )
    except Exception as e:
        class _R:
            returncode = 999
            stdout = ""
            stderr = str(e)
        return _R()

def _eli_tile_current_desktop():
    p = _eli_tile_run(["wmctrl", "-d"])
    if p.returncode != 0:
        return None
    for line in p.stdout.splitlines():
        if "*" in line:
            try:
                return int(line.split()[0])
            except Exception:
                return None
    return None

def _eli_tile_screen_size():
    p = _eli_tile_run(["xdotool", "getdisplaygeometry"])
    if p.returncode == 0:
        parts = p.stdout.strip().split()
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            return int(parts[0]), int(parts[1])

    p = _eli_tile_run(["xrandr", "--current"])
    if p.returncode == 0:
        m = _eli_tile_re.search(r"current\s+(\d+)\s+x\s+(\d+)", p.stdout)
        if m:
            return int(m.group(1)), int(m.group(2))

    return 1366, 768

def _eli_tile_xprop(wid):
    p = _eli_tile_run(["xprop", "-id", wid], timeout=1)
    return p.stdout if p.returncode == 0 else ""

def _eli_tile_visible_windows():
    p = _eli_tile_run(["wmctrl", "-lG", "-p"])
    if p.returncode != 0:
        return [], p.stderr.strip() or "wmctrl failed"

    curdesk = _eli_tile_current_desktop()
    wins = []

    for line in p.stdout.splitlines():
        parts = line.split(None, 8)
        if len(parts) < 9:
            continue

        wid, desk_s, pid_s, x_s, y_s, w_s, h_s, host, title = parts
        try:
            desk = int(desk_s)
            x, y, w, h = int(x_s), int(y_s), int(w_s), int(h_s)
        except Exception:
            continue

        if curdesk is not None and desk not in {curdesk, -1}:
            continue
        if w < 80 or h < 80:
            continue
        if not str(title or "").strip():
            continue

        xp = _eli_tile_xprop(wid)
        xp_low = xp.lower()

        # Skip hidden/minimized/taskbar-skipped/system surfaces.
        if "_net_wm_state_hidden" in xp_low:
            continue
        if "_net_wm_state_skip_taskbar" in xp_low:
            continue
        if "_net_wm_state_skip_pager" in xp_low:
            continue

        # Keep normal/dialog windows; skip docks, desktops, menus, tooltips, splash, etc.
        if "_net_wm_window_type" in xp_low:
            bad_types = (
                "_net_wm_window_type_desktop",
                "_net_wm_window_type_dock",
                "_net_wm_window_type_toolbar",
                "_net_wm_window_type_menu",
                "_net_wm_window_type_utility",
                "_net_wm_window_type_splash",
                "_net_wm_window_type_dropdown_menu",
                "_net_wm_window_type_popup_menu",
                "_net_wm_window_type_tooltip",
                "_net_wm_window_type_notification",
            )
            if any(t in xp_low for t in bad_types):
                continue

        wins.append({"id": wid, "desk": desk, "x": x, "y": y, "w": w, "h": h, "title": title})

    return wins, ""

def _eli_tile_parse_grid(args, count):
    args = args or {}
    grid = args.get("grid")
    cols = args.get("cols") or args.get("columns")
    rows = args.get("rows")

    if isinstance(grid, (list, tuple)) and len(grid) >= 2:
        cols = cols or grid[0]
        rows = rows or grid[1]

    try:
        cols = int(cols) if cols else 0
    except Exception:
        cols = 0
    try:
        rows = int(rows) if rows else 0
    except Exception:
        rows = 0

    if cols > 0 and rows > 0:
        return max(1, min(cols, 8)), max(1, min(rows, 8))

    if count <= 1:
        return 1, 1
    cols = int(_eli_tile_math.ceil(_eli_tile_math.sqrt(count)))
    rows = int(_eli_tile_math.ceil(count / cols))
    return max(1, cols), max(1, rows)

def _eli_tile_windows(args=None):
    wins, err = _eli_tile_visible_windows()
    if err:
        return {"ok": False, "action": "TILE_WINDOWS", "content": err, "response": err, "error": err}

    count = len(wins)
    if count == 0:
        msg = "No visible normal windows found to tile."
        return {"ok": False, "action": "TILE_WINDOWS", "content": msg, "response": msg, "count": 0}

    cols, rows = _eli_tile_parse_grid(args or {}, count)
    screen_w, screen_h = _eli_tile_screen_size()

    margin = int((args or {}).get("margin", 10) or 10)
    top_reserved = int((args or {}).get("top_reserved", 34) or 34)

    usable_x = margin
    usable_y = top_reserved + margin
    usable_w = max(300, screen_w - margin * 2)
    usable_h = max(240, screen_h - top_reserved - margin * 2)

    cell_w = max(180, usable_w // cols)
    cell_h = max(140, usable_h // rows)

    moved = 0
    for i, win in enumerate(wins[: cols * rows]):
        c = i % cols
        r = i // cols
        x = usable_x + c * cell_w
        y = usable_y + r * cell_h
        w = max(120, cell_w - margin)
        h = max(100, cell_h - margin)

        wid = win["id"]
        _eli_tile_run(["wmctrl", "-ir", wid, "-b", "remove,maximized_vert,maximized_horz"], timeout=1)
        p = _eli_tile_run(["wmctrl", "-ir", wid, "-e", f"0,{x},{y},{w},{h}"], timeout=2)
        if p.returncode == 0:
            moved += 1

    msg = f"Tiled {moved} visible window{'s' if moved != 1 else ''} into a {cols}×{rows} grid."
    if count > cols * rows:
        msg += f" {count - cols * rows} visible window(s) did not fit in the requested grid."

    return {
        "ok": moved > 0,
        "action": "TILE_WINDOWS",
        "content": msg,
        "response": msg,
        "count": moved,
        "visible_count": count,
        "grid": [cols, rows],
    }

def _eli_second_execute(action, args=None, *pargs, **kwargs):
    action_name = str(action or "").upper()
    args = args or {}

    if action_name == "REASONING_MODE_STATUS":
        try:
            from eli.runtime.reasoning_status import current_reasoning_mode_text
            msg = current_reasoning_mode_text()
        except Exception:
            msg = "Current reasoning mode: unavailable"
        return {"ok": True, "action": "REASONING_MODE_STATUS", "content": msg, "response": msg}

    if action_name == "TILE_WINDOWS":
        return _eli_tile_windows(args)

    if callable(_ELI_TILE_ORIG_EXECUTE):
        return _ELI_TILE_ORIG_EXECUTE(action, args, *pargs, **kwargs)
    if callable(_ELI_TILE_ORIG_EXECUTE_ACTION):
        return _ELI_TILE_ORIG_EXECUTE_ACTION(action, args, *pargs, **kwargs)

    msg = f"No executor available for {action_name}"
    return {"ok": False, "action": action_name, "content": msg, "response": msg}

execute = _eli_second_execute
execute_action = _eli_second_execute
'''
    return text

patch(ROOT / "eli/execution/executor_enhanced.py", patch_executor)

# ------------------------------------------------------------------
# 4. Engine wrapper: exact reasoning-mode question must not go through GGUF.
# ------------------------------------------------------------------

def patch_engine(text: str) -> str:
    marker = "ELI_ENGINE_REASONING_TERMINAL_SECOND_FIX_20260505"
    if marker in text:
        return text

    text += r'''

# ELI_ENGINE_REASONING_TERMINAL_SECOND_FIX_20260505
# Last-mile guard: if router returns REASONING_MODE_STATUS but process() would
# otherwise synthesize, terminate here with visible status text.
try:
    _ELI_ENGINE_SECOND_ORIG_PROCESS = CognitiveEngine.process

    def _eli_engine_second_is_reasoning_status_query(text):
        import re as _re
        low = str(text or "").lower()
        if "reasoning mode" not in low:
            return False
        if _re.search(r"\b(cognition pipeline|input to output|every step|memory system|db tables|runtime audit|diagnostic|diagnostics|full audit)\b", low):
            return False
        return True

    def _eli_engine_second_process(self, user_input="", *args, **kwargs):
        if _eli_engine_second_is_reasoning_status_query(user_input):
            override = None
            for k, v in kwargs.items():
                if "mode" in str(k).lower() and ("reason" in str(k).lower() or str(k).lower() == "mode"):
                    override = v
                    break
            try:
                from eli.runtime.reasoning_status import current_reasoning_mode_text
                return current_reasoning_mode_text(self, override=override)
            except Exception:
                return "Current reasoning mode: unavailable"

        return _ELI_ENGINE_SECOND_ORIG_PROCESS(self, user_input, *args, **kwargs)

    CognitiveEngine.process = _eli_engine_second_process
except Exception as _eli_engine_second_patch_error:
    print(f"[ELI_ENGINE_REASONING_TERMINAL_SECOND_FIX] failed: {_eli_engine_second_patch_error}", flush=True)
'''
    return text

patch(ROOT / "eli/kernel/engine.py", patch_engine)

# ------------------------------------------------------------------
# 5. Tests.
# ------------------------------------------------------------------

write(ROOT / "tests/test_live_route_executor_second_fix.py", r'''from __future__ import annotations

def _route(text: str):
    from eli.execution import router_enhanced
    fn = getattr(router_enhanced, "route", None) or getattr(router_enhanced, "route_intent")
    return fn(text)

def test_trailing_grid_routes_to_tile_windows():
    r = _route("2x tree grid")
    assert r["action"] == "TILE_WINDOWS"
    assert r["args"]["cols"] == 2
    assert r["args"]["rows"] == 3

def test_numeric_grid_routes_to_tile_windows():
    r = _route("4x2")
    assert r["action"] == "TILE_WINDOWS"
    assert r["args"]["grid"] == [4, 2]

def test_reasoning_mode_status_not_runtime_status():
    r = _route("what is your reasoning mode")
    assert r["action"] == "REASONING_MODE_STATUS"

def test_memory_internals_do_not_become_search_chat():
    r = _route("Tell me exactly how your memory system works internally — which files, which DB tables, which functions.")
    assert r["action"] == "EXPLAIN_MEMORY_RUNTIME"

def test_reasoning_status_override_label():
    from eli.runtime.reasoning_status import current_reasoning_mode_text
    s = current_reasoning_mode_text(override="tree_of_thoughts")
    assert "Tree of Thoughts" in s
''')

# ------------------------------------------------------------------
# 6. Verification.
# ------------------------------------------------------------------

compile_targets = [
    "eli/runtime/reasoning_status.py",
    "eli/execution/router_enhanced.py",
    "eli/execution/executor_enhanced.py",
    "eli/kernel/engine.py",
    "tests/test_live_route_executor_second_fix.py",
]

pytest_targets = [
    "tests/test_live_route_executor_second_fix.py",
    "tests/test_runtime_routing_authority_fix.py",
    "tests/test_reasoning_surface_hardening.py",
    "tests/test_reasoning_mode_contract.py",
]

def run(cmd, name):
    p = subprocess.run(cmd, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (REPORT / f"{name}.txt").write_text(p.stdout, encoding="utf-8")
    print(p.stdout)
    if p.returncode != 0:
        raise SystemExit(p.returncode)

run([sys.executable, "-m", "py_compile", *compile_targets], "py_compile")
run([sys.executable, "-m", "pytest", "-q", *pytest_targets], "pytest_focused")

(REPORT / "SUMMARY.md").write_text(f"""# {PHASE}

Second live routing hardening pass.

## Fixed
- `2x tree grid` / `4x2 grid` route to `TILE_WINDOWS`.
- `TILE_WINDOWS` now tiles visible normal windows only, not hidden/system/minimized surfaces.
- `what is your reasoning mode` terminates before GGUF.
- internal memory architecture questions route to `EXPLAIN_MEMORY_RUNTIME`, not document/search output.

## Backups
{BACKUP}
""", encoding="utf-8")

print(f"✅ Applied {PHASE}")
print(f"Backups: {BACKUP}")
print(f"Report:  {REPORT}")
