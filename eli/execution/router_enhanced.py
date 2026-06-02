# eli/tools/router_enhanced.py
# Deterministic intent router (upgraded)
# Goals:
# - Stable / redistributable / no machine-specific paths
# - Strong URL/path detection
# - Backward compatibility for legacy tests (e.g. STOP_MEDIA)
# - Canonicalized aliases + STT cleanup
# - Route metadata for debugging / future planner integration
# - Deterministic first, "AGI-ready" structure second

from __future__ import annotations

def _eli_pipeline_trace(stage: str, **data):
    try:
        import json, time, os
        from pathlib import Path
        from eli.core.paths import get_paths
        out = Path(get_paths().project_root) / "ops" / "reports" / "pipeline_visibility" / "runtime_pipeline_trace.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.time(), "stage": stage, **data}, ensure_ascii=False, default=str) + "\n")
        # CLI print: silent by default (file write still happens for forensics).
        # Set ELI_PIPELINE_TRACE_VERBOSE=1 to restore the per-call print.
        if os.environ.get("ELI_PIPELINE_TRACE_VERBOSE", "0").lower() in {"1", "true", "yes", "on"}:
            _preview = {k: (v[:60] + "..." if isinstance(v, str) and len(v) > 60 else v) for k, v in data.items()}
            log.debug(f"[PIPELINE_TRACE] {stage} {_preview}")
    except Exception as _e:
        log.debug(f"[PIPELINE_TRACE_ERR] {stage}: {_e}")

def _eli_phase10_is_codebase_audit_request(text: str) -> bool:
    """
    Prevent broad memory-runtime regexes from hijacking codebase audits.
    """
    s = str(text or "").lower()

    audit_words = (
        "audit", "inspect", "scan", "check", "verify", "examine",
        "what is wrong", "what's wrong", "broken", "missing",
    )
    code_words = (
        "router", "executor", "engine", "agent_bus", "world_model",
        "gguf_inference", "orchestrator", "output_governor",
        "output_governer", "response_governance", "response_governence",
        "hyde", "vector_store", "working_memory", "introspection_agent",
        "reranker", "llm_intent", "hardware_profile", "runtime_settings",
        "pipeline", "self_upgrade", "habits_memory_db", "knowledge_graph",
        "memory_adapter", "memory_truth", "memory_service", "sqlite_memory",
        "os_controller", "screen_locator", "log_rotation", "/runtime",
        "python files", ".py", "eli_pro_audio_gui", "router_enhanced",
        "executor_enhanced",
    )

    return any(a in s for a in audit_words) and any(c in s for c in code_words)



import json
import os
import re
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List

# ============================================================
# PRE-COMPILED REGEX — module-level so route() pays zero compile cost.
# Python caches up to 512 recently-used patterns, but 379 inline calls
# still pay a dict-lookup on every invocation; module-level compiled
# patterns bypass the cache lookup entirely.
# ============================================================
_RE_MEDIA_CONTROL = re.compile(
    r"\b(play|pause|stop|resume|next|previous|skip|mute|unmute|volume|repeat|shuffle)\b", re.I)
_RE_OPEN_APP = re.compile(
    r"\b(open|launch|start|run|load)\b.{1,30}\b(app|application|program|browser|terminal|ide|editor)\b",
    re.I)
_RE_MEMORY_QUERY = re.compile(
    r"\b(remember|recall|memory|what do you know|stored|from memory|profile)\b", re.I)
_RE_SELF_AWARE = re.compile(
    r"\b(who are you|what are you|tell me about yourself|your (identity|persona|purpose|capabilities))\b",
    re.I)
_RE_REASONING_MODE = re.compile(r"\breasoning\s+mode", re.I)
_RE_ALL_MODES = re.compile(
    r"\b(all|every|each|how many|list|explain|full|describe|detail|difference|differ|compare"
    r"|what are|tell me about|tell me all|tell me everything|what do|how do"
    r"|modes?\s+you\s+have|modes?\s+does|all.*mode|every.*mode)\b", re.I)
_RE_RUNTIME_AUDIT = re.compile(
    r"\b(audit|inspect|diagnose|scan|what('s| is) wrong|broken|missing|wiring|pipeline)\b", re.I)
_RE_SYSTEM_STATS = re.compile(
    r"\b(cpu|ram|memory usage|disk|gpu|system stats|hardware|uptime|load)\b", re.I)
_RE_CHAT_FILLER = re.compile(
    r"^\s*(ok|okay|yes|no|yeah|nope|sure|thanks|thank you|got it|understood"
    r"|alright|cool|nice|great|fine)\s*[.!?]*\s*$", re.I)
_RE_GROUNDED_PIPELINE = re.compile(
    r"\b(cognition pipeline|input to output|every step|memory system|db tables"
    r"|runtime audit|diagnostic|diagnostics|full audit|fulltime audit|full.time audit"
    r"|system audit|run.*audit|do.*audit|wanna.*audit)\b", re.I)
_RE_URL = re.compile(r"https?://\S+|www\.\S+", re.I)
_RE_SHELL_CMD = re.compile(r"^(sudo|bash|sh|python|pip|apt|dnf|brew|npm|git)\s", re.I)

# Tracks the last successfully resolved filesystem path across router calls
_last_used_path: str | None = None


def _eli_latest_screenshot() -> str | None:
    """Return the path to the most recent screenshot image, or None.

    Searches the user's Pictures dir (where SCREENSHOT saves) and a few common
    fallbacks for the newest screenshot-named image by modification time.
    """
    import glob as _g
    dirs: list[str] = []
    try:
        from eli.utils import platform_compat as _pf
        dirs.append(str(_pf.user_pictures_dir()))
    except Exception:
        pass
    dirs += [
        os.path.expanduser("~/Pictures"),
        os.path.expanduser("~/Pictures/Screenshots"),
        os.path.expanduser("~/Desktop"),
    ]
    candidates: list[str] = []
    seen: set[str] = set()
    for d in dirs:
        if not d or d in seen or not os.path.isdir(d):
            continue
        seen.add(d)
        for pat in ("Screenshot*.png", "Screenshot*.jpg",
                    "*creenshot*.png", "*creenshot*.jpg"):
            candidates.extend(_g.glob(os.path.join(d, pat)))
    if not candidates:
        return None
    try:
        return max(set(candidates), key=lambda p: os.path.getmtime(p))
    except Exception:
        return None


# ============================================================
# STATIC CONFIG
# ============================================================

COMMON_DIRS = {
    "home": "~",
    "desktop": str(Path.home() / "Desktop"),
    "downloads": str(Path.home() / "Downloads"),
    "documents": str(Path.home() / "Documents"),
    "music": str(Path.home() / "Music"),
    "pictures": str(Path.home() / "Pictures"),
    "videos": str(Path.home() / "Videos"),
}

DESKTOP_APP_PRIORITY = {
    "spotify", "steam", "discord", "slack", "code", "vscode", "codium",
    "thunderbird", "paraview", "powerview", "rhythmbox", "vlc", "mpv",
    "totem", "gimp", "inkscape", "blender", "krita", "libreoffice",
    "onlyoffice", "wps", "zoom", "skype", "teams", "telegram", "signal",
    "element", "minecraft", "lutris", "heroic", "retroarch", "obs",
    "obs-studio", "audacity", "shotcut", "kdenlive", "openshot",
    "handbrake", "makemkv", "calibre", "evince", "okular", "qbittorrent",
    "transmission", "deluge", "filezilla", "thunar", "nautilus",
    "dolphin", "pcmanfm", "kitty", "alacritty", "konsole", "gnome-terminal",
    "xfce4-terminal", "terminator", "guake", "yakuake", "dropbox",
    "nextcloud", "owncloud", "syncthing", "kodi", "plex", "jellyfin",
    "emby", "stremio", "anki", "obsidian", "joplin", "typora", "marktext",
    "zotero", "mendeley", "pycharm", "intellij", "webstorm", "phpstorm",
    "android-studio", "eclipse", "netbeans", "sublime", "sublime-text",
    "atom", "emacs", "vim", "nvim", "neovim", "gitk", "gitg", "gitkraken",
    "github-desktop", "postman", "insomnia", "docker", "kubectl", "lens",
    "virtualbox", "vmware", "vagrant", "ansible", "terraform", "packer",
    "qgis", "grass", "rstudio", "jupyter", "jupyter-lab", "spyder",
    "matlab", "octave", "gnuplot", "fritzing", "kicad", "eagle", "freecad",
    "openscad", "solvespace", "celestia", "stellarium", "geogebra",
    "code-oss",
    "firefox", "chrome", "chromium",
    "terminal",
}

WEBSITE_ALIASES = {
    "youtube": "https://youtube.com",
    "google": "https://google.com",
    "facebook": "https://facebook.com",
    "twitter": "https://twitter.com",
    "x": "https://x.com",
    "instagram": "https://instagram.com",
    "linkedin": "https://linkedin.com",
    "reddit": "https://reddit.com",
    "github": "https://github.com",
    "stackoverflow": "https://stackoverflow.com",
    "wikipedia": "https://wikipedia.org",
    "amazon": "https://amazon.com",
    "ebay": "https://ebay.com",
    "netflix": "https://netflix.com",
    "hulu": "https://hulu.com",
    "twitch": "https://twitch.tv",
    "gmail": "https://mail.google.com",
    "outlook": "https://outlook.live.com",
    "yahoo": "https://mail.yahoo.com",
    "maps": "https://maps.google.com",
    "news": "https://news.google.com",
    "weather": "https://weather.com",
}

APP_ALIASES = {
    "codes": "code",
    "code-oss": "code",
    "vs code": "code",
    "visual studio code": "code",
    "term": "x-terminal-emulator",
    "terminal app": "x-terminal-emulator",
    "chrome browser": "chrome",
    "google chrome": "chrome",
    "chromium browser": "chromium",
    "firefox browser": "firefox",
    # Spelling corrections
    "calender": "gnome-calendar",
    "calander": "gnome-calendar",
    "calendar": "gnome-calendar",
    "calandar": "gnome-calendar",
    "settings": "gnome-control-center",
    "setting": "gnome-control-center",
    "calculator": "gnome-calculator",
    "calc": "gnome-calculator",
    "files": "nautilus",
    "file manager": "nautilus",
    "text editor": "gedit",
    "editor": "gedit",
    "system monitor": "gnome-system-monitor",
    "monitor": "gnome-system-monitor",
    "music player": "rhythmbox",
    "image viewer": "eog",
    "photos": "eog",
    "disks": "gnome-disks",
    "disk usage": "baobab",
    "screenshot": "gnome-screenshot",
}

MEDIA_APPS = [
    "spotify",
    "vlc",
    "chrome",
    "firefox",
    "mpv",
    "rhythmbox",
    "audacious",
    "youtube",
    "netflix",
    "soundcloud",
    "primevideo",
    "prime",
    "disneyplus",
    "disney",
    "hulu",
    "twitch",
]


# ============================================================
# LOW-LEVEL HELPERS
# ============================================================

def _eli_weather_prepass(user_text: str):
    low = user_text.lower().strip()
    # Guard: only fire when the sentence is *requesting* weather info.
    # Skip if the user is talking *about* a weather-related topic (e.g.
    # "the script is for a weather forecast", "stop telling me the weather").
    _REQUEST_SIGNALS = re.compile(
        r"\b(?:what(?:'s|s|\s+is|\s+will)?\s+(?:the\s+)?(?:weather|forecast|temperature|temp)|"
        r"how(?:'s|\s+is)\s+(?:the\s+)?weather|"
        r"(?:check|get|tell\s+me|show(?:\s+me)?|give\s+me)\s+(?:the\s+)?(?:weather|forecast|temperature)|"
        r"(?:will\s+it|is\s+it|going\s+to)\s+(?:rain|snow|be\s+(?:hot|cold|warm|sunny|cloudy)))\b",
        re.I)
    # Also allow bare "weather in X" / "weather for X" at the start of input
    _BARE_WEATHER_REQUEST = re.compile(
        r"^(?:weather|forecast|temperature)\b[^.!?]{0,60}\b(?:in|at|for)\s+[A-Za-z]",
        re.I)
    _TOPIC_PHRASES = re.compile(
        r"\b(?:script|code|program|file|function|task|fix|issue|error|this|that|the\s+\w+)\s+"
        r"(?:is|was|are|were|for|about|regarding|related\s+to)\s+(?:a\s+)?(?:weather|forecast|temperature)\b|"
        r"\b(?:stop|don'?t|cease|quit)\b.{0,30}\bweather\b",
        re.I)
    if _TOPIC_PHRASES.search(low):
        return None
    if not _REQUEST_SIGNALS.search(low) and not _BARE_WEATHER_REQUEST.search(low):
        return None
    m = re.search(
        r"(?:weather|forecast|temperature).{0,40}?(?:in|at|for) ([A-Za-z][A-Za-z ,]+?)(?:\?|$|[,;]|\band\b)",
        user_text,
        re.I)
    if m:
        loc = m.group(1).strip().rstrip("?.!, ")
        return {
            "action": "GET_WEATHER",
            "args": {"location": loc, "_raw_user_text": user_text},
            "confidence": 0.97,
            "meta": {"matched_by": "weather.prepass", "entities": {"location": loc}},
        }
    return None


_SHELL_PREPASS_CMDS = {
    "ls", "cd", "pwd", "cat", "head", "tail", "grep", "find", "wc",
    "date", "df", "du", "free", "top", "ps", "kill", "chmod", "chown",
    "cp", "mv", "rm", "mkdir", "rmdir", "touch", "echo", "which", "whoami",
    "uname", "uptime", "hostname", "ip", "ifconfig", "ping", "curl", "wget",
    "tar", "zip", "unzip", "apt", "pip", "npm", "git", "docker", "systemctl",
    "python", "python3", "bash", "sh", "env", "export", "source", "less", "more",
}


def _eli_shell_prepass(user_text: str):
    """Early-stage shell command detector — fires before OPEN_APP can steal 'run X'."""
    import re as _re
    m = _re.match(r"^\s*(?:run|execute)\s+(\S+(?:\s+.*)?)$", user_text.strip(), _re.I)
    if m:
        parts = m.group(1).strip().split()
        if parts and parts[0].lower() in _SHELL_PREPASS_CMDS:
            cmd = m.group(1).strip()
            return {
                "action": "SHELL_EXEC",
                "args": {"cmd": cmd},
                "confidence": 0.95,
                "meta": {"matched_by": "shell.prepass"},
            }
    return None


def _mk(
    action: str,
    args: Optional[Dict[str, Any]] = None,
    confidence: float = 0.7,
    *,
    matched_by: Optional[str] = None,
    entities: Optional[Dict[str, Any]] = None,
    need_grounding: Optional[bool] = None,
    required_capabilities: Optional[List[str]] = None,
    allow_chat_without_evidence: Optional[bool] = None,
    task_family: Optional[str] = None,
) -> Dict[str, Any]:
    """Canonical route object with debug/planner metadata."""
    out = {
        "action": action,
        "args": args or {},
        "confidence": float(max(0.0, min(1.0, confidence))),
    }
    meta: Dict[str, Any] = {}
    if matched_by:
        meta["matched_by"] = matched_by
    if entities:
        meta["entities"] = entities
    if need_grounding is not None:
        meta["need_grounding"] = bool(need_grounding)
    if required_capabilities:
        meta["required_capabilities"] = list(required_capabilities)
    if allow_chat_without_evidence is not None:
        meta["allow_chat_without_evidence"] = bool(allow_chat_without_evidence)
    if task_family:
        meta["task_family"] = task_family
    if meta:
        out["meta"] = meta
    return out


def _normalize_text(text: str) -> Tuple[str, str]:
    """
    Returns (raw_clean, low_clean)
    Removes weird whitespace/control chars that can break regexes.
    """
    raw = (text or "")
    raw = raw.replace("\u200b", " ").replace("\ufeff", " ")
    raw = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", raw)  # strip control chars
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw, raw.lower()


def _clean_app_name(s: str) -> str:
    s = s.strip()
    s = re.sub(r'^(?:the|my|a|an)\s+', '', s, flags=re.I)
    s = re.sub(r'^(?:application|app)\s+', '', s, flags=re.I)
    s = re.sub(r'\s+located.*$', '', s, flags=re.I).strip()
    s = APP_ALIASES.get(s.lower(), s)
    return s


def _is_likely_url(s: str) -> bool:
    """
    Detects URLs and bare domains (google.com, www.x.y, foo.io/bar).
    Avoids false positives for local files when possible.
    """
    s = s.strip().lower()
    if not s:
        return False

    if s.startswith(("http://", "https://", "www.")):
        return True

    # domain.tld[/...]
    # conservative but broad enough for practical routing
    if re.match(r"^(?:[a-z0-9-]+\.)+[a-z]{2,24}(?:[:/].*)?$", s):
        return True

    return False


def _normalize_url(s: str) -> str:
    s = s.strip()
    if s.lower().startswith(("http://", "https://")):
        return s
    if s.lower().startswith("www."):
        return f"https://{s}"
    if _is_likely_url(s):
        return f"https://{s}"
    return s


def _is_likely_path(s: str) -> bool:
    s = s.strip()
    if not s:
        return False

    # URL check first to avoid "google.com" becoming a file
    if _is_likely_url(s):
        return False

    if s.startswith(("./", "../", "~", "/")):
        return True

    if "/" in s or "\\" in s:
        return True

    if s.lower() in COMMON_DIRS:
        return True

    # file.ext style
    if "." in s:
        ext = s.rsplit(".", 1)[-1]
        if ext.isalpha() and 1 <= len(ext) <= 8:
            return True

    keywords = {
        "directory", "folder", "file", "path", "location",
        "desktop", "documents", "downloads", "music", "pictures", "videos"
    }
    toks = set(re.findall(r"[a-zA-Z]+", s.lower()))
    if toks & keywords:
        return True

    return False


def _expand_common_dir(s: str) -> str:
    key = s.strip()

    # If already a full/home path, just expand ~ and return
    if key.startswith(("~", "/", "./")):
        return str(Path(key).expanduser())

    low = re.sub(r'^(?:the|my|a|an)\s+', '', key.lower()).strip()

    for dirname, path in COMMON_DIRS.items():
        if re.search(rf"\b{re.escape(dirname)}\b", low):
            rest = re.sub(rf"\b{re.escape(dirname)}\b", "", low).strip()
            rest = re.sub(r"\b(?:folder|directory|dir|files?|contents?)\b", "", rest).strip()
            # Clean leftover slashes/dots
            rest = rest.strip("/. ")
            if rest:
                return str(Path(path).expanduser() / rest)
            return str(Path(path).expanduser())

    return COMMON_DIRS.get(low, str(Path(key).expanduser()))


def _extract_path_from_text(raw: str) -> Optional[str]:
    # Remove common command prefixes like "file", "in", etc.
    raw = re.sub(
        r'^(?:fix|read|show|open|list)\s+(?:file|directory)?\s*',
        '',
        raw,
        flags=re.IGNORECASE)
    raw = re.sub(r'\s+in\s+', ' ', raw)  # "file in /path" -> "/path"
    patterns = [
        r'([~/][\w.\- /]+(?:\.\w+)?)',
        r'(\./[\w.\- /]+(?:\.\w+)?)',
        r'(\.\./[\w.\- /]+(?:\.\w+)?)',
        r'([\w.\-]+/\S+)',
        r'([A-Za-z0-9_.-]+\.(?:py|txt|md|json|yaml|yml|csv|pdf|log|ini|cfg|toml|sh))',
    ]
    for p in patterns:
        m = re.search(p, raw)
        if m:
            return m.group(1).strip()
    return None



def _extract_pdf_paths(raw: str) -> list[str]:
    """
    Robust PDF path extractor.

    Fixes the old bug where:
        <path-to-pdf-file>
    became:
        /File.pdf

    Supports:
    - absolute paths
    - ~/ paths
    - ./ and ../ paths
    - multiple PDFs in one prompt
    - basename fallback search for bracketed PDF-content prompts
    """
    import os
    import re
    from pathlib import Path

    text = str(raw or "")
    # ELI PATCH: correct common STT errors
    if 'taste' in text and ('today' in text or 'now' in text):
        text = text.replace('taste','date')
    found: list[str] = []

    full_path_re = re.compile(
        r'(?P<path>(?:~|/|\.{1,2}/)[^\n\r\t"\'<>]*?\.pdf)\b',
        re.IGNORECASE,
    )

    for m in full_path_re.finditer(text):
        p = m.group("path").strip()
        p = p.strip(" ,.;:)]}>")
        p = os.path.abspath(os.path.expanduser(p))
        found.append(p)

    # Basename fallback for prompts like:
    #   [PDF content — Exergetic_Coherence_Revoloution.pdf]
    # Only used to help route; executor still verifies existence.
    name_re = re.compile(r'(?P<name>[A-Za-z0-9_. -]+\.pdf)\b', re.IGNORECASE)
    roots = [
        Path.cwd(),
        Path.home(),
        Path.home() / "Desktop",
        Path.home() / "Desktop/Physics",
        Path.home() / "Desktop/Physics/Theory_MATHEMATICS",
    ]

    for m in name_re.finditer(text):
        name = m.group("name").strip().strip(" ,.;:)]}>")
        if any(Path(x).name == name for x in found):
            continue

        # If user supplied only a basename, try known local roots.
        for root in roots:
            if not root.exists():
                continue
            try:
                direct = root / name
                if direct.exists():
                    found.append(str(direct.resolve()))
                    break

                # Keep this bounded to likely user document locations.
                matches = list(root.rglob(name))
                if matches:
                    found.append(str(matches[0].resolve()))
                    break
            except Exception:
                continue

    deduped: list[str] = []
    seen: set[str] = set()
    for p in found:
        if p not in seen:
            seen.add(p)
            deduped.append(p)

    return deduped


def _extract_pdf_path(raw: str) -> Optional[str]:
    """
    Backward-compatible single-PDF wrapper.
    Prefer _extract_pdf_paths() for new routing.
    """
    paths = _extract_pdf_paths(raw)
    return paths[0] if paths else None


def _extract_int(raw: str, default: int, min_value: int,
                 max_value: int) -> int:
    m = re.search(r'(\d+)', raw)
    if not m:
        return default
    n = int(m.group(1))
    return max(min_value, min(max_value, n))


def _canonical_media_command(low: str) -> Optional[str]:
    # Specific ordering matters
    if "unmute" in low:
        return "unmute"
    if "mute" in low:
        return "mute"
    if "pause" in low or re.search(r"\bstop\b", low):
        return "pause"  # generic media stop often means pause
    if "resume" in low or re.search(r"\bplay\b", low):
        return "play"
    if "next" in low or "skip" in low:
        return "next"
    if "previous" in low or "prev" in low or re.search(r"\bback\b", low):
        return "previous"
    if "shuffle" in low:
        return "shuffle"
    if "repeat" in low:
        return "repeat"
    return None


def _is_time_recall_query(raw: str, low: str) -> bool:
    patterns = [
        r"\bwhat did (?:we|i|you) (?:discuss|talk|say|mention)\b",
        r"\bwhat was (?:the )?last (?:thing|topic|subject|conversation)\b",
        r"\b(?:an?\s+hour\s+ago|earlier today|this morning|yesterday)\b",
        r"\bwhat did i (?:say|ask|tell you)\b",
    ]
    return any(re.search(p, low) for p in patterns)


def _looks_like_conversation_summary(low: str) -> bool:
    return any(re.search(p, low) for p in [
        r"^summari[sz]e\s+(?:the\s+)?(?:conversation|chat|discussion|what we talked about)",
        r"^summari[sz]e\s+(?:the\s+)?last\s+\d+\s+(?:messages|conversations|turns)",
    ])


# ============================================================
# ROUTER
# ============================================================
def _route_set_user_name(raw: str, low: str) -> Optional[Dict[str, Any]]:
    """Detect explicit name-setting statements and route to SET_USER_NAME."""
    import re as _re

    # Negation guard: bail immediately on "my name is NOT", "my name isn't",
    # "that is not my name", "not my name", "I am not", etc.
    _negation_patterns = (
        r"\bmy name is(?:n't| not)\b",
        r"\bmy name isn't\b",
        r"\bnot my name\b",
        r"\bthat(?:'s| is) not my name\b",
        r"\bdon't call me\b",
        r"\bdo not call me\b",
        r"\bi am not\b",
        r"\bi'm not\b",
        r"\bmy name is not\b",
        # "User is not my name" / "X is not my name"
        r"\bis not my name\b",
        # "that's not my name" / "that is not my name"
        r"\bthat(?:'?s?|\s+is)\s+not\s+my\b",
        # "stop calling me X" / "don't call me X"
        r"\bstop calling me\b",
        # Questions/references about what ELI calls the user are NOT name-set
        # commands: "why did you call me speak", "you called me X", "what did
        # you call me". Bail so they fall through to CHAT.
        r"\byou\s+call(?:ed)?\s+me\b",
        r"\b(?:why|what|when|who|how|did|do|does)\b[^.?!]*\bcall(?:ed)?\s+me\b",
    )
    for _npat in _negation_patterns:
        if _re.search(_npat, low, _re.IGNORECASE):
            return None

    # "my name is X", "call me X", "i'm X" / "i am X" (followed by end or punctuation)
    _patterns = (
        r"(?:my name is|my name's)\s+([A-Za-z][A-Za-z\-']{1,30})\b",
        r"call me\s+([A-Za-z][A-Za-z\-']{1,30})\b",
        r"(?:you can call me|please call me)\s+([A-Za-z][A-Za-z\-']{1,30})\b",
        r"^(?:i'?m|i am)\s+([A-Z][a-z]{2,24})\s*[.,!?]?\s*$",
        # Bare name as full message: require actual uppercase first char (typed, not STT-lowercased)
        r"^([A-Z][a-z]{3,24})\s*[.,!?]?\s*$",
    )
    # Common words / abbreviations that must never be treated as names.
    _bad = {"you", "eli", "okay", "ok", "sure", "fine", "good", "here",
            "yes", "no", "hi", "hey", "hello", "there", "done", "ready",
            "sorry", "thanks", "thank", "great", "right", "wrong", "not",
            # Media control reserved words — must never become a name
            "play", "pause", "resume", "stop", "next", "skip", "back",
            "previous", "mute", "unmute", "louder", "quieter", "volume",
            "shuffle", "repeat", "rewind", "forward", "restart",
            # Voice/system reserved words
            "start", "go", "cancel", "abort", "quit", "exit", "close",
            "open", "search", "find", "show", "hide", "run", "launch",
            # Command keywords — must never become a user name
            "help", "commands", "command", "list", "check", "status",
            "info", "about", "what", "when", "where", "who", "why", "how",
            # Common English words that STT might produce as single-word utterances
            "port", "read", "write", "note", "chat", "call", "ping", "send",
            "move", "copy", "load", "save", "take", "make", "time", "date",
            "week", "test", "demo", "data", "text", "file", "code", "mode",
            "this", "that", "with", "from", "into", "just", "also", "only",
            "more", "less", "most", "very", "some", "none", "both", "each",
            "then", "than", "when", "well", "will", "been", "have", "does",
            "done", "used", "like", "want", "need", "make", "knew", "know",
            "told", "tell", "said", "says", "came", "come", "goes", "went",
            "seem", "seen", "been", "gave", "give", "took", "take", "keep",
            # Common abbreviations / acronyms — never a personal name
            "eta", "ata", "ota", "asap", "fyi", "btw", "tbd", "tba",
            "aka", "tldr", "diy", "imo", "imho", "afk", "brb", "wtf",
            "omg", "lol", "idk", "nvm", "tbh", "irl", "gg", "rn",
            "api", "gui", "cli", "url", "cpu", "gpu", "ram", "ssd",}

    for i, pat in enumerate(_patterns):
        # Use the LAST occurrence: "my name is speak, my name is jason" must
        # resolve to the final assertion (jason), not a quoted earlier error.
        _matches = list(_re.finditer(pat, raw, _re.IGNORECASE))
        m = _matches[-1] if _matches else None
        if m:
            candidate = m.group(1).strip().rstrip(".,!?")
            _clow = candidate.lower()
            _has_vowel = any(c in "aeiou" for c in _clow)
            # Bare-word pattern (index 4): require actual uppercase first letter in raw text.
            # STT produces all-lowercase; a typed name would be capitalised.
            if i == 4 and (not raw or not raw[0].isupper()):
                continue
            if _clow not in _bad and len(candidate) >= 3 and _has_vowel:
                return _mk(
                    "SET_USER_NAME",
                    {"name": candidate},
                    0.97,
                    matched_by="identity.set_user_name",
                )
    return None


def _route_grounded_runtime_intent(
        raw: str, low: str) -> Optional[Dict[str, Any]]:
    if not raw:
        return None

    # ── Identity / personality questions → CHAT (clean fixed) ───────
    _identity_phrases = (
        "who are you", "what are you", "tell me about yourself",
        "who do you think you are", "what is your purpose", "what do you want",
        "what is your name", "what's your name"
    )

    _memory_system_keywords = (
        "db", "database", "sqlite", "memory system",
        "cognition", "pipeline", "runtime"
    )

    _is_identity = any(p in low for p in _identity_phrases)
    _has_system_kw = any(k in low for k in _memory_system_keywords)

    if re.search(r"\b(what are you actually running on|running on right now|model|context size|gpu layers|threads|batch|provider)\b", raw, re.I):
        return _mk("CHAT", {"message": raw}, 0.99, matched_by="runtime.status.identity_grounded_chat", allow_chat_without_evidence=False)

    # identity precedence
    # Pure persona/character questions go to CHAT so ELI answers from its own
    # voice and memory. SELF_REPORT is reserved for *technical* runtime queries
    # (model path, gpu layers, provider, context size) — not "who are you".
    if re.search(r"\b(who are you|what are you(?!\s+\w)|what is your name|what's your name|tell me about yourself)\b", raw, re.I):
        return _mk("CHAT", {"message": raw}, 0.99, matched_by="identity.persona_chat", allow_chat_without_evidence=True)

    if re.search(
        r"\b(who am i|do you know who i am|do you know me|do you remember me|"
        r"what is my name|what('s| is) my name|what do you know about me|"
        r"you do not know who i am|you don'?t know who i am|"
        r"don'?t you know who i am|don'?t you know me|"
        r"you don'?t know me|you have no idea who i am)\b",
        raw, re.I
    ):
        return _mk("USER_IDENTITY_SUMMARY", {}, 0.99, matched_by="identity.user_summary_preempt", allow_chat_without_evidence=False)

    # Last-turn trace questions require retrieval + live _prev_bus_result
    # injection. Routing to COGNITION_STATUS returned static source-code line
    # numbers as evidence and caused the 7B to confabulate confidence/agent
    # values. CHAT lets stages 3-11 engage and the persona handoff splice in
    # the real prior-turn AgentBus metadata.
    if re.search(r"\b(confidence in (?:your|my) last response|which agents contributed|what agents contributed|agents contributed|grounded trace|trace metadata|last turn trace|previous response trace)\b", raw, re.I):
        return _mk("EXPLAIN_LAST_RESPONSE", {}, 0.99,
                   matched_by="router.explain_last_response",
                   allow_chat_without_evidence=False)

    if _is_identity and not _has_system_kw:
        return _mk("CHAT", {"message": raw}, 0.95, matched_by="identity.chat_classified")


def _route_plugin_bridge_prepass(raw: str, low: str):
    """
    High-priority plugin routing prepass.

    This must run before broad runtime/status routing because phrases like
    "system stats" and "say system check complete" otherwise get stolen by
    generic status/identity rules.
    """
    # Web plugin: explicit only. Generic "search for X" stays browser-routed.
    _web_m = re.match(
        r"^(?:web\s+search|search\s+the\s+web\s+for|search\s+online\s+for|online\s+search\s+for|internet\s+search\s+for)\s+(.+)$",
        raw,
        re.I,
    )
    if _web_m:
        query = _web_m.group(1).strip()
        if query:
            return _mk("WEB_SEARCH", {"query": query}, 0.98, matched_by="plugin.prepass.web_search",
                       entities={"query": query})

    # TTS plugin: must beat runtime/status rules when spoken text contains "system".
    _speak_m = re.match(
        r"^(?:speak|say|read\s+aloud|tts)\s+(.+)$",
        raw,
        re.I,
    )
    if _speak_m:
        text_to_say = _speak_m.group(1).strip()
        if text_to_say:
            return _mk("SPEAK", {"text": text_to_say}, 0.98, matched_by="plugin.prepass.tts_speak",
                       entities={"text": text_to_say})

    # System stats plugin: must beat generic runtime/status routing.
    if re.match(r"^(?:system\s+stats|system\s+statistics|resource\s+usage|show\s+system\s+stats)$", low):
        return _mk("SYSTEM_STATS", {}, 0.98, matched_by="plugin.prepass.system_stats")

    if re.match(r"^(?:cpu\s+usage|processor\s+usage|show\s+cpu\s+usage|how\s+busy\s+is\s+the\s+cpu)$", low):
        return _mk("CPU_USAGE", {}, 0.98, matched_by="plugin.prepass.cpu_usage")

    if re.match(r"^(?:ram\s+usage|memory\s+usage|show\s+ram\s+usage|show\s+memory\s+usage|how\s+much\s+ram\s+is\s+used)$", low):
        return _mk("RAM_USAGE", {}, 0.98, matched_by="plugin.prepass.ram_usage")

    # Pomodoro plugin.
    if re.match(r"^(?:start\s+pomodoro|begin\s+pomodoro|pomodoro\s+start)(?:\s+timer)?$", low):
        return _mk("POMODORO_START", {}, 0.98, matched_by="plugin.prepass.pomodoro_start")

    if re.match(r"^(?:stop\s+pomodoro|end\s+pomodoro|cancel\s+pomodoro|pomodoro\s+stop)$", low):
        return _mk("POMODORO_STOP", {}, 0.98, matched_by="plugin.prepass.pomodoro_stop")

    if re.match(r"^(?:pomodoro\s+status|show\s+pomodoro|pomodoro)$", low):
        return _mk("POMODORO_STATUS", {}, 0.96, matched_by="plugin.prepass.pomodoro_status")

    # Notes plugin.
    _new_note_m = re.match(
        r"^(?:new\s+note|create\s+note|write\s+note)\s+(.+)$",
        raw,
        re.I,
    )
    if _new_note_m:
        note_text = _new_note_m.group(1).strip()
        if note_text:
            return _mk("NEW_NOTE", {"text": note_text, "content": note_text}, 0.98,
                       matched_by="plugin.prepass.notes_new", entities={"text": note_text})

    _search_notes_m = re.match(
        r"^(?:search\s+notes\s+for|find\s+note\s+about|find\s+notes\s+about|search\s+my\s+notes\s+for)\s+(.+)$",
        raw,
        re.I,
    )
    if _search_notes_m:
        query = _search_notes_m.group(1).strip()
        if query:
            return _mk("SEARCH_NOTES", {"query": query}, 0.98, matched_by="plugin.prepass.notes_search",
                       entities={"query": query})

    if re.match(r"^(?:list\s+notes|show\s+notes|show\s+my\s+notes|notes\s+list)$", low):
        return _mk("LIST_NOTES", {}, 0.98, matched_by="plugin.prepass.notes_list")

    # Smart-home plugin.
    _smart_m = re.match(
        r"^(?:smart\s+home|home\s+automation)\s+(.+)$",
        raw,
        re.I,
    )
    if _smart_m:
        command = _smart_m.group(1).strip()
        if command:
            return _mk("SMART_HOME", {"command": command, "text": command}, 0.97,
                       matched_by="plugin.prepass.smart_home", entities={"command": command})

    return None



# === ELI non-Quick/meta-continuity routing contract v1 ===
def _eli_meta_continuity_probe(text: str) -> bool:
    t = (text or "").lower()
    return any(x in t for x in (
        "short answer", "short answers", "terribly short", "what is with",
        "what's with", "where is your continuity", "continuity", "awareness",
        "memory", "lobotom", "constitutional", "reasoning mode", "quick mode",
        "fallback", "orchestration", "pipeline", "why did you", "what the fuck",
    ))
# === END ELI non-Quick/meta-continuity routing contract v1 ===

def _eli_react_to_content_prepass(original_text: str, raw: str, low: str):
    """Force CHAT when the user asks ELI to react to / give an opinion on text
    they have pasted or referenced.

    Quoted material must never be scanned for status/command intent: the words
    inside a pasted block belong to the thing being judged, not to an
    instruction. Without this, a long paste that happens to mention ELI's
    internals ("memory", "faiss", "runtime", "context") trips a status regex
    and the turn is hijacked into a deterministic data dump instead of an
    actual reply. Routing to CHAT with the full (whitespace-normalised) text as
    the message also guarantees the referenced content is present in the prompt
    so the model can genuinely evaluate it rather than confabulate.
    """
    if not low:
        return None
    react_frame = re.search(
        r"\b(what(?:'s| is| do| are)?\s+(?:you|your)\s+(?:think|reckon|make|take|opinion|view|thoughts?)"
        r"|what do you (?:think|reckon|make) of"
        r"|your (?:thoughts?|opinion|take|view)\b"
        r"|thoughts on\b"
        r"|respond to\b|react to\b|reply to\b"
        r"|the following (?:reply|response|message|text|paragraph)"
        r"|this (?:reply|response|message|paste|text)\b"
        r"|(?:reply|response|message|text) (?:from|by) \w+"
        r"|i (?:just )?(?:sent|pasted|posted|shared|wrote)\b"
        r"|(?:message|reply|response|text) (?:above|earlier)\b"
        r"|(?:above|earlier) (?:message|reply|response)\b"
        r"|read (?:this|the following)\b)",
        low,
    )
    if not react_frame:
        return None
    src = original_text or ""
    has_paste = ("-->" in src) or (src.count("\n") >= 2) or (len(src) > 600)
    points_at_content = bool(re.search(
        r"\b(the following|this (?:reply|response|message|paste|text)"
        r"|(?:reply|response|message|text) (?:from|by) \w+"
        r"|i (?:just )?(?:sent|pasted|posted|shared)"
        r"|above|earlier|claude|chatgpt|gpt|that (?:reply|response|message))\b",
        low,
    ))
    if not (has_paste or points_at_content):
        return None
    return _mk(
        "CHAT",
        {"message": raw},
        0.9,
        matched_by="chat.react_to_pasted_content",
    )


def _eli_web_lookup_prepass(raw: str, low: str):
    """Route real-time factual lookups and explicit web searches to WEB_SEARCH
    when networking is enabled.

    Without this, 'search for X', 'when is X out', 'release date of X',
    'latest news on X' fell through to CHAT and were answered from the model's
    stale training weights — and ELI would then argue with the user about
    current facts it cannot actually know. Gated on network_allowed(): offline
    mode returns None (stays CHAT) so the persona can say it cannot check live
    rather than confabulate.
    """
    if not low:
        return None
    # Never hijack ELI-internal / self / memory introspection or media control.
    if re.search(r"\b(my|your|you)\b.{0,30}\b(memory|memories|remember|stored|profile|runtime|cognition|capabilit|status|identity|persona)", low):
        return None
    if re.match(r"^(play|pause|resume|stop|next|previous|open|close|volume|mute|unmute)\b", low):
        return None
    # Local notes search/list is SEARCH_NOTES/LIST_NOTES, not a web lookup.
    if re.search(r"\b(search|find|list|show|read|open)\s+(?:my\s+|the\s+)?notes?\b", low):
        return None
    # "news" has a dedicated NEWS_FETCH path — let core_router handle it.
    if re.search(r"\bnews\b", low):
        return None

    explicit_search = re.search(
        r"\b(search\s+(?:the\s+)?(?:web|internet|online)|search\s+for|search\b|"
        r"look\s+(?:it|this|that)?\s*up|google\b|"
        r"check\s+the\s+(?:internet|web|online)|find\s+out)\b",
        low,
    )
    realtime_fact = re.search(
        r"\b(when\b.{0,45}\b(out|air|airs|airing|aired|release|released|releasing|"
        r"premier|premiere|coming\s+out|due|drop|drops)"
        r"|(?:season|episode|movie|film|game|album|series)\b.{0,30}\b(out|air|airing|"
        r"release|released|coming|drop|when)"
        r"|release\s+date|what'?s\s+the\s+latest|current\s+(?:price|score)"
        r"|who\s+won|how\s+much\s+is|is\s+.+\s+out\s+yet)\b",
        low,
    )
    if not (explicit_search or realtime_fact):
        return None

    try:
        from eli.core.config import network_allowed
        if not network_allowed():
            return None  # offline: stay CHAT; persona explains it can't check live
    except Exception:
        return None

    query = raw
    m = re.match(
        r"^(?:can\s+you\s+|could\s+you\s+|please\s+|hey\s+)?(?:do\s+a\s+|run\s+a\s+)?"
        r"(?:web\s+search|search\s+the\s+web\s+for|search\s+online\s+for|"
        r"search\s+the\s+internet\s+for|search\s+for|search|look\s+up|google|"
        r"find\s+out|check\s+the\s+internet\s+for|check\s+the\s+web\s+for)\s+(.+)$",
        raw, re.I,
    )
    if m and m.group(1).strip():
        query = m.group(1).strip()
    query = re.sub(r"\b(for me|please|now|on the internet|online)\b\.?$", "", query, flags=re.I).strip(" .?!")
    if not query:
        query = raw.strip()
    return _mk("WEB_SEARCH", {"query": query}, 0.92,
               matched_by="web.realtime_lookup", entities={"query": query})


def route(text: str) -> Dict[str, Any]:

    raw, low = _normalize_text(text)
    text_l = low  # compatibility alias for legacy route guards
    _plugin_prepass = _route_plugin_bridge_prepass(raw, low)
    if _plugin_prepass is not None:
        return _plugin_prepass

    # React-to-pasted-content guard: opinion/evaluation requests over quoted or
    # referenced text are conversational. Run before any status/grounding regex
    # so quoted ELI-internal vocabulary can't hijack the turn into a data dump.
    _react_prepass = _eli_react_to_content_prepass(text, raw, low)
    if _react_prepass is not None:
        return _react_prepass



    # --- primary contract diagnostics: proof / latency / inference ---
    # These are not casual chat. They require grounded runtime/file evidence.
    # This block belongs inside the primary route() function, not as an
    # end-of-file wrapper around route().
    if re.search(
        r"\b(prove|proof|timestamp|timestamps|data|scanned|actually scanned|read the file|read in full)\b",
        low,
    ) and re.search(
        r"\b(gui|file|audit|scan|read)\b",
        low,
    ):
        return _mk(
            "GUI_RUNTIME_AUDIT",
            {
                "question": raw,
                "proof_requested": True,
                "audit_depth": "proof",
            },
            0.995,
            matched_by="router.primary_contract_diagnostics.gui_audit_proof",
            need_grounding=True,
            allow_chat_without_evidence=False,
            task_family="grounded_audit",
        )

    if re.search(
        r"\b(took you|took so long|why did you take|response time|slow response|that took ages|20 minutes|twenty minutes|you don't believe me|dont believe me|took over|took nearly|took just under)\b",
        low,
    ):
        return _mk(
            "EXPLAIN_COGNITION_RUNTIME",
            {
                "question": raw,
                "diagnostic_focus": "latency_timing",
            },
            0.995,
            matched_by="router.primary_contract_diagnostics.latency_timing",
            need_grounding=True,
            allow_chat_without_evidence=False,
            task_family="grounded_audit",
        )

    if re.search(
        r"\b(current inference|inference issues|gguf issues|prompt overflow|context overflow|context window|sacrificing reasoning|sacrifice reasoning|model slow|llama slow|gpu_layers|gpu layers|max_tokens|n_ctx|batch size|llama_context)\b",
        low,
    ):
        return _mk(
            "EXPLAIN_COGNITION_RUNTIME",
            {
                "question": raw,
                "diagnostic_focus": "inference_runtime",
            },
            0.995,
            matched_by="router.primary_contract_diagnostics.inference_runtime",
            need_grounding=True,
            allow_chat_without_evidence=False,
            task_family="grounded_audit",
        )
    # --- end primary contract diagnostics ---


    # --- primary contract diagnostics: self-report recent updates ---
    # Questions about what checks/updates ELI performed are not casual chat.
    # They must route to grounded self-report evidence, otherwise GGUF invents
    # plausible maintenance activity.
    if re.search(
        r"\b(what|which|any|show|tell|list)\b.{0,80}\b(updates?|checks?|repairs?|changes?|maintenance|work)\b.{0,80}\b(as of late|recently|lately|performed|done|happened|made)\b",
        low,
    ) or re.search(
        r"\b(what have you been doing|what have you been working on|what have you checked|what have you updated)\b",
        low,
    ):
        return {
            "action": "SELF_REPORT",
            "args": {
                "question": raw,
                "self_report_scope": "recent_updates",
            },
            "confidence": 0.995,
            "meta": {
                "matched_by": "router.primary_contract_diagnostics.self_report_recent_updates",
                "need_grounding": True,
                "allow_chat_without_evidence": False,
                "task_family": "self_report_runtime",
                "forbid_chat_fallback": True,
                "forbid_fake_update_claims": True,
            },
        }
    # --- end primary contract diagnostics: self-report recent updates ---

    # --- strict control actions: never fall through to generic CHAT ---    # ELI_PATCH_PERSONAL_MEMORY_ROUTE_PRECEDENCE_20260511
    # Personalised/internal-memory questions must beat the generic memory-runtime route.
    # This is routing precedence only; final response synthesis remains downstream.
    _pm_text = low  # `low` is always defined: low = raw.lower()
    if (
        ("memory" in _pm_text)
        and (
            "personal" in _pm_text
            or "personalised" in _pm_text
            or "personalized" in _pm_text
            or "about me" in _pm_text
            or "my memory" in _pm_text
            or "internals" in _pm_text
            or "internally" in _pm_text
            or "which files" in _pm_text
            or "which db" in _pm_text
            or "which tables" in _pm_text
            or "which functions" in _pm_text
        )
    ):
        return {
            "action": "PERSONAL_MEMORY_DEEP_EXPLAIN",
            "confidence": 0.99,
            "source": "router.personal_memory_precedence",
            "reason": "personalised/internal memory explanation must not be captured by generic memory runtime route",
            "query": text if 'text' in locals() else (_pm_text or ""),
        }

    if re.fullmatch(r"(?:self[- ]?update|update yourself|refresh yourself|refresh all overlays)", low):
        return _mk("SELF_UPDATE", {}, 0.99, matched_by="router.self_update", allow_chat_without_evidence=False)

    if re.search(r"\b(confidence in (?:your|my) last response|which agents contributed|what agents contributed|last response trace|previous response trace|last turn trace)\b", low):
        return _mk("EXPLAIN_LAST_RESPONSE", {}, 0.99, matched_by="router.explain_last_response", allow_chat_without_evidence=False)

    # --- explicit grounded speech-act route authority ---
    # This is routing authority, not a canned response layer.
    if re.search(r"\b(i did not ask|i didn't ask|not what i asked|that's not what i asked|that is not what i asked)\b", low):
        return _mk("CHAT", {"message": raw}, 0.92, matched_by="router.correction_chat", allow_chat_without_evidence=True)

    if re.search(r"\b(who are you|what are you|what is your name|what's your name)\b", low) and re.search(
        r"\b(running on|model|context size|gpu layers|threads|batch|provider|runtime)\b",
        low,
    ):
        return _mk("SELF_REPORT", {}, 0.99, matched_by="router.self_report_with_runtime", allow_chat_without_evidence=False)

    if re.search(r"\b(what are you actually running on|running on right now|context size|gpu layers|threads|batch|provider|runtime status)\b", low):
        return _mk("RUNTIME_STATUS", {}, 0.99, matched_by="router.runtime_status", allow_chat_without_evidence=False)

    # Self-referential temperature: "what's your temperature", "your temperature out now",
    # "what is your inference temperature", "what temp are you running at" etc.
    # Must fire BEFORE the weather prepass which also matches "temperature".
    if re.search(
        r"\b(?:your|eli(?:'s)?|its)\s+(?:inference\s+)?temp(?:erature)?\b"
        r"|\binference\s+temp(?:erature)?\b"
        r"|\bgeneration\s+temp(?:erature)?\b"
        r"|\btemp(?:erature)?\s+(?:(?:are\s+)?you(?:'re|\s+are)?\s+(?:running|at|set|using|on)|out\s+now|setting|parameter|value|right\s+now|currently)\b",
        low,
    ):
        return _mk("RUNTIME_STATUS", {}, 0.97, matched_by="router.self_temp_runtime_status", allow_chat_without_evidence=False)

    if re.search(r"\b(explain exactly how your memory system works internally|memory system works internally|which files.*which db tables.*which functions|memory runtime surface|memory runtime)\b", low):
        return _mk("EXPLAIN_MEMORY_RUNTIME", {}, 0.99, matched_by="router.memory_runtime", allow_chat_without_evidence=False)

    if "memory" in low and re.search(
        r"\b(db paths?|database|sqlite|tables?|functions?|internally|semantic|rag|faiss|fts5|vector(?:ing|s)?|index(?:ing|es)?|hyde|short[- ]?term|long[- ]?term)\b",
        low,
    ):
        return _mk("EXPLAIN_MEMORY_RUNTIME", {}, 0.99, matched_by="router.memory_runtime_architecture", allow_chat_without_evidence=False)

    if re.search(r"\b(explain your cognition pipeline|cognition pipeline from input to output|input to output.*every step|cognitive pipeline)\b", low):
        return _mk("EXPLAIN_COGNITION_RUNTIME", {}, 0.99, matched_by="router.cognition_runtime", allow_chat_without_evidence=False)

    if re.search(r"\b(what do you know about me from memory|what do you know about me|what do you remember of me|who am i|what is my name|do you remember me|do you know me|my preferences|my persona|my ethos)\b", low):
        return _mk("USER_IDENTITY_SUMMARY", {}, 0.99, matched_by="router.user_identity_summary", allow_chat_without_evidence=False)

    # Pure persona questions (no runtime keywords) → CHAT so ELI answers from
    # its own character and memory, not a raw JSON spec dump.
    if re.search(r"\b(who are you|what are you(?!\s+\w)|what is your name|what's your name|tell me about yourself|what is your purpose)\b", low) and not re.search(r"\b(model|running on|provider|context|gpu|llm|specs?|technical|runtime|layers|threads|batch)\b", low):
        return _mk("CHAT", {"message": raw}, 0.99, matched_by="router.identity_persona_chat", allow_chat_without_evidence=True)
    # Technical model/runtime queries → SELF_REPORT (actual spec evidence needed)
    if re.search(r"\b(what model(?: are you| do you use| is this)?|which model(?: are you| do you use| is this)?|what llm|which llm|what are you running on|what are you actually)\b", low):
        return _mk("SELF_REPORT", {}, 0.99, matched_by="router.self_report", allow_chat_without_evidence=False)
    # --- end explicit grounded speech-act route authority ---

    # --- dynamic evidence preempts ---
    if re.search(r"\b(who are you.*running on right now|model.*context size.*gpu layers|what are you actually running on right now|you know who you are)\b", low):
        return _mk("CHAT", {"message": raw}, 0.95, matched_by="router.runtime_status_to_chat", allow_chat_without_evidence=False)

    if re.search(r"\b(what do you know about me from memory|what do you know about me|what do you remember of me|who am i|what is my name|do you remember me)\b", low):
        return _mk("CHAT", {"message": raw}, 0.95, matched_by="router.memory_status_to_chat", allow_chat_without_evidence=False)

    if re.search(r"\b(explain exactly how your memory system works internally|memory system works internally|which files.*which db tables.*which functions)\b", low):
        return _mk("EXPLAIN_MEMORY_RUNTIME", {}, 0.99, matched_by="router.memory_runtime_to_grounded", allow_chat_without_evidence=False)

    if re.search(r"\b(run a full runtime audit|runtime audit.*broken or missing)\b", low):
        return _mk("RUNTIME_AUDIT", {}, 0.99, matched_by="router.runtime_audit", allow_chat_without_evidence=False, need_grounding=True, task_family="grounded_audit")

    if re.search(r"\b(what imports are failing|what imports are missing|imports are failing or missing)\b", low):
        return _mk("IMPORT_AUDIT", {}, 0.99, matched_by="router.import_audit", allow_chat_without_evidence=False, need_grounding=True, task_family="grounded_audit")

    if re.search(
        r"\b(diagnose\s+wrappers?|show\s+(?:the\s+)?(?:executor\s+)?(?:wrapper|middleware)\s+(?:chain|stack|table)|"
        r"what\s+wraps?\s+(?:the\s+)?executor|executor\s+middleware\s+(?:chain|stack|table)|"
        r"list\s+(?:the\s+)?executor\s+wrappers?)\b",
        low,
    ):
        return _mk(
            "DIAGNOSE_WRAPPERS", {}, 0.99,
            matched_by="router.diagnose_wrappers",
            allow_chat_without_evidence=False,
            need_grounding=True,
            task_family="grounded_audit",
        )

    if re.search(r"\b(show me the resolved runtime paths|resolved runtime paths|runtime paths for every critical file|critical file you depend on)\b", low):
        return _mk("RESOLVE_RUNTIME_PATHS", {}, 0.99, matched_by="runtime.paths.preempt", allow_chat_without_evidence=False)

    if re.search(r"\b(audit your gui file|gui runtime audit|gui file.*wired incorrectly)\b", low):
        return _mk(
            "GUI_RUNTIME_AUDIT",
            {},
            0.99,
            matched_by="router.gui_runtime_audit",
            allow_chat_without_evidence=False,
            need_grounding=True,
            task_family="grounded_audit",
        )

    if re.search(r"\b(show me the resolved runtime paths|resolved runtime paths|runtime paths for every critical file|critical file you depend on)\b", low):
        return _mk("CHAT", {"message": raw}, 0.95, matched_by="router.runtime_paths_to_chat")

    if re.search(r"\b(audit your gui file|gui runtime audit|gui file.*wired incorrectly)\b", low):
        return _mk("GUI_RUNTIME_AUDIT", {}, 0.99, matched_by="gui.runtime.preempt")

    # Voice/STT diagnostics must be checked BEFORE general RUNTIME_AUDIT
    # because RUNTIME_AUDIT's regex catches bare "diagnostic/diagnostics" which
    # swallows "voice diagnostics", "mic diagnostics", etc.
    if re.search(r"\b(voice|stt|speech[- ]to[- ]text|whisper|microphone|mic)\s+"
                 r"(diagnostic|diagnostics|status|test|check|health)\b"
                 r"|\b(diagnostic|diagnostics|status|test|check|health)\s+(voice|stt|speech|whisper|mic)\b",
                 low):
        return _mk("VOICE_DIAGNOSTICS", {}, 0.93, matched_by="voice.diagnostics.preempt")

    # ── Gaze engine control ────────────────────────────────────────────────────
    # Must sit before RUNTIME_AUDIT so "gaze status" / "gaze diagnostics" don't
    # get absorbed by the generic audit preempt.
    if re.search(
        r"\b(gaze\s*(engine|tracker|tracking|system)?\s*(status|diagnostics?|check|health|info))\b"
        r"|\b(is\s+gaze\s+(running|active|on|enabled))\b"
        r"|\b(gaze\s+engine\s+status)\b",
        low,
    ):
        return _mk("GAZE_STATUS", {}, 0.95, matched_by="gaze.status.preempt")

    if re.search(
        r"\b(enable|start|turn\s+on|activate|switch\s+on)\s+(the\s+)?(gaze|gaze\s+engine|gaze\s+track(er|ing))\b"
        r"|\bgaze\s+(engine\s+)?(on|enable|start|activate)\b",
        low,
    ):
        return _mk("GAZE_ENABLE", {}, 0.96, matched_by="gaze.enable.preempt")

    if re.search(
        r"\b(disable|stop|turn\s+off|deactivate|switch\s+off)\s+(the\s+)?(gaze|gaze\s+engine|gaze\s+track(er|ing))\b"
        r"|\bgaze\s+(engine\s+)?(off|disable|stop|deactivate)\b",
        low,
    ):
        return _mk("GAZE_DISABLE", {}, 0.96, matched_by="gaze.disable.preempt")

    if re.search(
        r"\b(calibrate\s+gaze|gaze\s+calibr|run\s+gaze\s+calibr|gaze\s+setup)"
        r"|\b(calibrate\s+(the\s+)?gaze\s+engine)",
        low,
    ):
        return _mk("GAZE_CALIBRATE", {}, 0.95, matched_by="gaze.calibrate.preempt")
    # ── end gaze engine control ───────────────────────────────────────────────

    # ── File Audit (must precede RUNTIME_AUDIT — "do a file audit" would
    # otherwise be stolen by the broad 'do ... audit' RUNTIME_AUDIT pattern) ──
    # NOTE: "list" is intentionally excluded from bare "files?" matching.
    # "list the files in my downloads folder" must fall through to LIST_DIR.
    # Only audit|examine|inspect|scan|inventory pair with bare "files?".
    # "list" only triggers FILE_AUDIT when paired with code-specific nouns
    # (codebase, source, modules, scripts, project files) or explicit qualifiers.
    if re.search(
        r"\b(audit|examine|inspect|scan|inventory)\b.{0,40}\b(files?|codebase|source|modules?|scripts?|project\s+files?)\b"
        r"|\b(list|inventory)\b.{0,40}\b(codebase|source|modules?|scripts?|project\s+files?)\b"
        r"|\bfile\s+(audit|scan|inventory|check|examination)\b"
        r"|\baudis?\s+(?:all\s+(?:of\s+)?(?:your|the)\s+)?files?\b"
        r"|\b(do|perform|run)\s+(?:a\s+)?file\s+audit\b"
        r"|\blist\s+(?:all\s+)?(?:your\s+)?files?\b",
        low,
    ):
        return _mk(
            "FILE_AUDIT",
            {"scope": "eli", "message": raw},
            0.95,
            matched_by="router.file_audit",
            need_grounding=True,
            task_family="grounded_audit",
        )

    if re.search(
        r"\b(run a full runtime audit|run full runtime audit|runtime audit|system audit|health check|diagnostic|diagnostics|what'?s actually broken|what is actually broken)\b"
        r"|\b(perform|do|run|wanna run|want to run|let'?s run)\b.{0,30}\b(full.?time\s+audit|full\s+audit|runtime audit|system audit|audit)\b"
        r"|\b(fulltime|full.time)\s+audit\b"
        r"|\bdo an? audit\b"
        r"|\bcheck (the\s+)?(runtime|system|modules?|pipeline)\b",
        low,
    ):
        return _mk("RUNTIME_AUDIT", {}, 0.95, matched_by="audit.runtime.preempt",
                   need_grounding=True, task_family="grounded_audit")

    if re.search(r"\b(what are you actually running on|running on right now|context size|gpu layers|threads|batch|provider)\b", low):
        return _mk("CHAT", {"message": raw}, 0.95, matched_by="router.runtime_status_grounded_to_chat", allow_chat_without_evidence=False)

    # See notes on cognition.trace.chat_handoff in _route_grounded_runtime_intent.
    if re.search(r"\b(confidence in your last response|which agents contributed|agents contributed|grounded trace|trace metadata)\b", low):
        return _mk("CHAT", {"message": raw}, 0.98,
                   matched_by="cognition.trace.chat_handoff",
                   allow_chat_without_evidence=False)

    if re.search(r"\b(memory system|memory runtime|how does your memory work internally|which files|which db tables|which functions)\b", low):
        return _mk("EXPLAIN_MEMORY_RUNTIME", {}, 0.99, matched_by="router.memory_status_to_grounded", allow_chat_without_evidence=False)

    # ELI_ROUTER_REASONING_MODE_STATUS_FIX_20260505: answer the active mode label; do not hijack into full runtime diagnostics.
    # Only intercept queries specifically asking about the CURRENT/ACTIVE mode.
    # Queries about ALL modes, every mode, how many modes, explain modes, differences, etc.
    # must fall through to CHAT so the full pipeline synthesises from the source files.
    _asking_about_all_modes = re.search(
        r"\b(all|every|each|how many|list|explain|full|describe|detail|difference|differ|compare|what are|tell me about|tell me all|tell me everything|what do|how do|modes?\s+you\s+have|modes?\s+does|all.*mode|every.*mode)\b",
        low,
    )
    if not _asking_about_all_modes and (
        re.fullmatch(r"(?:what(?:'s| is)|which is|tell me|show me)?\s*(?:your|eli'?s|the|my)?\s*(?:current|active)?\s*reasoning mode(?:\s*,?\s*eli)?\??", low)
        or re.search(r"\b(?:what(?:'s| is)|which|current|active)\b.{0,40}\breasoning mode\b", low)
    ):
        return _mk("REASONING_MODE_STATUS", {}, 0.995, matched_by="reasoning.mode_status", allow_chat_without_evidence=False)

    # Route broad "explain / describe / breakdown / list all reasoning modes" queries to
    # EXPLAIN_ALL_REASONING_MODES so the executor reads directly from reasoning_modes.py
    # and the GGUF synthesises from real file evidence, not training knowledge.
    if _asking_about_all_modes and re.search(r"\b(reasoning mode|modes?)\b", low):
        return _mk(
            "EXPLAIN_ALL_REASONING_MODES", {},
            0.99,
            matched_by="reasoning.all_modes_grounded",
            allow_chat_without_evidence=False,
            need_grounding=True,
            task_family="grounded_audit",
        )

    if re.search(r"\b(cognition pipeline|input to output|every step|no vague descriptions)\b", low):
        return _mk("CHAT", {"message": raw}, 0.95, matched_by="router.cognition_status_to_chat")

    # "What do you know about me from memory" is open-ended and needs HyDE
    # expansion + rerank. The MEMORY_RECALL preempt produced single weak hits
    # (observed conf 0.34) and synth_actions skipped stages 3/9, so the LLM
    # filled gaps with invented details. CHAT engages the full retrieval path.


    if re.search(
        r"\b("
        r"what do you know about me|"
        r"what do you know from memory|"
        r"show (?:my|the) stored memor(?:y|ies)(?: about me)?|"
        r"dump (?:my )?(?:user )?(?:profile|info|memory)|"
        r"who am i(?: to you)?|"
        r"show user info|"
        r"user info report|"
        r"profile report"
        r")\b",
        text_l,
    ):
        return _mk(
            "MEMORY_RECALL",
            {"query": text, "_prefer_user_info_report": True},
            0.99,
            matched_by="identity.user_info.report",
            allow_chat_without_evidence=False,
        )

    if re.search(
        r"\b(refresh|rebuild|update)\s+(?:the\s+)?(?:user\s+info|profile\s+report)\b",
        text_l,
    ):
        return _mk(
            "REFRESH_USER_INFO",
            {"force": True},
            0.99,
            matched_by="identity.user_info.refresh",
            allow_chat_without_evidence=False,
        )
    if re.search(r"\b(what do you know about me from memory|what do you remember about me|tell me everything you know about me from memory)\b", low):
        return _mk("CHAT", {"message": raw}, 0.98,
                   matched_by="memory.user_recall.chat_handoff",
                   allow_chat_without_evidence=False)

    if re.fullmatch(r"\s*who am i\??\s*", low):
        return _mk("MEMORY_RECALL", {"query": "identity"}, 0.99, matched_by="memory.identity.preempt")

    # --- DIRECT SCREENSHOT MATCH ---
    if raw.strip().lower() == "screenshot":
        return _mk("SCREENSHOT", {"region": "full"},
                   1.0, matched_by="io.screenshot_exact")
    # --- SCREENSHOT: direct capture before anything else ---
    if re.search(
            r"\b(take|capture|grab)\s+(a\s+)?(screenshot|screen\s*shot|screen\s*capture|screen|picture of screen)\b", raw, re.I):
        region = "area" if re.search(
            r"\b(area|region|selection|part)\b", raw, re.I) else "full"
        return _mk("SCREENSHOT", {"region": region}, 0.99,
                   matched_by="io.screenshot_direct", entities={"region": region})
    # --- WRITE_NOTE: colon format ---
    if re.match(r"^write note:\s*(.+)", raw, re.I):
        note_text = re.match(
            r"^write note:\s*(.+)",
            raw,
            re.I).group(1).strip()
        return _mk("WRITE_NOTE", {"text": note_text},
                   0.99, matched_by="notes.write_colon_direct")

    grounded = _route_grounded_runtime_intent(raw, low)
    if grounded is not None:
        return grounded

    if (("?" in raw or "!" in raw) and len(low.split()) >= 12 and not re.match(
            r"^(open|access|initiate|fabricate|check|run|execute|type|press|pause|resume|play|next|previous|stop|mute|unmute|read|list|show|write|add|analyse|analyze|improve)\b", low)):
        return _mk("CHAT", {"message": raw}, 0.85,
                   matched_by="chat.long_question_guard")

    if not raw:
        return _mk("CHAT", {"message": ""}, 0.2, matched_by="empty_input")

    # ── NEWS / WEB LEARNING (before generic web/search routes) ───────────────
    if re.search(r"\b(fetch|get|pull|download|update)\b.{0,25}\bnews\b"
                 r"|\bnews\b.{0,20}(fetch|get|update|refresh)\b", low):
        _tm = re.search(r"(?:about|on|for|topic[:\s]+)\s*([a-z][a-z ]{2,30})", low)
        return _mk("NEWS_FETCH",
                   {"mode": "fetch_and_show", "topic": _tm.group(1).strip() if _tm else "", "sources": ["all"]},
                   0.96, matched_by="news.fetch")

    if re.search(r"\bwhat(?:'?s?|\s+is)\s+(happening|going\s+on|the\s+news)\b"
                 r"|\bcurrent\s+events?\b|\blatest\s+news\b"
                 r"|\btoday'?s?\s+news\b|\bworld\s+news\b|\bnews\s+today\b"
                 r"|\bany\s+news\b|\bwhat'?s?\s+new\b"
                 r"|\bthe\s+news\b|\bheadlines?\b|\bnews[,\s]*eli\b|\beli[,\s]*news\b", low) \
            and not re.search(r"\b(dude|bro|man|wtf|omg|lol|hey|seriously|really)\b", low):
        # Extract topic from "news in/about/on/for X" or "X news" phrasing.
        _topic = ""
        _tm = re.search(r"\bnews\s+(?:in|about|on|for|regarding|covering)\s+([a-z][a-z0-9 \-]{2,40})\b", low)
        if not _tm:
            _tm = re.search(r"\b(?:in|about|on|for|regarding|covering)\s+([a-z][a-z0-9 \-]{2,40})\s+news\b", low)
        if not _tm:
            _tm = re.search(r"\b([a-z][a-z0-9 \-]{2,40})\s+news\b", low)
        if _tm:
            _topic = _tm.group(1).strip().rstrip("?.!,;:")
            # Reject non-topic matches: contraction artifacts ("s the latest"),
            # question fragments ("what is the latest"), and stop words.
            _TOPIC_NOISE = {
                "the", "any", "today", "world", "current", "latest",
                "what", "is", "are", "some", "news", "it", "me",
                "what is the latest", "is the latest", "the latest",
                "what are the", "what is",
            }
            _first_word = _topic.split()[0] if _topic else ""
            if (not _topic
                    or len(_first_word) < 2
                    or _topic in _TOPIC_NOISE
                    or _first_word in {"what", "how", "why", "when", "where", "who",
                                       "is", "are", "was", "were", "the", "a", "an"}):
                _topic = ""
        args_news = {"mode": "fetch_and_show", "sources": ["all"]}
        if _topic and _topic not in {"the", "any", "today", "world", "current", "latest"}:
            args_news["topic"] = _topic
        return _mk("NEWS_FETCH", args_news, 0.95, matched_by="news.current_events")

    if re.search(r"\b(search|find)\b.{0,20}\bnews\b|\bnews\b.{0,20}(search|find)\b", low):
        _qm = re.search(r"(?:about|for|on)\s+(.+)$", low)
        return _mk("NEWS_FETCH",
                   {"mode": "search", "query": _qm.group(1).strip() if _qm else raw.strip()},
                   0.94, matched_by="news.search")

    if re.search(r"\b(show|list|give\s+me)\b.{0,30}\b(headlines?|recent\s+news|news\s+articles?)\b", low):
        return _mk("NEWS_FETCH", {"mode": "recent"}, 0.94, matched_by="news.recent")

    # "show me X news" / "give me X news" / "show me news on X"
    _topic_news = re.search(
        r"\b(?:show|list|give|tell|fetch|pull|get|bring)\s+(?:me\s+|us\s+)?"
        r"(?:some\s+|the\s+|any\s+)?"
        r"([a-z][a-z0-9 \-]{2,40}?)\s+news\b",
        low,
    )
    if _topic_news:
        topic = _topic_news.group(1).strip().rstrip("?.!,;:")
        if topic and topic not in {"the", "any", "today", "world", "current", "latest", "some"}:
            return _mk("NEWS_FETCH",
                       {"mode": "fetch_and_show", "topic": topic, "sources": ["all"]},
                       0.93, matched_by="news.show_topic")
    _topic_news_about = re.search(
        r"\b(?:show|list|give|tell|fetch|pull|get|bring)\s+(?:me\s+|us\s+)?"
        r"(?:some\s+|the\s+|any\s+)?news\s+(?:about|on|for|in|regarding|covering)\s+"
        r"([a-z][a-z0-9 \-]{2,40})",
        low,
    )
    if _topic_news_about:
        topic = _topic_news_about.group(1).strip().rstrip("?.!,;:")
        if topic:
            return _mk("NEWS_FETCH",
                       {"mode": "fetch_and_show", "topic": topic, "sources": ["all"]},
                       0.93, matched_by="news.show_about_topic")

    if re.search(r"\b(where|what)\b.{0,15}\bmy\s+news\b"
                 r"|\bshow\s+(?:me\s+)?(?:the\s+)?news\b"
                 r"|\bwhere(?:'?s?\s+|\s+is\s+)(?:the\s+)?news\b", low):
        return _mk("NEWS_FETCH", {"mode": "recent"}, 0.93, matched_by="news.show_cached")

    if re.search(r"\bnews\s+(stats?|status|count|database)\b", low):
        return _mk("NEWS_FETCH", {"mode": "stats"}, 0.91, matched_by="news.stats")

    if re.search(r"\b(learn|teach\s+yourself|update\s+yourself)\b.{0,30}"
                 r"\b(web|internet|online|news|current)\b", low):
        _tm = re.search(r"about\s+([a-z][a-z ]{2,30})", low)
        return _mk("NEWS_FETCH",
                   {"mode": "fetch_and_show", "topic": _tm.group(1).strip() if _tm else "", "sources": ["all"]},
                   0.93, matched_by="news.learn")

    # ── SELF_UPGRADE (before generic 'update' routes) ─────────────────────────
    if re.search(r"\b(upgrade|update)\s+(yourself|eli|the\s+system)\b"
                 r"|\bself.?upgrade\b|\brun\s+upgrade\b", low):
        return _mk("SELF_UPGRADE", {"request": raw}, 0.96, matched_by="self.upgrade")

    if re.search(r"\b(generate|create)\s+patch\b|\bpatch\s+(eli|system)\b", low):
        return _mk("SELF_UPGRADE", {"request": "generate_patch"}, 0.93, matched_by="self.patch")

    if re.search(r"\bpatch\s+yourself\b|\bself.?patch\b|\bapply.*patch\b|\bfix\s+your\s+own\s+code\b", low):
        return _mk("SELF_PATCH", {}, 0.95, matched_by="self.patch_cycle")

    # ── SELF_TEST (before generic 'test' routes) ──────────────────────────────
    if re.search(r"\b(run\s+)?self.?test\b|\btest\s+yourself\b|\brun\s+tests?\b", low):
        return _mk("SELF_TEST", {}, 0.94, matched_by="self.test")

        # ── Memory search (must be before web search to prevent mis-routing) ─
    # Bare forms: 'search your memory', 'search memory', 'check memory'
    _bare_mem = re.match(
        r'^(?:search|check|look\s+in|query)\s+(?:your\s+)?memor(?:y|ies)$', low
    )
    if _bare_mem:
        return _mk('MEMORY_RECALL', {'query': ''},
                   0.95, matched_by='memory.search_bare')
    # Explicit "what do you know about me" → MEMORY_RECALL
    if re.search(r"\bwhat\s+do\s+you\s+know\s+about\s+me\b", low):
        return _mk("MEMORY_RECALL", {"query": "information about user"},
                   0.98, matched_by="memory.user_recall", entities={"query": "user"})

    # Forms with 'for X': 'search your memory/memories for python'
    # NOTE: memor(?:y|ies) handles both singular and plural to prevent
    # "search your memories for X" from falling through to OPEN_BROWSER web.search.
    _mem_search_patterns = (
        r'^search\s+(?:your\s+)?memor(?:y|ies)\s+(?:for\s+)?(.+)$',
        r'^(?:look|check)\s+(?:in\s+)?(?:your\s+)?memor(?:y|ies)\s+(?:for\s+)?(.+)$',
        r'^(?:do\s+you\s+(?:have|know)\s+anything\s+(?:in\s+memor(?:y|ies)\s+)?(?:about|related\s+to))\s+(.+)$',
        r'^(?:recall|retrieve)\s+(?:from\s+memor(?:y|ies)\s+)?(?:anything\s+(?:about|related\s+to)\s+)?(.+)$',
    )
    for _mp in _mem_search_patterns:
        _mm = re.match(_mp, low, re.I)
        if _mm:
            _mq = _mm.group(1).strip(
            ) if _mm.lastindex and _mm.lastindex >= 1 else ''
            return _mk('MEMORY_RECALL', {'query': _mq}, 0.95, matched_by='memory.search_explicit',
                       entities={'query': _mq})

# ---- PLUGINS ----
    if re.search(
            r"\b(?:install|download|get)\s+(?:a\s+|the\s+)?plugin\s+(?:for\s+)?(.+)", low):
        m = re.search(
            r"\b(?:install|download|get)\s+(?:a\s+|the\s+)?plugin\s+(?:for\s+)?(.+)",
            low)
        query = m.group(1).strip() if m else raw
        return _mk("PLUGIN_INSTALL", {"query": query}, 0.95, matched_by="plugin.install_for",
                   entities={"query": query}, task_family="plugin")
    if re.search(
            r"\b(?:install|download|get)\s+(?:the\s+)?(?:plugin\s+)?([a-z_]+)\s+plugin\b", low):
        m = re.search(
            r"\b(?:install|download|get)\s+(?:the\s+)?(?:plugin\s+)?([a-z_]+)\s+plugin\b",
            low)
        pid = m.group(1).strip() if m else ""
        return _mk("PLUGIN_INSTALL", {"plugin": pid}, 0.97, matched_by="plugin.install_named",
                   entities={"plugin": pid}, task_family="plugin")
    if re.search(r"\buninstall\s+(?:the\s+)?(?:plugin\s+)?([a-z_]+)", low):
        m = re.search(r"\buninstall\s+(?:the\s+)?(?:plugin\s+)?([a-z_]+)", low)
        pid = m.group(1).strip() if m else ""
        return _mk("PLUGIN_UNINSTALL", {"plugin": pid}, 0.95, matched_by="plugin.uninstall",
                   entities={"plugin": pid}, task_family="plugin")
    if re.search(
            r"\b(?:list|show)\s+(?:all\s+)?(?:available\s+)?plugins\b", low):
        return _mk("PLUGIN_LIST", {"scope": "all"}, 0.95,
                   matched_by="plugin.list_all", task_family="plugin")
    if re.search(r"\b(?:list|show)\s+(?:my\s+)?installed\s+plugins\b", low):
        return _mk("PLUGIN_LIST", {"scope": "installed"}, 0.95,
                   matched_by="plugin.list_installed", task_family="plugin")
    if re.search(
            r"\b(?:search|find)\s+(?:a\s+)?plugin(?:s)?\s+(?:for\s+)?(.+)", low):
        m = re.search(
            r"\b(?:search|find)\s+(?:a\s+)?plugin(?:s)?\s+(?:for\s+)?(.+)", low)
        query = m.group(1).strip() if m else raw
        return _mk("PLUGIN_SEARCH", {"query": query}, 0.95, matched_by="plugin.search",
                   entities={"query": query}, task_family="plugin")
    # Ambient vision toggle — must beat the generic "enable/disable X" plugin
    # matcher below ("enable ambient vision" is not a plugin).
    if re.search(r"\bambient\s+vision\b", low):
        _av_off = bool(re.search(r"\b(?:disable|turn\s+off|stop|deactivate)\b", low))
        return _mk("AMBIENT_VISION", {"enabled": not _av_off, "text": raw}, 0.96,
                   matched_by="vision.ambient_off" if _av_off else "vision.ambient_on")
    if re.search(
            r"\benable\s+(?:the\s+)?(?:plugin\s+)?([a-z_]+)\s*(?:plugin)?\b", low):
        m = re.search(
            r"\benable\s+(?:the\s+)?(?:plugin\s+)?([a-z_]+)\s*(?:plugin)?\b", low)
        pid = m.group(1).strip() if m else ""
        return _mk("PLUGIN_ENABLE", {"plugin": pid}, 0.95, matched_by="plugin.enable",
                   entities={"plugin": pid}, task_family="plugin")
    if re.search(
            r"\bdisable\s+(?:the\s+)?(?:plugin\s+)?([a-z_]+)\s*(?:plugin)?\b", low):
        m = re.search(
            r"\bdisable\s+(?:the\s+)?(?:plugin\s+)?([a-z_]+)\s*(?:plugin)?\b", low)
        pid = m.group(1).strip() if m else ""
        return _mk("PLUGIN_DISABLE", {"plugin": pid}, 0.95, matched_by="plugin.disable",
                   entities={"plugin": pid}, task_family="plugin")

    # ---- RUNTIME AUDIT ----
    if re.search(
            r"\b(?:run|do|perform|execute|start|run\s+a|do\s+a|perform\s+a)\s+"
            r"(?:full\s+)?(?:runtime\s+audit|system\s+audit|health\s+check|diagnostic|diagnostics|audit)\b", low):
        return _mk("RUNTIME_AUDIT", {}, 0.95, matched_by="audit.runtime",
                   need_grounding=True, task_family="grounded_audit")
    if re.search(
            r"\bwhat(?:'s|\s+is)\s+(?:actually\s+)?broken\b", low):
        return _mk("RUNTIME_AUDIT", {}, 0.90, matched_by="audit.broken",
                   need_grounding=True, task_family="grounded_audit")
    if re.search(
            r"\b(?:audit|check|test|verify)\s+(?:all|every|the)\s+"
            r"(?:agents?|systems?|modules?|components?|pipeline)\b", low):
        return _mk("RUNTIME_AUDIT", {}, 0.90, matched_by="audit.all_agents",
                   need_grounding=True, task_family="grounded_audit")

    # ---- HARDWARE PROFILE ----
    if re.search(
            r"\b(?:hardware|system)\s+(?:profile|benchmark|scan|detect)\b", low):
        return _mk("HARDWARE_PROFILE", {}, 0.95, matched_by="hardware.profile",
                   need_grounding=True, task_family="grounded_audit")
    if re.search(r"\bapply\s+(?:the\s+)?hardware\s+recommendation\b", low):
        return _mk("HARDWARE_PROFILE", {"apply": True}, 0.97, matched_by="hardware.apply",
                   need_grounding=True, task_family="grounded_audit")
    if re.search(
            r"\b(?:what|which)\s+model\s+(?:should|would|do)\s+(?:i|you|we)\s+(?:use|recommend)\b", low):
        return _mk("HARDWARE_PROFILE", {}, 0.90, matched_by="hardware.recommend",
                   need_grounding=True, task_family="grounded_audit")
    if re.search(
            r"\boptim(?:ize|ise)\s+(?:my\s+)?(?:model|settings|parameters|config)\b", low):
        return _mk("HARDWARE_PROFILE", {}, 0.90, matched_by="hardware.optimize",
                   need_grounding=True, task_family="grounded_audit")

    # ---- AWARENESS / CODE CHANGES ----
    if re.search(
            r"\b(?:awareness|self[- ]?awareness)\s+(?:status|report|check)\b", low):
        return _mk("AWARENESS_STATUS", {"query": raw}, 0.95, matched_by="awareness.status",
                   entities={"query": raw}, need_grounding=True, task_family="grounded_audit")
    if re.search(r"memory\s*(status|stats|report|info|summary|check|usage|count|size|total)|how many memories|memories (do you have|count|total)", low):
        return _mk("MEMORY_STATUS", {}, 0.97, matched_by="memory.status")
    if re.search(r"\bcognition\s*(runtime\s+)?status\b|\bcognition\s*(stats|report|check|health)\b", low):
        return _mk("COGNITION_STATUS", {}, 0.99, matched_by="cognition.status")
    if re.search(r"\bruntime\s+status\b|\b(runtime|system)\s*(stats|report|health|check)\b", low):
        return _mk("RUNTIME_STATUS", {}, 0.99, matched_by="runtime.status")
    if re.search(r"\bwhat\s+code\s+(changed|has changed)\b|\bcode\s+changes?\b", low):
        return _mk("CODE_CHANGES", {"query": raw}, 0.95, matched_by="router.code_changes")
    if re.search(
            r"\b(?:code|source)\s+(?:changes?|diff|modifications?)\b", low):
        return _mk("CODE_CHANGES", {"query": raw}, 0.95, matched_by="awareness.code_changes",
                   entities={"query": raw}, need_grounding=True, task_family="grounded_audit")
    if re.search(
            r"\bwhat\s+(?:changed|has changed|was changed)\s+(?:in\s+)?(?:your|the|my)?\s*(?:code|source|codebase|repo)\b", low):
        return _mk("CODE_CHANGES", {"query": raw}, 0.93, matched_by="awareness.what_changed",
                   entities={"query": raw}, need_grounding=True, task_family="grounded_audit")
    if re.search(
            r"\b(?:capability|capabilities)\s+(?:changes?|updates?|diff)\b", low):
        return _mk("AWARENESS_STATUS", {"query": raw}, 0.93, matched_by="awareness.cap_changes",
                   entities={"query": raw}, need_grounding=True, task_family="grounded_audit")

        # ============================================================
    # LEGACY-COMPAT MEDIA INTENTS (must be before generic MEDIA_CONTROL)
    # Keeps test compatibility and deterministic semantics.
    # ============================================================
    if re.search(r"\bstop\s+(?:the\s+)?(?:media|music|spotify)\b", low):
        return {"action": "STOP_MEDIA", "args": {}, "confidence": 0.96}

    if re.search(r"\bpause\s+(?:the\s+)?(?:media|music|spotify)\b", low):
        return {"action": "PAUSE_MEDIA", "args": {}, "confidence": 0.96}

    if re.search(
            r"\b(play|resume|start)\s+(?:the\s+)?(?:media|music|spotify)\b", low):
        return {"action": "PLAY_MEDIA", "args": {}, "confidence": 0.96}

    if re.search(r"\b(next|skip)\s+(?:the\s+)?(?:song|track|media)\b", low):
        return {"action": "NEXT_MEDIA", "args": {}, "confidence": 0.96}

    if re.search(
            r"\b(previous|prev|back)\s+(?:the\s+)?(?:song|track|media)\b", low):
        return {"action": "PREVIOUS_MEDIA", "args": {}, "confidence": 0.96}

    # ------------------------------------------------------------
    # 0) HARD COMPATIBILITY / REGRESSION CONTRACTS
    # ------------------------------------------------------------
    # Important: tests may expect STOP_MEDIA exactly for "stop media"
    if low.strip() == "stop media":
        return _mk("STOP_MEDIA", {}, 0.99,
                   matched_by="compat.stop_media_exact")

    # Bare domain / URL
    if _is_likely_url(raw):
        return _mk(
            "OPEN_URL",
            {"url": _normalize_url(raw)},
            0.99,
            matched_by="url.bare",
            entities={"url": _normalize_url(raw)},
        )

    # ------------------------------------------------------------
    # 1) SELF / SYSTEM INTELLIGENCE INTENTS
    # ------------------------------------------------------------
    if any(p in low for p in ["analyze yourself", "analyse yourself",
           "self analysis", "check yourself", "diagnostic"]):
        return _mk("SELF_ANALYZE", {}, 0.95, matched_by="self.analyze")

    if any(p in low for p in ["morning report",
           "daily report", "intelligence report"]):
        return _mk("MORNING_REPORT", {}, 0.95,
                   matched_by="self.morning_report")

    if any(p in low for p in ["apply self-improvement patch", "apply patch", "run patch cycle",
                              "patch yourself", "fix your own code", "self-patch"]):
        return _mk("SELF_PATCH", {}, 0.95, matched_by="self.patch")

    if "improve" in low and (
            "yourself" in low or "self" in low or "code" in low):
        return _mk("SELF_IMPROVE", {}, 0.9, matched_by="self.improve")

    if "suggest" in low and (
            "improvement" in low or "optimization" in low or "optimisation" in low):
        return _mk("SELF_ANALYZE", {"suggest": True},
                   0.9, matched_by="self.suggest_improvements")

    # ------------------------------------------------------------
    # 2) CODE / IDE / DEV WORKFLOWS
    # ------------------------------------------------------------
    if any(p in low for p in [
        "create project", "build project", "generate project", "make project",
        "new project", "start project"
    ]):
        return _mk("GENERATE_PROJECT", {"description": raw, "use_gguf_only": True,
                   "forbid_ollama": True}, 0.95, matched_by="dev.generate_project")

    # "run command X" / "run nvidia-smi" — explicit shell requests
    _run_cmd_m = re.match(
        r'^run\s+(?:the\s+)?(?:command\s+)?([a-zA-Z][\w\-]+(\s+[^,]+)?)$',
        raw,
        re.I)
    if _run_cmd_m:
        _cmd = _run_cmd_m.group(1).strip()
        if not re.search(r'\b(script|function|program|code)\b', _cmd, re.I):
            return _mk("SHELL_EXEC", {"cmd": _cmd}, 0.95, matched_by="shell.run_command",
                       entities={"cmd": _cmd})

    # Non-code "script" intents — must check BEFORE code triggers
    _NON_CODE_SCRIPT = re.compile(
        r"\b(?:for|about|on|regarding)\s+(?:[\w]+\s+)*?"
        r"(?:presentation|slides?|talk|speech|podcast|film|movie|play|show|actors?|"
        r"onboarding|marketing|campaign|video|youtube|event|ceremony|wedding|performance|"
        r"audience|interview|screenplay)\b", re.I)
    _CREATIVE_SCRIPT = re.compile(
        r"\b(?:film\s+script|movie\s+script|play\s+script|podcast\s+script|write\s+a\s+(?:podcast|film|stage|theatre|movie)\s+script|"
        r"theatre\s+script|stage\s+script|script\s+for\s+(?:a\s+)?(?:film|movie|play|"
        r"podcast|show|talk|video|event|presentation|slides?|actors?|onboarding|ceremony|"
        r"wedding|performance|audience|interview|marketing|campaign|youtube))\b", re.I)
    # _NON_CODE_SCRIPT must only fire when there's a clear creation intent.
    # Without this guard "...drowning on youtube" matches because "on" is in
    # the preposition set and "youtube" is in the keyword list.
    _CREATION_VERB = re.compile(
        r"\b(?:write|create|generate|make|build|prepare|draft|produce|develop|design)\b",
        re.I)
    if (_CREATION_VERB.search(raw) and _NON_CODE_SCRIPT.search(raw)) or _CREATIVE_SCRIPT.search(raw):
        return _mk("CHAT", {"message": raw}, 0.75,
                   matched_by="dev.non_code_script")

    code_triggers = [
        "create a script", "write a script", "generate a script",
        "create a python", "write a python", "make a python",
        "create a function", "write a function", "generate a function",
        "write code", "generate code", "write me code",
        "create code", "build a script", "make a script",
        "create me a script", "write me a script"
    ]
    # Also catch: "write a bash/python/shell/js script to/for/that"
    _CODE_SCRIPT_RE = re.compile(
        r"\b(?:write|create|generate|make|build)\s+(?:a\s+)?(?:bash|python|shell|sh|"
        r"js|javascript|ruby|perl|powershell|zsh|fish|lua|go|rust)\s+(?:script|function|"
        r"program|module|class|code)\b", re.I)
    _GENERATION_COMPLAINT = (
        low.startswith((
            "you did not", "you didn't", "you just", "that script", "this script",
            "why did you", "why didn't you", "where is", "where did",
        ))
        or any(p in low for p in (
            "did not generate", "didn't generate", "never ran", "not generated",
            "nothing to do with", "less in content", "no ide opened",
            "did not open", "didn't open", "dump it into chat", "not provide any path",
        ))
    )
    # Background-job inspection
    if re.search(r"\b(?:check|status\s+of|how'?s|show|view)\s+job\s+\d+|\bjob\s+\d+\b", low):
        _jm = re.search(r"\bjob\s+(\d+)", low)
        return _mk("CHECK_JOB", {"job_id": _jm.group(1) if _jm else None, "text": raw},
                   0.95, matched_by="dev.check_job")
    if re.search(r"\b(?:background\s+jobs|list\s+(?:background\s+|running\s+)?jobs|running\s+jobs|what\s+jobs)\b", low):
        return _mk("BACKGROUND_JOBS", {}, 0.9, matched_by="dev.background_jobs")

    # CODE_SOLVE — the verified coding agent (plan → DAG/tree search → execute →
    # repair). Takes precedence over GENERATE_SCRIPT for requests that ask for
    # verification/testing/robustness; plain "write a script" stays GENERATE_SCRIPT.
    _CODE_SOLVE_RE = re.compile(
        r"\b(?:code[\s_-]?solve"
        r"|solve\s+(?:this\s+|the\s+)?(?:coding|programming|algorithm|leetcode|kata)"
        r"|(?:implement|write|build|create|fix|code)\b[^.?!]*\b(?:and|with|then|that)\b[^.?!]*"
        r"\b(?:tested|test|tests|verify|verified|unit\s+tests?|passes?\s+tests?|make\s+sure\s+it\s+(?:works|passes|runs))\b"
        r"|verified\s+(?:code|solution|implementation)"
        r"|use\s+the\s+coding\s+agent)\b", re.I)
    if not _GENERATION_COMPLAINT and _CODE_SOLVE_RE.search(raw):
        _cs_lang = "python"
        _cs_lm = re.search(r"\b(bash|shell|javascript|js|typescript|ts|ruby|go|golang|lua)\b", low)
        if _cs_lm:
            _cs_lang = {"js": "javascript", "ts": "typescript", "golang": "go",
                        "shell": "bash"}.get(_cs_lm.group(1), _cs_lm.group(1))
        return _mk("CODE_SOLVE", {"description": raw, "language": _cs_lang}, 0.95,
                   matched_by="dev.code_solve")

    if not _GENERATION_COMPLAINT and (any(p in low for p in code_triggers) or _CODE_SCRIPT_RE.search(raw)):
        return _mk("GENERATE_SCRIPT", {"description": raw, "use_gguf_only": True,
                   "forbid_ollama": True}, 0.95, matched_by="dev.generate_script")

    if re.search(
            r"(show|open|view|display)\s+.{0,20}?(diff|changes?|what.{0,10}fixed)", low):
        return _mk("SHOW_DIFF", {}, 0.9, matched_by="dev.show_diff")

    # fixed regex (no hidden control char nonsense)
    if re.search(
            r"(open|show|view)\s+.{0,20}?(?:in\s+)?(?:code|editor|ide)\b", low):
        pm = re.search(r"([~/\w.\- /]+\.py)\b", raw)
        path = pm.group(1).strip() if pm else ""
        return _mk("OPEN_IN_IDE", {"path": path}, 0.88, matched_by="dev.open_in_ide", entities={
                   "path": path} if path else None)

    if re.search(r"(?:open|launch|start|run)\s+(?:my\s+)?(?:ide|code\s+editor|vscode|visual\s+studio\s+code|pycharm|intellij|sublime|atom|gedit|notepad\+\+|nano|vim)", low):
        return _mk("OPEN_IDE", {}, 0.97, matched_by="dev.open_ide")

    # ------------------------------------------------------------
    # 3) MEMORY / CONTEXT / TEMPORAL RECALL
    # ------------------------------------------------------------
    if _is_time_recall_query(raw, low):
        # Let chat/planner handle temporal interpretation using memory backend
        return _mk("CHAT", {"message": raw}, 0.98,
                   matched_by="memory.temporal_recall_as_chat")

    if re.search(r"\bwhat(?:'s| is) my name\b", low) or re.search(
            r"\bwhat should you call me\b", low):
        return _mk("MEMORY_RECALL", {"query": "name"},
                   0.95, matched_by="memory.name_recall")

    m = re.match(r"^(?:recall|memory recall)\s+(.+)$", raw, re.I)
    if m:
        return _mk("MEMORY_RECALL", {"query": m.group(
            1).strip()}, 1.0, matched_by="memory.recall_explicit")

    if re.search(
            r"(what (is|was) (my|our) favourite colour|what (is|was) (my|our) favorite color|tell me (my|our) favorite color)", raw, re.I):
        return _mk("MEMORY_RECALL", {
                   "query": "favorite color"}, 0.95, matched_by="memory.favorite_color")

    # Name questions → let LLM answer naturally using injected memories
    # if re.search(r"(what (is|was) (my|our) name|what should you call me)", raw, re.I):
    # return _mk("MEMORY_RECALL", {"query": "name"}, 0.95,
    # matched_by="memory.name_recall")

    if re.search(r"\b(?:access|query)\s+neural\s+archive\b", raw, re.I):
        return _mk("MEMORY_RECALL", {
                   "query": "recent memories"}, 1.0, matched_by="memory.neural_archive_alias")

    if _looks_like_conversation_summary(low):
        m_num = re.search(r"last\s+(\d+)", low)
        limit = int(m_num.group(1)) if m_num else 10
        return _mk("MEMORY_RECALL", {
                   "query": "recent", "limit": limit}, 0.95, matched_by="memory.conversation_summary")

    # ── Note taking: check BEFORE memory store to avoid confusion ──
    _note_m = re.match(
        r'^(?:write|save|create|make|add|take|jot)\s+(?:(?:a|the|down)\s+)*notes?(?:\s+down)?[:\s]+(?:saying\s+|that\s+)?(.+)$',
        raw,
        re.I)
    if _note_m:
        return _mk("WRITE_NOTE", {"text": _note_m.group(
            1).strip()}, 0.97, matched_by="notes.write_early")
    _note_m2 = re.match(r'^(?:write|add|take|jot)\s+note\s+(.+)$', raw, re.I)
    if _note_m2:
        return _mk("WRITE_NOTE", {"text": _note_m2.group(
            1).strip()}, 0.95, matched_by="notes.add_early")

    # Explicit remember/store (keep this later than some command parses)
    m = re.match(
        r"^(?:remember|store|save|note)\s+(?:that\s+)?(.+)$",
        raw,
        re.I)
    if m:
        text_to_store = m.group(1).strip()
        return _mk(
            "MEMORY_STORE",
            {"text": text_to_store, "tags": ["user_memory", "remembered"]},
            1.0,
            matched_by="memory.store_explicit",
            entities={"text": text_to_store},
        )

    if re.search(r"\b(store|remember|save)\s+(?:this\s+)?memory\b", low):
        return _mk("MEMORY_STORE", {"text": raw},
                   0.8, matched_by="memory.store_generic")

    # ------------------------------------------------------------
    # 4) MEDIA CONTROL (specific → generic)
    # ------------------------------------------------------------
    # Specific next/prev track controls (legacy-friendly)
    if re.search(r"\b(next|skip)\s+(?:the\s+)?(?:song|track)\b", low):
        return _mk("NEXT_MEDIA", {}, 0.95,
                   matched_by="media.next_track_specific")
    if re.search(r"\b(previous|back)\s+(?:the\s+)?(?:song|track)\b", low):
        return _mk("PREVIOUS_MEDIA", {}, 0.95,
                   matched_by="media.prev_track_specific")

    # App-targeted media commands
    for app in MEDIA_APPS:
        if re.search(rf"\b{re.escape(app)}\b", low):
            cmd = _canonical_media_command(low)
            if cmd:
                # preserve STOP_MEDIA semantic if user literally says stop
                # media/music/spotify later
                if cmd == "pause" and re.search(r"\bstop\b", low) and app in {
                        "spotify"}:
                    return _mk("STOP_MEDIA", {
                    }, 0.93, matched_by="media.legacy_stop_specific_app", entities={"target": app})
                return _mk(
                    "MEDIA_CONTROL",
                    {"command": cmd, "target": app, "type": "app"},
                    0.95,
                    matched_by="media.app_targeted",
                    entities={"target": app, "command": cmd},
                )

    # Browser tab controls — handled before browser/media fallback so
    # "go to next tab" / "exit current tab" do not become MEDIA_CONTROL.
    if re.search(r"\b(?:go\s+to\s+|switch\s+to\s+|move\s+to\s+|next)\s*next\s+tab\b|\bnext\s+(?:browser\s+)?tab\b", low):
        return _mk("KEYBOARD", {"key": "ctrl+tab"}, 0.94,
                   matched_by="browser.tab_next.early")
    if re.search(r"\b(?:previous|prev|back\s+to)\s+tab\b|\bgo\s+back\s+(?:a\s+|one\s+)?tab\b", low):
        return _mk("KEYBOARD", {"key": "ctrl+shift+tab"}, 0.94,
                   matched_by="browser.tab_prev.early")
    if re.search(r"\b(?:close|exit|kill)\s+(?:current\s+|the\s+)?(?:browser\s+)?tab\b", low):
        return _mk("KEYBOARD", {"key": "ctrl+w"}, 0.94,
                   matched_by="browser.tab_close.early")
    if re.search(r"\bnew\s+(?:browser\s+)?tab\b|\bopen\s+(?:a\s+)?(?:new\s+)?tab\b", low):
        return _mk("KEYBOARD", {"key": "ctrl+t"}, 0.93,
                   matched_by="browser.tab_new.early")

    # ── Window management (JARVIS-style screen control) ────────────────────
    # "optimise screen" / "tile windows" / "minimise all" / "focus X" / etc.
    _window_ops = (
        (r"\boptimi[sz]e\s+(?:my\s+)?screen\b|\btile\s+(?:all\s+)?windows?\b|"
         r"\barrange\s+(?:my\s+)?windows?\b|\borganis[ez]e\s+(?:my\s+)?windows?\b|"
         r"\bfit\s+(?:all\s+)?windows?\b",
         "TILE_WINDOWS"),
        (r"\bminimi[sz]e\s+(?:all|everything)\b|\bshow\s+(?:my\s+)?desktop\b|"
         r"\bclear\s+(?:my\s+)?screen\b|\bhide\s+all\s+windows?\b",
         "MINIMISE_ALL"),
        (r"\bmaximi[sz]e\s+(?:current|this|the\s+window|window)\b|"
         r"\bfullscreen\s+(?:current|this|the\s+window|window)?\b|"
         r"\bmake\s+(?:this|current|window)\s+fullscreen\b",
         "MAXIMISE_WINDOW"),
        (r"\brestore\s+(?:windows?|all|everything)\b|\bunminimi[sz]e\s+all\b|"
         r"\bbring\s+back\s+(?:windows?|everything)\b",
         "RESTORE_WINDOWS"),
        (r"\bnext\s+window\b|\bswitch\s+window\b|\bcycle\s+windows?\b",
         "NEXT_WINDOW"),
        (r"\bprevious\s+window\b|\bprior\s+window\b",
         "PREVIOUS_WINDOW"),
        (r"\bworkspace\s+left\b|\bnext\s+workspace\b|\bworkspace\s+right\b|"
         r"\bswitch\s+workspace\b|\bnext\s+desktop\b|\bprevious\s+desktop\b",
         "SWITCH_WORKSPACE"),
    )
    for _wre, _waction in _window_ops:
        if re.search(_wre, low):
            args_w: Dict[str, Any] = {}
            if _waction == "SWITCH_WORKSPACE":
                if re.search(r"\b(?:left|previous|prior)\b", low):
                    args_w["direction"] = "left"
                else:
                    args_w["direction"] = "right"
            return _mk(_waction, args_w, 0.93,
                       matched_by=f"window.{_waction.lower()}")

    # Focus a specific app: "focus spotify", "switch to firefox", "bring up X"
    m = re.match(
        r"^(?:focus|switch\s+to|bring\s+up|jump\s+to|raise|activate)\s+(.+?)\s*$",
        low,
    )
    if m:
        app_name = m.group(1).strip().rstrip("?.!,;:")
        if app_name and len(app_name.split()) <= 3:
            return _mk("FOCUS_APP", {"name": app_name}, 0.9,
                       matched_by="window.focus_app",
                       entities={"name": app_name})

    # ── Per-service quick commands ─────────────────────────────────────────
    # "next song on spotify", "next video on youtube",
    # "pause spotify", "pause youtube", "resume soundcloud", "volume up"
    m = re.search(
        r"\b(?:next|skip)\s+(?:song|track|video|episode|item|clip|chapter)\s+on\s+"
        r"(spotify|youtube|soundcloud|netflix|prime(?:\s+video)?|primevideo|"
        r"disney(?:\+|\s*plus)?|disneyplus|hulu|twitch|mpv|local|system)\b",
        low,
    )
    if m:
        target = m.group(1).strip().lower().replace(" ", "")
        target = {"prime": "primevideo", "primevideo": "primevideo",
                  "disney": "disneyplus", "disney+": "disneyplus",
                  "disneyplus": "disneyplus"}.get(target, target)
        return _mk("MEDIA_CONTROL", {"command": "next", "target": target,
                                     "type": "service"}, 0.94,
                   matched_by="media.next_on_service",
                   entities={"target": target, "command": "next"})
    m = re.search(
        r"\b(?:previous|prev|back)\s+(?:song|track|video|episode|item|clip|chapter)\s+on\s+"
        r"(spotify|youtube|soundcloud|netflix|prime(?:\s+video)?|primevideo|"
        r"disney(?:\+|\s*plus)?|disneyplus|hulu|twitch|mpv|local|system)\b",
        low,
    )
    if m:
        target = m.group(1).strip().lower().replace(" ", "")
        target = {"prime": "primevideo", "disney": "disneyplus",
                  "disney+": "disneyplus"}.get(target, target)
        return _mk("MEDIA_CONTROL", {"command": "previous", "target": target,
                                     "type": "service"}, 0.94,
                   matched_by="media.prev_on_service",
                   entities={"target": target, "command": "previous"})

    # Browser/video media
    if any(k in low for k in ["netflix", "youtube", "browser", "tab",
           "video", "prime", "disney", "twitch", "hulu", "bro", "brows"]):
        cmd = _canonical_media_command(low)
        if cmd:
            if "forward" in low:
                cmd = "seek_forward"
            elif "rewind" in low:
                cmd = "seek_backward"
            return _mk(
                "MEDIA_CONTROL",
                {"command": cmd, "type": "browser", "target": "browser"},
                0.9,
                matched_by="media.browser",
                entities={"command": cmd},
            )

    # Generic media control
    media_keywords = [
        "media",
        "music",
        "audio",
        "song",
        "track",
        "player",
        "spotify"]
    exact_bare_media = {
        "pause": ("PAUSE_MEDIA", 0.88),
        "play": ("PLAY_MEDIA", 0.88),
        "resume": ("PLAY_MEDIA", 0.88),
        "stop": ("STOP_MEDIA", 0.85),
        "next": ("NEXT_MEDIA", 0.88),
        "next song": ("NEXT_MEDIA", 0.88),
        "next track": ("NEXT_MEDIA", 0.88),
        "previous": ("PREVIOUS_MEDIA", 0.88),
        "prev": ("PREVIOUS_MEDIA", 0.88),
        "previous song": ("PREVIOUS_MEDIA", 0.88),
        "previous track": ("PREVIOUS_MEDIA", 0.88),
    }
    if low in exact_bare_media:
        action, conf = exact_bare_media[low]
        return _mk(action, {}, conf, matched_by="media.bare_command",
                   entities={"command": low})

    if any(k in low for k in media_keywords):
        if re.search(r"\bstop\s+(?:the\s+)?(?:media|music|spotify)\b", low):
            return _mk("STOP_MEDIA", {}, 0.95, matched_by="media.stop_legacy")
        if re.search(r"\bpause\s+(?:the\s+)?(?:media|music|spotify)\b", low):
            return _mk("PAUSE_MEDIA", {}, 0.9, matched_by="media.pause_legacy")
        if re.search(
                r"\b(play|resume|start)\s+(?:the\s+)?(?:media|music|spotify)\b", low):
            return _mk("PLAY_MEDIA", {}, 0.9, matched_by="media.play_legacy")

    # "play X by Y" / "play X from Z" / "play some jazz" / "play movie soundtrack"
    _play_specific_m = re.match(
        r"^play\s+(?:me\s+|some\s+)?(.+?)(?:\s+on\s+(\w+))?$", raw, re.I
    )
    if _play_specific_m:
        query = _play_specific_m.group(1).strip()
        target = (_play_specific_m.group(2) or "").strip() or None
        # Only route as specific if it's not a bare "play" or "play media"
        if query and query.lower() not in ("media", "music", "audio", ""):
            return _mk("PLAY_MEDIA", {"query": query, "target": target}, 0.92,
                       matched_by="media.play_specific",
                       entities={"query": query, "target": target})

    # "shuffle" / "shuffle music" / "shuffle on"
    if re.match(r"^shuffle\b", low):
        return _mk("SHUFFLE_MEDIA", {}, 0.95, matched_by="media.shuffle")

    # "repeat" / "repeat track" / "loop"
    if re.match(r"^(?:repeat|loop)\b", low):
        return _mk("REPEAT_MEDIA", {}, 0.95, matched_by="media.repeat")

    # ------------------------------------------------------------
    # 5) TIME / DATE / CAPABILITIES
    # ------------------------------------------------------------
    if any(re.search(p, low) for p in [
        r"\bwhat(?:'?s|\s+is)?\s+(?:the\s+)?time\b",
        r'\bcurrent time\b', r'\bclock\b', r'^time[?!.\s]*$', r'\btell me the time\b',
        r'\bwhat\s+time\s+is\s+it\b',
    ]):
        return _mk("TIME", {}, 1.0, matched_by="system.time")

    # Pre-guard: conversational openers mean this sentence is NOT a date request
    # even if it contains the word "date" (e.g. "yeah that's fair enough i have
    # asked you what the date and time is quite a bit lately").
    # CREATE_FILE: "create/make/write/save a file called PATH containing CONTENT
    # [, then read it back]". Requires both the word 'file' and a path with an
    # extension, so it can't steal "write a function/script". Runs before DATE
    # so "…containing today's date…" no longer answers with a bare date.
    if re.search(r"\b(?:create|make|write|save|generate)\s+(?:a\s+|an\s+|the\s+|new\s+)*[a-z]*\s*file\b", low):
        _cf_path_m = (
            re.search(r"(?:called|named|at|to|in)\s+[\"']?([~/]?[\w./\-]+\.[A-Za-z0-9]{1,8})", raw)
            or re.search(r"([~/][\w./\-]*\.[A-Za-z0-9]{1,8})", raw)
            or re.search(r"\b([\w.\-]+\.[A-Za-z0-9]{1,6})\b", raw)
        )
        if _cf_path_m:
            _cf_path = _cf_path_m.group(1)
            _cf_content_m = re.search(
                r"(?:containing|with\s+(?:the\s+)?(?:content|contents|text)|that\s+says|with)\s+(.+?)"
                r"(?:,?\s*(?:then|and\s+(?:then\s+)?read|and\s+read\s+it\s+back)\b|[.!?]?\s*$)",
                raw, re.IGNORECASE)
            _cf_content = (_cf_content_m.group(1).strip() if _cf_content_m else "")
            return _mk("CREATE_FILE", {"path": _cf_path, "content": _cf_content},
                       0.96, matched_by="fs.create_file")

    _date_conv_starters = frozenset({
        "yeah", "yes", "yep", "yup", "no", "nope", "ok", "okay",
        "so", "well", "fair", "right", "sure", "true", "exactly",
        "indeed", "agreed", "alright", "fine", "cool",
    })
    _date_anti_signals = (
        "i have asked", "i've asked", "i asked", "i said", "i told",
        "i keep asking", "i've been asking", "i was asking",
        "asked you what", "asked about the date",
    )
    _first_word_low = low.split()[0] if low.split() else ""
    _is_date_conv = (
        _first_word_low in _date_conv_starters
        or any(s in low for s in _date_anti_signals)
    )
    # File-command guard: "create/write/make/save a file … today's date …, then
    # read it back" is a file operation, not a date query — don't let "today's
    # date" hijack it into a bare DATE answer. (Fix: issue #5 DATE misroute.)
    _file_command = bool(
        re.search(r"\b(?:create|write|make|save|append|generate|put)\b[^.?!]*\bfile\b", low)
        or re.search(r"\bread it back\b", low)
        or re.search(r"/\S*\.(?:txt|py|md|json|csv|sh|log|ini|cfg|yaml|yml)\b", low)
    )
    if not _is_date_conv and not _file_command and any(re.search(p, low) for p in [
        r"\bwhat(?:'?s|\s+is)?\s+(?:the\s+)?date\b",
        r'\bcurrent date\b',
        # today's date / today is the date — no greedy .* (would match "update")
        r"\btoday'?s?\s+(?:is\s+the\s+|the\s+)?date\b",
        r'^date[?!.\s]*$',
        r"\bwhat(?:'s| is) today\b",
        r'\bwhat day is it\b', r'\bwhat day is this\b',
        r"\bwhat'?s?\s+the\s+day\b", r"\bwhat'?s?\s+the\s+days\b",
        r'\bwhat days\b', r'\bwhat is the day\b', r'\bday is it\b',
    ]):
        return _mk("DATE", {"original_query": text}, 1.0, matched_by="system.date")

    if (
        re.search(r"\b(?:list|show)\s+(?:me\s+)?(?:all\s+(?:of\s+)?)?(?:your\s+)?capabilities\b", low)
        or re.search(r"\bfull\s+list\s+of\s+(?:your\s+)?capabilities\b", low)
        or low in ("capabilities", "what can you do", "what can you do?")
        or re.search(r"\b(what|which|list|show)\b.{0,25}\b(agents?|capabilities|skills|actions|tools)\b", low)
        or re.search(r"\bwhat agents\b|\bwhat can you do\b|\bwhat are you capable\b|\byour agents\b|\byour capabilities\b|\byour skills\b", low)
    ):
        return _mk("LIST_CAPABILITIES", {}, 1.0,
                   matched_by="system.capabilities")

    if re.search(r"\b(?:check|what is)\s+chronal\s+alignment\b", raw, re.I):
        return _mk("TIME", {}, 1.0, matched_by="alias.chronal_alignment")

    # Alarm with am/pm format: "set alarm for 7am", "alarm at 8pm"
    _ampm_m = re.search(
        r"\balarm\s+(?:for\s+|at\s+)?(\d{1,2})\s*([ap]m)\b", low)
    if _ampm_m:
        _hour = int(_ampm_m.group(1))
        _ampm = _ampm_m.group(2)
        if _ampm == "pm" and _hour != 12:
            _hour += 12
        elif _ampm == "am" and _hour == 12:
            _hour = 0
        _alarm_time = f"{_hour:02d}:00"
        return _mk("SET_ALARM", {"time": _alarm_time}, 0.95, matched_by="timer.set_alarm_loose",
                   entities={"time": _alarm_time})

    # ------------------------------------------------------------
    # 5b) ALARM / TIMER
    # ------------------------------------------------------------
    m = re.search(
        r"\b(?:(?:set|start|create)\s+(?:a\s+)?)?(?:timer|countdown)\s+(?:for\s+)?(\d+)\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?)\b",
        low)
    if m:
        val = int(m.group(1))
        unit = m.group(2).lower()
        if unit.startswith("min"):
            val *= 60
        elif unit.startswith("hour") or unit.startswith("hr"):
            val *= 3600
        return _mk("SET_TIMER", {"duration": val}, 0.98,
                   matched_by="timer.set_duration", entities={"seconds": val})

    m = re.search(
        r"\b(?:(?:set|create)\s+(?:a\s+)?)?(?:alarm|reminder)\s+(?:for\s+)?(\d{1,2}[:.]\d{2})\b",
        low)
    if m:
        alarm_time = m.group(1).replace(".", ":")
        return _mk("SET_ALARM", {"time": alarm_time}, 0.98,
                   matched_by="timer.set_alarm", entities={"time": alarm_time})

    m = re.search(
        r"\b(?:set|create)\s+(?:a\s+)?(?:alarm|timer|reminder)\b",
        low)
    if m:
        # Try to find a time anywhere in the string
        time_m = re.search(r"(\d{1,2}[:.]\d{2})", raw)
        dur_m = re.search(
            r"(\d+)\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?)", low)
        if time_m:
            alarm_time = time_m.group(1).replace(".", ":")
            return _mk("SET_ALARM", {"time": alarm_time}, 0.95,
                       matched_by="timer.set_alarm_loose", entities={"time": alarm_time})
        elif dur_m:
            val = int(dur_m.group(1))
            unit = dur_m.group(2).lower()
            if unit.startswith("min"):
                val *= 60
            elif unit.startswith("hour") or unit.startswith("hr"):
                val *= 3600
            return _mk("SET_TIMER", {
                       "duration": val}, 0.95, matched_by="timer.set_duration_loose", entities={"seconds": val})
        return _mk("CHAT", {"message": raw}, 0.6,
                   matched_by="timer.no_time_found")

    # ------------------------------------------------------------
    # 6) FILE SYSTEM / PATH / DIRECTORY
    # ------------------------------------------------------------
    m = re.match(
        r"^(?:list|show|read)\s+(?:me\s+)?(?:my\s+|the\s+)?"
        r"(?:files?|contents?|directory|folder)\s+"
        r"(?:(?:in|inside|of)\s+)?(?:my\s+|the\s+)?(.+)$",
        raw,
        re.I)
    if m:
        path = _expand_common_dir(m.group(1).strip())
        return _mk("LIST_DIR", {
                   "path": path}, 0.95, matched_by="fs.list_dir_explicit", entities={"path": path})

    if re.search(
            r"\b(?:list|show)\s+(?:my\s+|the\s+)?project\s+files?\b", raw, re.I):
        return _mk("LIST_DIR", {"path": "."}, 0.9,
                   matched_by="fs.list_project_files")

    if re.search(
            r"\b(list|show)\s+(?:the\s+)?(?:files?|contents?|directory)\s+(?:in\s+)?(?:the\s+)?(?:project|current)\b", raw, re.I):
        return _mk("LIST_DIR", {"path": "."}, 0.9,
                   matched_by="fs.list_project")

    if re.match(r"^(?:list|show)\s+directory\s*$", raw, re.I):
        return _mk("LIST_DIR", {"path": "."}, 0.9,
                   matched_by="fs.list_dir_default")

    if re.match(
            r"^(?:open|launch|start|show)\s+(?:the\s+)?(?:home|home\s+(?:folder|directory)|file\s+manager|files?)\b", low):
        return _mk("OPEN_FILE_SYSTEM", {
                   "path": "~"}, 0.98, matched_by="fs.open_home")

    if re.search(r"\b(?:access|open|launch)\s+storage\s+matrix\b", raw, re.I):
        return _mk("OPEN_FILE_SYSTEM", {"path": "~"},
                   1.0, matched_by="alias.storage_matrix")

    # ------------------------------------------------------------
    # 6.5) PLUGIN ROUTER BRIDGE: explicit plugin-backed actions
    # ------------------------------------------------------------
    # Keep these patterns explicit. Do not hijack broad natural language.
    # Generic "search for X" should remain browser/search routing unless
    # the user explicitly asks for web/plugin/search-online behavior.

    # Web plugin
    _web_m = re.match(
        r"^(?:web\s+search|search\s+the\s+web\s+for|search\s+online\s+for|online\s+search\s+for|internet\s+search\s+for)\s+(.+)$",
        raw,
        re.I,
    )
    if _web_m:
        query = _web_m.group(1).strip()
        if query:
            return _mk("WEB_SEARCH", {"query": query}, 0.96, matched_by="plugin.web_search",
                       entities={"query": query})

    # TTS plugin
    _speak_m = re.match(
        r"^(?:speak|say|read\s+aloud|tts)\s+(.+)$",
        raw,
        re.I,
    )
    if _speak_m:
        text_to_say = _speak_m.group(1).strip()
        if text_to_say:
            return _mk("SPEAK", {"text": text_to_say}, 0.96, matched_by="plugin.tts_speak",
                       entities={"text": text_to_say})

    # System stats plugin
    if re.match(r"^(?:system\s+stats|system\s+statistics|resource\s+usage|show\s+system\s+stats)$", low):
        return _mk("SYSTEM_STATS", {}, 0.96, matched_by="plugin.system_stats")

    if re.match(r"^(?:cpu\s+usage|processor\s+usage|show\s+cpu\s+usage|how\s+busy\s+is\s+the\s+cpu)$", low):
        return _mk("CPU_USAGE", {}, 0.96, matched_by="plugin.cpu_usage")

    if re.match(r"^(?:ram\s+usage|memory\s+usage|show\s+ram\s+usage|show\s+memory\s+usage|how\s+much\s+ram\s+is\s+used)$", low):
        return _mk("RAM_USAGE", {}, 0.96, matched_by="plugin.ram_usage")

    # Pomodoro plugin
    if re.match(r"^(?:start\s+pomodoro|begin\s+pomodoro|pomodoro\s+start)(?:\s+timer)?$", low):
        return _mk("POMODORO_START", {}, 0.96, matched_by="plugin.pomodoro_start")

    if re.match(r"^(?:stop\s+pomodoro|end\s+pomodoro|cancel\s+pomodoro|pomodoro\s+stop)$", low):
        return _mk("POMODORO_STOP", {}, 0.96, matched_by="plugin.pomodoro_stop")

    if re.match(r"^(?:pomodoro\s+status|show\s+pomodoro|pomodoro)$", low):
        return _mk("POMODORO_STATUS", {}, 0.94, matched_by="plugin.pomodoro_status")

    # Notes plugin
    _new_note_m = re.match(
        r"^(?:new\s+note|create\s+note|write\s+note)\s+(.+)$",
        raw,
        re.I,
    )
    if _new_note_m:
        note_text = _new_note_m.group(1).strip()
        if note_text:
            return _mk("NEW_NOTE", {"text": note_text, "content": note_text}, 0.96,
                       matched_by="plugin.notes_new", entities={"text": note_text})

    _search_notes_m = re.match(
        r"^(?:search\s+notes\s+for|find\s+note\s+about|find\s+notes\s+about|search\s+my\s+notes\s+for)\s+(.+)$",
        raw,
        re.I,
    )
    if _search_notes_m:
        query = _search_notes_m.group(1).strip()
        if query:
            return _mk("SEARCH_NOTES", {"query": query}, 0.96, matched_by="plugin.notes_search",
                       entities={"query": query})

    if re.match(r"^(?:list\s+notes|show\s+notes|show\s+my\s+notes|notes\s+list)$", low):
        return _mk("LIST_NOTES", {}, 0.96, matched_by="plugin.notes_list")

    # Smart-home plugin
    _smart_m = re.match(
        r"^(?:smart\s+home|home\s+automation)\s+(.+)$",
        raw,
        re.I,
    )
    if _smart_m:
        command = _smart_m.group(1).strip()
        if command:
            return _mk("SMART_HOME", {"command": command, "text": command}, 0.95,
                       matched_by="plugin.smart_home", entities={"command": command})


    # ------------------------------------------------------------
    # 7) URL / BROWSER
    # ------------------------------------------------------------
    if re.match(r"^(?:open|launch)\s+url\s+(.+)$", raw, re.I):
        url = re.match(
            r"^(?:open|launch)\s+url\s+(.+)$",
            raw,
            re.I).group(1).strip()
        return _mk("OPEN_URL", {"url": _normalize_url(url)},
                   0.98, matched_by="web.open_url_explicit")

    m = re.match(r"^(?:open|launch)\s+(https?://\S+)\s*$", raw, re.I)
    if m:
        return _mk("OPEN_URL", {"url": m.group(1)}, 0.98,
                   matched_by="web.open_url_with_scheme")

    if re.search(r"\b(?:open|launch|access|start)\s+network\s+browser\b", low):
        return _mk("OPEN_BROWSER", {}, 0.98,
                   matched_by="web.browser_alias_network")

    if re.match(
            r"^(?:open|launch|start)\s+(?:the\s+)?(?:browser|web browser|internet browser|browse the web)\s*$", low):
        return _mk("OPEN_BROWSER", {}, 0.98, matched_by="web.browser_explicit")

    if re.match(r"^(?:open|launch|start)\s+(?:the\s+)?(?:internet|web)\b", low):
        return _mk("OPEN_BROWSER", {}, 0.98,
                   matched_by="web.browser_internet_alias")

    # Named site + optional search: "open youtube and search for cats"
    _BROWSER_SITES = {
        "youtube": "https://www.youtube.com",
        "netflix": "https://www.netflix.com",
        "gmail": "https://mail.google.com",
        "google": "https://www.google.com",
        "wikipedia": "https://www.wikipedia.org",
        "reddit": "https://www.reddit.com",
        "github": "https://www.github.com",
        "twitter": "https://www.twitter.com",
        "twitch": "https://www.twitch.tv",
        "prime": "https://www.primevideo.com",
        "disney": "https://www.disneyplus.com",
        "hulu": "https://www.hulu.com",
    }
    _site_m = re.match(
        r"^(?:open|launch|go\s+to|navigate\s+to)\s+(\w+)(?:\s+and\s+search\s+(?:for\s+)?(.+))?$",
        raw, re.I)
    if _site_m:
        site_key = _site_m.group(1).lower()
        search_q = (_site_m.group(2) or "").strip()
        if site_key in _BROWSER_SITES:
            base = _BROWSER_SITES[site_key]
            import urllib.parse as _up
            if search_q:
                if "youtube" in base:
                    url = "https://www.youtube.com/results?search_query=" + \
                        _up.quote_plus(search_q)
                else:
                    url = "https://www.google.com/search?q=" + \
                        _up.quote_plus(search_q)
            else:
                url = base
            return _mk("OPEN_URL", {"url": url, "query": search_q},
                       0.97, matched_by="web.site_open", entities={"url": url})

    # Multiple sites: "open wikipedia and google" / "open wikipedia, google
    # and reddit"
    _multi_m = re.match(
        r"^(?:open|launch)\s+(?:multiple\s+tabs?\s*(?:in\s+\w+)?\s*[:,]?\s*)?(.+)$",
        raw,
        re.I)
    if _multi_m:
        raw_sites = _multi_m.group(1).lower()
        parts = re.split(r"\s+and\s+|\s*,\s*|\s+one\s+for\s+|;", raw_sites)
        urls = []
        for p in parts:
            key = p.strip().split()[0] if p.strip() else ""
            if key in _BROWSER_SITES:
                urls.append(_BROWSER_SITES[key])
        if len(urls) > 1:
            return _mk("OPEN_BROWSER", {"url": urls[0], "urls": urls},
                       0.97, matched_by="web.multi_tab", entities={"urls": urls})

    # "browse to X.com" / "go to X.com" / "navigate to X"
    m_browse = re.match(
        r"^(?:browse\s+to|go\s+to|navigate\s+to|visit)\s+(.+)$",
        raw,
        re.I)
    if m_browse:
        target = m_browse.group(1).strip()
        if target:
            url = target if re.match(
                r"https?://", target) else "https://" + target.lstrip("/")
            return _mk("OPEN_URL", {"url": url}, 0.97,
                       matched_by="web.browse_to", entities={"url": url})

    # Guard: "search your memory/memories ..." must never fall through to web search.
    m = re.match(r"^(?:search\s+(?:for\s+)?)(.+)$", raw, re.I)
    if m:
        query = m.group(1).strip()
        if query and not re.match(r"(?:your\s+)?memor(?:y|ies)\b", query, re.I):
            return _mk("OPEN_BROWSER", {"query": query}, 0.95,
                       matched_by="web.search", entities={"query": query})

    # ------------------------------------------------------------
    # 8) SCREENSHOT / INPUT / VOLUME
    # ------------------------------------------------------------
    if re.search(
            r"\b(take|capture)\s+(a\s+)?(screenshot|screen\s*shot|screen\s*capture|screen)\b", raw, re.I):
        region = "area" if re.search(
            r"\b(area|region|selection|part)\b", raw, re.I) else "full"
        return _mk("SCREENSHOT", {"region": region}, 0.98,
                   matched_by="io.screenshot", entities={"region": region})

    # Volume (order matters: unmute before mute)
    if re.search(
            r"\bmax(?:imum)?\s+volume\b|\bvolume\s+max\b|\bfull\s+volume\b", low):
        return _mk("VOLUME", {"direction": "set", "level": 100},
                   0.99, matched_by="audio.volume_max")

    m = re.search(
        r"\b(?:(?:set|change)\s+volume(?:\s+to)?|volume\s+set)\s+(\d+)%?",
        raw,
        re.I)
    if m:
        level = max(0, min(100, int(m.group(1))))
        return _mk("VOLUME", {"direction": "set", "level": level}, 0.98,
                   matched_by="audio.volume_set", entities={"level": level})

    if re.search(r"\bunmute\b", low):
        return _mk("VOLUME", {"direction": "unmute"},
                   0.98, matched_by="audio.unmute")

    if re.search(r"\bmute\b", low):
        return _mk("VOLUME", {"direction": "mute"},
                   0.98, matched_by="audio.mute")

    _vol_up_m = re.search(
        r"\b(?:volume\s+up|turn\s+up\s+(?:the\s+)?(?:volume|sound|audio)|"
        r"increase\s+(?:the\s+)?(?:volume|sound|audio)|"
        r"raise\s+(?:the\s+)?(?:volume|sound|audio)|louder)\b",
        low,
    )
    if _vol_up_m:
        _pct = re.search(r"\b(?:by\s+)?(\d{1,3})\s*%?\b", low[_vol_up_m.end():])
        delta = max(1, min(100, int(_pct.group(1)))) if _pct else 15
        return _mk("VOLUME", {"direction": "up", "delta": delta},
                   0.95, matched_by="audio.volume_up")

    if re.search(r"\b(lower|decrease|volume\s+down)\b", low):
        return _mk("VOLUME", {"direction": "down", "delta": 15},
                   0.95, matched_by="audio.volume_down")

    # Browser tab controls — keyboard shortcuts for tab navigation.
    if re.search(r"\b(?:go\s+to\s+|switch\s+to\s+|move\s+to\s+|next)\s*(?:next\s+)?tab\b|\bnext\s+(?:browser\s+)?tab\b", low):
        return _mk("KEYBOARD", {"key": "ctrl+tab"}, 0.93,
                   matched_by="browser.tab_next")
    if re.search(r"\b(?:previous|prev|back\s+to)\s+tab\b|\bgo\s+back\s+(?:a\s+|one\s+)?tab\b", low):
        return _mk("KEYBOARD", {"key": "ctrl+shift+tab"}, 0.93,
                   matched_by="browser.tab_prev")
    if re.search(r"\b(?:close|exit|kill)\s+(?:current\s+|the\s+)?(?:browser\s+)?tab\b", low):
        return _mk("KEYBOARD", {"key": "ctrl+w"}, 0.93,
                   matched_by="browser.tab_close")
    if re.search(r"\bnew\s+(?:browser\s+)?tab\b|\bopen\s+(?:a\s+)?(?:new\s+)?tab\b", low):
        return _mk("KEYBOARD", {"key": "ctrl+t"}, 0.92,
                   matched_by="browser.tab_new")

    # Screen-locator routes — find/click visible UI text on the screen.
    m = re.search(r"\b(?:find|locate|where\s+is)\s+(?:the\s+)?(.+?)\s+on\s+(?:the\s+)?screen\b", low)
    if m:
        query = m.group(1).strip()
        if query:
            return _mk("SCREEN_LOCATE", {"query": query}, 0.93,
                       matched_by="screen.locate", entities={"query": query})
    m = re.search(r"\b(?:click|tap|press)\s+(?:on\s+)?(?:the\s+)?(.+?)\s+on\s+(?:the\s+)?screen\b", low)
    if m:
        query = m.group(1).strip()
        if query:
            return _mk("SCREEN_LOCATE", {"query": query, "click": True}, 0.94,
                       matched_by="screen.locate_click", entities={"query": query})

    # Keyboard typing/press
    m = re.match(r"^type\s+(.+)$", raw, re.I)
    if m:
        typed = m.group(1).strip()
        if typed:
            return _mk("KEYBOARD", {
                       "type": typed}, 0.95, matched_by="io.keyboard_type", entities={"text": typed})

    m = re.search(r"\b(press|hit)\s+(enter|return)\b", raw, re.I)
    if m:
        return _mk("KEYBOARD", {"key": "Return"}, 0.95,
                   matched_by="io.keyboard_enter")

    m = re.search(r"\b(press|hit)\s+([a-zA-Z0-9_\-]+)\b", raw, re.I)
    if m:
        key = m.group(2)
        # Guard: only fire KEYBOARD when the captured word is actually a
        # recognised key name.  "hit me with it", "hit that button" etc. must
        # NOT route here — "me", "that", "it" are not keys.
        _KNOWN_KEYS = frozenset({
            # navigation / control
            "enter", "return", "space", "tab", "escape", "esc", "backspace",
            "delete", "del", "insert", "ins", "home", "end",
            "pageup", "pagedown", "page_up", "page_down",
            # arrows
            "up", "down", "left", "right",
            # function keys
            "f1", "f2", "f3", "f4", "f5", "f6",
            "f7", "f8", "f9", "f10", "f11", "f12",
            # modifiers (used alone or named in combos)
            "ctrl", "control", "alt", "shift", "super", "win", "meta",
            # punctuation / symbol names
            "comma", "period", "dot", "slash", "backslash",
            "minus", "plus", "equals", "semicolon", "quote",
            "bracketleft", "bracketright",
            # single alpha keys a-z
            "a","b","c","d","e","f","g","h","i","j","k","l","m",
            "n","o","p","q","r","s","t","u","v","w","x","y","z",
            # digits 0-9
            "0","1","2","3","4","5","6","7","8","9",
        })
        if key.lower() in _KNOWN_KEYS:
            return _mk("KEYBOARD", {"key": key}, 0.9,
                       matched_by="io.keyboard_key", entities={"key": key})

    # ------------------------------------------------------------
    # 9) CALENDAR shortcuts before generic read/show
    # ------------------------------------------------------------
    if re.match(r"^(?:show|list)\s+(?:my\s+)?calendar$", low, re.I):
        return _mk("LIST_EVENTS", {}, 0.97, matched_by="calendar.show_exact")

    # ------------------------------------------------------------
    # 10) FILE READ / FIX / SUMMARIZE / ANALYZE
    # ------------------------------------------------------------
    # Show clipboard must be checked before generic "show X" → READ_FILE
    if "clipboard" in low and "show" in low:
        return _mk("GET_CLIPBOARD", {}, 0.9, matched_by="clipboard.show")

    # Exclude habit queries from file-read
    if re.match(r"^(?:show|list|read)\s+habits?", low):
        return _mk("HABIT_STATUS", {}, 0.95, matched_by="habits.show")
    # Exclude habit queries from file-read
    if re.match(r"^(?:show|list|read)\s+habits?$", low):
        return _mk("HABIT_STATUS", {}, 0.95, matched_by="habits.show")
    m = re.match(r"^(read|show)\s+(~?/?[\w./\-]+(?:\.[\w]+)?)", raw, re.I)
    if m:
        path = m.group(2).strip()
        # Require the candidate to look like an actual path: contain a slash,
        # an extension, leading ~/, or have at least one path segment delimiter.
        # Bare English words ("me", "the") and natural-language tokens are
        # excluded so phrases like "show me physics news" do not become file
        # reads.
        looks_like_path = (
            "/" in path or "." in path or path.startswith("~")
        )
        if looks_like_path:
            return _mk("READ_FILE", {"path": path}, 0.9,
                       matched_by="file.read_show", entities={"path": path})

    m = re.search(
        r"(fix|debug|repair|correct|patch)\s+.{0,30}?([\w./~ -]+\.py)\b",
        raw,
        re.I)
    if m:
        path = m.group(2).strip()
        return _mk("FIX_FILE", {"path": path}, 0.92,
                   matched_by="file.fix_python", entities={"path": path})

    m = re.search(
        r"(fix|debug|repair|correct|patch)\s+(?:the\s+)?(?:script|file|code)(?:\s+(?:in|at|located\s+at))?\s+(.+)$",
        raw,
        re.I)
    if m:
        path = (m.group(2) or "").strip()
        extracted = _extract_path_from_text(path) or path
        return _mk("FIX_FILE", {"path": extracted}, 0.9,
                   matched_by="file.fix_generic", entities={"path": extracted})

    if re.match(r"^(?:fix|debug|repair|correct|patch)\b", low):
        guessed = _extract_path_from_text(raw)
        if guessed:
            return _mk("FIX_FILE", {
                       "path": guessed}, 0.86, matched_by="file.fix_fallback", entities={"path": guessed})

    # Message starts with a file path (dropped file + instruction format)
    # e.g. "/home/user/Ξ–χ–φ–A.pdf , tell me what this is about"
    if raw.strip().startswith(("/", "~/")):
        if ".pdf" in raw.lower():
            _pdf_p = _extract_pdf_path(raw)
            if _pdf_p:
                return _mk("ANALYZE_PDF", {"path": _pdf_p, "instruction": raw},
                           0.95, matched_by="analyze.path_first_pdf")

    # summarize / analyse / read / look at: conversation vs file/path
    # Matches both:
    #   "summarise /path"  "analyse and read /path"  "read /path"
    #   "can you look at /path"  "look at, read, and analyse /path"
    m = re.match(
        r"^(?:please\s+)?(?:can\s+you\s+)?(?:summari[sz]e|analyse|analyze|read|look\s+at)"
        r"(?:[,\s]+(?:and\s+)?(?:summari[sz]e|analyse|analyze|read|look\s+at))*"
        r"[,\s]+(?:this\s+)?(.+)$",
        raw, re.I,
    ) or re.match(r"^(?:please\s+)?(?:summari[sz]e|analyse|analyze|read)\s+(.+)$", raw, re.I)
    if m:
        target = m.group(1).strip()
        # If target contains an absolute path, extract from the first / or ~/
        # This handles typos, extra verbs, and multi-word prefixes cleanly.
        _path_hit = re.search(r'(?:^|[\s,])([~/][^\s]+)', target)
        if _path_hit:
            target = _path_hit.group(1).strip()
        else:
            # Fallback: strip leading filler words
            target = re.sub(
                r"^(?:and\s+)?(?:summari[sz]e|analyse|analyze|summaise|read|look\s+at|the|this|file|directory|folder)\s+",
                "", target, flags=re.I,
            ).strip()
        # If the target contains a PDF, use the robust extractor to avoid
        # Unicode/em-dash path issues (captures everything before the extension)
        if ".pdf" in target.lower():
            _pdf_path = _extract_pdf_path(raw)
            if _pdf_path:
                return _mk("ANALYZE_PDF", {"path": _pdf_path, "instruction": raw},
                           0.95, matched_by="analyze.summarize_pdf")
        expanded = os.path.expanduser(target)
        _has_file_ext = bool(re.search(r'\.[a-zA-Z0-9]{1,5}$', target.strip()))
        _has_path_prefix = target.strip().startswith(("/", "~", "./", "../"))
        _path_exists = os.path.exists(expanded)
        if (_has_path_prefix or _path_exists or _has_file_ext):
            abs_path = os.path.abspath(expanded)
            global _last_used_path
            if _path_exists:
                _last_used_path = abs_path
            # Route PDFs → ANALYZE_PDF, CSVs → ANALYZE_CSV, everything else →
            # SUMMARIZE_FILE
            if abs_path.lower().endswith(".pdf"):
                return _mk("ANALYZE_PDF", {"path": abs_path, "instruction": raw},
                           0.95, matched_by="analyze.summarize_pdf")
            if abs_path.lower().endswith(".csv"):
                return _mk("ANALYZE_CSV", {"path": abs_path},
                           0.95, matched_by="analyze.summarize_csv")
            if abs_path.lower().endswith(
                    (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".tif")):
                return _mk("ANALYZE_IMAGE", {"path": abs_path},
                           0.95, matched_by="analyze.image")
            return _mk("SUMMARIZE_FILE", {
                       "path": abs_path}, 0.92, matched_by="analyze.summarize_file")
        # Referential: "summarise the pdfs in that directory" with no explicit path
        if any(w in low for w in ["pdf", "pdfs"]) and any(
                w in low for w in ["that", "there", "those", "the folder", "the directory"]):
            if _last_used_path and os.path.isdir(_last_used_path):
                return _mk("ANALYZE_PDF_FOLDER", {"folder": _last_used_path, "recursive": True},
                           0.90, matched_by="analyze.pdf_referential")
        # Referential: "analyse the recent/last screenshot" → resolve newest
        # screenshot file and OCR it, rather than confabulating from memory.
        if "screenshot" in low:
            _shot = _eli_latest_screenshot()
            if _shot:
                return _mk("ANALYZE_IMAGE", {"path": _shot},
                           0.93, matched_by="analyze.recent_screenshot")
        # Live screen: "look at my screen", "read the screen", "analyse my display"
        # → capture + vision, not a memory lookup.
        if re.search(r"\b(?:my|the)\s+(?:screen|display|monitor)\b", low):
            return _mk("SCREEN_READ_ANALYZE", {}, 0.92,
                       matched_by="screen.analyze_referential")
        # A bare generic file-noun ("read the document", "summarize the file")
        # with no actual filename/path is NOT a memory topic — there is nothing
        # stored to "recall". Defer to CHAT so ELI asks which file, rather than
        # recalling a phantom "document"/"file" topic.
        if target.strip().lower() in {
            "document", "documents", "doc", "docs", "file", "files",
            "it", "this", "that",
        }:
            return _mk("CHAT", {"message": raw}, 0.6, matched_by="chat.vague_file_ref")
        return _mk("MEMORY_RECALL", {"query": target},
                   0.8, matched_by="memory.summarize_topic")

    # PDF analysis
    if any(w in low for w in ["pdf", "pdfs"]) and any(w in low for w in [
            "analyze", "analyse", "summarize", "summarise", "read", "extract"]):
        path_match = _extract_pdf_path(raw)
        if path_match:
            return _mk("ANALYZE_PDF", {"path": path_match, "instruction": raw}, 0.95,
                       matched_by="analyze.pdf", entities={"path": path_match})
        # Referential: "the pdfs in that directory" → use last resolved path
        _is_referential = any(w in low for w in ["that", "there", "those", "the folder", "the directory"])
        if _is_referential and _last_used_path and os.path.isdir(_last_used_path):
            return _mk("ANALYZE_PDF_FOLDER", {"folder": _last_used_path, "recursive": True},
                       0.90, matched_by="analyze.pdf_referential")
        return _mk("ANALYZE_PDF", {"path": ".", "instruction": raw},
                   0.85, matched_by="analyze.pdf_default")

    # CSV analysis
    if any(w in low for w in ["csv", "spreadsheet"]) or (
            any(w in low for w in ["read", "show"]) and ".csv" in low):
        if any(w in low for w in [
               "analyze", "analyse", "summarize", "summarise", "read", "parse", "show"]):
            m = re.search(r'([~/\w.\-/ ]+\.csv)\b', raw, re.I)
            if m:
                return _mk("ANALYZE_CSV", {"path": m.group(1).strip(
                )}, 0.95, matched_by="analyze.csv", entities={"path": m.group(1).strip()})

    # ------------------------------------------------------------
    # 10) DOCUMENT / NOTES / GENERATION
    # ------------------------------------------------------------
    note_m = re.match(
        r'^(?:write|save|create|make|add)\s+(?:a\s+)?notes?[:\s]+(?:saying\s+)?(.+)$',
        raw,
        re.I)
    if note_m:
        note_text = note_m.group(1).strip()
        return _mk("WRITE_NOTE", {"text": note_text}, 0.97,
                   matched_by="notes.write", entities={"text": note_text})

    note_m2 = re.match(r'^(?:write|add)\s+note\s+(.+)$', raw, re.I)
    if note_m2:
        note_text = note_m2.group(1).strip()
        return _mk("WRITE_NOTE", {"text": note_text}, 0.95,
                   matched_by="notes.add", entities={"text": note_text})

    if "generate" in low and "document" in low and not _GENERATION_COMPLAINT:
        topic = re.sub(
            r'\b(generate|create|write|document|about|on|a|the)\b',
            '',
            low).strip()
        return _mk("GENERATE_DOCUMENT", {"topic": topic or raw, "use_advanced_generator": True, "use_gguf_only": True,
                   "forbid_ollama": True}, 0.95, matched_by="doc.generate_generic", entities={"topic": topic or raw})

    m = re.search(
        r"\b(create|write|generate|draft|make|place|raise)\s+(?:a\s+)?(?:doc|document|report|notes?)\s+(?:about|on|for)\s+(.+)$",
        raw,
        re.I)
    if m:
        topic = m.group(2).strip()
        return _mk("CREATE_DOCUMENT", {"topic": topic, "format": "md", "use_advanced_generator": True, "use_gguf_only": True,
                   "forbid_ollama": True}, 0.9, matched_by="doc.generate_structured", entities={"topic": topic})

    # Data fabricator alias
    if re.search(
            r"\b(?:fabricate|create|make)\s+data\s+(?:construct|fabricator)\b", raw, re.I):
        topic_match = re.search(
            r"fabricate data construct(?:\s+about\s+|\s+on\s+)?(.+)$", raw, re.I)
        if topic_match:
            topic = topic_match.group(1).strip()
            return _mk("DATA_FABRICATOR", {
                       "topic": topic}, 0.98, matched_by="alias.data_fabricator", entities={"topic": topic})
        return _mk("DATA_FABRICATOR", {}, 0.98,
                   matched_by="alias.data_fabricator")

    # ------------------------------------------------------------
    # 11) CLIPBOARD / WEATHER / CALENDAR
    # ------------------------------------------------------------
    if any(w in low for w in ["clipboard", "copy", "paste"]):
        if "copy" in low or "set clipboard" in low:
            content = re.sub(
                r'.*(copy|set clipboard to|clipboard)\s+',
                '',
                raw,
                flags=re.I).strip()
            return _mk("SET_CLIPBOARD", {
                       "text": content}, 0.9, matched_by="clipboard.set", entities={"text": content})
        if "get" in low or "what" in low or "show" in low:
            return _mk("GET_CLIPBOARD", {}, 0.9, matched_by="clipboard.get")

    if any(w in low for w in ["weather", "forecast", "temperature"]):
        # Only route when the sentence is an actual weather *request*, not a
        # sentence that merely mentions weather as a subject/object/topic.
        _wx_request = re.search(
            r"\b(?:what(?:'s|s|\s+is|\s+will)?\s+(?:the\s+)?(?:weather|forecast|temperature)|"
            r"how(?:'s|\s+is)\s+(?:the\s+)?weather|"
            r"(?:check|get|tell\s+me|show(?:\s+me)?|give\s+me)\s+(?:the\s+)?(?:weather|forecast|temperature)|"
            r"(?:will\s+it|is\s+it|going\s+to)\s+(?:rain|snow|be\s+(?:hot|cold|warm|sunny|cloudy)))\b",
            low, re.I)
        _wx_topic = re.search(
            r"\b(?:script|code|program|file|function|task|fix|issue|error|this|that)\s+"
            r"(?:is|was|are|were|for|about)\s+(?:a\s+)?(?:weather|forecast)|"
            r"\b(?:stop|don'?t|cease|quit)\b.{0,30}\bweather\b",
            low, re.I)
        if _wx_request and not _wx_topic:
            location_match = re.search(
                r'\b(?:in|at|for)\b\s+([\w\s\-]+?)(?:\s*[,?!.]|\s+and\s+|\s+(?:provide|tell|show|give|also|then|next|tomorrow|today|forecast)|$)',
                raw,
                re.I)
            location = location_match.group(1).strip().rstrip("?.!, ") if location_match else None
            return _mk("GET_WEATHER", {"location": location, "_raw_user_text": raw}, 0.95, matched_by="info.weather", entities={
                       "location": location} if location else None)

    if any(w in low for w in ["calendar", "calender",
           "calander", "event", "appointment", "meeting"]):
        if any(w in low for w in ["show", "list",
               "my", "what", "open", "display"]):
            return _mk("LIST_EVENTS", {}, 0.95, matched_by="calendar.list")
        if any(w in low for w in ["add", "create", "schedule"]):
            return _mk("ADD_EVENT", {"text": raw}, 0.95,
                       matched_by="calendar.add", entities={"text": raw})

    # ------------------------------------------------------------
    # 12) SYSTEM SETTINGS / PANELS / ALIASES
    # ------------------------------------------------------------
    if re.search(
            r"\b(?:initiate|open|launch|access|start)\s+audio\s+(?:interface|settings)\b", raw, re.I):
        return _mk("OPEN_AUDIO_SETTINGS", {}, 1.0,
                   matched_by="alias.audio_interface")

    if re.search(
            r"\b(?:access|open|launch|start)\s+communication\s+hub\b", raw, re.I):
        return _mk("OPEN_COMMUNICATION_HUB", {}, 1.0,
                   matched_by="alias.communication_hub")

    if re.search(r"\bopen\s+power\b", raw, re.I):
        return _mk("OPEN_POWER_SETTINGS", {}, 0.95, matched_by="system.power")

    if re.match(r"^(?:open|launch|start|show)\s+(?:system\s+)?settings?\b", low):
        return _mk("OPEN_SYSTEM_SETTINGS", {}, 0.98,
                   matched_by="system.settings")

    # ------------------------------------------------------------
    # 12b) PROACTIVE DAEMON — must be before section 13 open/launch/start catch-all
    # ------------------------------------------------------------
    if (
        re.search(r"\bproactive\s+(?:daemon\s+)?(?:status|state|running)\b", low)
        or re.search(r"\b(?:status|state)\s+of\s+(?:the\s+)?proactive\s+daemon\b", low)
        or re.search(r"\bwhat(?:'s| is)\s+(?:the\s+)?status\s+of\s+(?:the\s+)?proactive\s+daemon\b", low)
    ):
        return _mk("PROACTIVE_STATUS", {}, 0.95,
                   matched_by="system.proactive_status")
    if re.search(
            r"\b(?:start|launch|run)\s+(?:proactive\s+(?:daemon|mode)|proactive)\b", low):
        return _mk("PROACTIVE_START", {}, 0.95,
                   matched_by="system.proactive_start")
    if re.search(
            r"\b(?:stop|kill|shut\s+down)\s+(?:proactive\s+(?:daemon|mode)|proactive)\b", low):
        return _mk("PROACTIVE_STOP", {}, 0.95,
                   matched_by="system.proactive_stop")

    # ------------------------------------------------------------
    # 13) OPEN / LAUNCH (apps, aliases, websites, paths)
    # ------------------------------------------------------------
    m = re.match(r"^(?:open|launch|start)\s+(.+)$", raw, re.I)
    if m:
        arg = m.group(1).strip()
        cleaned = _clean_app_name(arg)
        cleaned_low = cleaned.lower()
    m = re.match(r"^\s*(open|run|launch|start)\s+(.+?)\s*$", raw, re.I)

    m = re.match(r"^\s*open\s+((?:https?://)?[a-z0-9][a-z0-9.-]*\.[a-z]{2,}(?:/[^\s]*)?)\s*$", text_l)
    if m:
        _url = m.group(1).strip()
        if not _url.startswith(("http://", "https://")):
            _url = "https://" + _url
        return _mk(
            "OPEN_URL",
            {"url": _url},
            0.99,
            matched_by="open.domain.preempt",
            allow_chat_without_evidence=False,
        )
    if m:
        target = re.sub(r"\s+app$", "", m.group(2).strip(), flags=re.I)
        target_low = target.lower()

        generic_ide = {
            "ide", "the ide", "editor", "the editor",
            "built in ide", "built-in ide", "gui ide", "eli ide",
            "internal ide", "ide tab", "the ide tab",
        }

        if (
            target.startswith("/")
            or target.startswith("~/")
            or re.search(r"\b(folder|directory|path)\b", target, re.I)
            or target_low in {"trash", "home", "home directory"}
        ):
            return _mk("OPEN_FILE_SYSTEM", {"path": target}, 0.99, matched_by="open.filesystem.literal_preempt")

        app_aliases = {
            "vscode": "code",
            "visual studio code": "code",
            "virtual studio code": "code",
            "vs code": "code",
            "code": "code",
            "gedit": "gedit",
            "chrome": "chromium",
            "google chrome": "chromium",
            "calendar": "gnome-calendar",
            "camera": "snapshot",
        }

        if target_low in generic_ide:
            return _mk("OPEN_IDE", {"name": "ide"}, 0.99, matched_by="open.ide.literal_preempt")

        canonical = app_aliases.get(target_low, target)
        return _mk("OPEN_APP", {"name": canonical}, 0.99, matched_by="open.app.literal_preempt")
    m = re.match(r"^\s*(open|run|launch|start)\s+(.+?)\s*$", raw, re.I)
    if m:
        target = re.sub(r"\s+app$", "", m.group(2).strip(), flags=re.I)
        target_low = target.lower()

        generic_ide = {
            "ide", "the ide", "editor", "the editor",
            "built in ide", "built-in ide", "gui ide", "eli ide",
            "internal ide", "ide tab", "the ide tab",
        }

        app_aliases = {
            "vscode": "code",
            "visual studio code": "code",
            "virtual studio code": "code",
            "vs code": "code",
            "chrome": "chromium",
            "google chrome": "chromium",
            "calendar": "gnome-calendar",
            "camera": "snapshot",
        }

        if target_low in generic_ide:
            return _mk("OPEN_IDE", {"name": "ide"}, 0.99, matched_by="open.ide.literal_preempt")

        canonical = app_aliases.get(target_low, target)
        return _mk("OPEN_APP", {"name": canonical}, 0.99, matched_by="open.app.literal_preempt")

    # ------------------------------------------------------------
    # 14) SHELL EXEC (explicit only)
    # ------------------------------------------------------------
    shell_prefixes = (
        "execute ",
        "run cmd ",
        "bash ",
        "shell cmd ",
        "$ ",
        "terminal: ")
    for pfx in shell_prefixes:
        if low.startswith(pfx):
            cmd = raw[len(pfx):].strip().strip("`")
            if cmd:
                return _mk("SHELL_EXEC", {
                           "cmd": cmd}, 0.95, matched_by="shell.prefix", entities={"cmd": cmd})

    m = re.match(r'^(grep\s+.+)$', raw, re.I)
    if m:
        return _mk("SHELL_EXEC", {"cmd": m.group(
            1)}, 0.95, matched_by="shell.grep", entities={"cmd": m.group(1)})

    if re.match(r'^(ls|cat|head|tail|find|diff|wc)\s+[~/\.]', raw, re.I):
        return _mk("SHELL_EXEC", {
                   "cmd": raw}, 0.92, matched_by="shell.safeish_builtin", entities={"cmd": raw})

    m = re.match(r'^`([^`]+)`$', raw)
    if m:
        return _mk("SHELL_EXEC", {"cmd": m.group(
            1)}, 0.93, matched_by="shell.backticks", entities={"cmd": m.group(1)})

    # 14b placeholder — proactive daemon patterns moved before section 13

    # 14c) CREATE FOLDER
    m = re.match(
        r"^(?:create|make|mkdir)\s+(?:a\s+)?(?:new\s+)?(?:folder|directory|dir)(?:\s+called|\s+named)?\s+(.+)$",
        raw,
        re.I)
    if m:
        raw_name = m.group(1).strip()
        # Extract explicit path like /home/... or ~/...
        path_m = re.search(r"((?:~|/[^\s]+(?:/[^\s]+)*)/[^\s]+)", raw_name)
        if path_m:
            folder_path = path_m.group(1)
            # folder name is word before "in" or the path basename
            name_m = re.match(r"(\S+)\s+(?:in|at|inside|under)", raw_name)
            folder_name = name_m.group(
                1) if name_m else os.path.basename(folder_path)
            full_path = os.path.join(
                os.path.expanduser(folder_path),
                folder_name) if not folder_path.endswith(folder_name) else os.path.expanduser(folder_path)
        else:
            # Just take first token as folder name
            folder_name = re.split(
                r"\s+(?:in|at|inside|under|on)\s",
                raw_name)[0].strip()
            full_path = os.path.expanduser(f"~/{folder_name}")
        return _mk("CREATE_FOLDER", {"name": full_path}, 0.95,
                   matched_by="fs.create_folder", entities={"name": full_path})

    # 14d) CLOSE / KILL APP
    m = re.match(r"^(?:close|quit|kill|exit)\s+(.+)$", raw, re.I)
    if m:
        name = m.group(1).strip()
        return _mk("CLOSE_APP", {"name": name}, 0.9,
                   matched_by="system.close_app")

    # ------------------------------------------------------------
    # 15) DEFAULT CHAT
    # ------------------------------------------------------------
    m = re.match(
        r"^(?:run|execute)\s+(?:the\s+)?(?:shell\s+)?command\s+(.+)$",
        raw,
        flags=re.I)
    if m:
        cmd = m.group(1).strip()
        if cmd:
            return _mk("SHELL_EXEC", {
                       "cmd": cmd}, 0.95, matched_by="shell.run_command", entities={"cmd": cmd})

    # Bare "run <unix_command>" — match common CLI tools
    _UNIX_CMDS = {"ls", "cd", "pwd", "cat", "head", "tail", "grep", "find", "wc",
                  "date", "df", "du", "free", "top", "ps", "kill", "chmod", "chown",
                  "cp", "mv", "rm", "mkdir", "rmdir", "touch", "echo", "which", "whoami",
                  "uname", "uptime", "hostname", "ip", "ifconfig", "ping", "curl", "wget",
                  "tar", "zip", "unzip", "apt", "pip", "npm", "git", "docker", "systemctl"}
    m = re.match(r"^(?:run|execute)\s+(\S+(?:\s+.*)?)$", raw, flags=re.I)
    if m:
        parts = m.group(1).strip().split()
        if parts and parts[0].lower() in _UNIX_CMDS:
            cmd = m.group(1).strip()
            return _mk("SHELL_EXEC", {
                       "cmd": cmd}, 0.93, matched_by="shell.run_bare_unix", entities={"cmd": cmd})

    m = re.match(r"^(?:list|ls)\s+(.+)$", raw, flags=re.I)
    if m:
        captured = m.group(1).strip()
        # Extract only the path-like segment, not natural language
        path_match = re.search(r'([~/.][\w/._~-]+|/[\w/._~-]+)', captured)
        if path_match:
            path_value = path_match.group(1).strip().rstrip(".,;:")
            return _mk("LIST_DIR", {"path": path_value}, 0.98,
                       matched_by="fs.list_dir_bare", entities={"path": path_value})
        # If no path found but it's a short word, treat as relative path
        elif len(captured.split()) <= 2 and not any(w in captured.lower() for w in ("every", "all", "each", "the")):
            return _mk("LIST_DIR", {"path": captured}, 0.90,
                       matched_by="fs.list_dir_bare", entities={"path": captured})
        # Otherwise it's natural language about listing — fall through to CHAT

    # ── Disk usage queries → SHELL_EXEC ──────────────────────────────────────
    _du_match = re.search(
        r"(?:disk\s+usage|size|how\s+(?:big|large|much\s+space))\s+(?:of\s+|for\s+|in\s+)?([~/][\w/._~-]+)",
        raw, re.I
    )
    if _du_match or re.search(r"\bdu\s+[-shH]", raw):
        _du_path = _du_match.group(1).strip() if _du_match else ""
        if _du_path:
            import os as _os
            _du_path_exp = _os.path.expanduser(_du_path)
            _du_cmd = f"du -sh {_du_path_exp!r}"
        else:
            _du_cmd = raw
        return _mk("SHELL_EXEC", {"cmd": _du_cmd}, 0.95, matched_by="shell.disk_usage",
                   entities={"cmd": _du_cmd})

    # Habit status
    if re.match(r"^(?:show\s+)?habits?(?:\s+status)?$",
                low) or re.match(r"^(?:my\s+)?habits?$", low):
        return _mk("HABIT_STATUS", {}, 0.95, matched_by="habits.status")

    # ── Coverage patch: additional patterns before fallback ──

    # Power: shutdown / restart / reboot
    if re.search(
            r"\b(shutdown|shut\s+down|power\s+off|poweroff|restart|reboot)\b", low):
        return _mk("OPEN_POWER_SETTINGS", {}, 0.95, matched_by="system.power")

    # System settings (bare)
    if low.strip() in ("system settings", "settings", "preferences"):
        return _mk("OPEN_SYSTEM_SETTINGS", {}, 0.98,
                   matched_by="system.settings")

    # Skip (bare) → NEXT_MEDIA
    if low.strip() in ("skip", "skip it", "next"):
        return _mk("NEXT_MEDIA", {}, 0.88, matched_by="media.next_legacy")

    # Self test
    if re.search(r"\bself[\s_-]*test\b",
                 low) or low.strip() in ("run self test", "self test"):
        return _mk("SELF_TEST", {}, 0.95, matched_by="self.self_test")

    # Self analyze (space separated)
    if low.strip() in ("self analyze", "self analyse", "self-analyze", "self-analyse"):
        return _mk("SELF_ANALYZE", {}, 0.95, matched_by="self.analyze")

    # Google X → web search
    if re.match(r"^google\s+(.+)$", raw, re.I):
        query = re.match(r"^google\s+(.+)$", raw, re.I).group(1).strip()
        return _mk("OPEN_BROWSER", {"query": query}, 0.95, matched_by="web.search",
                   entities={"query": query})

    # Look up X → web search (but NOT "look in memory")
    if re.match(r"^look\s+up\s+(.+)$", raw, re.I):
        query = re.match(r"^look\s+up\s+(.+)$", raw, re.I).group(1).strip()
        return _mk("OPEN_BROWSER", {"query": query}, 0.93, matched_by="web.search",
                   entities={"query": query})

    # Find X → web search (generic, after memory patterns already checked)
    _find_m = re.match(
        r"^find\s+(?:me\s+)?(?:a\s+|the\s+)?(.{10,})$",
        raw,
        re.I)
    if _find_m:
        query = _find_m.group(1).strip()
        if query:
            return _mk("OPEN_BROWSER", {"query": query}, 0.90, matched_by="web.search",
                       entities={"query": query})

    # Installed plugins / plugin status
    if re.search(r"\binstalled\s+plugins\b",
                 low) or low.strip() == "plugin status":
        return _mk("PLUGIN_LIST", {"scope": "installed"},
                   0.95, matched_by="plugin.list_installed")

    # Bare unix commands: whoami, uptime, hostname, etc.
    _BARE_UNIX = {
        "whoami",
        "uptime",
        "hostname",
        "uname",
        "date",
        "pwd",
        "df",
        "free"}
    if low.strip() in _BARE_UNIX:
        return _mk("SHELL_EXEC", {"cmd": raw.strip()}, 0.92, matched_by="shell.safeish_builtin",
                   entities={"cmd": raw.strip()})

    # Disk usage (bare, no path)
    if low.strip() in ("disk usage", "disk space", "storage space"):
        return _mk("SHELL_EXEC", {"cmd": "df -h"}, 0.95, matched_by="shell.disk_usage",
                   entities={"cmd": "df -h"})

    # mkdir X (bare)
    m = re.match(r"^mkdir\s+(.+)$", raw, re.I)
    if m:
        folder_name = m.group(1).strip()
        # os already imported at module level
        full_path = os.path.expanduser(
            f"~/{folder_name}") if not folder_name.startswith(
            ("/", "~")) else os.path.expanduser(folder_name)
        return _mk("CREATE_FOLDER", {"name": full_path}, 0.95, matched_by="fs.create_folder",
                   entities={"name": full_path})

    # note: X (colon format)
    m = re.match(r"^note:\s*(.+)$", raw, re.I)
    if m:
        return _mk("WRITE_NOTE", {"text": m.group(
            1).strip()}, 0.95, matched_by="notes.write")

    # Set a timer (bare, no duration) → prompt for duration
    if re.search(r"\bset\s+(?:a\s+)?timer\b",
                 low) and not re.search(r"\d", raw):
        return _mk("SET_TIMER", {"duration": None}, 0.7,
                   matched_by="timer.set_duration_loose")

    # Analyze X.csv / X.pdf (bare, without "summarize")
    m = re.match(r"^(?:analyze|analyse)\s+(.+\.csv)\s*$", raw, re.I)
    if m:
        # os already imported at module level
        return _mk("ANALYZE_CSV", {"path": os.path.abspath(os.path.expanduser(m.group(1).strip()))},
                   0.95, matched_by="analyze.csv")

    m = re.match(r"^(?:analyze|analyse)\s+(.+\.pdf)\s*$", raw, re.I)
    if m:
        # os already imported at module level
        return _mk("ANALYZE_PDF", {"path": os.path.abspath(os.path.expanduser(m.group(1).strip())),
                                   "instruction": raw},
                   0.95, matched_by="analyze.pdf")

    # Generate project with description
    if re.search(
            r"\bgenerate\s+(?:a\s+)?(?:new\s+)?(?:python\s+)?project\b", low):
        return _mk("GENERATE_PROJECT", {"description": raw, "use_gguf_only": True, "forbid_ollama": True},
                   0.95, matched_by="dev.generate_project")

    # Hardware: broader triggers
    if re.search(
            r"\b(?:hardware|gpu|cpu|ram|vram)\s+(?:info|specs?|status|check|details?)\b", low):
        return _mk("HARDWARE_PROFILE", {}, 0.90, matched_by="hardware.profile",
                   need_grounding=True, task_family="grounded_audit")

    if re.search(r"\boptimize\s+(?:my\s+)?hardware\b",
                 low) or re.search(r"\b(?:profile|scan)\s+hardware\b", low):
        return _mk("HARDWARE_PROFILE", {}, 0.90, matched_by="hardware.optimize",
                   need_grounding=True, task_family="grounded_audit")

    # Weather: umbrella / rain queries
    if re.search(r"\b(?:umbrella|rain(?:ing)?|snow(?:ing)?|storm)\b", low):
        location_match = re.search(
            r'\b(?:in|at|for)\b\s+([\w\s\-]+?)(?:\s*[,?!.]|\s+and\s+|\s+(?:provide|tell|show|give|also|then|next|tomorrow|today|forecast)|$)',
            raw,
            re.I)
        location = location_match.group(1).strip().rstrip("?.!, ") if location_match else None
        return _mk("GET_WEATHER", {"location": location, "_raw_user_text": raw}, 0.90, matched_by="info.weather",
                   entities={"location": location} if location else None)

    # "what is the time" / "what's the time" (expanded TIME patterns)
    if re.search(r"\bwhat\s+is\s+the\s+time\b",
                 low) or re.search(r"\bwhat's\s+the\s+time\b", low):
        return _mk("TIME", {}, 1.0, matched_by="system.time")
    # --- WRITE_NOTE with colon ---
    if re.match(r"^write note:", low):
        return _mk("WRITE_NOTE", {"text": re.sub(
            r"^write note:\s*", "", raw, flags=re.I).strip()}, 0.97, matched_by="notes.write_colon")
    # --- SCREENSHOT: final fallback catch ---
    if re.search(
            r"\b(take|capture)\s+(a\s+)?(screenshot|screen\s*shot|screen\s*capture|screen)\b", raw, re.I):
        region = "area" if re.search(
            r"\b(area|region|selection|part)\b", raw, re.I) else "full"
        return _mk("SCREENSHOT", {"region": region}, 0.98,
                   matched_by="io.screenshot", entities={"region": region})

    # Bare "screenshot" without "take a"
    if low.strip() == "screenshot":
        return _mk("SCREENSHOT", {}, 0.95, matched_by="io.screenshot_bare")

    # "write a report/guide/essay/document about X"
    _doc_m = re.match(
        r"^(?:write|create|generate|draft|produce)\s+(?:a\s+|an\s+)?"
        r"(report|guide|tutorial|essay|article|blog\s*post|document|manual|handbook|specification|proposal|plan|summary|brief)\s+"
        r"(?:about|on|for|regarding)\s+(.+)$", raw, re.I
    )
    if _doc_m:
        doc_type = _doc_m.group(1).strip()
        topic = _doc_m.group(2).strip()
        return _mk("GENERATE_DOCUMENT", {"topic": topic, "doc_type": doc_type, "format": "md"},
                   0.95, matched_by="doc.generate_typed", entities={"type": doc_type, "topic": topic})

    # ------------------------------------------------------------
    # OCR — extract text from image file
    # ------------------------------------------------------------
    m = re.match(
        r"^(?:ocr|read\s+(?:text\s+(?:from|in|on)|image)|extract\s+text\s+(?:from|in))\s+(.+)$",
        raw, re.I)
    if m:
        path = m.group(1).strip()
        return _mk("OCR_IMAGE", {"path": os.path.abspath(os.path.expanduser(path))},
                   0.95, matched_by="ocr.extract", entities={"path": path})

    # AMBIENT_VISION — continuous "watch my screen" toggle (distinct from a
    # one-shot "what's on my screen"). Check OFF before ON.
    if re.search(r"\b(?:stop|quit|disable|turn\s+off|cease)\b.{0,30}\b(?:watch|watching|"
                 r"look(?:ing)?\s+at|ambient\s+vision|keep\s+an\s+eye)\b", raw, re.I) or \
       re.search(r"\b(?:turn\s+off|disable)\s+ambient\s+vision\b", raw, re.I) or \
       re.search(r"\bstop\s+watching\b", raw, re.I):
        return _mk("AMBIENT_VISION", {"enabled": False, "text": raw}, 0.95,
                   matched_by="vision.ambient_off")
    if re.search(r"\b(?:watch|keep\s+watching|keep\s+an\s+eye\s+on|monitor)\s+(?:my|the)\s+screen\b",
                 raw, re.I) or \
       re.search(r"\b(?:enable|turn\s+on|start|activate)\s+ambient\s+vision\b", raw, re.I) or \
       re.search(r"\b(?:keep\s+)?(?:watching|looking\s+at)\s+what\s+i(?:'m|\s+am)\s+doing\b", raw, re.I):
        return _mk("AMBIENT_VISION", {"enabled": True, "text": raw}, 0.95,
                   matched_by="vision.ambient_on")

    # SCREEN_READ_ANALYZE — screenshot then vision (VL model) + OCR
    if re.search(
            r"\b(?:read|analyse?|analyze|describe|interpret|look\s+at|what(?:'s|\s+is)\s+on)\s+"
            r"(?:the|my)\s+(?:screen|display|monitor|desktop)\b", raw, re.I):
        return _mk("SCREEN_READ_ANALYZE", {}, 0.95, matched_by="screen.read_analyze")

    if re.search(r"\bscreen\s*(?:read|analyse?|analyze|ocr)\b", raw, re.I):
        return _mk("SCREEN_READ_ANALYZE", {}, 0.93, matched_by="screen.read_ocr")

    # Conversational vision: "what do you see", "can you see this/my screen",
    # "look at my screen", "what am I looking at", "see what I see".
    if re.search(
            r"\b(?:what\s+do\s+you\s+see|what\s+can\s+you\s+see|can\s+you\s+see\s+"
            r"(?:this|that|my\s+screen|what|the\s+screen)|see\s+what\s+i(?:'m|\s+am)?\s*"
            r"(?:see|seeing|looking\s+at)|what\s+am\s+i\s+looking\s+at|look\s+at\s+"
            r"(?:this|what\s+i'?m\s+doing)|see\s+my\s+screen)\b", raw, re.I):
        return _mk("SCREEN_READ_ANALYZE", {}, 0.9, matched_by="screen.vision_conversational")

    # ------------------------------------------------------------
    # CONVERT_DOCUMENT — convert between document formats
    # ------------------------------------------------------------
    m = re.search(
        r"convert\s+(.+?)\s+to\s+(pdf|docx?|html?|markdown|md|txt|tex|latex|lualatex|odt|rtf|epub)",
        raw, re.I)
    if m:
        src = m.group(1).strip()
        fmt = m.group(2).strip().lower()
        src_path = os.path.abspath(os.path.expanduser(src)) if _is_likely_path(src) or "." in src else src
        return _mk("CONVERT_DOCUMENT", {"source": src_path, "format": fmt},
                   0.95, matched_by="doc.convert", entities={"source": src_path, "format": fmt})

    m = re.search(
        r"export\s+(?:as|to)\s+(pdf|docx?|html?|markdown|md|txt|tex|latex|lualatex|odt|rtf|epub)",
        raw, re.I)
    if m:
        fmt = m.group(1).strip().lower()
        path_m = re.search(r'(?:from|file|document)\s+([\w./~\- ]+\.\w+)', raw, re.I)
        src_path = os.path.abspath(os.path.expanduser(path_m.group(1).strip())) if path_m else ""
        return _mk("CONVERT_DOCUMENT", {"source": src_path, "format": fmt},
                   0.90, matched_by="doc.export", entities={"source": src_path, "format": fmt})

    if re.search(r'\blualatex\b', raw, re.I):
        src_path = _extract_path_from_text(raw) or ""
        return _mk("CONVERT_DOCUMENT", {"source": src_path, "format": "lualatex"},
                   0.90, matched_by="doc.lualatex")

    # ------------------------------------------------------------
    # DICTATE / TRANSCRIBE — voice dictation and audio transcription
    # ------------------------------------------------------------
    if re.search(r"\b(?:start|begin|enable)\s+dictati(?:on|ng)\b", raw, re.I):
        return _mk("DICTATE", {"action": "start"}, 0.97, matched_by="voice.dictate_start")

    if re.search(r"\b(?:stop|end|disable)\s+dictati(?:on|ng)\b", raw, re.I):
        return _mk("DICTATE", {"action": "stop"}, 0.97, matched_by="voice.dictate_stop")

    if re.match(r"^dictate\b", raw, re.I):
        return _mk("DICTATE", {"action": "start"}, 0.95, matched_by="voice.dictate_bare")

    m = re.search(
        r"\btranscri(?:be|pt)\s+(.+)$", raw, re.I)
    if m:
        src = m.group(1).strip()
        src_path = os.path.abspath(os.path.expanduser(src)) if _is_likely_path(src) or "." in src else src
        return _mk("TRANSCRIBE", {"source": src_path},
                   0.95, matched_by="voice.transcribe", entities={"source": src_path})

    if re.search(r"\btranscri(?:be|pt)\b", raw, re.I):
        return _mk("TRANSCRIBE", {}, 0.90, matched_by="voice.transcribe_bare")

    # ------------------------------------------------------------
    # MOUSE_CONTROL — move, click, scroll
    # ------------------------------------------------------------
    m = re.search(
        r"\b(?:mouse\s+)?(?:click|left.click|right.click|double.click)\s+"
        r"(?:at\s+|on\s+)?(?:(\d+)\s*[,x]\s*(\d+))?", raw, re.I)
    if m and m.group(1):
        x, y = int(m.group(1)), int(m.group(2))
        btn = "right" if "right" in raw.lower() else "left"
        dbl = "double" in raw.lower()
        return _mk("MOUSE_CONTROL", {"action": "click", "x": x, "y": y, "button": btn, "double": dbl},
                   0.95, matched_by="ui.mouse_click", entities={"x": x, "y": y})

    if re.search(r"\bmove\s+(?:the\s+)?(?:mouse|cursor)\s+to\s+(\d+)\s*[,x]\s*(\d+)", raw, re.I):
        mm = re.search(r"(\d+)\s*[,x]\s*(\d+)", raw)
        x, y = int(mm.group(1)), int(mm.group(2))
        return _mk("MOUSE_CONTROL", {"action": "move", "x": x, "y": y},
                   0.95, matched_by="ui.mouse_move", entities={"x": x, "y": y})

    if re.search(r"\bscroll\s+(up|down)(?:\s+(\d+))?\b", raw, re.I):
        sm = re.search(r"\bscroll\s+(up|down)(?:\s+(\d+))?\b", raw, re.I)
        direction = sm.group(1).lower()
        amount = int(sm.group(2) or 3)
        return _mk("MOUSE_CONTROL", {"action": "scroll", "direction": direction, "amount": amount},
                   0.93, matched_by="ui.mouse_scroll")

    _low_raw = str(raw or "").lower()
    if any(_p in _low_raw for _p in (
        "one answer", "short answer", "short answers", "terribly short",
        "lobotom", "continuity", "awareness", "reasoning mode",
        "constitutional", "chain of thought", "cot", "pipeline",
        "fallback", "runtime audit", "runtime diagnostic",
        "what is with", "what's with", "why are you"
    )):
        return _mk(
            "CHAT",
            {"message": raw},
            0.92,
            matched_by="chat.meta_continuity_diagnostic",
            meta_extra={
                "requires_plan": True,
                "requires_memory": True,
                "quick_direct_allowed": False,
                "response_contract": "nonquick_continuity_diagnostic",
            },
        )

    # ── Persona lock ──────────────────────────────────────────────────────────
    # STATUS must be checked first — "persona lock status" contains "persona lock"
    # which would be caught by the SET regex if ordered after it.
    if re.search(r"\bpersona\s+lock\s+status\b|\bcheck\s+persona\s+lock\b|\bis\s+persona\s+locked\b", low):
        return _mk("PERSONA_LOCK_STATUS", {}, 0.92, matched_by="persona.lock_status")

    if re.search(r"\bunlock\s+persona\b|\bclear\s+persona\s+lock\b|\bpersona\s+unlock\b|"
                 r"\bremove\s+persona\s+lock\b|\breset\s+persona\s+lock\b", low):
        return _mk("PERSONA_LOCK_CLEAR", {}, 0.92, matched_by="persona.lock_clear")

    if re.search(r"\bpersona\s+lock\b|\block\s+persona\b|\bset\s+persona\s+lock\b", low):
        _model_arg = {}
        _m_model = re.search(r"\bto\s+([a-zA-Z0-9_:/-]+\.(?:gguf|bin|ggml))\b", low)
        if _m_model:
            _model_arg["model"] = _m_model.group(1)
        return _mk("PERSONA_LOCK_SET", _model_arg, 0.92, matched_by="persona.lock_set")

    # ── Skip YouTube ad ───────────────────────────────────────────────────────
    if re.search(r"\bskip\s+(?:the\s+)?(?:youtube\s+)?ad\b|\bskip\s+this\s+ad\b|"
                 r"\bbypass\s+(?:the\s+)?ad\b|\bskip\s+advertisement\b", low):
        return _mk("SKIP_YOUTUBE_AD", {}, 0.95, matched_by="media.skip_ad")

    # ── Clear chat history ───────────────────────────────────────────────────
    if re.search(r"\bclear\s+(?:chat|conversation|history|our\s+conversation)\b|"
                 r"\breset\s+(?:chat|conversation|history)\b|\berase\s+(?:chat|history)\b|"
                 r"\bwipe\s+(?:chat|conversation|history)\b", low):
        return _mk("CLEAR_CHAT_HISTORY", {}, 0.93, matched_by="system.clear_chat")

    # ── Listen for command ───────────────────────────────────────────────────
    if re.search(r"\b(listen\s+for\s+(?:a\s+)?command|start\s+listening|listen\s+for\s+speech|"
                 r"activate\s+(?:voice|speech)\s+input|begin\s+listening)\b", low):
        _timeout = 5.0
        _m_to = re.search(r"(\d+)\s*(?:second|sec|s)\b", low)
        if _m_to:
            _timeout = float(_m_to.group(1))
        return _mk("LISTEN_FOR_COMMAND", {"timeout": _timeout}, 0.90, matched_by="voice.listen_for_command")

    # ── Help ─────────────────────────────────────────────────────────────────
    if re.search(r"^\s*(?:help|commands?|what\s+(?:can\s+i|commands?|actions?)|"
                 r"what\s+(?:do\s+you|are\s+your)\s+(?:command|capability|action)|"
                 r"show\s+(?:me\s+)?(?:help|commands?|capabilities?)|list\s+command)\b", low):
        return _mk("HELP", {}, 0.90, matched_by="system.help")

    _eli_pipeline_trace("router.fallback_chat_selected", text=str(raw)[:160])
    return _mk("CHAT", {"message": raw}, 0.6, matched_by="fallback.chat")


# Backward-compatible route alias
_ROUTE_CORE = route


# Open-typo guard: catch common STT typos for OPEN_APP routing
# Handles common STT/typing variants before fallback chat.
import re as _eli_open_typo_re

def _eli_open_typo_norm(v):
    t = _eli_open_typo_re.sub(r"\s+", " ", str(v or "").lower()).strip(" .,!?:;")
    t = _eli_open_typo_re.sub(r"^opens\s+", "open ", t)
    t = _eli_open_typo_re.sub(r"\bspot\s*ify\b|\bspot\s+if\s+i\b|\bspotifyify\b|\bpotify\b", "spotify", t)
    return t



# Media query cleaner: normalize search query before media routing
# Clean residual open/play media query mistakes after routing.
import re as _eli_mqc_re

def _eli_mqc_clean_query(q: str) -> str:
    """
    Normalize whitespace and strip leading verb tokens, but preserve the
    original casing of title/artist names. Apply known STT alias fixes
    case-insensitively without lowercasing the rest of the query.
    """
    q = _eli_mqc_re.sub(r"\s+", " ", str(q or "")).strip(" .,!?:;")
    q = _eli_mqc_re.sub(r"^(open|play|search|find)\s+", "", q, flags=_eli_mqc_re.I).strip()
    # Strip trailing service qualifiers — the router already extracted `target`.
    # Without this, "logic by diabolic on spotify" → query="logic by diabolic on spotify"
    # instead of the expected "logic by diabolic".
    q = _eli_mqc_re.sub(
        r"\s+on\s+(spotify|youtube|yt|mpv|soundcloud|apple\s+music|tidal|deezer)\s*$",
        "",
        q,
        flags=_eli_mqc_re.I,
    ).strip()
    q = _eli_mqc_re.sub(
        r"\b(?:alt\s*[- ]?\s*0|hours\s+of\s+zero|i'll\s+just\s+air|"
        r"and\s+i'll\s+just\s+air|algezera|algezira|algazear|algazare|"
        r"algiers\s+era)\b",
        "al jazeera",
        q,
        flags=_eli_mqc_re.I,
    )
    return _eli_mqc_re.sub(r"\s+", " ", q).strip()



# Identity route wrapper, tiny-chat guard, follow-up pass-through,
# and persona-route override all use the top-level re import.



# voice_runtime_contract_guard
# Deterministic voice-command grammar for common local-control requests.
# This layer fixes ASR wording variants before the broad tiny-fragment/fallback
# chat guards see them. It contains no user-machine absolute paths.

def _eli_voice_contract_text_from_call(args, kwargs):
    for item in args:
        if isinstance(item, str) and item.strip():
            return item
    for key in ("text", "message", "command", "prompt", "query", "utterance"):
        item = kwargs.get(key)
        if isinstance(item, str) and item.strip():
            return item
    return ""

def _eli_voice_contract_norm(text):
    import re
    text = str(text or "").lower()
    text = text.replace("’", "'").replace("“", '"').replace("”", '"')
    text = text.replace(" per cent", "%").replace(" percent", "%")
    text = re.sub(r"[^a-z0-9%'\s]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def _eli_voice_contract_response(message, matched_by):
    return {
        "action": "NOOP",
        "args": {
            "message": message,
            "response": message,
            "content": message,
        },
        "confidence": 0.999,
        "meta": {"matched_by": matched_by},
    }

def _eli_voice_contract_route(text):
    import re

    raw = str(text or "").strip()
    norm = _eli_voice_contract_norm(raw)
    if not norm:
        return None

    # Absolute volume: "volume 80", "volume 80%", "set volume to 80".
    m = re.fullmatch(r"(?:set\s+)?volume\s+(?:to\s+)?(\d{1,3})\s*%?", norm)
    if m:
        level = max(0, min(100, int(m.group(1))))
        return {
            "action": "VOLUME",
            "args": {"level": level, "percent": level, "mode": "absolute"},
            "confidence": 0.999,
            "meta": {
                "matched_by": "voice_runtime_contract.volume_absolute",
                "normalized": f"volume {level}%",
            },
        }

    if re.fullmatch(r"volume\s+(?:max|maximum|full)", norm):
        return {
            "action": "VOLUME",
            "args": {"level": 100, "percent": 100, "mode": "absolute"},
            "confidence": 0.999,
            "meta": {"matched_by": "voice_runtime_contract.volume_maximum"},
        }

    if re.fullmatch(r"volume\s+(?:off|zero|mute)", norm):
        return {
            "action": "VOLUME",
            "args": {"level": 0, "percent": 0, "mode": "absolute"},
            "confidence": 0.999,
            "meta": {"matched_by": "voice_runtime_contract.volume_zero"},
        }

    # Keep "open settings" on the direct-execution path. Do not send this to
    # cognition/broker after the OS action has already succeeded.
    if re.fullmatch(r"(?:open|launch|show)\s+(?:system\s+)?settings", norm):
        return {
            "action": "OPEN_APP",
            "args": {"name": "settings", "app": "settings"},
            "confidence": 0.999,
            "meta": {
                "matched_by": "voice_runtime_contract.open_settings_direct",
                "normalized": "open settings",
            },
        }

    # ASR variants for "May the Fourth" / "May the Force".
    may_fourth = (
        re.search(r"\bmay\s+(?:the\s+)?(?:4th|fourth|forth|fort|force|default)\b", norm)
        or re.search(r"\b(?:4th|fourth|forth|fort)\s+of\s+may\b", norm)
        or "fort of may" in norm
        or "fort fou or th" in norm
        or "made of fort" in norm
        or "fort be with you" in norm
        or "force be with you" in norm
    )
    if may_fourth:
        msg = (
            "You mean May the Fourth. Its significance is Star Wars Day: "
            "a pun on “May the Force be with you.”"
        )
        return _eli_voice_contract_response(msg, "voice_runtime_contract.may_fourth_asr_normalised")

    return None

def _eli_voice_contract_wrap_callable(fn):
    if not callable(fn) or getattr(fn, "_eli_voice_contract_wrapped", False):
        return fn

    def _wrapped(*args, **kwargs):
        shortcut = _eli_voice_contract_route(_eli_voice_contract_text_from_call(args, kwargs))
        if shortcut is not None:
            return shortcut
        return fn(*args, **kwargs)

    try:
        _wrapped.__name__ = getattr(fn, "__name__", "_wrapped")
        _wrapped.__doc__ = getattr(fn, "__doc__", None)
        _wrapped._eli_voice_contract_wrapped = True
    except Exception:
        pass
    return _wrapped

_eli_voice_contract_route_names = (
    "route",
    "route_text",
    "route_command",
    "route_intent",
    "parse",
    "parse_intent",
    "parse_command",
    "classify",
    "classify_intent",
)

for _name in _eli_voice_contract_route_names:
    _fn = globals().get(_name)
    if callable(_fn) and _fn is not _eli_voice_contract_route:
        globals()[_name] = _eli_voice_contract_wrap_callable(_fn)

for _obj in list(globals().values()):
    if isinstance(_obj, type):
        for _name in _eli_voice_contract_route_names:
            try:
                _method = getattr(_obj, _name, None)
                if callable(_method):
                    setattr(_obj, _name, _eli_voice_contract_wrap_callable(_method))
            except Exception:
                pass

# portable_runtime_contract_v3_router_hook


# ELI_LIVE_ROUTE_SECOND_FIX_20260505
# High-priority route wrapper for cases the base router currently lets fall into CHAT/search.
import re as _eli_lrf_re


def _eli_lrf_mk(action, args=None, confidence=0.99, matched_by="eli.live_route_second_fix"):
    mk = globals().get("_mk")
    if callable(mk):
        try:
            return mk(action, args or {}, confidence, matched_by=matched_by, allow_chat_without_evidence=False)
        except TypeError:
            try:
                return mk(action, args or {}, confidence, matched_by=matched_by)
            except TypeError:
                pass
    return {
        "action": action,
        "args": args or {},
        "confidence": confidence,
        "meta": {"matched_by": matched_by, "allow_chat_without_evidence": False},
    }

def _eli_lrf_word_to_int(s):
    s = str(s or "").strip().lower()
    table = {
        "one": 1, "two": 2, "to": 2, "too": 2,
        "three": 3, "tree": 3, "free": 3,
        "four": 4, "for": 4, "fore": 4,
        "five": 5, "six": 6, "seven": 7, "eight": 8,
    }
    if s.isdigit():
        return int(s)
    return table.get(s)

def _eli_lrf_pre_route(text):
    raw = str(text or "").strip()
    low = raw.lower().strip()
    low = low.replace("×", "x")

    # Exact/near-exact mode query: status action only, not full RUNTIME_STATUS.

    if _eli_phase10_is_codebase_audit_request(raw):
        return _mk(
            "RUNTIME_AUDIT",
            {"query": raw, "audit_depth": "codebase"},
            0.99,
            matched_by="phase10.codebase_audit_guard",
            allow_chat_without_evidence=False,
            need_grounding=True,
            task_family="grounded_audit",
        )

    # Only report current mode status if the query is specifically about the active/current mode.
    # Queries asking about ALL modes, explaining modes, differences, etc. must reach CHAT/synthesis.
    _lrf_asking_all_modes = _eli_lrf_re.search(
        r"\b(all|every|each|how many|list|explain|full|describe|detail|difference|differ|compare|what are|tell me about|tell me all|tell me everything|what do|how do|modes?\s+you\s+have|modes?\s+does)\b",
        low,
    )
    if _lrf_asking_all_modes and _eli_lrf_re.search(r"\b(reasoning mode|modes?)\b", low):
        return _eli_lrf_mk(
            "EXPLAIN_ALL_REASONING_MODES", {},
            0.99,
            "reasoning.all_modes_grounded.second_fix",
        )
    if "reasoning mode" in low and not _lrf_asking_all_modes and not _eli_lrf_re.search(
        r"\b(cognition pipeline|input to output|every step|memory system|db tables|functions|files|runtime audit|diagnostic|diagnostics|full audit)\b",
        low,
    ):
        return _eli_lrf_mk("REASONING_MODE_STATUS", {}, 0.995, "reasoning.mode_status.second_fix")

    # Internal memory architecture question must not become document/search plugin output.
    if _eli_lrf_re.search(r"\b(memory system|memory internally|memory.*db tables|db tables|which files|which functions)\b", low) and _eli_lrf_re.search(r"\b(memory|db|sqlite|faiss|functions?|files?|internally|runtime)\b", low):
        return _eli_lrf_mk(
            "EXPLAIN_MEMORY_RUNTIME",
            {"question": raw, "detail": "full"},
            0.985,
            "memory.runtime_architecture.second_fix",
        )

    # Bare grid follow-up, including STT's "tree" for "three" and optional trailing "grid/layout/windows".
    m = _eli_lrf_re.fullmatch(
        r"\s*(\d{1,2}|one|two|three|tree|four|five|six|seven|eight)\s*(?:x|by)\s*(\d{1,2}|one|two|three|tree|four|five|six|seven|eight)\s*(?:grid|layout|windows?)?\s*",
        low,
    )
    if m:
        cols = _eli_lrf_word_to_int(m.group(1))
        rows = _eli_lrf_word_to_int(m.group(2))
        if cols and rows and 1 <= cols <= 8 and 1 <= rows <= 8:
            return _eli_lrf_mk(
                "TILE_WINDOWS",
                {"cols": cols, "rows": rows, "grid": [cols, rows]},
                0.995,
                "window.grid_followup.second_fix",
            )

    return None





# ELI_PERSONAL_MEMORY_MODE_AWARE_ROUTER_FIX_20260505
# High-priority route wrapper: personal memory questions need synthesis, not raw truth reports/search.
import re as _eli_pm_re


def _eli_pm_mk(action, args=None, confidence=0.99, matched_by="eli.personal_memory_mode_aware"):
    mk = globals().get("_mk")
    if callable(mk):
        try:
            return mk(action, args or {}, confidence, matched_by=matched_by, allow_chat_without_evidence=False)
        except TypeError:
            try:
                return mk(action, args or {}, confidence, matched_by=matched_by)
            except TypeError:
                pass
    return {
        "action": action,
        "args": args or {},
        "confidence": confidence,
        "meta": {"matched_by": matched_by, "allow_chat_without_evidence": False},
    }

def _eli_pm_wants_raw_memory_truth(low):
    return bool(_eli_pm_re.search(
        r"\b(memory truth report|memory count|how many memories|memory status|memory runtime status|raw counts?|db counts?|diagnostic counts?)\b",
        low,
    ))

def _eli_pm_wants_personal_memory(low):
    if _eli_pm_wants_raw_memory_truth(low):
        return False

    has_memory = bool(_eli_pm_re.search(r"\b(memory|remember|stored memories|what do you know about me|what you know about me|actual(?:ly)? remember)\b", low))
    has_depth = bool(_eli_pm_re.search(
        r"\b(full|in[- ]?depth|personalised|personalized|properly|not quick|not in quick mode|"
        r"stop giving me data dumps|data dumps|what you actually remember|about me|which files|db tables|functions|internally|cognition pipeline)\b",
        low,
    ))
    return has_memory and has_depth

def _eli_pm_pre_route(text):
    raw = str(text or "").strip()
    low = raw.lower()

    if _eli_pm_re.search(r"\bwhy\b.*\b(browser|web|online|search)\b", low) or _eli_pm_re.search(r"\bwhy.*go.*browser\b", low):
        return _eli_pm_mk(
            "ROUTING_FAULT_EXPLAIN",
            {"question": raw},
            0.995,
            "routing_fault.browser_complaint",
        )

    if _eli_pm_re.search(r"\bstop giving me data dumps\b|\bwe are not in quick mode\b|\bfull and personalised response\b|\bfull and personalized response\b", low):
        return _eli_pm_mk(
            "PERSONAL_MEMORY_DEEP_EXPLAIN",
            {"question": raw, "reason": "user_rejected_data_dump"},
            0.995,
            "memory.personalized_no_data_dump",
        )

    if _eli_pm_wants_personal_memory(low):
        return _eli_pm_mk(
            "PERSONAL_MEMORY_DEEP_EXPLAIN",
            {"question": raw},
            0.99,
            "memory.personalized_deep_explain",
        )

    return None





# --- ELI high-priority self-improvement route guard ---
def _eli_self_improvement_phrase_guard(text):
    raw = str(text or "")
    low = raw.lower().strip()

    if re.search(r"\b(self[- ]?improvement|improvement)\s+log\b", low) or (
        re.search(r"\bexact\s+error\s+message\b", low)
        and re.search(r"\blast\s+failure\b", low)
    ):
        return {
            "action": "SELF_IMPROVEMENT_LOG",
            "args": {"question": raw, "limit": 5},
            "confidence": 0.99,
            "meta": {
                "matched_by": "eli.self_improvement_log_guard",
                "need_grounding": True,
                "allow_chat_without_evidence": False,
                "task_family": "self_improvement",
            },
        }

    if re.search(
        r"\b(run|start|perform|execute)\s+(?:an?\s+)?(?:self[- ]?)?improvement(?:\s+cycle)?\b"
        r"|\bimprove\s+yourself\b"
        r"|\bself[- ]?improve\b",
        low,
    ):
        return {
            "action": "SELF_IMPROVE",
            "args": {},
            "confidence": 0.99,
            "meta": {
                "matched_by": "eli.self_improvement_cycle_guard",
                "need_grounding": True,
                "allow_chat_without_evidence": False,
                "task_family": "self_improvement",
            },
        }

    if re.search(r"\bwhat\s+have\s+you\s+improved\b|\bself[- ]?improvement\s+status\b", low):
        return {
            "action": "SELF_ANALYZE",
            "args": {},
            "confidence": 0.98,
            "meta": {
                "matched_by": "eli.self_improvement_status_guard",
                "need_grounding": True,
                "allow_chat_without_evidence": False,
                "task_family": "self_improvement",
            },
        }

    return None

# --- end ELI high-priority self-improvement route guard ---


# --- ELI runtime/cognition/failure high-priority route guard ---
def _eli_runtime_cognition_failure_guard(text):
    raw = str(text or "")
    low = raw.lower().strip()

    if re.search(r"\bnvidia-smi\b", low) or (
        re.search(r"\b(gpu|vram|cuda|nvidia)\b", low)
        and re.search(r"\b(status|diagnostic|diagnostics|usage|memory|performance|running on|tell me what it means)\b", low)
    ):
        return {
            "action": "GPU_STATUS",
            "args": {"question": raw, "explain": True},
            "confidence": 0.995,
            "meta": {
                "matched_by": "eli.gpu_status_guard",
                "need_grounding": True,
                "allow_chat_without_evidence": False,
                "task_family": "grounded_diagnostic",
            },
        }

    if re.search(r"\b(full\s+)?runtime\s+audit\b", low) or re.search(r"\bwhat'?s?\s+actually\s+(broken|missing)\b", low):
        return {
            "action": "RUNTIME_AUDIT",
            "args": {},
            "confidence": 0.99,
            "meta": {
                "matched_by": "eli.runtime_audit_guard",
                "need_grounding": True,
                "allow_chat_without_evidence": False,
                "task_family": "grounded_audit",
            },
        }

    if re.search(r"\bcognition\s+pipeline\b", low) or re.search(r"\binput\s+to\s+output\b", low):
        return {
            "action": "EXPLAIN_COGNITION_RUNTIME",
            "args": {},
            "confidence": 0.99,
            "meta": {
                "matched_by": "eli.cognition_pipeline_guard",
                "need_grounding": True,
                "allow_chat_without_evidence": False,
                "task_family": "grounded_audit",
            },
        }

    if re.search(r"\brecent\s+failures?\b", low) or re.search(r"\bactual\s+root\s+cause\b", low):
        return {
            "action": "SELF_ANALYZE",
            "args": {},
            "confidence": 0.98,
            "meta": {
                "matched_by": "eli.failure_analysis_guard",
                "need_grounding": True,
                "allow_chat_without_evidence": False,
                "task_family": "self_improvement",
            },
        }

    return None

# --- end ELI runtime/cognition/failure high-priority route guard ---




# =============================================================================

# =============================================================================
# ELI IDENTITY / NAME-SOURCE ROUTE FIX - SINGLE CLOSURE-SAFE INSTALL
# =============================================================================
# =============================================================================

# =============================================================================
# ELI FINAL RUNTIME STATUS ROUTE CONTRACT
# Runtime identity/status questions must route to grounded runtime evidence.
# Quick mode may display compact output downstream; non-quick modes must synthesize.
# =============================================================================
# =============================================================================

# =============================================================================
# ELI FINAL MEMORY QUESTION ROUTE CONTRACT
# Separates "what do you know about me" from "explain memory internals".
# =============================================================================
# =============================================================================

# =============================================================================
# ELI PERSONAL_MEMORY_SUMMARY COMPATIBILITY
# PERSONAL_MEMORY_SUMMARY is now a first-class evidence action. Keep this
# wrapper only to preserve the final route binding and metadata hygiene; do
# not collapse summary requests back into the old deep-response override.
# =============================================================================
# =============================================================================

# =============================================================================
# ELI IDENTITY SCOPE CONTRACT
# USER_IDENTITY_SUMMARY must carry the original question and must not be treated
# as a generic "what do you know about me" memory/profile dump.
# =============================================================================
# ELI_PHASE51_IDENTITY_SCOPE_HELPER_SHELL_PRUNE_V1
# Standalone helper retained from the obsolete identity-scope Try shell.
def _eli_identity_scope_for_text(text):
    import re as _re
    low = _re.sub(r"\s+", " ", str(text or "").lower()).strip(" .,!?:;")

    if _re.search(r"\b(what is my name|what's my name|do you know my name)\b", low):
        return "name_only"

    if _re.search(r"\b(who am i|who i am)\b", low):
        return "identity_only"

    if _re.search(r"\b(do you remember me|do you know me)\b", low):
        return "memory_presence_only"

    return "identity_only"
# =============================================================================

# =============================================================================
# ELI PROFILE MEMORY SCOPE CONTRACT
# Separates:
#   - identity-only questions
#   - memory-presence questions
#   - generic profile inventory
#   - explicit preference detail requests
#   - full profile dump requests
# No user names are hardcoded here.
# =============================================================================
# ELI_PHASE53_HELPER_TRYBLOCK_HOIST_DIAGNOSTIC_SHELL_RETIREMENT_V1: profile_scope_helpers
# Phase53: helper/import-only Try shell hoisted to module scope.
# The former except branch only printed a diagnostic and swallowed import-time
# helper-definition failure; that stale diagnostic shell is intentionally retired.

def _eli_profile_scope_low(text):
    import re as _re
    return _re.sub(r"\s+", " ", str(text or "").strip().lower())

def _eli_profile_scope_result(action, question, scope, confidence=0.995, matched_by="profile.scope_contract"):
    return {
        "action": action,
        "args": {
            "question": str(question or ""),
            "profile_scope": scope,
        },
        "confidence": confidence,
        "meta": {
            "matched_by": matched_by,
            "profile_scope_contract": scope,
            "active_user_scoped": True,
            "forbid_schema_dump": True,
            "forbid_reflection_spam": True,
            "forbid_news_rows": True,
        },
    }

def _eli_is_explicit_preference_request(low):
    import re as _re
    if _re.search(r"\b(show|list|summari[sz]e|tell me|what are|display|read)\b.{0,80}\b(my|stored|profile)?\s*preferences\b", low):
        return True
    if _re.search(r"\bmy stored preferences\b", low):
        return True
    if low in {"my preferences", "show preferences", "show my preferences"}:
        return True
    return False

def _eli_is_generic_profile_inventory(low):
    return low in {
        "what do you know about me",
        "what do you remember about me",
        "what do you remember of me",
        "do you know me",
    }

def _eli_is_full_profile_dump(low):
    import re as _re
    return bool(_re.search(r"\b(dump|show|print|read|display)\b.{0,80}\b(full|complete|entire|all)\b.{0,80}\b(profile|personal memory|memory profile)\b", low))
# =============================================================================

# =============================================================================
# ELI MEMORY COUNT GROUNDED SYNTHESIS CONTRACT
# Count questions are evidence-backed questions. Quick mode may direct-return.
# Non-quick modes must synthesize from compact evidence and validate the answer.
# =============================================================================
# ELI_PHASE53_HELPER_TRYBLOCK_HOIST_DIAGNOSTIC_SHELL_RETIREMENT_V1: memory_count_helper
# Phase53: helper/import-only Try shell hoisted to module scope.
# The former except branch only printed a diagnostic and swallowed import-time
# helper-definition failure; that stale diagnostic shell is intentionally retired.

def _eli_is_memory_count_question(text):
    import re
    low = str(text or "").strip().lower()
    return bool(
        re.search(r"\b(how many|number of|count)\b.{0,80}\b(memories|memory entries|stored memories|memory rows)\b", low)
        or re.fullmatch(r"(memory count|count memories|count memory|memories count|memory rows)", low)
    )

# =============================================================================
# ELI RECENT MEMORY PROCESSING ROUTE
# Questions like "what memories have you been processing lately?" are not CHAT.
# They require grounded memory/runtime evidence, otherwise the model invents
# plausible-sounding fake memory activity.
# =============================================================================
# ELI_PHASE53_HELPER_TRYBLOCK_HOIST_DIAGNOSTIC_SHELL_RETIREMENT_V1: recent_memory_processing_helper
# Phase53: helper/import-only Try shell hoisted to module scope.
# The former except branch only printed a diagnostic and swallowed import-time
# helper-definition failure; that stale diagnostic shell is intentionally retired.
import re as _eli_recent_mem_re



from eli.utils.log import get_logger
log = get_logger(__name__)

def _eli_recent_memory_processing_question(text: object) -> bool:
    low = str(text or "").strip().lower()
    if not low:
        return False

    # Preserve existing count-only route.
    if _eli_recent_mem_re.search(r"\b(how many|count|number of)\b.{0,40}\b(memories|memory rows|memory entries)\b", low):
        return False

    memory_terms = _eli_recent_mem_re.search(
        r"\b(memories|memory|remembered|remembering|processed|processing|learning|stored|recalled|recall)\b",
        low,
    )
    recent_terms = _eli_recent_mem_re.search(
        r"\b(lately|recently|latest|last|currently|been|processing|working on|what .* processing)\b",
        low,
    )

    patterns = [
        r"\bwhat\s+memories\s+have\s+you\s+been\s+processing\b",
        r"\bwhat\s+memory\s+have\s+you\s+been\s+processing\b",
        r"\bwhat\s+have\s+you\s+been\s+remembering\b",
        r"\bwhat\s+have\s+you\s+remembered\s+(?:recently|lately)\b",
        r"\bwhat\s+have\s+you\s+been\s+learning\s+(?:recently|lately)\b",
        r"\bwhat\s+memories\s+(?:did|do)\s+you\s+(?:process|have)\s+(?:recently|lately)\b",
        r"\bwhat\s+recent\s+memories\b",
        r"\bshow\s+(?:me\s+)?recent\s+memories\b",
        r"\blatest\s+memory\s+(?:activity|processing|updates)\b",
        r"\brecent\s+memory\s+(?:activity|processing|updates)\b",
    ]
    if any(_eli_recent_mem_re.search(p, low) for p in patterns):
        return True

    return bool(memory_terms and recent_terms and "you" in low)

# =============================================================================
# ELI SELF-REPORT RECENT UPDATES ROUTE
# Self/status questions asking what updates/checks have happened must not fall
# into generic CHAT, because GGUF will invent plausible maintenance activity.
# =============================================================================
# ELI_PHASE53_HELPER_TRYBLOCK_HOIST_DIAGNOSTIC_SHELL_RETIREMENT_V1: self_report_recent_updates_helper
# Phase53: helper/import-only Try shell hoisted to module scope.
# The former except branch only printed a diagnostic and swallowed import-time
# helper-definition failure; that stale diagnostic shell is intentionally retired.


def _eli_self_report_recent_updates_question(text):
    low = str(text or "").strip().lower()
    if not low:
        return False

    self_ref = any(x in low for x in (
        "eli",
        "yourself",
        "about yourself",
        "your runtime",
        "your system",
    ))

    update_ref = any(x in low for x in (
        "what updates",
        "which updates",
        "updates and checks",
        "checks have been",
        "checks were",
        "performed as of late",
        # NOTE: bare "as of late" removed — it fires on casual idioms like
        # "are you saying i'm obsessive these days as of late".
        # "performed as of late" above is specific enough.
        "recent checks",
        "routine updates",
        "recent updates",
        "what have you been doing",
        "what have you been processing",
        "what have you been working on",
    ))

    return bool(update_ref and (self_ref or " you " in f" {low} " or " your " in f" {low} "))



# =============================================================================
# ELI GUI AUDIT ACTUAL-SCAN PROOF ROUTE V2
# Catches direct "did you actually scan/read file in full" probes.
# =============================================================================
# ELI_PHASE53_HELPER_TRYBLOCK_HOIST_DIAGNOSTIC_SHELL_RETIREMENT_V1: gui_actual_scan_helper
# Phase53: helper/import-only Try shell hoisted to module scope.
# The former except branch only printed a diagnostic and swallowed import-time
# helper-definition failure; that stale diagnostic shell is intentionally retired.

def _eli_gui_audit_actual_scan_v2(text):
    q = " ".join(str(text or "").lower().split())
    if not q:
        return False

    file_hit = any(x in q for x in (
        "eli/gui/eli_pro_audio_gui_mki.py",
        "eli_pro_audio_gui_mki.py",
        "gui file",
        "audio gui",
    ))

    scan_hit = any(x in q for x in (
        "actually scan",
        "actually scanned",
        "actually read",
        "did you scan",
        "did you read",
        "scan the file",
        "read the file",
        "in full",
        "full file",
        "whole file",
        "entire file",
    ))

    return bool(file_hit and scan_hit)



# =============================================================================
# ELI_MEMORY_RUNTIME_ROUTE_LOCK_V1
# Memory-runtime architecture/control questions are first-class grounded telemetry.
# They must not be stolen by generic CHAT, OPEN_APP, or personal-memory/profile
# routing. This does not answer the question; it only guarantees the correct
# evidence action.
# =============================================================================
# ELI_PHASE53_HELPER_TRYBLOCK_HOIST_DIAGNOSTIC_SHELL_RETIREMENT_V1: memory_runtime_lock_helpers
# Phase53: helper/import-only Try shell hoisted to module scope.
# The former except branch only printed a diagnostic and swallowed import-time
# helper-definition failure; that stale diagnostic shell is intentionally retired.

def _eli_memory_runtime_route_lock_should_trigger(text):
    import re as _re

    raw = str(text or "").strip()
    low = raw.lower()

    if not low:
        return False

    # Literal control/action invocation.
    if _re.search(r"\b(?:run|execute|call|invoke)?\s*`?explain_memory_runtime`?\b", low):
        return True

    # Direct architecture/internal-memory requests.
    if _re.search(
        r"\b("
        r"explain exactly how your memory system works internally|"
        r"memory system works internally|"
        r"how (?:does|do) your memory system work|"
        r"how does your memory work internally|"
        r"which files.*which db tables.*which functions|"
        r"memory runtime(?: surface)?|"
        r"memory architecture|"
        r"memory internals"
        r")\b",
        low,
    ):
        return True

    # Broader DB/schema/function phrasing.
    if _re.search(r"\bmemor(?:y|ies)\b", low) and _re.search(
        r"\b("
        r"database files?|db files?|databases?|sqlite|tables?|schema|"
        r"functions?|internally|architecture|runtime|"
        r"faiss|fts5|vectors?|vectoring|recall_log|conversation_turns|"
        r"user\.sqlite3|agent\.sqlite3|memory\.sqlite3"
        r")\b",
        low,
    ):
        # Personal profile questions should stay personal-memory unless the
        # user explicitly asks architecture/schema/files/functions.
        asks_profile = _re.search(
            r"\b(what do you know about me|what do you remember about me|"
            r"my preferences|my profile|who am i|what is my name)\b",
            low,
        )
        asks_arch = _re.search(
            r"\b(files?|db|database|sqlite|tables?|functions?|schema|"
            r"internally|runtime|architecture)\b",
            low,
        )
        if asks_profile and not asks_arch:
            return False
        return True

    return False


def _eli_memory_runtime_route_lock_result(raw):
    return {
        "action": "EXPLAIN_MEMORY_RUNTIME",
        "args": {"question": str(raw or ""), "detail": "full"},
        "confidence": 0.995,
        "meta": {
            "matched_by": "eli.memory_runtime_route_lock_v1",
            "need_grounding": True,
            "allow_chat_without_evidence": False,
            "task_family": "memory_runtime",
            "response_contract": "canonical_grounded_memory_runtime_no_raw_gguf",
        },
    }
# =============================================================================


# ELI_PATCH_FINAL_PERSONAL_MEMORY_ROUTE_PRECEDENCE_AFTER_ROUTE_LOCK_20260511
# Final route wrapper: installed after late memory-runtime route locks.
# The phrase logic now lives in eli.execution.route_contracts.
# This wrapper remains at EOF only to preserve precedence over legacy route wrappers.











# --- Phase 11: multi-PDF route contract wrapper -----------------------
# Purpose:
#   Existing route branches call _extract_pdf_path(raw), which returns only the
#   first PDF. Phase 10 added _extract_pdf_paths(raw). This wrapper preserves
#   existing route behaviour while enriching ANALYZE_PDF args with paths=[...].
# --- Phase 48: standalone Phase11 multi-PDF enrichment helper -----------
# Phase38 flattened dispatch uses this helper directly. The older Phase11
# route/route_intent capture shell has been removed as dead pre-marker debt.
def _eli_phase11_enrich_pdf_route(raw, result):
    try:
        if not isinstance(result, dict):
            return result

        action = str(result.get("action") or "").upper().strip()
        if action != "ANALYZE_PDF":
            return result

        args = result.setdefault("args", {})
        if not isinstance(args, dict):
            return result

        text = str(raw or "")
        if ".pdf" not in text.lower():
            return result

        paths = []
        try:
            paths = list(_extract_pdf_paths(text))
        except Exception:
            paths = []

        if not paths:
            return result

        args["path"] = str(args.get("path") or paths[0])
        args["paths"] = paths

        meta = result.setdefault("meta", {})
        if isinstance(meta, dict):
            entities = meta.setdefault("entities", {})
            if isinstance(entities, dict):
                entities["path"] = args["path"]
                entities["paths"] = paths
            meta["multipdf_count"] = len(paths)
            # ELI_PHASE33_MULTIPDF_IDEMPOTENT
            _phase11_matched_by = str(meta.get("matched_by") or "analyze.pdf")
            if "+phase11_multipdf" not in _phase11_matched_by:
                meta["matched_by"] = _phase11_matched_by + "+phase11_multipdf"
            else:
                meta["matched_by"] = _phase11_matched_by

        return result
    except Exception:
        return result



# =============================================================================
# ELI_PHASE33_CANONICAL_PUBLIC_ROUTER_SURFACE_EXPORT
#
# Phase 32 proved that the exported router surfaces had drifted:
#   - route / route_intent were on the latest final route chain
#   - route_command was partially stale
#   - parse_command / classify were more stale
#
# Do not let these historical aliases capture old intermediate route wrappers.
# Until router_enhanced.py is structurally flattened, all exported public routing
# surfaces must resolve to the single final route() authority below.
# =============================================================================
try:
    _ELI_PHASE33_FINAL_CANONICAL_ROUTE = route

    if callable(_ELI_PHASE33_FINAL_CANONICAL_ROUTE):

        print(
            flush=True,
        )
    else:
        log.debug(
            "[ROUTER] canonical public routing surface export skipped: final route is not callable",
        )

except Exception as _eli_phase33_router_surface_err:
    log.debug(
        f"[ROUTER] canonical public routing surface export failed: "
        f"{_eli_phase33_router_surface_err}",
    )
# =============================================================================


# =============================================================================
# ELI_PHASE38_FLATTENED_CANONICAL_DISPATCH_V1
# =============================================================================
#
# Purpose:
#   Replace the active nested wrapper-chain public router surface with one
#   explicit canonical dispatch pipeline, while preserving the semantics proven
#   by Phase 36 v2 and the live-stage order proven by Phase 37.
#
# Important:
#   This phase intentionally does NOT delete historical wrapper source blocks.
#   It shadows them as the final exported route surface. Once semantic parity is
#   proven, a dedicated pruning pass can safely remove obsolete rebinding debt.
# =============================================================================

try:
    from eli.execution.portable_intent_contract import try_route as _eli_phase38_portable_try_route
except Exception:
    _eli_phase38_portable_try_route = None


def _eli_phase38_enrich_pdf_if_needed(raw, result):
    enricher = globals().get("_eli_phase11_enrich_pdf_route")
    if callable(enricher):
        try:
            return enricher(raw, result)
        except Exception:
            return result
    return result


def _eli_phase38_route_precedence_contract(raw):
    try:
        from eli.execution.route_contracts import classify_precedence_route
        return classify_precedence_route(raw)
    except Exception:
        return None


def _eli_phase38_frontier_status_contract(raw):
    import re as _re

    low = _re.sub(r"\s+", " ", str(raw or "").lower()).strip()
    if not low:
        return None

    if _re.search(
        r"\b("
        r"frontier status"
        r"|full system (?:status|audit|wiring|matrix)"
        r"|cross[- ]system (?:status|audit|wiring|matrix)"
        r"|full (?:project|eli) (?:audit|wiring|matrix)"
        r"|memory.*self[- ]aware.*proactive.*image.*world.*labs"
        r"|chat flow.*memory.*self.*proactive.*image.*world.*labs"
        r")\b",
        low,
    ):
        return {
            "action": "FRONTIER_STATUS",
            "args": {"question": str(raw or "")},
            "confidence": 0.997,
            "meta": {
                "matched_by": "eli.frontier_status_route_contract",
                "need_grounding": True,
                "allow_chat_without_evidence": False,
                "task_family": "grounded_audit",
                "response_contract": "quick_direct_nonquick_persona_synthesis",
            },
        }
    return None


def _eli_phase39_identity_audit_contract(raw):
    import re as _re

    low = _re.sub(r"\s+", " ", str(raw or "").lower()).strip()
    if not low:
        return None

    if _re.search(
        r"\b("
        r"eli identity audit"
        r"|classif(?:y|ication) (?:eli|yourself|you)"
        r"|what (?:exactly )?is eli"
        r"|what should eli be classified as"
        r"|what are you classified as"
        r"|verified (?:eli )?(?:identity|classification) audit"
        r"|full (?:verified )?(?:eli )?(?:identity|classification) audit"
        r")\b",
        low,
    ):
        return {
            "action": "ELI_IDENTITY_AUDIT",
            "args": {"question": str(raw or "")},
            "confidence": 0.997,
            "meta": {
                "matched_by": "eli.identity_audit_route_contract",
                "need_grounding": True,
                "allow_chat_without_evidence": False,
                "task_family": "grounded_identity_audit",
                "response_contract": "verified_local_classification_matrix",
            },
        }
    return None


def _eli_phase38_runtime_status_or_name_source_contract(raw):
    import re as _re

    low = _re.sub(r"\s+", " ", str(raw or "").lower()).strip()

    runtime_status_query = (
        ("who are you" in low or "what are you" in low)
        and (
            "actually running" in low
            or "running on right now" in low
            or "model" in low
            or "context size" in low
            or "gpu layers" in low
            or "everything" in low
        )
    )

    if runtime_status_query:
        return {
            "action": "RUNTIME_STATUS",
            "args": {"question": str(raw or "")},
            "confidence": 0.995,
            "meta": {
                "matched_by": "eli.final_runtime_status_route_contract",
                "need_grounding": True,
                "allow_chat_without_evidence": False,
                "task_family": "grounded_status",
                "response_contract": "quick_direct_nonquick_persona_synthesis",
            },
        }

    if (
        ("how do you know" in low and "name" in low)
        or ("where" in low and "name" in low and ("file" in low or "located" in low or "stored" in low))
        or ("which file" in low and "name" in low)
    ):
        return {
            "action": "NAME_SOURCE_AUDIT",
            "args": {"question": str(raw or "")},
            "confidence": 0.99,
            "meta": {
                "matched_by": "eli.final_name_source_audit_route_contract",
                "need_grounding": True,
                "allow_chat_without_evidence": False,
                "task_family": "grounded_audit",
            },
        }

    return None


def _eli_phase38_identity_name_source_single_safe_contract(raw):
    low = str(raw or "").lower().strip()

    if (
        ("how do you know" in low and "name" in low)
        or ("where" in low and "name" in low and ("file" in low or "located" in low or "stored" in low))
        or ("which file" in low and "name" in low)
    ):
        return {
            "action": "NAME_SOURCE_AUDIT",
            "args": {"question": str(raw or "")},
            "confidence": 0.99,
            "meta": {
                "matched_by": "identity.name_source_audit.single_safe",
                "need_grounding": True,
                "allow_chat_without_evidence": False,
                "task_family": "grounded_audit",
            },
        }

    return None


def _eli_phase38_final_memory_question_contract(raw):
    import re as _re

    low = _re.sub(r"\s+", " ", str(raw or "").lower()).strip()

    asks_memory_internals = (
        "memory system" in low
        or "memory internals" in low
        or ("which files" in low and "db tables" in low)
        or ("which db tables" in low)
        or ("which functions" in low and "memory" in low)
        or ("how" in low and "memory" in low and ("works" in low or "internally" in low))
    )

    asks_personal_memory = (
        "what do you know about me" in low
        or "what you know about me" in low
        or "what have you stored about me" in low
        or "what you actually remember" in low
        or "remember about me" in low
        or ("most recent things" in low and "stored" in low and "me" in low)
        or "patterns have you detected" in low
        or "how i interact with you" in low
    )

    if asks_memory_internals and asks_personal_memory:
        return {
            "action": "PERSONAL_MEMORY_DEEP_EXPLAIN",
            "args": {"question": str(raw or "")},
            "confidence": 0.995,
            "meta": {
                "matched_by": "eli.final_memory_hybrid_route_contract",
                "need_grounding": True,
                "allow_chat_without_evidence": False,
                "task_family": "personal_memory",
                "forbid_schema_dump": True,
                "forbid_reflection_spam": True,
                "forbid_news_rows": True,
                "response_contract": "quick_direct_nonquick_persona_synthesis",
            },
        }

    if asks_memory_internals:
        return {
            "action": "EXPLAIN_MEMORY_RUNTIME",
            "args": {"question": str(raw or "")},
            "confidence": 0.995,
            "meta": {
                "matched_by": "eli.final_memory_internals_route_contract",
                "need_grounding": True,
                "allow_chat_without_evidence": False,
                "task_family": "grounded_audit",
            },
        }

    if asks_personal_memory:
        return {
            "action": "PERSONAL_MEMORY_SUMMARY",
            "args": {"question": str(raw or "")},
            "confidence": 0.995,
            "meta": {
                "matched_by": "eli.final_personal_memory_summary_route_contract",
                "need_grounding": True,
                "allow_chat_without_evidence": False,
                "task_family": "personal_memory",
                "forbid_schema_dump": True,
                "forbid_reflection_spam": True,
                "forbid_news_rows": True,
            },
        }

    return None


def _eli_phase38_persona_override_contract(raw):
    import re as _re

    low = _re.sub(r"\s+", " ", str(raw or "").lower()).strip(" .,!?:;")

    if low in {
        "elaborate more",
        "elaborate",
        "continue",
        "go on",
        "more detail",
        "explain more",
        "tell me more",
    }:
        return _mk(
            "CHAT",
            {
                "message": (
                    "Continue the immediately previous answer. "
                    "No role prefix. No HR filler. Stay in ELI's direct voice."
                )
            },
            0.95,
            matched_by="eli.final_followup_override",
            allow_chat_without_evidence=False,
        )

    if low in {
        "what's the story here we go",
        "whats the story here we go",
        "what's the story",
        "whats the story",
    }:
        return _mk(
            "CHAT",
            {
                "message": (
                    "Brief operational status in ELI's direct, dry voice. "
                    "One or two sentences max. Say what's running, call out anything broken or "
                    "degraded if relevant, say what's next if there is something. "
                    "No bullet points. No corporate framing. No \"I am happy to report\" filler. "
                    "Just the facts, ELI's way."
                )
            },
            0.95,
            matched_by="eli.final_story_status_override",
            allow_chat_without_evidence=False,
        )

    return None


def _eli_phase38_followup_passthrough_contract(raw):
    import re as _re

    low = _re.sub(r"\s+", " ", str(raw or "").lower()).strip(" .,!?:;")

    if low in {
        "elaborate more",
        "elaborate",
        "continue",
        "go on",
        "more",
        "more detail",
        "expand",
        "explain more",
        "tell me more",
        "go ahead",
        "go ahead please",
        "yeah go ahead",
        "please go ahead",
        "yes go ahead",
        "sure go ahead",
        "go",
        "proceed",
        "keep going",
    }:
        return _mk(
            "CHAT",
            {"message": str(raw or "")},
            0.90,
            matched_by="eli.followup.short_contextual",
            allow_chat_without_evidence=False,
        )

    return None


def _eli_phase38_identity_contract(raw):
    import re as _re

    low = _re.sub(r"\s+", " ", str(raw or "").lower()).strip(" .,!?:;")

    if _re.search(
        r"\b(who are you|what are you(?!\s+\w)|what is your name|what's your name|tell me about yourself)\b",
        low,
    ):
        # Persona/identity questions answered from ELI's character + memory.
        # SELF_REPORT (raw spec JSON) is wrong here — that's for runtime/model queries.
        if not _re.search(r"\b(model|running on|provider|context|gpu|llm|specs?|technical|runtime|layers|threads|batch)\b", low):
            return _mk(
                "CHAT",
                {"message": raw},
                0.99,
                matched_by="identity.persona_chat",
                allow_chat_without_evidence=True,
            )
        return _mk(
            "SELF_REPORT",
            {},
            0.99,
            matched_by="identity.final_self_report",
            allow_chat_without_evidence=False,
        )

    if _re.search(
        r"\b(who am i|do you know who i am|do you know me|do you remember me|"
        r"what is my name|what('s| is) my name|what do you know about me|"
        r"you do not know who i am|you don'?t know who i am|"
        r"don'?t you know who i am|don'?t you know me|"
        r"you don'?t know me|you have no idea who i am)\b",
        low,
    ):
        return _mk(
            "USER_IDENTITY_SUMMARY",
            {},
            0.99,
            matched_by="identity.final_user_summary",
            allow_chat_without_evidence=False,
        )

    return None


def _eli_phase38_open_typo_or_core_route(raw, *args, **kwargs):
    t = _eli_open_typo_norm(raw)

    if t in {"open spotify", "launch spotify", "start spotify", "spotify open"}:
        return {
            "action": "OPEN_APP",
            "args": {"name": "spotify"},
            "confidence": 0.999,
            "meta": {"matched_by": "eli.open_typo.spotify", "normalized": t},
        }

    if t in {"open browser", "open web browser", "browser", "launch browser", "start browser"}:
        return {
            "action": "OPEN_APP",
            "args": {"name": "browser"},
            "confidence": 0.999,
            "meta": {"matched_by": "eli.open_typo.browser", "normalized": t},
        }

    core = globals().get("_ROUTE_CORE")
    if callable(core):
        return core(raw, *args, **kwargs)

    return {
        "action": "CHAT",
        "args": {"message": str(raw or "")},
        "confidence": 0.25,
        "meta": {"matched_by": "phase38.missing_route_core_fallback"},
    }


def _eli_media_contract_post(raw, result):
    """Final media-routing contract for legacy GUI/STT command shapes."""
    try:
        original = str(raw or "")
        low = re.sub(r"\s+", " ", original.lower()).strip(" .,!?:;")
        if not low:
            return result
        text = re.sub(r"^(?:eli|vera|computer|assistant|buddy)\s+", "", low).strip()

        def _target(value: str) -> str:
            target = re.sub(r"^(?:the|a|an)\s+", "", str(value or "").strip(" .,!?:;"))
            target = target.replace("prime video", "primevideo")
            target = target.replace("disney plus", "disneyplus")
            if target in {"tv", "and tv", "television", "the tv"}:
                return "mpv"
            return target

        def _play(target: str, query: str, matched_by: str):
            return _mk(
                "PLAY_MEDIA",
                {"target": _target(target), "query": str(query or "").strip()},
                0.97,
                matched_by=matched_by,
                entities={"target": _target(target), "query": str(query or "").strip()},
            )

        if (
            re.match(r"^play\b", text)
            and "situation brief" in text
            and "conversation history" in text
        ):
            return _mk("CHAT", {"message": original}, 0.99, matched_by="media.internal_prompt_echo_guard")

        if re.fullmatch(r"play(?:\s+the)?", text) or re.fullmatch(r"play\s+.+\s+(?:by|on)", text):
            return _mk(
                "NOOP",
                {"message": "Incomplete command: tell me what to play and the artist name or service."},
                0.99,
                matched_by="media.incomplete_play_guard",
            )

        # ── "youtube web/website" variants → browser (yt-dlp resolves watch URL) ─
        _ytw = r"youtube\s+web(?:site)?"
        m = re.match(rf"^play\s+(.+?)\s+on\s+({_ytw})\s*$", text)
        if m:
            return _play(m.group(2), m.group(1), "media.play_on_youtube_web_contract")

        m = re.match(rf"^play\s+({_ytw})\s+(.+)$", text)
        if m:
            return _play(m.group(1), m.group(2), "media.play_youtube_web_prefix_contract")

        m = re.match(rf"^(.+?)\s+(?:by\s+.+?\s+)?on\s+({_ytw})\s*$", text)
        if m:
            return _play(m.group(2), m.group(1), "media.query_on_youtube_web_contract")

        m = re.match(r"^play\s+(youtube|spotify|soundcloud)\s+(.+)$", text)
        if m:
            return _play(m.group(1), m.group(2), "media.play_target_prefix_contract")

        m = re.match(r"^(youtube|spotify|soundcloud)\s+play\s+(.+)$", text)
        if m:
            return _play(m.group(1), m.group(2), "media.target_play_prefix_contract")

        m = re.match(r"^on\s+(youtube|spotify|soundcloud)\s+play\s+(.+)$", text)
        if m:
            return _play(m.group(1), m.group(2), "media.on_target_play_contract")

        m = re.match(r"^play\s+(.+?)\s+on\s+(youtube|spotify|soundcloud|mpv)\s*$", text)
        if m:
            return _play(m.group(2), m.group(1), "media.play_query_on_target_contract")

        m = re.match(r"^play\s+(.+\s+by\s+.+)$", text)
        if m:
            return _play("spotify", m.group(1), "media.play_song_by_artist_contract")

        # Implied song request — "title by artist" with no "play" verb.
        # Matches "all eyez on me by tupac" / "bohemian rhapsody by queen".
        # Negative lookahead excludes sentences starting with action/question verbs
        # so "explain X by Y" / "search X by Y" / "what is X by Y" fall through.
        m = re.match(
            r"^(?!(?:search|find|look|show|get|tell|what|how|why|when|where|which|who"
            r"|is|are|was|were|will|can|could|should|would|do|does|did"
            r"|make|create|run|start|stop|open|close|pause|explain|describe|define"
            r"|read|write|list|audit|check|scan|review|analyse|analyze"
            r"|created?|written?|made|designed?|built|developed?)\b)"
            r"(.{4,70})\s+by\s+([a-z][a-z\s]{1,35})$",
            text,
        )
        if m:
            return _play("spotify", raw, "media.implied_song_by_artist")

        m = re.match(r"^(open|launch|start|close|quit|kill|exit)\s+(.+?)$", text)
        if m:
            verb = m.group(1)
            name = _clean_app_name(m.group(2)).lower()
            known = (
                name in WEBSITE_ALIASES
                or name in MEDIA_APPS
                or name in DESKTOP_APP_PRIORITY
                or name in APP_ALIASES
                or name in {"browser", "youtube"}
            )
            if known:
                action = "CLOSE_APP" if verb in {"close", "quit", "kill", "exit"} else "OPEN_APP"
                return _mk(action, {"name": name}, 0.98, matched_by="app.wake_prefix_contract")

        controls = {
            "pause": ("PAUSE_MEDIA", "pause"),
            "resume": ("PLAY_MEDIA", "play"),
            "play": ("PLAY_MEDIA", "play"),
            "stop": ("STOP_MEDIA", "stop"),
            "next": ("NEXT_MEDIA", "next"),
            "skip": ("NEXT_MEDIA", "next"),
            "previous": ("PREVIOUS_MEDIA", "previous"),
            "prev": ("PREVIOUS_MEDIA", "previous"),
            "back": ("PREVIOUS_MEDIA", "previous"),
        }
        target_words = "|".join(sorted(map(re.escape, MEDIA_APPS + ["and tv", "tv"]), key=len, reverse=True))

        m = re.match(rf"^({'|'.join(controls)})\s+({target_words})$", text)
        if m:
            action, command = controls[m.group(1)]
            target = _target(m.group(2))
            return _mk(
                action,
                {"target": target},
                0.97,
                matched_by="media.targeted_control_contract",
                entities={"target": target, "command": command},
            )

        m = re.match(rf"^({target_words})\s+({'|'.join(controls)})$", text)
        if m:
            action, command = controls[m.group(2)]
            target = _target(m.group(1))
            return _mk(
                action,
                {"target": target},
                0.97,
                matched_by="media.reverse_targeted_control_contract",
                entities={"target": target, "command": command},
            )

        m = re.match(r"^(pause|resume)\s+(.+)$", text)
        if m:
            command = "play" if m.group(1) == "resume" else "pause"
            target = _target(m.group(2))
            if target and len(target.split()) <= 5:
                return _mk(
                    "MEDIA_CONTROL",
                    {"command": command, "target": target, "type": "dynamic"},
                    0.91,
                    matched_by="media.dynamic_control_contract",
                    entities={"target": target, "command": command},
                )
    except Exception:
        return result
    return result


def _eli_phase38_media_query_cleaner_post(result):
    try:
        if isinstance(result, dict) and str(result.get("action") or "").upper() == "PLAY_MEDIA":
            args = result.setdefault("args", {})
            query = str(args.get("query") or "")
            cleaned = _eli_mqc_clean_query(query)
            if cleaned:
                args["query"] = cleaned
                result.setdefault("meta", {})["query_cleaned_by"] = "eli.final_media_query_cleaner"
    except Exception:
        pass
    return result


def _eli_phase38_tiny_fragment_post(raw, result):
    import json as _json
    import re as _re

    try:
        if isinstance(result, dict) and str(result.get("action") or "").upper() == "CHAT":
            low = _re.sub(r"\s+", " ", str(raw or "").lower()).strip(" .,!?:;")
            words = _re.findall(r"[a-z0-9']+", low)

            allowed_short = _re.search(
                r"\b("
                r"who are you|who am i|who made you|who built you|"
                r"what are you|what is this|what is it|"
                r"are you (?:sentient|alive|conscious|real|there|ok|okay)|"
                r"describe yourself|describe your|introduce yourself|tell me about yourself|"
                r"how many memories|"
                r"elaborate more|elaborate|continue|go on|more detail|expand|explain more|tell me more|"
                r"remember this|save this|help me|explain|why|how|what|where|when|who|"
                r"okay|ok|yes|no|nope|yep|yeah|sure|agreed|correct|exactly|right|fair|"
                r"nice|cool|great|perfect|good|got it|understood|alright|indeed|true|false|"
                r"hi|hello|hey|howya|hiya|yo|sup|afternoon|morning|evening|night|"
                r"for fucksake|fucksake|for fuck sake|jesus|jaysus|seriously|what the|"
                r"fuck off|piss off|cop on|come on|wise up"
                r")\b",
                low,
            )

            ends_in_terminator = bool(_re.search(r"[.?!]\s*$", str(raw or "").strip()))

            looks_fragmentary = (
                not ends_in_terminator
                and (
                    len(words) <= 1
                    or str(raw or "").strip().endswith("-")
                    or low in {"preview", "resil", "i u", "here i will", "find your mo"}
                )
            )

            if looks_fragmentary and _re.fullmatch(
                r"(?:date|the\s+date|is\s+the\s+date|what\s+date|what\s+is\s+the\s+date|what's\s+the\s+date|today|what\s+day|what\s+days|their\s+date|tell\s+me\s+their\s+days)",
                low,
            ):
                return _mk("DATE", {}, 0.999, matched_by="system.date.fragment")

            if looks_fragmentary and _re.fullmatch(
                r"(?:time|the\s+time|what\s+time|what\s+is\s+the\s+time|what's\s+the\s+time)",
                low,
            ):
                return _mk("TIME", {}, 0.999, matched_by="system.time.fragment")

            if looks_fragmentary and low in {
                "date",
                "the date",
                "is the date",
                "what date",
                "what days",
                "what's the day",
                "what's the days",
                "what day",
                "what day is it",
                "what day is this",
                "their date",
                "tell me their days",
            }:
                return _mk("DATE", {}, 0.999, matched_by="system.date.fragment")

            if looks_fragmentary and low in {
                "time",
                "the time",
                "what time",
                "what is the time",
                "what's the time",
            }:
                return _mk("TIME", {}, 0.999, matched_by="system.time.fragment")

            if looks_fragmentary and not allowed_short:
                # install/download commands are valid 2-word actions — bypass
                # the fragment guard and let the remediation handler process them.
                _idm = _re.match(r"^(install|download|get|setup)\s+(\S+)", low)
                if _idm:
                    return _mk(
                        "CONFIRM_PENDING_REMEDIATION",
                        {"message": str(raw or "").strip()},
                        0.97,
                        matched_by="remediation.install_download_fragment_bypass",
                    )

                # Pending-repair confirmation bypass — if a repair plan is waiting
                # and the input contains a clear yes/no word (even with STT noise),
                # route to remediation instead of dropping as a fragment.
                try:
                    from eli.runtime import grounded_remediation as _gr_frag
                    if _gr_frag.get_pending():
                        if _re.search(r'\b(yes|confirm|confirmed|proceed|go ahead|do it)\b', low, _re.I):
                            return _mk(
                                "CONFIRM_PENDING_REMEDIATION",
                                {"message": str(raw or "").strip()},
                                0.95,
                                matched_by="pending_remediation.yes_intercept",
                            )
                        if _re.search(r'\b(no|cancel|abort|stop|never mind)\b', low, _re.I):
                            return _mk(
                                "CONFIRM_PENDING_REMEDIATION",
                                {"message": str(raw or "").strip()},
                                0.95,
                                matched_by="pending_remediation.no_intercept",
                            )
                except Exception:
                    pass

                grid_text = str(raw or "").strip().lower().replace("×", "x")
                grid_text = _re.sub(r"\btree\b", "3", grid_text)
                grid_text = _re.sub(r"\bthree\b", "3", grid_text)
                grid_text = _re.sub(r"\btwo\b", "2", grid_text)
                grid_text = _re.sub(r"\bfour\b", "4", grid_text)

                grid_m = _re.fullmatch(r"(\d{1,2})\s*(?:x|by)\s*(\d{1,2})", grid_text)
                if grid_m:
                    cols, rows = int(grid_m.group(1)), int(grid_m.group(2))
                    if 1 <= cols <= 8 and 1 <= rows <= 8:
                        return _mk(
                            "TILE_WINDOWS",
                            {"cols": cols, "rows": rows, "grid": [cols, rows]},
                            0.985,
                            matched_by="window.grid_followup",
                        )

                msg = _json.dumps(
                    {
                        "event": "input_fragment_guard",
                        "heard": str(raw or "").strip(),
                        "routed_to_cognition": False,
                        "reason": "fragmentary_input",
                    },
                    ensure_ascii=False,
                )

                return _mk(
                    "NOOP",
                    {"message": msg, "response": msg, "content": msg},
                    0.999,
                    matched_by="eli.tiny_chat_fragment_guard",
                )

    except Exception:
        pass

    return result


def _eli_phase38_bottom_core_dispatch(raw, *args, **kwargs):
    identity = _eli_phase38_identity_contract(raw)
    if identity is not None:
        return identity

    result = _eli_phase38_open_typo_or_core_route(raw, *args, **kwargs)
    result = _eli_phase38_media_query_cleaner_post(result)
    result = _eli_phase38_tiny_fragment_post(raw, result)
    return result


def _eli_phase38_voice_portable_persona_lower_dispatch(raw, *args, **kwargs):
    if callable(_eli_phase38_portable_try_route):
        try:
            portable = _eli_phase38_portable_try_route(raw)
            if portable is not None:
                return portable
        except Exception:
            pass

    voice = globals().get("_eli_voice_contract_route")
    if callable(voice):
        try:
            shortcut = voice(raw)
            if shortcut is not None:
                return shortcut
        except Exception:
            pass

    persona = _eli_phase38_persona_override_contract(raw)
    if persona is not None:
        return persona

    followup = _eli_phase38_followup_passthrough_contract(raw)
    if followup is not None:
        return followup

    return _eli_phase38_bottom_core_dispatch(raw, *args, **kwargs)


def _eli_phase38_lower_contract_dispatch(raw, *args, **kwargs):
    lrf_pre = globals().get("_eli_lrf_pre_route")
    if callable(lrf_pre):
        try:
            out = lrf_pre(raw)
            if out is not None:
                return out
        except Exception:
            pass

    return _eli_phase38_voice_portable_persona_lower_dispatch(raw, *args, **kwargs)


def _eli_phase38_personal_memory_guard_dispatch(raw, *args, **kwargs):
    pm_pre = globals().get("_eli_pm_pre_route")
    if callable(pm_pre):
        try:
            out = pm_pre(raw)
            if out is not None:
                return out
        except Exception:
            pass

    return _eli_phase38_lower_contract_dispatch(raw, *args, **kwargs)


def _eli_phase38_self_improvement_dispatch(raw, *args, **kwargs):
    sig = globals().get("_eli_self_improvement_phrase_guard")
    if callable(sig):
        try:
            guarded = sig(raw)
            if guarded:
                return guarded
        except Exception:
            pass

    return _eli_phase38_personal_memory_guard_dispatch(raw, *args, **kwargs)


def _eli_phase38_runtime_cognition_failure_dispatch(raw, *args, **kwargs):
    rcfg = globals().get("_eli_runtime_cognition_failure_guard")
    if callable(rcfg):
        try:
            guarded = rcfg(raw)
            if guarded:
                return guarded
        except Exception:
            pass

    return _eli_phase38_self_improvement_dispatch(raw, *args, **kwargs)


def _eli_phase38_identity_name_dispatch(raw, *args, **kwargs):
    identity_name = _eli_phase38_identity_name_source_single_safe_contract(raw)
    if identity_name is not None:
        return identity_name

    return _eli_phase38_runtime_cognition_failure_dispatch(raw, *args, **kwargs)


def _eli_phase38_runtime_status_dispatch(raw, *args, **kwargs):
    status_or_name = _eli_phase38_runtime_status_or_name_source_contract(raw)
    if status_or_name is not None:
        return status_or_name

    return _eli_phase38_identity_name_dispatch(raw, *args, **kwargs)


def _eli_phase38_final_memory_dispatch(raw, *args, **kwargs):
    memory_contract = _eli_phase38_final_memory_question_contract(raw)
    if memory_contract is not None:
        return memory_contract

    return _eli_phase38_runtime_status_dispatch(raw, *args, **kwargs)


def _eli_phase38_personal_memory_summary_compat_post(out):
    if isinstance(out, dict) and out.get("action") == "PERSONAL_MEMORY_SUMMARY":
        out = dict(out)
        meta = dict(out.get("meta") or {})
        meta["matched_by"] = "eli.personal_memory_summary_first_class"
        meta["forbid_schema_dump"] = True
        meta["forbid_reflection_spam"] = True
        meta["forbid_news_rows"] = True
        out["meta"] = meta
    return out


def _eli_phase38_identity_scope_post(raw, out):
    if isinstance(out, dict) and str(out.get("action") or "").upper() == "USER_IDENTITY_SUMMARY":
        out = dict(out)

        route_args = dict(out.get("args") or {})
        route_args["question"] = str(raw or "")
        route_args["identity_scope"] = _eli_identity_scope_for_text(raw)
        out["args"] = route_args

        meta = dict(out.get("meta") or {})
        meta["identity_scope_contract"] = route_args["identity_scope"]
        meta["forbid_profile_memory_dump"] = True
        meta["forbid_preferences"] = True
        out["meta"] = meta

    return out


def _eli_phase38_profile_scope_dispatch(raw, *args, **kwargs):
    low = _eli_profile_scope_low(raw)

    if _eli_is_explicit_preference_request(low):
        return _eli_profile_scope_result(
            "PERSONAL_MEMORY_SUMMARY",
            raw,
            "preferences_detail",
            matched_by="profile.scope_contract.preferences_detail",
        )

    if _eli_is_full_profile_dump(low):
        return _eli_profile_scope_result(
            "PERSONAL_MEMORY_SUMMARY",
            raw,
            "full_profile",
            matched_by="profile.scope_contract.full_profile",
        )

    out = _eli_phase38_final_memory_dispatch(raw, *args, **kwargs)
    out = _eli_phase38_personal_memory_summary_compat_post(out)
    out = _eli_phase38_identity_scope_post(raw, out)

    if isinstance(out, dict):
        action = str(out.get("action") or "").upper()
        if action == "PERSONAL_MEMORY_SUMMARY" and _eli_is_generic_profile_inventory(low):
            out = dict(out)
            out["args"] = dict(out.get("args") or {})
            out["args"]["question"] = str(raw or "")
            out["args"]["profile_scope"] = "inventory_only"

            out["meta"] = dict(out.get("meta") or {})
            out["meta"]["profile_scope_contract"] = "inventory_only"
            out["meta"]["forbid_preference_detail"] = True
            out["meta"]["forbid_project_detail"] = True
            out["meta"]["active_user_scoped"] = True
            return out

    return out


def _eli_phase38_memory_count_dispatch(raw, *args, **kwargs):
    if _eli_is_memory_count_question(raw):
        return {
            "action": "MEMORY_STATUS",
            "args": {
                "question": str(raw or ""),
                "memory_scope": "count_only",
            },
            "confidence": 0.995,
            "meta": {
                "matched_by": "memory.count.grounded_synthesis",
                "allow_chat_without_evidence": False,
                "requires_grounded_synthesis": True,
                "requires_output_validation": True,
                "quick_direct_allowed": True,
                "forbid_unverified_generation": True,
            },
        }

    out = _eli_phase38_profile_scope_dispatch(raw, *args, **kwargs)

    if isinstance(out, dict) and str(out.get("action") or "").upper() == "MEMORY_STATUS":
        if _eli_is_memory_count_question(raw):
            real_args = dict(out.get("args") or {})
            real_args["question"] = str(raw or "")
            real_args["memory_scope"] = "count_only"
            out["args"] = real_args

            meta = dict(out.get("meta") or {})
            meta["matched_by"] = "memory.count.grounded_synthesis.post_route"
            meta["requires_grounded_synthesis"] = True
            meta["requires_output_validation"] = True
            meta["quick_direct_allowed"] = True
            meta["forbid_unverified_generation"] = True
            out["meta"] = meta

    return out


def _eli_phase38_recent_memory_dispatch(raw, *args, **kwargs):
    if _eli_recent_memory_processing_question(raw):
        return {
            "action": "MEMORY_STATUS",
            "args": {
                "question": str(raw or ""),
                "memory_scope": "recent_processing",
            },
            "confidence": 0.995,
            "meta": {
                "matched_by": "memory.recent_processing_grounded",
                "task_family": "memory_runtime",
                "grounded_required": True,
                "forbid_chat_fallback": True,
                "forbid_fake_memory_activity": True,
                "allow_chat_without_evidence": False,
            },
        }

    return _eli_phase38_memory_count_dispatch(raw, *args, **kwargs)


def _eli_phase38_self_report_recent_updates_dispatch(raw, *args, **kwargs):
    if _eli_self_report_recent_updates_question(raw):
        return {
            "action": "SELF_REPORT",
            "args": {
                "question": str(raw or ""),
                "self_report_scope": "recent_updates",
            },
            "confidence": 0.995,
            "meta": {
                "matched_by": "self_report.recent_updates_grounded",
                "task_family": "self_report_runtime",
                "grounded_required": True,
                "forbid_chat_fallback": True,
                "forbid_fake_update_claims": True,
                "allow_chat_without_evidence": False,
            },
        }

    return _eli_phase38_recent_memory_dispatch(raw, *args, **kwargs)


def _eli_phase38_gui_actual_scan_dispatch(raw, *args, **kwargs):
    if _eli_gui_audit_actual_scan_v2(raw):
        return {
            "action": "GUI_RUNTIME_AUDIT",
            "args": {
                "question": str(raw or ""),
                "proof_requested": True,
                "audit_depth": "proof",
                "require_timestamps": True,
                "require_full_file_read_evidence": True,
            },
            "confidence": 0.995,
            "meta": {
                "matched_by": "router.gui_audit_actual_scan_proof_v2",
                "need_grounding": True,
                "allow_chat_without_evidence": False,
                "task_family": "grounded_audit",
                "forbid_chat_fallback": True,
            },
        }

    return _eli_phase38_self_report_recent_updates_dispatch(raw, *args, **kwargs)


def _eli_phase38_memory_runtime_lock_dispatch(raw, *args, **kwargs):
    if _eli_memory_runtime_route_lock_should_trigger(raw):
        return _eli_memory_runtime_route_lock_result(raw)

    return _eli_phase38_gui_actual_scan_dispatch(raw, *args, **kwargs)


def _eli_phase38_flattened_route(raw="", *args, **kwargs):
    text = str(raw or "")

    precedence = _eli_phase38_route_precedence_contract(text)
    if precedence is not None:
        return _eli_phase38_enrich_pdf_if_needed(text, precedence)

    result = _eli_phase38_memory_runtime_lock_dispatch(text, *args, **kwargs)
    return _eli_phase38_enrich_pdf_if_needed(text, result)


log.debug("[ROUTER] router_enhanced module loaded — canonical dispatch pipeline active")

# =============================================================================
# End ELI_PHASE38_FLATTENED_CANONICAL_DISPATCH_V1
# =============================================================================

# =============================================================================
# ELI_ROUTE_PRIORITY_PIPELINE_V1
# Explicit priority pipeline replacing nested phase-chain dispatch as the
# active exported route surface.
# =============================================================================
try:
    if not globals().get("_ELI_ROUTE_PRIORITY_PIPELINE_V1"):
        _ELI_ROUTE_PRIORITY_PIPELINE_V1 = True

        def _eli_route_priority_stages():
            def _stage_precedence(text, *_a, **_k):
                return _eli_phase38_route_precedence_contract(text)

            def _stage_frontier_status(text, *_a, **_k):
                return _eli_phase38_frontier_status_contract(text)

            def _stage_identity_audit(text, *_a, **_k):
                return _eli_phase39_identity_audit_contract(text)

            def _stage_memory_runtime_lock(text, *_a, **_k):
                if _eli_memory_runtime_route_lock_should_trigger(text):
                    return _eli_memory_runtime_route_lock_result(text)
                return None

            def _stage_gui_actual_scan(text, *_a, **_k):
                if _eli_gui_audit_actual_scan_v2(text):
                    return {
                        "action": "GUI_RUNTIME_AUDIT",
                        "args": {
                            "question": str(text or ""),
                            "proof_requested": True,
                            "audit_depth": "proof",
                            "require_timestamps": True,
                            "require_full_file_read_evidence": True,
                        },
                        "confidence": 0.995,
                        "meta": {
                            "matched_by": "router.gui_audit_actual_scan_proof_v2",
                            "need_grounding": True,
                            "allow_chat_without_evidence": False,
                            "task_family": "grounded_audit",
                            "forbid_chat_fallback": True,
                        },
                    }
                return None

            def _stage_self_report_recent_updates(text, *_a, **_k):
                if _eli_self_report_recent_updates_question(text):
                    return {
                        "action": "SELF_REPORT",
                        "args": {"question": str(text or ""), "self_report_scope": "recent_updates"},
                        "confidence": 0.995,
                        "meta": {
                            "matched_by": "self_report.recent_updates_grounded",
                            "task_family": "self_report_runtime",
                            "grounded_required": True,
                            "forbid_chat_fallback": True,
                            "forbid_fake_update_claims": True,
                            "allow_chat_without_evidence": False,
                        },
                    }
                return None

            def _stage_recent_memory(text, *_a, **_k):
                if _eli_recent_memory_processing_question(text):
                    return {
                        "action": "MEMORY_STATUS",
                        "args": {"question": str(text or ""), "memory_scope": "recent_processing"},
                        "confidence": 0.995,
                        "meta": {
                            "matched_by": "memory.recent_processing_grounded",
                            "task_family": "memory_runtime",
                            "grounded_required": True,
                            "forbid_chat_fallback": True,
                            "forbid_fake_memory_activity": True,
                            "allow_chat_without_evidence": False,
                        },
                    }
                return None

            def _stage_memory_count(text, *_a, **_k):
                if _eli_is_memory_count_question(text):
                    return {
                        "action": "MEMORY_STATUS",
                        "args": {"question": str(text or ""), "memory_scope": "count_only"},
                        "confidence": 0.995,
                        "meta": {
                            "matched_by": "memory.count.grounded_synthesis",
                            "allow_chat_without_evidence": False,
                            "requires_grounded_synthesis": True,
                            "requires_output_validation": True,
                            "quick_direct_allowed": True,
                            "forbid_unverified_generation": True,
                        },
                    }
                return None

            def _stage_profile_scope_explicit(text, *_a, **_k):
                low = _eli_profile_scope_low(text)
                if _eli_is_explicit_preference_request(low):
                    return _eli_profile_scope_result(
                        "PERSONAL_MEMORY_SUMMARY",
                        text,
                        "preferences_detail",
                        matched_by="profile.scope_contract.preferences_detail",
                    )
                if _eli_is_full_profile_dump(low):
                    return _eli_profile_scope_result(
                        "PERSONAL_MEMORY_SUMMARY",
                        text,
                        "full_profile",
                        matched_by="profile.scope_contract.full_profile",
                    )
                return None

            def _stage_final_memory_contract(text, *_a, **_k):
                return _eli_phase38_final_memory_question_contract(text)

            def _stage_runtime_or_name_contract(text, *_a, **_k):
                return _eli_phase38_runtime_status_or_name_source_contract(text)

            def _stage_identity_name_source_contract(text, *_a, **_k):
                return _eli_phase38_identity_name_source_single_safe_contract(text)

            def _stage_generate_script_prepass(text, *_a, **_k):
                """Fire BEFORE GPU/runtime guards so 'write a bash script that monitors GPU...'
                always routes to GENERATE_SCRIPT, not GPU_STATUS."""
                import re as _rgs
                raw2 = str(text or "").strip()
                low2 = raw2.lower()
                # Skip complaint/follow-up phrases — they are not generation requests
                _complaint_starts = (
                    "you did not", "you didn't", "you just", "that script", "this script",
                    "why did you", "why didn't you", "where is", "where did",
                )
                _complaint_frags = (
                    "did not generate", "didn't generate", "never ran", "not generated",
                    "no ide opened", "did not open", "didn't open",
                )
                if low2.startswith(_complaint_starts) or any(f in low2 for f in _complaint_frags):
                    return None
                # Skip questions
                if raw2.rstrip().endswith("?"):
                    return None
                # First token must be a creation verb (typo-tolerant whitelist).
                _CREATION_VERBS = {
                    "write", "writ", "writes", "wrtie", "wright",
                    "create", "creat", "craete", "cretae", "creaet", "crete", "crate",
                    "generate", "generat", "genrate", "genarate", "gnerate", "generete",
                    "make", "mak", "makes",
                    "build", "buil", "builds",
                    "code", "cod", "codes",
                }
                _first_tok = low2.split()[0] if low2.split() else ""
                if _first_tok not in _CREATION_VERBS:
                    return None
                # Reject negated generation: "not generate...", "don't write..."
                if _rgs.search(
                    r"\b(?:not|don'?t|never|no|stop|without|rather\s+than|instead\s+of)\b\s+\w*\s*"
                    r"(?:generate|write|create|build|make)\b", low2):
                    return None
                # Non-code creative scripts (film/podcast/etc.) → skip
                _NON_CODE_SCRIPT2 = _rgs.compile(
                    r"\b(?:for|about|on|regarding)\s+(?:[\w]+\s+)*?"
                    r"(?:presentation|slides?|talk|speech|podcast|film|movie|play|show|actors?|"
                    r"onboarding|marketing|campaign|video|youtube|event|ceremony|wedding|"
                    r"performance|audience|interview|screenplay)\b", _rgs.I)
                _CREATIVE_SCRIPT2 = _rgs.compile(
                    r"\b(?:film\s+script|movie\s+script|play\s+script|podcast\s+script|"
                    r"write\s+a\s+(?:podcast|film|stage|theatre|movie)\s+script|"
                    r"theatre\s+script|stage\s+script|script\s+for\s+(?:a\s+)?(?:film|movie|"
                    r"play|podcast|show|talk|video|event|presentation|slides?|actors?|"
                    r"onboarding|ceremony|wedding|performance|audience|interview|"
                    r"marketing|campaign|youtube))\b", _rgs.I)
                if _NON_CODE_SCRIPT2.search(raw2) or _CREATIVE_SCRIPT2.search(raw2):
                    return None
                # Explicit language keywords
                _LANG_RE = _rgs.compile(
                    r"\b(?:bash|python|shell|sh|javascript|js|typescript|ts|ruby|perl|"
                    r"powershell|zsh|fish|lua|go|golang|rust|c\+\+|cpp|java|"
                    r"script|function|program|module|code)\b", _rgs.I)
                if _LANG_RE.search(raw2):
                    return {
                        "action": "GENERATE_SCRIPT",
                        "args": {"description": raw2, "use_gguf_only": True, "forbid_ollama": True},
                        "confidence": 0.97,
                        "meta": {"matched_by": "eli.generate_script_prepass"},
                    }
                return None

            def _stage_runtime_cognition_failure_guard(text, *_a, **_k):
                rcfg = globals().get("_eli_runtime_cognition_failure_guard")
                if callable(rcfg):
                    try:
                        out = rcfg(text)
                        if out:
                            return out
                    except Exception:
                        pass
                return None

            def _stage_self_improvement_guard(text, *_a, **_k):
                sig = globals().get("_eli_self_improvement_phrase_guard")
                if callable(sig):
                    try:
                        out = sig(text)
                        if out:
                            return out
                    except Exception:
                        pass
                return None

            def _stage_personal_memory_pre_route(text, *_a, **_k):
                pm_pre = globals().get("_eli_pm_pre_route")
                if callable(pm_pre):
                    try:
                        out = pm_pre(text)
                        if out is not None:
                            return out
                    except Exception:
                        pass
                return None

            def _stage_lrf_pre_route(text, *_a, **_k):
                lrf_pre = globals().get("_eli_lrf_pre_route")
                if callable(lrf_pre):
                    try:
                        out = lrf_pre(text)
                        if out is not None:
                            return out
                    except Exception:
                        pass
                return None

            def _stage_portable_route(text, *_a, **_k):
                if callable(_eli_phase38_portable_try_route):
                    try:
                        return _eli_phase38_portable_try_route(text)
                    except Exception:
                        return None
                return None

            def _stage_voice_contract(text, *_a, **_k):
                voice = globals().get("_eli_voice_contract_route")
                if callable(voice):
                    try:
                        out = voice(text)
                        if out is not None:
                            return out
                    except Exception:
                        pass
                return None

            def _stage_persona_override(text, *_a, **_k):
                return _eli_phase38_persona_override_contract(text)

            def _stage_followup_passthrough(text, *_a, **_k):
                return _eli_phase38_followup_passthrough_contract(text)

            def _stage_identity_contract(text, *_a, **_k):
                return _eli_phase38_identity_contract(text)

            def _stage_set_user_name(text, *_a, **_k):
                import re as _re
                low = _re.sub(r"\s+", " ", str(text or "").lower()).strip()
                return _route_set_user_name(str(text or ""), low)

            def _stage_web_lookup(text, *_a, **_k):
                """Real-time factual lookups / explicit web search → WEB_SEARCH
                when network is on. Runs late (just before the core router) so
                every specific grounded/memory/identity/media stage wins first;
                this only catches what would otherwise be a stale-weights CHAT."""
                try:
                    _raw, _low = _normalize_text(text)
                    return _eli_web_lookup_prepass(_raw, _low)
                except Exception:
                    return None

            def _stage_core_router(text, *a, **k):
                return _eli_phase38_open_typo_or_core_route(text, *a, **k)

            def _stage_pending_remediation_confirm(text, *_a, **_k):
                """
                Pre-pass: if a remediation offer is pending (e.g. 'install netflix?'),
                intercept YES/NO and direct install/download commands before anything
                else can swallow them as CHAT or block them as fragments.
                """
                try:
                    import re as _re
                    from eli.runtime import grounded_remediation as _gr
                    if not _gr.get_pending():
                        return None
                    low = _re.sub(r"\s+", " ", str(text or "").strip().lower())
                    if _gr.YES_RE.match(low):
                        return {
                            "action": "CONFIRM_PENDING_REMEDIATION",
                            "args": {"message": low},
                            "confidence": 0.99,
                            "meta": {"matched_by": "pending_remediation.yes_intercept"},
                        }
                    if _gr.NO_RE.match(low):
                        return {
                            "action": "CANCEL_PENDING_REMEDIATION",
                            "args": {"message": low},
                            "confidence": 0.99,
                            "meta": {"matched_by": "pending_remediation.no_intercept"},
                        }
                    # "install X" / "download X" — route to confirmation handler
                    # which will either advance the pending plan or diagnose fresh.
                    _im = _re.match(r"^(install|download|get)\s+(\S+)", low)
                    if _im:
                        return {
                            "action": "CONFIRM_PENDING_REMEDIATION",
                            "args": {"message": low},
                            "confidence": 0.97,
                            "meta": {"matched_by": "pending_remediation.install_download_intercept"},
                        }
                except Exception:
                    pass
                return None

            def _stage_pending_proposal_confirm(text, *_a, **_k):
                """If ELI offered to do something ("Want me to set a reminder?")
                and the user now affirms, re-route the stored proposal phrase
                through the pipeline so it actually executes (or asks for
                specifics). A decline clears it and falls through to chat."""
                try:
                    from eli.runtime.pending_proposal import (
                        get_pending_proposal, clear_pending_proposal,
                    )
                    prop = get_pending_proposal()
                    if not prop:
                        return None
                    low = re.sub(r"\s+", " ", str(text or "").strip().lower())
                    try:
                        from eli.runtime.grounded_remediation import YES_RE, NO_RE
                    except Exception:
                        YES_RE = re.compile(r"^\s*(yes|y|yeah|yep|sure|ok|okay|go ahead|do it|please do|go for it)\s*$", re.I)
                        NO_RE = re.compile(r"^\s*(no|nope|nah|cancel|don'?t|never mind|leave it)\s*$", re.I)
                    if NO_RE.match(low):
                        clear_pending_proposal()
                        return None
                    if YES_RE.match(low):
                        cmd = str(prop.get("command") or "").strip()
                        clear_pending_proposal()
                        if cmd:
                            routed = route(cmd)  # pending already cleared → no recursion
                            if isinstance(routed, dict):
                                routed.setdefault("meta", {})
                                routed["meta"]["matched_by"] = "pending_proposal.confirm"
                                routed["meta"]["rerouted_from_proposal"] = cmd
                                return routed
                except Exception:
                    return None
                return None

            def _stage_react_to_pasted_content(text, *_a, **_k):
                """Highest-priority conversational guard: when the user asks ELI
                to react to / give an opinion on text they pasted or referenced,
                force CHAT before any status/memory/grounding stage can scan the
                quoted material and hijack the turn into a data dump."""
                try:
                    _raw, _low = _normalize_text(text)
                    return _eli_react_to_content_prepass(text, _raw, _low)
                except Exception:
                    return None

            return (
                ("pending_remediation_confirm", _stage_pending_remediation_confirm),
                ("pending_proposal_confirm", _stage_pending_proposal_confirm),
                ("react_to_pasted_content", _stage_react_to_pasted_content),
                ("precedence", _stage_precedence),
                ("identity_audit", _stage_identity_audit),
                ("frontier_status", _stage_frontier_status),
                ("memory_runtime_lock", _stage_memory_runtime_lock),
                ("gui_actual_scan", _stage_gui_actual_scan),
                ("self_report_recent_updates", _stage_self_report_recent_updates),
                ("recent_memory", _stage_recent_memory),
                ("memory_count", _stage_memory_count),
                ("profile_scope_explicit", _stage_profile_scope_explicit),
                ("final_memory_contract", _stage_final_memory_contract),
                ("runtime_or_name_contract", _stage_runtime_or_name_contract),
                ("identity_name_source_contract", _stage_identity_name_source_contract),
                ("generate_script_prepass", _stage_generate_script_prepass),
                ("runtime_cognition_failure_guard", _stage_runtime_cognition_failure_guard),
                ("self_improvement_guard", _stage_self_improvement_guard),
                ("personal_memory_pre_route", _stage_personal_memory_pre_route),
                ("lrf_pre_route", _stage_lrf_pre_route),
                # set_user_name runs before portable_route so explicit identity
                # assertions ("call me Jason", "my name is X") are never
                # misclassified as media-play requests by portable_intent_contract.
                ("set_user_name", _stage_set_user_name),
                ("portable_route", _stage_portable_route),
                ("weather_prepass", lambda t, *a, **k: _eli_weather_prepass(t)),
                ("shell_prepass",   lambda t, *a, **k: _eli_shell_prepass(t)),
                ("voice_contract", _stage_voice_contract),
                ("persona_override", _stage_persona_override),
                ("followup_passthrough", _stage_followup_passthrough),
                ("identity_contract", _stage_identity_contract),
                ("web_lookup", _stage_web_lookup),
                ("core_router", _stage_core_router),
            )

        _ELI_ROUTE_PRIORITY_STAGES = _eli_route_priority_stages()

        def _eli_route_apply_post_contracts(raw, out):
            out = _eli_media_contract_post(raw, out)
            out = _eli_phase38_media_query_cleaner_post(out)
            out = _eli_phase38_tiny_fragment_post(raw, out)
            out = _eli_phase38_personal_memory_summary_compat_post(out)
            out = _eli_phase38_identity_scope_post(raw, out)

            if isinstance(out, dict):
                low = _eli_profile_scope_low(raw)
                action = str(out.get("action") or "").upper()

                if action == "PERSONAL_MEMORY_SUMMARY" and _eli_is_generic_profile_inventory(low):
                    out = dict(out)
                    out["args"] = dict(out.get("args") or {})
                    out["args"]["question"] = str(raw or "")
                    out["args"]["profile_scope"] = "inventory_only"
                    out["meta"] = dict(out.get("meta") or {})
                    out["meta"]["profile_scope_contract"] = "inventory_only"
                    out["meta"]["forbid_preference_detail"] = True
                    out["meta"]["forbid_project_detail"] = True
                    out["meta"]["active_user_scoped"] = True

                if action == "MEMORY_STATUS" and _eli_is_memory_count_question(raw):
                    out = dict(out)
                    out["args"] = dict(out.get("args") or {})
                    out["args"]["question"] = str(raw or "")
                    out["args"]["memory_scope"] = "count_only"
                    out["meta"] = dict(out.get("meta") or {})
                    out["meta"]["matched_by"] = "memory.count.grounded_synthesis.post_route"
                    out["meta"]["requires_grounded_synthesis"] = True
                    out["meta"]["requires_output_validation"] = True
                    out["meta"]["quick_direct_allowed"] = True
                    out["meta"]["forbid_unverified_generation"] = True

            return out

        def _eli_priority_route(raw="", *args, **kwargs):
            text = str(raw or "")
            result = None
            matched_by = "unmatched"
            _trace = str(__import__("os").environ.get("ELI_PIPELINE_TRACE", "")).strip().lower() in {"1", "true", "yes", "on"}
            _perf = __import__("time").perf_counter
            _route_t0 = _perf()

            if _trace:
                _preview = text.replace("\n", " ").strip()
                if len(_preview) > 160:
                    _preview = _preview[:157] + "..."
                log.debug(f"[PIPELINE][ROUTER] begin text={_preview!r}")

            for stage_name, stage_fn in _ELI_ROUTE_PRIORITY_STAGES:
                _stage_t0 = _perf() if _trace else 0.0
                try:
                    candidate = stage_fn(text, *args, **kwargs)
                except Exception:
                    candidate = None
                if _trace:
                    _dt = (_perf() - _stage_t0) * 1000.0
                    log.debug(
                        f"[PIPELINE][ROUTER] stage={stage_name} hit={candidate is not None} dt_ms={_dt:.2f}",
                    )
                if candidate is not None:
                    result = candidate
                    matched_by = stage_name
                    break

            if result is None:
                result = {
                    "action": "CHAT",
                    "args": {"message": text},
                    "confidence": 0.25,
                    "meta": {"matched_by": "eli.priority_pipeline.fallback_chat"},
                }

            result = _eli_route_apply_post_contracts(text, result)
            if isinstance(result, dict):
                meta = dict(result.get("meta") or {})
                meta.setdefault("priority_pipeline_stage", matched_by)
                result["meta"] = meta
                if _trace:
                    _total = (_perf() - _route_t0) * 1000.0
                    log.debug(
                        f"[PIPELINE][ROUTER] final action={result.get('action')} "
                        f"confidence={result.get('confidence')} stage={matched_by} total_ms={_total:.2f}",
                    )
            return _eli_phase38_enrich_pdf_if_needed(text, result)

        route = _eli_priority_route  # type: ignore[assignment]
        route_intent = route
        route_command = route
        parse_command = route
        classify = route

        log.debug("[ROUTER] explicit priority pipeline installed")
except Exception as _eli_route_priority_pipeline_err:
    log.debug(f"[ROUTER] explicit priority pipeline install failed: {_eli_route_priority_pipeline_err}")
