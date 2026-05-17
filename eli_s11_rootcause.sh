#!/usr/bin/env bash
# ============================================================
# ELI Stage 11 — Root Cause Confirmation
# Targets the exact gap: reasoning_mode lost between
# process() trace and the streaming dispatch function
# ============================================================
ROOT="$(pwd)"
TMPPY=$(mktemp /tmp/eli_s11_rc_XXXXXX.py)

cat > "$TMPPY" << 'ENDPY'
import re, sys, logging
logging.disable(logging.CRITICAL)

ENGINE = "eli/kernel/engine.py"
GUI    = "eli/gui/eli_pro_audio_gui_MKI.py"

lines = open(ENGINE, errors="replace").readlines()

def show_lines(start, end, label=""):
    print(f"\n--- {label} (lines {start+1}–{end}) ---")
    for i in range(max(0, start), min(len(lines), end)):
        print(f"  {i+1:6d}: {lines[i]}", end="")

def find_func_start(lineno_1based):
    """Walk back from lineno to find the def that owns it."""
    i = lineno_1based - 2  # 0-based
    while i >= 0:
        if re.match(r'\s{0,4}def ', lines[i]):
            return i
        i -= 1
    return 0

# ── 1. Function signature owning the zero-token check (line 8628) ────
print("=" * 70)
print("1. FUNCTION OWNING the zero-token check (surrounding line 8628)")
print("=" * 70)
func_start = find_func_start(8628)
show_lines(func_start, func_start + 25, "streaming dispatch function signature")

# ── 2. How generate_stream_from_assembled_prompt is defined ──────────
print("\n" + "=" * 70)
print("2. generate_stream_from_assembled_prompt — signature")
print("=" * 70)
for i, ln in enumerate(lines):
    if "def generate_stream_from_assembled_prompt" in ln:
        show_lines(i, i + 20, f"definition at line {i+1}")
        break

# ── 3. Where GUI calls the streaming dispatch ─────────────────────────
print("\n" + "=" * 70)
print("3. GUI call sites to the streaming dispatch function")
print("=" * 70)
try:
    gui_lines = open(GUI, errors="replace").readlines()
    for i, ln in enumerate(gui_lines):
        if re.search(r'stream_chat|process_stream|generate_stream|stream_response', ln, re.I):
            start = max(0, i-3)
            end   = min(len(gui_lines), i+8)
            print(f"\n  GUI line {i+1}:")
            for j in range(start, end):
                marker = ">>>" if j == i else "   "
                print(f"  {marker} {j+1:5d}: {gui_lines[j]}", end="")
except Exception as e:
    print(f"  [GUI READ ERROR] {e}")

# ── 4. reasoning_mode threading from process() to stream dispatch ─────
print("\n" + "=" * 70)
print("4. How reasoning_mode flows from process() into the stream call")
print("=" * 70)
# Find process() def
for i, ln in enumerate(lines):
    if re.match(r'    def process\(', ln) or re.match(r'def process\(', ln):
        show_lines(i, i + 20, f"process() signature at line {i+1}")
        break

# Is reasoning_mode stored on self between process() and stream?
for i, ln in enumerate(lines):
    if re.search(r'self\._reasoning_mode|self\.reasoning_mode|self\._current_mode|self\.current_mode', ln):
        start = max(0, i-2)
        end   = min(len(lines), i+5)
        print(f"\n  Line {i+1} — reasoning_mode stored on self:")
        for j in range(start, end):
            marker = ">>>" if j == i else "   "
            print(f"  {marker} {j+1:5d}: {lines[j]}", end="")

# ── 5. The exact Stage 11 call in generate_stream_from_assembled_prompt ─
print("\n" + "=" * 70)
print("5. Inside generate_stream_from_assembled_prompt — GGUF call path")
print("=" * 70)
in_func = False
func_lines_collected = []
for i, ln in enumerate(lines):
    if "def generate_stream_from_assembled_prompt" in ln:
        in_func = True
    if in_func:
        func_lines_collected.append((i, ln))
        # Stop at next def at same indent level
        if len(func_lines_collected) > 1 and re.match(r'    def |^def ', ln):
            break

# Show first 80 lines of function body
print(f"  Function body (up to 80 lines):")
for i, (lineno, ln) in enumerate(func_lines_collected[:80]):
    print(f"  {lineno+1:6d}: {ln}", end="")

# ── 6. Stage 11 primary path block in the streaming dispatch ─────────
print("\n" + "=" * 70)
print("6. Stage 11 primary path TRY block in streaming dispatch")
print("=" * 70)
# Find the try block just before line 8628
# Search backwards from 8628 for the try:
search_start = 8627 - 1  # 0-based
for i in range(search_start, max(0, search_start - 200), -1):
    if lines[i].strip() == "try:":
        show_lines(i, min(len(lines), i + 60), f"try block starting at line {i+1}")
        break

# ── 7. The yielded / full_tokens collection loop ─────────────────────
print("\n" + "=" * 70)
print("7. Token collection loop (where 'yielded' flag is set)")
print("=" * 70)
for i, ln in enumerate(lines):
    if "yielded" in ln and ("full_tokens" in ln or "visible" in ln.lower()):
        start = max(0, i-5)
        end   = min(len(lines), i+15)
        print(f"\n  Line {i+1}:")
        for j in range(start, end):
            marker = ">>>" if j == i else "   "
            print(f"  {marker} {j+1:5d}: {lines[j]}", end="")
        if i > 8700:
            break

# ── 8. What constitutes a "visible" token ────────────────────────────
print("\n" + "=" * 70)
print("8. Visible token definition — what makes a chunk 'visible'")
print("=" * 70)
for i, ln in enumerate(lines):
    if re.search(r'is_visible|visible_chunk|chunk.*visible|visible.*chunk|not.*visible|_visible', ln):
        start = max(0, i-3)
        end   = min(len(lines), i+10)
        print(f"\n  Line {i+1}:")
        for j in range(start, end):
            marker = ">>>" if j == i else "   "
            print(f"  {marker} {j+1:5d}: {lines[j]}", end="")

ENDPY

PYTHONPATH="$ROOT" python3 "$TMPPY" 2>/dev/null
rm -f "$TMPPY"
