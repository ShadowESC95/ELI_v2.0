#!/usr/bin/env python3
import json
from pathlib import Path

# All actions that the router can return (from executor_enhanced.py SUPPORTED_ACTIONS)
ACTIONS = [
    "CHAT", "TIME", "DATE", "OPEN_APP", "OPEN_URL", "OPEN_BROWSER", "OPEN_FILE_SYSTEM",
    "OPEN_SYSTEM_SETTINGS", "OPEN_AUDIO_SETTINGS", "OPEN_POWER_SETTINGS", "OPEN_COMMUNICATION_HUB",
    "OPEN_MEDIA_HUB", "OPEN_IDE", "OPEN_IN_IDE", "CLOSE_APP", "FOCUS_APP",
    "PLAY_MEDIA", "PAUSE_MEDIA", "STOP_MEDIA", "NEXT_MEDIA", "PREVIOUS_MEDIA", "SHUFFLE_MEDIA",
    "REPEAT_MEDIA", "VOLUME", "KEYBOARD", "MOUSE_CONTROL", "SCREENSHOT", "SCREEN_LOCATE",
    "LIST_DIR", "READ_FILE", "CREATE_FOLDER", "WRITE_NOTE", "NEW_NOTE", "LIST_NOTES", "SEARCH_NOTES",
    "MEMORY_STORE", "MEMORY_RECALL", "MEMORY_STATUS", "EXPLAIN_MEMORY_RUNTIME",
    "RUNTIME_STATUS", "COGNITION_STATUS", "REASONING_MODE_STATUS", "SELF_REPORT",
    "USER_IDENTITY_SUMMARY", "PERSONAL_MEMORY_SUMMARY", "NAME_SOURCE_AUDIT",
    "GET_WEATHER", "NEWS_FETCH", "WEB_SEARCH", "ANALYZE_PDF", "ANALYZE_CSV",
    "SUMMARIZE_FILE", "CONVERT_DOCUMENT", "GENERATE_SCRIPT", "GENERATE_DOCUMENT",
    "GENERATE_PROJECT", "FIX_FILE", "DATA_FABRICATOR", "SHELL_EXEC", "RUN_CMD",
    "SET_ALARM", "SET_TIMER", "POMODORO_START", "POMODORO_STOP", "POMODORO_STATUS",
    "PROACTIVE_STATUS", "PROACTIVE_START", "PROACTIVE_STOP", "HABIT_STATUS",
    "SELF_ANALYZE", "SELF_IMPROVE", "SELF_PATCH", "SELF_UPGRADE", "SELF_TEST",
    "CODE_CHANGES", "MORNING_REPORT", "PLUGIN_LIST", "PLUGIN_INSTALL", "PLUGIN_UNINSTALL",
    "PLUGIN_ENABLE", "PLUGIN_DISABLE", "FRONTIER_STATUS", "ELI_IDENTITY_AUDIT"
]

# For each action, generate several natural language inputs
PATTERNS = {
    "TIME": ["what time is it", "current time", "tell me the time", "time"],
    "DATE": ["what's the date", "today's date", "what day is it"],
    "OPEN_APP": ["open firefox", "launch spotify", "start terminal", "open settings"],
    "OPEN_URL": ["open google.com", "go to github.com", "open https://example.com"],
    "PLAY_MEDIA": ["play music", "play next song", "resume playback"],
    "PAUSE_MEDIA": ["pause music", "stop the music", "pause"],
    "VOLUME": ["volume up", "turn volume down", "set volume to 50%", "mute", "unmute"],
    "SCREENSHOT": ["take screenshot", "capture screen", "screenshot"],
    "MEMORY_STORE": ["remember that I like Python", "store this: test", "save this note"],
    "MEMORY_RECALL": ["what do you know about me", "search memory for Python"],
    "GET_WEATHER": ["weather in London", "what's the forecast", "temperature outside"],
    "ANALYZE_PDF": ["analyze this.pdf", "summarize the PDF", "read the document"],
    "WEB_SEARCH": ["search for cats", "google Python tutorials", "look up ELI"],
    "CHAT": ["hello", "how are you", "what is AI", "tell me a joke", "why is the sky blue"],
}

def generate_test_cases():
    cases = []
    for action, phrases in PATTERNS.items():
        for phrase in phrases:
            cases.append({"input": phrase, "expected_action": action})
    # Also add generic fallback tests
    cases.append({"input": "xyzzy plugh", "expected_action": "CHAT"})
    return cases

if __name__ == "__main__":
    data = generate_test_cases()
    out_path = Path(__file__).parent / "router_test_data.json"
    with open(out_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Generated {len(data)} test cases in {out_path}")
