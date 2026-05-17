#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()
STAMP = subprocess.check_output(["date", "+%Y%m%d_%H%M%S"], text=True).strip()
OUT = ROOT / f"ops/reports/phase12d_guard_get_chat_response_failed_evidence_{STAMP}"
OUT.mkdir(parents=True, exist_ok=True)

engine = ROOT / "eli/kernel/engine.py"
src = engine.read_text(encoding="utf-8", errors="replace")

block = r'''

# --- Phase 12d: final GGUF entry guard for failed executor evidence ----
# Previous guards caught _synthesize_answer() and control framing. The live
# process() lane still reached _get_chat_response() with failed executor
# evidence. This guard stops the final GGUF entry point itself.
try:
    if not globals().get("_ELI_PHASE12D_GET_CHAT_RESPONSE_FAILURE_GUARD_INSTALLED"):
        _ELI_PHASE12D_GET_CHAT_RESPONSE_FAILURE_GUARD_INSTALLED = True

        _eli_phase12d_prev_get_chat_response = CognitiveEngine._get_chat_response

        def _eli_phase12d_extract_query_from_prompt(prompt: str) -> str:
            import re as _re
            text = str(prompt or "")

            for pat in (
                r"USER ASKED:\s*(.+?)(?:\n\n|$)",
                r"USER QUESTION:\s*(.+?)(?:\n\n|$)",
                r"USER:\s*(.+?)(?:\n\n|$)",
            ):
                m = _re.search(pat, text, _re.I | _re.S)
                if m:
                    return m.group(1).strip()[:1000]

            return ""

        def _eli_phase12d_action_from_prompt(prompt: str) -> str:
            import re as _re
            text = str(prompt or "")

            for pat in (
                r"'action'\s*:\s*'([^']+)'",
                r'"action"\s*:\s*"([^"]+)"',
                r"\baction\s*=\s*([A-Z_]+)",
                r"\baction:\s*([A-Z_]+)",
            ):
                m = _re.search(pat, text)
                if m:
                    return m.group(1).upper().strip()

            if "ANALYZE_PDF" in text or "analyze_pdf" in text.lower():
                return "ANALYZE_PDF"

            return "ACTION"

        def _eli_phase12d_get_chat_response_guard(self, prompt, *args, **kwargs):
            text = str(prompt or "")
            low = text.lower()

            looks_failed_executor = (
                "'ok': false" in low
                or '"ok": false' in low
                or "ok=false" in low
                or "ok: false" in low
                or "filenotfounderror" in low
                or "file not found" in low
                or "successful: 0 | failed:" in low
                or "this is attempt" in low and "analyze_pdf failure" in low
                or "execute result:" in low and "ok': false" in low
            )

            looks_executor_context = (
                "execute result" in low
                or "agent:system" in low
                or "grounded_evidence" in low
                or "agent data:" in low
                or "analyze_pdf" in low
                or "runtime_audit" in low
            )

            if looks_failed_executor and looks_executor_context:
                try:
                    action = _eli_phase12d_action_from_prompt(text)
                    query = _eli_phase12d_extract_query_from_prompt(text)

                    if "_eli_phase12_failed_executor_surface" in globals():
                        return _eli_phase12_failed_executor_surface(
                            text,
                            query or text[:500],
                            action=action,
                        )

                    return (
                        f"I did not successfully complete `{action}`.\n\n"
                        "The executor evidence reports `ok=False`, so I am not going "
                        "to claim the action succeeded."
                    )
                except Exception as _guard_err:
                    print(f"[ENGINE] Phase 12d failed-evidence get_chat_response guard failed: {_guard_err}", flush=True)

            return _eli_phase12d_prev_get_chat_response(self, prompt, *args, **kwargs)

        CognitiveEngine._get_chat_response = _eli_phase12d_get_chat_response_guard

        print("[ENGINE] Phase 12d failed-evidence GGUF entry guard installed", flush=True)

except Exception as _eli_phase12d_guard_err:
    print(f"[ENGINE] Phase 12d failed-evidence GGUF entry guard failed: {_eli_phase12d_guard_err}", flush=True)
'''

changed = []

if "_ELI_PHASE12D_GET_CHAT_RESPONSE_FAILURE_GUARD_INSTALLED" not in src:
    (OUT / "eli__kernel__engine.py.before").write_text(src, encoding="utf-8")
    engine.write_text(src.rstrip() + "\n" + block + "\n", encoding="utf-8")
    changed.append("eli/kernel/engine.py")

probe = ROOT / "ops/probes/phase12d_get_chat_response_failed_evidence_probe.py"
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
The following grounded evidence is authoritative.

<grounded_evidence>
[AGENT:system] execute result: {'ok': False, 'action': 'ANALYZE_PDF', 'error': '/tmp/nonexistent_phase12d.pdf',
'content': '/tmp/nonexistent_phase12d.pdf', 'response': '/tmp/nonexistent_phase12d.pdf'}
FileNotFoundError: /tmp/nonexistent_phase12d.pdf
</grounded_evidence>

USER ASKED: read and summarise /tmp/nonexistent_phase12d.pdf

ANSWER:
"""

out = dummy._get_chat_response(prompt)

print(out)
print("--- checks ---")
print("contains_fake_success:", any(x in out.lower() for x in [
    "i'd be happy", "let me read", "here are the main points", "summarize the content"
]))
print("contains_failure:", "did not successfully" in out.lower() or "failed" in out.lower() or "ok=false" in out.lower())
print("contains_path:", "/tmp/nonexistent_phase12d.pdf" in out)
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
    "# Phase 12d Failed Evidence GGUF Entry Guard\n\n"
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
