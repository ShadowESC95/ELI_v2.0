#!/usr/bin/env python3
"""capabilities_doc.py — regenerate blueprints/capabilities_and_actions.md.

Companion to capability_updater.py: that refreshes capability_manifest.json; this
renders the human-readable reference table (every routable action + a
representative activation phrase + Core/Plugin source) from that manifest plus a
curated description/phrase map below.

Driven off the manifest (no heavy executor import). Any routable action that is
NOT yet in the curated map is still emitted (under "New / undocumented") with a
"(needs activation phrase)" marker and reported in `needs_phrase`, so the doc can
never silently drift or go stale as actions are added — it just flags what a human
should write a phrase for. Wire-in: capability_updater calls
generate_capabilities_doc() after writing the manifest.

Paths are derived relative to this file (repo-root portable; no hardcoded home).
"""
from __future__ import annotations

import datetime
import json
import textwrap
from collections import OrderedDict
from pathlib import Path
from typing import Dict, List, Tuple

ELI_ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ELI_ROOT / "capability_manifest.json"
OUT = ELI_ROOT / "blueprints" / "capabilities_and_actions.md"

# action -> (category, description, [phrases]). Edit here when adding an action.
_C: "OrderedDict[str, Tuple[str, str, List[str]]]" = OrderedDict()


def _add(cat: str, action: str, desc: str, *phrases: str) -> None:
    _C[action] = (cat, desc, list(phrases))


# ── Conversation & persona ──────────────────────────────────────────────────
_add("Conversation & persona", "CHAT", "Open conversation / fallback; persona-bound reply", "anything not matching a command", "“how are you”", "“tell me a story”")
_add("Conversation & persona", "EXPLAIN_LAST_RESPONSE", "Explain why ELI gave its previous answer", "“why did you say that”", "“explain your last response”")
_add("Conversation & persona", "CLEAR_CHAT_HISTORY", "Clear the current chat history", "“clear chat history”", "“start a new chat”")
_add("Conversation & persona", "PERSONA_LOCK_SET", "Pin a persona/role for the session", "“lock your persona to X”")
_add("Conversation & persona", "PERSONA_LOCK_CLEAR", "Release a pinned persona", "“clear persona lock”")
_add("Conversation & persona", "PERSONA_LOCK_STATUS", "Show the current persona lock", "“what persona are you locked to”")
_add("Conversation & persona", "HELP", "List what ELI can do", "“help”", "“what commands do you have”")
_add("Conversation & persona", "LIST_CAPABILITIES", "Enumerate ELI's capabilities", "“what can you do”", "“list your capabilities”")

# ── App & window control ────────────────────────────────────────────────────
_add("App & window control", "OPEN_APP", "Launch an application (installs it if missing)", "“open spotify”", "“launch firefox”")
_add("App & window control", "CLOSE_APP", "Close an application", "“close spotify”", "“quit chrome”")
_add("App & window control", "FOCUS_APP", "Bring an app's window to the front", "“focus firefox”", "“switch to the browser”")
_add("App & window control", "OPEN_BROWSER", "Open the default web browser", "“open the browser”")
_add("App & window control", "OPEN_URL", "Open a URL in the browser", "“open github.com”", "“go to youtube.com”")
_add("App & window control", "OPEN_IDE", "Open the code IDE", "“open the IDE”")
_add("App & window control", "OPEN_FILE_SYSTEM", "Open the file manager", "“open files”", "“open the file manager”")
_add("App & window control", "OPEN_SYSTEM_SETTINGS", "Open OS settings", "“open system settings”")
_add("App & window control", "OPEN_AUDIO_SETTINGS", "Open sound settings", "“open audio settings”")
_add("App & window control", "OPEN_POWER_SETTINGS", "Open power settings", "“open power settings”")
_add("App & window control", "OPEN_NETWORK_BROWSER", "Open network settings", "“open network settings”")
_add("App & window control", "OPEN_COMMUNICATION_HUB", "Open the comms hub (mail/chat apps)", "“open communication hub”")
_add("App & window control", "OPEN_MEDIA_HUB", "Open the media hub", "“open media hub”")
_add("App & window control", "TILE_WINDOWS", "Tile windows in a grid", "“tile windows”", "“2x2 grid”", "“4x2”")
_add("App & window control", "MAXIMISE_WINDOW", "Maximise the focused window", "“maximise the window”")
_add("App & window control", "MINIMISE_ALL", "Minimise all / show desktop", "“minimise everything”", "“show desktop”")
_add("App & window control", "NEXT_WINDOW", "Switch to the next window", "“next window”")
_add("App & window control", "PREVIOUS_WINDOW", "Switch to the previous window", "“previous window”")
_add("App & window control", "RESTORE_WINDOWS", "Restore minimised windows", "“restore windows”")
_add("App & window control", "SWITCH_WORKSPACE", "Switch virtual desktop/workspace", "“switch to workspace 2”")
_add("App & window control", "SMART_HOME", "Control smart-home devices", "“turn off the lights”")
_add("App & window control", "CONFIRM_PENDING_REMEDIATION", "Approve a pending fix/install offer", "“yes” (to an “install X?” offer)")
_add("App & window control", "CANCEL_PENDING_REMEDIATION", "Decline a pending fix/install offer", "“no” (to an “install X?” offer)")

# ── Input control ───────────────────────────────────────────────────────────
_add("Input control", "VOLUME", "Adjust/mute system volume", "“volume up”", "“mute”", "“set volume to 30”")
_add("Input control", "KEYBOARD", "Send keystrokes / type text", "“press enter”", "“type hello world”")
_add("Input control", "MOUSE_CONTROL", "Move/click the mouse", "“left click”", "“move the mouse up”")

# ── Media ───────────────────────────────────────────────────────────────────
_add("Media", "PLAY_MEDIA", "Play a track on the named platform", "“play Juicy by Notorious B.I.G. on Spotify”", "“play lo-fi on YouTube”")
_add("Media", "PAUSE_MEDIA", "Pause playback", "“pause”", "“pause the music”")
_add("Media", "STOP_MEDIA", "Stop playback", "“stop the music”")
_add("Media", "NEXT_MEDIA", "Next track", "“next song”", "“skip”")
_add("Media", "PREVIOUS_MEDIA", "Previous track", "“previous track”", "“go back a song”")
_add("Media", "REPEAT_MEDIA", "Repeat current track", "“repeat this song”")
_add("Media", "SHUFFLE_MEDIA", "Toggle shuffle", "“shuffle”")
_add("Media", "MEDIA_CONTROL", "Generic transport control (MPRIS)", "“play/pause”")
_add("Media", "SKIP_YOUTUBE_AD", "Skip a YouTube ad when skippable", "“skip the ad”")

# ── Vision & screen ─────────────────────────────────────────────────────────
_add("Vision & screen", "SCREEN_READ_ANALYZE", "Screenshot → vision model + OCR; answers questions about on-screen content", "“what's on my screen”", "“can you see this”", "“what season is on the screen”")
_add("Vision & screen", "SCREEN_LOCATE", "Find on-screen UI text/element", "“find the submit button on screen”")
_add("Vision & screen", "SCREENSHOT", "Capture a screenshot", "“take a screenshot”")
_add("Vision & screen", "OCR_IMAGE", "Extract text from an image file", "“ocr photo.png”", "“read the text in image.jpg”")
_add("Vision & screen", "ANALYZE_IMAGE", "Describe/analyse an image file (VLM)", "“describe cat.jpg”", "“analyse this image”")
_add("Vision & screen", "ANALYZE_PDF", "Read/summarise a PDF", "“summarise report.pdf”", "“analyse this pdf”")
_add("Vision & screen", "ANALYZE_PDF_FOLDER", "Analyse all PDFs in a folder", "“analyse the pdfs in that directory”")
_add("Vision & screen", "ANALYZE_CSV", "Analyse a CSV/spreadsheet", "“analyse data.csv”")
_add("Vision & screen", "AMBIENT_VISION", "Toggle continuous screen-watching", "“watch my screen”", "“stop watching”")

# ── Gaze (eye-tracking) ─────────────────────────────────────────────────────
_add("Gaze (eye-tracking)", "GAZE_ENABLE", "Enable webcam gaze control", "“enable gaze control”")
_add("Gaze (eye-tracking)", "GAZE_DISABLE", "Disable gaze control", "“disable gaze control”")
_add("Gaze (eye-tracking)", "GAZE_CALIBRATE", "Calibrate gaze tracking", "“calibrate gaze”")
_add("Gaze (eye-tracking)", "GAZE_STATUS", "Show gaze tracker status", "“gaze status”")
_add("Gaze (eye-tracking)", "GAZE_CLICK", "Click where the eyes rest", "“open” / “left click” / “hit enter” (while gaze is on)")

# ── Voice ───────────────────────────────────────────────────────────────────
_add("Voice", "DICTATE", "Start/stop dictation into the active field", "“start dictation”", "“stop dictating”")
_add("Voice", "TRANSCRIBE", "Transcribe an audio file", "“transcribe audio.wav”")
_add("Voice", "SPEAK", "Speak text aloud (TTS)", "“say good morning”")
_add("Voice", "LISTEN_FOR_COMMAND", "Start listening for a voice command", "“listen” / the wake word “computer”")
_add("Voice", "VOICE_DIAGNOSTICS", "Run voice/STT diagnostics", "“run voice diagnostics”", "“stt diagnostics”")

# ── Files & notes ───────────────────────────────────────────────────────────
_add("Files & notes", "CREATE_FILE", "Create a file", "“create a file notes.txt”")
_add("Files & notes", "CREATE_FOLDER", "Create a folder", "“make a folder called projects”")
_add("Files & notes", "READ_FILE", "Read a file's contents", "“read notes.txt”")
_add("Files & notes", "LIST_DIR", "List a directory", "“list the files in ~/Documents”")
_add("Files & notes", "FILE_AUDIT", "Audit files for issues", "“audit my files”")
_add("Files & notes", "SUMMARIZE_FILE", "Summarise a document/file", "“summarise report.docx”")
_add("Files & notes", "CONVERT_DOCUMENT", "Convert between document formats", "“convert report.md to pdf”")
_add("Files & notes", "WRITE_NOTE", "Write a quick note", "“write a note saying buy milk”")
_add("Files & notes", "NEW_NOTE", "Create a new note", "“new note”")
_add("Files & notes", "LIST_NOTES", "List saved notes", "“list my notes”")
_add("Files & notes", "SEARCH_NOTES", "Search notes", "“search notes for budget”")
_add("Files & notes", "GET_CLIPBOARD", "Read the clipboard", "“what's in my clipboard”")
_add("Files & notes", "SET_CLIPBOARD", "Write to the clipboard", "“copy this to the clipboard”")

# ── Generation (docs/code) ──────────────────────────────────────────────────
_add("Generation (docs/code)", "GENERATE_DOCUMENT", "Grounded document via the multi-stage pipeline (evidence → plan/outline → sections → review→revise)", "“generate a document about X”", "“write a report on Y”")
_add("Generation (docs/code)", "CREATE_DOCUMENT", "Multi-stage grounded document (plan→draft→review); single-pass fallback", "“create a document on X”")
_add("Generation (docs/code)", "DATA_FABRICATOR", "Generate synthetic/test data", "“fabricate a test dataset for X”")
_add("Generation (docs/code)", "GENERATE_SCRIPT", "Generate a runnable script via the coding agent", "“write a bash script to monitor the GPU”")
_add("Generation (docs/code)", "GENERATE_PROJECT", "Scaffold a multi-file project", "“generate a project that does X”")
_add("Generation (docs/code)", "CODE_SOLVE", "Solve a coding task (plan→DAG→verify→repair)", "“solve this: …”", "“implement function X”")
_add("Generation (docs/code)", "FIX_FILE", "Find and fix bugs in a file", "“fix the bugs in foo.py”")
_add("Generation (docs/code)", "EXAMINE_CODE", "Tiered error scan of named files/codebase", "“examine eli/memory/memory.py for errors”", "“review the codebase for bugs”")
_add("Generation (docs/code)", "CONFIRM_CODE_FIX", "Apply the offered code fixes (pending-confirm)", "“yes, fix it”", "“fix the logic ones too”")
_add("Generation (docs/code)", "CANCEL_CODE_FIX", "Decline the offered code fixes", "“no, leave it”")
_add("Generation (docs/code)", "SHOW_DIFF", "Show a code diff", "“show the diff”")
_add("Generation (docs/code)", "OPEN_IN_IDE", "Open a generated artifact in the IDE", "(post-action; auto after generate)")

# ── System status & info ────────────────────────────────────────────────────
_add("System status & info", "CPU_USAGE", "Current CPU usage", "“cpu usage”")
_add("System status & info", "RAM_USAGE", "Current memory usage", "“how much ram is free”")
_add("System status & info", "GPU_STATUS", "GPU/VRAM status", "“gpu status”")
_add("System status & info", "SYSTEM_STATS", "Combined system stats", "“system stats”")
_add("System status & info", "HARDWARE_PROFILE", "Detected hardware profile", "“show hardware profile”")
_add("System status & info", "GET_STATUS", "General status", "“status”")
_add("System status & info", "TIME", "Current time", "“what time is it”")
_add("System status & info", "GET_TIME", "Current time (alt)", "“tell me the time”")
_add("System status & info", "DATE", "Current date", "“what's the date”")
_add("System status & info", "GET_DATE", "Current date (alt)", "“what day is it”")
_add("System status & info", "GET_WEATHER", "Weather for a place", "“weather in Wexford”")
_add("System status & info", "NEWS_FETCH", "Synthesised news digest", "“what's the news”", "“catch me up”")
_add("System status & info", "WEB_SEARCH", "Web search (Net-gated)", "“search the web for X”")
_add("System status & info", "MESSAGE_TIME_QUERY", "Time-of-a-message query", "“when did I say that”")
_add("System status & info", "CHECK_CHRONAL_ALIGNMENT", "Playful date/time sanity check", "“check chronal alignment”")

# ── Grounded introspection ──────────────────────────────────────────────────
_add("Grounded introspection", "RUNTIME_STATUS", "Live runtime: model, ctx, GPU layers, batch", "“what are you running on”", "“runtime status — everything”")
_add("Grounded introspection", "RUNTIME_AUDIT", "Full runtime audit (what's broken/missing)", "“run a full runtime audit”")
_add("Grounded introspection", "IMPORT_AUDIT", "Which imports are failing/missing", "“what imports are failing”")
_add("Grounded introspection", "RESOLVE_RUNTIME_PATHS", "Resolved paths of critical files", "“show the resolved runtime paths”")
_add("Grounded introspection", "GUI_RUNTIME_AUDIT", "Audit GUI wiring with file-read proof", "“audit your gui file”", "“scan the gui runtime wiring and prove every hook”")
_add("Grounded introspection", "DIAGNOSE_WRAPPERS", "Show the executor middleware/wrapper chain", "“show the executor wrapper chain”")
_add("Grounded introspection", "COGNITION_STATUS", "Cognition runtime status", "“cognition status”")
_add("Grounded introspection", "EXPLAIN_COGNITION_RUNTIME", "Explain the cognition runtime verbatim", "“explain your cognition runtime”")
_add("Grounded introspection", "MEMORY_STATUS", "Memory subsystem status / counts", "“how does your memory work”")
_add("Grounded introspection", "MEMORY_STATS", "Memory statistics", "“memory stats”")
_add("Grounded introspection", "EXPLAIN_MEMORY_RUNTIME", "Explain the memory runtime verbatim (4 DBs)", "“explain exactly how your memory works internally”")
_add("Grounded introspection", "AWARENESS_STATUS", "What ELI is currently aware of", "“what are you aware of”")
_add("Grounded introspection", "FRONTIER_STATUS", "Full system wiring matrix", "“run a full system wiring matrix”")
_add("Grounded introspection", "ELI_IDENTITY_AUDIT", "Audit ELI's identity provenance", "“audit your identity”")
_add("Grounded introspection", "CODE_CHANGES", "Recent code changes", "“what code has changed”")
_add("Grounded introspection", "NAME_SOURCE_AUDIT", "Where ELI's knowledge of your name comes from", "“how do you know my name”")
_add("Grounded introspection", "REASONING_MODE_STATUS", "Current reasoning mode", "“what reasoning mode are you in”")
_add("Grounded introspection", "EXPLAIN_ALL_REASONING_MODES", "Describe all 5 reasoning modes", "“explain all your reasoning modes”")
_add("Grounded introspection", "SELF_REPORT", "What ELI has recently done/worked on", "“what have you been working on”")

# ── Memory & profile ────────────────────────────────────────────────────────
_add("Memory & profile", "MEMORY_STORE", "Store a durable fact", "“remember that my sister's name is Anna”")
_add("Memory & profile", "MEMORY_RECALL", "Recall stored facts", "“what do you remember about my car”")
_add("Memory & profile", "PERSONAL_MEMORY_SUMMARY", "Summary of what ELI knows about you", "“what do you know about me”")
_add("Memory & profile", "PERSONAL_MEMORY_DEEP_EXPLAIN", "Deep, sourced profile explanation", "“explain everything you know about me and where it's stored”")
_add("Memory & profile", "USER_IDENTITY_SUMMARY", "Who the user is", "“who am I”")
_add("Memory & profile", "REFRESH_USER_INFO", "Re-extract the user profile", "“refresh my user info”")
_add("Memory & profile", "SET_USER_NAME", "Set/correct the user's name", "“my name is Alex”", "“call me Alex”")

# ── Self-maintenance ────────────────────────────────────────────────────────
_add("Self-maintenance", "SELF_ANALYZE", "Analyse own failures/metrics", "“analyse your failures”")
_add("Self-maintenance", "SELF_IMPROVE", "Run a self-improvement patch cycle", "“improve yourself”")
_add("Self-maintenance", "SELF_PATCH", "Apply a self-improvement patch", "“patch yourself”")
_add("Self-maintenance", "SELF_IMPROVEMENT_LOG", "Show the self-improvement log", "“show your self-improvement log”")
_add("Self-maintenance", "SELF_UPGRADE", "git pull → deps → rebuild indexes", "“upgrade yourself”")
_add("Self-maintenance", "SELF_UPDATE", "Self-update (control-contract)", "“update yourself”")
_add("Self-maintenance", "SELF_TEST", "Run internal self-tests", "“run a self test”")
_add("Self-maintenance", "RUN_TESTS", "Run the pytest suite and summarise the results document", "“run the test suite”", "“generate a test report”")
_add("Self-maintenance", "GENERATE_TESTS", "ELI writes + sandbox-verifies behavioural tests for its own functions (Phase 4)", "“generate tests for your code”", "“grow your test coverage”")

# ── Tasks, time & planning ──────────────────────────────────────────────────
_add("Tasks, time & planning", "SCHEDULE_TASK", "Schedule overnight/timed work (code/research/etc.)", "“research X overnight”", "“build Y at 2am”")
_add("Tasks, time & planning", "SET_ALARM", "Set an alarm", "“set an alarm for 7am”")
_add("Tasks, time & planning", "SET_TIMER", "Set a timer", "“set a timer for 10 minutes”")
_add("Tasks, time & planning", "ADD_EVENT", "Add a calendar event", "“add an event tomorrow at 3pm”")
_add("Tasks, time & planning", "LIST_EVENTS", "List events", "“list my events”")
_add("Tasks, time & planning", "POMODORO_START", "Start a pomodoro", "“start a pomodoro”")
_add("Tasks, time & planning", "POMODORO_STOP", "Stop the pomodoro", "“stop the pomodoro”")
_add("Tasks, time & planning", "POMODORO_STATUS", "Pomodoro status", "“pomodoro status”")
_add("Tasks, time & planning", "BACKGROUND_JOBS", "List background/scheduled jobs", "“show background jobs”")
_add("Tasks, time & planning", "CHECK_JOB", "Check a specific job", "“check job 5”")
_add("Tasks, time & planning", "HABIT_STATUS", "Show learned habits", "“show my habits”")
_add("Tasks, time & planning", "CONFIRM_HABIT", "Approve a proposed habit", "“yes” (to a habit offer)")
_add("Tasks, time & planning", "DECLINE_HABIT", "Decline a proposed habit", "“no” (to a habit offer)")
_add("Tasks, time & planning", "EXECUTE_GOAL", "Execute a stored goal", "“execute goal X”")

# ── Proactive ───────────────────────────────────────────────────────────────
_add("Proactive", "PROACTIVE_START", "Start the proactive daemon", "“start proactive mode”")
_add("Proactive", "PROACTIVE_STOP", "Stop the proactive daemon", "“stop proactive mode”")
_add("Proactive", "PROACTIVE_STATUS", "Proactive daemon status", "“proactive status”")
_add("Proactive", "MORNING_REPORT", "Daily briefing (news/weather/agenda)", "“morning report”", "“give me my briefing”")

# ── Plugins ─────────────────────────────────────────────────────────────────
_add("Plugins", "PLUGIN_LIST", "List installed plugins", "“list plugins”")
_add("Plugins", "PLUGIN_SEARCH", "Search for plugins", "“search plugins for weather”")
_add("Plugins", "PLUGIN_INSTALL", "Install a plugin", "“install the X plugin”")
_add("Plugins", "PLUGIN_UNINSTALL", "Uninstall a plugin", "“uninstall the X plugin”")
_add("Plugins", "PLUGIN_ENABLE", "Enable a plugin", "“enable the X plugin”")
_add("Plugins", "PLUGIN_DISABLE", "Disable a plugin", "“disable the X plugin”")

# ── Shell & advanced ────────────────────────────────────────────────────────
_add("Shell & advanced", "RUN_CMD", "Run a shell command (gated/confirmed)", "“run the command: ls -la”")
_add("Shell & advanced", "SHELL_EXEC", "Execute shell (gated/confirmed)", "“execute: df -h”")
_add("Shell & advanced", "SEQUENCE", "Run a multi-step action sequence", "“do X then Y then Z”")
_add("Shell & advanced", "ROUTING_FAULT_EXPLAIN", "Explain why an input failed to route", "“why did that fail to route”")
_add("Shell & advanced", "NOOP", "Internal no-op (ignored fragment guard)", "(internal — fragmentary input is dropped)")


_CAT_ORDER = list(OrderedDict((c, None) for (c, _, _) in _C.values()))


def _load_manifest() -> Tuple[List[dict], set, set]:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    caps = data.get("capabilities", [])
    routable = {c["action"] for c in caps
                if c.get("routable") or c.get("in_supported_list")}
    plugin = {c["action"] for c in caps if c.get("plugin")}
    return caps, routable, plugin


def generate_capabilities_doc() -> Dict:
    """Render blueprints/capabilities_and_actions.md from the manifest + curated map.
    Returns {ok, total, documented, routable, needs_phrase}."""
    caps, routable, plugin = _load_manifest()
    all_actions = {c["action"] for c in caps}

    # New routable actions not yet curated → emitted with a placeholder so the doc
    # stays complete; reported so a human can add a phrase.
    needs_phrase = sorted(a for a in routable if a not in _C)

    cats: "OrderedDict[str, list]" = OrderedDict((c, []) for c in _CAT_ORDER)
    for action, (cat, desc, phrases) in _C.items():
        cats.setdefault(cat, []).append((action, desc, phrases))
    if needs_phrase:
        cats["New / undocumented (add a phrase above)"] = [
            (a, "—", ["(needs activation phrase)"]) for a in needs_phrase]

    out: List[str] = []
    out.append("# ELI — Capabilities & Actions (with activation phrases)\n")
    out.append(f"*Auto-generated {datetime.date.today().isoformat()} from "
               f"`capability_manifest.json` ({len(all_actions)} capabilities; "
               f"{len(routable)} routable). Regenerated by "
               f"`eli/tools/registry/capabilities_doc.py` alongside the manifest.*\n")
    out.append(textwrap.dedent("""\
        **How to read this:** every row is a real action ELI can route to and
        execute. Activation phrases are **representative** — the router is
        paraphrase- and typo-tolerant; a phrase shows the *shape* that fires the
        action, not the only accepted wording. `Plugin` = backed by a plugin (rest
        are core executor+router). Voice users prefix with the wake word
        (“computer, …”). Generation actions (documents/scripts/projects) run the
        evidence-planner first (real code/web/memory analysis) before synthesising.
        """))

    for cat, rows in cats.items():
        if not rows:
            continue
        out.append(f"\n## {cat}\n")
        out.append("| Action | What it does | Example activation phrase(s) | Source |")
        out.append("|---|---|---|---|")
        for action, desc, phrases in rows:
            src = "Plugin" if action in plugin else "Core"
            out.append(f"| `{action}` | {desc} | {' · '.join(phrases)} | {src} |")

    aliases = sorted(all_actions - routable - set(_C))
    if aliases:
        out.append("\n## Aliases & internal actions (not directly user-triggered)\n")
        out.append("Synonyms normalised to a routable action, post-actions, or "
                   "internal pipeline steps:\n")
        out.append(", ".join(f"`{a}`" for a in aliases) + "\n")

    out.append("\n## Coverage\n")
    out.append(f"- Routable actions documented: **{len(routable & set(_C))}/{len(routable)}**")
    if needs_phrase:
        out.append(f"- ⚠️ New/undocumented (need a curated phrase): {', '.join(needs_phrase)}")
    out.append("")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(out), encoding="utf-8")
    return {
        "ok": True,
        "total": len(all_actions),
        "routable": len(routable),
        "documented": len(routable & set(_C)),
        "needs_phrase": needs_phrase,
        "path": str(OUT),
    }


if __name__ == "__main__":
    r = generate_capabilities_doc()
    print(f"Wrote {r['path']}")
    print(f"  documented {r['documented']}/{r['routable']} routable")
    if r["needs_phrase"]:
        print(f"  needs phrase: {', '.join(r['needs_phrase'])}")
