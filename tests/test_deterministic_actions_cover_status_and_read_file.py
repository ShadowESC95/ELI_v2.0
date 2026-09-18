"""_deterministic_direct_payload_actions (engine.py) is the set of actions
that return their executor's own content verbatim in quick mode instead of
being re-narrated by an LLM. Audited 2026-09-18: ~26 actions whose executor
handlers already build a complete, well-formed content/response string
(confirmed by reading each handler directly) were missing from it entirely --
including READ_FILE, where letting the LLM "synthesize" a file read means the
answer is never guaranteed to match what's actually on disk, which is the
exact class of bug this project exists to not have.

A second pass the same day covered the remaining confirmation/status/report
actions (plugin/MCP/voice/wake-word/gaze/pomodoro management, GET_WEATHER,
MEMORY_STORE, SCHEDULE_TASK, etc.) -- 41 more actions, each individually
verified against its handler's actual return shape, led by MCP_CALL (same
raw-tool-output risk class as READ_FILE/SHELL_EXEC).

No test previously verified this set's membership at all, so it could (and
did) silently miss actions as new ones were added. This is a regression
guard, not exhaustive: it checks the specific actions audited and fixed
today, not every one of the ~186 routable actions.
"""
import re
from pathlib import Path

ENGINE_PY = Path(__file__).resolve().parents[1] / "eli" / "kernel" / "engine.py"


def _deterministic_direct_payload_actions() -> set[str]:
    text = ENGINE_PY.read_text(encoding="utf-8")
    start = text.index("_deterministic_direct_payload_actions = {")
    end = text.index("\n                        }", start)
    block = text[start:end]
    return set(re.findall(r'"([A-Z_]+)"', block))


AUDITED_2026_09_18 = {
    "READ_FILE", "HARDWARE_PROFILE", "AWARENESS_STATUS", "FRONTIER_STATUS",
    "BACKGROUND_JOBS", "CHECK_JOB", "ORCHESTRATION_STATUS", "LORA_STATUS",
    "PROACTIVE_STATUS", "PERSONA_LOCK_STATUS", "POMODORO_STATUS", "HABIT_STATUS",
    "GAZE_STATUS", "TIMESTAMP_DIAG", "ELI_IDENTITY_AUDIT", "FILE_AUDIT",
    "CODEBASE_GRAPH", "AUTOPILOT_DEBUG", "LIST_EVENTS", "SEARCH_NOTES",
    "MCP_STATUS", "MCP_TOOLS", "MCP_LIST", "STT_DIAGNOSTICS",
    "NAME_SOURCE_AUDIT", "ROUTING_FAULT_EXPLAIN", "SHELL_EXEC",
}

# Second pass, same day: confirmation/status/report actions whose handlers
# were individually verified after the first batch shipped.
AUDITED_2026_09_18_PASS2 = {
    "ADD_EVENT", "PLUGIN_STATUS", "MEMORY_STORE", "GET_WEATHER",
    "PERSONA_LOCK_SET", "PERSONA_LOCK_CLEAR", "SET_TONE", "CLEAR_TONE",
    "SET_USER_NAME", "SET_COMMUNICATION_STYLE", "SET_VOICE",
    "POMODORO_START", "POMODORO_STOP", "WAKE_SET", "WAKE_ENROLL",
    "WAKE_TRAIN", "TRAIN_VOICE", "GAZE_CALIBRATE", "GAZE_CLICK",
    "GAZE_ENABLE", "GAZE_DISABLE", "MCP_ADD", "MCP_REMOVE", "MCP_DOCTOR",
    "MCP_CALL", "PLUGIN_LIST", "PLUGIN_SEARCH", "PLUGIN_INSTALL",
    "PLUGIN_ENABLE", "PLUGIN_DISABLE", "PLUGIN_UNINSTALL", "LIST_VOICES",
    "DOWNLOAD_VOICE", "SCHEDULE_TASK", "SKIP_YOUTUBE_AD", "SCREEN_LOCATE",
    "LORA_TRAIN", "LISTEN_FOR_COMMAND", "AMBIENT_VISION",
    "CANCEL_PENDING_REMEDIATION", "CONFIRM_PENDING_REMEDIATION",
    "CLEAR_CHAT_HISTORY", "REFRESH_USER_INFO", "MESSAGE_TIME_QUERY",
}

# The highest-risk entries: raw content/tool output that must never be
# paraphrased by an LLM synthesis pass, or the "answer" stops being
# guaranteed to match what is actually on disk / what a command or tool
# actually printed.
HIGH_RISK_RAW_CONTENT_ACTIONS = {"READ_FILE", "SHELL_EXEC", "MCP_CALL"}


def test_all_audited_actions_are_in_the_set():
    actions = _deterministic_direct_payload_actions()
    missing = AUDITED_2026_09_18 - actions
    assert not missing, f"regression: dropped from the verbatim set: {sorted(missing)}"


def test_all_pass2_audited_actions_are_in_the_set():
    actions = _deterministic_direct_payload_actions()
    missing = AUDITED_2026_09_18_PASS2 - actions
    assert not missing, f"regression: dropped from the verbatim set: {sorted(missing)}"


def test_high_risk_raw_content_actions_are_covered():
    actions = _deterministic_direct_payload_actions()
    missing = HIGH_RISK_RAW_CONTENT_ACTIONS - actions
    assert not missing, f"raw-content action(s) at risk of LLM paraphrase: {sorted(missing)}"


def test_the_set_did_not_shrink_below_its_pre_audit_size():
    """Loose regression guard -- the set had ~91 entries before this audit
    added 27 more, then 41 more in a second pass the same day. A large drop
    signals something got deleted, not just reorganized."""
    assert len(_deterministic_direct_payload_actions()) >= 91 + 27 + 41
