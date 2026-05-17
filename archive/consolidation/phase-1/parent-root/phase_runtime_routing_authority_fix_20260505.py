from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT = Path.cwd()
STAMP = time.strftime("%Y%m%d_%H%M%S")
PHASE = f"phase_runtime_routing_authority_fix_{STAMP}"
BACKUP = ROOT / "ops" / "backups" / PHASE
REPORT = ROOT / "ops" / "reports" / PHASE
BACKUP.mkdir(parents=True, exist_ok=True)
REPORT.mkdir(parents=True, exist_ok=True)

TARGETS = [
    ROOT / "eli/runtime/reasoning_status.py",
    ROOT / "eli/runtime/deterministic_introspection.py",
    ROOT / "eli/execution/router_enhanced.py",
    ROOT / "eli/execution/executor_enhanced.py",
    ROOT / "eli/gui/eli_pro_audio_gui_MKI.py",
    ROOT / "eli/kernel/engine.py",
    ROOT / "eli/runtime/control_contracts.py",
    ROOT / "eli/runtime/response_contracts.py",
    ROOT / "tests/test_runtime_routing_authority_fix.py",
]

def backup_file(path: Path):
    if path.exists():
        dst = BACKUP / path.relative_to(ROOT)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dst)

def write(path: Path, text: str):
    backup_file(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")

def patch(path: Path, fn):
    if not path.exists():
        print(f"[SKIP missing] {path}")
        return
    backup_file(path)
    old = path.read_text(encoding="utf-8", errors="replace")
    new = fn(old)
    if new != old:
        path.write_text(new, encoding="utf-8")
        print(f"[PATCHED] {path.relative_to(ROOT)}")
    else:
        print(f"[UNCHANGED] {path.relative_to(ROOT)}")

# ---------------------------------------------------------------------
# 1. First-class reasoning-mode status surface.
# ---------------------------------------------------------------------

write(
    ROOT / "eli/runtime/reasoning_status.py",
    '''from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_MODE_LABELS = {
    "quick": "Quick",
    "chain_of_thought": "Chain of Thought",
    "cot": "Chain of Thought",
    "self_consistency": "Self-Consistency",
    "tree_of_thoughts": "Tree of Thoughts",
    "constitutional_ai": "Constitutional AI",
    "const_ai": "Constitutional AI",
}

_ATTRS = (
    "reasoning_mode",
    "active_reasoning_mode",
    "current_reasoning_mode",
    "_reasoning_mode",
    "_active_reasoning_mode",
    "_current_reasoning_mode",
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
        return "quick"
    raw = raw.replace("⚡", "").replace("🔗", "").replace("🔄", "").replace("🌳", "").replace("⚖️", "").strip()
    low = raw.lower().replace("-", "_").replace(" ", "_")
    if low in {"co_t", "cot", "chain", "chain_of_thought"}:
        return "chain_of_thought"
    if low in {"self_c", "self_consistency", "selfconsistent"}:
        return "self_consistency"
    if low in {"tot", "tree", "tree_of_thoughts"}:
        return "tree_of_thoughts"
    if low in {"const", "const_ai", "constitutional", "constitutional_ai"}:
        return "constitutional_ai"
    if low in {"quick", "fast"}:
        return "quick"
    return low

def _settings_paths() -> list[Path]:
    root = Path(os.environ.get("ELI_PROJECT_ROOT", ".")).resolve()
    here = Path.cwd().resolve()
    return [
        here / "config" / "settings.json",
        root / "config" / "settings.json",
    ]

def _mode_from_settings() -> str:
    for path in _settings_paths():
        try:
            if not path.exists():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for key in _SETTING_KEYS:
                    if data.get(key):
                        return _norm(data.get(key))
                modes = data.get("reasoning_modes")
                if isinstance(modes, dict):
                    active = modes.get("active") or modes.get("default")
                    if active:
                        return _norm(active)
        except Exception:
            continue
    return ""

def current_reasoning_mode(engine: Any = None) -> str:
    if engine is not None:
        for attr in _ATTRS:
            try:
                value = getattr(engine, attr, None)
            except Exception:
                value = None
            if value:
                return _norm(value)

    env = os.environ.get("ELI_REASONING_MODE") or os.environ.get("ELI_ACTIVE_REASONING_MODE")
    if env:
        return _norm(env)

    settings = _mode_from_settings()
    if settings:
        return settings

    return "quick"

def current_reasoning_mode_label(engine: Any = None) -> str:
    key = current_reasoning_mode(engine)
    try:
        from eli.cognition.reasoning_modes import mode_display
        label = mode_display(key)
        if label:
            return str(label)
    except Exception:
        pass
    return _MODE_LABELS.get(key, key.replace("_", " ").title())

def current_reasoning_mode_text(engine: Any = None) -> str:
    return f"Current reasoning mode: {current_reasoning_mode_label(engine)}"

__all__ = [
    "current_reasoning_mode",
    "current_reasoning_mode_label",
    "current_reasoning_mode_text",
]
''',
)

# ---------------------------------------------------------------------
# 2. deterministic_introspection: stop treating "reasoning mode" as full diagnostics.
# ---------------------------------------------------------------------

def patch_deterministic(text: str) -> str:
    marker = "ELI_REASONING_MODE_STATUS_FIX_20260505"

    old = 'if re.search(r"\\b(cognition pipeline|reasoning mode|input to output|cognition runtime)\\b", low):'
    if old in text:
        new = f'''# {marker}: exact mode-status request is not a full diagnostic report.
    if re.search(r"\\breasoning mode\\b", low) and not re.search(r"\\b(cognition pipeline|input to output|cognition runtime|diagnostic|diagnostics|audit|every step|explain)\\b", low):
        return "REASONING_MODE_STATUS"

    if re.search(r"\\b(cognition pipeline|input to output|cognition runtime)\\b", low):'''
        text = text.replace(old, new)

    if marker not in text:
        print("[WARN] deterministic marker not inserted; source shape may differ")

    handler_needle = 'if action in {"SELF_REPORT", "RUNTIME_STATUS", "GUI_RUNTIME_AUDIT"}:'
    if handler_needle in text and "current_reasoning_mode_text(engine)" not in text:
        text = text.replace(
            handler_needle,
            '''if action == "REASONING_MODE_STATUS":
        try:
            from eli.runtime.reasoning_status import current_reasoning_mode_text
            return current_reasoning_mode_text(engine)
        except Exception:
            return "Current reasoning mode: Quick"

    ''' + handler_needle,
        )

    return text

patch(ROOT / "eli/runtime/deterministic_introspection.py", patch_deterministic)

# ---------------------------------------------------------------------
# 3. router_enhanced: exact reasoning-mode status action + grid follow-up.
# ---------------------------------------------------------------------

def patch_router(text: str) -> str:
    marker = "ELI_ROUTER_REASONING_MODE_STATUS_FIX_20260505"

    runtime_line = '    if re.search(r"\\b(cognition pipeline|input to output|every step|no vague descriptions|reasoning mode|current reasoning mode)\\b", low):'
    if runtime_line in text:
        replacement = f'''    # {marker}: answer the active mode label; do not hijack into full runtime diagnostics.
    if (
        re.fullmatch(r"(?:what(?:'s| is)|which is|tell me|show me)?\\s*(?:your|eli'?s|the|my)?\\s*(?:current|active)?\\s*reasoning mode(?:\\s*,?\\s*eli)?\\??", low)
        or re.search(r"\\b(?:what(?:'s| is)|which|current|active)\\b.{{0,40}}\\breasoning mode\\b", low)
    ):
        return _mk("REASONING_MODE_STATUS", {{}}, 0.995, matched_by="reasoning.mode_status", allow_chat_without_evidence=False)

    if re.search(r"\\b(cognition pipeline|input to output|every step|no vague descriptions)\\b", low):'''
        text = text.replace(runtime_line, replacement)

    # Add grid reply recovery inside the tiny-fragment guard, immediately before the canned incomplete message.
    grid_marker = "ELI_GRID_FOLLOWUP_FIX_20260505"
    if grid_marker not in text:
        m = re.search(r'(?m)^(\s*)msg = f"I only caught:', text)
        if m:
            indent = m.group(1)
            block_lines = [
                f"# {grid_marker}: bare layout replies are valid after screen/grid prompts.",
                "_grid_text = str(raw or '').strip().lower().replace('×', 'x')",
                "_grid_text = re.sub(r'\\btree\\b', '3', _grid_text)",
                "_grid_text = re.sub(r'\\bthree\\b', '3', _grid_text)",
                "_grid_text = re.sub(r'\\btwo\\b', '2', _grid_text)",
                "_grid_text = re.sub(r'\\bfour\\b', '4', _grid_text)",
                "_grid_m = re.fullmatch(r'(\\d{1,2})\\s*(?:x|by)\\s*(\\d{1,2})', _grid_text)",
                "if _grid_m:",
                "    _cols, _rows = int(_grid_m.group(1)), int(_grid_m.group(2))",
                "    if 1 <= _cols <= 8 and 1 <= _rows <= 8:",
                "        return _mk('TILE_WINDOWS', {'cols': _cols, 'rows': _rows, 'grid': [_cols, _rows]}, 0.985, matched_by='window.grid_followup')",
            ]
            block = "\n".join(indent + line for line in block_lines)
            text = text[:m.start()] + block + "\n" + text[m.start():]
        else:
            print("[WARN] tiny-fragment message site not found; grid follow-up patch not inserted")

    return text

patch(ROOT / "eli/execution/router_enhanced.py", patch_router)

# ---------------------------------------------------------------------
# 4. executor_enhanced: support REASONING_MODE_STATUS without GGUF.
# ---------------------------------------------------------------------

def patch_executor(text: str) -> str:
    marker = "ELI_REASONING_MODE_EXECUTOR_FIX_20260505"

    # Add action to supported-action surfaces if simple string surfaces exist.
    if "'RUNTIME_STATUS'," in text and "'REASONING_MODE_STATUS'," not in text:
        text = text.replace("'RUNTIME_STATUS',", "'RUNTIME_STATUS',\n    'REASONING_MODE_STATUS',", 1)

    if marker not in text:
        text += f'''

# {marker}
_ELI_REASONING_MODE_ORIG_EXECUTE = globals().get("execute")
_ELI_REASONING_MODE_ORIG_EXECUTE_ACTION = globals().get("execute_action")

def _eli_reasoning_mode_execute(action, args=None, *pargs, **kwargs):
    action_name = str(action or "").upper()
    if action_name == "REASONING_MODE_STATUS":
        try:
            from eli.runtime.reasoning_status import current_reasoning_mode_text
            msg = current_reasoning_mode_text()
        except Exception:
            msg = "Current reasoning mode: Quick"
        return {{"ok": True, "action": "REASONING_MODE_STATUS", "content": msg, "response": msg}}

    orig = _ELI_REASONING_MODE_ORIG_EXECUTE
    if callable(orig):
        return orig(action, args or {{}}, *pargs, **kwargs)

    orig_action = _ELI_REASONING_MODE_ORIG_EXECUTE_ACTION
    if callable(orig_action):
        return orig_action(action, args or {{}}, *pargs, **kwargs)

    return {{"ok": False, "action": action_name, "content": "Executor unavailable.", "response": "Executor unavailable."}}

execute = _eli_reasoning_mode_execute
execute_action = _eli_reasoning_mode_execute
'''
    return text

patch(ROOT / "eli/execution/executor_enhanced.py", patch_executor)

# ---------------------------------------------------------------------
# 5. GUI: make TILE_WINDOWS voice direct-exec, not CognitiveEngine/GGUF.
# ---------------------------------------------------------------------

def patch_gui(text: str) -> str:
    marker = "ELI_GUI_TILE_DIRECT_EXEC_FIX_20260505"

    if marker not in text:
        # The voice direct-exec allowlist contains this exact media/volume block in the audit.
        text = text.replace(
            '"VOLUME", "VOLUME_UP", "VOLUME_DOWN",',
            f'"VOLUME", "VOLUME_UP", "VOLUME_DOWN",\n                # {marker}\n                "TILE_WINDOWS", "MINIMISE_ALL", "RESTORE_WINDOWS",',
            1,
        )

    # If a second capability/category list exists, expose reasoning status there too if safe.
    if '"RUNTIME_STATUS", "MEMORY_STATUS", "COGNITION_STATUS"' in text and '"REASONING_MODE_STATUS"' not in text:
        text = text.replace(
            '"RUNTIME_STATUS", "MEMORY_STATUS", "COGNITION_STATUS"',
            '"RUNTIME_STATUS", "REASONING_MODE_STATUS", "MEMORY_STATUS", "COGNITION_STATUS"',
        )

    return text

patch(ROOT / "eli/gui/eli_pro_audio_gui_MKI.py", patch_gui)

# ---------------------------------------------------------------------
# 6. Engine/control contracts: direct terminal action sets.
# ---------------------------------------------------------------------

def patch_engine(text: str) -> str:
    # Reasoning-mode status belongs beside runtime status in deterministic/control surfaces.
    text = text.replace(
        '"RUNTIME_STATUS", "MEMORY_STATUS", "COGNITION_STATUS"',
        '"RUNTIME_STATUS", "REASONING_MODE_STATUS", "MEMORY_STATUS", "COGNITION_STATUS"',
    )
    text = text.replace(
        '"EXPLAIN_LAST_RESPONSE", "RUNTIME_STATUS", "MEMORY_STATUS", "COGNITION_STATUS"',
        '"EXPLAIN_LAST_RESPONSE", "RUNTIME_STATUS", "REASONING_MODE_STATUS", "MEMORY_STATUS", "COGNITION_STATUS"',
    )

    # TILE_WINDOWS should terminate like media/volume/system actions, not synthesize an LLM response.
    text = text.replace(
        '"NEXT_MEDIA", "PREVIOUS_MEDIA", "VOLUME"',
        '"NEXT_MEDIA", "PREVIOUS_MEDIA", "VOLUME", "TILE_WINDOWS"',
    )
    text = text.replace(
        '"VOLUME", "CLARIFY_COMMAND", "CANCEL_INSTALL"',
        '"VOLUME", "TILE_WINDOWS", "CLARIFY_COMMAND", "CANCEL_INSTALL"',
    )
    return text

patch(ROOT / "eli/kernel/engine.py", patch_engine)

def patch_contracts(text: str) -> str:
    if '"RUNTIME_STATUS"' in text and '"REASONING_MODE_STATUS"' not in text:
        text = text.replace('"RUNTIME_STATUS"', '"RUNTIME_STATUS",\n    "REASONING_MODE_STATUS"', 1)
    if "'RUNTIME_STATUS'" in text and "'REASONING_MODE_STATUS'" not in text:
        text = text.replace("'RUNTIME_STATUS'", "'RUNTIME_STATUS',\n    'REASONING_MODE_STATUS'", 1)
    return text

patch(ROOT / "eli/runtime/control_contracts.py", patch_contracts)
patch(ROOT / "eli/runtime/response_contracts.py", patch_contracts)

# ---------------------------------------------------------------------
# 7. Regression tests.
# ---------------------------------------------------------------------

write(
    ROOT / "tests/test_runtime_routing_authority_fix.py",
    '''from __future__ import annotations

def _route(text: str):
    from eli.execution import router_enhanced
    if hasattr(router_enhanced, "route"):
        return router_enhanced.route(text)
    return router_enhanced.route_intent(text)

def test_reasoning_mode_question_is_not_runtime_status():
    r = _route("what is your reasoning mode")
    assert isinstance(r, dict)
    assert r.get("action") == "REASONING_MODE_STATUS"
    assert r.get("action") != "RUNTIME_STATUS"

def test_reasoning_mode_with_eli_suffix_is_not_runtime_status():
    r = _route("what is your reasoning mode, eli?")
    assert isinstance(r, dict)
    assert r.get("action") == "REASONING_MODE_STATUS"

def test_cognition_pipeline_still_routes_to_runtime_status():
    r = _route("explain the cognition pipeline input to output")
    assert isinstance(r, dict)
    assert r.get("action") == "RUNTIME_STATUS"

def test_optimize_screen_routes_tile_windows():
    r = _route("optimize my screen")
    assert isinstance(r, dict)
    assert r.get("action") == "TILE_WINDOWS"

def test_bare_grid_reply_routes_tile_windows():
    r = _route("4x2")
    assert isinstance(r, dict)
    assert r.get("action") == "TILE_WINDOWS"
    args = r.get("args") or {}
    assert args.get("cols") == 4
    assert args.get("rows") == 2

def test_stt_tree_means_three_for_grid_reply():
    r = _route("2x tree")
    assert isinstance(r, dict)
    assert r.get("action") == "TILE_WINDOWS"
    args = r.get("args") or {}
    assert args.get("cols") == 2
    assert args.get("rows") == 3

def test_reasoning_mode_executor_surface():
    from eli.execution import executor_enhanced
    fn = getattr(executor_enhanced, "execute_action", None) or getattr(executor_enhanced, "execute")
    out = fn("REASONING_MODE_STATUS", {})
    assert isinstance(out, dict)
    assert out.get("ok") is True
    assert "Current reasoning mode:" in (out.get("content") or out.get("response") or "")
''',
)

# ---------------------------------------------------------------------
# 8. Compile + focused tests.
# ---------------------------------------------------------------------

compile_targets = [
    "eli/runtime/reasoning_status.py",
    "eli/runtime/deterministic_introspection.py",
    "eli/execution/router_enhanced.py",
    "eli/execution/executor_enhanced.py",
    "eli/gui/eli_pro_audio_gui_MKI.py",
    "eli/kernel/engine.py",
    "eli/runtime/control_contracts.py",
    "eli/runtime/response_contracts.py",
    "tests/test_runtime_routing_authority_fix.py",
]

compile_cmd = [sys.executable, "-m", "py_compile", *compile_targets]
pytest_cmd = [
    sys.executable, "-m", "pytest", "-q",
    "tests/test_runtime_routing_authority_fix.py",
    "tests/test_reasoning_mode_contract.py",
    "tests/test_reasoning_surface_hardening.py",
    "tests/test_kernel_engine.py",
    "tests/test_runtime_modules.py",
]

def run(cmd, name):
    p = subprocess.run(cmd, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (REPORT / f"{name}.txt").write_text(p.stdout, encoding="utf-8")
    print(p.stdout)
    if p.returncode != 0:
        raise SystemExit(p.returncode)

run(compile_cmd, "py_compile")
run(pytest_cmd, "pytest_focused")

(REPORT / "SUMMARY.md").write_text(
    f"""# {PHASE}

Applied runtime routing authority fixes.

## Fixed
- `what is your reasoning mode` now routes to `REASONING_MODE_STATUS`, not `RUNTIME_STATUS`.
- `TILE_WINDOWS` is added to GUI voice direct-exec so screen optimization does not fall into GGUF.
- Bare grid follow-ups such as `4x2` and STT error `2x tree` route to `TILE_WINDOWS`.
- `REASONING_MODE_STATUS` added to executor/control surfaces.
- Focused regression tests added.

## Backups
{BACKUP}
""",
    encoding="utf-8",
)

print(f"✅ Applied {PHASE}")
print(f"Backups: {BACKUP}")
print(f"Report:  {REPORT}")
