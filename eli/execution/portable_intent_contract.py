from __future__ import annotations
def _eli_phase10_blocks_media_intent(text: str) -> bool:
    """
    Hard block document/code/analysis prompts from PLAY_MEDIA.
    This prevents long academic PDF prompts being interpreted as songs.
    """
    s = str(text or "").lower().strip()

    if len(s) > 260:
        return True

    blockers = (
        ".pdf", "[pdf content", "pdf content", "analyse", "analyze",
        "summarise", "summarize", "read and summarise", "read and summarize",
        "abstract", "research", "experiment", "hypothesis", "dataset",
        "simulation", "scientific", "framework", "theory",
        "audit", "router", "executor", "gguf_inference", "orchestrator",
        "python files", "codebase",
    )
    return any(b in s for b in blockers)


import re
from typing import Optional


def normalise_voice_text(text: str) -> str:
    text = str(text or "").strip().lower()
    text = text.replace("’", "'").replace("“", '"').replace("”", '"')
    text = text.replace(" per cent", "%").replace(" percent", "%")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _clean_target(text: str) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip(" .,:;")
    s = re.sub(r"\b(?:chikovsky|chekovsky|chaykovsky|chaikovsky)\b", "tchaikovsky", s, flags=re.I)
    s = re.sub(r"\b(?:a moral technique|immoral technique|immortal technic|immortal technical)\b", "immortal technique", s, flags=re.I)
    return re.sub(r"\s+", " ", s).strip(" .,:;")


_MEDIA_SERVICE_ALIASES = {
    "spotify": "spotify",
    "youtube": "youtube",
    "yt": "youtube",
    "you tube": "youtube",
    "soundcloud": "soundcloud",
    "netflix": "netflix",
    "net flix": "netflix",
    "prime": "primevideo",
    "prime video": "primevideo",
    "primevideo": "primevideo",
    "amazon prime": "primevideo",
    "disney": "disneyplus",
    "disney+": "disneyplus",
    "disney plus": "disneyplus",
    "disneyplus": "disneyplus",
    "hulu": "hulu",
    "twitch": "twitch",
}


def _normalise_media_service(target: str) -> str:
    key = _clean_target(target).lower()
    key = re.sub(r"\s+", " ", key)
    return _MEDIA_SERVICE_ALIASES.get(key, key)


# Words that signal the utterance is a question/instruction about an app, not
# a launch command. If any of these appear in the tail, OPEN_APP/CLOSE_APP/etc.
# should NOT capture the entire sentence as the app name.
_APP_TAIL_REJECT_TOKENS = frozenset({
    "and", "or", "but", "so", "then", "tell", "show", "explain", "describe",
    "say", "report", "what", "why", "how", "when", "where", "who", "which",
    "please", "thanks", "thank", "to", "for", "about", "regarding", "if",
    "whether", "could", "would", "should", "can", "may", "might", "do",
    "does", "did", "is", "are", "was", "were", "the",
})


def _looks_like_app_target(target: str) -> bool:
    """
    A real OPEN/CLOSE/RUN target is a short app/binary identifier.
    Reject anything that looks like a sentence: multiple words containing
    natural-language fillers, conjunctions, or wh-words.
    """
    s = str(target or "").strip()
    if not s:
        return False
    tokens = s.split()
    if len(tokens) > 4:
        return False
    if any(tok.lower() in _APP_TAIL_REJECT_TOKENS for tok in tokens):
        return False
    # First token must look like an app/binary name: letters/digits/dot/dash/underscore.
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._\-+]{0,40}", tokens[0]):
        return False
    return True


# Common TLDs the user might dictate. STT drops the dot, so "open github com"
# arrives as the two-token target "github com" and "open github dot com" as
# "github dot com" — both are web addresses, not installable apps.
_URL_TLDS = frozenset({
    "com", "org", "net", "io", "gov", "edu", "co", "uk", "ie", "dev",
    "app", "ai", "me", "info", "xyz", "tv", "fm", "cloud", "online", "site",
})


def _looks_like_url_target(target: str) -> bool:
    """True when an OPEN target is a web address rather than an app name."""
    s = str(target or "").strip().lower()
    if not s:
        return False
    if re.match(r"https?://", s):
        return True
    collapsed = re.sub(r"\s+dot\s+", ".", s)
    # Spoken "<name> com" (dot dropped by STT): two tokens, trailing TLD word.
    toks = collapsed.split()
    if len(toks) == 2 and toks[1] in _URL_TLDS and re.fullmatch(r"[a-z0-9\-]+", toks[0]):
        return True
    # Embedded dotted domain, e.g. "github.com", "docs.python.org".
    if re.search(r"\b[a-z0-9\-]+\.(?:%s)\b" % "|".join(_URL_TLDS), collapsed):
        return True
    return False


def _build_url(target: str) -> str:
    """Normalise a dictated web address into a real https URL."""
    s = str(target or "").strip().lower()
    if re.match(r"https?://", s):
        return s
    s = re.sub(r"\s+dot\s+", ".", s)
    toks = s.split()
    if len(toks) == 2 and toks[1] in _URL_TLDS:
        s = toks[0] + "." + toks[1]
    s = re.sub(r"\s+", "", s)
    return "https://" + s


_SCRIPT_LANGUAGE_ALIASES = {
    "py": "python",
    "python3": "python",
    "node": "javascript",
    "nodejs": "javascript",
    "js": "javascript",
    "ts": "typescript",
    "sh": "bash",
    "shell": "bash",
    "csharp": "c#",
    "rs": "rust",
    "golang": "go",
    "ps": "powershell",
    "pwsh": "powershell",
}

_SCRIPT_LANGUAGE_NAMES = frozenset({
    "python", "bash", "zsh", "javascript", "typescript", "c", "c++", "cpp",
    "c#", "java", "rust", "go", "ruby", "php", "lua", "r", "swift",
    "kotlin", "scala", "sql", "html", "css", "json", "yaml", "yml",
    "julia", "fortran", "perl", "powershell",
})

_SCRIPT_LANGUAGE_REJECTS = frozenset({
    "a", "an", "the", "ide", "labs", "tab", "default", "previous",
    "following", "this", "that", "advanced", "basic", "simple", "new",
    "powerful", "potent",
})


def _normalise_script_language(candidate: str) -> str | None:
    value = str(candidate or "").strip().lower().rstrip(".,:;")
    if not value or value in _SCRIPT_LANGUAGE_REJECTS:
        return None
    value = _SCRIPT_LANGUAGE_ALIASES.get(value, value)
    if value in _SCRIPT_LANGUAGE_NAMES:
        return value
    return None


def infer_script_language(text: str) -> str:
    norm = normalise_voice_text(text)

    m = re.search(
        r"\b(?:generate|write|create|build|make)\s+(?:a|an|the)?\s*([a-z0-9+#.\-]{1,40})\s+(?:script|code|program|module|tool|app)\b",
        norm,
    )
    if m:
        language = _normalise_script_language(m.group(1))
        if language:
            return language

    for m in re.finditer(r"\b(?:in|using|with)\s+([a-z0-9+#.\-]{1,40})\b", norm):
        language = _normalise_script_language(m.group(1))
        if language:
            return language

    if (
        re.search(r"\b(?:generate|write|create|build|make|define)\b", norm)
        and re.search(r"\b(?:script|code|program|class|function|module|object|constructor|inherit)\b", norm)
    ):
        return "python"

    return "auto"


def _looks_like_generation_complaint(norm: str) -> bool:
    if not norm:
        return False
    complaint_starts = (
        "you did not", "you didn't", "you just", "that script", "this script",
        "why did you", "why didn't you", "where is", "where did", "it did not",
        "it didn't", "your code", "your script",
    )
    complaint_phrases = (
        "did not generate", "didn't generate", "never ran", "not generated",
        "nothing to do with", "less in content", "no ide opened",
        "did not open", "didn't open", "dump it into chat", "not provide any path",
        "where is it",
    )
    return norm.startswith(complaint_starts) or any(p in norm for p in complaint_phrases)


def try_route(text: str) -> Optional[dict]:
    if _eli_phase10_blocks_media_intent(text):
        return None
    raw = str(text or "").strip()
    norm = normalise_voice_text(raw)
    if not norm:
        return None

    if re.fullmatch(r"(?:start\s+pomodoro|begin\s+pomodoro|pomodoro\s+start)(?:\s+timer)?", norm):
        return None

    # ── Shell command prepass ────────────────────────────────────────────────
    # Must fire BEFORE the OPEN_APP "run X" pattern so "run ls", "run ps",
    # "run git status" etc. route to SHELL_EXEC, not PulseAudio / some random app.
    _PORTABLE_SHELL_CMDS = frozenset({
        "ls", "cd", "pwd", "cat", "head", "tail", "grep", "find", "wc",
        "date", "df", "du", "free", "top", "ps", "kill", "chmod", "chown",
        "cp", "mv", "rm", "mkdir", "rmdir", "touch", "echo", "which", "whoami",
        "uname", "uptime", "hostname", "ip", "ifconfig", "ping", "curl", "wget",
        "tar", "zip", "unzip", "apt", "pip", "npm", "git", "docker", "systemctl",
        "python", "python3", "bash", "sh", "env", "export", "source", "less", "more",
        "htop", "nano", "vim", "vi", "ssh", "scp", "rsync", "nc", "netstat", "ss",
        "lsblk", "lsusb", "lspci", "dmesg", "journalctl", "lsof", "strace",
        "make", "cmake", "gcc", "g++", "cargo", "go", "java", "node", "ruby",
    })
    m_shell = re.fullmatch(r"(?:run|execute)\s+(\S+(?:\s+.+)?)", norm)
    if m_shell:
        parts = m_shell.group(1).strip().split()
        if parts and parts[0].lower() in _PORTABLE_SHELL_CMDS:
            # Extract the command from the ORIGINAL text, not the lowercased
            # norm — shell commands are case-sensitive (paths like
            # /home/<user>/Desktop, flags like -R vs -r). norm is only used to
            # detect that this IS a shell command; the cmd itself must keep
            # the user's original case.
            _raw_collapsed = re.sub(r"\s+", " ", raw).strip()
            m_shell_raw = re.match(r"(?i)(?:run|execute)\s+(\S+(?:\s+.+)?)", _raw_collapsed)
            _cmd = (m_shell_raw.group(1).strip() if m_shell_raw
                    else m_shell.group(1).strip())
            return {
                "action": "SHELL_EXEC",
                "args": {"cmd": _cmd},
                "confidence": 0.96,
                "meta": {"matched_by": "portable_intent_contract.shell_exec"},
            }

    m = re.fullmatch(r"(?:open|opens|launch|start|run)\s+(.+)", norm)
    if m:
        target = _clean_target(m.group(1))
        # Deictic targets ("open it / that / this / here / there") mean "open
        # what I'm looking at" — a gaze-cursor double-click, not an app launch.
        # Let them fall through to the gaze router instead of opening an app
        # literally named "it".
        if target.lower().strip() in {
            "it", "that", "this", "these", "those", "here", "there", "them",
        }:
            pass
        elif (
            target.lower().strip() in {
                "home", "home folder", "home directory", "home dir", "my home",
                "my files", "files", "file manager", "file explorer", "explorer",
                "the home folder", "the home directory", "trash", "downloads",
            }
            or re.search(r"\b(folder|directory)$", target.strip(), re.I)
        ):
            # File-manager / "<x> folder" requests are NOT app launches — let them
            # fall through to fs.open_home (OPEN_FILE_SYSTEM), so "open home folder"
            # opens the file browser instead of trying to install an app called
            # "home folder".
            pass
        elif _looks_like_url_target(target):
            # "open github com" / "open github.com" is a web address, not an app —
            # route to the browser instead of the not-installed install dialogue.
            return {
                "action": "OPEN_URL",
                "args": {"url": _build_url(target)},
                "confidence": 0.97,
                "meta": {"matched_by": "portable_intent_contract.open_url"},
            }
        elif _looks_like_app_target(target):
            return {
                "action": "OPEN_APP",
                "args": {"name": target, "target": target},
                "confidence": 0.995,
                "meta": {"matched_by": "portable_intent_contract.open_app"},
            }

    if re.fullmatch(r"(?:close|closed|exit|quit)\s+(?:current\s+|the\s+)?(?:browser\s+)?tab", norm):
        return {
            "action": "KEYBOARD",
            "args": {"key": "ctrl+w"},
            "confidence": 0.995,
            "meta": {"matched_by": "portable_intent_contract.close_current_tab"},
        }

    m = re.fullmatch(r"(?:close|closed|exit|quit)\s+(.+)", norm)
    if m:
        target = _clean_target(m.group(1))
        if _looks_like_app_target(target):
            return {
                "action": "CLOSE_APP",
                "args": {"name": target, "target": target},
                "confidence": 0.995,
                "meta": {"matched_by": "portable_intent_contract.close_app"},
            }

    m = re.fullmatch(r"(?:kill|force close|force quit)\s+(.+)", norm)
    if m:
        target = _clean_target(m.group(1))
        if _looks_like_app_target(target):
            return {
                "action": "CLOSE_APP",
                "args": {"name": target, "target": target, "force": True},
                "confidence": 0.995,
                "meta": {"matched_by": "portable_intent_contract.force_close_app"},
            }

    m = re.fullmatch(r"(?:minimize|minimise|hide)\s+(.+)", norm)
    if m:
        target = _clean_target(m.group(1))
        if _looks_like_app_target(target):
            return {
                "action": "MINIMIZE_APP",
                "args": {"name": target, "target": target},
                "confidence": 0.995,
                "meta": {"matched_by": "portable_intent_contract.minimize_app"},
            }

    m = re.fullmatch(r"(?:set\s+)?volume\s+(?:to\s+)?(\d{1,3})\s*%?", norm)
    if m:
        level = max(0, min(100, int(m.group(1))))
        return {
            "action": "VOLUME",
            "args": {"level": level, "percent": level, "mode": "absolute"},
            "confidence": 0.999,
            "meta": {"matched_by": "portable_intent_contract.volume_absolute"},
        }

    m = re.fullmatch(r"play\s+(.+?)\s+(?:on|using|with)\s+(.+)", norm)
    if m:
        query = _clean_target(m.group(1))
        try:
            raw_m = re.fullmatch(r"play\s+(.+?)[\s,]+(?:on|using|with)\s+(.+)", raw, re.I)
            if raw_m:
                query = _clean_target(raw_m.group(1))
        except Exception:
            pass
        target = _normalise_media_service(m.group(2))
        return {
            "action": "PLAY_MEDIA",
            "args": {"query": query, "target": target, "service": target},
            "confidence": 0.995,
            "meta": {"matched_by": "portable_intent_contract.play_query_on_target"},
        }

    m = re.fullmatch(r"(.+?)\s+by\s+(.+)", norm)
    if m and len(norm.split()) >= 4:
        # Guard against conversational sentences where "by" is a preposition,
        # not a "song by artist" separator.  The title (before "by") must not
        # contain common English function/pronoun/verb words that signal a
        # sentence rather than a media title.  Also block if the text starts
        # with a negation or conversational opener.
        _before_by = m.group(1).strip()
        _before_words = set(_before_by.lower().split())
        _sentence_signals = {
            "you", "will", "would", "could", "should", "can", "me", "my",
            "i", "we", "they", "he", "she", "it", "is", "are", "was",
            "were", "be", "been", "am", "no", "yes", "ok", "okay", "got",
            "get", "go", "did", "do", "does", "done", "please", "that",
            "this", "which", "what", "how", "run", "come", "take", "give",
            "your", "our", "their", "its", "first", "now", "then", "also",
            "just", "not", "never", "always", "but", "and", "or", "so",
        }
        # A genuine "song by artist" query is short and single-clause. Long
        # utterances, or anything spanning multiple sentences/clauses (interior
        # . ! ? punctuation), are conversation with a stray "by" preposition —
        # e.g. "Still being held up by my shoulders! haha. Nah, ...".
        _too_long = len(norm.split()) > 9
        _multi_sentence = bool(re.search(r"[.!?]", raw.strip().rstrip(".!? ")))
        if (_before_words & _sentence_signals) or _too_long or _multi_sentence:
            pass  # "by" is a preposition in a sentence — not a media query
        else:
            query = _clean_target(raw)
            query = re.sub(r"(?i)^\s*play\s+", "", query).strip()
            target = "spotify"
            return {
                "action": "PLAY_MEDIA",
                "args": {"query": query, "target": target, "service": target},
                "confidence": 0.96,
                "meta": {"matched_by": "portable_intent_contract.implied_song_by_artist"},
            }

    wants_generation = re.search(r"\b(?:generate|write|create|build|make)\b", norm)
    wants_code = re.search(r"\b(?:script|code|program|module|tool|app)\b", norm)
    # A question is conversation, not an imperative generation command — e.g.
    # "i did not ask you to write a code for that.. you feeling okay?" or
    # "when did we discuss ... you do have the ability to write your own code?".
    # Genuine "write a python script" commands are imperatives without a '?';
    # any real request that slips through still reaches the LLM intent resolver.
    _is_question = "?" in raw
    # Reject if a negation word precedes the generation verb anywhere in the
    # same clause — "not generate a python script", "i did NOT ask you to write
    # a code" (note the words between the negation and the verb).
    _negated_generation = bool(wants_generation and re.search(
        r"\b(?:not|don'?t|didn'?t|doesn'?t|won'?t|never|no|stop|without|"
        r"cannot|can'?t|rather\s+than|instead\s+of)\b[^.?!]*?\b"
        r"(?:generate|write|create|build|make)\b", norm))
    # Reject when the generation verb is subordinate to another verb (it is
    # being talked ABOUT, not commanded) — "the ability to write code",
    # "i asked you to write", "trying to make a tool".
    _subordinate_generation = bool(wants_generation and re.search(
        r"\b(?:ability|able|want|wanted|need|needed|ask|asked|tell|told|"
        r"trying|try|going|supposed|meant|ought|refuse|refused|capable)\b"
        r"[^.?!]*?\bto\s+(?:generate|write|create|build|make)\b", norm))
    # "make sure/sense/it/certain/use/note/do" are conversational idioms, not
    # code-generation commands. Only flag as generation if a real imperative
    # verb (generate/write/create/build) is present, or "make" is not in an idiom.
    _make_idiom_only = bool(
        wants_generation
        and not re.search(r"\b(?:generate|write|create|build)\b", norm)
        and re.search(r"\bmake\s+(?:sure|sense|it|this|that|certain|use|note|do|up|mention)\b", norm)
    )
    # "code" used as a noun referring to existing code (noticed/seen/the/your/their
    # code changes/base/review) is not a generation target.
    _code_is_reference = bool(
        wants_code
        and re.search(r"\b(?:script|code|program)\b", norm)
        and re.search(r"\b(?:noticed|seen|the|your|their|my|our|its|this|that|"
                      r"existing|current|latest)\s+(?:own\s+)?(?:code|script|program)\b", norm)
    )
    if (wants_generation and wants_code
            and not _is_question
            and not _looks_like_generation_complaint(norm)
            and not _negated_generation
            and not _subordinate_generation
            and not _make_idiom_only
            and not _code_is_reference):
        language = infer_script_language(raw)
        return {
            "action": "GENERATE_SCRIPT",
            "args": {
                "description": raw,
                "prompt": raw,
                "language": language,
                "destination": "labs_sim_ide",
                "open_in_labs": True,
                "open_in_ide": True,
            },
            "confidence": 0.995,
            "meta": {"matched_by": "portable_intent_contract.generate_script"},
        }

    return None


def wrap_router_callable(fn):
    if not callable(fn) or getattr(fn, "_portable_intent_contract_wrapped", False):
        return fn

    def wrapped(*args, **kwargs):
        text = ""
        for item in args:
            if isinstance(item, str) and item.strip():
                text = item
                break
        if not text:
            for key in ("text", "message", "command", "prompt", "query", "utterance"):
                value = kwargs.get(key)
                if isinstance(value, str) and value.strip():
                    text = value
                    break

        route = try_route(text)
        if route is not None:
            return route
        return fn(*args, **kwargs)

    wrapped.__name__ = getattr(fn, "__name__", "wrapped")
    wrapped.__doc__ = getattr(fn, "__doc__", None)
    wrapped._portable_intent_contract_wrapped = True
    return wrapped
