#!/usr/bin/env python3
"""
ELI Stage 11 surgical patch script (idempotent).

Targets:
  eli/kernel/engine.py

Fixes:
  1) generate_stream_from_assembled_prompt:
     return _live_stream() -> yield from _live_stream()
  2) _stream_chat reasoning_mode recovery from self._current_reasoning_mode
  3) Stage 11 pipeline trace logging (entry / zero-token / GGUF fallback)
"""
from __future__ import annotations

from pathlib import Path
import sys

TARGET = Path("eli/kernel/engine.py")
if not TARGET.exists():
    raise SystemExit(f"ABORT: {TARGET} not found (run from repo root)")

src = TARGET.read_text(encoding="utf-8", errors="replace")
patched = src

# --- Bug 1: stream handoff ---
BUG1_OLD = "        return _live_stream()\n"
BUG1_NEW = (
    "        # Streaming generator handoff must yield sub-generator tokens live.\n"
    "        # Returning the generator object here can collapse visible streaming.\n"
    "        yield from _live_stream()\n"
    "        return\n"
)

# --- Bug 2: reasoning mode recovery ---
BUG2_ANCHOR = "        _rapport_mode = _eli_is_rapport_prompt(prompt)\n"
BUG2_MARKER = "ELI_REASONING_MODE_RECOVERY_V1"
BUG2_BLOCK = (
    "        # ELI_REASONING_MODE_RECOVERY_V1\n"
    "        # Some indirect stream paths may omit the explicit reasoning_mode kwarg.\n"
    "        # process() stamps the active mode on self; recover it here to preserve\n"
    "        # non-Quick mode contracts in Stage 11 and fallback guards.\n"
    "        if not reasoning_mode:\n"
    "            reasoning_mode = getattr(self, \"_current_reasoning_mode\", None) or None\n"
    "\n"
    "        print(\n"
    "            f\"[COGNITIVE][PIPELINE] stream_chat begin \"\n"
    "            f\"mode={reasoning_mode or 'quick'} \"\n"
    "            f\"prompt_chars={len(prompt)} \"\n"
    "            f\"prebuilt_ctx={bool(pre_built_memory_context)} \"\n"
    "            f\"prebuilt_bus={bool(pre_built_bus_result)}\"\n"
    "        )\n"
    "\n"
    "        _rapport_mode = _eli_is_rapport_prompt(prompt)\n"
)

# --- Stage 11 traces ---
TRACE_ENTRY_ANCHOR = '            print("[COGNITIVE] Stream: Stage 11 primary path")\n'
TRACE_ENTRY_MARKER = "stage_11_enter"
TRACE_ENTRY_NEW = (
    '            print("[COGNITIVE] Stream: Stage 11 primary path")\n'
    '            print(\n'
    '                f"[COGNITIVE][PIPELINE] stage_11_enter "\n'
    '                f"mode={reasoning_mode or \'quick\'} "\n'
    '                f"ctx_chars={len(situation_brief)} "\n'
    '                f"memory_chars={len(pre_built_memory_context or str())} "\n'
    '                f"bus_result={bool(pre_built_bus_result)}"\n'
    '            )\n'
)

TRACE_ZERO_ANCHOR = '            print("[COGNITIVE] Stream: Stage 11 primary path yielded zero visible tokens")\n'
TRACE_ZERO_MARKER = "stage_11_zero_token"
TRACE_ZERO_NEW = (
    '            print("[COGNITIVE] Stream: Stage 11 primary path yielded zero visible tokens")\n'
    '            print(\n'
    '                f"[COGNITIVE][PIPELINE] stage_11_zero_token "\n'
    '                f"mode_at_check={reasoning_mode or None} "\n'
    '                f"full_tokens_count={len(full_tokens)} "\n'
    '                f"situation_brief_len={len(situation_brief)}"\n'
    '            )\n'
)

TRACE_FALLBACK_ANCHOR = '            print("[COGNITIVE] Stream: direct gguf fallback path")\n'
TRACE_FALLBACK_MARKER = "gguf_fallback mode_now="
TRACE_FALLBACK_NEW = (
    '            print("[COGNITIVE] Stream: direct gguf fallback path")\n'
    '            print(f"[COGNITIVE][PIPELINE] gguf_fallback mode_now={_mode_now!r}")\n'
)


def patch_once(text: str, old: str, new: str, label: str) -> tuple[str, bool]:
    if new in text:
        return text, False
    if old not in text:
        raise AssertionError(f"{label}: anchor not found")
    return text.replace(old, new, 1), True


changes = []

# Apply bug1 only if old line exists and new block not yet present.
if BUG1_NEW not in patched and BUG1_OLD in patched:
    patched, changed = patch_once(patched, BUG1_OLD, BUG1_NEW, "PATCH1")
    if changed:
        changes.append("Bug1: yield from _live_stream()")

# Apply bug2 only if marker absent.
if BUG2_MARKER not in patched:
    patched, changed = patch_once(patched, BUG2_ANCHOR, BUG2_BLOCK, "PATCH2")
    if changed:
        changes.append("Bug2: reasoning_mode recovery")

# Apply stage11 traces only if markers absent.
if TRACE_ENTRY_MARKER not in patched:
    patched, changed = patch_once(patched, TRACE_ENTRY_ANCHOR, TRACE_ENTRY_NEW, "PATCH3")
    if changed:
        changes.append("Trace: stage_11 entry")

if TRACE_ZERO_MARKER not in patched:
    patched, changed = patch_once(patched, TRACE_ZERO_ANCHOR, TRACE_ZERO_NEW, "PATCH4")
    if changed:
        changes.append("Trace: stage_11 zero-token")

if TRACE_FALLBACK_MARKER not in patched:
    patched, changed = patch_once(patched, TRACE_FALLBACK_ANCHOR, TRACE_FALLBACK_NEW, "PATCH5")
    if changed:
        changes.append("Trace: gguf fallback")

print("=" * 60)
print("ELI Stage 11 patch — dry-run")
print("=" * 60)
print(f"  Target: {TARGET}")
print(f"  Pending changes: {len(changes)}")
for item in changes:
    print(f"  - {item}")
if not changes:
    print("  - none (already patched)")
print()

confirm = input("Apply patch? [yes/no]: ").strip().lower()
if confirm not in {"y", "yes"}:
    print("Aborted — no changes made.")
    raise SystemExit(0)

if not changes:
    print("No-op — target already patched.")
    raise SystemExit(0)

backup = TARGET.with_suffix(".py.pre_s11_patch")
backup.write_text(src, encoding="utf-8")
TARGET.write_text(patched, encoding="utf-8")

print()
print(f"Backup:  {backup}")
print(f"Patched: {TARGET}")
print("Patch complete.")
print("Verify:")
print("  python3 -m py_compile eli/kernel/engine.py")
print("  python3 eli/gui/eli_pro_audio_gui_MKI.py 2>&1 | tee ops/reports/post_patch.log")
print("Look for:")
print("  [COGNITIVE][PIPELINE] stream_chat begin ...")
print("  [COGNITIVE][PIPELINE] stage_11_enter ...")
print("  [COGNITIVE][PIPELINE] stage_11_zero_token ...")
print("  [COGNITIVE][PIPELINE] gguf_fallback ...")

