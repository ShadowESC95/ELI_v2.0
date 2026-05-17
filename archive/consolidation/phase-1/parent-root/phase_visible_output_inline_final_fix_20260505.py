from pathlib import Path
import shutil
import time

ROOT = Path.cwd()
STAMP = time.strftime("%Y%m%d_%H%M%S")
PHASE = f"phase_visible_output_inline_final_fix_{STAMP}"
BACKUP = ROOT / "ops" / "backups" / PHASE
REPORT = ROOT / "ops" / "reports" / PHASE
BACKUP.mkdir(parents=True, exist_ok=True)
REPORT.mkdir(parents=True, exist_ok=True)

path = ROOT / "eli/runtime/visible_output.py"
backup = BACKUP / path.relative_to(ROOT)
backup.parent.mkdir(parents=True, exist_ok=True)
shutil.copy2(path, backup)

s = path.read_text(encoding="utf-8")

old = r'''_FINAL_MARKER_RE = re.compile(
    r"(?is)"
    r"(?:^|\n|\r)"
    r"\s*(?:final\s+answer|final|answer|response)\s*[:\-]\s*"
)'''

new = r'''_FINAL_MARKER_RE = re.compile(
    r"(?is)"
    r"(?:^|[\n\r]|[\.\!\?]\s+|\b)"
    r"(?:final\s+answer|final|answer|response)\s*[:\-]\s*"
)'''

if old not in s:
    raise SystemExit("Could not find old _FINAL_MARKER_RE block. Inspect eli/runtime/visible_output.py manually.")

s = s.replace(old, new, 1)
path.write_text(s, encoding="utf-8")

(REPORT / "summary.txt").write_text(
    "Fixed visible_output final-answer extraction so inline markers like "
    "'Scratchpad: x. Final answer: y' preserve y instead of collapsing to ellipsis.\n"
    f"Backup: {backup}\n",
    encoding="utf-8",
)

print(f"✅ Applied {PHASE}")
print(f"Backups: {BACKUP}")
print(f"Report:  {REPORT}")
