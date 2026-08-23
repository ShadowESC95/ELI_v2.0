"""
ELI API Server – Enterprise edition.
Provides REST endpoints for chat and command execution.
"""

# --- Make the repo root importable regardless of how we were launched ---
# `python api/server.py` (path form) puts the api/ dir on sys.path[0], NOT the repo
# root, so `import eli` / `import api.*` fail. Prepend the repo root so the script form
# works the same as `python -m api.server` and the in-process GUI launch.
import os as _os, sys as _sys
_REPO_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _REPO_ROOT not in _sys.path:
    _sys.path.insert(0, _REPO_ROOT)

# --- Self-heal: run under the project's venv even if invoked with system python ---
# `python api/server.py` (system interpreter) lacks fastapi/uvicorn; the deps live in
# the project's .venv. Rather than fail with ModuleNotFoundError, transparently re-exec
# this same command under .venv/bin/python (Scripts/python.exe on Windows) when it
# exists and we're not already running it. Cross-platform; one-shot (guarded against a
# re-exec loop); falls through to the normal import if no venv is found.
def _reexec_under_venv() -> None:
    import os, sys
    try:
        import fastapi  # noqa: F401 — already in the right interpreter, nothing to do
        return
    except Exception:
        pass
    if os.environ.get("_ELI_VENV_REEXEC") == "1":
        return  # already tried once — avoid an exec loop; let the real ImportError surface
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # NB: compare plain abspaths, NOT realpath — a venv's python is usually a *symlink*
    # to the base interpreter, so realpath() would make them equal and skip the re-exec.
    _here = os.path.normcase(os.path.abspath(sys.executable))
    for _cand in (os.path.join(_root, ".venv", "bin", "python"),
                  os.path.join(_root, ".venv", "Scripts", "python.exe")):
        if os.path.isfile(_cand) and os.path.normcase(os.path.abspath(_cand)) != _here:
            os.environ["_ELI_VENV_REEXEC"] = "1"
            try:
                os.execv(_cand, [_cand, os.path.abspath(__file__), *sys.argv[1:]])
            except Exception:
                break  # exec failed — fall through to the normal import / error
    # No venv found (or exec failed): let the import below raise the real, clear error.


# Only self-heal when launched as the entry point (`python api/server.py` or
# `python -m api.server`). When imported in-process (e.g. the GUI launcher does
# `from api.server import app`), never re-exec — that would replace the host process;
# the caller is responsible for its own interpreter.
if __name__ == "__main__":
    _reexec_under_venv()

from fastapi import FastAPI, HTTPException, Depends, Header, Request
from fastapi.responses import HTMLResponse, StreamingResponse, Response
from pydantic import BaseModel
from typing import Optional, Any, List
import json
import os
import secrets
import threading
import time
from pathlib import Path
import uvicorn

from eli.kernel.engine import get_engine
from eli.memory.memory import get_memory

# Bearer-token gate. Enforced ONLY when ELI_API_TOKEN is set — which the launcher does
# automatically when binding beyond loopback (--lan). Loopback (default) runs tokenless
# for zero-friction same-machine use. Local-first: nothing here reaches the network; the
# token only controls who on YOUR LAN may talk to the server.
def _api_token() -> str:
    """Active bearer token, read LIVE from the environment so a token set at startup
    (e.g. the non-loopback safety guard in main()) is always enforced — not merely
    whatever happened to be present at import time."""
    return os.environ.get("ELI_API_TOKEN", "").strip()


def _is_loopback_host(host: str) -> bool:
    """True only for genuinely local binds (127.0.0.0/8, ::1, localhost). Anything
    else — 0.0.0.0, a LAN IP, an unresolved hostname — is treated as network-exposed."""
    h = (host or "").strip().lower()
    if h in ("localhost", ""):
        return True
    try:
        import ipaddress
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def _tokenless_allowed() -> bool:
    """Tokenless serving is permitted ONLY when explicitly opted in. The loopback
    launcher / loopback `main()` set this; nothing else does — so any ASGI-direct
    launch (uvicorn api.server:app, gunicorn, a Docker CMD, a systemd ExecStart)
    that never runs main() leaves it UNSET and the gate fails closed."""
    return os.environ.get("ELI_API_ALLOW_TOKENLESS", "").strip().lower() in ("1", "true", "yes", "on")


def _loopback_grants_admin() -> bool:
    """When false (ELI_LOOPBACK_ADMIN=0), localhost connections must present a token
    like any remote client — for shared machines or reverse-proxy hardening."""
    return os.environ.get("ELI_LOOPBACK_ADMIN", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


from typing import NamedTuple


class Principal(NamedTuple):
    """The authenticated caller: a user id and a role (admin | member)."""
    user_id: str
    role: str


def _bearer(authorization: str) -> str:
    a = (authorization or "").strip()
    return a[7:].strip() if a.lower().startswith("bearer ") else ""


def _is_loopback_client(request) -> bool:
    """True when the request comes from THIS machine (the socket peer is loopback). Used to
    keep same-machine browsing zero-friction even when the server is bound to 0.0.0.0 for
    the LAN. The peer address is the real kernel socket source — it can't be spoofed to
    127.x from another device (martian-source packets are dropped), so this is safe."""
    try:
        host = (request.client.host if (request and request.client) else "") or ""
    except Exception:
        return False
    return host == "::1" or host == "localhost" or host.startswith("127.")


def _resolve_principal(authorization: str, loopback: bool = False) -> Optional[Principal]:
    """Resolve a request to an authenticated Principal, or None (→ 401).

    RBAC mode (one or more users defined): the bearer token maps to a (user_id, role).
    Single-operator mode (no users): the legacy ELI_API_TOKEN — or a loopback connection /
    tokenless bind — authenticates the local 'operator' as admin (back-compatible).
    `loopback` lets a same-machine caller serve tokenless even in --lan mode; LAN callers
    (non-loopback) always still need the token."""
    token = _bearer(authorization)
    loopback_admin = loopback and _loopback_grants_admin()
    tokenless = _tokenless_allowed() or loopback_admin
    try:
        from eli.runtime import api_users
        if api_users.rbac_enabled():
            rec = api_users.resolve_token(token)
            if rec:
                return Principal(rec["user_id"], rec["role"])
            # No matching token. The LOOPBACK operator (machine owner) stays admin so they
            # can manage users / never lock themselves out. A LAN client (non-loopback, no
            # tokenless) with no/invalid token still fails closed.
            if not token and tokenless:
                return Principal("operator", "admin")
            return None
    except Exception:
        pass  # store unreadable → fall through to single-operator mode (fail-closed below)
    configured = _api_token()
    if configured:
        if token and secrets.compare_digest(token, configured):
            return Principal("operator", "admin")
        if not token and loopback_admin:   # same machine, no token typed → owner
            return Principal("operator", "admin")
        return None
    if tokenless:
        return Principal("operator", "admin")
    return None


# Privilege hierarchy: viewer (read-only) < member (acts) < admin (console + user mgmt).
_ROLE_RANK = {"viewer": 0, "member": 1, "admin": 2}


def _rank(role: str) -> int:
    return _ROLE_RANK.get((role or "").strip().lower(), 0)  # unknown role → least privilege


def _authenticated(authorization: str, loopback: bool = False) -> Principal:
    """Fail-CLOSED: resolve to a Principal or 401. The default — no token, no opt-out —
    is DENY, so a raw `uvicorn api.server:app` stays locked down regardless of main().
    A same-machine (loopback) caller is the owner and serves tokenless even in --lan mode."""
    p = _resolve_principal(authorization, loopback)
    if p is None:
        raise HTTPException(
            status_code=401,
            detail="API token required (set ELI_API_TOKEN or define a user; for "
                   "same-machine use launch via scripts/eli_serve.sh)",
        )
    return p


def require_viewer(request: Request, authorization: str = Header(default="")) -> Principal:
    """Read-only level — any authenticated caller (viewer, member, or admin)."""
    return _authenticated(authorization, _is_loopback_client(request))


def require_member(request: Request, authorization: str = Header(default="")) -> Principal:
    """Acting level — member or admin. A read-only viewer is 403'd from mutating actions."""
    p = _authenticated(authorization, _is_loopback_client(request))
    if _rank(p.role) < _ROLE_RANK["member"]:
        raise HTTPException(status_code=403, detail="member role required (read-only viewer)")
    return p


def require_admin(request: Request, authorization: str = Header(default="")) -> Principal:
    """Admin level — the Admin console + user management."""
    p = _authenticated(authorization, _is_loopback_client(request))
    if _rank(p.role) < _ROLE_RANK["admin"]:
        raise HTTPException(status_code=403, detail="admin role required")
    return p


def _require_token(request: Request, authorization: str = Header(default="")):
    """Read-level dependency (kept as the name read-only endpoints already reference) —
    permits any authenticated caller, including a viewer."""
    _authenticated(authorization, _is_loopback_client(request))


def _effective_user(principal: Optional[Principal], supplied: str) -> str:
    """The user id to attribute an action to. In RBAC mode the *authenticated* identity
    is authoritative (a member can't spoof another user); otherwise the client-supplied
    value is used (single-operator mode has no per-user tokens)."""
    try:
        from eli.runtime import api_users
        if api_users.rbac_enabled() and principal is not None:
            return principal.user_id
    except Exception:
        pass
    return (supplied or "anon")

app = FastAPI(
    title="ELI Cognitive OS Agent API",
    description="Enterprise API for ELI – locally deployed, private, powerful.",
    version="1.0.0"
)

# Serve the UI's stylesheet and script from api/static/. Deliberately mounted
# without auth: index.html itself is already public (the page gates its own
# actions on a token), and holding the CSS behind a dependency would leave an
# unauthenticated visitor staring at unstyled HTML instead of a login prompt.
# Missing directory is survivable — the loader below degrades to a plain message
# rather than the whole server failing to import.
try:
    from fastapi.staticfiles import StaticFiles as _StaticFiles
    from pathlib import Path as _P

    _sd = _P(__file__).resolve().parent / "static"
    if _sd.is_dir():
        app.mount("/static", _StaticFiles(directory=str(_sd)), name="static")
except Exception:  # pragma: no cover - static assets are optional at import time
    pass

@app.on_event("startup")
def _eli_startup_hooks():
    """Server boot hooks. Install the offline socket guard FIRST so early startup
    egress (e.g. MQTT auto-connect, any raw urlopen) is gated even before the first
    chat request lazily constructs the CognitiveEngine."""
    try:
        from eli.core.netguard import install_socket_guard
        install_socket_guard()
    except Exception:
        pass
    try:
        from eli.runtime.device_server import get_server
        get_server().maybe_auto_connect()
    except Exception:
        pass
    try:
        from eli.runtime import home_mesh
        cfg = home_mesh.load_config()
        if cfg.get("enabled"):
            home_mesh.ensure_watchdog()
    except Exception:
        pass
    # Preload whisper when cached so web mic (/v1/voice/stt) works offline. Do it in a
    # BACKGROUND thread — loading the model on CPU takes ~20s and would otherwise block
    # uvicorn's startup event, delaying the HTTP/HTTPS port bind (and the Connect page).
    try:
        from eli.perception.local_whisper_stt import whisper_cache_ready, preload_model
        if whisper_cache_ready():
            import threading
            threading.Thread(target=preload_model, daemon=True,
                             name="eli-whisper-preload").start()
    except Exception:
        pass
    # Preload the GGUF chat model at boot (BACKGROUND thread, like whisper above) so the
    # FIRST chat request isn't stuck loading it. Otherwise a large model makes the first
    # reply appear to "hang" for minutes (or fail on VRAM), which reads as a dead server.
    # Failures surface in the log at startup instead of as a silent spinner. Run the server
    # standalone so the model loads once — not alongside the desktop GUI (double-load OOM).
    try:
        import threading as _th, logging as _lg
        def _preload_chat_model():
            _log = _lg.getLogger("eli.api.server")
            try:
                from eli.cognition import gguf_inference as _gi
                if not _gi.is_loaded():
                    _gi.load_model()
                    _log.info("[SERVER] chat model preloaded — first request will be fast")
            except Exception as _e:
                _log.warning("[SERVER] chat model preload failed (first chat will retry): %s", _e)
        _th.Thread(target=_preload_chat_model, daemon=True, name="eli-gguf-preload").start()
    except Exception:
        pass

# Has any device OTHER than this machine actually reached the server? In LAN mode the
# desktop connects via loopback, so if this stays False after the server's been up a
# while, real LAN traffic isn't getting through — almost always the OS firewall. The
# Connect tab uses this to detect-and-warn (with the exact 'allow' command).
_LAN_SEEN = {"any": False, "count": 0, "last": None}

@app.middleware("http")
async def _track_lan_reachability(request, call_next):
    try:
        if not _is_loopback_client(request):
            _LAN_SEEN["any"] = True
            _LAN_SEEN["count"] += 1
            _LAN_SEEN["last"] = request.client.host if request.client else None
    except Exception:
        pass
    return await call_next(request)

# Minimal, dependency-free, mobile-first chat UI. Served at "/". Lets any device
# with a browser (Android/iOS/desktop) talk to a self-hosted ELI over the network —
# inference stays on the host running this server (no on-device model build needed).
# ── Web UI ───────────────────────────────────────────────────────────────────
# The UI used to live here as a single 233KB triple-quoted string: unlintable,
# undiffable in any useful way, and impossible for an editor or a designer to
# work on. It now lives in api/static/ as real .html/.css/.js files and is read
# from disk, so the page can be edited (and linted, and reviewed line by line)
# without touching Python.
#
# Cached on mtime rather than read per request: the page is ~233KB across three
# files, so re-reading on every hit is pure waste, but picking up a changed file
# automatically is what makes editing the UI bearable.
_STATIC_DIR = Path(__file__).resolve().parent / "static"
_UI_CACHE: dict = {"mtime": None, "html": ""}


def _web_ui() -> str:
    """The index page, re-read whenever it changes on disk."""
    index = _STATIC_DIR / "index.html"
    try:
        mtime = index.stat().st_mtime
    except OSError:
        return _UI_CACHE["html"] or (
            "<!doctype html><title>ELI</title>"
            "<p>UI assets are missing from this install (api/static/index.html)."
        )
    if _UI_CACHE["mtime"] != mtime:
        _UI_CACHE["html"] = index.read_text(encoding="utf-8")
        _UI_CACHE["mtime"] = mtime
    return _UI_CACHE["html"]


# ----------------------------------------------------------------------
# Request/Response Models
# ----------------------------------------------------------------------
class ChatRequest(BaseModel):
    message: str
    user_id: str = "default"
    session_id: Optional[str] = None
    stream: bool = False

class ChatResponse(BaseModel):
    response: str
    session_id: str
    user_id: str
    timestamp: float

class ExecuteRequest(BaseModel):
    action: str
    args: dict = {}
    user_id: str = "default"

class ExecuteResponse(BaseModel):
    ok: bool
    result: dict
    user_id: str
    timestamp: float

class StatusResponse(BaseModel):
    status: str
    version: str
    model: str
    uptime: float
    user_id: str

class DeviceConfig(BaseModel):
    # ELI's own MQTT broker connection — NOT Home Assistant.
    host: str = ""
    port: int = 1883
    username: str = ""
    password: str = ""
    discovery_prefix: str = ""   # optional MQTT discovery; blank = manual devices only
    tls: bool = False

class DeviceRegister(BaseModel):
    device_id: str
    name: str = ""
    type: str = "switch"          # light|switch|fan|sensor|climate|media|cover|outlet
    command_topic: str = ""
    state_topic: str = ""
    room: str = ""

class DeviceControl(BaseModel):
    device_id: str
    command: str                  # on | off | brightness | set
    value: Optional[Any] = None

class DeviceRoom(BaseModel):
    device_id: str
    room: str = ""

class RoomControl(BaseModel):
    room: str
    command: str                  # on | off

class DriverInstall(BaseModel):
    name: str                     # cast | firetv | airplay | upnp

class AddDiscovered(BaseModel):
    # A discovery result from /v1/devices/discover (kind/host/port/control/name/...).
    device: dict = {}

class BluetoothAction(BaseModel):
    address: str = ""             # BT MAC (from a scan); or leave blank and give a name
    name: str = ""
    command: str = "connect"      # connect | disconnect | pair | trust | use_for_audio

class WifiConnect(BaseModel):
    ssid: str
    password: str = ""

class AudioRoute(BaseModel):
    sink: str                     # pactl sink id, alias, or "device 1"

class AudioAlias(BaseModel):
    sink: str
    name: str = ""                # friendly label; empty clears

class DeviceNameSave(BaseModel):
    key: str = ""                 # stable key: dev:{id}, sink:{MAC}, bt:{MAC}
    name: str = ""                # user label for voice; empty clears
    sink: str = ""                # legacy: resolve sink → stable key when key omitted

class DevicePair(BaseModel):
    device_id: str
    code: Optional[str] = None    # PIN for AirPlay; omit to begin pairing

class MeshPeer(BaseModel):
    id: str = ""
    name: str = ""
    url: str = ""
    role: str = "secondary"       # primary | secondary | tertiary

class MeshConfig(BaseModel):
    enabled: bool = False
    role: str = "off"             # primary | secondary | tertiary | reflex | off
    node_name: str = ""
    primary_url: str = ""
    peers: List[MeshPeer] = []
    heartbeat_interval_sec: float = 5.0
    failover_after_sec: float = 18.0
    auto_takeover: bool = True

class MediaControl(BaseModel):
    command: str                          # play|pause|play-pause|stop|next|previous|volume
    player: Optional[str] = None          # target a specific player; None = active player
    value: Optional[float] = None         # for volume (0–100)

class UIPrefs(BaseModel):
    prefs: dict = {}                      # arbitrary per-user dashboard layout JSON

class TaskCreate(BaseModel):
    request: str                          # what ELI should do
    when: str = "overnight"               # "overnight" | "tonight" | "in 1 hour" | "2am" …
    kind: Optional[str] = None            # code|research|eval|reflection|… (None = inferred)

class TaskRef(BaseModel):
    pid: str

class AutomationCreate(BaseModel):
    device: str
    command: str = "on"
    time: str                     # HH:MM
    value: Optional[Any] = None
    days: Any = "daily"           # "daily" or a list of weekday ints (0=Mon)
    name: str = ""

class AutomationRef(BaseModel):
    id: str
    enabled: Optional[bool] = None

class SuggestionAccept(BaseModel):
    device: str
    command: str = "on"
    hour: int
    name: str = ""

class SceneAction(BaseModel):
    device: str
    command: str = "on"
    value: Optional[Any] = None

class SceneCreate(BaseModel):
    name: str
    actions: list[SceneAction] = []

class SceneRef(BaseModel):
    id: str

class SceneActivate(BaseModel):
    scene: str                    # id or name

class AutomationCreateV2(BaseModel):
    name: str = ""
    trigger: dict                 # {type:time|sun|device_state, ...}
    action: Any                   # an action dict, or a list of them (multi-action)
    condition: list = []          # [{device, state}] — all must hold for it to run

class HomeLocation(BaseModel):
    lat: float
    lon: float

class CompletionMessage(BaseModel):
    role: str = "user"
    content: str = ""

class CompletionRequest(BaseModel):
    # The de-facto industry chat shape. Extra fields (temperature, top_p, …) are
    # accepted and ignored so any standard client connects without erroring.
    model: Optional[str] = "eli-local"
    messages: list[CompletionMessage] = []
    stream: bool = False

class ResearchIngest(BaseModel):
    corpus: str
    path: str
    user: str = "anon"

class NetToggle(BaseModel):
    # The monitored internet switch. Off by default; admin-only to flip. Every
    # change is recorded in the tamper-evident audit ledger.
    enabled: bool
    reason: str = ""

class SettingsUpdate(BaseModel):
    settings: dict = {}


class ModelSwitch(BaseModel):
    path: str = ""

# Curated, safe-to-expose ELI settings — real keys from runtime_settings.DEFAULTS, grouped
# for the dashboard. Excludes anything that could strand a running model (model_path,
# n_gpu_layers, tensor_split…). (type, group, label, hint, [min, max, step] for numbers).
_SETTINGS_SCHEMA = {
    "user_name":              ("str",  "General",    "Your name", "What ELI calls you"),
    "auto_save":              ("bool", "General",    "Auto-save conversations", ""),
    "log_to_file":            ("bool", "General",    "Write logs to file", ""),
    "temperature":            ("float","Generation", "Temperature", "Higher = more creative", 0.0, 2.0, 0.05),
    "top_p":                  ("float","Generation", "Top-p", "Nucleus sampling", 0.0, 1.0, 0.01),
    "top_k":                  ("int",  "Generation", "Top-k", "0 = disabled", 0, 200, 1),
    "max_tokens":             ("int",  "Generation", "Max response tokens", "", 256, 32768, 256),
    "repeat_penalty":         ("float","Generation", "Repeat penalty", "", 1.0, 1.5, 0.01),
    "model_thinking":         ("bool", "Generation", "Deep thinking (reasoning models)", "Higher quality, slower"),
    "auto_speak":             ("bool", "Voice",      "Speak replies aloud", ""),
    "tts_voice":              ("str",  "Voice",      "Voice", "Local Piper voice"),
    "mic_enabled":            ("bool", "Voice",      "Microphone / wake word", ""),
    "vision_enabled":         ("bool", "Vision",     "Local vision", "Describe images & screen"),
    "ambient_vision_enabled": ("bool", "Vision",     "Ambient screen glances", "Periodic awareness"),
    "ambient_vision_interval":("int",  "Vision",     "Glance interval (s)", "", 30, 1800, 30),
    "searxng_url":            ("str",  "Network",    "SearXNG URL", "Optional self-hosted search"),
    "theme":                  ("str",  "Appearance", "Theme", "dark or light"),
    "user_text_color":        ("str",  "Appearance", "Your message colour", ""),
}

class ResearchQuery(BaseModel):
    corpus: str
    question: str
    k: int = 6
    user: str = "anon"

class ResearchNote(BaseModel):
    corpus: str
    title: str
    text: str
    user: str = "anon"

class ResearchDoc(BaseModel):
    corpus: str
    source: str
    user: str = "anon"

class TTSRequest(BaseModel):
    text: str
    voice: Optional[str] = None

class UserCreate(BaseModel):
    user_id: str
    role: str = "member"   # admin | member

class UserRef(BaseModel):
    user_id: str

# ----------------------------------------------------------------------
# API Endpoints
# ----------------------------------------------------------------------
def _extract_response_text(result) -> str:
    """Normalise whatever engine.process() returned into user-visible text.

    process() usually returns a dict, but several paths return a bare string
    (e.g. the multi-question splitter joins sub-answers) or a streaming
    generator. Assuming a dict and calling .get() on a str raised
    "'str' object has no attribute 'get'" → HTTP 500. Field order mirrors the
    engine's own extraction: response → content → text."""
    if isinstance(result, str):
        return result.strip()
    if isinstance(result, dict):
        return str(
            result.get("response") or result.get("content") or result.get("text") or ""
        ).strip()
    try:  # streaming generator / iterable of chunks
        parts = []
        for chunk in result:
            if isinstance(chunk, dict):
                parts.append(
                    chunk.get("response") or chunk.get("content") or chunk.get("token") or ""
                )
            elif isinstance(chunk, str):
                parts.append(chunk)
        return "".join(parts).strip()
    except Exception:
        return str(result or "").strip()


@app.get("/", response_class=HTMLResponse, tags=["Root"])
async def root():
    """The web chat UI — open this host in any browser (incl. Android/iOS)."""
    return HTMLResponse(_web_ui())

# ── PWA: make the web app installable (home-screen icon) + an offline shell ──
_PWA_ICON = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">'
    '<rect width="512" height="512" rx="96" fill="#05070d"/>'
    '<text x="50%" y="56%" font-family="monospace" font-size="240" font-weight="800" '
    'text-anchor="middle" fill="#22d3ee">E</text>'
    '<rect x="96" y="372" width="320" height="14" rx="7" fill="#f637ec"/></svg>'
)
import io as _io
from functools import lru_cache as _lru

@_lru(maxsize=24)
def _eli_icon_png(size: int, maskable: bool) -> bytes:
    """Render ELI's launcher icon onto a square <size> canvas.
    Transparent + minimal padding for the favicon/sidebar; dark-filled with safe-zone
    padding for installable/maskable app icons (Android squircle-crops maskable icons).
    The source is non-square, so we letterbox-fit it centred. Cached per (size, maskable)."""
    from PIL import Image
    src_path = None
    for rel in ("packaging/desktop/Eli_Icon.png", "blueprints/Eli_Icon.png"):
        cand = _os.path.join(_REPO_ROOT, rel)
        if _os.path.isfile(cand):
            src_path = cand
            break
    if not src_path:
        raise FileNotFoundError("Eli_Icon.png not found under packaging/desktop or blueprints/")
    src = Image.open(src_path).convert("RGBA")
    bg = (6, 20, 31, 255) if maskable else (0, 0, 0, 0)
    pad = 0.72 if maskable else 0.92
    canvas = Image.new("RGBA", (size, size), bg)
    box = int(size * pad)
    sw, sh = src.size
    scale = min(box / sw, box / sh)
    nw, nh = max(1, int(sw * scale)), max(1, int(sh * scale))
    src = src.resize((nw, nh), Image.LANCZOS)
    canvas.alpha_composite(src, ((size - nw) // 2, (size - nh) // 2))
    buf = _io.BytesIO()
    canvas.save(buf, "PNG")
    return buf.getvalue()

def _icon_resp(size: int, maskable: bool):
    """Serve the rendered PNG, falling back to the bundled SVG glyph if PIL/the file fails."""
    try:
        return Response(content=_eli_icon_png(size, maskable), media_type="image/png",
                        headers={"Cache-Control": "max-age=604800"})
    except Exception:
        return Response(content=_PWA_ICON, media_type="image/svg+xml")

_PWA_MANIFEST = {
    "name": "ELI", "short_name": "ELI", "start_url": "/", "scope": "/",
    "display": "standalone", "background_color": "#05070d", "theme_color": "#05070d",
    "icons": [
        {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
        {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "maskable"},
        {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
    ],
}
_SERVICE_WORKER = """
const C='eli-shell-v12';
self.addEventListener('install',e=>self.skipWaiting());
self.addEventListener('message',e=>{if(e.data==='skip')self.skipWaiting();});
self.addEventListener('activate',e=>e.waitUntil((async()=>{
  // Drop any older cache so a stale app shell can never linger.
  const keys=await caches.keys();
  await Promise.all(keys.filter(k=>k!==C).map(k=>caches.delete(k)));
  await self.clients.claim();
})()));
self.addEventListener('fetch',e=>{
  if(e.request.method!=='GET')return;
  const u=new URL(e.request.url);
  if(u.pathname.startsWith('/v1/')||u.pathname.startsWith('/docs'))return; // never cache live API
  // NETWORK-FIRST for the app shell (the HTML page + the SW) so UI updates always appear;
  // fall back to cache only when genuinely offline. Static assets stay cache-first.
  const isShell=e.request.mode==='navigate'||u.pathname==='/'||u.pathname==='/sw.js';
  if(isShell){
    e.respondWith(fetch(e.request).then(r=>{
      if(r&&r.status===200){const cp=r.clone();caches.open(C).then(c=>c.put(e.request,cp));}
      return r;
    }).catch(()=>caches.match(e.request)));
    return;
  }
  e.respondWith(caches.open(C).then(c=>c.match(e.request).then(hit=>{
    const net=fetch(e.request).then(r=>{if(r&&r.status===200)c.put(e.request,r.clone());return r;}).catch(()=>hit);
    return hit||net;
  })));
});
"""

@app.get("/manifest.webmanifest", tags=["Root"])
def pwa_manifest():
    return Response(content=json.dumps(_PWA_MANIFEST), media_type="application/manifest+json")

@app.get("/icon.svg", tags=["Root"])
def pwa_icon():
    return Response(content=_PWA_ICON, media_type="image/svg+xml",
                   headers={"Cache-Control": "max-age=86400"})

@app.get("/icon.png", tags=["Root"])
def icon_png(size: int = 64):
    """ELI's real icon as a transparent square PNG (favicon / in-app logo)."""
    return _icon_resp(max(16, min(512, int(size))), maskable=False)

@app.get("/icon-192.png", tags=["Root"])
def icon_192():
    return _icon_resp(192, maskable=True)

@app.get("/icon-512.png", tags=["Root"])
def icon_512():
    return _icon_resp(512, maskable=True)

@app.get("/apple-touch-icon.png", tags=["Root"])
def apple_touch_icon():
    """iOS home-screen icon (no transparency — iOS fills it anyway)."""
    return _icon_resp(180, maskable=True)

@app.get("/favicon.ico", tags=["Root"])
def favicon():
    """Browsers auto-request /favicon.ico — serve the real ELI icon (PNG bytes; accepted)."""
    return _icon_resp(32, maskable=False)

@app.get("/sw.js", tags=["Root"])
def pwa_sw():
    return Response(content=_SERVICE_WORKER, media_type="application/javascript")

@app.get("/api", tags=["Root"])
async def api_info():
    return {
        "service": "ELI Cognitive OS Agent",
        "version": "1.0.0",
        "ui": "/",
        "documentation": "/docs",
    }

@app.get("/health", tags=["System"])
async def health():
    return {"status": "healthy"}

def _audit(event_type: str, *, user_id: str = "default", action: str = "",
           subject: str = "", outcome: str = "ok", severity: str = "info",
           session_id: str = "", payload: Optional[dict] = None) -> None:
    """Best-effort, tamper-evident audit record for an API request. Records WHO
    (user_id) did WHAT (action) with what OUTCOME into the hash-chained ledger —
    metadata only, never message/response content. Never raises into the request."""
    try:
        from eli.runtime.evidence_ledger import record_event
        record_event(event_type, source="api", action=action, subject=subject,
                     outcome=outcome, severity=severity, user_id=user_id or "default",
                     session_id=session_id, payload=payload or {})
    except Exception:
        pass


@app.post("/v1/chat", response_model=ChatResponse, tags=["Chat"])
def chat(request: ChatRequest, principal: Principal = Depends(require_member)):
    """Send a message to ELI and get a response."""
    try:
        engine = get_engine()
        session_id = request.session_id or str(int(time.time()))
        who = _effective_user(principal, request.user_id)

        result = engine.process(
            request.message,
            source=f"api:{who}",
            stream=False
        )

        _audit("api_chat", user_id=who, action="CHAT", session_id=session_id)
        return ChatResponse(
            response=_extract_response_text(result),
            session_id=session_id,
            user_id=request.user_id,
            timestamp=time.time()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/v1/chat/stream", tags=["Chat"])
def chat_stream(request: ChatRequest, principal: Principal = Depends(require_member)):
    """Stream ELI's reply incrementally as Server-Sent Events — same LOCAL model and
    same pipeline as /v1/chat, just token-by-token so the UI isn't blank for a minute.
    Frames: {"session_id":…} first, then {"delta":"…"} chunks, then {"done":true}.
    Same acting level as /v1/chat: it runs the full engine, so a read-only viewer
    is 403'd here too, and attribution uses the authenticated identity."""
    engine = get_engine()
    session_id = request.session_id or str(int(time.time()))
    who = _effective_user(principal, request.user_id)

    def _frame(obj) -> str:
        return "data: " + json.dumps(obj) + "\n\n"

    def _gen():
        yield _frame({"session_id": session_id})
        try:
            result = engine.process(request.message, source=f"api:{who}", stream=True)
            if isinstance(result, dict):
                yield _frame({"delta": _extract_response_text(result)})
            elif isinstance(result, str):
                yield _frame({"delta": result})
            else:
                for chunk in result:
                    if isinstance(chunk, str):
                        t = chunk
                    elif isinstance(chunk, dict):
                        t = (chunk.get("token") or chunk.get("delta") or chunk.get("content")
                             or chunk.get("response") or "")
                    else:
                        t = str(chunk)
                    if t:
                        yield _frame({"delta": t})
            yield _frame({"done": True})
        except Exception as e:
            yield _frame({"error": str(e)})

    return StreamingResponse(_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

# ----------------------------------------------------------------------
# ELI local API — the de-facto industry chat shape, served by the LOCAL model.
# Lets any standard local-AI client (IDE assistants, notebooks, MCP bridges) point
# its "Base URL" at ELI and run on your hardware. NOT OpenAI: nothing leaves the
# box; the model is ELI's local GGUF, behind netguard, token-gated like everything.
# ----------------------------------------------------------------------
def _messages_to_prompt(messages) -> str:
    """Flatten a standard `messages` array into one ELI turn. Single-turn → the raw
    user text; multi-turn → a transcript, with any system message(s) on top."""
    msgs = [m for m in messages if (m.content or "").strip()]
    if not msgs:
        return ""
    system = "\n".join(m.content for m in msgs if (m.role or "").lower() == "system").strip()
    convo = [m for m in msgs if (m.role or "").lower() != "system"]
    if len(convo) == 1:
        body = convo[0].content
    else:
        body = "\n".join(
            (("Assistant: " if (m.role or "").lower() == "assistant" else "User: ") + m.content)
            for m in convo)
    return ((system + "\n\n") if system else "") + body

@app.get("/v1/models", tags=["Chat"], dependencies=[Depends(_require_token)])
def list_models():
    """Advertise ELI's local model in the standard list shape (clients query this
    before chatting). It's one entry: your local model, owned by 'eli'."""
    return {"object": "list",
            "data": [{"id": "eli-local", "object": "model", "created": 0, "owned_by": "eli"}]}

@app.post("/v1/chat/completions", tags=["Chat"], dependencies=[Depends(require_member)])
def chat_completions(request: CompletionRequest):
    """Standard chat-completions shape, answered by ELI's LOCAL model + pipeline.
    Honours `stream`; returns the canonical `chat.completion` / `chat.completion.chunk`
    objects (and the `[DONE]` sentinel) so standard clients work drop-in.
    Acting level (member+): it runs the full engine, so read-only viewers are 403'd."""
    engine = get_engine()
    prompt = _messages_to_prompt(request.messages)
    if not prompt.strip():
        raise HTTPException(status_code=400, detail="no message content")
    model = request.model or "eli-local"
    created = int(time.time())
    cid = "chatcmpl-" + secrets.token_hex(12)

    def _chunk(delta: dict, finish=None) -> str:
        return "data: " + json.dumps({
            "id": cid, "object": "chat.completion.chunk", "created": created, "model": model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}) + "\n\n"

    if request.stream:
        def _gen():
            try:
                yield _chunk({"role": "assistant"})
                result = engine.process(prompt, source="api:completions", stream=True)
                if isinstance(result, dict):
                    t = _extract_response_text(result)
                    if t:
                        yield _chunk({"content": t})
                elif isinstance(result, str):
                    if result:
                        yield _chunk({"content": result})
                else:
                    for chunk in result:
                        if isinstance(chunk, str):
                            t = chunk
                        elif isinstance(chunk, dict):
                            t = (chunk.get("token") or chunk.get("delta") or chunk.get("content")
                                 or chunk.get("response") or "")
                        else:
                            t = str(chunk)
                        if t:
                            yield _chunk({"content": t})
                yield _chunk({}, finish="stop")
                yield "data: [DONE]\n\n"
            except Exception as e:
                yield "data: " + json.dumps({"error": {"message": str(e)}}) + "\n\n"
                yield "data: [DONE]\n\n"
        return StreamingResponse(_gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    try:
        result = engine.process(prompt, source="api:completions", stream=False)
        text = _extract_response_text(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {
        "id": cid, "object": "chat.completion", "created": created, "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }

@app.post("/v1/execute", response_model=ExecuteResponse, tags=["Commands"])
def execute(request: ExecuteRequest, principal: Principal = Depends(require_member)):
    """Execute a direct ELI command (OPEN_APP, SCREENSHOT, etc.)."""
    try:
        from eli.execution.executor_enhanced import execute as exec_cmd

        result = exec_cmd(request.action, request.args)

        ok = bool(result.get("ok", False))
        who = _effective_user(principal, request.user_id)
        _audit("api_execute", user_id=who,
               action=str(request.action or "").upper(),
               subject=str(request.args or {})[:200],
               outcome="ok" if ok else "failed",
               severity="info" if ok else "error")
        return ExecuteResponse(
            ok=ok,
            result=result,
            user_id=who,
            timestamp=time.time()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/v1/status/{user_id}", response_model=StatusResponse, tags=["System"],
         dependencies=[Depends(_require_token)])
def status(user_id: str):
    """Get ELI's current status for a user."""
    try:
        from eli.execution.executor_enhanced import get_status
        from eli.core import config
        
        status_data = get_status()
        
        return StatusResponse(
            status="operational",
            version="1.0.0",
            model=config.get_gguf_model_path() or "unknown",
            uptime=time.time() - status_data.get("start_time", time.time()),
            user_id=user_id
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ----------------------------------------------------------------------
# Commands catalogue  (powers the "Commands" tab)
# ----------------------------------------------------------------------
@app.get("/v1/capabilities", tags=["Commands"], dependencies=[Depends(_require_token)])
async def capabilities():
    """The full command catalogue (categories → actions → descriptions → example
    phrases), sourced from the same table that generates the docs so the UI never
    drifts from what ELI can actually do."""
    from eli.tools.registry.capabilities_doc import catalogue
    cats = catalogue()
    return {"total": sum(len(c["actions"]) for c in cats), "categories": cats}

# ----------------------------------------------------------------------
# Devices  (powers the "Devices" tab — ELI's OWN MQTT device server, no Home Assistant)
# ELI keeps its own device registry and talks to devices directly over MQTT
# (ESPHome / Tasmota / Zigbee2MQTT, or anything that speaks MQTT).
# ----------------------------------------------------------------------
def _device_server():
    from eli.runtime.device_server import get_server
    return get_server()

@app.get("/v1/devices/status", tags=["Devices"], dependencies=[Depends(_require_token)])
def devices_status():
    """Broker connection + registry summary (no secrets returned)."""
    return {"ok": True, "status": _device_server().status()}

@app.get("/v1/devices/mqtt/guide", tags=["Devices"], dependencies=[Depends(_require_token)])
def devices_mqtt_guide():
    """Platform-specific MQTT broker install steps and discovery presets."""
    from eli.runtime.mqtt_setup import broker_install_guide, suggest_local_hosts
    guide = broker_install_guide()
    guide["suggested_hosts"] = suggest_local_hosts()
    return {"ok": True, **guide}

@app.post("/v1/devices/mqtt/test", tags=["Devices"], dependencies=[Depends(require_member)])
def devices_mqtt_test(cfg: DeviceConfig):
    """Test broker reachability without persisting settings."""
    from eli.runtime.mqtt_setup import probe_broker_connection
    return probe_broker_connection(
        host=cfg.host.strip(),
        port=int(cfg.port or 1883),
        username=cfg.username or "",
        password=cfg.password or "",
        tls=bool(cfg.tls),
    )

@app.post("/v1/devices/config", tags=["Devices"], dependencies=[Depends(require_member)])
def devices_config(cfg: DeviceConfig):
    """Save the MQTT broker settings, then (re)connect. Password is never returned."""
    srv = _device_server()
    srv.configure(host=cfg.host.strip(), port=int(cfg.port), username=cfg.username,
                  password=cfg.password, discovery_prefix=cfg.discovery_prefix.strip(),
                  tls=bool(cfg.tls))
    return srv.connect()

@app.post("/v1/devices/connect", tags=["Devices"], dependencies=[Depends(require_member)])
def devices_connect():
    """Connect to the configured MQTT broker."""
    return _device_server().connect()

@app.post("/v1/devices/setup", tags=["Devices"], dependencies=[Depends(require_member)])
def devices_setup():
    """One-click device setup: find a broker, save it, connect, report.

    The previous flow required the user to already know their broker's
    hostname and enter it by hand. This finds it over mDNS or on the local
    machine, and when there genuinely is no broker it returns the
    platform-specific install guide as the single remaining step.
    """
    from eli.runtime.mqtt_setup import one_click_setup
    return one_click_setup()

@app.post("/v1/devices/disconnect", tags=["Devices"], dependencies=[Depends(require_member)])
def devices_disconnect():
    return _device_server().disconnect()

@app.get("/v1/devices", tags=["Devices"], dependencies=[Depends(_require_token)])
def devices_list():
    """List ELI's registered devices with their last-known state."""
    return {"ok": True, "devices": _device_server().list_devices()}

@app.get("/v1/devices/rooms", tags=["Devices"], dependencies=[Depends(_require_token)])
def devices_rooms():
    """Devices grouped by room (named rooms first, 'Unassigned' last)."""
    return {"ok": True, "rooms": _device_server().rooms()}

@app.post("/v1/devices/register", tags=["Devices"], dependencies=[Depends(require_member)])
def devices_register(req: DeviceRegister):
    """Manually register a device by its MQTT topics (works without discovery)."""
    return _device_server().register_device(
        device_id=req.device_id, name=req.name, dtype=req.type,
        command_topic=req.command_topic, state_topic=req.state_topic, room=req.room)

@app.post("/v1/devices/room", tags=["Devices"], dependencies=[Depends(require_member)])
def devices_set_room(req: DeviceRoom):
    """Assign (or clear) a device's room."""
    return _device_server().set_room(req.device_id, req.room)

@app.post("/v1/devices/room/control", tags=["Devices"], dependencies=[Depends(require_member)])
def devices_room_control(req: RoomControl):
    """Turn every controllable device in a room on/off at once."""
    return _device_server().control_room(req.room, req.command)

@app.post("/v1/devices/remove", tags=["Devices"], dependencies=[Depends(require_member)])
def devices_remove(req: DeviceRegister):
    return _device_server().remove_device(req.device_id)

@app.post("/v1/devices/control", tags=["Devices"], dependencies=[Depends(require_member)])
def devices_control(req: DeviceControl):
    """Control a device: on | off | brightness <0-100> | set <payload>."""
    return _device_server().control(req.device_id, req.command, req.value)

@app.post("/v1/devices/discover", tags=["Devices"], dependencies=[Depends(require_member)])
def devices_discover(timeout: float = 3.0, fresh: bool = False, kind: str = "all", quick: bool = False):
    """Scan for devices. ``kind=network`` → LAN only. ``kind=bluetooth`` → Bluetooth only.
    ``quick=true`` → instant OS-cached Bluetooth list (no scan). ``fresh=true`` drops cache."""
    from eli.runtime.device_server import discover
    k = (kind or "all").lower()
    bt_only = k in ("all", "bluetooth")
    max_t = 3.0 if quick else (20.0 if k == "bluetooth" else 8.0)
    return discover(
        timeout=min(max_t, max(1.0, float(timeout))),
        fresh=bool(fresh),
        include_network=(k in ("all", "network")),
        include_bluetooth=bt_only,
        quick=bool(quick),
    )


@app.get("/v1/devices/bluetooth/known", tags=["Devices"], dependencies=[Depends(_require_token)])
def devices_bluetooth_known():
    """Instant Bluetooth device list from the OS (paired/connected/known) — no scan."""
    from eli.runtime import bt_platform as bp
    from eli.runtime.device_server import _enrich_bt_discover_results
    rows = bp.list_known_devices()
    if rows:
        _enrich_bt_discover_results(rows)
    return {"ok": True, "found": rows, "count": len(rows)}


@app.post("/v1/devices/bluetooth", tags=["Devices"], dependencies=[Depends(require_member)])
def devices_bluetooth(req: BluetoothAction):
    """Control a Bluetooth device: connect / disconnect / pair / trust / use_for_audio. Give an
    address (from a scan) or a spoken name; both resolve to the OS Bluetooth stack."""
    try:
        cmd = (req.command or "connect").strip().lower().replace(" ", "_").replace("-", "_")
        addr = (req.address or "").strip()
        if addr:
            from eli.runtime import device_drivers
            drv = device_drivers.get_driver("bluetooth")
            if not drv:
                return {"ok": False, "error": "bluetooth driver unavailable"}
            res = dict(drv.control({"host": addr, "name": req.name or "", "driver": "bluetooth"}, cmd))
            res.setdefault("device_name", req.name or addr)
            return res
        from eli.runtime.device_server import bluetooth_control_by_name
        return bluetooth_control_by_name(req.name, cmd)
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ── Local connectivity (WiFi + audio routing) — sovereign, OS tools only ──
@app.get("/v1/connectivity/status", tags=["Devices"], dependencies=[Depends(_require_token)])
def connectivity_status_ep():
    """WiFi link, default audio output, Bluetooth stack — all local, nothing cloud."""
    from eli.runtime import local_connectivity as lc
    return lc.connectivity_status()

@app.get("/v1/connectivity/wifi/networks", tags=["Devices"], dependencies=[Depends(_require_token)])
def connectivity_wifi_scan():
    """Scan nearby WiFi networks via nmcli/netsh — stays on your machine."""
    from eli.runtime import local_connectivity as lc
    return lc.wifi_scan()

@app.post("/v1/connectivity/wifi/connect", tags=["Devices"], dependencies=[Depends(require_member)])
def connectivity_wifi_connect(req: WifiConnect):
    """Join a WiFi network locally (member). Password optional for open networks."""
    from eli.runtime import local_connectivity as lc
    return lc.wifi_connect(req.ssid, req.password or "")

@app.get("/v1/connectivity/audio/outputs", tags=["Devices"], dependencies=[Depends(_require_token)])
def connectivity_audio_outputs(refresh: bool = False):
    """List system audio sinks (speakers, HDMI, Bluetooth) — route media without cloud."""
    from eli.runtime import local_connectivity as lc
    return lc.list_audio_outputs(refresh=bool(refresh))

@app.post("/v1/connectivity/audio/default", tags=["Devices"], dependencies=[Depends(require_member)])
def connectivity_audio_default(req: AudioRoute):
    """Set the default audio output so ELI voice and media play on that device."""
    from eli.runtime import local_connectivity as lc
    return lc.set_default_audio(req.sink)


@app.post("/v1/connectivity/audio/alias", tags=["Devices"], dependencies=[Depends(require_member)])
def connectivity_audio_alias(req: AudioAlias):
    """Name a speaker/output for voice — e.g. 'Kitchen speaker', 'Device 1' → sink id."""
    from eli.runtime import local_connectivity as lc
    return lc.save_audio_alias(req.sink, req.name)

@app.get("/v1/devices/names", tags=["Devices"], dependencies=[Depends(_require_token)])
def devices_names():
    """All nameable devices (Home registry, speakers, Bluetooth) with saved labels."""
    from eli.runtime.device_names import list_nameable_devices
    return {"ok": True, "devices": list_nameable_devices()}

@app.post("/v1/devices/name", tags=["Devices"], dependencies=[Depends(require_member)])
def devices_save_name(req: DeviceNameSave):
    """Save a persistent custom name ELI uses for voice control."""
    from eli.runtime.device_names import save_custom_name, sink_key
    key = (req.key or "").strip()
    if not key and req.sink:
        key = sink_key(req.sink)
    if not key:
        return {"ok": False, "error": "device key required"}
    return save_custom_name(key, req.name)

@app.get("/v1/devices/drivers", tags=["Devices"], dependencies=[Depends(_require_token)])
def devices_drivers():
    """Local-control driver status: which are installed, how each pairs — so the dashboard
    can offer one-click Install / guided Pair when you choose to control a device."""
    from eli.runtime import device_drivers
    return {"ok": True, "drivers": device_drivers.driver_status(),
            "adb": device_drivers.adb_available()}

@app.post("/v1/devices/driver/install", tags=["Devices"], dependencies=[Depends(require_admin)])
def devices_driver_install(req: DriverInstall):
    """One-click, on-demand install of a control driver's library into ELI's own venv
    (admin-only). Keeps the base lean — you only pull a driver when you actually use it."""
    from eli.runtime import device_drivers
    return device_drivers.install_driver(req.name)

@app.post("/v1/devices/add-discovered", tags=["Devices"], dependencies=[Depends(require_member)])
def devices_add_discovered(req: AddDiscovered):
    """Promote a discovery result into a controllable device with its local driver."""
    return _device_server().add_discovered_device(req.device or {})

@app.post("/v1/devices/pair", tags=["Devices"], dependencies=[Depends(require_member)])
def devices_pair(req: DevicePair):
    """Drive a device's pairing (AirPlay PIN / Fire TV accept-on-device). Returns the next
    step: need_code, instructions, or paired."""
    return _device_server().pair_device(req.device_id, req.code)

@app.get("/v1/home/state", tags=["Devices"], dependencies=[Depends(_require_token)])
def home_state_ep():
    """Home snapshot for ELI's awareness — connection, rooms, what's on."""
    return {"ok": True, "state": _device_server().home_state()}

@app.get("/v1/home/mesh/ping", tags=["Devices"], dependencies=[Depends(_require_token)])
def home_mesh_ping():
    """LAN heartbeat — other ELI nodes poll this to detect primary-up/down."""
    from eli.runtime import home_mesh
    return home_mesh.ping_payload()

@app.get("/v1/home/mesh/status", tags=["Devices"], dependencies=[Depends(_require_token)])
def home_mesh_status():
    from eli.runtime import home_mesh
    return home_mesh.mesh_status()

@app.post("/v1/home/mesh/config", tags=["Devices"], dependencies=[Depends(require_member)])
def home_mesh_config(req: MeshConfig):
    from eli.runtime import home_mesh
    # Only patch fields the client actually sent — a full model_dump() would splat
    # every default (node_name="", primary_url="", …) over update_config and WIPE
    # settings the user didn't touch (e.g. editing just the role blanked the name).
    patch = req.model_dump(exclude_unset=True)
    if "peers" in patch:
        patch["peers"] = [p.model_dump() if hasattr(p, "model_dump") else p for p in (req.peers or [])]
    return home_mesh.update_config(patch)

@app.post("/v1/home/mesh/takeover", tags=["Devices"], dependencies=[Depends(require_member)])
def home_mesh_takeover():
    from eli.runtime import home_mesh
    return home_mesh.manual_takeover()

# ── Now-playing media (local MPRIS players: Spotify desktop, VLC, browsers, …) ──
@app.get("/v1/media", tags=["Media"], dependencies=[Depends(_require_token)])
def media_now_playing():
    """Live now-playing across local MPRIS2 players (the same backend voice control uses).
    Returns every running player + which one is 'active', so the dashboard can show a
    now-playing widget and drive transport controls."""
    try:
        from eli.integrations.mpris import playerctl_backend as mp
    except Exception as e:
        return {"ok": False, "error": f"media backend unavailable: {e}", "players": []}
    try:
        infos = mp.list_player_infos()
    except Exception as e:
        return {"ok": False, "error": str(e), "players": []}
    active = None
    try:
        active = mp.get_active_player(command="status")
    except Exception:
        active = (infos[0]["player"] if infos else None)
    for i in infos:
        i["is_active"] = (i.get("player") == active)
    return {"ok": True, "players": infos, "active": active,
            "playing": any((i.get("status") == "playing") for i in infos)}

@app.post("/v1/media/control", tags=["Media"], dependencies=[Depends(require_member)])
def media_control(req: MediaControl):
    """Drive a local media player: play/pause/play-pause/stop/next/previous/volume.
    Same path as voice ('pause spotify') — controls the desktop app on this machine."""
    try:
        from eli.integrations.mpris import playerctl_backend as mp
    except Exception as e:
        return {"ok": False, "error": f"media backend unavailable: {e}"}
    cmd = (req.command or "").strip().lower()
    p = req.player
    fn = {
        "play": lambda: mp.play(p),
        "pause": lambda: mp.pause(p),
        "play-pause": lambda: mp.play_pause(p),
        "toggle": lambda: mp.play_pause(p),
        "stop": lambda: mp.stop(p),
        "next": lambda: mp.next_track(p),
        "previous": lambda: mp.previous_track(p),
        "prev": lambda: mp.previous_track(p),
        "volume": lambda: mp.set_volume(int(req.value if req.value is not None else 30), p),
    }.get(cmd)
    if not fn:
        return {"ok": False, "error": f"unsupported media command {req.command!r}"}
    try:
        return fn()
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ── Per-user dashboard layout (server-side so it syncs across PC ↔ phone) ──
_UI_PREFS_LOCK = threading.Lock()

def _ui_prefs_path():
    try:
        from eli.core.paths import get_paths
        base = Path(get_paths().artifacts_dir)
    except Exception:
        base = Path("artifacts")
    base.mkdir(parents=True, exist_ok=True)
    return base / "ui_prefs.json"

def _ui_prefs_all() -> dict:
    try:
        return json.loads(_ui_prefs_path().read_text())
    except Exception:
        return {}

@app.get("/v1/ui/prefs", tags=["UI"])
def ui_prefs_get(request: Request, authorization: str = Header(default="")):
    """Load this user's saved dashboard layout (widget order + hidden set). Empty = defaults."""
    p = _authenticated(authorization, _is_loopback_client(request))
    uid = _effective_user(p, "")
    with _UI_PREFS_LOCK:
        return {"ok": True, "prefs": _ui_prefs_all().get(uid, {})}

@app.post("/v1/ui/prefs", tags=["UI"], dependencies=[Depends(require_member)])
def ui_prefs_set(req: UIPrefs, request: Request, authorization: str = Header(default="")):
    """Persist this user's dashboard layout."""
    p = _authenticated(authorization, _is_loopback_client(request))
    uid = _effective_user(p, "")
    with _UI_PREFS_LOCK:
        allp = _ui_prefs_all()
        allp[uid] = req.prefs or {}
        try:
            _ui_prefs_path().write_text(json.dumps(allp, indent=2))
        except Exception as e:
            return {"ok": False, "error": str(e)}
    return {"ok": True, "prefs": req.prefs or {}}

# ── Cognition / autonomy: surface ELI's real internals to the dashboard ──
@app.get("/v1/cognition/orchestration", tags=["Cognition"], dependencies=[Depends(_require_token)])
def cognition_orchestration():
    """The live agent DAG: orchestration engine, agents, and parallel execution layers."""
    try:
        from eli.cognition.agent_bus import orchestration_snapshot
        return {"ok": True, **orchestration_snapshot()}
    except Exception as e:
        return {"ok": False, "error": str(e), "agents": [], "execution_layers": []}

@app.get("/v1/autonomy/goals", tags=["Cognition"], dependencies=[Depends(_require_token)])
def autonomy_goals():
    """ELI's self-generated autonomous goals (habit-streamlining, self-repair, …)."""
    try:
        from eli.planning.goal_store import summarize_goals, list_active_goals
        s = summarize_goals()
        try:
            s["goals"] = [{"title": g.title, "status": getattr(g, "status", "active"),
                           "kind": getattr(g, "kind", "")} for g in list_active_goals()[:10]]
        except Exception:
            pass
        return s
    except Exception as e:
        return {"ok": False, "error": str(e), "active": 0, "total": 0, "titles": []}

@app.get("/v1/tasks", tags=["Cognition"], dependencies=[Depends(_require_token)])
def tasks_list():
    """Scheduled / overnight tasks ELI will run (code, research, eval, reflection, …)."""
    try:
        from eli.runtime.scheduled_tasks import _load_store
        items = [{"pid": e.get("pid"), "request": e.get("request"), "kind": e.get("kind"),
                  "when_ts": e.get("when_ts"), "when_spec": e.get("when_spec"),
                  "recurring": bool(e.get("recurring"))} for e in _load_store()]
        items.sort(key=lambda x: x.get("when_ts") or 0)
        return {"ok": True, "tasks": items}
    except Exception as e:
        return {"ok": False, "error": str(e), "tasks": []}

@app.post("/v1/tasks", tags=["Cognition"], dependencies=[Depends(require_member)])
def tasks_add(req: TaskCreate):
    """Queue a task for ELI to run later (e.g. 'review the codebase for bugs' overnight)."""
    if not (req.request or "").strip():
        return {"ok": False, "error": "no task description"}
    try:
        from eli.runtime.scheduled_tasks import schedule_request
        return schedule_request(req.request, when_spec=(req.when or req.request), kind=req.kind)
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.post("/v1/tasks/remove", tags=["Cognition"], dependencies=[Depends(require_member)])
def tasks_remove(req: TaskRef):
    try:
        from eli.runtime.scheduled_tasks import forget
        forget(req.pid)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/v1/home/suggestions", tags=["Devices"], dependencies=[Depends(_require_token)])
def home_suggestions_ep():
    """Proactive automation ideas ELI derives from how you use your devices."""
    from eli.runtime import home_intel
    return {"ok": True, "suggestions": home_intel.suggestions()}

@app.post("/v1/home/suggestions/accept", tags=["Devices"], dependencies=[Depends(require_member)])
def home_suggestion_accept(req: SuggestionAccept):
    """Turn one of ELI's suggestions into a real recurring automation."""
    hm = f"{int(req.hour) % 24:02d}:00"
    return _device_server().add_automation(device=req.device, command=req.command,
                                          time_str=hm, name=req.name)

@app.get("/v1/home/automations", tags=["Devices"], dependencies=[Depends(_require_token)])
def home_automations_list():
    return {"ok": True, "automations": _device_server().list_automations()}

@app.post("/v1/home/automations/add", tags=["Devices"], dependencies=[Depends(require_member)])
def home_automation_add(req: AutomationCreate):
    """Create a recurring automation: run <command> on <device> at <time> (HH:MM)."""
    return _device_server().add_automation(device=req.device, command=req.command,
                                          time_str=req.time, value=req.value,
                                          days=req.days, name=req.name)

@app.post("/v1/home/automations/remove", tags=["Devices"], dependencies=[Depends(require_member)])
def home_automation_remove(req: AutomationRef):
    return _device_server().remove_automation(req.id)

@app.post("/v1/home/automations/toggle", tags=["Devices"], dependencies=[Depends(require_member)])
def home_automation_toggle(req: AutomationRef):
    return _device_server().set_automation_enabled(req.id, bool(req.enabled))

@app.post("/v1/home/automations/create", tags=["Devices"], dependencies=[Depends(require_member)])
def home_automation_create(req: AutomationCreateV2):
    """Create an automation: a trigger (time / sun / device_state) runs one or more
    actions (control a device, or activate a scene), optionally only when conditions hold."""
    return _device_server().create_automation(req.name, req.trigger, req.action, req.condition)

# ── Scenes ──────────────────────────────────────────────────────────────────
@app.get("/v1/home/scenes", tags=["Devices"], dependencies=[Depends(_require_token)])
def scenes_list():
    return {"ok": True, "scenes": _device_server().list_scenes()}

@app.post("/v1/home/scenes/add", tags=["Devices"], dependencies=[Depends(require_member)])
def scenes_add(req: SceneCreate):
    return _device_server().add_scene(req.name, [a.model_dump() for a in req.actions])

@app.post("/v1/home/scenes/remove", tags=["Devices"], dependencies=[Depends(require_member)])
def scenes_remove(req: SceneRef):
    return _device_server().remove_scene(req.id)

@app.post("/v1/home/scenes/activate", tags=["Devices"], dependencies=[Depends(require_member)])
def scenes_activate(req: SceneActivate):
    return _device_server().activate_scene(req.scene)

# ── Location (for sunrise/sunset triggers) ──────────────────────────────────
@app.get("/v1/home/sun", tags=["Devices"], dependencies=[Depends(_require_token)])
def home_sun():
    return {"ok": True, "sun": _device_server()._sun_hm()}

@app.post("/v1/home/location", tags=["Devices"], dependencies=[Depends(require_member)])
def home_location(req: HomeLocation):
    """Save the home's latitude/longitude so sunrise/sunset triggers can be computed."""
    from eli.core import config
    config.set("home_lat", req.lat)
    config.set("home_lon", req.lon)
    return {"ok": True, "sun": _device_server()._sun_hm()}

# ----------------------------------------------------------------------
# System telemetry  (powers the "System" tab — real, measured, never guessed)
# ----------------------------------------------------------------------
@app.get("/v1/system", tags=["System"], dependencies=[Depends(_require_token)])
def system_status():
    """Live, MEASURED self-status — GPU temp/util/VRAM, CPU load/temp, RAM, the
    loaded model and uptime. Same grounded source ELI uses so it never confabulates
    hardware numbers. Read-only."""
    try:
        from eli.runtime.self_status import get_self_status
        st = get_self_status()
        m = st.get("model")
        if isinstance(m, dict) and m.get("model_path"):
            m["name"] = os.path.basename(str(m["model_path"]))
        return {"ok": True, "status": st}
    except Exception as e:
        return {"ok": False, "error": str(e), "status": {}}

# ----------------------------------------------------------------------
# Internet toggle + egress monitoring  (powers the Overview "Internet" switch)
# ELI is offline-by-default and hard-gated at the socket boundary (eli.core.netguard).
# This surface lets the OWNER deliberately open internet access while keeping it
# monitored: the switch is admin-only and every flip is written to the tamper-evident
# audit ledger, AND — once on — netguard records every allowed outbound connection
# (host:port) to the same ledger (`net_egress` events) and an in-memory live tail.
# Reading the state/egress is token-gated; flipping the switch is admin-only.
# ----------------------------------------------------------------------
def _net_state() -> dict:
    """Current, grounded internet-gate state — what netguard will actually enforce."""
    from eli.core import netguard
    try:
        from eli.core.config import network_allowed
        enabled = bool(network_allowed())
    except Exception:
        enabled = False
    return {
        "enabled": enabled,                                  # persisted policy
        "override_active": netguard.network_override_active(),  # scoped allow_network()
        "blocked": netguard.should_block_network(),          # net effect right now
        "local_services": netguard.local_services(),         # permitted LAN hosts
        "egress_total": netguard.egress_total(),             # outbound connections recorded
        "egress_recent": netguard.recent_egress(limit=5),    # last few host:port (live tail)
    }

@app.get("/v1/net", tags=["System"], dependencies=[Depends(_require_token)])
def net_status():
    """Read the monitored internet-gate state + a live tail of recorded egress (read-only)."""
    try:
        return {"ok": True, "net": _net_state()}
    except Exception as e:
        return {"ok": False, "error": str(e), "net": {}}

@app.get("/v1/net/egress", tags=["System"], dependencies=[Depends(_require_token)])
def net_egress(limit: int = 100):
    """The outbound connections netguard allowed (host:port + timestamp). This is the
    live in-memory tail; the durable, tamper-evident record is the `net_egress` events
    in the audit trail (`/v1/audit`)."""
    try:
        from eli.core import netguard
        n = max(1, min(int(limit or 100), 500))
        return {"ok": True, "total": netguard.egress_total(),
                "egress": netguard.recent_egress(limit=n)}
    except Exception as e:
        return {"ok": False, "error": str(e), "egress": [], "total": 0}

@app.post("/v1/net", tags=["System"])
def net_set(body: NetToggle, principal: Principal = Depends(require_admin)):
    """Flip the internet switch (admin-only). Persisted and recorded to the audit
    ledger. Enabling is logged at 'warning' severity so it stands out in the trail.
    The socket-level failsafe still governs every actual connection."""
    try:
        from eli.core import config as _cfg
        _cfg.set("network_enabled", bool(body.enabled))
        state = _net_state()
        _audit(
            "net_toggle",
            user_id=principal.user_id,
            action="NET_ENABLE" if body.enabled else "NET_DISABLE",
            subject=(body.reason or "")[:280],
            outcome="enabled" if body.enabled else "disabled",
            severity="warning" if body.enabled else "info",
            payload={"enabled": bool(body.enabled), "reason": body.reason or "",
                     "state": state},
        )
        return {"ok": True, "net": state}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/v1/settings", tags=["System"], dependencies=[Depends(_require_token)])
def get_settings():
    """Current values for the curated, safe-to-expose settings + their schema, so the
    dashboard can render real, typed controls (no invented options)."""
    from eli.core import config as _cfg
    cur = {}
    for k in _SETTINGS_SCHEMA:
        cur[k] = _cfg.get(k, None)
    schema = []
    for k, t in _SETTINGS_SCHEMA.items():
        item = {"key": k, "type": t[0], "group": t[1], "label": t[2], "hint": t[3]}
        if len(t) > 4:
            item.update({"min": t[4], "max": t[5], "step": t[6]})
        schema.append(item)
    return {"ok": True, "values": cur, "schema": schema}

@app.post("/v1/settings", tags=["System"])
def set_settings(req: SettingsUpdate, principal: Principal = Depends(require_admin)):
    """Apply settings (admin-only). Only allow-listed keys with valid coercion are written;
    every change is recorded to the tamper-evident audit ledger."""
    from eli.core import config as _cfg
    applied = {}
    for k, v in (req.settings or {}).items():
        if k not in _SETTINGS_SCHEMA:
            continue
        typ = _SETTINGS_SCHEMA[k][0]
        try:
            if typ == "bool":
                v = bool(v)
            elif typ == "int":
                v = int(v)
            elif typ == "float":
                v = float(v)
            else:
                v = str(v)
        except Exception:
            continue
        _cfg.set(k, v)
        applied[k] = v
    if applied:
        _audit("settings_update", user_id=principal.user_id, action="UPDATE",
               subject=",".join(sorted(applied)), outcome="applied",
               payload={"applied": applied})
    return {"ok": True, "applied": applied}


def _list_chat_models() -> list:
    """Chat-capable GGUFs under models/ (excludes vision/projector/embedding files)."""
    import glob
    out = []
    for g in sorted(glob.glob("models/**/*.gguf", recursive=True)):
        base = os.path.basename(g).lower()
        if any(x in base for x in ("mmproj", "embed", "nomic", "clip", "moondream", "vision")):
            continue
        try:
            gb = round(os.path.getsize(g) / 1e9, 1)
        except OSError:
            continue
        out.append({"path": g, "name": os.path.basename(g), "size_gb": gb})
    return out


@app.get("/v1/models/installed", tags=["System"], dependencies=[Depends(_require_token)])
def list_models():
    """Available chat models + the active one, for the dashboard's model dropdown.
    (Distinct path from the OpenAI-compatible /v1/models so it isn't shadowed by it.)
    `active` is the *actually resolved* model (honours the env override), so the
    dropdown reflects what's really loaded — not just what's in config."""
    active = None
    try:
        from eli.cognition import gguf_inference as _gi
        p = _gi.get_model_path()
        active = str(p) if p else None
    except Exception:
        pass
    if not active:
        from eli.core import config as _cfg
        active = (_cfg.get("gguf_model_path", None) or _cfg.get("model_path", None)
                  or _cfg.get("custom_model_path", None))
    return {"ok": True, "models": _list_chat_models(), "active": active}


@app.post("/v1/model", tags=["System"])
def switch_model(req: ModelSwitch, principal: Principal = Depends(require_admin)):
    """Switch the active model and hot-reload it (admin-only). Only a path already in
    the available-models list is accepted, so the dropdown can never strand the runtime
    on a bad path; the VRAM loader fits it on reload."""
    path = (req.path or "").strip()
    if path not in {m["path"] for m in _list_chat_models()}:
        return {"ok": False, "error": "unknown_model", "path": path}
    try:
        from eli.core import runtime_settings as _rs
        res = _rs.apply_runtime_settings(
            {"model_path": path, "gguf_model_path": path, "custom_model_path": path},
            do_reload=True)
        _audit("model_switch", user_id=principal.user_id, action="UPDATE",
               subject=os.path.basename(path), outcome="applied", payload={"path": path})
        return {"ok": True, "path": path, "reload": res}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _lan_subnet() -> str:
    """The /24 the LAN IP sits on (e.g. 192.168.1.0/24) — used to scope the firewall rule
    to the local network rather than the whole world."""
    ip = _lan_ip()
    p = ip.split(".")
    if len(p) == 4 and ip != "<this-computer-ip>":
        return f"{p[0]}.{p[1]}.{p[2]}.0/24"
    return "192.168.0.0/16"


def _firewall_hint() -> dict:
    """OS-aware command to open the LAN port through the local firewall, + a best-effort
    read of whether it's likely the blocker. Detection is behavioural (see _LAN_SEEN);
    this supplies the exact fix for the detected OS/firewall tool."""
    import platform
    import shutil
    osname = platform.system().lower()
    port = os.environ.get("ELI_API_PORT", "8081")
    hport = os.environ.get("ELI_API_HTTPS_PORT")
    subnet = _lan_subnet()
    cmds, tool = [], ""
    if osname == "linux":
        if shutil.which("ufw"):
            tool = "ufw"
            cmds = [f"sudo ufw allow from {subnet} to any port {port} proto tcp"]
            if hport:
                cmds.append(f"sudo ufw allow from {subnet} to any port {hport} proto tcp")
        elif shutil.which("firewall-cmd"):
            tool = "firewalld"
            cmds = [f"sudo firewall-cmd --add-port={port}/tcp",
                    f"sudo firewall-cmd --permanent --add-port={port}/tcp"]
        else:
            tool = "iptables"
            cmds = [f"sudo iptables -I INPUT -p tcp -s {subnet} --dport {port} -j ACCEPT"]
    elif osname == "windows":
        tool = "Windows Firewall"
        cmds = [f'netsh advfirewall firewall add rule name="ELI" dir=in '
                f'action=allow protocol=TCP localport={port}']
    elif osname == "darwin":
        tool = "macOS firewall"
        cmds = ["System Settings → Network → Firewall → allow incoming connections for "
                "python3 (or turn the firewall off while testing)."]
    return {"os": osname, "tool": tool, "commands": cmds, "subnet": subnet}


def _connect_url() -> dict:
    """Everything the 'Connect a phone' tab needs: the LAN IP, port, the ready-to-open URL
    (token included when set), and whether the server is actually reachable from the LAN."""
    host = os.environ.get("ELI_API_HOST", "127.0.0.1")
    port = os.environ.get("ELI_API_PORT", "8081")
    lan_accessible = host in ("0.0.0.0", "::", "")  # bound to all interfaces
    ip = _lan_ip()
    token = _api_token()
    # Token in the URL FRAGMENT (#token=…), never the query: the fragment is not sent to
    # the server, so it can't land in uvicorn's access log; the page JS reads location.hash,
    # stores it, and strips it from history. Keeps the bearer token out of logs/history.
    q = f"#token={token}" if token else ""
    url = f"http://{ip}:{port}/" + q            # primary connect — opens on any phone
    hport = os.environ.get("ELI_API_HTTPS_PORT")  # set only when HTTPS (voice) is running
    voice_url = (f"https://{ip}:{hport}/" + q) if hport else None
    return {"lan_ip": ip, "port": port, "bind_host": host, "scheme": "http",
            "lan_accessible": lan_accessible, "url": url, "has_token": bool(token),
            "https_available": bool(hport), "https_port": hport, "voice_url": voice_url}

@app.get("/v1/connect", tags=["System"], dependencies=[Depends(_require_token)])
def connect_info():
    """Phone-connect details (URL + LAN reachability) for the Connect tab — plus behavioural
    firewall detection: whether any LAN device has actually reached the server, and the
    exact 'allow' command if not."""
    info = _connect_url()
    info["lan_clients_seen"] = bool(_LAN_SEEN["any"])
    info["lan_client_count"] = int(_LAN_SEEN["count"])
    info["firewall"] = _firewall_hint()
    try:
        from eli.core import config as _cfg
        info["saved_port"] = _cfg.get("api_port") or None
    except Exception:
        info["saved_port"] = None
    return {"ok": True, **info}


class PortSetting(BaseModel):
    port: int


@app.post("/v1/connect/port", tags=["System"], dependencies=[Depends(require_admin)])
def set_api_port(body: PortSetting):
    """Persist the port the ELI server should listen on. Takes effect on the next start —
    change it when 8081 clashes with another service on your LAN. Clearing it (port 0)
    restores the 8081 default. Loopback (127.0.0.1) ports < 1024 need root, so we cap the
    accepted range to the safe, user-bindable band."""
    p = int(body.port)
    from eli.core import config as _cfg
    if p == 0:
        _cfg.delete("api_port") if hasattr(_cfg, "delete") else _cfg.set("api_port", None)
        return {"ok": True, "port": None, "note": "Reset to default 8081. Restart the server to apply."}
    if not (1024 <= p <= 65535):
        raise HTTPException(status_code=400, detail="port must be between 1024 and 65535 (or 0 to reset)")
    _cfg.set("api_port", p)
    return {"ok": True, "port": p, "note": f"Saved. Restart the ELI server for it to listen on :{p}."}

@app.get("/v1/connect/qr.svg", tags=["System"], dependencies=[Depends(_require_token)])
def connect_qr(kind: str = "connect"):
    """A scannable QR (SVG). kind=connect → the HTTP URL (opens on any phone); kind=voice →
    the HTTPS URL (enables the mic). Dark modules on a light field with a quiet-zone border
    so phone cameras read it reliably; the dashboard fetches this with auth and injects it."""
    info = _connect_url()
    target = info["voice_url"] if (kind == "voice" and info.get("voice_url")) else info["url"]
    try:
        import re
        import segno
        svg = segno.make(target, error="m").svg_inline(
            scale=8, border=4, dark="#06141f", light="#eafcff")
        # segno's svg_inline emits width/height but NO viewBox, so a CSS resize CLIPS it
        # (cutting off the QR → unscannable). Add a viewBox so it scales to its container,
        # and make it responsive (width/height 100%).
        m = re.search(r'width="(\d+)" height="(\d+)"', svg)
        if m:
            w = m.group(1)
            svg = svg.replace(
                m.group(0),
                f'viewBox="0 0 {w} {w}" width="100%" height="100%" '
                f'preserveAspectRatio="xMidYMid meet"', 1)
        return Response(content=svg, media_type="image/svg+xml")
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"qr unavailable: {e} (pip install segno)")

# ----------------------------------------------------------------------
# Audit trail  (powers the "Audit" tab — tamper-evident, read-only)
# Every API action is recorded into a hash-chained ledger (who did what, with what
# outcome). /v1/audit returns recent events (optionally per user) plus a live
# verification of the chain's integrity — any edited/deleted/reordered row is flagged.
# ----------------------------------------------------------------------
@app.get("/v1/audit", tags=["System"], dependencies=[Depends(_require_token)])
def audit_log(user_id: Optional[str] = None, limit: int = 50):
    """Tamper-evident audit trail: recent action events (optionally filtered to one
    user) + a verification of the hash chain. Metadata only — no message content."""
    try:
        from eli.runtime.evidence_ledger import recent_events, verify_chain
        n = max(1, min(int(limit or 50), 500))
        rows = recent_events(limit=n, user_id=user_id)
        events = [{
            "id": e.get("id"), "timestamp": e.get("timestamp"),
            "event_type": e.get("event_type"), "source": e.get("source"),
            "action": e.get("action"), "subject": e.get("subject"),
            "outcome": e.get("outcome"), "severity": e.get("severity"),
            "user_id": e.get("user_id"), "session_id": e.get("session_id"),
        } for e in rows]
        return {"ok": True, "integrity": verify_chain(), "events": events}
    except Exception as e:
        return {"ok": False, "error": str(e), "events": [], "integrity": None}

@app.get("/v1/me", tags=["Auth"])
def whoami(principal: Principal = Depends(require_viewer)):
    """The authenticated caller's identity + role (lets the UI reflect read-only viewers)."""
    from eli.runtime import api_users
    return {"ok": True, "user_id": principal.user_id, "role": principal.role,
            "rbac": api_users.rbac_enabled()}

# ----------------------------------------------------------------------
# Admin / Enterprise console  (powers the "Admin" tab — read-only management view)
# Aggregates the tamper-evident audit ledger (integrity, totals, per-user activity)
# and surfaces the approval/risk-gate policy. All local; metadata only.
# ----------------------------------------------------------------------
def _approval_policy() -> dict:
    """The risk-gate policy: which action classes auto-approve vs need manual approval,
    and which emitter (agent) may propose which classes."""
    try:
        from eli.runtime import approval_engine as ap
        return {
            "action_classes": sorted(ap.ACTION_CLASSES),
            "auto_approve": sorted(ap.AUTO_APPROVE),
            "manual_approve": sorted(ap.MANUAL_APPROVE),
            "emitter_policy": {k: sorted(v) for k, v in ap.EMITTER_POLICY.items()},
            "full_control": _full_control_on(),
        }
    except Exception as e:
        return {"error": str(e)}

def _full_control_on() -> bool:
    try:
        from eli.core.full_control import is_full_control
        return bool(is_full_control())
    except Exception:
        return False

@app.get("/v1/admin/overview", tags=["Admin"], dependencies=[Depends(require_admin)])
def admin_overview():
    """Enterprise overview: audit-chain integrity, totals, per-user activity rollup,
    the approval/risk-gate policy, and the RBAC user roster. Admin only."""
    try:
        from eli.runtime.evidence_ledger import verify_chain, totals, users_summary
        from eli.runtime import api_users
        return {"ok": True, "integrity": verify_chain(), "totals": totals(),
                "users": users_summary(), "policy": _approval_policy(),
                "rbac": {"enabled": api_users.rbac_enabled(), "accounts": api_users.list_users()}}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.post("/v1/admin/users/add", tags=["Admin"], dependencies=[Depends(require_admin)])
def admin_users_add(req: UserCreate):
    """Create (or replace) a user with a role; returns a one-time token to share. Admin only."""
    from eli.runtime import api_users
    return api_users.add_user(req.user_id, req.role)

@app.post("/v1/admin/users/remove", tags=["Admin"], dependencies=[Depends(require_admin)])
def admin_users_remove(req: UserRef):
    """Remove a user (the last admin cannot be removed). Admin only."""
    from eli.runtime import api_users
    return api_users.remove_user(req.user_id)

@app.get("/v1/admin/user", tags=["Admin"], dependencies=[Depends(require_admin)])
def admin_user(user_id: str, limit: int = 50):
    """Recent activity for one user (drill-down from the overview)."""
    try:
        from eli.runtime.evidence_ledger import recent_events
        rows = recent_events(limit=max(1, min(int(limit or 50), 500)), user_id=user_id)
        events = [{
            "id": e.get("id"), "timestamp": e.get("timestamp"),
            "event_type": e.get("event_type"), "source": e.get("source"),
            "action": e.get("action"), "subject": e.get("subject"),
            "outcome": e.get("outcome"), "severity": e.get("severity"),
        } for e in rows]
        return {"ok": True, "user_id": user_id, "events": events}
    except Exception as e:
        return {"ok": False, "error": str(e), "events": []}

# ----------------------------------------------------------------------
# Research workspaces  (powers the "Research" tab — fully local, no external surface)
# Ingest your own documents into an isolated corpus, then ask grounded questions
# answered ONLY from those sources (with citations). Reuses ELI's nomic embedder +
# FAISS + the local model; nothing leaves the box.
# ----------------------------------------------------------------------
@app.get("/v1/research/corpora", tags=["Research"], dependencies=[Depends(_require_token)])
def research_corpora():
    from eli.runtime.research_corpus import corpora
    return {"ok": True, "corpora": corpora()}

@app.post("/v1/research/ingest", tags=["Research"])
def research_ingest(req: ResearchIngest, principal: Principal = Depends(require_member)):
    """Ingest a local file or folder of documents (.pdf/.txt/.md) into a SHARED corpus,
    attributed to the (authenticated, under RBAC) contributor."""
    from eli.runtime.research_corpus import ingest
    return ingest(req.corpus, req.path, user=_effective_user(principal, req.user))

@app.post("/v1/research/note", tags=["Research"])
def research_note(req: ResearchNote, principal: Principal = Depends(require_member)):
    """Create/replace a text note in a shared corpus (collaborative create/edit)."""
    from eli.runtime.research_corpus import add_note
    return add_note(req.corpus, req.title, req.text, user=_effective_user(principal, req.user))

@app.post("/v1/research/remove", tags=["Research"])
def research_remove(req: ResearchDoc, principal: Principal = Depends(require_member)):
    """Remove a document from a shared corpus (collaborative edit/cleanup)."""
    from eli.runtime.research_corpus import remove_document
    return remove_document(req.corpus, req.source, user=_effective_user(principal, req.user))

@app.get("/v1/research/documents", tags=["Research"], dependencies=[Depends(_require_token)])
def research_documents(corpus: str):
    """List the documents in a corpus with who added each and when."""
    from eli.runtime.research_corpus import documents, members
    return {"ok": True, "documents": documents(corpus), "members": members(corpus)}

@app.get("/v1/research/activity", tags=["Research"], dependencies=[Depends(_require_token)])
def research_activity(corpus: str, limit: int = 25):
    """Recent collaboration activity in a corpus (who ingested/added/asked)."""
    from eli.runtime.research_corpus import activity
    return {"ok": True, "activity": activity(corpus, limit=limit)}

@app.post("/v1/research/query", tags=["Research"])
def research_query(req: ResearchQuery, principal: Principal = Depends(require_member)):
    """Retrieve the most relevant passages from a corpus and synthesise a grounded,
    cited answer with the LOCAL model. Returns {answer, sources}."""
    from eli.runtime.research_corpus import query
    res = query(req.corpus, req.question, k=req.k, user=_effective_user(principal, req.user))
    if not res.get("ok"):
        return res
    hits = res.get("hits", [])
    if not hits:
        return {"ok": True, "answer": "No relevant passages found in this corpus.", "sources": []}
    ctx = "\n\n".join(f"[{h['source']}] {h['text']}" for h in hits)
    prompt = ("Answer the QUESTION using ONLY the SOURCES below. After each claim, cite the "
              "source name in square brackets, e.g. [paper.pdf]. If the sources do not contain "
              "the answer, say so plainly — do not invent.\n\nSOURCES:\n" + ctx +
              "\n\nQUESTION: " + req.question)
    try:
        answer = _extract_response_text(get_engine().process(prompt, source="api:research", stream=False))
    except Exception as e:
        answer = f"(retrieval succeeded; local-model synthesis unavailable: {e})"
    sources = [{"source": h["source"], "score": h["score"], "excerpt": (h["text"] or "")[:240]}
               for h in hits]
    return {"ok": True, "answer": answer, "sources": sources}

# ----------------------------------------------------------------------
# Browser voice  (powers "Talk to ELI" from any phone — fully local)
# Mic audio → ELI's local faster-whisper STT → text; reply text → local Piper
# TTS → WAV the browser plays itself. No cloud STT/TTS; nothing leaves the box.
# ----------------------------------------------------------------------
@app.get("/v1/voice/voices", tags=["Voice"], dependencies=[Depends(_require_token)])
def voice_voices():
    try:
        from eli.perception import tts_router
        return {"ok": True, "voices": tts_router.list_voices(),
                "active": tts_router.get_active_voice()}
    except Exception as e:
        return {"ok": False, "error": str(e), "voices": [], "active": None}

_VOICE_EXTS = {"webm", "ogg", "mp4", "m4a", "wav", "mp3"}

@app.post("/v1/voice/stt", tags=["Voice"], dependencies=[Depends(require_member)])
async def voice_stt(request: Request, ext: str = "webm"):
    """Transcribe a raw audio clip (POST body) with ELI's local whisper model.
    Body is the audio bytes; `?ext=` (or the Content-Type subtype) names the
    container so PyAV can decode it. Raw-body keeps us free of python-multipart."""
    import tempfile
    data = await request.body()
    if not data:
        return {"ok": False, "error": "empty audio"}
    ct = (request.headers.get("content-type") or "").split(";")[0].split("/")[-1].strip().lower()
    chosen = (ext or "").lower() if (ext or "").lower() in _VOICE_EXTS else (ct if ct in _VOICE_EXTS else "webm")
    suffix = "." + chosen
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(prefix="eli_voice_", suffix=suffix, delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        from eli.perception.local_whisper_stt import transcribe_file
        from fastapi.concurrency import run_in_threadpool
        # Offload the blocking transcription so it doesn't stall the event loop.
        text = (await run_in_threadpool(transcribe_file, tmp_path) or "").strip()
        return {"ok": True, "text": text}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

@app.post("/v1/voice/tts", tags=["Voice"], dependencies=[Depends(require_member)])
def voice_tts(req: TTSRequest):
    """Render text to a WAV with ELI's local Piper voice (the browser plays it)."""
    try:
        from eli.perception import tts_router
        wav = tts_router.synthesize_wav(req.text, voice_name=req.voice)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"tts failed: {e}")
    if not wav:
        raise HTTPException(status_code=503, detail="no speakable text or no local voice available")
    return Response(content=wav, media_type="audio/wav")

# ----------------------------------------------------------------------
# Run the server
# ----------------------------------------------------------------------
def _lan_ip() -> str:
    """Best-effort private LAN IP a phone on the same Wi-Fi can actually reach.
    Prefers 192.168/10/non-docker-172 over loopback and docker bridges."""
    import socket, subprocess
    cands = []
    try:
        cands.append(socket.gethostbyname(socket.gethostname()))
    except Exception:
        pass
    try:
        out = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=2)
        cands += (out.stdout or "").split()
    except Exception:
        pass
    try:  # macOS
        for ifc in ("en0", "en1"):
            out = subprocess.run(["ipconfig", "getifaddr", ifc], capture_output=True, text=True, timeout=2)
            if out.stdout.strip():
                cands.append(out.stdout.strip())
    except Exception:
        pass

    def _score(ip: str) -> int:
        if not ip or ip.startswith("127.") or ":" in ip:
            return -1
        if ip.startswith("192.168."):
            return 4
        if ip.startswith("10."):
            return 3
        if ip.startswith("172.17.") or ip.startswith("172.18."):
            return 1  # docker bridge — usable but deprioritised
        return 2
    best = max(cands, key=_score, default="")
    return best if best and _score(best) > 0 else "<this-computer-ip>"


def _ensure_lan_cert():
    """Self-signed TLS cert for LAN HTTPS — so a phone browser will allow the microphone
    (getUserMedia is blocked on plain http://LAN-IP). Generated locally with `cryptography`
    (pure-python, cross-platform, no cloud); SANs cover the LAN IP + loopback + localhost.
    Private key born 0600. Reused while valid + still covering the current IP. Returns
    (cert_path, key_path)."""
    import datetime
    import ipaddress
    from pathlib import Path
    try:
        from eli.core.paths import get_paths
        cdir = Path(get_paths().config_dir) / "certs"
    except Exception:
        cdir = Path("config") / "certs"
    cdir.mkdir(parents=True, exist_ok=True)
    crt, key = cdir / "eli-lan.crt", cdir / "eli-lan.key"
    ip = _lan_ip()
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    if crt.exists() and key.exists():  # reuse if valid + covers this IP
        try:
            c = x509.load_pem_x509_certificate(crt.read_bytes())
            ok_time = c.not_valid_after_utc > datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)
            san = c.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            ips = [str(x) for x in san.get_values_for_type(x509.IPAddress)]
            if ok_time and (ip in ips or ip == "<this-computer-ip>"):
                return str(crt), str(key)
        except Exception:
            pass

    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    san_ips = []
    for cand in (ip, "127.0.0.1"):
        try:
            san_ips.append(x509.IPAddress(ipaddress.ip_address(cand)))
        except Exception:
            pass
    san = [x509.DNSName("localhost")] + san_ips
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ELI Local Server")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(k.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=825))
            .add_extension(x509.SubjectAlternativeName(san), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(k, hashes.SHA256()))
    crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_pem = k.private_bytes(serialization.Encoding.PEM,
                              serialization.PrivateFormat.TraditionalOpenSSL,
                              serialization.NoEncryption())
    try:
        from eli.core import secure_io
        secure_io.secure_write_bytes(str(key), key_pem, mode=0o600)
    except Exception:
        key.write_bytes(key_pem)
        try:
            os.chmod(str(key), 0o600)
        except Exception:
            pass
    return str(crt), str(key)


def _osc8(url: str, label: str | None = None) -> str:
    """Wrap a URL as an OSC 8 terminal hyperlink — Ctrl/Cmd-clickable in terminals that
    support them (GNOME Terminal, kitty, iTerm2, WezTerm, foot…). The label defaults to
    the URL itself, so it stays visible and copy-pasteable either way. (NB: `cat -v` and
    log files always show the raw escapes — that is NOT how a live terminal renders it.)"""
    label = label or url
    return f"\033]8;;{url}\033\\{label}\033]8;;\033\\"


def _open_browser_async(url: str, delay: float = 1.2) -> bool:
    """Open `url` in the default browser shortly after the server comes up, so you
    never have to click or copy anything. Returns True if a browser open was launched.
    Skipped only on a genuinely headless box (no desktop session at all) or when
    ELI_API_NO_BROWSER is set."""
    if os.environ.get("ELI_API_NO_BROWSER", "").strip().lower() in ("1", "true", "yes", "on"):
        return False
    # Only bail if there's clearly NO desktop session to open onto (real headless server).
    if _sys.platform.startswith("linux") and not any(
            os.environ.get(v) for v in
            ("DISPLAY", "WAYLAND_DISPLAY", "XDG_SESSION_TYPE", "XDG_CURRENT_DESKTOP")):
        return False

    def _launch():
        # Try every mechanism until one works — different desktops/confinements favour
        # different ones. webbrowser first (it returns True on success and is what worked
        # historically), then the OS "open" handlers.
        import shutil
        import subprocess
        plat = _sys.platform
        try:
            import webbrowser
            if webbrowser.open(url):
                return
        except Exception:
            pass
        try:
            if plat.startswith("linux"):
                for name in ("xdg-open", "gio", "sensible-browser", "gnome-open"):
                    opener = shutil.which(name)
                    if opener:
                        args = [opener, "open", url] if name == "gio" else [opener, url]
                        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        return
            elif plat == "darwin":
                subprocess.Popen(["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif plat.startswith("win"):
                os.startfile(url)  # type: ignore[attr-defined]
        except Exception:
            pass

    def _go():
        time.sleep(delay)          # let uvicorn finish binding first
        _launch()
    threading.Thread(target=_go, daemon=True).start()
    return True


def main():
    import argparse
    ap = argparse.ArgumentParser(
        prog="api.server",
        description="ELI local web server. Default: loopback only (same machine). "
                    "Use --lan to expose it to your phone / other devices on the Wi-Fi.")
    ap.add_argument("--lan", action="store_true",
                    help="bind 0.0.0.0 so other devices can reach it, require a token, "
                         "and print the ready-to-open phone URL")
    ap.add_argument("--host", default=None, help="bind host (overrides --lan / ELI_API_HOST)")
    ap.add_argument("--port", type=int, default=None, help="port (default 8081 / ELI_API_PORT)")
    ap.add_argument("--token", default=None,
                    help="API token to require (default: reuse ELI_API_TOKEN, else auto-generate)")
    ap.add_argument("--reload", action="store_true", help="uvicorn auto-reload (dev)")
    ap.add_argument("--https", action="store_true",
                    help="serve over HTTPS with a local self-signed cert — unlocks the phone "
                         "microphone (browsers block the mic on plain http://LAN-IP)")
    args, _ = ap.parse_known_args()

    # Precedence: explicit flag > --lan > env default. --lan means 0.0.0.0 unless --host given.
    host = args.host or ("0.0.0.0" if args.lan else os.environ.get("ELI_API_HOST", "127.0.0.1"))
    from eli.runtime.server_util import effective_api_port
    port = args.port or effective_api_port()  # --port > env > saved api_port setting > 8081
    reload = args.reload or os.environ.get("ELI_API_RELOAD", "0").strip().lower() in ("1", "true", "yes", "on")
    if args.token:
        os.environ["ELI_API_TOKEN"] = args.token
    # Record the actual bind host/port so the "Connect a phone" tab can tell whether the
    # server is reachable from the LAN (0.0.0.0) or loopback-only, and build the phone URL.
    os.environ["ELI_API_HOST"] = host
    os.environ["ELI_API_PORT"] = str(port)

    # Optional HTTPS for the phone MICROPHONE (getUserMedia is blocked on http://LAN-IP).
    # Key insight: a self-signed HTTPS URL is hostile to QR scanners (many refuse to open
    # it). So we keep PLAIN HTTP as the primary connect path — it opens on any phone — and,
    # when --https is on, run HTTPS ALONGSIDE on its own port purely for voice. The Connect
    # tab shows the HTTP QR to connect + an HTTPS link/QR to enable the mic.
    use_https = args.https or os.environ.get("ELI_API_HTTPS", "0").strip().lower() in ("1", "true", "yes", "on")
    https_port = None
    _crt = _key = None
    if use_https:
        try:
            _crt, _key = _ensure_lan_cert()
            https_port = int(os.environ.get("ELI_API_HTTPS_PORT", "8443"))
            os.environ["ELI_API_HTTPS_PORT"] = str(https_port)
        except Exception as _e:
            print(f"  HTTPS requested but cert setup failed ({_e}); HTTP only.", flush=True)
            use_https = False
            https_port = None
    os.environ["ELI_API_SCHEME"] = "http"  # primary is always HTTP (reliable phone-open)

    # The auth gate fails CLOSED by default; main() relaxes it for the two safe cases ONLY.
    if _is_loopback_host(host):
        os.environ.setdefault("ELI_API_ALLOW_TOKENLESS", "1")
        local_url = f"http://127.0.0.1:{port}/"
    else:
        os.environ.pop("ELI_API_ALLOW_TOKENLESS", None)
        token = _api_token()   # explicit --token / ELI_API_TOKEN env wins
        auto_generated = not token
        if auto_generated:
            # Use the PERSISTED stable token (saved 0600 under config_dir) so it stays the
            # SAME across restarts — otherwise every restart mints a fresh random token and
            # strands the already-paired phone (its QR/URL carries the old one → 401 →
            # "loads but not fully"). Rotate deliberately via the Connect tab.
            from api.api_token import get_stable_token
            token = get_stable_token()
            os.environ["ELI_API_TOKEN"] = token
        ip = _lan_ip()
        _bar = "=" * 72
        print(_bar, flush=True)
        print(f"  ELI web server on the LAN  ({host}:{port})", flush=True)
        local_url = f"http://127.0.0.1:{port}/#token={token}"
        print(f"  Phone — open the Connect tab and scan, or visit:", flush=True)
        print(f"      http://{ip}:{port}/#token={token}", flush=True)
        if https_port:
            print(f"  Phone microphone (voice) needs HTTPS — same Connect tab, or visit:", flush=True)
            print(f"      https://{ip}:{https_port}/#token={token}", flush=True)
            print("      (self-signed: accept the one-time 'not private' warning to use the mic)", flush=True)
        else:
            print("  Tip: add --https to also enable the phone microphone (voice).", flush=True)
        print(f"  Or send header:   Authorization: Bearer {token}", flush=True)
        if auto_generated:
            print("  (Stable token — saved locally, survives restarts so your phone stays paired.", flush=True)
            print("   Change it with the Connect tab's Rotate, or pass --token <secret>.)", flush=True)
        try:
            _fw = _firewall_hint()
            if _fw.get("commands"):
                print(f"  If a phone can't connect, your {_fw['tool']} firewall is likely "
                      f"blocking it — allow the port:", flush=True)
                for _c in _fw["commands"]:
                    print(f"      {_c}", flush=True)
        except Exception:
            pass
        print(_bar, flush=True)

    # Open-on-this-computer: a clickable link + auto-launch the local browser so you
    # never have to copy-paste the URL (set ELI_API_NO_BROWSER=1 to skip the launch).
    print(f"  On this computer:  {local_url}", flush=True)
    if _open_browser_async(local_url):
        print("  (opening it in your browser now — Ctrl-click or copy the URL above if it doesn't)",
              flush=True)
    else:
        print("  (copy the URL above into your browser)", flush=True)

    # Run HTTPS (voice) alongside on its own port, in a daemon thread.
    if https_port and _crt and _key:
        import threading
        _hsrv = uvicorn.Server(uvicorn.Config(
            "api.server:app", host=host, port=https_port, log_level="warning",
            ssl_certfile=_crt, ssl_keyfile=_key))
        threading.Thread(target=_hsrv.run, daemon=True).start()
    uvicorn.run("api.server:app", host=host, port=port, reload=reload, log_level="info")

if __name__ == "__main__":
    main()
