from pathlib import Path
import re
import shutil
import time

ROOT = Path.cwd()
STAMP = time.strftime("%Y%m%d_%H%M%S")
PHASE = f"phase_reasoning_surface_hardening_{STAMP}"
BACKUP = ROOT / "ops" / "backups" / PHASE
REPORT = ROOT / "ops" / "reports" / PHASE
BACKUP.mkdir(parents=True, exist_ok=True)
REPORT.mkdir(parents=True, exist_ok=True)

targets = [
    ROOT / "eli/kernel/engine.py",
    ROOT / "eli/perception/tts_router.py",
    ROOT / "tests/test_reasoning_surface_hardening.py",
    ROOT / "eli/runtime/visible_output.py",
]

def backup(path: Path):
    if path.exists():
        rel = path.relative_to(ROOT)
        dst = BACKUP / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dst)

for p in targets:
    backup(p)

# ---------------------------------------------------------------------
# 1. Add central visible-output sanitizer.
# ---------------------------------------------------------------------
visible_output = ROOT / "eli/runtime/visible_output.py"
visible_output.write_text(r'''"""
Central visible-output contract for ELI.

Anything that may be displayed, spoken, persisted as assistant-visible text,
or returned through a direct bypass path should pass through visible_text().
"""

from __future__ import annotations

from typing import Any


def visible_text(
    text: Any,
    *,
    user_input: str = "",
    is_grounded: bool = False,
    evidence: str | None = None,
) -> str:
    raw = "" if text is None else str(text)

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
# 2. Harden engine prompt wording.
#    Do not remove internal mode keys; remove visible self-awareness wording.
# ---------------------------------------------------------------------
engine = ROOT / "eli/kernel/engine.py"
s = engine.read_text(encoding="utf-8")

replacements = {
    'f"\\nREASONING MODE SELF-AWARENESS:"':
        'f"\\nPRIVATE RESPONSE STRATEGY CONTRACT:"',

    'f"\\n- Active mode: {_c_mode_display}"':
        'f"\\n- Internal strategy label: {_c_mode_display}"',

    'f"\\n- Your current active reasoning mode is: {_mode_tail_display}"':
        'f"\\n- Internal strategy label: {_mode_tail_display}"',

    'f"\\n- If asked, report mode as EXACTLY: \\"{_c_mode_display}\\""':
        'f"\\n- If explicitly asked about the selected public mode label, answer exactly: \\"{_c_mode_display}\\""',

    'f"\\n- If asked what mode you are using, answer EXACTLY: \\"{_mode_tail_display}\\""':
        'f"\\n- If explicitly asked about the selected public mode label, answer exactly: \\"{_mode_tail_display}\\""',
}

for old, new in replacements.items():
    s = s.replace(old, new)

# Extra belt-and-braces: remove any surviving exact phrase.
s = s.replace("REASONING MODE SELF-AWARENESS", "PRIVATE RESPONSE STRATEGY CONTRACT")

engine.write_text(s, encoding="utf-8")

# ---------------------------------------------------------------------
# 3. Harden TTS visible text path.
# ---------------------------------------------------------------------
tts = ROOT / "eli/perception/tts_router.py"
if tts.exists():
    s = tts.read_text(encoding="utf-8")

    # Add visible_text import lazily inside _eli_tts_visible_text if possible.
    pattern = r"(def _eli_tts_visible_text\(text\).*?:\n)"
    if re.search(pattern, s, flags=re.S):
        def repl(m):
            head = m.group(1)
            return head + (
                "    try:\n"
                "        from eli.runtime.visible_output import visible_text as _eli_visible_text\n"
                "        text = _eli_visible_text(text)\n"
                "    except Exception:\n"
                "        pass\n"
            )
        s = re.sub(pattern, repl, s, count=1, flags=re.S)
    else:
        s += r'''

def _eli_tts_visible_text(text):
    try:
        from eli.runtime.visible_output import visible_text as _eli_visible_text
        return _eli_visible_text(text)
    except Exception:
        return str(text or "").strip()
'''

    tts.write_text(s, encoding="utf-8")

# ---------------------------------------------------------------------
# 4. Add regression tests.
# ---------------------------------------------------------------------
test = ROOT / "tests/test_reasoning_surface_hardening.py"
test.write_text(r'''from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_engine_has_no_reasoning_mode_self_awareness_phrase():
    text = (ROOT / "eli/kernel/engine.py").read_text(encoding="utf-8")
    assert "REASONING MODE SELF-AWARENESS" not in text


def test_visible_output_strips_private_reasoning_markers():
    from eli.runtime.visible_output import visible_text

    dirty = """
    REASONING MODE SELF-AWARENESS:
    - Active mode: Chain of Thought
    Chain-of-thought: first I will expose hidden steps.
    Final answer: use the patched visible-output contract.
    """

    clean = visible_text(dirty, user_input="test")
    low = clean.lower()

    assert "reasoning mode self-awareness" not in low
    assert "chain-of-thought" not in low
    assert "hidden steps" not in low
    assert "patched visible-output contract" in low


def test_tts_visible_text_uses_visible_contract():
    from eli.perception.tts_router import _eli_tts_visible_text

    dirty = "Chain-of-thought: bad leak. Final answer: speak only this."
    clean = _eli_tts_visible_text(dirty)
    low = clean.lower()

    assert "chain-of-thought" not in low
    assert "bad leak" not in low
    assert "speak only this" in low
''', encoding="utf-8")

(REPORT / "changed.txt").write_text(
    "\n".join([
        "Added eli/runtime/visible_output.py",
        "Patched engine.py prompt wording away from REASONING MODE SELF-AWARENESS",
        "Wrapped TTS visible text through central visible_output contract",
        "Added tests/test_reasoning_surface_hardening.py",
        f"Backups: {BACKUP}",
    ]) + "\n",
    encoding="utf-8",
)

print(f"✅ Applied {PHASE}")
print(f"Backups: {BACKUP}")
print(f"Report:  {REPORT}")
