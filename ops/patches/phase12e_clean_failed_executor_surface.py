#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()
STAMP = subprocess.check_output(["date", "+%Y%m%d_%H%M%S"], text=True).strip()
OUT = ROOT / f"ops/reports/phase12e_clean_failed_executor_surface_{STAMP}"
OUT.mkdir(parents=True, exist_ok=True)

engine = ROOT / "eli/kernel/engine.py"
src = engine.read_text(encoding="utf-8", errors="replace")

block = r'''

# --- Phase 12e: clean failed-executor surface, scoped evidence only -----
# Phase 12d correctly stopped failed executor evidence from entering GGUF,
# but it scanned the entire prompt and could pick up stale persona/memory
# artefacts such as PAUSE_MEDIA, old PDF paths, or "Runtime Persona Notes".
# This guard scopes parsing to the actual failed executor evidence.
try:
    if not globals().get("_ELI_PHASE12E_CLEAN_FAILED_EXECUTOR_SURFACE_INSTALLED"):
        _ELI_PHASE12E_CLEAN_FAILED_EXECUTOR_SURFACE_INSTALLED = True

        _eli_phase12e_prev_get_chat_response = CognitiveEngine._get_chat_response

        def _eli_phase12e_user_query(prompt: str) -> str:
            import re as _re
            text = str(prompt or "")
            for pat in (
                r"USER ASKED:\s*(.+?)(?:\n\n|$)",
                r"USER QUESTION:\s*(.+?)(?:\n\n|$)",
                r"USER:\s*(.+?)(?:\n\n|$)",
            ):
                m = _re.search(pat, text, _re.I | _re.S)
                if m:
                    return m.group(1).strip()[:1200]
            return ""

        def _eli_phase12e_relevant_failure_block(prompt: str) -> str:
            import re as _re
            text = str(prompt or "")

            # Prefer explicit executor-result lines. This avoids persona.auto,
            # memory notes, stale failure history, and unrelated action names.
            lines = text.splitlines()
            selected = []

            for i, line in enumerate(lines):
                low = line.lower()
                if (
                    "execute result" in low
                    and ("'ok': false" in low or '"ok": false' in low)
                ):
                    selected.append(line.strip())
                    # Capture a small local window for traceback/error/path.
                    for j in range(i + 1, min(len(lines), i + 8)):
                        nxt = lines[j].strip()
                        nl = nxt.lower()
                        if not nxt:
                            continue
                        if (
                            "filenotfounderror" in nl
                            or "traceback" in nl
                            or "error" in nl
                            or ".pdf" in nl
                            or "attempt" in nl and "failure" in nl
                        ):
                            selected.append(nxt)

            if selected:
                return "\n".join(selected)

            # Fallback: extract grounded_evidence only, never the full prompt.
            m = _re.search(
                r"<grounded_evidence>\s*(.*?)\s*</grounded_evidence>",
                text,
                _re.I | _re.S,
            )
            if m:
                block = m.group(1).strip()
                # Keep only lines directly relevant to failed action.
                filtered = []
                for raw in block.splitlines():
                    s = raw.strip()
                    low = s.lower()
                    if (
                        "'ok': false" in low
                        or '"ok": false' in low
                        or "execute result" in low
                        or "filenotfounderror" in low
                        or "file not found" in low
                        or "error" in low
                        or ".pdf" in low
                        or "analyze_pdf" in low
                    ):
                        filtered.append(s)
                return "\n".join(filtered) if filtered else block[:3000]

            # Fallback: AGENT DATA section only.
            m = _re.search(
                r"AGENT DATA:\s*(.*?)(?:\n\nUSER QUESTION:|\n\nYOUR ANSWER:|$)",
                text,
                _re.I | _re.S,
            )
            if m:
                return m.group(1).strip()[:3000]

            return ""

        def _eli_phase12e_is_failed_block(block: str) -> bool:
            low = str(block or "").lower()
            return (
                "'ok': false" in low
                or '"ok": false' in low
                or "ok=false" in low
                or "ok: false" in low
                or "filenotfounderror" in low
                or "file not found" in low
                or "successful: 0 | failed:" in low
                or "analyze_pdf failure" in low
            )

        def _eli_phase12e_action(block: str, query: str = "") -> str:
            import re as _re
            text = str(block or "")
            q = str(query or "").lower()

            for pat in (
                r"'action'\s*:\s*'([^']+)'",
                r'"action"\s*:\s*"([^"]+)"',
                r"\baction\s*=\s*([A-Z_]+)",
                r"\baction:\s*([A-Z_]+)",
            ):
                m = _re.search(pat, text)
                if m:
                    return m.group(1).upper().strip()

            low = text.lower()
            if "analyze_pdf" in low or (".pdf" in q and any(x in q for x in ("read", "summari", "analyse", "analyze"))):
                return "ANALYZE_PDF"

            return "ACTION"

        def _eli_phase12e_paths(block: str, query: str = "") -> list[str]:
            import re as _re
            src = f"{block}\n{query}"
            out = []
            for m in _re.finditer(r"(/[^,\n\r`\"']+?\.pdf)\b", src, _re.I):
                p = m.group(1).strip().rstrip(" .;:)]}")
                if p not in out:
                    out.append(p)
            return out[:8]

        def _eli_phase12e_errors(block: str) -> list[str]:
            import re as _re
            text = str(block or "")
            out = []

            for pat in (
                r"'error'\s*:\s*'([^']{1,300})'",
                r'"error"\s*:\s*"([^"]{1,300})"',
                r"(FileNotFoundError:\s*[^\n\r]{1,300})",
                r"(No such file or directory[^\n\r]{0,200})",
                r"(This is attempt\s+\d+\s+for the same\s+[A-Z_]+\s+failure\s+`[^`]+`)",
            ):
                for m in _re.finditer(pat, text):
                    s = m.group(1).strip()
                    if s and s not in out:
                        out.append(s)

            return out[:8]

        def _eli_phase12e_surface(block: str, query: str = "") -> str:
            action = _eli_phase12e_action(block, query)
            paths = _eli_phase12e_paths(block, query)
            errors = _eli_phase12e_errors(block)

            if action == "ANALYZE_PDF":
                lines = ["I did not successfully analyse the PDF request."]
            else:
                lines = [f"I did not successfully complete `{action}`."]

            if errors:
                lines.append("")
                lines.append("What failed:")
                for e in errors:
                    lines.append(f"- {e}")

            if paths:
                lines.append("")
                lines.append("Path(s) involved:")
                for p in paths:
                    lines.append(f"- `{p}`")

            lines.append("")
            lines.append(
                "I am not going to claim the document was read or summarised, "
                "because the executor evidence says the action failed."
            )

            return "\n".join(lines).strip()

        # Replace the global surface too, so Phase 12/12b/12d callers become clean.
        def _eli_phase12_failed_executor_surface(evidence, query, action=None):  # type: ignore[no-redef]
            block = _eli_phase12e_relevant_failure_block(str(evidence or ""))
            q = str(query or "")
            if not block:
                block = str(evidence or "")[:3000]
            return _eli_phase12e_surface(block, q)

        globals()["_eli_phase12_failed_executor_surface"] = _eli_phase12_failed_executor_surface

        def _eli_phase12e_get_chat_response_guard(self, prompt, *args, **kwargs):
            text = str(prompt or "")
            block = _eli_phase12e_relevant_failure_block(text)
            if block and _eli_phase12e_is_failed_block(block):
                query = _eli_phase12e_user_query(text)
                return _eli_phase12e_surface(block, query)

            return _eli_phase12e_prev_get_chat_response(self, prompt, *args, **kwargs)

        CognitiveEngine._get_chat_response = _eli_phase12e_get_chat_response_guard

        print("[ENGINE] Phase 12e clean failed-executor surface installed", flush=True)

except Exception as _eli_phase12e_clean_failed_surface_err:
    print(f"[ENGINE] Phase 12e clean failed-executor surface failed: {_eli_phase12e_clean_failed_surface_err}", flush=True)
'''

changed = []

if "_ELI_PHASE12E_CLEAN_FAILED_EXECUTOR_SURFACE_INSTALLED" not in src:
    (OUT / "eli__kernel__engine.py.before").write_text(src, encoding="utf-8")
    engine.write_text(src.rstrip() + "\n" + block + "\n", encoding="utf-8")
    changed.append("eli/kernel/engine.py")

probe = ROOT / "ops/probes/phase12e_clean_failed_surface_probe.py"
probe.write_text(r'''#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eli.kernel.engine import CognitiveEngine

class Dummy(CognitiveEngine):
    def __init__(self):
        pass

dummy = Dummy()

prompt = """
## Runtime Persona Notes
Some stale action mentions PAUSE_MEDIA and unrelated old path /tmp/nonexistent_b.pdf.
## Recent Failure Patterns
Old stale path /Exergetic_Coherence_Revoloution.pdf.

<grounded_evidence>
[AGENT:system] execute result: {'ok': False, 'action': 'ANALYZE_PDF', 'error': '/tmp/nonexistent_phase12e.pdf',
'content': '/tmp/nonexistent_phase12e.pdf', 'response': '/tmp/nonexistent_phase12e.pdf'}
FileNotFoundError: /tmp/nonexistent_phase12e.pdf
</grounded_evidence>

USER ASKED: read and summarise /tmp/nonexistent_phase12e.pdf

ANSWER:
"""

out = dummy._get_chat_response(prompt)

print(out)
print("--- checks ---")
low = out.lower()
print("contains_fake_success:", any(x in low for x in [
    "i'd be happy", "let me read", "here are the main points", "summarize the content"
]))
print("contains_failure:", "did not successfully" in low or "failed" in low)
print("contains_pdf_action:", "analyse the pdf request" in low or "analyze_pdf" in out)
print("contains_wrong_pause:", "pause_media" in low)
print("contains_stale_path_b:", "/tmp/nonexistent_b.pdf" in out)
print("contains_old_exergetic_path:", "/Exergetic_Coherence_Revoloution.pdf" in out)
print("contains_target_path:", "/tmp/nonexistent_phase12e.pdf" in out)
''', encoding="utf-8")
probe.chmod(0o755)

cp = subprocess.run(
    [sys.executable, "-m", "compileall", "-q", "eli"],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
)

summary = OUT / "SUMMARY.md"
summary.write_text(
    "# Phase 12e Clean Failed Executor Surface\n\n"
    "Changed files:\n"
    + ("".join(f"- {x}\n" for x in changed) if changed else "- none\n")
    + "\nCompile output:\n\n```text\n"
    + cp.stdout
    + "\n```\n",
    encoding="utf-8",
)

print(f"REPORT: {OUT}")
print(summary.read_text())

if cp.returncode != 0:
    raise SystemExit(cp.returncode)
