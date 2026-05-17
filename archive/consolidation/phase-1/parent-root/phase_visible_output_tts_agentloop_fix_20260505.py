from pathlib import Path
import re
import shutil
import time

ROOT = Path.cwd()
STAMP = time.strftime("%Y%m%d_%H%M%S")
PHASE = f"phase_visible_output_tts_agentloop_fix_{STAMP}"
BACKUP = ROOT / "ops" / "backups" / PHASE
REPORT = ROOT / "ops" / "reports" / PHASE
BACKUP.mkdir(parents=True, exist_ok=True)
REPORT.mkdir(parents=True, exist_ok=True)

FILES = [
    ROOT / "eli/runtime/visible_output.py",
    ROOT / "eli/perception/tts_router.py",
    ROOT / "eli/cognition/chat_model.py",
    ROOT / "tests/test_reasoning_surface_hardening.py",
]

def backup(path: Path):
    if path.exists():
        dst = BACKUP / path.relative_to(ROOT)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dst)

for f in FILES:
    backup(f)

# ---------------------------------------------------------------------
# 1. Stronger central visible-output contract:
#    extract explicit final answer before nuking private sections.
# ---------------------------------------------------------------------
visible = ROOT / "eli/runtime/visible_output.py"
visible.write_text(r'''"""
Central visible-output contract for ELI.

Anything that may be displayed, spoken, persisted as assistant-visible text,
or returned through a direct bypass path should pass through visible_text().
"""

from __future__ import annotations

import re
from typing import Any


_PRIVATE_MARKER_RE = re.compile(
    r"(?is)"
    r"(chain[-_ ]?of[-_ ]?thought|reasoning chain|scratchpad|hidden reasoning|"
    r"private reasoning|internal reasoning|tree[-_ ]?of[-_ ]?thoughts?|"
    r"self[-_ ]?consistency|constitutional critique|draft critique|"
    r"critique pass|revision pass|active reasoning mode|reasoning mode self-awareness)"
)

_FINAL_MARKER_RE = re.compile(
    r"(?is)"
    r"(?:^|\n|\r)"
    r"\s*(?:final\s+answer|final|answer|response)\s*[:\-]\s*"
)


def _extract_explicit_final(text: str) -> str:
    """
    If a model emits private scaffolding but also provides an explicit final
    section, keep the final section instead of collapsing everything to "...".
    """
    s = "" if text is None else str(text)
    if not s.strip():
        return ""

    if not _PRIVATE_MARKER_RE.search(s):
        return s

    matches = list(_FINAL_MARKER_RE.finditer(s))
    if not matches:
        return s

    start = matches[-1].end()
    final = s[start:].strip()

    # Remove obvious trailing private blocks if the model put them after final.
    final = re.split(
        r"(?is)\n\s*(?:chain[-_ ]?of[-_ ]?thought|scratchpad|hidden reasoning|private reasoning|critique pass)\s*[:\-]",
        final,
        maxsplit=1,
    )[0].strip()

    return final or s


def visible_text(
    text: Any,
    *,
    user_input: str = "",
    is_grounded: bool = False,
    evidence: str | None = None,
) -> str:
    raw = _extract_explicit_final("" if text is None else str(text))

    try:
        from eli.cognition.response_sanitizer import sanitize_assistant_text
        raw = sanitize_assistant_text(raw)
    except Exception:
        pass

    try:
        from eli.cognition.output_governor import govern_output, normalize_assistant_text
        raw = normalize_assistant_text(user_input or "", raw)
        raw = govern_output(raw, is_grounded=is_grounded, evidence=evidence or "")
    except Exception:
        pass

    try:
        from eli.cognition.response_sanitizer import sanitize_assistant_text
        raw = sanitize_assistant_text(raw)
    except Exception:
        pass

    return str(raw or "").strip()


__all__ = ["visible_text"]
''', encoding="utf-8")

# ---------------------------------------------------------------------
# 2. Replace TTS visible cleaner with central contract early-return.
# ---------------------------------------------------------------------
tts = ROOT / "eli/perception/tts_router.py"
s = tts.read_text(encoding="utf-8")

new_tts_func = r'''def _eli_tts_visible_text(text) -> str:
    """
    Final-only TTS surface.

    TTS must never read private reasoning scaffolds. Use the central visible
    output contract and return its result directly.
    """
    try:
        from eli.runtime.visible_output import visible_text as _eli_visible_text
        clean = _eli_visible_text(text)
    except Exception:
        clean = str(text or "").strip()

    return clean if clean else "..."
'''

pattern = r"def _eli_tts_visible_text\(text\).*?(?=\n\ndef |\Z)"
if re.search(pattern, s, flags=re.S):
    s = re.sub(pattern, new_tts_func, s, count=1, flags=re.S)
else:
    s += "\n\n" + new_tts_func + "\n"

tts.write_text(s, encoding="utf-8")

# ---------------------------------------------------------------------
# 3. Fix chat_model.chat_response(system=...) mismatch and sanitize output.
# ---------------------------------------------------------------------
chat_model = ROOT / "eli/cognition/chat_model.py"
s = chat_model.read_text(encoding="utf-8")

s = s.replace(
    "def chat_response(user: str, *, model: Optional[str] = None, host: Optional[str] = None) -> str:",
    "def chat_response(user: str, *, model: Optional[str] = None, host: Optional[str] = None, system: Optional[str] = None) -> str:",
)

s = s.replace(
    "    system = build_context(user)\n",
    "    base_system = build_context(user)\n"
    "    if system:\n"
    "        system = (str(system).strip() + \"\\n\\n\" + str(base_system).strip()).strip()\n"
    "    else:\n"
    "        system = base_system\n",
    1,
)

s = s.replace(
    "    _persist_turns(user, out, model=mdl)\n"
    "    return out\n",
    "    try:\n"
    "        from eli.runtime.visible_output import visible_text as _eli_visible_text\n"
    "        out = _eli_visible_text(out, user_input=user)\n"
    "    except Exception:\n"
    "        pass\n"
    "\n"
    "    _persist_turns(user, out, model=mdl)\n"
    "    return out\n",
    1,
)

chat_model.write_text(s, encoding="utf-8")

# ---------------------------------------------------------------------
# 4. Strengthen the test to verify visible_text and TTS both preserve final.
# ---------------------------------------------------------------------
test = ROOT / "tests/test_reasoning_surface_hardening.py"
s = test.read_text(encoding="utf-8")

extra = r'''

def test_visible_output_preserves_explicit_final_answer_after_private_marker():
    from eli.runtime.visible_output import visible_text

    dirty = "Scratchpad: private junk. Final answer: Preserve this exact final."
    clean = visible_text(dirty)
    low = clean.lower()

    assert "scratchpad" not in low
    assert "private junk" not in low
    assert "preserve this exact final" in low
'''

if "test_visible_output_preserves_explicit_final_answer_after_private_marker" not in s:
    s += extra

test.write_text(s, encoding="utf-8")

(REPORT / "summary.txt").write_text(
    "\n".join([
        "Patched visible_output.visible_text() to preserve explicit Final answer sections.",
        "Replaced tts_router._eli_tts_visible_text() with central visible-output early return.",
        "Fixed chat_model.chat_response(system=...) compatibility used by planning/agent_loop.py.",
        "Added final-answer preservation regression test.",
        f"Backups: {BACKUP}",
    ]) + "\n",
    encoding="utf-8",
)

print(f"✅ Applied {PHASE}")
print(f"Backups: {BACKUP}")
print(f"Report:  {REPORT}")
