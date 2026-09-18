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

A third pass finished the sweep of the ~186 routable actions: 21 more,
including TRANSCRIBE and OCR_IMAGE (raw transcribed/recognized text, same
danger class as READ_FILE). Two were deliberately left OUT after reading
their handlers -- FIX_FILE (its content is a machine-readable JSON event
blob, not prose; verbatim would show raw JSON in chat) and RUN_TESTS (its
own code comment says the design intent is "summarise it in chat", not a
raw dump).

A fourth pass re-verified the actions initially waved through as
"genuinely creative" rather than individually read -- the user's standing
rule throughout this audit was to verify the handler, not assume from the
action name. Half of them turned out to be misclassified: ANALYZE_IMAGE,
ANALYZE_PDF, and ANALYZE_PDF_FOLDER all run their own dedicated,
evidence-constrained internal model call and the chat-facing content is
already the complete final answer (or a deterministic "saved to X"
confirmation -- the raw analysis goes to a file, not this string);
SCREEN_READ_ANALYZE just wraps ANALYZE_IMAGE; DATA_FABRICATOR delegates to
CREATE_DOCUMENT or returns its own confirmation; GENERATE_PROJECT's
success path embeds real generated code that must not be paraphrased, and
its fallback already calls chat() and returns finished text either way;
SEQUENCE and MULTI_COMMAND never call a model themselves, they mechanically
join already-finished sub-step results. 8 more added. Genuinely still
excluded after this closer look: CHAT (the model call itself), CODE_SOLVE
and GENERATE_SCRIPT (both real code-generation actions whose primary
success path returns a JSON event blob, same as FIX_FILE), SHOW_DIFF
(routes straight to chat()), WEB_SEARCH (its own code comment: the results
are evidence for the model to answer from, not the answer), EXECUTE_GOAL
(no executor handler at all to verify against), and NOOP (no single
handler in the dispatch ladder).

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

# Third pass, same day: the remaining confirmation/report/raw-content actions
# from the full ~186 routable-action sweep.
AUDITED_2026_09_18_PASS3 = {
    "CODE_CHANGES", "TRANSCRIBE", "DICTATE", "SMART_HOME", "PERSONA_REFRESH",
    "PROACTIVE_START", "PROACTIVE_STOP", "HELP", "LIST_CAPABILITIES",
    "MEMORY_RECALL", "TEST_REVIEW", "OCR_IMAGE", "SUMMARIZE_FILE",
    "CONVERT_DOCUMENT", "ANALYZE_CSV", "GENERATE_TESTS", "CREATE_DOCUMENT",
    "GENERATE_DOCUMENT", "DOC_GENERATE", "DESIGN_VOICE", "CREATE_VOICE",
}

# Fourth pass, same day: re-verified "genuinely creative" exclusions by
# actually reading each handler; over half turned out to be misclassified.
AUDITED_2026_09_18_PASS4 = {
    "ANALYZE_IMAGE", "ANALYZE_PDF", "ANALYZE_PDF_FOLDER", "SCREEN_READ_ANALYZE",
    "DATA_FABRICATOR", "GENERATE_PROJECT", "SEQUENCE", "MULTI_COMMAND",
}

# Deliberately NOT in the set, verified by reading the handler: their content
# is either not meant for verbatim display (FIX_FILE/CODE_SOLVE/GENERATE_SCRIPT:
# JSON event blob on the primary success path; RUN_TESTS: handler's own comment
# states the design intent is LLM narration) or the action never reaches a
# verifiable single handler (CHAT is the model call itself; SHOW_DIFF routes
# straight to chat(); WEB_SEARCH's own comment says its results are evidence
# for the model, not the answer; EXECUTE_GOAL has no executor handler at all;
# NOOP has no single handler in the dispatch ladder).
AUDITED_2026_09_18_EXCLUDED = {
    "FIX_FILE", "RUN_TESTS", "CODE_SOLVE", "GENERATE_SCRIPT", "CHAT",
    "SHOW_DIFF", "WEB_SEARCH", "EXECUTE_GOAL", "NOOP",
}

# The highest-risk entries: raw content/tool output that must never be
# paraphrased by an LLM synthesis pass, or the "answer" stops being
# guaranteed to match what is actually on disk / what a command, tool, or
# transcription/OCR engine actually produced.
HIGH_RISK_RAW_CONTENT_ACTIONS = {
    "READ_FILE", "SHELL_EXEC", "MCP_CALL", "TRANSCRIBE", "OCR_IMAGE",
}


def test_all_audited_actions_are_in_the_set():
    actions = _deterministic_direct_payload_actions()
    missing = AUDITED_2026_09_18 - actions
    assert not missing, f"regression: dropped from the verbatim set: {sorted(missing)}"


def test_all_pass2_audited_actions_are_in_the_set():
    actions = _deterministic_direct_payload_actions()
    missing = AUDITED_2026_09_18_PASS2 - actions
    assert not missing, f"regression: dropped from the verbatim set: {sorted(missing)}"


def test_all_pass3_audited_actions_are_in_the_set():
    actions = _deterministic_direct_payload_actions()
    missing = AUDITED_2026_09_18_PASS3 - actions
    assert not missing, f"regression: dropped from the verbatim set: {sorted(missing)}"


def test_all_pass4_audited_actions_are_in_the_set():
    actions = _deterministic_direct_payload_actions()
    missing = AUDITED_2026_09_18_PASS4 - actions
    assert not missing, f"regression: dropped from the verbatim set: {sorted(missing)}"


def test_excluded_actions_stay_out_of_the_set():
    """FIX_FILE and RUN_TESTS were deliberately left out -- adding them would
    put raw JSON (FIX_FILE) or a wall of pytest text designed to be narrated
    (RUN_TESTS) directly in front of the user in quick mode."""
    actions = _deterministic_direct_payload_actions()
    present = AUDITED_2026_09_18_EXCLUDED & actions
    assert not present, (
        f"action(s) added back without re-checking why they were excluded: "
        f"{sorted(present)}"
    )


def test_high_risk_raw_content_actions_are_covered():
    actions = _deterministic_direct_payload_actions()
    missing = HIGH_RISK_RAW_CONTENT_ACTIONS - actions
    assert not missing, f"raw-content action(s) at risk of LLM paraphrase: {sorted(missing)}"


def test_the_set_did_not_shrink_below_its_pre_audit_size():
    """Loose regression guard -- the set had ~91 entries before this audit
    added 27, then 41, then 21, then 8 more across four passes the same
    day. A large drop signals something got deleted, not just reorganized."""
    assert len(_deterministic_direct_payload_actions()) >= 91 + 27 + 41 + 21 + 8


def test_every_routable_action_is_covered_or_documented_excluded():
    """Full-coverage guard: every action in capability_manifest.json marked
    routable must be either in the verbatim set (this file or
    _verbatim_always_actions in engine.py) or in AUDITED_2026_09_18_EXCLUDED
    with a reason. Catches a newly-added routable action silently landing in
    neither -- the exact gap this whole audit exists to close."""
    import json

    manifest_path = ENGINE_PY.parents[2] / "capability_manifest.json"
    if not manifest_path.exists():
        import pytest
        pytest.skip("capability_manifest.json not present in this environment")

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    caps = data.get("capabilities", data)
    items = caps.items() if isinstance(caps, dict) else (
        (c.get("action") or c.get("name"), c) for c in caps
    )
    routable = {k for k, v in items if isinstance(v, dict) and v.get("routable")}

    text = ENGINE_PY.read_text(encoding="utf-8")
    va_start = text.index("_verbatim_always_actions = {")
    va_end = text.index("\n                        }", va_start)
    verbatim_always = set(re.findall(r'"([A-Z_]+)"', text[va_start:va_end]))

    covered = _deterministic_direct_payload_actions() | verbatim_always
    uncovered = routable - covered - AUDITED_2026_09_18_EXCLUDED
    assert not uncovered, (
        f"routable action(s) neither in the verbatim set nor in "
        f"AUDITED_2026_09_18_EXCLUDED with a documented reason: "
        f"{sorted(uncovered)}"
    )
