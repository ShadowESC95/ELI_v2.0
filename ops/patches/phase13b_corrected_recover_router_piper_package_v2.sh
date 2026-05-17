#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd -P)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase13b_corrected_recover_router_piper_package_${STAMP}"
BACKUP="$OUT/backups"

PREV_PHASE13="$(
  ls -td "$ROOT"/ops/reports/phase13_surface_integrity_package_repair_* \
    2>/dev/null | head -1 || true
)"

mkdir -p "$OUT" "$BACKUP"

exec > >(tee "$OUT/00_console.log") 2>&1

echo "======================================================================"
echo "PHASE 13B — Corrected Recovery + Router/TTS Package Repair"
echo "ROOT         : $ROOT"
echo "OUT          : $OUT"
echo "PREV PHASE13 : ${PREV_PHASE13:-<none>}"
echo "TIME         : $(date -Is)"
echo "======================================================================"
echo

if [ ! -d "$ROOT/eli" ] || [ ! -f "$ROOT/bin/elix" ]; then
  echo "FATAL: this is not the ELI project root:"
  echo "  $ROOT"
  false
fi

if [ -z "${PREV_PHASE13:-}" ]; then
  echo "FATAL: no prior Phase 13 report found."
  echo "Expected something like:"
  echo "  ops/reports/phase13_surface_integrity_package_repair_*"
  false
fi

PH13_ROUTER_BACKUP="$PREV_PHASE13/backups/eli/execution/router_enhanced.py"
PH13_ENGINE_BACKUP="$PREV_PHASE13/backups/eli/kernel/engine.py"

if [ ! -f "$PH13_ROUTER_BACKUP" ]; then
  echo "FATAL: Phase 13 router backup missing:"
  echo "  $PH13_ROUTER_BACKUP"
  false
fi

{
  echo "# Phase 13B Corrected Recovery + Router/TTS Package Repair"
  echo
  echo "- Date: $(date -Is)"
  echo "- Root: \`$ROOT\`"
  echo "- Prior Phase 13 report: \`$PREV_PHASE13\`"
  echo "- Python: \`$(python3 --version 2>&1)\`"
  echo "- Current PYTHONPATH: \`${PYTHONPATH-<unset>}\`"
  echo
} > "$OUT/SUMMARY.md"

echo "=== 0. Pre-repair file backups ==="
for rel in \
  "eli/execution/router_enhanced.py" \
  "eli/kernel/engine.py" \
  "eli/cognition/output_governor.py" \
  "eli/gui/labs_tab.py" \
  "eli/perception/tts_router.py" \
  "eli/runtime/visible_text.py" \
  "config/settings.json" \
  ".env.mkxi"
do
  SRC="$ROOT/$rel"
  DST="$BACKUP/$rel"
  if [ -f "$SRC" ]; then
    mkdir -p "$(dirname "$DST")"
    cp -a "$SRC" "$DST"
    echo "BACKUP $rel"
  else
    echo "MISSING $rel"
  fi
done
echo

echo "=== 1. Restore router_enhanced.py from clean Phase 13 backup ==="
cp -a "$PH13_ROUTER_BACKUP" "$ROOT/eli/execution/router_enhanced.py"
echo "RESTORED router:"
echo "  $ROOT/eli/execution/router_enhanced.py"
echo "FROM:"
echo "  $PH13_ROUTER_BACKUP"
echo

echo "=== 2. Apply SAFE append-only router guard ==="
python3 - "$ROOT" "$OUT" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

root = Path(sys.argv[1])
out = Path(sys.argv[2])
path = root / "eli/execution/router_enhanced.py"

src = path.read_text(encoding="utf-8")

marker = "# === PHASE13B_V2_APPEND_ONLY_ROUTE_SURFACE_GUARD ==="

if marker in src:
    print("SKIP: Phase 13B v2 router guard already present.")
    (out / "01_router_patch.txt").write_text(
        "SKIP: marker already present\n",
        encoding="utf-8",
    )
    raise SystemExit(0)

if "def route" not in src:
    raise SystemExit("PATCH FAILED: router_enhanced.py has no route() function.")

append = r'''

# === PHASE13B_V2_APPEND_ONLY_ROUTE_SURFACE_GUARD ===
# This wrapper is intentionally append-only.
# It does not inject into the existing legacy patch stack or tail wrappers.
#
# Repairs:
# 1. Conversational confusion/frustration remains ordinary CHAT.
# 2. Questions about missing imports / modules / dependencies / virtual
#    environments route into grounded IMPORT_AUDIT rather than generic CHAT.

import re as _eli_phase13b_v2_re

_ELI_PHASE13B_V2_ORIGINAL_ROUTE = route


def _eli_phase13b_v2_extract_text(_args, _kwargs) -> str:
    for _key in (
        "user_input",
        "user_text",
        "message",
        "text",
        "query",
        "prompt",
        "raw",
    ):
        _value = _kwargs.get(_key)
        if isinstance(_value, str) and _value.strip():
            return _value

    for _value in _args:
        if isinstance(_value, str) and _value.strip():
            return _value

    return ""


def _eli_phase13b_v2_surface_preempt(_user_text: str):
    _raw = str(_user_text or "")
    _low = _eli_phase13b_v2_re.sub(r"\s+", " ", _raw.strip().lower())

    if not _low:
        return None

    # ------------------------------------------------------------------
    # A. Grounded import / dependency / venv status questions
    # ------------------------------------------------------------------
    _import_terms = (
        "import",
        "imports",
        "module",
        "modules",
        "dependency",
        "dependencies",
        "missing package",
        "missing packages",
    )

    _venv_terms = (
        "virtual environment",
        "virtual environments",
        "venv",
        ".venv",
        "python environment",
    )

    _status_terms = (
        "status",
        "missing",
        "failing",
        "failure",
        "failures",
        "broken",
        "audit",
        "check",
        "inspect",
        "what is",
        "what are",
        "tell me",
        "show me",
    )

    _asks_import_status = (
        any(_term in _low for _term in _import_terms)
        and any(_term in _low for _term in _status_terms)
    )

    _asks_venv_status = (
        any(_term in _low for _term in _venv_terms)
        and any(_term in _low for _term in _status_terms)
    )

    if _asks_import_status or _asks_venv_status:
        return {
            "action": "IMPORT_AUDIT",
            "args": {
                "query": _raw,
                "include_venv": True,
                "scope": "project_and_runtime",
            },
            "confidence": 0.98,
            "meta": {
                "matched_by": "phase13b_v2.import_venv_audit.preempt",
                "need_grounding": True,
                "task_family": "grounded_audit",
            },
        }

    # ------------------------------------------------------------------
    # B. Conversational clarification should not become META_DIAGNOSTIC
    # ------------------------------------------------------------------
    _explicit_technical_terms = (
        "audit",
        "diagnostic",
        "diagnose",
        "runtime",
        "runtime status",
        "system status",
        "model",
        "gguf",
        "gpu",
        "ctx",
        "context window",
        "memory db",
        "router",
        "executor",
        "orchestrator",
        "pipeline",
        "engine",
        "traceback",
        "stack trace",
        "import",
        "imports",
        "module",
        "modules",
        "dependency",
        "dependencies",
        "virtual environment",
        "venv",
        ".venv",
        "settings",
        "config",
    )

    _clarification_patterns = (
        r"^what(?: the fuck)? is happening[?!., ]*$",
        r"^what(?: the fuck)? is going on[?!., ]*$",
        r"^what are you talking about[?!., ]*$",
        r"^what do you mean[?!., ]*$",
        r"^why did you say that[?!., ]*$",
        r"^what was that[?!., ]*$",
    )

    _looks_like_clarification = any(
        _eli_phase13b_v2_re.match(_pat, _low)
        for _pat in _clarification_patterns
    )

    if "note to yourself" in _low:
        _looks_like_clarification = True

    if _looks_like_clarification and not any(
        _term in _low for _term in _explicit_technical_terms
    ):
        return {
            "action": "CHAT",
            "args": {"message": _raw},
            "confidence": 0.97,
            "meta": {
                "matched_by": "phase13b_v2.conversational_clarification.chat_guard",
                "need_grounding": False,
                "task_family": "chat",
            },
        }

    return None


def route(*args, **kwargs):
    _eli_phase13b_v2_text = _eli_phase13b_v2_extract_text(args, kwargs)
    _eli_phase13b_v2_preempt = _eli_phase13b_v2_surface_preempt(
        _eli_phase13b_v2_text
    )
    if _eli_phase13b_v2_preempt is not None:
        return _eli_phase13b_v2_preempt

    return _ELI_PHASE13B_V2_ORIGINAL_ROUTE(*args, **kwargs)


print("[ROUTER] Phase 13B v2 append-only route surface guard installed")
'''

path.write_text(src.rstrip() + append + "\n", encoding="utf-8")

(out / "01_router_patch.txt").write_text(
    "PATCHED router_enhanced.py with append-only Phase 13B v2 route guard.\n",
    encoding="utf-8",
)

print("PATCHED router_enhanced.py")
PY
echo

echo "=== 3. Verify engine.py from prior Phase 13 patch; restore if syntactically damaged ==="
if python3 -m py_compile "$ROOT/eli/kernel/engine.py" 2>"$OUT/02_engine_compile_before_restore.err"; then
  echo "ENGINE_OK: current engine.py compiles."
  echo "ENGINE_OK: retaining Phase 13 engine patch if present." | tee "$OUT/02_engine_recovery.txt"
else
  echo "ENGINE_BROKEN: current engine.py did not compile."
  cat "$OUT/02_engine_compile_before_restore.err" || true

  if [ -f "$PH13_ENGINE_BACKUP" ]; then
    cp -a "$PH13_ENGINE_BACKUP" "$ROOT/eli/kernel/engine.py"
    echo "RESTORED engine.py from Phase 13 backup:"
    echo "  $PH13_ENGINE_BACKUP"

    python3 -m py_compile "$ROOT/eli/kernel/engine.py"
    echo "ENGINE_RESTORED_AND_COMPILES"
    {
      echo "ENGINE_BROKEN_AFTER_PHASE13_PATCH"
      echo "RESTORED_FROM=$PH13_ENGINE_BACKUP"
      echo "RESULT=ENGINE_RESTORED_AND_COMPILES"
    } > "$OUT/02_engine_recovery.txt"
  else
    echo "FATAL: engine.py broken and Phase 13 engine backup is missing."
    false
  fi
fi
echo

echo "=== 4. Confirm output_governor and labs_tab Phase 13 repairs still present ==="
{
  echo "--- output_governor markers ---"
  grep -n \
    -E 'PHASE13_OUTPUT_GOVERNOR_REPAIR_CONTEXT_GATE|Wrong frame' \
    "$ROOT/eli/cognition/output_governor.py" || true

  echo
  echo "--- labs_tab markers ---"
  grep -n \
    -E 'PHASE13_LABS_QT_BINDING_ALIGNMENT|_QT_IMPORT_ORDER' \
    "$ROOT/eli/gui/labs_tab.py" || true
} | tee "$OUT/03_phase13_patch_presence.txt"
echo

echo "=== 5. Correct TTS package discovery for packaged tts_piper/piper layout ==="
python3 - "$ROOT" "$OUT" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
out = Path(sys.argv[2])
path = root / "eli/perception/tts_router.py"

src = path.read_text(encoding="utf-8")

marker = "# === PHASE13B_V2_PACKAGED_TTS_PIPER_SEARCH ==="

if marker in src:
    print("SKIP: tts_router packaged Piper search patch already present.")
    (out / "04_tts_router_patch.txt").write_text(
        "SKIP: marker already present\n",
        encoding="utf-8",
    )
    raise SystemExit(0)

# ----------------------------------------------------------------------
# A. Add packaged Piper directory helpers after _PIPER_VOICE_CACHE line.
# ----------------------------------------------------------------------
anchor = "_PIPER_VOICE_CACHE: dict = {}  # voice_name → PiperVoice instance\n"
if anchor not in src:
    raise SystemExit("PATCH FAILED: could not find Piper cache anchor in tts_router.py.")

helper = r'''
# === PHASE13B_V2_PACKAGED_TTS_PIPER_SEARCH ===
# Packaged ELI builds place Piper assets under:
#   <project_root>/tts_piper/piper
# Keep this as a search location; do not duplicate or move assets.
_PROJECT_ROOT_TTS = Path(
    os.environ.get("ELI_PROJECT_ROOT")
    or Path(__file__).resolve().parents[2]
).expanduser()

_PACKAGED_TTS_PIPER_ROOT = _PROJECT_ROOT_TTS / "tts_piper" / "piper"
_PACKAGED_TTS_PIPER_PARENT = _PROJECT_ROOT_TTS / "tts_piper"


def _packaged_piper_voice_dirs() -> list[Path]:
    candidates = [
        _PACKAGED_TTS_PIPER_ROOT,
        _PACKAGED_TTS_PIPER_ROOT / "voices",
        _PACKAGED_TTS_PIPER_PARENT,
        _PACKAGED_TTS_PIPER_PARENT / "voices",
    ]
    return candidates


def _packaged_piper_binary_candidates() -> list[Path]:
    return [
        _PACKAGED_TTS_PIPER_ROOT / "piper",
        _PACKAGED_TTS_PIPER_PARENT / "piper",
        _PACKAGED_TTS_PIPER_PARENT / "bin" / "piper",
    ]

'''

src = src.replace(anchor, anchor + helper, 1)

# ----------------------------------------------------------------------
# B. Extend _VOICE_SEARCH_DIRS to include packaged Piper voice dirs.
# ----------------------------------------------------------------------
voice_block_start = src.find("_VOICE_SEARCH_DIRS = [")
if voice_block_start < 0:
    raise SystemExit("PATCH FAILED: could not find _VOICE_SEARCH_DIRS block.")

voice_block_end = src.find("]\n", voice_block_start)
if voice_block_end < 0:
    raise SystemExit("PATCH FAILED: could not find end of _VOICE_SEARCH_DIRS block.")

voice_block_end += 2
voice_block = src[voice_block_start:voice_block_end]

replacement_voice_block = voice_block.rstrip("\n")
replacement_voice_block = replacement_voice_block[:-1].rstrip()
replacement_voice_block += """
    *_packaged_piper_voice_dirs(),
]
"""

src = src[:voice_block_start] + replacement_voice_block + src[voice_block_end:]

# ----------------------------------------------------------------------
# C. Extend _find_piper_bin() candidate loop to check packaged binaries first.
# ----------------------------------------------------------------------
old_guess = '''    for guess in (
        "piper",
        str(Path.cwd() / ".venv" / "bin" / "piper"),
        str(Path.home() / ".local" / "bin" / "piper"),
        "/usr/local/bin/piper",
        "/usr/bin/piper",
    ):
        if shutil.which(guess) or Path(guess).exists():
            return guess
'''

new_guess = '''    for packaged in _packaged_piper_binary_candidates():
        try:
            if packaged.exists() and packaged.is_file():
                return str(packaged.resolve())
        except Exception:
            pass

    for guess in (
        "piper",
        str(Path.cwd() / ".venv" / "bin" / "piper"),
        str(Path.home() / ".local" / "bin" / "piper"),
        "/usr/local/bin/piper",
        "/usr/bin/piper",
    ):
        if shutil.which(guess) or Path(guess).exists():
            return guess
'''

if old_guess not in src:
    raise SystemExit("PATCH FAILED: could not find _find_piper_bin guess loop.")
src = src.replace(old_guess, new_guess, 1)

# ----------------------------------------------------------------------
# D. Extend Piper CLI runtime binary resolution to packaged candidates.
# ----------------------------------------------------------------------
old_cli_bin = '''    piper_bin = (
        _os.environ.get("ELI_PIPER_BINARY", "").strip().strip('"')
        or _shutil.which("piper")
        or str(_Path.cwd() / ".venv" / "bin" / "piper")
    )
'''

new_cli_bin = '''    _eli_packaged_cli_bins = [
        _Path(p) for p in _packaged_piper_binary_candidates()
    ]
    _eli_packaged_cli_bin = next(
        (str(p.resolve()) for p in _eli_packaged_cli_bins if p.exists() and p.is_file()),
        "",
    )

    piper_bin = (
        _os.environ.get("ELI_PIPER_BINARY", "").strip().strip('"')
        or _eli_packaged_cli_bin
        or _shutil.which("piper")
        or str(_Path.cwd() / ".venv" / "bin" / "piper")
    )
'''

if old_cli_bin not in src:
    raise SystemExit("PATCH FAILED: could not find Piper CLI binary resolution block.")
src = src.replace(old_cli_bin, new_cli_bin, 1)

path.write_text(src, encoding="utf-8")

(out / "04_tts_router_patch.txt").write_text(
    "PATCHED tts_router.py to search packaged tts_piper/piper voices and binary candidates.\n",
    encoding="utf-8",
)

print("PATCHED tts_router.py for packaged tts_piper/piper layout.")
PY
echo

echo "=== 6. TTS packaged layout audit ==="
{
  echo "Packaged Piper root:"
  echo "  $ROOT/tts_piper/piper"
  echo
  echo "Directory tree, shallow:"
  find "$ROOT/tts_piper" -maxdepth 4 -printf '%y %p\n' 2>/dev/null | sort || true
  echo
  echo "Candidate Piper binaries:"
  find "$ROOT/tts_piper" -type f -name 'piper' -o -type f -name 'piper.exe' 2>/dev/null | sort || true
  echo
  echo "Candidate Piper ONNX voices:"
  find "$ROOT/tts_piper" -type f -name '*.onnx' 2>/dev/null | sort || true
  echo
  echo "Candidate Piper JSON configs:"
  find "$ROOT/tts_piper" -type f \( -name '*.json' -o -name '*.onnx.json' \) 2>/dev/null | sort || true
} | tee "$OUT/05_tts_packaged_layout_audit.txt"
echo

echo "=== 7. Critical file compile check ==="
{
  python3 -m py_compile \
    "$ROOT/eli/cognition/output_governor.py" \
    "$ROOT/eli/gui/labs_tab.py" \
    "$ROOT/eli/execution/router_enhanced.py" \
    "$ROOT/eli/kernel/engine.py" \
    "$ROOT/eli/perception/tts_router.py" \
    "$ROOT/eli/runtime/visible_text.py" \
    "$ROOT/eli/gui/eli_pro_audio_gui_MKI.py"

  echo "PY_COMPILE_OK"
} | tee "$OUT/06_py_compile.txt"
echo

echo "=== 8. Recursive compileall across eli/ ==="
{
  env -u PYTHONPATH python3 -m compileall -q "$ROOT/eli"
  echo "COMPILEALL_OK"
} | tee "$OUT/07_compileall.txt"
echo

echo "=== 9. Targeted behavior probe ==="
env -u PYTHONPATH python3 - "$ROOT" "$OUT" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
out = Path(sys.argv[2])
sys.path.insert(0, str(root))

lines: list[str] = []

# ------------------------------------------------------------------
# A. Output governor: verify unrelated prompt does not become Wrong frame.
# ------------------------------------------------------------------
from eli.cognition.output_governor import repair_local_persona_drift

unrelated = repair_local_persona_drift(
    "The surgeon mentioned the skull in a bad generated sentence.",
    user_input="you alive buddy ?",
)

repair_context = repair_local_persona_drift(
    "The surgeon mentioned the skull in a bad generated sentence.",
    user_input="did the open-head surgery on your memory/persona work?",
)

lines.append("OUTPUT_GOVERNOR unrelated_prompt_result=" + repr(unrelated))
lines.append("OUTPUT_GOVERNOR repair_prompt_result=" + repr(repair_context))
lines.append("OUTPUT_GOVERNOR unrelated_wrong_frame=" + str(unrelated.startswith("Wrong frame.")))
lines.append("OUTPUT_GOVERNOR repair_wrong_frame=" + str(repair_context.startswith("Wrong frame.")))

# ------------------------------------------------------------------
# B. Router guard behavior.
# ------------------------------------------------------------------
from eli.execution.router_enhanced import route

cases = [
    "what the fuck is happening?",
    "What are you talking about? is that a note to yourself, or me?",
    "there is more failing than that. what is the status of missing imports and virtual environments?",
    "run full audit and diagnostic!",
]

for case in cases:
    routed = route(case)
    if isinstance(routed, dict):
        action = routed.get("action")
        matched_by = (routed.get("meta") or {}).get("matched_by")
    else:
        action = type(routed).__name__
        matched_by = None

    lines.append(
        f"ROUTE case={case!r} action={action!r} matched_by={matched_by!r}"
    )

# ------------------------------------------------------------------
# C. Qt binding alignment between main GUI and Labs.
# ------------------------------------------------------------------
try:
    from eli.gui import eli_pro_audio_gui_MKI as gui_mod
    from eli.gui import labs_tab as labs_mod

    gui_qt = getattr(gui_mod, "QT_API", None)
    labs_qt = getattr(labs_mod, "_QT", None)

    lines.append(f"QT_BINDING gui={gui_qt!r} labs={labs_qt!r}")
    lines.append("QT_BINDING aligned=" + str(gui_qt == labs_qt))
except Exception as exc:
    lines.append("QT_BINDING import_failed=" + repr(exc))

# ------------------------------------------------------------------
# D. TTS backend/package discovery after tts_router patch.
# ------------------------------------------------------------------
try:
    from eli.perception.tts_router import (
        available_backends,
        _packaged_piper_voice_dirs,
        _packaged_piper_binary_candidates,
    )

    backends = available_backends()
    lines.append("TTS_BACKENDS " + json.dumps(backends, sort_keys=True))
    lines.append(
        "TTS_PACKAGED_VOICE_DIRS "
        + json.dumps([str(p) for p in _packaged_piper_voice_dirs()])
    )
    lines.append(
        "TTS_PACKAGED_BINARY_CANDIDATES "
        + json.dumps([str(p) for p in _packaged_piper_binary_candidates()])
    )
except Exception as exc:
    lines.append("TTS_BACKENDS failed=" + repr(exc))

text = "\n".join(lines) + "\n"
(out / "08_targeted_behavior_probe.txt").write_text(text, encoding="utf-8")
print(text, end="")
PY
echo

echo "=== 10. Isolated recursive ELI import sweep ==="
env -u PYTHONPATH python3 - "$ROOT" "$OUT" <<'PY'
from __future__ import annotations

import json
import os
import pkgutil
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1])
out = Path(sys.argv[2])

sys.path.insert(0, str(root))
import eli  # noqa

modules = sorted({
    mod.name
    for mod in pkgutil.walk_packages([str(root / "eli")], prefix="eli.")
})

records = []

for name in modules:
    cmd = [
        sys.executable,
        "-c",
        (
            "import sys;"
            f"sys.path.insert(0, {str(root)!r});"
            f"import {name};"
            "print('OK')"
        ),
    ]

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(root),
            env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"},
            capture_output=True,
            text=True,
            timeout=12,
        )

        records.append({
            "module": name,
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout_tail": proc.stdout[-600:],
            "stderr_tail": proc.stderr[-1600:],
        })
    except subprocess.TimeoutExpired as exc:
        records.append({
            "module": name,
            "ok": False,
            "returncode": None,
            "stdout_tail": (exc.stdout or "")[-600:] if isinstance(exc.stdout, str) else "",
            "stderr_tail": "TIMEOUT after 12s",
        })

(out / "09_import_sweep.json").write_text(
    json.dumps(records, indent=2),
    encoding="utf-8",
)

fails = [record for record in records if not record["ok"]]

summary = [
    f"modules_total={len(records)}",
    f"modules_failed={len(fails)}",
    "",
]

for record in fails:
    summary.append(f"FAIL {record['module']}")
    if record["stderr_tail"]:
        summary.append("  STDERR " + record["stderr_tail"].replace("\n", " | ")[:900])
    elif record["stdout_tail"]:
        summary.append("  STDOUT " + record["stdout_tail"].replace("\n", " | ")[:900])

text = "\n".join(summary) + "\n"

(out / "09_import_sweep_summary.txt").write_text(text, encoding="utf-8")
print(text, end="")
PY
echo

echo "=== 11. Package status audit ==="
{
  echo "ROOT=$ROOT"
  echo
  echo "Current shell PYTHONPATH=${PYTHONPATH-<unset>}"
  echo
  echo ".venv present?"
  if [ -x "$ROOT/.venv/bin/python" ]; then
    echo "YES $ROOT/.venv/bin/python"
    "$ROOT/.venv/bin/python" --version || true
  else
    echo "NO"
  fi
  echo
  echo "Packaged GGUF models:"
  find "$ROOT/models" -maxdepth 2 -type f -name '*.gguf' 2>/dev/null | sort || true
  echo
  echo "Embedder expected:"
  EMBED="$ROOT/models/embeddings/nomic-embed-text-v1.5.Q4_K_M.gguf"
  if [ -f "$EMBED" ]; then
    echo "FOUND $EMBED"
  else
    echo "MISSING $EMBED"
  fi
  echo
  echo "Piper packaged root:"
  echo "$ROOT/tts_piper/piper"
  echo
  echo "Piper packaged files:"
  find "$ROOT/tts_piper" -maxdepth 5 -type f 2>/dev/null | sort || true
  echo
  echo "Requirements files:"
  find "$ROOT" -maxdepth 2 -type f \
    \( -iname 'requirements*.txt' -o -iname 'pyproject.toml' \) \
    | sort || true
} | tee "$OUT/10_package_status.txt"
echo

echo "=== 12. Structural audit: duplicate top-level names and hardcoded /home paths ==="
env -u PYTHONPATH python3 - "$ROOT" "$OUT" <<'PY'
from __future__ import annotations

import ast
import json
import sys
from collections import defaultdict
from pathlib import Path

root = Path(sys.argv[1])
out = Path(sys.argv[2])

results = {}

for path in sorted((root / "eli").rglob("*.py")):
    rel = str(path.relative_to(root))
    text = path.read_text(encoding="utf-8", errors="replace")

    record = {
        "duplicate_top_level_symbols": [],
        "hardcoded_home_paths": [],
        "syntax_error": None,
    }

    try:
        tree = ast.parse(text)
        seen = defaultdict(list)

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                seen[node.name].append(node.lineno)

        for symbol, lines in sorted(seen.items()):
            if len(lines) > 1:
                record["duplicate_top_level_symbols"].append({
                    "symbol": symbol,
                    "lines": lines,
                })

    except SyntaxError as exc:
        record["syntax_error"] = f"{exc.msg} line={exc.lineno}"

    for lineno, line in enumerate(text.splitlines(), start=1):
        if "/home/" in line:
            record["hardcoded_home_paths"].append({
                "line": lineno,
                "text": line.strip()[:280],
            })

    if (
        record["duplicate_top_level_symbols"]
        or record["hardcoded_home_paths"]
        or record["syntax_error"]
    ):
        results[rel] = record

(out / "11_structure_audit.json").write_text(
    json.dumps(results, indent=2),
    encoding="utf-8",
)

for rel, record in results.items():
    print(rel)
    for item in record["duplicate_top_level_symbols"]:
        print(f"  DUPLICATE {item['symbol']} lines={item['lines']}")
    for item in record["hardcoded_home_paths"]:
        print(f"  HOME_PATH line={item['line']} {item['text']}")
    if record["syntax_error"]:
        print(f"  SYNTAX_ERROR {record['syntax_error']}")
PY
echo

echo "=== 13. Surface/control grep ==="
{
  grep -RIn --color=never \
    -E 'control_result_without_visible_synthesis|runtime_truth_evidence|import_audit_evidence|META_DIAGNOSTIC|DETERMINISTIC_INTROSPECTION|Wrong frame|Stage 11 primary path yielded zero visible tokens' \
    "$ROOT/eli" 2>/dev/null || true
} | tee "$OUT/12_surface_control_grep.txt"
echo

echo "=== 14. Runtime settings vs runtime snapshot comparison ==="
env -u PYTHONPATH python3 - "$ROOT" "$OUT" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
out = Path(sys.argv[2])

settings_path = root / "config" / "settings.json"
snapshot_path = root / "artifacts" / "runtime_snapshot.json"

def read_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"__error__": repr(exc)}

settings = read_json(settings_path)
snapshot = read_json(snapshot_path)

keys = (
    "provider",
    "model_path",
    "n_ctx",
    "context_size",
    "n_gpu_layers",
    "gpu_layers",
    "n_threads",
    "cpu_threads",
    "n_batch",
    "batch_size",
    "kv_cache_k",
    "kv_cache_v",
)

comparison = {}

for key in keys:
    comparison[key] = {
        "settings": settings.get(key) if isinstance(settings, dict) else None,
        "snapshot": snapshot.get(key) if isinstance(snapshot, dict) else None,
    }

payload = {
    "settings_path": str(settings_path),
    "snapshot_path": str(snapshot_path),
    "settings_exists": settings_path.exists(),
    "snapshot_exists": snapshot_path.exists(),
    "comparison": comparison,
}

(out / "13_runtime_settings_snapshot_compare.json").write_text(
    json.dumps(payload, indent=2),
    encoding="utf-8",
)

print(json.dumps(comparison, indent=2))
PY
echo

echo "=== 15. Git diff summary ==="
{
  git diff --stat 2>/dev/null || true
  echo
  git diff -- \
    eli/execution/router_enhanced.py \
    eli/kernel/engine.py \
    eli/cognition/output_governor.py \
    eli/gui/labs_tab.py \
    eli/perception/tts_router.py \
    2>/dev/null || true
} > "$OUT/14_patch_diff.txt"

echo "Diff written to:"
echo "  $OUT/14_patch_diff.txt"
echo

{
  echo "## Repairs performed"
  echo
  echo "1. Restored router_enhanced.py from the clean Phase 13 backup, removing the broken indentation insertion."
  echo "2. Applied a safe append-only route guard for clarification chat and import/venv audit routing."
  echo "3. Verified current engine.py; if Phase 13 damaged it, restored the pre-Phase-13 engine backup automatically."
  echo "4. Retained and rechecked output_governor and Labs repairs."
  echo "5. Patched tts_router.py to search the packaged \`tts_piper/piper\` layout rather than assuming \`models/tts/piper\`."
  echo "6. Performed compile, compileall, import sweep, structural audit, TTS package audit, and runtime/settings comparison."
  echo
  echo "## Read these first"
  echo
  echo "- \`06_py_compile.txt\`"
  echo "- \`08_targeted_behavior_probe.txt\`"
  echo "- \`09_import_sweep_summary.txt\`"
  echo "- \`10_package_status.txt\`"
  echo "- \`13_runtime_settings_snapshot_compare.json\`"
  echo "- \`14_patch_diff.txt\`"
} >> "$OUT/SUMMARY.md"

echo "======================================================================"
echo "PHASE 13B CORRECTED COMPLETE"
echo "REPORT:"
echo "  $OUT"
echo
echo "READ:"
echo "  $OUT/SUMMARY.md"
echo "  $OUT/08_targeted_behavior_probe.txt"
echo "  $OUT/09_import_sweep_summary.txt"
echo "======================================================================"
