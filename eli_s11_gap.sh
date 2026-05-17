#!/usr/bin/env bash
# ============================================================
# ELI Stage 11 — Final gap confirmation
# Shows exactly where reasoning_mode is dropped between
# _stream_chat and generate_stream_from_assembled_prompt
# ============================================================
ROOT="$(pwd)"
TMPPY=$(mktemp /tmp/eli_s11_gap_XXXXXX.py)

cat > "$TMPPY" << 'ENDPY'
import re, sys, logging
logging.disable(logging.CRITICAL)

ENGINE = "eli/kernel/engine.py"
GUI    = "eli/gui/eli_pro_audio_gui_MKI.py"

lines     = open(ENGINE, errors="replace").readlines()
gui_lines = open(GUI,    errors="replace").readlines()

def show(label, start, end):
    print(f"\n--- {label} (lines {start+1}–{end}) ---")
    for i in range(max(0, start), min(len(lines), end)):
        print(f"  {i+1:6d}: {lines[i]}", end="")

# ── 1. _stream_chat lines 8480-8625 (the orchestrator/Stage11 call block) ──
print("=" * 70)
print("1. _stream_chat — orchestrator call block (lines 8480–8625)")
print("=" * 70)
show("_stream_chat orchestrator block", 8479, 8625)

# ── 2. _live_stream — body after definition (lines 6453-6600) ───────────
print("\n" + "=" * 70)
print("2. _live_stream() — body and GGUF call (lines 6453–6600)")
print("=" * 70)
show("_live_stream body", 6452, 6600)

# ── 3. GUI: how _stream_chat is called (search call sites) ───────────────
print("\n" + "=" * 70)
print("3. GUI call sites to _stream_chat")
print("=" * 70)
for i, ln in enumerate(gui_lines):
    if re.search(r'_stream_chat\s*\(|stream_chat\s*\(', ln):
        start = max(0, i-4)
        end   = min(len(gui_lines), i+12)
        print(f"\n  GUI line {i+1}:")
        for j in range(start, end):
            marker = ">>>" if j == i else "   "
            print(f"  {marker} {j+1:5d}: {gui_lines[j]}", end="")

# ── 4. Engine: all _stream_chat call sites ───────────────────────────────
print("\n" + "=" * 70)
print("4. Engine internal _stream_chat call sites")
print("=" * 70)
for i, ln in enumerate(lines):
    if re.search(r'_stream_chat\s*\(', ln) and "def _stream_chat" not in ln:
        start = max(0, i-3)
        end   = min(len(lines), i+10)
        print(f"\n  Line {i+1}:")
        for j in range(start, end):
            marker = ">>>" if j == i else "   "
            print(f"  {marker} {j+1:5d}: {lines[j]}", end="")

# ── 5. is_private_reasoning_mode definition ──────────────────────────────
print("\n" + "=" * 70)
print("5. is_private_reasoning_mode — what it considers 'private'")
print("=" * 70)
for i, ln in enumerate(open("eli/cognition/reasoning_modes.py",
                             errors="replace").readlines()):
    if "is_private" in ln or "private" in ln.lower():
        print(f"  {i+1:5d}: {ln}", end="")
ENDPY

PYTHONPATH="$ROOT" python3 "$TMPPY" 2>/dev/null
rm -f "$TMPPY"
