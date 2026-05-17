#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()
STAMP = subprocess.check_output(["date", "+%Y%m%d_%H%M%S"], text=True).strip()
OUT = ROOT / f"ops/reports/phase12_failed_executor_no_fake_success_{STAMP}"
OUT.mkdir(parents=True, exist_ok=True)

engine = ROOT / "eli/kernel/engine.py"
src = engine.read_text(encoding="utf-8", errors="replace")

block = r'''

# --- Phase 12: failed executor evidence must not become fake success ----
# Contract:
#   If a tool/action/executor result is failed evidence, do not send it into
#   normal GGUF prose synthesis where the model can hallucinate success.
#   Return a concise, natural failure explanation derived only from the
#   executor evidence. This is not a Quick-mode raw bypass; it is a governed
#   failure surface for non-Quick synthesis paths.
try:
    if not globals().get("_ELI_PHASE12_FAILED_EXECUTOR_GUARD_INSTALLED"):
        _ELI_PHASE12_FAILED_EXECUTOR_GUARD_INSTALLED = True

        _eli_phase12_prev_synthesize_answer = CognitiveEngine._synthesize_answer

        def _eli_phase12_is_failed_executor_evidence(evidence, action=None) -> bool:
            import re as _re

            ev = str(evidence or "")
            low = ev.lower()
            act = str(action or "").upper().strip()

            # Only act on executor/control evidence, not ordinary discussion.
            actionish = bool(act and act not in {"CHAT", "NONE"})
            if not actionish:
                actionish = any(x in low for x in (
                    "'action':", '"action":', "action=", "analyze_pdf",
                    "runtime_audit", "execute result", "agent:system",
                    "response_mode",
                ))

            if not actionish:
                return False

            failed = (
                _re.search(r'["\']ok["\']\s*:\s*false\b', low) is not None
                or _re.search(r'["\']ok["\']\s*:\s*False\b', ev) is not None
                or _re.search(r'\bok\s*=\s*false\b', low) is not None
                or _re.search(r'\bok:\s*false\b', low) is not None
                or "successful: 0 | failed:" in low
                or "file not found" in low
                or "filenotfounderror" in low
                or "traceback" in low and "failed" in low
            )

            return bool(failed)

        def _eli_phase12_extract_failed_action(evidence, action=None) -> str:
            import re as _re

            act = str(action or "").upper().strip()
            if act and act not in {"CHAT", "NONE"}:
                return act

            ev = str(evidence or "")
            pats = [
                r'["\']action["\']\s*:\s*["\']([^"\']+)["\']',
                r'\baction\s*=\s*([A-Z_]+)',
                r'\baction:\s*([A-Z_]+)',
            ]
            for p in pats:
                m = _re.search(p, ev)
                if m:
                    return m.group(1).upper().strip()

            if "ANALYZE_PDF" in ev or "analyze_pdf" in ev.lower():
                return "ANALYZE_PDF"

            return "ACTION"

        def _eli_phase12_extract_paths(evidence) -> list[str]:
            import re as _re

            ev = str(evidence or "")
            paths = []

            for m in _re.finditer(r'(/[^,\n\r`"\']+?\.pdf)\b', ev, _re.I):
                p = m.group(1).strip()
                p = p.rstrip(" .;:)]}")
                if p not in paths:
                    paths.append(p)

            return paths[:12]

        def _eli_phase12_extract_error_lines(evidence) -> list[str]:
            import re as _re

            ev = str(evidence or "")
            lines = []

            # Pull compact error fields first.
            for pat in [
                r'["\']error["\']\s*:\s*["\']([^"\']{1,300})["\']',
                r'\bError:\s*([^\n\r]{1,300})',
                r'(FileNotFoundError:\s*[^\n\r]{1,300})',
                r'(No such file or directory[^\n\r]{0,200})',
                r'(Missing path[^\n\r]{0,200})',
            ]:
                for m in _re.finditer(pat, ev):
                    item = m.group(1).strip()
                    if item and item not in lines:
                        lines.append(item)

            # If aggregated multi-PDF output is present, keep its useful lines.
            for raw in ev.splitlines():
                s = raw.strip()
                if not s:
                    continue
                low = s.lower()
                if (
                    "successful:" in low
                    or s.startswith("## ")
                    or s.startswith("Source:")
                    or s.startswith("Error:")
                ):
                    if s not in lines:
                        lines.append(s)

            return lines[:20]

        def _eli_phase12_failed_executor_surface(evidence, query, action=None) -> str:
            act = _eli_phase12_extract_failed_action(evidence, action)
            paths = _eli_phase12_extract_paths(evidence)
            errors = _eli_phase12_extract_error_lines(evidence)

            lines = []

            if act == "ANALYZE_PDF":
                lines.append("I did not successfully analyse the PDF request.")
            else:
                lines.append(f"I did not successfully complete `{act}`.")

            if errors:
                lines.append("")
                lines.append("What failed:")
                for e in errors[:12]:
                    lines.append(f"- {e}")

            if paths:
                lines.append("")
                lines.append("Path(s) involved:")
                for p in paths[:8]:
                    lines.append(f"- `{p}`")

            lines.append("")
            lines.append(
                "I am not going to claim the document was read or summarised, "
                "because the executor evidence says the action failed."
            )

            return "\n".join(lines).strip()

        def _eli_phase12_synthesize_answer_guard(
            self,
            evidence,
            query,
            reasoning_mode=None,
            compact_override=False,
            max_tokens_override=None,
            action=None,
            *args,
            **kwargs,
        ):
            if _eli_phase12_is_failed_executor_evidence(evidence, action=action):
                return _eli_phase12_failed_executor_surface(evidence, query, action=action)

            return _eli_phase12_prev_synthesize_answer(
                self,
                evidence,
                query,
                reasoning_mode=reasoning_mode,
                compact_override=compact_override,
                max_tokens_override=max_tokens_override,
                action=action,
                *args,
                **kwargs,
            )

        CognitiveEngine._synthesize_answer = _eli_phase12_synthesize_answer_guard

        print("[ENGINE] Phase 12 failed-executor no-fake-success guard installed", flush=True)

except Exception as _eli_phase12_failed_executor_guard_err:
    print(f"[ENGINE] Phase 12 failed-executor guard failed: {_eli_phase12_failed_executor_guard_err}", flush=True)
'''

if "_ELI_PHASE12_FAILED_EXECUTOR_GUARD_INSTALLED" not in src:
    backup = OUT / "eli__kernel__engine.py.before"
    backup.write_text(src, encoding="utf-8")
    engine.write_text(src.rstrip() + "\n" + block + "\n", encoding="utf-8")
    changed = ["eli/kernel/engine.py"]
else:
    changed = []

probe = ROOT / "ops/probes/phase12_failed_executor_guard_probe.py"
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

failed_evidence = """
{'ok': False, 'action': 'ANALYZE_PDF', 'error': '/tmp/nonexistent_a.pdf',
 'content': '/tmp/nonexistent_a.pdf',
 'response': '/tmp/nonexistent_a.pdf'}
FileNotFoundError: /tmp/nonexistent_a.pdf
"""

out = dummy._synthesize_answer(
    failed_evidence,
    "read and summarise /tmp/nonexistent_a.pdf",
    reasoning_mode="constitutional_ai",
    action="ANALYZE_PDF",
)

print(out)
print("--- checks ---")
print("contains_fake_success:", any(x in out.lower() for x in [
    "i'd be happy", "let me read", "here are the main points", "summarize the content"
]))
print("contains_failure:", "did not successfully" in out.lower() or "failed" in out.lower())
print("contains_path:", "/tmp/nonexistent_a.pdf" in out)
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
    "# Phase 12 Failed Executor No-Fake-Success Guard\n\n"
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
