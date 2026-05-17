#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()
STAMP = subprocess.check_output(["date", "+%Y%m%d_%H%M%S"], text=True).strip()
OUT = ROOT / f"ops/reports/phase12b_guard_failed_control_synthesis_{STAMP}"
OUT.mkdir(parents=True, exist_ok=True)

engine = ROOT / "eli/kernel/engine.py"
src = engine.read_text(encoding="utf-8", errors="replace")

block = r'''

# --- Phase 12b: failed control evidence must not call GGUF -------------
# Phase 12 guarded _synthesize_answer(). The full non-Quick control path can
# also call _synthesize_control_with_mode_framing(), which invokes GGUF
# directly. Guard that path too.
try:
    if not globals().get("_ELI_PHASE12B_FAILED_CONTROL_GUARD_INSTALLED"):
        _ELI_PHASE12B_FAILED_CONTROL_GUARD_INSTALLED = True

        _eli_phase12b_prev_control_synth = CognitiveEngine._synthesize_control_with_mode_framing

        def _eli_phase12b_control_synth_guard(
            self,
            user_input,
            evidence_text,
            action,
            reasoning_mode,
            *args,
            **kwargs,
        ):
            try:
                is_failed = False
                if "_eli_phase12_is_failed_executor_evidence" in globals():
                    is_failed = _eli_phase12_is_failed_executor_evidence(
                        evidence_text,
                        action=action,
                    )
                else:
                    ev_low = str(evidence_text or "").lower()
                    act = str(action or "").upper().strip()
                    is_failed = (
                        act not in {"", "CHAT", "NONE"}
                        and (
                            "'ok': false" in ev_low
                            or '"ok": false' in ev_low
                            or "ok=false" in ev_low
                            or "ok: false" in ev_low
                            or "filenotfounderror" in ev_low
                            or "file not found" in ev_low
                            or "successful: 0 | failed:" in ev_low
                        )
                    )

                if is_failed:
                    if "_eli_phase12_failed_executor_surface" in globals():
                        return _eli_phase12_failed_executor_surface(
                            evidence_text,
                            user_input,
                            action=action,
                        )

                    return (
                        f"I did not successfully complete `{action}`.\n\n"
                        f"The executor evidence reports a failure, so I am not going "
                        f"to claim the action succeeded."
                    )
            except Exception as _guard_err:
                print(f"[ENGINE] Phase 12b failed-control guard check failed: {_guard_err}", flush=True)

            return _eli_phase12b_prev_control_synth(
                self,
                user_input,
                evidence_text,
                action,
                reasoning_mode,
                *args,
                **kwargs,
            )

        CognitiveEngine._synthesize_control_with_mode_framing = _eli_phase12b_control_synth_guard

        print("[ENGINE] Phase 12b failed-control no-GGUF guard installed", flush=True)

except Exception as _eli_phase12b_failed_control_guard_err:
    print(f"[ENGINE] Phase 12b failed-control guard failed: {_eli_phase12b_failed_control_guard_err}", flush=True)
'''

if "_ELI_PHASE12B_FAILED_CONTROL_GUARD_INSTALLED" not in src:
    (OUT / "eli__kernel__engine.py.before").write_text(src, encoding="utf-8")
    engine.write_text(src.rstrip() + "\n" + block + "\n", encoding="utf-8")
    changed = ["eli/kernel/engine.py"]
else:
    changed = []

probe = ROOT / "ops/probes/phase12b_failed_control_guard_probe.py"
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

def forbidden_get_chat_response(*args, **kwargs):
    raise RuntimeError("GGUF synthesis was incorrectly invoked")

dummy._get_chat_response = forbidden_get_chat_response

failed_evidence = """
[AGENT:system] execute result: {'ok': False, 'action': 'ANALYZE_PDF', 'error': '/tmp/nonexistent_a.pdf',
'content': '/tmp/nonexistent_a.pdf', 'response': '/tmp/nonexistent_a.pdf'}
FileNotFoundError: /tmp/nonexistent_a.pdf
"""

out = dummy._synthesize_control_with_mode_framing(
    "read and summarise /tmp/nonexistent_a.pdf",
    failed_evidence,
    "ANALYZE_PDF",
    "constitutional_ai",
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
    "# Phase 12b Failed Control Synthesis Guard\n\n"
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
