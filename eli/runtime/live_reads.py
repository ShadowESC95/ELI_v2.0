"""What ELI can read about the present in a moment, read for the turn that is about it.

Facts that were one tool call away were denied ("I don't have a live feed of your screen") until the
person called the tool themselves. Each read here is cheap and changes nothing, and runs only when the
message is about what it reads, so the rest of the time the prompt is as it was.
"""
from __future__ import annotations

import re
from typing import Any, List

from eli.utils.log import get_logger

log = get_logger(__name__)

_ABOUT_MEDIA = re.compile(
    r"\b(?:watch\w*|playing|listening|song|track|album|film|movie|series|episode|show|music|spotify|youtube|paused|feed)\b",
    re.I)
_ABOUT_WORK = re.compile(
    r"\b(?:pdfs?|jobs?|folders?|files?|documents?|papers?|background|progress|eta|remaining|finish\w*|done|started|running|"
    r"working\s+on|queue\w*|them)\b", re.I)


_ASKS_WHAT_WAS_FOUND = re.compile(r"\b(?:find|found|say|says|said|conclu\w*|results?|findings?|summary|report)\b", re.I)
_NAMES_OWN_WORK = re.compile(
    r"\b(?:the|my|your|those|these|that|this|them)\s+(?:\w+\s+)?(?:pdfs?|jobs?|papers?|folders?|documents?|analysis|scan|files?)\b",
    re.I)


def about_own_work(text: Any) -> bool:
    """A message about work ELI has on record: the answer is in the job record, not out in the world."""
    if not _NAMES_OWN_WORK.search(str(text or "")):
        return False
    from eli.runtime.background_tasks import work_block
    return bool(work_block())


def _media_line() -> str:
    from eli.execution.executor_enhanced import now_playing
    return str((now_playing() or {}).get("content") or "").strip()


def measured_health(evidence: Any) -> str:
    """What the status report's own check found. It said "All core systems nominal" whatever that was."""
    concerns = ((evidence or {}).get("runtime_health") or {}).get("concerns") if isinstance(evidence, dict) else None
    if not concerns:
        return ""
    if len(concerns) == 1 and str(concerns[0]).startswith("none"):
        return "The running settings are within what the hardware profile recommends."
    return "Concerns: " + "; ".join(str(c) for c in concerns) + "."


def live_facts(text: Any) -> str:
    """The reads this message is about, as lines for the prompt; empty when it is about none."""
    said = str(text or "")
    out: List[str] = []
    from eli.cognition.supplied_in_message import worked_out
    sums = worked_out(said)
    if sums:
        out.append(f"Worked out from the numbers in this message, so state these as they are: {sums}.")
    if _ABOUT_MEDIA.search(said):
        try:
            line = _media_line()
            if line:
                out.append(f"Playing on this machine right now, read from its media session this moment: {line}")
        except Exception as e:
            log.debug("media read skipped", exc_info=True)
            out.append(f"The media session on this machine could not be read just now ({e}).")
    if _ABOUT_WORK.search(said):
        try:
            from eli.runtime.background_tasks import latest_report, work_block
            block = work_block()
            if block:
                out.append(block)
            report = latest_report() if _ASKS_WHAT_WAS_FOUND.search(said) else ""
            if report:
                out.append(f"What the last finished job reported:\n{report}")
        except Exception as e:
            log.debug("job read skipped", exc_info=True)
            out.append(f"The job record could not be read just now ({e}).")
    return "\n\n".join(out)
