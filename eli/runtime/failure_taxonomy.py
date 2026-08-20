"""Classify a runtime failure by what actually went wrong, and where.

Every improvement proposal was logged as `category="stability", area="runtime"` —
a constant, whatever had failed. A CUDA out-of-memory, a missing voice file, a
refused socket and a bad dict key all arrived identically labelled. The
descriptions were real; the classification carried no information at all.

That is not cosmetic. `improvements` is what the self-upgrade path reports from
and what the daemon prioritises over, and with one category there is nothing to
prioritise BY. "What keeps breaking in audio?" and "show me only the network
failures" were unanswerable, and a resource exhaustion that needs a settings
change looked exactly like a logic bug that needs a patch.

Two axes, because they answer different questions:

  * CATEGORY — what kind of failure. Decides who fixes it and how: a `resource`
    failure wants a settings change, a `correctness` failure wants a patch, a
    `network` failure may want nothing at all because the operator is offline on
    purpose.
  * AREA — which subsystem. Derived from the traceback's own module path where
    there is one, because that is evidence rather than inference.

Classification is evidence-ordered: the exception TYPE is the strongest signal
and is checked first, then distinctive message text, and only then keywords. The
fallback is `stability`/`runtime` — the old constant — but it is now the answer
when nothing matched, not the answer to everything.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

# ── categories ────────────────────────────────────────────────────────────────
RESOURCE = "resource"            # out of memory, VRAM, disk, file handles
TIMEOUT = "timeout"              # exceeded a deadline
NETWORK = "network"              # connection refused, DNS, offline by policy
PERMISSION = "permission"        # denied by the OS or by ELI's own gating
DEPENDENCY = "dependency"        # a module or binary is not installed
MISSING = "missing_resource"     # a file, model or device that should exist
DATA = "data"                    # malformed or unexpected input shape
CORRECTNESS = "correctness"      # ran fine, produced the wrong answer
INTERFACE = "interface"          # called with the wrong shape — a real code bug
CONCURRENCY = "concurrency"      # deadlock, race, locked database
STABILITY = "stability"          # genuinely unclassified

# Exception type -> category. The strongest signal available, so it wins.
_BY_EXCEPTION: Dict[str, str] = {
    "MemoryError": RESOURCE,
    "OutOfMemoryError": RESOURCE,
    "TimeoutError": TIMEOUT,
    "TimeoutExpired": TIMEOUT,
    "socket.timeout": TIMEOUT,
    "ConnectionError": NETWORK,
    "ConnectionRefusedError": NETWORK,
    "ConnectionResetError": NETWORK,
    "URLError": NETWORK,
    "HTTPError": NETWORK,
    "SSLError": NETWORK,
    "gaierror": NETWORK,
    "OfflineError": NETWORK,
    "PermissionError": PERMISSION,
    "AccessDenied": PERMISSION,
    "ImportError": DEPENDENCY,
    "ModuleNotFoundError": DEPENDENCY,
    "FileNotFoundError": MISSING,
    "NotADirectoryError": MISSING,
    "IsADirectoryError": MISSING,
    "KeyError": DATA,
    "IndexError": DATA,
    "ValueError": DATA,
    "JSONDecodeError": DATA,
    "UnicodeDecodeError": DATA,
    "AssertionError": CORRECTNESS,
    "TypeError": INTERFACE,
    "AttributeError": INTERFACE,
    "NameError": INTERFACE,
    "SyntaxError": INTERFACE,
    "IndentationError": INTERFACE,
    "RecursionError": CONCURRENCY,
    "DeadlockError": CONCURRENCY,
}

# Distinctive message text, for the many failures that surface as a bare
# RuntimeError or OSError and would otherwise fall through to the default.
_BY_MESSAGE: Tuple[Tuple[str, str], ...] = (
    (r"\bcuda\b.*\bout of memory\b|\bout of memory\b|\boom\b|\bvram\b|"
     r"\bcannot allocate\b|\bno space left\b|\bdisk full\b", RESOURCE),
    (r"\btimed? ?out\b|\bdeadline exceeded\b|\btook too long\b", TIMEOUT),
    (r"\bconnection refused\b|\bname or service not known\b|\bunreachable\b|"
     r"\boffline\b|\bnetguard\b|\bblocked by policy\b|\bdns\b", NETWORK),
    (r"\bpermission denied\b|\baccess is denied\b|\bnot permitted\b|"
     r"\brefused: .*permission\b|\bread-only file system\b", PERMISSION),
    (r"\bno module named\b|\bnot installed\b|\bcommand not found\b|"
     r"\bno such binary\b|\bmissing dependency\b", DEPENDENCY),
    (r"\bno such file\b|\bdoes not exist\b|\bnot found on disk\b|"
     r"\bmodel file missing\b|\bno player could handle\b", MISSING),
    (r"\bdatabase is locked\b|\bdeadlock\b|\brace condition\b|"
     r"\balready in use\b|\bresource temporarily unavailable\b", CONCURRENCY),
    (r"\bexpected .* got\b|\bwrong (?:answer|result|output)\b|"
     r"\bdid not match\b|\bassertion\b", CORRECTNESS),
    (r"\bmalformed\b|\binvalid json\b|\bcould not parse\b|\bunexpected token\b",
     DATA),
)

# Subsystem -> area. Matched against the traceback's module path first (evidence),
# then against the failing action name (inference).
_AREA_BY_MODULE: Tuple[Tuple[str, str], ...] = (
    (r"eli/perception|audio_stt|/tts|piper|whisper", "audio"),
    (r"eli/vision|vision_|qwen.?vl|ocr|screenshot", "vision"),
    (r"eli/memory|vector_store|knowledge_graph", "memory"),
    (r"eli/cognition|inference_broker|gguf", "inference"),
    (r"eli/gui|qt_|pyside", "gui"),
    (r"eli/plugins|marketplace|mcp", "plugins"),
    (r"eli/execution|executor|router", "execution"),
    (r"eli/planning|proactive|scheduled", "scheduling"),
    (r"eli/tools/(?:web|news)|netguard", "network"),
    (r"eli/coding", "coding"),
    (r"eli/world|avatar", "world"),
    (r"eli/learning|training|lora", "training"),
)

_AREA_BY_ACTION: Tuple[Tuple[str, str], ...] = (
    (r"^(?:PLAY|PAUSE|STOP|NEXT|PREV|VOLUME|MEDIA)", "media"),
    (r"^(?:SPEAK|VOICE|TTS|LISTEN|STT)", "audio"),
    (r"^(?:SCREENSHOT|GAZE|VISION|OCR|LOOK)", "vision"),
    (r"^(?:MEMORY|RECALL|REMEMBER|FORGET)", "memory"),
    (r"^(?:WEB|NEWS|SEARCH|FETCH)", "network"),
    (r"^(?:OPEN|LAUNCH|CLOSE|MINIMISE|MINIMIZE|FOCUS)", "desktop"),
    (r"^(?:WRITE|READ|FILE|SAVE|DELETE)", "filesystem"),
    (r"^(?:PLUGIN|MCP|MARKETPLACE)", "plugins"),
    (r"^(?:SCHEDULE|TASK|REMIND)", "scheduling"),
    (r"^(?:CODE|EXAMINE|DEBUG|GENERATE_CODE)", "coding"),
    (r"^(?:SELF|GUI_RUNTIME_AUDIT|PERSONA)", "introspection"),
)

_EXC_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception|Expired|Timeout))\b")
_MODULE_RE = re.compile(r'File "([^"]+)"|(\beli[/\\][a-z_/\\]+\.py)')

# A resource or network failure is usually the environment, not a defect in ELI.
# Proposing a code patch for "the user is offline on purpose" wastes a cycle and
# fills the improvements table with noise, so severity drives what happens next.
_SEVERITY: Dict[str, str] = {
    INTERFACE: "bug",
    CORRECTNESS: "bug",
    DATA: "bug",
    CONCURRENCY: "bug",
    DEPENDENCY: "environment",
    MISSING: "environment",
    PERMISSION: "environment",
    RESOURCE: "capacity",
    TIMEOUT: "capacity",
    NETWORK: "external",
    STABILITY: "unknown",
}


def exception_name(error: str) -> str:
    """The exception type named in an error string, if there is one."""
    m = _EXC_RE.search(str(error or ""))
    return m.group(1) if m else ""


def classify_category(error: str, command: str = "") -> str:
    """What kind of failure this is. Evidence-ordered: type, then text."""
    err = str(error or "")
    exc = exception_name(err)
    if exc:
        # Match the bare name too, so `json.JSONDecodeError` resolves.
        for key in (exc, exc.rsplit(".", 1)[-1]):
            if key in _BY_EXCEPTION:
                return _BY_EXCEPTION[key]
    low = err.lower()
    for pattern, cat in _BY_MESSAGE:
        if re.search(pattern, low):
            return cat
    return STABILITY


def classify_area(error: str, command: str = "") -> str:
    """Which subsystem. The traceback's own path is evidence; the action is not."""
    err = str(error or "")
    for m in _MODULE_RE.finditer(err):
        path = (m.group(1) or m.group(2) or "").replace("\\", "/")
        for pattern, area in _AREA_BY_MODULE:
            if re.search(pattern, path, re.I):
                return area
    cmd = str(command or "").strip().upper()
    if cmd:
        for pattern, area in _AREA_BY_ACTION:
            if re.search(pattern, cmd):
                return area
    for pattern, area in _AREA_BY_MODULE:
        if re.search(pattern, err, re.I):
            return area
    return "runtime"


def classify(error: str, command: str = "", user_input: str = "") -> Dict[str, str]:
    """Full classification for one failure.

    `severity` says what kind of response is even appropriate — a network failure
    on a deliberately offline machine is not a defect, and proposing a patch for
    it only fills the improvements table with noise.
    """
    category = classify_category(error, command)
    return {
        "category": category,
        "area": classify_area(error, command),
        "severity": _SEVERITY.get(category, "unknown"),
        "exception": exception_name(error),
    }


def is_actionable(category: str) -> bool:
    """True when a code change is a plausible response to this failure."""
    return _SEVERITY.get(category, "unknown") in ("bug", "unknown")


__all__ = [
    "classify", "classify_category", "classify_area", "exception_name",
    "is_actionable", "RESOURCE", "TIMEOUT", "NETWORK", "PERMISSION",
    "DEPENDENCY", "MISSING", "DATA", "CORRECTNESS", "INTERFACE",
    "CONCURRENCY", "STABILITY",
]
