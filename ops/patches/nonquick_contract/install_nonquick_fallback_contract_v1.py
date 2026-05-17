from __future__ import annotations

from pathlib import Path
from datetime import datetime
import re

ROOT = Path("/home/jay/Desktop/ELI_MKXI-main_MAY_NEWEST")
ENGINE = ROOT / "eli/kernel/engine.py"
REPORT = ROOT / "ops/reports/nonquick_contract/patch_result.txt"

if not ENGINE.exists():
    raise SystemExit(f"Missing expected engine file: {ENGINE}")

src = ENGINE.read_text(encoding="utf-8")
stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = ENGINE.with_suffix(f".py.bak_nonquick_contract_{stamp}")
backup.write_text(src, encoding="utf-8")

HELPER = r'''
# === ELI NON-QUICK FALLBACK CONTRACT GUARD v1 ===
def _eli_nonquick_mode_name(mode):
    try:
        if mode is None:
            return ""
        if hasattr(mode, "value"):
            return str(mode.value).lower()
        return str(mode).lower()
    except Exception:
        return ""

def _eli_is_quick_mode(mode):
    m = _eli_nonquick_mode_name(mode)
    return m in {"quick", "quick_mode", "fast", "raw"}

def _eli_is_nonquick_mode(mode):
    m = _eli_nonquick_mode_name(mode)
    return any(k in m for k in (
        "constitutional",
        "const",
        "cot",
        "chain",
        "tree",
        "tot",
        "self",
        "consistency",
        "deep",
        "reason",
    )) and not _eli_is_quick_mode(mode)

def _eli_mode_contract_violation_response(mode, cause="raw fallback blocked"):
    mode_name = _eli_nonquick_mode_name(mode) or "unknown"
    return (
        "I hit an internal synthesis-contract fault before producing a valid response. "
        f"Mode was `{mode_name}`, so I am not allowed to return a raw/unsynthesized fallback answer. "
        f"Cause: {cause}. "
        "This should be routed through the full non-Quick synthesis pipeline: draft → critique/check → revised final → governor. "
        "The correct fix is in the Stage 11/broker fallback path, not in memory or the user profile."
    )

def _eli_guard_nonquick_fallback_text(text, mode, cause="raw fallback blocked"):
    if _eli_is_nonquick_mode(mode):
        return _eli_mode_contract_violation_response(mode, cause)
    return text
# === END ELI NON-QUICK FALLBACK CONTRACT GUARD v1 ===
'''

if "_eli_guard_nonquick_fallback_text" not in src:
    insert_at = 0
    m = re.search(r"\n(class |def )", src)
    if m:
        insert_at = m.start()
    src = src[:insert_at] + "\n" + HELPER + "\n" + src[insert_at:]

# Patch obvious direct fallback return sites conservatively.
# This does not hard-code normal answers; it only blocks illegal raw fallback in non-Quick modes.
patterns = [
    (
        r"(\breturn\s+)(raw_text|raw|text|response)(\s*(?:#.*)?\n)",
        r"\1_eli_guard_nonquick_fallback_text(\2, locals().get('mode', locals().get('reasoning_mode', None)), 'direct return fallback guarded')\3",
    ),
]

changed = False
for pat, repl in patterns:
    new_src = re.sub(pat, repl, src)
    if new_src != src:
        changed = True
        src = new_src

ENGINE.write_text(src, encoding="utf-8")
REPORT.write_text(
    f"backup={backup}\nchanged={changed}\nengine={ENGINE}\n",
    encoding="utf-8",
)

print(f"[OK] patched {ENGINE}")
print(f"[OK] backup {backup}")
print(f"[OK] changed_return_sites={changed}")
