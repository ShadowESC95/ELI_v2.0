"""
ELI Audio STT — safer, dependency-aware version.

Exports:
- get_audio_stt()
- start_audio_listening(callback=None)
- stop_audio_listening()
- listen_for_command(timeout=5)

Key fixes:
- Bare wake word arms a guarded-command window instead of being emitted as chat
- Guarded commands (open/run/delete/etc.) require wake word unless wake is disabled
- Safe direct commands (pause/play/volume/etc.) work without wake word
- Short ambient garbage is ignored instead of being forwarded into the LLM
- Repeated phrase collapse for cases like: "open spotify open spotify open spotify"
- Single listener thread / single microphone context; no nested microphone reuse
- Clear diagnostics when SpeechRecognition / PyAudio are unavailable
"""
from __future__ import annotations

import os
import queue
import re
import subprocess
import threading
import time
from typing import Callable, Optional


# Purpose:
#   - When wake word is heard, reduce playback volume while user speaks command.
#   - After command dispatch, restore playback volume.
#   - Suppress obvious assistant/media echo that the microphone hears afterwards.
#
# This does NOT alter mic device selection, STT backend, Whisper, Google, Vosk,
# sample rate, or recognizer model.

import os as _eli_os
import re as _eli_re
import subprocess as _eli_subprocess
_ELI_ECHO_GATE_DEFAULT_S = float(_eli_os.environ.get("ELI_STT_POST_COMMAND_ECHO_GATE", "0.5"))
_ELI_DUCK_LEVEL = _eli_os.environ.get("ELI_WAKE_DUCK_LEVEL", "18%")
_ELI_DUCK_ENABLED = _eli_os.environ.get("ELI_WAKE_DUCK_ENABLED", "1") != "0"


def _eli_run_quiet(argv, timeout=1.5):
    try:
        cp = _eli_subprocess.run(
            argv,
            stdout=_eli_subprocess.PIPE,
            stderr=_eli_subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )
        return cp.returncode == 0, (cp.stdout or cp.stderr or "").strip()
    except Exception as exc:
        return False, str(exc)


def _eli_get_sink_volume_snapshot():
    # Prefer wpctl because your system is PipeWire.
    ok, out = _eli_run_quiet(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"], timeout=1.0)
    if ok and out:
        return ("wpctl", out)

    ok, out = _eli_run_quiet(["pactl", "get-sink-volume", "@DEFAULT_SINK@"], timeout=1.0)
    if ok and out:
        return ("pactl", out)

    return None


def _eli_parse_wpctl_volume(snapshot):
    # Example: "Volume: 0.65" or "Volume: 0.65 [MUTED]"
    if not snapshot:
        return None
    m = _eli_re.search(r"Volume:\s*([0-9.]+)", str(snapshot))
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None


def _eli_duck_output():
    if not _ELI_DUCK_ENABLED:
        return None

    snap = _eli_get_sink_volume_snapshot()

    if snap and snap[0] == "wpctl":
        _eli_run_quiet(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", _ELI_DUCK_LEVEL], timeout=1.0)
        log.debug(f"[AUDIO_DUCK] ducked output to {_ELI_DUCK_LEVEL}; snapshot={snap[1]!r}")
        return snap

    if snap and snap[0] == "pactl":
        _eli_run_quiet(["pactl", "set-sink-volume", "@DEFAULT_SINK@", _ELI_DUCK_LEVEL], timeout=1.0)
        log.debug(f"[AUDIO_DUCK] ducked output to {_ELI_DUCK_LEVEL}; snapshot=pactl")
        return snap

    return None


def _eli_restore_output(snapshot):
    if not snapshot:
        return

    backend, raw = snapshot

    if backend == "wpctl":
        vol = _eli_parse_wpctl_volume(raw)
        if vol is not None:
            _eli_run_quiet(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", str(vol)], timeout=1.0)
            log.debug(f"[AUDIO_DUCK] restored output volume to {vol}")
        return

    # pactl output is messier. Avoid unsafe parsing. Best effort only.
    log.debug("[AUDIO_DUCK] pactl restore snapshot present; wpctl restore unavailable")


def _eli_echo_like_assistant_output(text):
    t = _eli_re.sub(r"\s+", " ", str(text or "").lower()).strip(" .,!?:;")
    if not t:
        return False

    # These are not normal user commands. They are typical assistant/TTS echo.
    echo_prefixes = (
        "yes i can help",
        "i can help you",
        "to help you",
        "to help you out",
        "based on our recent conversation",
        "here's why",
        "heres why",
        "it seems that",
        "it seems you're",
        "it seems you are",
        "the user asked me",
        "the user is asking",
        "the user is referring",
        "let's start with",
        "lets start with",
        "as for spotify",
        "i hope this information",
        "if that doesn't help",
        "if that doesnt help",
        "open your web browser",
        "search for immortal technique",
        "once you've found",
        "once you found",
        "click the play button",
    )

    if any(t.startswith(x) for x in echo_prefixes):
        return True

    # Long instructional fragments captured from ELI output.
    if len(t.split()) >= 12 and any(x in t for x in (
        "open your web browser",
        "click the play button",
        "search for",
        "i hope this",
        "let me know",
        "recent conversation",
    )):
        return True

    return False


# Silence ALSA/Jack/PulseAudio stderr noise during microphone init
import ctypes
import ctypes.util

from eli.utils.log import get_logger
log = get_logger(__name__)

try:
    _libc = ctypes.CDLL(ctypes.util.find_library("c"))
    _devnull_fd = os.open(os.devnull, os.O_WRONLY)
    _saved_stderr = os.dup(2)
    def _suppress_alsa():
        os.dup2(_devnull_fd, 2)
    def _restore_stderr():
        os.dup2(_saved_stderr, 2)
except Exception:
    def _suppress_alsa(): pass
    def _restore_stderr(): pass

try:
    import speech_recognition as sr  # type: ignore
    _SR_IMPORT_ERROR: Optional[Exception] = None
except Exception as e:  # pragma: no cover
    sr = None
    _SR_IMPORT_ERROR = e

WAKE_WORDS = [
    "hey eli", "hey computer", "eli", "computer",
]

SAFE_DIRECT_COMMANDS = {
    "play", "pause", "resume", "stop",
    "next", "previous", "skip", "back",
    "next song", "previous song", "next track", "previous track",
    "mute", "unmute",
    "volume up", "volume down",
    "turn volume up", "turn volume down",
    "increase volume", "decrease volume",
    "louder", "quieter",
}

GUARDED_PREFIXES = (
    "open ", "launch ", "start ", "run ", "execute ",
    "close ", "quit ", "kill ", "stop process ",
    "delete ", "remove ", "rm ", "move ", "copy ", "rename ",
    "mkdir ", "create folder", "create directory",
    "open folder", "open directory", "browse ",
    "go to ", "change directory", "cd ",
    "install ", "uninstall ", "sudo ",
    "shutdown", "reboot", "power off",
    "open browser", "open chrome", "open firefox",
    "open settings", "open spotify", "open terminal",
)

GUARDED_EXACT = {
    "settings", "spotify", "terminal", "browser", "chrome", "firefox",
}

DUCK_LEVEL = os.environ.get("ELI_STT_DUCK_LEVEL", "15%")
RESTORE_DELAY_S = float(os.environ.get("ELI_STT_RESTORE_DELAY", "0.20"))
MAIN_TIMEOUT = float(os.environ.get("ELI_STT_MAIN_TIMEOUT", "1.2"))
PHRASE_TIME_LIMIT = float(os.environ.get("ELI_STT_PHRASE_TIME_LIMIT", "6.0"))
WAKE_ARM_TIMEOUT = float(os.environ.get("ELI_STT_WAKE_ARM_TIMEOUT", "12.0"))
# Shorter pause when unarmed — wake word is one word, safe-direct is 1-3 words.
# 0.20s of silence is enough to know a short command ended.
UNARMED_PAUSE_S = float(os.environ.get("ELI_STT_UNARMED_PAUSE", "0.20"))
WAKE_DEBOUNCE_S = float(os.environ.get("ELI_STT_WAKE_DEBOUNCE", "0.7"))
ELI_DISABLE_WAKE_WORD = os.environ.get("ELI_DISABLE_WAKE_WORD", "0").lower() in ("1", "true", "yes", "on")
def _allow_direct_chat() -> bool:
    """Runtime check so the GUI can flip ELI_STT_ALLOW_DIRECT_CHAT without a restart."""
    return os.environ.get("ELI_STT_ALLOW_DIRECT_CHAT", "0").lower() in ("1", "true", "yes", "on")

ALLOW_DIRECT_CHAT_WITHOUT_WAKE = _allow_direct_chat()  # kept for backwards compat
MIN_DIRECT_CHAT_WORDS = int(os.environ.get("ELI_STT_MIN_DIRECT_CHAT_WORDS", "2"))

# Hard override: require wake word for ALL safe-direct commands regardless of media state.
# Default off — media-aware gating in classify() handles the speaker-bleed case dynamically.
# Set ELI_STT_REQUIRE_WAKE_FOR_SAFE_DIRECT=1 to force wake word even in silence.
REQUIRE_WAKE_FOR_SAFE_DIRECT = os.environ.get(
    "ELI_STT_REQUIRE_WAKE_FOR_SAFE_DIRECT", "0"
).lower() in ("1", "true", "yes", "on")



def _cleanup(text: str) -> str:
    t = (text or "").strip().lower()
    t = re.sub(r"[^\w\s'%-]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    prefixes = ["comma", "please", "could you", "can you", "would you", "will you", "hey", "okay", "ok"]
    for p in prefixes:
        if t.startswith(p + " "):
            t = t[len(p) + 1:].strip()
    return re.sub(r"^[,\s\-:;.]+", "", t).strip()


def _collapse_repeated_phrase(text: str) -> str:
    t = _cleanup(text)
    words = t.split()
    n = len(words)
    if n < 2:
        return t

    # Whole-phrase repetition (e.g. "pause pause pause" → "pause")
    for size in range(1, min(5, n // 2) + 1):
        chunk = words[:size]
        i = 0
        reps = 0
        while i + size <= n and words[i:i + size] == chunk:
            reps += 1
            i += size
        if reps >= 2 and i == n:
            return " ".join(chunk)

    # Leading-loop bleed: "X X X Y" where X repeats 3+ times then a tail follows.
    # Almost always music/speaker bleed picking up a chorus + a different snippet.
    # Drop the repeated portion; keep the tail (it's most likely the real command).
    for size in range(1, min(4, n // 3) + 1):
        chunk = words[:size]
        i = 0
        reps = 0
        while i + size <= n and words[i:i + size] == chunk:
            reps += 1
            i += size
        if reps >= 3 and i < n:
            tail = words[i:]
            # If tail is also just the chunk word(s), the whole thing was a loop.
            if all(w in chunk for w in tail):
                return " ".join(chunk)
            return " ".join(tail)

    deduped = [words[0]]
    for w in words[1:]:
        if w != deduped[-1]:
            deduped.append(w)
    return " ".join(deduped)




# Fast command alias resolution
# Whisper/base.en often mangles very short commands because there is almost no
# linguistic context. This layer is deliberately tiny and only rewrites observed
# short command mishears before VoiceGate/router classification.
def _eli_fast_command_alias(text: str) -> str:
    raw = str(text or "")
    t = " ".join(raw.lower().replace("-", " ").replace("_", " ").split())

    exact = {
        "volume up": "volume up",
        "volume down": "volume down",
        "vol up": "volume up",
        "vol down": "volume down",
        "mute": "mute",
        "unmute": "unmute",
        "play": "play",
        "pause": "pause",
        "resume": "resume",
        "stop": "stop",
        "next": "next",
        "previous": "previous",
    }

    mapped = exact.get(t)
    if mapped:
        if mapped != t:
            log.debug(f"[STT_ALIAS] {raw!r} -> {mapped!r}")
        return mapped

    return t

def _word_count(text: str) -> int:
    return len(_cleanup(text).split())


# Safe-direct media wake-word guard
def _eli_media_probably_audible() -> bool:
    """
    Best-effort local check. If playerctl says something is playing, bare media
    controls should require the wake window to avoid lyrics triggering commands.
    """
    if os.environ.get("ELI_STT_REQUIRE_WAKE_FOR_BARE_MEDIA", "1").lower() in {"0", "false", "no", "off"}:
        return False
    try:
        cp = subprocess.run(
            ["playerctl", "-a", "status"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=0.35,
            check=False,
        )
        out = (cp.stdout or "").lower()
        return "playing" in out
    except Exception:
        return False

# Known-app fast-direct route
_SAFE_FAST_APP_TARGETS = {
    "spotify", "browser", "web browser", "firefox", "chrome", "chromium",
    "terminal", "settings", "files", "file manager", "calculator",
    "steam", "discord", "vlc", "text editor", "code", "vscode",
}

_SAFE_FAST_CLOSE_TARGETS = _SAFE_FAST_APP_TARGETS | {"tab", "window"}

def _is_safe_direct(text: str) -> bool:
    t = _collapse_repeated_phrase(text)

    # Existing bare deterministic controls.
    if t in SAFE_DIRECT_COMMANDS:
        return True

    # Use media/app alias normalizer if later patches installed it.
    alias = globals().get("_eli_media_voice_alias")
    if callable(alias):
        try:
            t = alias(t)
        except Exception:
            pass

    # Known local app opens may bypass wake.
    # Arbitrary "open X" stays guarded, because ambient media can say "open ...".
    m = re.fullmatch(r"(?:open|launch|start)\s+(.+)", t)
    if m and m.group(1).strip() in _SAFE_FAST_APP_TARGETS:
        return True

    m = re.fullmatch(r"(?:close|quit|kill)\s+(.+)", t)
    if m and m.group(1).strip() in _SAFE_FAST_CLOSE_TARGETS:
        return True

    # Bare known app names can be used as fast app-open shorthand.
    if t in _SAFE_FAST_APP_TARGETS:
        return True

    return False


def _is_guarded_command(text: str) -> bool:
    t = _collapse_repeated_phrase(text)
    if not t:
        return False
    if t in GUARDED_EXACT:
        return True
    return any(t.startswith(prefix) for prefix in GUARDED_PREFIXES)


_VOL_RE = re.compile(r"(\d+)%")


def _get_current_volume() -> Optional[str]:
    try:
        out = subprocess.check_output(
            ["pactl", "get-sink-volume", "@DEFAULT_SINK@"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        m = _VOL_RE.search(out)
        if m:
            return f"{m.group(1)}%"
    except Exception:
        pass
    return None


def _set_volume(level: str) -> None:
    try:
        subprocess.Popen(
            ["pactl", "set-sink-volume", "@DEFAULT_SINK@", str(level)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def _duck(prev_vol: Optional[str]) -> None:
    _set_volume(DUCK_LEVEL)


def _restore(prev_vol: Optional[str]) -> None:
    if prev_vol:
        _set_volume(prev_vol)


def _restore_later(prev_vol: Optional[str], delay_s: float = RESTORE_DELAY_S) -> None:
    threading.Timer(delay_s, _restore, args=(prev_vol,)).start()


def stt_diagnostics() -> dict:
    return {
        "speech_recognition_imported": sr is not None,
        "speech_recognition_error": repr(_SR_IMPORT_ERROR) if _SR_IMPORT_ERROR else None,
        "mic_device_index_env": os.environ.get("ELI_MIC_DEVICE_INDEX"),
        "wake_word_disabled": ELI_DISABLE_WAKE_WORD,
        "allow_direct_chat_without_wake": ALLOW_DIRECT_CHAT_WITHOUT_WAKE,
        "min_direct_chat_words": MIN_DIRECT_CHAT_WORDS,
        "wake_arm_timeout": WAKE_ARM_TIMEOUT,
    }


def process_transcript(text: str):
    try:
        from eli.execution.router_enhanced import route
        from eli.execution.executor_enhanced import execute
        intent = route(text)
        return execute(intent.get("action") or "CHAT", intent.get("args") or {"message": text})
    except Exception as e:
        return {
            "ok": False,
            "action": "VOICE_ROUTE",
            "error": str(e),
            "content": "Voice routing failed",
            "response": "Voice routing failed",
        }


# Bare command verbs that need a target — if heard alone, wait for more
_INCOMPLETE_COMMAND_VERBS = {
    "open", "launch", "start", "run", "execute",
    "close", "quit", "kill",
    "delete", "remove", "move", "copy", "rename",
    "install", "uninstall",
    "go to", "browse", "search",
}

def _is_incomplete_command(text: str) -> bool:
    """Return True if text is a bare command verb without a target."""
    t = _cleanup(text).strip()
    return t in _INCOMPLETE_COMMAND_VERBS


# Media phrases often arrive split across STT chunks:
#   "play blood runs cold" + "by jedi mind tricks on spotify"
# Do not dispatch ambiguous play-search fragments immediately.
def _is_potentially_incomplete_media_play(text: str) -> bool:
    t = _eli_media_voice_alias(text or "")
    if not t:
        return False

    # Service-first fragments are incomplete without a query.
    if t in {"spotify", "youtube", "yt", "mpv", "on spotify", "on youtube", "on yt", "on mpv"}:
        return True
    if t in {"spotify play", "youtube play", "yt play", "mpv play", "on spotify play", "on youtube play", "on yt play", "on mpv play"}:
        return True

    if not t.startswith("play "):
        return False

    # Explicit service means complete enough for router.
    if any(x in t for x in (" on spotify", " on youtube", " on yt", " on mpv")):
        return False

    # Dangling connectors are definitely incomplete.
    if t.endswith((" by", " on", " from", " album by", " song by")):
        return True

    # If there is no explicit service, hold it briefly so the user can finish:
    # "by artist on spotify". This prevents accidental YouTube launches.
    return True



# Media voice alias and pending-command guard
# This sits before VoiceGate classification. It fixes short media-service
# fragments that Whisper regularly mangles:
#   "algezera on you"       -> "al jazeera on youtube"
#   "open alt-0 on youtube" -> "open al jazeera on youtube"
#   "party ... on spot"     -> "party ... on spotify"
def _media_voice_alias_legacy(text: str) -> str:
    t = _cleanup(text)
    if not t:
        return t

    # common command verb mishear
    t = re.sub(r"^pay\s+", "play ", t)
    t = re.sub(r"^played\s+", "play ", t)
    t = re.sub(r"^opens\s+", "open ", t)

    # "put" → "play" when it looks like a media search (Whisper mishears "play"
    # as "put" / "put our" / "put a" very often with short commands).
    # Only rewrite when followed by a filler article that signals the original
    # was "play" — bare "put X" could be a legitimate system command.
    t = re.sub(r"^put\s+(?:our|a|the)\s+", "play ", t)
    # Also rewrite "put X on spotify/youtube/yt/mpv" unconditionally.
    t = re.sub(
        r"^put\s+(.+?)\s+on\s+(spotify|youtube|yt|mpv)\b",
        lambda m: f"play {m.group(1)} on {m.group(2)}",
        t,
    )

    # Al Jazeera is a brutal one for Whisper/base.en.
    # Keep this intentionally narrow to command/media phrases.
    alj_patterns = [
        r"al\s*jazeera",
        r"al\s*jazerra",
        r"al\s*jazera",
        r"al\s*gezera",
        r"al\s*gezira",
        r"algezera",
        r"algezira",
        r"algazear",
        r"algazare",
        r"algazera",
        r"algazira",
        r"algazir",
        r"algiers\s+era",
        r"all\s+jizz\s*era",
        r"alt\s*[- ]?\s*0",
        r"alt\s+zero",
        r"hours\s+of\s+zero",
        r"i'll\s+just\s+air",
        r"and\s+i'll\s+just\s+air",
    ]
    for pat in alj_patterns:
        t = re.sub(rf"\b{pat}\b", "al jazeera", t)

    # Service aliases. Strip junk after a clear service fragment at the end.
    # GUARD: only rewrite a trailing "on you[tube]" / "on spot[ify]" into a
    # service when the text is actually a media-play command. Without this,
    # ordinary conversation ending in "on you" / "on your ..." ("checking up
    # on you", "turned on your network") was being corrupted into "...youtube".
    _looks_media_cmd = bool(re.match(
        r"^(play|pay|played|put|open|opens|listen|watch|stream|queue)\b", t
    )) or " play " in f" {t} "
    if _looks_media_cmd:
        t = re.sub(
            r"\bon\s+(?:you|your|youtub|youtube|you\s*tube|yt|your\s+ship)(?:\b.*)?$",
            "on youtube",
            t,
        )
        t = re.sub(
            r"\bon\s+(?:spot|spott|spot\s+of\s*f?|spot\s+if\s+i|spotify|spodify|spotif(?:y)?)(?:\b.*)?$",
            "on spotify",
            t,
        )

    # Standalone service fragment completion used after pending media command.
    # Only unambiguous service words — bare "you"/"your" are normal speech and
    # must never be auto-completed to YouTube.
    if t in {"youtub", "youtube", "you tube", "yt"}:
        return "on youtube"
    if t in {"spot", "spott", "spot of", "spot of f", "spot if i", "spotify", "spodify", "spotif"}:
        return "on spotify"

    return re.sub(r"\s+", " ", t).strip()


def _eli_pending_media_can_complete(prefix: str, fragment: str) -> bool:
    p = _eli_media_voice_alias(prefix)
    f = _eli_media_voice_alias(fragment)

    # Media play fragments may only be completed by explicit service/artist/service text.
    if p.startswith("play "):
        if re.search(r"\bon\s+(spotify|youtube|yt|mpv)\b", f):
            return True
        if f in {"spotify", "youtube", "yt", "mpv", "on spotify", "on youtube", "on yt", "on mpv"}:
            return True
        if re.search(r"\bby\s+.+\s+on\s+(spotify|youtube|yt|mpv)\b", f):
            return True
        return False

    # Non-media incomplete commands like "open" can still take a target.
    return bool(f)


# Internal-prompt echo phrases. When ELI's TTS reads internal prompt content
# back into the mic (or the LLM emits internal scaffolding), the STT can
# capture phrases like "the situation brief and conversation history" and
# try to dispatch them as commands. These phrases are unlikely in natural
# user speech and should be dropped before routing.
_INTERNAL_PROMPT_ECHO_RE = re.compile(
    r"\b("
    r"situation\s+brief|"
    r"conversation\s+history|"
    r"grounding\s+package|"
    r"grounded\s+(?:facts|evidence)|"
    r"recent\s+dialogue|"
    r"final\s+instruction|"
    r"orchestrator\s+observations?|"
    r"intent\s+action|"
    r"user\s+prompt|"
    r"persona\s+handoff|"
    r"agent\s+bus\s+notes?|"
    r"reranked\s+hits"
    r")\b",
    re.IGNORECASE,
)


def is_internal_prompt_echo(text: str) -> bool:
    """True if `text` looks like a leak of ELI's own internal scaffolding."""
    return bool(_INTERNAL_PROMPT_ECHO_RE.search(str(text or "")))


class VoiceGate:
    def __init__(self, wake_timeout_sec: float = WAKE_ARM_TIMEOUT):
        self.wake_timeout_sec = wake_timeout_sec
        self._guarded_until = 0.0
        self._last_wake_ts = 0.0
        self._pending_prefix = ""  # accumulated incomplete command prefix
        self._pending_started = 0.0

    def arm(self) -> None:
        self._guarded_until = time.monotonic() + self.wake_timeout_sec
        self._armed_at = time.monotonic()

    def clear(self) -> None:
        self._guarded_until = 0.0
        self._pending_prefix = ""

    def armed(self) -> bool:
        return time.monotonic() < self._guarded_until

    def _strip_leading_wake(self, text: str) -> tuple[Optional[str], str]:
        t = _collapse_repeated_phrase(text)
        for wake in sorted(WAKE_WORDS, key=len, reverse=True):
            if t == wake:
                return wake, ""
            if t.startswith(wake + " "):
                return wake, _cleanup(t[len(wake):])
        return None, t

    def classify(self, raw_text: str) -> tuple[str, Optional[str], Optional[str]]:
        text = _eli_media_voice_alias(_collapse_repeated_phrase(raw_text))
        if not text:
            return "ignore", None, None

        # Drop internal-prompt echoes before any other gate decision.
        if is_internal_prompt_echo(text):
            return "ignore", None, None

        if ELI_DISABLE_WAKE_WORD:
            return "dispatch", text, None

        wake, remainder = self._strip_leading_wake(text)

        # Bare wake word: arm guarded window; do not emit to callback.
        if wake and not remainder:
            now = time.time()
            if (now - self._last_wake_ts) < WAKE_DEBOUNCE_S:
                return "ignore", None, wake
            self._last_wake_ts = now
            self._pending_prefix = ""
            self._pending_started = 0.0
            self.arm()
            return "arm", None, wake

        # Wake word plus command in same utterance.
        if wake and remainder:
            # Check if remainder is incomplete (e.g., bare "open" without target)
            if _is_incomplete_command(remainder) or _is_potentially_incomplete_media_play(remainder):
                print(f"🔄 [AUDIO] Incomplete command '{remainder}' — waiting for target/service...")
                self._pending_prefix = remainder
                self._pending_started = time.monotonic()
                self.arm()  # re-arm to wait for the target/service
                return "arm_incomplete", None, wake
            self.clear()
            return "dispatch", remainder, wake

        # If armed from a prior bare wake word, prepend any pending prefix.
        if self.armed():
            if self._pending_prefix:
                if not _eli_pending_media_can_complete(self._pending_prefix, text):
                    print(f"🧯 [AUDIO] Dropped non-completing fragment for pending command: '{self._pending_prefix}' + '{text}'")
                    self._pending_prefix = ""
                    self.clear()
                    return "ignore_unarmed", None, None

                # If the user re-said the full command (text already self-contained and
                # complete), use text directly rather than prepending the pending prefix
                # — prevents duplication like "play diabolic play diabolic on spotify".
                _pref_verb = self._pending_prefix.split()[0] if self._pending_prefix else ""
                if _pref_verb and text.startswith(_pref_verb + " ") and not _is_potentially_incomplete_media_play(text):
                    combined = _eli_media_voice_alias(text)
                else:
                    combined = _eli_media_voice_alias(f"{self._pending_prefix} {text}")
                print(f"🔗 [AUDIO] Combined: '{self._pending_prefix}' + '{text}' → '{combined}'")
                self._pending_prefix = ""
                self.clear()
                return "dispatch", combined, None
            # Check if this utterance itself is an incomplete command
            if _is_incomplete_command(text) or _is_potentially_incomplete_media_play(text):
                print(f"🔄 [AUDIO] Incomplete command '{text}' — waiting for target/service...")
                self._pending_prefix = text
                self._pending_started = time.monotonic()
                # Stay armed, don't clear
                return "arm_incomplete", None, None
            self.clear()
            return "dispatch", text, None

        # Safe direct commands (play/pause/next/volume/etc.) always dispatch without
        # wake word. REQUIRE_WAKE_FOR_SAFE_DIRECT is an opt-in hard override
        # (default off) — set ELI_STT_REQUIRE_WAKE_FOR_SAFE_DIRECT=1 only if you
        # want wake-word-always mode for debugging.
        if _is_safe_direct(text):
            if REQUIRE_WAKE_FOR_SAFE_DIRECT:
                return "ignore_unarmed", None, None
            return "dispatch", text, None

        # Guarded commands without wake are ignored.
        if _is_guarded_command(text):
            return "guarded_without_wake", None, None

        # Free-form direct chat without wake is optional. Use a minimum word count
        # so ambient snippets like "mot" or single-noise blips do not trigger the LLM.
        if _allow_direct_chat():
            if _word_count(text) >= MIN_DIRECT_CHAT_WORDS:
                return "dispatch", text, None
            return "ignore_too_short", None, None

        return "ignore_unarmed", None, None


class ELIAudioSTT:
    def __init__(self):
        if sr is None:
            raise RuntimeError(
                "speech_recognition is not installed in this environment. "
                "Install with: pip install SpeechRecognition pyaudio"
            )

        self.recognizer = sr.Recognizer()

        # Local Whisper needs a more sensitive capture front-end than Google STT.
        # These values control when SpeechRecognition decides speech has started/stopped.
        self.recognizer.energy_threshold = int(os.environ.get("ELI_STT_ENERGY_THRESHOLD", "1200"))
        self.recognizer.dynamic_energy_threshold = os.environ.get(
            "ELI_STT_DYNAMIC_ENERGY", "0"
        ).lower() in {"1", "true", "yes", "on"}
        self.recognizer.pause_threshold = float(os.environ.get("ELI_STT_PAUSE_THRESHOLD", "1.20"))
        self.recognizer.non_speaking_duration = float(
            os.environ.get("ELI_STT_NON_SPEAKING_DURATION", "0.35")
        )
        # Minimum sustained duration (seconds) of above-threshold audio before it
        # counts as a phrase. 0.2s is enough to distinguish a real word from a
        # brief transient; 0.5s was silently dropping short commands like "next".
        self.recognizer.phrase_threshold = float(os.environ.get("ELI_STT_PHRASE_THRESHOLD", "0.2"))
        log.debug(
            f"[STT_CONFIG] energy={self.recognizer.energy_threshold} "
            f"dynamic={self.recognizer.dynamic_energy_threshold} "
            f"pause={self.recognizer.pause_threshold} "
            f"non_speaking={self.recognizer.non_speaking_duration}",
        )

        device_index = os.environ.get("ELI_MIC_DEVICE_INDEX")
        if device_index is not None:
            try:
                self.microphone = sr.Microphone(device_index=int(device_index))
                log.debug(f"[AUDIO] Using microphone device index {device_index}")
            except Exception as e:
                log.debug(f"[AUDIO] Failed to use device {device_index}: {e}. Falling back to default mic.")
                self.microphone = sr.Microphone()
        else:
            self.microphone = sr.Microphone()

        self.is_listening = False
        self.callback: Optional[Callable[[str], None]] = None
        self.audio_queue: queue.Queue[str] = queue.Queue()
        self.last_transcript = ""
        self._state_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._voice_gate = VoiceGate()
        self._ducked_vol = None  # stored during wake word duck
        self._eli_duck_snapshot = None
        self._eli_ignore_until = 0.0
        self._eli_ignore_reason = ""

        # Voice profile state — runtime statistics on the user's speech volume
        # so the energy threshold can be biased toward what the local user
        # actually sounds like, not the SpeechRecognition library's ambient
        # estimate alone.
        self._voice_profile = self._load_voice_profile()

        # Ambient calibration: adjusts the energy threshold to sit above the
        # current room noise floor. With ELI's noise cancellation active (via
        # module-echo-cancel in the launcher), ambient RMS is ~30-60 so calibration
        # is safe. Without noise cancel (raw mic + music/HVAC), calibration can
        # spike to 800-8000 making normal speech undetectable. In that case set
        # ELI_STT_CALIBRATE=0 to use the fixed ELI_STT_ENERGY_THRESHOLD instead.
        _do_calibrate = os.environ.get("ELI_STT_CALIBRATE", "0").lower() not in {"0", "false", "no", "off"}
        if _do_calibrate:
            log.debug("[AUDIO] Calibrating microphone for ambient noise...")
            _suppress_alsa()
            try:
                with self.microphone as source:
                    cal_duration = float(os.environ.get("ELI_STT_AMBIENT_CAL_SEC", "1.5"))
                    _pre_cal = self.recognizer.energy_threshold
                    self.recognizer.adjust_for_ambient_noise(source, duration=cal_duration)
                    # Hard cap so loud startup noise can't push threshold into shouting range.
                    _cal_cap = float(os.environ.get("ELI_STT_CAL_CAP", "2000"))
                    if self.recognizer.energy_threshold > _cal_cap:
                        log.debug(
                            f"[AUDIO] Calibration capped {self.recognizer.energy_threshold:.0f}"
                            f" → {_cal_cap:.0f} (ELI_STT_CAL_CAP)",
                        )
                        self.recognizer.energy_threshold = _cal_cap
            finally:
                _restore_stderr()
        else:
            log.debug(
                f"[AUDIO] Ambient calibration skipped (ELI_STT_CALIBRATE=0). "
                f"Fixed threshold={self.recognizer.energy_threshold:.0f}",
            )
        # Bias against picked-up profile, if any history exists.
        self._apply_voice_profile_bias()
        log.debug(
            f"[AUDIO] Microphone ready "
            f"(energy={self.recognizer.energy_threshold:.0f}, "
            f"voice_profile_n={self._voice_profile.get('count', 0)})"
        )

    # ── Voice profile learning ───────────────────────────────────────────
    def _voice_profile_path(self):
        from pathlib import Path
        try:
            from eli.core.paths import get_paths
            return get_paths().artifacts_dir / "runtime" / "voice_profile.json"
        except Exception:
            return Path.home() / ".eli_voice_profile.json"

    def _load_voice_profile(self) -> dict:
        import json
        p = self._voice_profile_path()
        try:
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {"count": 0, "energy_mean": 0.0, "energy_min": 0.0,
                "energy_max": 0.0, "duration_mean_s": 0.0}

    def _save_voice_profile(self) -> None:
        import json
        p = self._voice_profile_path()
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(self._voice_profile, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _apply_voice_profile_bias(self) -> None:
        """Bias energy_threshold toward the user's known speech volume range.
        The bias can only LOWER the threshold toward the user's voice level —
        it must never raise it above what was already set, so a polluted profile
        (built from shouting sessions) cannot make ELI deaf to normal speech."""
        if self._voice_profile.get("count", 0) < 5:
            return  # Not enough data yet.
        mean = float(self._voice_profile.get("energy_mean") or 0.0)
        if mean <= 0:
            return
        ambient_thr = float(self.recognizer.energy_threshold)
        # Target: 45% of mean energy (centre of expected voice range).
        # Hard cap at 2000 so a shout-polluted profile can't push this above
        # the point where normal speech becomes inaudible.
        target = min(max(60.0, mean * 0.45), 2000.0)
        # Only apply if it would LOWER the threshold, never raise it.
        if target < ambient_thr:
            self.recognizer.energy_threshold = float(target)

    def _record_voice_sample(self, audio) -> None:
        """Update voice profile statistics from a confirmed user utterance."""
        try:
            import audioop
            raw = audio.get_raw_data()
            energy = audioop.rms(raw, audio.sample_width)
            duration = len(raw) / float(audio.sample_width * audio.sample_rate)
            n = int(self._voice_profile.get("count", 0)) + 1
            mean = float(self._voice_profile.get("energy_mean", 0.0))
            mn = float(self._voice_profile.get("energy_min", energy))
            mx = float(self._voice_profile.get("energy_max", energy))
            dmean = float(self._voice_profile.get("duration_mean_s", 0.0))
            new_mean = mean + (energy - mean) / n
            new_dmean = dmean + (duration - dmean) / n
            self._voice_profile = {
                "count": n,
                "energy_mean": new_mean,
                "energy_min": min(mn, energy) if n > 1 else energy,
                "energy_max": max(mx, energy) if n > 1 else energy,
                "duration_mean_s": new_dmean,
                "last_energy": energy,
                "last_duration_s": duration,
            }
            # Persist every 5 samples to keep IO low.
            if n % 5 == 0:
                self._save_voice_profile()
        except Exception:
            pass

    def start_listening(self, callback=None):
        with self._state_lock:
            self.callback = callback
            if self._thread and self._thread.is_alive():
                self.is_listening = True
                log.debug("[AUDIO] Already listening")
                return
            self.is_listening = True
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._listen_loop, daemon=True, name="ELI-STT")
            self._thread.start()
        log.debug("[AUDIO] Started listening for voice commands")

    def stop_listening(self):
        with self._state_lock:
            self.is_listening = False
            self._stop_event.set()
            thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=max(2.0, MAIN_TIMEOUT + 0.5))
        with self._state_lock:
            if self._thread is thread and thread and not thread.is_alive():
                self._thread = None
        log.debug("[AUDIO] Stopped listening")

    def listen_once(self, timeout=5) -> str:
        try:
            with self.microphone as source:
                audio = self.recognizer.listen(source, timeout=timeout, phrase_time_limit=PHRASE_TIME_LIMIT)
            from eli.perception.local_whisper_stt import transcribe_speech_recognition_audio as _eli_local_stt
            text = _eli_local_stt(audio).lower().strip()
            text = _collapse_repeated_phrase(text)
            text = _eli_fast_command_alias(text)
            self.last_transcript = text
            return text
        except Exception:
            return ""

    def _recognize(self, audio) -> str:
        try:
            from eli.perception.local_whisper_stt import transcribe_speech_recognition_audio as _eli_local_stt
            return _collapse_repeated_phrase(_eli_local_stt(audio).lower().strip())
        except Exception as _stt_err:
            log.debug(f"[STT][ERROR] transcription failed: {type(_stt_err).__name__}: {_stt_err}")
            return ""

    def _emit(self, cmd: str):
        cmd = _collapse_repeated_phrase(cmd)
        cmd = _eli_fast_command_alias(cmd)
        if not cmd:
            return

        print(f"🎤 [AUDIO] Command: '{cmd}'")
        self.last_transcript = cmd

        if self.callback:
            print("   ↳ CALLBACK IS SET, invoking now")
            try:
                self.callback(cmd)
            except Exception as e:
                log.debug(f"[AUDIO] Callback error: {e}")
        else:
            print("   ↳ NO CALLBACK SET")

        # Restore output after command dispatch.
        try:
            snap = getattr(self, "_eli_duck_snapshot", None)
            if snap is not None:
                _eli_restore_output(snap)
                self._eli_duck_snapshot = None
        except Exception as e:
            log.debug(f"[AUDIO_DUCK][RESTORE_ERROR] {e}")

        # Short post-command gate so ELI/media output does not immediately get
        # re-transcribed as the next user command.
        try:
            gate_s = float(__import__("os").environ.get("ELI_STT_POST_COMMAND_ECHO_GATE", "0.5"))
        except Exception:
            gate_s = 0.5
        self._eli_ignore_until = __import__("time").monotonic() + gate_s
        self._eli_ignore_reason = "post_command_echo_gate"
        log.debug(f"[AUDIO_ECHO_GATE] ignoring mic for {gate_s:.1f}s after command dispatch")

    def _listen_loop(self):
        try:
            _suppress_alsa()
            with self.microphone as source:
                _restore_stderr()
                log.debug("[AUDIO] Microphone ready")
                # Adaptive recalibration: every ELI_STT_RECALIBRATE_EVERY cycles
                # of silence, redo ambient_noise to follow drifting fan/HVAC noise.
                _recal_every = int(os.environ.get("ELI_STT_RECALIBRATE_EVERY", "60"))
                _silent_streak = 0

                _speaking_lock_path = os.environ.get(
                    "ELI_TTS_SPEAKING_LOCK", "/tmp/eli_tts_speaking.lock"
                )
                _speaking_lock_max_age = float(
                    os.environ.get("ELI_TTS_SPEAKING_LOCK_MAX_AGE_SEC", "30")
                )

                def _eli_is_speaking() -> bool:
                    try:
                        from pathlib import Path as _P
                        p = _P(_speaking_lock_path)
                        if not p.exists():
                            return False
                        # Stale-lock guard: if older than max_age, treat as gone.
                        try:
                            age = time.time() - p.stat().st_mtime
                            if age > _speaking_lock_max_age:
                                p.unlink(missing_ok=True)
                                return False
                        except Exception:
                            pass
                        return True
                    except Exception:
                        return False

                # ── Background TTS monitor ───────────────────────────────────
                # recognizer.listen() blocks for up to phrase_time_limit (20 s in
                # direct-chat mode).  While it's blocking the while-loop's
                # _eli_is_speaking() guard never runs — so TTS audio accumulates
                # in the open PyAudio stream and is returned as a transcript.
                # A daemon thread continuously polls the speaking lock every 0.1 s
                # so _tts_mon_last[0] is updated even while listen() is blocking.
                # After listen() returns we can tell whether TTS overlapped the
                # capture window and drop the echo before Whisper even sees it.
                import threading as _threading
                _tts_mon_last: list[float] = [0.0]   # shared: last seen active (monotonic)
                _tts_mon_stop = _threading.Event()
                _post_tts_drain_s = float(
                    os.environ.get("ELI_STT_POST_TTS_DRAIN_SEC", "1.5")
                )

                def _tts_monitor_fn():
                    while not _tts_mon_stop.is_set():
                        try:
                            if _eli_is_speaking():
                                _tts_mon_last[0] = time.monotonic()
                        except Exception:
                            pass
                        time.sleep(0.1)

                _tts_mon_thread = _threading.Thread(
                    target=_tts_monitor_fn, daemon=True, name="eli-tts-monitor"
                )
                _tts_mon_thread.start()

                while self.is_listening and not self._stop_event.is_set():
                    try:
                        # Hard-pause mic capture while ELI's TTS is actively
                        # speaking. Without this, the mic transcribes ELI's
                        # own voice and triggers a chain of repeat commands.
                        if _eli_is_speaking():
                            _tts_mon_last[0] = time.monotonic()
                            time.sleep(0.15)
                            continue

                        # Post-TTS drain cooldown ─────────────────────────────
                        # If TTS ended less than _post_tts_drain_s ago, skip
                        # the listen() call entirely and let PyAudio's ring
                        # buffer cycle through stale TTS frames before we
                        # accept new mic input.
                        # Override: ELI_STT_POST_TTS_DRAIN_SEC
                        if _tts_mon_last[0] > 0:
                            _drain_elapsed = time.monotonic() - _tts_mon_last[0]
                            if _drain_elapsed < _post_tts_drain_s:
                                time.sleep(0.15)
                                continue

                        self._listen_count = getattr(self, '_listen_count', 0) + 1
                        if self._listen_count <= 1 or self._listen_count % 20 == 0:
                            print(f"👂 [AUDIO] Listening... (cycle {self._listen_count})")
                        # Wider pause window during armed (multi-word command) state.
                        # Default pause_threshold (1.20s) was set in __init__; only
                        # adjust it when the gate is armed so natural pauses don't
                        # cut commands short.
                        if self._voice_gate.armed():
                            # Wider pause window while armed — user is mid-command
                            # and natural pauses (e.g. "play ... on spotify") must
                            # not cut the phrase short.
                            self.recognizer.pause_threshold = float(
                                os.environ.get("ELI_STT_ARMED_PAUSE", "1.4")
                            )
                            self.recognizer.non_speaking_duration = float(
                                os.environ.get("ELI_STT_NON_SPEAKING_DURATION", "0.35")
                            )
                            _active_phrase_limit = PHRASE_TIME_LIMIT
                        elif _allow_direct_chat():
                            # Direct listen mode — user may speak long natural sentences.
                            # 1.5s silence ends the phrase (short enough that "pause" or
                            # "next" dispatch promptly even with mild background noise;
                            # long enough to not cut mid-sentence natural pauses).
                            # 20s phrase cap guarantees a submit if background noise
                            # prevents silence detection entirely.
                            self.recognizer.pause_threshold = float(
                                os.environ.get("ELI_STT_DIRECT_PAUSE", "1.5")
                            )
                            self.recognizer.non_speaking_duration = float(
                                os.environ.get("ELI_STT_NON_SPEAKING_DURATION", "0.35")
                            )
                            _active_phrase_limit = float(
                                os.environ.get("ELI_STT_DIRECT_PHRASE_LIMIT", "20.0")
                            )
                        else:
                            # Tight pause when unarmed — we're only listening for
                            # the wake word (1-3 words). 0.30s of silence is enough;
                            # shorter non_speaking_duration and phrase_time_limit
                            # reduce whisper input size for faster wake detection.
                            self.recognizer.pause_threshold = UNARMED_PAUSE_S
                            self.recognizer.non_speaking_duration = float(
                                os.environ.get("ELI_STT_UNARMED_NON_SPEAKING", "0.15")
                            )
                            _active_phrase_limit = float(
                                os.environ.get("ELI_STT_UNARMED_PHRASE_LIMIT", "3.0")
                            )

                        # Periodic recalibration during quiet periods so the
                        # energy threshold tracks ambient noise drift.
                        _do_recal = os.environ.get("ELI_STT_CALIBRATE", "0").lower() not in {"0", "false", "no", "off"}
                        if _do_recal and _silent_streak >= _recal_every and _recal_every > 0:
                            try:
                                _pre_recal = self.recognizer.energy_threshold
                                self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                                _recal_cap = float(os.environ.get("ELI_STT_CAL_CAP", "2000"))
                                if self.recognizer.energy_threshold > _recal_cap:
                                    self.recognizer.energy_threshold = _recal_cap
                                self._apply_voice_profile_bias()
                                print(
                                    f"🎚️ [AUDIO] Recalibrated ambient: "
                                    f"energy={self.recognizer.energy_threshold:.0f}",
                                    flush=True,
                                )
                            except Exception as _recal_err:
                                log.debug(f"[AUDIO] Recal failed: {_recal_err}")
                            _silent_streak = 0
                        elif not _do_recal and _silent_streak >= _recal_every and _recal_every > 0:
                            _silent_streak = 0  # reset counter even when calibration is off

                        _listen_start = time.monotonic()
                        audio = self.recognizer.listen(source, timeout=MAIN_TIMEOUT, phrase_time_limit=_active_phrase_limit)
                    except sr.WaitTimeoutError:
                        # Restore duck if the gate expired while we were waiting
                        # for the user to speak (covers arm_incomplete → silence → timeout).
                        if self._eli_duck_snapshot is not None and not self._voice_gate.armed():
                            try:
                                _eli_restore_output(self._eli_duck_snapshot)
                                self._eli_duck_snapshot = None
                                log.debug("[AUDIO_DUCK] Gate expired (no speech) — volume restored")
                            except Exception as _re:
                                log.debug(f"[AUDIO_DUCK][RESTORE_ERROR] {_re}")
                        continue
                    except Exception as e:
                        if not self.is_listening or self._stop_event.is_set():
                            break
                        log.debug(f"[AUDIO] Listen error: {e}")
                        time.sleep(0.1)
                        continue

                    transcript = self._recognize(audio)
                    if not transcript:
                        _silent_streak += 1
                        continue
                    _silent_streak = 0

                    # ── TTS window overlap check ──────────────────────────────
                    # The background monitor stamped _tts_mon_last[0] whenever TTS
                    # was active.  If that stamp falls at or after _listen_start
                    # (with a small 0.2 s pre-roll tolerance), TTS was playing
                    # while the mic was open — the transcript is ELI's own voice.
                    # Drop it and restart the drain cooldown so the next listen()
                    # call only fires after fresh frames fill the buffer.
                    if _tts_mon_last[0] >= _listen_start - 0.2:
                        _tts_mon_last[0] = time.monotonic()   # restart drain timer
                        print(
                            f"🔇 [AUDIO_ECHO_GATE] TTS active during listen window — dropped: "
                            f"{transcript!r}",
                            flush=True,
                        )
                        continue

                    # If the lock appeared during the listen() call (TTS
                    # started while we were still capturing), drop the
                    # transcript — it is almost certainly ELI's own voice.
                    if _eli_is_speaking():
                        print(
                            f"🔇 [AUDIO_ECHO_GATE] dropped transcript captured during TTS: {transcript!r}",
                            flush=True,
                        )
                        continue
                    # Update user voice profile for next time's threshold bias.
                    self._record_voice_sample(audio)

                    transcript = _collapse_repeated_phrase(transcript)
                    transcript = _eli_fast_command_alias(transcript)
                    # Speaker-bleed filter: when media is audible and the transcript
                    # looks like a song-loop capture (high token-repetition density),
                    # drop it. Real commands rarely have >60% repetition.
                    try:
                        _words = transcript.split()
                        if len(_words) >= 4 and _eli_media_probably_audible():
                            _unique = len(set(_words))
                            _rep_ratio = 1.0 - (_unique / len(_words))
                            if _rep_ratio >= 0.5:
                                print(
                                    f"🎵 [AUDIO_BLEED_FILTER] dropped likely-music transcript "
                                    f"(rep_ratio={_rep_ratio:.2f}): {transcript!r}",
                                    flush=True,
                                )
                                continue
                    except Exception:
                        pass
                    _heard_preview = transcript if len(transcript) <= 80 else (transcript[:77] + "...")
                    print(f"👂 [AUDIO] Heard ({len(transcript)} chars): '{_heard_preview}'", flush=True)

                    # Drop mic input during short post-command cooldown.
                    try:
                        now_mono = __import__("time").monotonic()
                        if now_mono < getattr(self, "_eli_ignore_until", 0.0):
                            left = getattr(self, "_eli_ignore_until", 0.0) - now_mono
                            print(
                                f"🛡️ [AUDIO_ECHO_GATE] ignored during cooldown "
                                f"({left:.1f}s left): {transcript!r}",
                                flush=True,
                            )
                            continue
                    except Exception:
                        pass

                    # Drop obvious assistant/TTS echo.
                    try:
                        if _eli_echo_like_assistant_output(transcript):
                            print(f"🛡️ [AUDIO_ECHO_GATE] ignored assistant echo: {transcript!r}", flush=True)
                            continue
                    except Exception:
                        pass

                    self.audio_queue.put(transcript)

                    # Restore volume if we took a duck snapshot but the gate
                    # expired without ever dispatching a command (e.g. arm →
                    # arm_incomplete → user went silent → gate timed out).
                    if self._eli_duck_snapshot is not None and not self._voice_gate.armed():
                        try:
                            _eli_restore_output(self._eli_duck_snapshot)
                            self._eli_duck_snapshot = None
                            log.debug("[AUDIO_DUCK] Gate expired without dispatch — volume restored")
                        except Exception as _re:
                            log.debug(f"[AUDIO_DUCK][RESTORE_ERROR] {_re}")

                    action, payload, wake = self._voice_gate.classify(transcript)

                    if action == "arm":
                        print(f"🔊 [AUDIO] Wake word detected: '{wake}'")
                        print("🎧 [AUDIO] Guarded command window armed")
                        try:
                            # Only snapshot+duck if not already ducked.
                            # Re-arm (user says wake word twice) must NOT overwrite
                            # the original pre-duck volume with the ducked level.
                            if self._eli_duck_snapshot is None:
                                self._eli_duck_snapshot = _eli_duck_output()
                            else:
                                log.debug("[AUDIO_DUCK] Already ducked — keeping existing snapshot")
                        except Exception as e:
                            log.debug(f"[AUDIO_DUCK][ERROR] {e}")
                        continue

                    if action == "arm_incomplete":
                        print(f"🔄 [AUDIO] Waiting for command target...")
                        # Keep listening — volume already ducked, window already armed
                        continue

                    if action == "guarded_without_wake":
                        print("⚠️ [AUDIO] guarded — wake word required", flush=True)
                        continue

                    if action == "ignore_unarmed":
                        print("🫥 [AUDIO] ignored — no wake word", flush=True)
                        continue

                    if action == "ignore_too_short":
                        print(
                            f"🫥 [AUDIO] ignored — too short "
                            f"({_word_count(transcript)} words, need {MIN_DIRECT_CHAT_WORDS})",
                            flush=True,
                        )
                        continue

                    if action == "ignore":
                        continue

                    if action == "dispatch" and payload:
                        self._emit(payload)
                        continue
        finally:
            try:
                _tts_mon_stop.set()
            except Exception:
                pass
            with self._state_lock:
                self.is_listening = False
                self._thread = None


_AUDIO_STT: Optional[ELIAudioSTT] = None


def get_audio_stt():
    global _AUDIO_STT
    if _AUDIO_STT is None:
        _AUDIO_STT = ELIAudioSTT()
    return _AUDIO_STT


def _get_recognizer():
    """Return the active sr.Recognizer if STT is running, else None."""
    if _AUDIO_STT is not None:
        return _AUDIO_STT.recognizer
    return None


def start_audio_listening(callback=None):
    try:
        get_audio_stt().start_listening(callback)
        return True
    except Exception as e:
        log.debug(f"[STT] start failed: {e}")
        return False


def stop_audio_listening():
    global _AUDIO_STT
    if _AUDIO_STT is not None:
        _AUDIO_STT.stop_listening()
    return True


def listen_for_command(timeout=5):
    try:
        return get_audio_stt().listen_once(timeout)
    except Exception:
        return ""

# Noise-alias hardening: block dangerous false-positive aliases
# Keep useful normalisation, but block dangerous garbage aliases such as:
#   "valium up" / "value mode" / "follow him up" -> "volume up"
# Those are common background/TV/music false positives and should NOT become commands.

_LEGACY_MEDIA_VOICE_ALIAS = globals().get("_media_voice_alias_legacy")

def _audio_compact(text):
    return " ".join(str(text or "").lower().replace("-", " ").replace("_", " ").split())

def _audio_noise_alias(text):
    c = _audio_compact(text)
    exact = {
        "valium up", "valium op", "valium mop", "valiumo", "valiumoth",
        "value up", "value op", "value more", "value mode",
        "volume mode",
        "follow him up", "follow him down", "follow mo", "follow more",
        "vanya mok", "violin up",
        "i'll find you more", "i'll tell you more", "i'll use more",
        "fire them up", "firemup", "for you more",
        "the volume up",
    }
    if c in exact:
        return True
    return any(frag in c for frag in (
        "valium", "follow him", "vanya mok", "violin up"
    ))

def _eli_media_voice_alias(text: str) -> str:
    raw = str(text or "")
    compact = _audio_compact(raw)

    canonical = {
        "volume up": "volume up",
        "volume down": "volume down",
        "vol up": "volume up",
        "vol down": "volume down",
        "mute": "mute",
        "unmute": "unmute",
        "play": "play",
        "pause": "pause",
        "resume": "resume",
        "stop": "stop",
        "next": "next",
        "previous": "previous",
    }

    if compact in canonical:
        mapped = canonical[compact]
        if mapped != raw.strip().lower():
            log.debug(f"[STT_ALIAS] {raw!r} -> {mapped!r}")
        return mapped

    if _audio_noise_alias(raw):
        log.debug(f"[STT_ALIAS_BLOCKED_FINAL] {raw!r} not converted")
        return raw

    if callable(_LEGACY_MEDIA_VOICE_ALIAS):
        try:
            mapped = str(_LEGACY_MEDIA_VOICE_ALIAS(raw) or raw)
            mapped_compact = _audio_compact(mapped)

            if _audio_noise_alias(raw) and mapped_compact in {
                "volume up", "volume down", "mute", "unmute",
                "play", "pause", "resume", "stop", "next", "previous"
            }:
                log.debug(f"[STT_ALIAS_BLOCKED_FINAL] old alias tried {raw!r} -> {mapped!r}")
                return raw

            return mapped
        except Exception as e:
            log.debug(f"[STT_ALIAS_BLOCKED_FINAL] alias error: {e}")
            return raw

    return raw

