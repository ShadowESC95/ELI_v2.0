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
from typing import Optional, Any
import json
import os
import secrets
import time
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


from typing import NamedTuple


class Principal(NamedTuple):
    """The authenticated caller: a user id and a role (admin | member)."""
    user_id: str
    role: str


def _bearer(authorization: str) -> str:
    a = (authorization or "").strip()
    return a[7:].strip() if a.lower().startswith("bearer ") else ""


def _resolve_principal(authorization: str) -> Optional[Principal]:
    """Resolve a request to an authenticated Principal, or None (→ 401).

    RBAC mode (one or more users defined): the bearer token maps to a (user_id, role).
    Single-operator mode (no users): the legacy ELI_API_TOKEN — or a loopback bind with
    tokenless allowed — authenticates the local 'operator' as admin (back-compatible)."""
    token = _bearer(authorization)
    try:
        from eli.runtime import api_users
        if api_users.rbac_enabled():
            rec = api_users.resolve_token(token)
            if rec:
                return Principal(rec["user_id"], rec["role"])
            # No matching token. The LOOPBACK operator (no token + tokenless allowed,
            # which main() enables only on a loopback bind) is the machine owner — keep
            # them admin so they can manage users / never lock themselves out. A LAN
            # client (no tokenless) with no/invalid token still fails closed.
            if not token and _tokenless_allowed():
                return Principal("operator", "admin")
            return None
    except Exception:
        pass  # store unreadable → fall through to single-operator mode (fail-closed below)
    configured = _api_token()
    if configured:
        if token and secrets.compare_digest(token, configured):
            return Principal("operator", "admin")
        return None
    if _tokenless_allowed():
        return Principal("operator", "admin")
    return None


# Privilege hierarchy: viewer (read-only) < member (acts) < admin (console + user mgmt).
_ROLE_RANK = {"viewer": 0, "member": 1, "admin": 2}


def _rank(role: str) -> int:
    return _ROLE_RANK.get((role or "").strip().lower(), 0)  # unknown role → least privilege


def _authenticated(authorization: str) -> Principal:
    """Fail-CLOSED: resolve to a Principal or 401. The default — no token, no opt-out —
    is DENY, so a raw `uvicorn api.server:app` stays locked down regardless of main()."""
    p = _resolve_principal(authorization)
    if p is None:
        raise HTTPException(
            status_code=401,
            detail="API token required (set ELI_API_TOKEN or define a user; for "
                   "same-machine use launch via scripts/eli_serve.sh)",
        )
    return p


def require_viewer(authorization: str = Header(default="")) -> Principal:
    """Read-only level — any authenticated caller (viewer, member, or admin)."""
    return _authenticated(authorization)


def require_member(authorization: str = Header(default="")) -> Principal:
    """Acting level — member or admin. A read-only viewer is 403'd from mutating actions."""
    p = _authenticated(authorization)
    if _rank(p.role) < _ROLE_RANK["member"]:
        raise HTTPException(status_code=403, detail="member role required (read-only viewer)")
    return p


def require_admin(authorization: str = Header(default="")) -> Principal:
    """Admin level — the Admin console + user management."""
    p = _authenticated(authorization)
    if _rank(p.role) < _ROLE_RANK["admin"]:
        raise HTTPException(status_code=403, detail="admin role required")
    return p


def _require_token(authorization: str = Header(default="")):
    """Read-level dependency (kept as the name read-only endpoints already reference) —
    permits any authenticated caller, including a viewer."""
    require_viewer(authorization)


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

# Minimal, dependency-free, mobile-first chat UI. Served at "/". Lets any device
# with a browser (Android/iOS/desktop) talk to a self-hosted ELI over the network —
# inference stays on the host running this server (no on-device model build needed).
_WEB_UI = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, viewport-fit=cover">
<title>ELI</title>
<link rel="manifest" href="/manifest.webmanifest">
<meta name="theme-color" content="#05070d">
<link rel="icon" href="/icon.svg"><link rel="apple-touch-icon" href="/icon.svg">
<meta name="apple-mobile-web-app-capable" content="yes"><meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<script>try{if(localStorage.getItem('eli_theme')==='light')document.documentElement.setAttribute('data-theme','light');}catch(e){}</script>
<style>
  :root {
    color-scheme: dark;
    --bg:#05070d; --bg2:#080b14; --grid:rgba(34,211,238,.05);
    --card:rgba(13,20,33,.62); --card2:rgba(20,28,44,.55); --line:rgba(64,224,255,.15); --input:rgba(7,12,22,.72);
    --fg:#dbeafe; --fg-dim:#8aa4c8; --mut:#5b6b86;
    --accent:#22d3ee; --accent2:#f637ec; --accent-press:#06b6d4; --teal:#22d3ee;
    --glow:0 0 0 1px rgba(34,211,238,.3), 0 0 18px rgba(34,211,238,.2);
    --ok:#34f5c5; --warn:#ffd166; --bad:#ff5d73;
    --radius:14px; --radius-sm:10px; --shadow:0 2px 10px rgba(0,0,0,.5), 0 14px 44px rgba(0,0,0,.42);
    --fast:.18s cubic-bezier(.4,0,.2,1); --mono:ui-monospace,"JetBrains Mono",Menlo,Consolas,monospace;
  }
  [data-theme="light"] {
    color-scheme: light;
    --bg:#eef3fb; --bg2:#e6edf7; --grid:rgba(8,145,178,.06);
    --card:rgba(255,255,255,.82); --card2:#f4f8fd; --line:rgba(8,145,178,.22); --input:#eef4fb;
    --fg:#0c1828; --fg-dim:#3f5168; --mut:#7589a3;
    --accent:#0891b2; --accent2:#be1d8f; --accent-press:#0e7490; --teal:#0891b2;
    --glow:0 0 0 1px rgba(8,145,178,.25); --ok:#059669; --warn:#b45309; --bad:#dc2626;
    --shadow:0 1px 2px rgba(20,30,60,.06), 0 10px 30px rgba(20,30,60,.1);
  }
  * { box-sizing: border-box; }
  body { margin:0; font-family: ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
    color:var(--fg); height:100dvh; display:flex; overflow:hidden; -webkit-font-smoothing:antialiased;
    background:
      radial-gradient(1100px 560px at 82% -12%, rgba(34,211,238,.08), transparent 60%),
      radial-gradient(900px 520px at -12% 112%, rgba(246,55,236,.06), transparent 60%),
      linear-gradient(var(--grid) 1px, transparent 1px) 0 0/34px 34px,
      linear-gradient(90deg, var(--grid) 1px, transparent 1px) 0 0/34px 34px,
      var(--bg);
    transition:background var(--fast),color var(--fast); }
  /* ── sidebar shell ── */
  .sidebar { width:214px; flex:none; display:flex; flex-direction:column; gap:4px; padding:14px 12px;
    background:linear-gradient(180deg, rgba(10,16,28,.72), rgba(6,10,18,.5)); border-right:1px solid var(--line); backdrop-filter:blur(16px); }
  .brand { display:flex; align-items:baseline; gap:9px; padding:4px 8px 14px; }
  .brand .logo { font-family:var(--mono); color:var(--accent); font-weight:800; font-size:16px; text-shadow:0 0 14px var(--accent); }
  .brand b { font-weight:800; letter-spacing:3px; font-size:19px; background:linear-gradient(90deg,var(--accent),var(--accent2)); -webkit-background-clip:text; background-clip:text; -webkit-text-fill-color:transparent; }
  .brand small { color:var(--mut); font-size:10px; letter-spacing:1.5px; text-transform:uppercase; }
  nav.tabs { display:flex; flex-direction:column; gap:3px; flex:1; min-height:0; overflow-y:auto; scrollbar-width:none; }
  nav.tabs::-webkit-scrollbar { display:none; }
  nav.tabs button { display:flex; align-items:center; gap:11px; padding:10px 12px; border:0; border-radius:10px;
    background:transparent; color:var(--fg-dim); font-size:13.5px; font-weight:500; cursor:pointer; text-align:left;
    position:relative; transition:var(--fast); letter-spacing:.3px; white-space:nowrap; }
  nav.tabs button svg { width:17px; height:17px; flex:none; opacity:.75; transition:var(--fast); }
  nav.tabs button:hover { color:var(--fg); background:rgba(34,211,238,.07); }
  nav.tabs button.active { color:var(--accent); background:linear-gradient(90deg, rgba(34,211,238,.16), transparent);
    box-shadow:inset 0 0 0 1px rgba(34,211,238,.28); text-shadow:0 0 12px rgba(34,211,238,.55); }
  nav.tabs button.active::before { content:""; position:absolute; left:0; top:18%; bottom:18%; width:3px; border-radius:0 3px 3px 0; background:var(--accent); box-shadow:0 0 12px var(--accent); }
  nav.tabs button.active svg { opacity:1; filter:drop-shadow(0 0 5px var(--accent)); }
  .sidefoot { display:flex; align-items:center; gap:8px; padding-top:11px; margin-top:2px; border-top:1px solid var(--line); }
  .sidefoot #rolebadge { flex:1; color:var(--mut); font-size:11px; letter-spacing:.4px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .iconbtn { width:34px; height:34px; border:1px solid var(--line); border-radius:9px; background:var(--input); color:var(--fg-dim); font-size:15px; cursor:pointer; display:grid; place-items:center; transition:var(--fast); flex:none; }
  .iconbtn:hover { color:var(--accent); border-color:var(--accent); box-shadow:var(--glow); }
  .main { flex:1; min-width:0; display:flex; flex-direction:column; }
  .view { flex:1; min-height:0; display:none; flex-direction:column; }
  .view.active { display:flex; animation:fade .25s ease; }
  @keyframes fade { from{opacity:0;transform:translateY(6px);} to{opacity:1;transform:none;} }
  @media (max-width:720px){
    body{ flex-direction:column-reverse; }
    .sidebar{ width:100%; flex-direction:row; gap:2px; padding:6px; overflow-x:auto; border-right:0; border-top:1px solid var(--line); backdrop-filter:blur(16px); }
    .brand,.sidefoot{ display:none; }
    nav.tabs{ flex-direction:row; }
    nav.tabs button{ flex-direction:column; gap:3px; padding:7px 10px; font-size:10px; }
    nav.tabs button.active::before{ left:18%; right:18%; top:0; bottom:auto; width:auto; height:3px; border-radius:0 0 3px 3px; }
  }
  #log { flex:1; overflow-y:auto; padding:16px; display:flex; flex-direction:column; gap:10px; }
  #log { scroll-behavior:smooth; }
  .msg { max-width:80%; padding:11px 14px; border-radius:16px; white-space:pre-wrap; line-height:1.5; font-size:15px; box-shadow:var(--shadow); animation:pop .18s ease; }
  @keyframes pop { from{opacity:0;transform:translateY(6px) scale(.98);} to{opacity:1;transform:none;} }
  .user { align-self:flex-end; background:var(--ubub,linear-gradient(135deg,var(--accent),var(--accent-press))); color:#fff; border-bottom-right-radius:5px; }
  .eli  { align-self:flex-start; background:var(--card); border:1px solid var(--line); border-bottom-left-radius:5px; }
  .meta { font-size:11px; color:var(--mut); align-self:center; }
  form#f { display:flex; gap:8px; padding:12px 14px; border-top:1px solid var(--line); background:var(--bg2); }
  #box { flex:1; padding:13px 14px; border-radius:12px; border:1px solid var(--line); background:var(--input); color:var(--fg); font-size:16px; transition:var(--fast); }
  #box:focus { outline:none; border-color:var(--accent); box-shadow:0 0 0 3px rgba(59,130,246,.18); }
  form#f #send { padding:0 20px; border:0; border-radius:12px; background:var(--sendc,var(--accent)); color:#fff; font-size:16px; font-weight:600; cursor:pointer; transition:var(--fast); }
  form#f #send:hover:not(:disabled) { filter:brightness(1.1); }
  form#f #send:disabled { opacity:.45; cursor:not-allowed; }
  form#f button:disabled { opacity:.45; cursor:not-allowed; }
  #mic { padding:0 14px; border:1px solid var(--line); border-radius:10px; background:var(--micc,var(--input)); color:var(--micfg,var(--fg)); font-size:18px; cursor:pointer; transition:var(--fast); }
  #mic.rec { background:#b42a2a; border-color:#b42a2a; color:#fff; animation:pulse 1.1s infinite; }
  @keyframes pulse { 0%,100%{opacity:1;} 50%{opacity:.55;} }
  .voicebar { display:flex; align-items:center; gap:12px; padding:0 12px 10px; font-size:13px; color:var(--mut); }
  .voicebar .spk { display:flex; align-items:center; gap:6px; cursor:pointer; }
  .voicebar #vstat { color:var(--teal); }
  .chatbar { display:flex; gap:8px; align-items:center; padding:10px 14px; border-bottom:1px solid var(--line); background:var(--bg2); }
  .chatbar select { flex:1; min-width:0; padding:8px 10px; border-radius:9px; border:1px solid var(--line); background:var(--input); color:var(--fg); font-size:13px; }
  .cbtn { padding:8px 12px; border:1px solid var(--line); border-radius:9px; background:var(--card); color:var(--fg-dim); font-size:13px; cursor:pointer; transition:var(--fast); white-space:nowrap; }
  .cbtn:hover { color:var(--fg); border-color:var(--teal); }
  form#f button.stop { background:var(--bad); }
  .typing { display:inline-flex; gap:4px; padding:3px 0; }
  .typing i { width:7px; height:7px; border-radius:50%; background:var(--fg-dim); display:inline-block; animation:blink 1.2s infinite; }
  .typing i:nth-child(2){animation-delay:.2s;} .typing i:nth-child(3){animation-delay:.4s;}
  @keyframes blink { 0%,80%,100%{opacity:.25;transform:translateY(0);} 40%{opacity:1;transform:translateY(-3px);} }
  .msg .mh { margin:.5em 0 .3em; font-size:1.05em; font-weight:700; }
  .msg .ml { margin:.3em 0; padding-left:1.3em; } .msg .ml li { margin:.15em 0; }
  .msg a { color:var(--teal); }
  .msg .ic { background:var(--input); border:1px solid var(--line); border-radius:5px; padding:1px 5px; font-family:ui-monospace,Menlo,Consolas,monospace; font-size:.92em; }
  .cb { margin:8px 0; border:1px solid var(--line); border-radius:10px; overflow:hidden; background:var(--input); }
  .cb .cbh { display:flex; justify-content:space-between; align-items:center; padding:5px 10px; background:rgba(127,127,127,.1); font-size:11px; color:var(--mut); }
  .cb .cpy { border:0; background:transparent; color:var(--teal); font-size:11px; cursor:pointer; }
  .cb pre { margin:0; padding:11px 12px; overflow-x:auto; } .cb code { font-family:ui-monospace,Menlo,Consolas,monospace; font-size:13px; line-height:1.5; color:var(--fg); }
  #commands, #home { overflow-y:auto; padding:14px; }
  #cmdsearch { width:100%; padding:11px 13px; border-radius:10px; border:1px solid var(--line); background:var(--input); color:var(--fg); font-size:15px; margin-bottom:12px; }
  .cat h3 { margin:18px 0 8px; font-size:13px; text-transform:uppercase; letter-spacing:.6px; color:var(--teal); }
  .cmd { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:11px 13px; margin-bottom:8px; }
  .cmd .act { font-weight:600; font-size:13px; }
  .cmd .desc { color:var(--fg-dim); font-size:13px; margin:3px 0 7px; }
  .chips { display:flex; flex-wrap:wrap; gap:6px; }
  .chip { font-size:12px; padding:4px 9px; border-radius:14px; background:var(--input); border:1px solid var(--line); color:var(--fg-dim); cursor:pointer; }
  .chip:hover { border-color:var(--teal); color:#fff; }
  .hconfig { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:16px; max-width:520px; margin:8px auto; }
  .hconfig h3 { margin:0 0 4px; } .hconfig p { color:var(--mut); font-size:13px; margin:0 0 14px; }
  .hconfig label { display:block; font-size:13px; color:var(--fg-dim); margin:10px 0 4px; }
  .hconfig input { width:100%; padding:10px; border-radius:9px; border:1px solid var(--line); background:var(--input); color:var(--fg); font-size:14px; }
  .hconfig button { margin-top:14px; padding:10px 18px; border:0; border-radius:9px; background:var(--accent); color:#fff; font-size:15px; cursor:pointer; }
  .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(168px,1fr)); gap:12px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:16px; padding:14px; display:flex; flex-direction:column; gap:10px; min-height:120px; box-shadow:var(--shadow); backdrop-filter:blur(12px); transition:transform var(--fast),border-color var(--fast),box-shadow var(--fast); }
  .card:hover { transform:translateY(-3px); border-color:var(--accent); box-shadow:var(--shadow),var(--glow); }
  .card .nm { font-size:14px; font-weight:600; } .card .dom { font-size:11px; color:var(--mut); text-transform:uppercase; letter-spacing:.5px; }
  .card .row { display:flex; align-items:center; justify-content:space-between; margin-top:auto; }
  .st { font-size:13px; color:var(--fg-dim); }
  .sw { position:relative; width:46px; height:26px; flex:none; }
  .sw input { opacity:0; width:0; height:0; }
  .sw span { position:absolute; inset:0; background:#3a3d45; border-radius:26px; transition:.2s; cursor:pointer; }
  .sw span:before { content:""; position:absolute; height:20px; width:20px; left:3px; top:3px; background:#fff; border-radius:50%; transition:.2s; }
  .sw input:checked + span { background:var(--teal); }
  .sw input:checked + span:before { transform:translateX(20px); }
  .gauge { width:84px; height:84px; border-radius:50%; margin:0 auto; display:grid; place-items:center; background:conic-gradient(var(--teal) calc(var(--p)*1%), #2a2d35 0); }
  .gauge i { width:64px; height:64px; border-radius:50%; background:var(--card); display:grid; place-items:center; font-size:16px; font-weight:600; font-style:normal; }
  .err { color:var(--bad); font-size:13px; padding:10px; } .muted { color:var(--mut); font-size:13px; text-align:center; padding:30px; }
  .modal { position:fixed; inset:0; background:rgba(0,0,0,.55); backdrop-filter:blur(5px); display:none; align-items:center; justify-content:center; z-index:50; }
  .modal.show { display:flex; animation:fade .2s ease; }
  .modal .sheet { background:var(--card2); border:1px solid var(--line); border-radius:18px; padding:22px; width:min(440px,92vw); box-shadow:var(--shadow); }
  .modal h3 { margin:0 0 4px; font-size:16px; } .modal .sub { color:var(--mut); font-size:12px; margin-bottom:16px; }
  .crow { margin-bottom:15px; } .crow .cl { font-size:12px; color:var(--fg-dim); margin-bottom:8px; }
  .sw-list { display:flex; flex-wrap:wrap; gap:7px; align-items:center; }
  .sw { width:25px; height:25px; border-radius:7px; cursor:pointer; border:2px solid transparent; transition:var(--fast); }
  .sw:hover { transform:scale(1.15); }
  .sw.sel { border-color:var(--fg); box-shadow:0 0 0 2px var(--card2), 0 0 12px currentColor; }
  .sw.custom { background:var(--input); display:grid; place-items:center; color:var(--fg-dim); font-size:13px; position:relative; overflow:hidden; }
  .sw.custom input { position:absolute; inset:0; opacity:0; cursor:pointer; }
  .modal .mfoot { display:flex; justify-content:space-between; margin-top:8px; }
  .modal .mbtn { padding:9px 16px; border:1px solid var(--line); border-radius:10px; background:var(--input); color:var(--fg); font-size:13px; cursor:pointer; }
  .modal .mbtn.primary { background:var(--accent); border-color:var(--accent); color:#04121a; font-weight:600; }
  .banner { border-radius:10px; padding:10px 13px; font-size:13px; }
  .banner.bad { background:rgba(248,113,113,.12); border:1px solid var(--bad); color:var(--bad); }
  .banner.ok { background:rgba(52,211,153,.12); border:1px solid var(--ok); color:var(--ok); }
  a.link, .link { color:var(--teal); cursor:pointer; }
  input[type=range] { width:100%; accent-color:var(--teal); margin-top:4px; }
  .media { display:flex; gap:6px; justify-content:center; }
  .media button { background:var(--input); border:1px solid var(--line); color:var(--fg); border-radius:8px; padding:6px 9px; font-size:15px; cursor:pointer; }
  .clim { display:flex; align-items:center; justify-content:space-between; }
  .clim button { width:32px; height:32px; border-radius:8px; border:1px solid var(--line); background:var(--input); color:var(--fg); font-size:18px; cursor:pointer; }
  .bar { height:8px; border-radius:6px; background:#2a2d35; overflow:hidden; margin-top:4px; }
  .bar i { display:block; height:100%; background:var(--teal); }
  .syscard { background:var(--card); border:1px solid var(--line); border-radius:16px; padding:16px; box-shadow:var(--shadow); backdrop-filter:blur(12px); margin-bottom:14px; position:relative; }
  .syscard::before { content:""; position:absolute; left:14px; right:14px; top:0; height:1px; background:linear-gradient(90deg,transparent,var(--accent),transparent); opacity:.5; }
  .syscard h4 { margin:0 0 12px; font-size:11px; color:var(--accent); text-transform:uppercase; letter-spacing:1.5px; font-family:var(--mono); text-shadow:0 0 10px rgba(34,211,238,.4); }
  .kv { display:flex; justify-content:space-between; font-size:13px; margin:6px 0; color:var(--fg-dim); }
  .glabel { text-align:center; font-size:11px; color:var(--mut); margin-top:4px; }
  #research { overflow-y:auto; padding:14px; }
  .rwrap { max-width:760px; margin:0 auto; }
  .rsec { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:16px; margin-bottom:14px; }
  .rsec h4 { margin:0 0 10px; font-size:12px; color:var(--teal); text-transform:uppercase; letter-spacing:.5px; }
  .rrow { display:flex; gap:8px; margin:8px 0; flex-wrap:wrap; }
  .rrow input, .rrow select { flex:1; min-width:140px; padding:10px; border-radius:9px; border:1px solid var(--line); background:var(--input); color:var(--fg); font-size:14px; }
  .rrow button { padding:10px 16px; border:0; border-radius:9px; background:var(--accent); color:#fff; font-size:14px; cursor:pointer; }
  .rrow button:disabled { opacity:.5; }
  .answer { background:var(--input); border:1px solid var(--line); border-radius:10px; padding:13px; white-space:pre-wrap; line-height:1.5; font-size:14px; margin-top:6px; }
  .src { background:var(--input); border:1px solid var(--line); border-radius:9px; padding:9px 11px; margin-top:7px; font-size:13px; }
  .src .sh { display:flex; justify-content:space-between; color:var(--teal); font-weight:600; margin-bottom:4px; }
  .src .sx { color:var(--fg-dim); }
  .rnote { font-size:12px; color:var(--mut); margin-top:6px; }
  #audit { overflow-y:auto; padding:14px; }
  .awrap { max-width:880px; margin:0 auto; }
  .abadge { border-radius:12px; padding:12px 16px; margin-bottom:14px; font-size:14px; display:flex; align-items:center; gap:10px; }
  .abadge.ok { background:#10331f; border:1px solid #1f7a44; color:#7ee2a8; }
  .abadge.bad { background:#3a1414; border:1px solid #b42a2a; color:#f8a0a0; }
  .abadge .dot { width:10px; height:10px; border-radius:50%; flex:none; }
  .abadge.ok .dot { background:#22c55e; } .abadge.bad .dot { background:#ef4444; }
  .arow { display:grid; grid-template-columns:128px 1fr 84px; gap:10px; padding:9px 11px; border:1px solid var(--line); border-radius:9px; background:var(--card); margin-bottom:6px; font-size:13px; align-items:center; }
  .arow .at { color:var(--mut); font-size:12px; } .arow .aa { font-weight:600; }
  .arow .au { color:var(--teal); font-size:12px; } .arow .as { color:var(--fg-dim); font-size:12px; }
  .arow .ao { text-align:right; font-size:12px; }
  .arow .ao.ok { color:#7ee2a8; } .arow .ao.failed, .arow .ao.error { color:#f8a0a0; }
  .afilter { display:flex; gap:8px; margin-bottom:12px; }
  .afilter input { flex:1; padding:9px 11px; border-radius:9px; border:1px solid var(--line); background:var(--input); color:var(--fg); font-size:13px; }
  .afilter button { padding:9px 14px; border:0; border-radius:9px; background:var(--accent); color:#fff; font-size:13px; cursor:pointer; }
  .roomsec { margin-top:16px; }
  .roomhd { display:flex; align-items:center; gap:9px; margin:6px 2px 9px; }
  .roomnm { font-size:13px; font-weight:700; color:var(--teal); text-transform:uppercase; letter-spacing:.5px; }
  .roomct { font-size:11px; color:var(--mut); background:var(--input); border:1px solid var(--line); border-radius:10px; padding:1px 8px; }
  .roombtn { font-size:12px; padding:5px 11px; border:1px solid var(--line); border-radius:8px; background:var(--input); color:var(--fg-dim); cursor:pointer; }
  /* ── JARVIS sub-tab framework + command-console chrome ───────────────── */
  .subwrap { margin-top:4px; }
  .subtabs { display:flex; gap:2px; border-bottom:1px solid var(--line); margin-bottom:16px; overflow-x:auto; scrollbar-width:none; position:relative; }
  .subtabs::-webkit-scrollbar { display:none; }
  .subtab { position:relative; background:transparent; border:0; color:var(--fg-dim); font-family:var(--mono); font-size:12px; letter-spacing:1.2px; text-transform:uppercase; padding:11px 16px 12px; cursor:pointer; white-space:nowrap; transition:var(--fast); }
  .subtab:hover { color:var(--fg); }
  .subtab.active { color:var(--accent); text-shadow:0 0 12px rgba(34,211,238,.5); }
  .subtab.active::after { content:""; position:absolute; left:8px; right:8px; bottom:-1px; height:2px; background:linear-gradient(90deg,transparent,var(--accent),transparent); box-shadow:0 0 12px var(--accent); animation:subglow 2.4s ease-in-out infinite; }
  @keyframes subglow { 0%,100%{opacity:.7} 50%{opacity:1} }
  .subbody { animation:fadein .25s ease; }
  @keyframes fadein { from{opacity:0;transform:translateY(4px)} to{opacity:1;transform:none} }
  /* Live status strip — the mission-control header */
  .livestrip { display:flex; flex-wrap:wrap; gap:10px; align-items:center; padding:12px 16px; margin-bottom:14px; border-radius:14px;
    background:linear-gradient(120deg,rgba(13,20,33,.85),rgba(20,28,44,.6)); border:1px solid var(--line); position:relative; overflow:hidden; box-shadow:var(--shadow); }
  .livestrip::before { content:""; position:absolute; inset:0; background:repeating-linear-gradient(90deg,transparent,transparent 38px,var(--grid) 38px,var(--grid) 39px); pointer-events:none; }
  .lspill { display:flex; align-items:center; gap:7px; font-size:12.5px; font-family:var(--mono); color:var(--fg); padding:5px 12px; border-radius:20px; background:rgba(7,12,22,.55); border:1px solid var(--line); position:relative; z-index:1; }
  .lspill b { color:var(--accent); font-weight:700; }
  .lspill .ld { width:8px; height:8px; border-radius:50%; background:var(--accent); box-shadow:0 0 8px var(--accent); }
  .lspill .ld.warn { background:#e0a72e; box-shadow:0 0 8px #e0a72e; }
  .lspill .ld.off { background:var(--mut); box-shadow:none; }
  .lspill .ld.live { animation:pulse 1.8s ease-in-out infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.35} }
  .lstitle { font-family:var(--mono); font-size:11px; letter-spacing:2px; text-transform:uppercase; color:var(--accent); text-shadow:0 0 10px rgba(34,211,238,.4); margin-right:4px; z-index:1; }
  /* Futuristic section header with accent bar */
  .jhead { display:flex; align-items:center; gap:10px; margin:18px 0 10px; font-family:var(--mono); font-size:12px; letter-spacing:1.6px; text-transform:uppercase; color:var(--fg-dim); }
  .jhead::before { content:""; width:3px; height:14px; background:var(--accent); border-radius:2px; box-shadow:0 0 10px var(--accent); }
  .jhead::after { content:""; flex:1; height:1px; background:linear-gradient(90deg,var(--line),transparent); }
  .grid .card { transition:var(--fast); }
  .grid .card:hover { border-color:var(--accent); box-shadow:0 0 0 1px rgba(34,211,238,.25),0 8px 26px rgba(0,0,0,.4); }
  .roombtn:hover { border-color:var(--teal); color:#fff; }
  .roomhd .roombtn:first-of-type { margin-left:auto; }
  #overview { overflow-y:auto; padding:20px; }
  .ovwrap { max-width:1120px; margin:0 auto; }
  .ovhero { display:flex; gap:22px; flex-wrap:wrap; align-items:center; margin-bottom:18px; padding:18px 20px; border:1px solid var(--line); border-radius:18px; background:var(--card); box-shadow:var(--shadow); backdrop-filter:blur(12px); }
  .clock .t { font-family:var(--mono); font-size:48px; font-weight:700; letter-spacing:3px; color:var(--accent); text-shadow:0 0 24px rgba(34,211,238,.55); line-height:1; }
  .clock .d { color:var(--fg-dim); font-size:12px; margin-top:7px; letter-spacing:2px; text-transform:uppercase; }
  .ovstat { flex:1; min-width:240px; display:flex; flex-direction:column; gap:8px; }
  .ovstat-row { font-size:13px; color:var(--fg-dim); display:flex; align-items:center; gap:9px; }
  .dot { width:9px; height:9px; border-radius:50%; flex:none; }
  .dot.ok { background:var(--ok); box-shadow:0 0 10px var(--ok); }
  .dot.bad { background:var(--bad); box-shadow:0 0 10px var(--bad); animation:pulse 1.1s infinite; }
  .dot.warn { background:#f59e0b; box-shadow:0 0 10px #f59e0b; }
  .netrow { display:flex; align-items:center; gap:12px; }
  .netstate { font-family:var(--mono); font-size:12px; font-weight:700; letter-spacing:1px; padding:4px 10px; border-radius:8px; }
  .netstate.on { color:#f59e0b; background:rgba(245,158,11,.13); border:1px solid rgba(245,158,11,.4); }
  .netstate.off { color:var(--ok); background:rgba(34,197,94,.10); border:1px solid rgba(34,197,94,.32); }
  .netbtn { margin-left:auto; cursor:pointer; font-size:12px; font-weight:600; padding:7px 14px; border-radius:9px; border:1px solid var(--line); background:var(--bg2); color:var(--fg); }
  .netbtn.off:not([disabled]):hover { border-color:#f59e0b; color:#f59e0b; }
  .netbtn.on:not([disabled]):hover { border-color:var(--ok); color:var(--ok); }
  .netbtn[disabled] { opacity:.45; cursor:not-allowed; }
  .netegress { margin-top:8px; font-family:var(--mono); font-size:11px; color:var(--fg-dim); word-break:break-all; }
  .ov-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:14px; }
  .widget { background:var(--card); border:1px solid var(--line); border-radius:16px; padding:16px; box-shadow:var(--shadow); backdrop-filter:blur(12px); }
  .widget.wide { grid-column:1/-1; }
  .widget h4 { margin:0 0 14px; font-size:11px; color:var(--accent); text-transform:uppercase; letter-spacing:1.5px; font-family:var(--mono); }
  .ovgauges { display:flex; gap:16px; flex-wrap:wrap; justify-content:space-around; }
  .ovg { text-align:center; }
  .ring { width:76px; height:76px; border-radius:50%; display:grid; place-items:center; background:conic-gradient(var(--accent) calc(var(--p)*1%), rgba(127,127,127,.13) 0); box-shadow:0 0 18px rgba(34,211,238,.22); }
  .ring span { width:58px; height:58px; border-radius:50%; background:var(--bg2); display:grid; place-items:center; font-weight:700; font-family:var(--mono); color:var(--fg); font-size:16px; }
  .ovg-l { font-size:11px; color:var(--mut); margin-top:7px; text-transform:uppercase; letter-spacing:.5px; }
  .qa { display:flex; flex-wrap:wrap; gap:8px; }
  .qchip { padding:9px 13px; border:1px solid var(--line); border-radius:10px; background:var(--input); color:var(--fg-dim); font-size:13px; cursor:pointer; transition:var(--fast); }
  .qchip:hover { color:var(--accent); border-color:var(--accent); box-shadow:var(--glow); }
  .ovact { display:grid; grid-template-columns:1fr auto auto; gap:14px; align-items:center; padding:8px 4px; border-bottom:1px solid var(--line); font-size:13px; }
  .ovact:last-child { border-bottom:0; }
  .ovact .aa { font-weight:600; } .ovact .au { color:var(--teal); font-size:12px; font-family:var(--mono); } .ovact .at { color:var(--mut); font-size:12px; }
  #admin { overflow-y:auto; padding:14px; }
  .adwrap { max-width:900px; margin:0 auto; }
  .adtot { display:grid; grid-template-columns:repeat(auto-fit,minmax(120px,1fr)); gap:10px; margin-bottom:14px; }
  .adtot .syscard { text-align:center; }
  .adtot .big { font-size:26px; font-weight:700; color:var(--fg); }
  .adtot .lbl { font-size:11px; color:var(--mut); text-transform:uppercase; letter-spacing:.5px; margin-top:4px; }
  .urow { display:grid; grid-template-columns:1fr 70px 70px 150px; gap:10px; align-items:center; padding:9px 11px; border:1px solid var(--line); border-radius:9px; background:var(--card); margin-bottom:6px; font-size:13px; cursor:pointer; }
  .urow:hover { border-color:var(--teal); }
  .urow .un { font-weight:600; } .urow .uf.bad { color:#f8a0a0; } .urow .ut { color:var(--mut); font-size:12px; text-align:right; }
  .uhdr { display:grid; grid-template-columns:1fr 70px 70px 150px; gap:10px; padding:4px 11px; font-size:11px; color:var(--mut); text-transform:uppercase; letter-spacing:.5px; }
  .pol { display:flex; flex-wrap:wrap; gap:6px; margin:6px 0 10px; }
  .pol .tag { font-size:12px; padding:4px 10px; border-radius:14px; border:1px solid var(--line); }
  .pol .tag.auto { background:#10331f; border-color:#1f7a44; color:#7ee2a8; }
  .pol .tag.manual { background:#3a2a14; border-color:#a06a2a; color:#ebcb8b; }
  .emrow { display:grid; grid-template-columns:160px 1fr; gap:10px; padding:6px 11px; font-size:13px; border-bottom:1px solid #20242c; }
  .emrow .em { color:var(--teal); font-weight:600; } .emrow .ec { color:var(--fg-dim); font-size:12px; }
  /* ════ ELEVATED HOME — state-reactive neon device cards + console chrome ════ */
  .grid { gap:14px; }
  .card { background:linear-gradient(158deg,rgba(22,32,52,.72),rgba(9,14,26,.66)); border:1px solid var(--line); border-radius:18px; padding:15px 16px; position:relative; overflow:hidden; }
  .card::after { content:""; position:absolute; left:14px; right:14px; top:0; height:1px; background:linear-gradient(90deg,transparent,rgba(180,240,255,.22),transparent); }
  .card.on { border-color:rgba(34,211,238,.5); box-shadow:0 0 0 1px rgba(34,211,238,.22),0 0 26px rgba(34,211,238,.16),0 12px 30px rgba(0,0,0,.45); }
  .card.on::before { content:""; position:absolute; left:0; top:14px; bottom:14px; width:3px; border-radius:0 3px 3px 0; background:var(--accent); box-shadow:0 0 14px var(--accent); }
  .card.off { opacity:.78; }
  .chead { display:flex; align-items:center; gap:11px; }
  .cmeta { min-width:0; } .card .nm { font-size:14px; font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .dicon { width:38px; height:38px; flex:none; display:grid; place-items:center; font-size:18px; border-radius:11px; background:rgba(6,11,20,.65); border:1px solid var(--line); color:var(--fg-dim); transition:var(--fast); }
  .card.on .dicon { color:var(--accent); border-color:rgba(34,211,238,.5); box-shadow:0 0 16px rgba(34,211,238,.32); text-shadow:0 0 12px var(--accent); }
  .card .st { font-family:var(--mono); font-size:11px; letter-spacing:1.3px; text-transform:uppercase; color:var(--mut); }
  .card.on .st { color:var(--accent); text-shadow:0 0 10px rgba(34,211,238,.4); }
  .sw { position:relative; width:48px; height:27px; flex:none; }
  .sw input { opacity:0; width:0; height:0; }
  .sw span { position:absolute; inset:0; background:rgba(6,11,20,.85); border:1px solid var(--line); border-radius:27px; transition:.28s cubic-bezier(.4,0,.2,1); cursor:pointer; }
  .sw span:before { content:""; position:absolute; height:19px; width:19px; left:3px; top:3px; background:#79889e; border-radius:50%; transition:.28s cubic-bezier(.4,0,.2,1); }
  .sw input:checked + span { background:linear-gradient(90deg,var(--accent-press),var(--accent)); border-color:var(--accent); box-shadow:0 0 15px rgba(34,211,238,.5),inset 0 0 9px rgba(34,211,238,.32); }
  .sw input:checked + span:before { transform:translateX(21px); background:#ecffff; box-shadow:0 0 9px rgba(180,250,255,.8); }
  .gauge { width:90px; height:90px; border-radius:50%; margin:8px auto 2px; display:grid; place-items:center; background:conic-gradient(var(--accent) calc(var(--p)*1%),rgba(255,255,255,.06) 0); box-shadow:0 0 20px rgba(34,211,238,.22); position:relative; }
  .gauge::before { content:""; position:absolute; inset:0; border-radius:50%; box-shadow:inset 0 0 13px rgba(34,211,238,.3); }
  .gauge i { width:68px; height:68px; border-radius:50%; background:rgba(7,11,20,.96); display:grid; place-items:center; font-size:17px; font-weight:700; font-style:normal; font-family:var(--mono); color:var(--accent); text-shadow:0 0 10px rgba(34,211,238,.4); }
  .brange { -webkit-appearance:none; appearance:none; width:100%; height:5px; border-radius:5px; background:rgba(255,255,255,.1); outline:none; margin-top:6px; }
  .brange::-webkit-slider-thumb { -webkit-appearance:none; width:15px; height:15px; border-radius:50%; background:var(--accent); box-shadow:0 0 11px var(--accent); cursor:pointer; }
  .brange::-moz-range-thumb { width:15px; height:15px; border:0; border-radius:50%; background:var(--accent); box-shadow:0 0 11px var(--accent); cursor:pointer; }
  .grid .card { animation:cardin .34s cubic-bezier(.2,.8,.2,1) backwards; }
  .grid .card:nth-child(2){animation-delay:.04s}.grid .card:nth-child(3){animation-delay:.08s}.grid .card:nth-child(4){animation-delay:.12s}.grid .card:nth-child(5){animation-delay:.16s}.grid .card:nth-child(n+6){animation-delay:.2s}
  @keyframes cardin { from{opacity:0;transform:translateY(9px) scale(.985)} to{opacity:1;transform:none} }
  .roomnm { color:var(--accent); text-shadow:0 0 10px rgba(34,211,238,.32); }
  .roomct { background:rgba(34,211,238,.08); border-color:rgba(34,211,238,.25); color:var(--accent); }
  /* Driver (media) cards — console transport */
  .card [data-cap] { padding:7px 0; min-width:36px; font-size:14px; border:1px solid var(--line); border-radius:9px; background:rgba(6,11,20,.6); color:var(--fg-dim); transition:var(--fast); }
  .card [data-cap]:hover { color:var(--accent); border-color:var(--accent); box-shadow:0 0 10px rgba(34,211,238,.3); }
  /* Atmospheric depth behind the home view */
  #view-devices::before { content:""; position:fixed; top:-10%; right:-5%; width:50vw; height:50vh; background:radial-gradient(circle,rgba(34,211,238,.06),transparent 70%); pointer-events:none; z-index:0; }
  /* Settings rows */
  .setrow { display:flex; align-items:center; justify-content:space-between; gap:16px; padding:12px 2px; border-bottom:1px solid var(--line); }
  .setrow:last-child { border-bottom:0; }
  .setlbl { font-size:13.5px; } .setlbl .rnote { margin-top:2px; }
  .setctl { display:flex; align-items:center; gap:9px; flex:none; }
  .setinput { padding:7px 10px; border:1px solid var(--line); border-radius:8px; background:var(--input); color:var(--fg); font-size:13px; min-width:130px; }
  .setinput:focus { outline:none; border-color:var(--accent); box-shadow:0 0 0 2px rgba(34,211,238,.18); }
  input.setinput[type=range] { min-width:160px; padding:0; }
  .setnum { font-family:var(--mono); font-size:12px; color:var(--accent); min-width:46px; text-align:right; text-shadow:0 0 8px rgba(34,211,238,.3); }
  input[type=color].setinput { padding:2px; width:46px; min-width:46px; height:32px; cursor:pointer; }
  /* Connect a phone */
  .qrbox { display:inline-block; padding:14px; background:#05070d; border:1px solid rgba(34,211,238,.3); border-radius:16px; box-shadow:0 0 28px rgba(34,211,238,.18); }
  .qrbox img { width:232px; height:232px; display:block; }
  .connecturl { margin-top:12px; }
  .connecturl code { display:inline-block; font-family:var(--mono); font-size:12.5px; color:var(--accent); background:rgba(7,12,22,.6); border:1px solid var(--line); border-radius:8px; padding:8px 12px; word-break:break-all; max-width:100%; }
</style></head><body>
  <aside class="sidebar">
    <div class="brand"><span class="logo">&#9698;&#9700;</span><b>ELI</b><small>v2</small></div>
    <nav class="tabs">
      <button data-tab="overview" class="active"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></svg><span>Overview</span></button>
      <button data-tab="chat"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M21 12a8 8 0 0 1-11.6 7.1L3 21l1.9-6.4A8 8 0 1 1 21 12z"/></svg><span>Chat</span></button>
      <button data-tab="commands"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9l3 3-3 3M13 15h4"/></svg><span>Commands</span></button>
      <button data-tab="devices"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M3 11l9-8 9 8M5 10v10h14V10"/></svg><span>Home</span></button>
      <button data-tab="system"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 1.5v3M15 1.5v3M9 19.5v3M15 19.5v3M1.5 9h3M1.5 15h3M19.5 9h3M19.5 15h3"/></svg><span>System</span></button>
      <button data-tab="research"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M9 3h6M10 3v6l-5.5 9.5A2 2 0 0 0 6.2 21h11.6a2 2 0 0 0 1.7-3.5L14 9V3"/></svg><span>Research</span></button>
      <button data-tab="audit"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M12 3l8 3v6c0 5-4 8-8 9-4-1-8-4-8-9V6z"/><path d="M9 12l2 2 4-4"/></svg><span>Audit</span></button>
      <button data-tab="admin"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M4 6h16M4 12h16M4 18h16"/><circle cx="9" cy="6" r="2" fill="currentColor" stroke="none"/><circle cx="15" cy="12" r="2" fill="currentColor" stroke="none"/><circle cx="8" cy="18" r="2" fill="currentColor" stroke="none"/></svg><span>Admin</span></button>
      <button data-tab="settings"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg><span>Settings</span></button>
      <button data-tab="connect"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="7" y="2" width="10" height="20" rx="2.5"/><path d="M11 18.5h2"/></svg><span>Connect</span></button>
    </nav>
    <div class="sidefoot"><span id="rolebadge">local &middot; private</span><button class="iconbtn" id="appearbtn" title="Colours" onclick="openAppear()">&#9670;</button><button class="iconbtn" id="themebtn" title="Toggle light / dark">&#9680;</button></div>
  </aside>
  <main class="main">
  <section class="view active" id="view-overview"><div id="overview"><div class="muted">Loading…</div></div></section>
  <section class="view" id="view-chat">
    <div class="chatbar">
      <button class="cbtn" onclick="newChat()" title="New chat">&#43; New</button>
      <select id="sessionsel" onchange="switchSession(this.value)"></select>
      <button class="cbtn" id="regenbtn" onclick="regenerate()" title="Regenerate last reply">&#8635;</button>
      <button class="cbtn" onclick="deleteSession()" title="Delete this chat">&#128465;</button>
    </div>
    <div id="log"><div class="meta">Connected to your ELI server. Say hello.</div></div>
    <form id="f"><button type="button" id="mic" title="Tap to talk">&#127908;</button><input id="box" autocomplete="off" placeholder="Message ELI..."><button id="send">Send</button></form>
    <div class="voicebar"><label class="spk"><input type="checkbox" id="spk"> Speak replies</label><span id="vstat"></span></div>
  </section>
  <section class="view" id="view-commands">
    <div id="commands">
      <input id="cmdsearch" autocomplete="off" placeholder="Search commands…">
      <div id="cmdcats" class="subtabs" style="margin-top:10px"></div>
      <div id="cmdlist"><div class="muted">Loading…</div></div>
    </div>
  </section>
  <section class="view" id="view-devices"><div id="devices"><div class="muted">Loading…</div></div></section>
  <section class="view" id="view-system"><div id="system"><div class="muted">Loading…</div></div></section>
  <section class="view" id="view-research"><div id="research"><div class="muted">Loading…</div></div></section>
  <section class="view" id="view-audit"><div id="audit"><div class="muted">Loading…</div></div></section>
  <section class="view" id="view-admin"><div id="admin"><div class="muted">Loading…</div></div></section>
  <section class="view" id="view-settings"><div id="settings-tab"><div class="muted">Loading…</div></div></section>
  <section class="view" id="view-connect"><div id="connect-tab"><div class="muted">Loading…</div></div></section>
  </main>
  <div id="appear" class="modal"><div class="sheet">
    <h3>Colours</h3><div class="sub">Personalise the chat — your choices are saved on this device.</div>
    <div id="appear-rows"></div>
    <div class="mfoot"><button class="mbtn" onclick="resetColors()">Reset</button><button class="mbtn primary" onclick="closeAppear()">Done</button></div>
  </div></div>
<script>
  const $ = s => document.querySelector(s);
  let uid=localStorage.getItem('eli_uid');
  if(!uid){uid='web-'+Math.random().toString(36).slice(2,8);localStorage.setItem('eli_uid',uid);}
  const qp=new URLSearchParams(location.search);
  if(qp.get('token')){localStorage.setItem('eli_token',qp.get('token'));history.replaceState({},'',location.pathname);}
  const token=localStorage.getItem('eli_token')||'';
  const H=()=>{const h={'Content-Type':'application/json'};if(token)h['Authorization']='Bearer '+token;return h;};
  const api=(path,opts)=>fetch(path,Object.assign({headers:H()},opts||{})).then(r=>r.json());
  function esc(s){return (''+s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
  // ── Settings (real, typed options wired to ELI's config) ───────────────
  let _setSub='General', _setSchema=[], _setVals={}, _setVoices=[];
  function loadSettings(){
    Promise.all([api('/v1/settings'), api('/v1/voice/voices').catch(()=>({})), api('/v1/me').catch(()=>({}))]).then(function(r){
      const s=r[0]||{}, v=r[1]||{}, me=r[2]||{};
      _setSchema=s.schema||[]; _setVals=s.values||{};
      _setVoices=((v.voices)||[]).map(x=>x.id||x.name||x);
      const isAdmin=!me.role||me.role==='admin';
      const groups=[],seen={};_setSchema.forEach(it=>{if(!seen[it.group]){seen[it.group]=1;groups.push(it.group);}});
      const host=$('#settings-tab');host.innerHTML='';
      const strip=document.createElement('div');strip.className='livestrip';
      strip.innerHTML='<span class="lstitle">&#9670; SETTINGS</span><span class="lspill"><b>'+_setSchema.length+'</b> options</span>'+(isAdmin?'<span class="lspill"><span class="ld live"></span>admin — editable</span>':'<span class="lspill"><span class="ld warn"></span>read-only</span>');
      host.appendChild(strip);
      const shell=document.createElement('div');shell.className='subwrap';host.appendChild(shell);
      mountSubtabs(shell, groups.map(g=>({id:g,label:g,render:el=>settingsPane(el,g,isAdmin)})), groups.indexOf(_setSub)>=0?_setSub:groups[0], id=>{_setSub=id;});
    }).catch(e=>{$('#settings-tab').innerHTML='<div class="err">'+esc(''+e)+'</div>';});
  }
  function settingControl(it,val){
    const k=esc(it.key);
    if(it.type==='bool')return '<label class="sw"><input type="checkbox" data-k="'+k+'" '+(val?'checked':'')+'><span></span></label>';
    if(it.type==='int'||it.type==='float'){
      if(it.min!==undefined)return '<input type="range" class="brange setinput" data-k="'+k+'" data-t="'+it.type+'" min="'+it.min+'" max="'+it.max+'" step="'+it.step+'" value="'+(val!=null?val:it.min)+'" oninput="this.nextElementSibling.textContent=this.value"><span class="setnum">'+(val!=null?val:it.min)+'</span>';
      return '<input type="number" class="setinput" data-k="'+k+'" data-t="'+it.type+'" value="'+(val!=null?val:'')+'">';
    }
    if(it.key==='tts_voice'&&_setVoices.length)return '<select class="setinput" data-k="'+k+'">'+_setVoices.map(v=>'<option '+(v===val?'selected':'')+'>'+esc(v)+'</option>').join('')+'</select>';
    if(it.key==='theme')return '<select class="setinput" data-k="'+k+'"><option '+(val==='dark'?'selected':'')+'>dark</option><option '+(val==='light'?'selected':'')+'>light</option></select>';
    if(it.key==='user_text_color')return '<input type="color" class="setinput" data-k="'+k+'" value="'+(val||'#4DA3FF')+'">';
    return '<input type="text" class="setinput" data-k="'+k+'" value="'+esc(val!=null?val:'')+'">';
  }
  function settingsPane(el, group, isAdmin){
    const items=_setSchema.filter(it=>it.group===group);
    let h='<div class="jhead">'+esc(group)+'</div><div class="syscard">';
    items.forEach(it=>{h+='<div class="setrow"><div class="setlbl"><div>'+esc(it.label)+'</div>'+(it.hint?'<div class="rnote">'+esc(it.hint)+'</div>':'')+'</div><div class="setctl">'+settingControl(it,_setVals[it.key])+'</div></div>';});
    h+='</div>';
    if(isAdmin)h+='<div class="rrow" style="margin-top:14px"><button onclick="saveSettings(\\''+esc(group)+'\\')">Save '+esc(group)+'</button><span id="set-status-'+esc(group)+'" class="rnote" style="align-self:center"></span></div>';
    else h+='<div class="rnote" style="margin-top:10px">Sign in as admin to change settings.</div>';
    el.innerHTML=h;
    if(!isAdmin)el.querySelectorAll('[data-k]').forEach(x=>x.disabled=true);
  }
  function saveSettings(group){
    const st=$('#set-status-'+group);if(st)st.textContent='Saving…';
    const out={};
    document.querySelectorAll('#view-settings [data-k]').forEach(el=>{
      const k=el.dataset.k;let v;
      if(el.type==='checkbox')v=el.checked;
      else if(el.dataset.t==='int')v=parseInt(el.value,10);
      else if(el.dataset.t==='float')v=parseFloat(el.value);
      else v=el.value;
      out[k]=v;
    });
    api('/v1/settings',{method:'POST',body:JSON.stringify({settings:out})}).then(r=>{
      if(st)st.innerHTML=r.ok?'Saved &#10003;':'<span style="color:#f87171">'+esc(r.error||'failed')+'</span>';
      if(out.theme){applyTheme(out.theme==='light'?'light':'dark');}
      if(out.hasOwnProperty('user_name')&&r.ok){const e=$('#me-name');if(e)e.textContent=out.user_name||'';}
    }).catch(e=>{if(st)st.textContent=''+e;});
  }
  // ── Connect a phone — QR + LAN URL ─────────────────────────────────────
  function loadConnect(){
    api('/v1/connect').then(function(d){
      const host=$('#connect-tab');if(!host)return;host.innerHTML='';
      const strip=document.createElement('div');strip.className='livestrip';
      strip.innerHTML='<span class="lstitle">&#9670; CONNECT</span>'+
        (d.lan_accessible?'<span class="lspill"><span class="ld live"></span>reachable on your network</span>':'<span class="lspill"><span class="ld warn"></span>this computer only</span>')+
        '<span class="lspill">'+esc(d.lan_ip||'?')+':'+esc(''+(d.port||''))+'</span>';
      host.appendChild(strip);
      let h='';
      if(d.lan_accessible){
        h+='<div class="jhead">Scan with your phone</div>'+
          '<div class="syscard" style="text-align:center">'+
          '<div class="rnote" style="margin-bottom:10px">Open your phone&#39;s camera and point it at this code — the dashboard opens automatically, already signed in.</div>'+
          '<div class="qrbox"><img id="qr-img" alt="QR code" src="/v1/connect/qr.svg?t='+Date.now()+'"></div>'+
          '<div class="connecturl"><code id="conn-url">'+esc(d.url)+'</code></div>'+
          '<div class="rrow" style="justify-content:center;margin-top:10px"><button class="cbtn" onclick="copyConnUrl()">&#128203; Copy link</button>'+
          '<button class="cbtn" onclick="loadConnect()">&#10227; Refresh</button></div>'+
          '<div class="rnote" style="margin-top:8px">Make sure the phone is on the <b>same Wi-Fi</b> as this computer.</div></div>';
        if(d.https){
          h+='<div class="syscard"><div class="row" style="gap:8px"><span class="ld live" style="width:8px;height:8px;border-radius:50%;background:#2ec07a;box-shadow:0 0 8px #2ec07a"></span><b>HTTPS on — phone microphone enabled.</b></div>'+
            '<div class="rnote" style="margin-top:6px">First open shows a <b>“connection not private”</b> warning (the certificate is self-signed and local) — tap <b>Advanced &#8594; Proceed</b> once. That accept is what unlocks the mic; voice works after it.</div></div>';
        } else {
          h+='<div class="syscard"><div class="row" style="gap:8px"><span class="ld warn" style="width:8px;height:8px;border-radius:50%;background:#e0a72e;box-shadow:0 0 8px #e0a72e"></span><b>Phone microphone needs HTTPS.</b></div>'+
            '<div class="rnote" style="margin-top:6px">Typed chat &amp; “Speak replies” already work on the phone. For the phone <b>mic</b>, restart with HTTPS — one flag, cert generated locally:</div>'+
            '<div class="connecturl" style="margin:8px 0"><code>python api/server.py --lan --https</code></div></div>';
        }
      } else {
        h+='<div class="jhead">Make it reachable from your phone</div>'+
          '<div class="syscard"><div class="banner bad" style="margin:0 0 12px">The server is running in <b>local-only</b> mode (loopback), so your phone can&#39;t reach it yet.</div>'+
          '<div class="rnote">Restart the server in LAN mode — one command, and it prints a phone link &amp; QR:</div>'+
          '<div class="connecturl" style="margin:8px 0"><code>python api/server.py --lan</code></div>'+
          '<div class="rnote">Or, from the desktop app: <b>Settings &#8594; Web Server</b>, tick <b>LAN</b>, Start. Either way, come back here and the QR appears.</div>'+
          '<div class="rnote" style="margin-top:10px;opacity:.7">Your LAN address would be <b>http://'+esc(d.lan_ip||'this-computer')+':'+esc(''+(d.port||'8081'))+'/</b> once LAN mode is on.</div></div>';
      }
      const body=document.createElement('div');body.innerHTML=h;host.appendChild(body);
    }).catch(e=>{$('#connect-tab').innerHTML='<div class="err">'+esc(''+e)+'</div>';});
  }
  function copyConnUrl(){const u=($('#conn-url')||{}).textContent||'';
    if(navigator.clipboard)navigator.clipboard.writeText(u).then(()=>{const b=event&&event.target;if(b){const o=b.textContent;b.textContent='Copied \\u2713';setTimeout(()=>b.textContent=o,1400);}}).catch(()=>{});}
  window.loadConnect=loadConnect; window.copyConnUrl=copyConnUrl;
  function switchTab(t){document.querySelector('nav.tabs button[data-tab="'+t+'"]').click();}

  /* theme toggle (persisted; applied pre-paint in <head> to avoid flash) */
  const themebtn=$('#themebtn');
  function applyTheme(t){
    if(t==='light')document.documentElement.setAttribute('data-theme','light');
    else document.documentElement.removeAttribute('data-theme');
    if(themebtn)themebtn.innerHTML=(t==='light')?'&#9790;':'&#9728;';
  }
  applyTheme(localStorage.getItem('eli_theme')||'dark');
  if(themebtn)themebtn.onclick=()=>{const t=(localStorage.getItem('eli_theme')==='light')?'dark':'light';localStorage.setItem('eli_theme',t);applyTheme(t);};

  /* appearance — pick chat colours (saved per device) */
  const PALETTE=['#22d3ee','#38bdf8','#3b82f6','#6366f1','#8b5cf6','#a855f7','#d946ef','#ec4899','#f43f5e','#ef4444','#f97316','#f59e0b','#84cc16','#22c55e','#10b981','#14b8a6','#64748b','#94a3b8'];
  let colors={}; try{colors=JSON.parse(localStorage.getItem('eli_colors')||'{}');}catch(e){colors={};}
  function applyColors(){
    const r=document.documentElement.style;
    colors.ubub?r.setProperty('--ubub',colors.ubub):r.removeProperty('--ubub');
    colors.sendc?r.setProperty('--sendc',colors.sendc):r.removeProperty('--sendc');
    if(colors.micc){r.setProperty('--micc',colors.micc);r.setProperty('--micfg','#04121a');}else{r.removeProperty('--micc');r.removeProperty('--micfg');}
  }
  function setColor(t,v){colors[t]=v;localStorage.setItem('eli_colors',JSON.stringify(colors));applyColors();renderAppear();}
  function resetColors(){colors={};localStorage.removeItem('eli_colors');applyColors();renderAppear();}
  function openAppear(){renderAppear();$('#appear').classList.add('show');}
  function closeAppear(){$('#appear').classList.remove('show');}
  function renderAppear(){
    const box=$('#appear-rows'); if(!box)return; box.innerHTML='';
    [['ubub','Your chat bubble'],['micc','Mic button'],['sendc','Send button']].forEach(function(pair){
      const target=pair[0], label=pair[1], cur=(colors[target]||'').toLowerCase();
      const row=document.createElement('div'); row.className='crow';
      const cl=document.createElement('div'); cl.className='cl'; cl.textContent=label; row.appendChild(cl);
      const list=document.createElement('div'); list.className='sw-list';
      PALETTE.forEach(function(c){const sw=document.createElement('span'); sw.className='sw'+(cur===c?' sel':''); sw.style.background=c; sw.style.color=c; sw.title=c; sw.onclick=function(){setColor(target,c);}; list.appendChild(sw);});
      const lab=document.createElement('label'); lab.className='sw custom'; lab.title='Custom'; lab.textContent='+';
      const inp=document.createElement('input'); inp.type='color'; inp.value=colors[target]||'#22d3ee'; inp.oninput=function(){setColor(target,inp.value);}; lab.appendChild(inp); list.appendChild(lab);
      row.appendChild(list); box.appendChild(row);
    });
  }
  applyColors();
  window.openAppear=openAppear; window.closeAppear=closeAppear; window.resetColors=resetColors;
  { const am=$('#appear'); if(am) am.onclick=function(e){ if(e.target===am) closeAppear(); }; }

  let cmdsLoaded=false;
  document.querySelectorAll('nav.tabs button').forEach(b=>b.onclick=()=>{
    document.querySelectorAll('nav.tabs button').forEach(x=>x.classList.remove('active'));
    b.classList.add('active');
    document.querySelectorAll('.view').forEach(v=>v.classList.remove('active'));
    $('#view-'+b.dataset.tab).classList.add('active');
    if(b.dataset.tab==='overview') loadOverview();
    if(b.dataset.tab==='commands' && !cmdsLoaded) loadCommands();
    if(b.dataset.tab==='devices') loadDevices();
    if(b.dataset.tab==='system') loadSystem();
    if(b.dataset.tab==='research') loadResearch();
    if(b.dataset.tab==='audit') loadAudit();
    if(b.dataset.tab==='admin') loadAdmin();
    if(b.dataset.tab==='settings') loadSettings();
    if(b.dataset.tab==='connect') loadConnect();
  });

  /* chat */
  const log=$('#log'),box=$('#box'),send=$('#send'),f=$('#f');
  const NL=String.fromCharCode(10), SEP=NL+NL;
  let session=null, abortCtl=null;

  /* --- markdown (safe, vanilla, offline) --- */
  function mdRender(src){
    src=String(src||''); const blocks=[];
    src=src.replace(/```(\\w*)\\n?([\\s\\S]*?)```/g,(m,lang,code)=>{blocks.push({lang:lang,code:code.replace(/\\n$/,'')});return '\\u0000B'+(blocks.length-1)+'\\u0000';});
    src=esc(src);
    src=src.replace(/`([^`]+)`/g,(m,c)=>'<code class="ic">'+c+'</code>');
    src=src.replace(/\\*\\*([^*]+)\\*\\*/g,'<b>$1</b>').replace(/(^|[^*])\\*([^*]+)\\*/g,'$1<i>$2</i>');
    src=src.replace(/\\[([^\\]]+)\\]\\((https?:[^)\\s]+)\\)/g,'<a href="$2" target="_blank" rel="noopener">$1</a>');
    const lines=src.split('\\n'); let out=[],inList=false;
    for(let ln of lines){
      let h=ln.match(/^(#{1,4})\\s+(.*)$/);
      if(h){if(inList){out.push('</ul>');inList=false;} const lv=Math.min(6,h[1].length+2); out.push('<h'+lv+' class="mh">'+h[2]+'</h'+lv+'>'); continue;}
      let li=ln.match(/^\\s*[-*]\\s+(.*)$/);
      if(li){if(!inList){out.push('<ul class="ml">');inList=true;} out.push('<li>'+li[1]+'</li>'); continue;}
      if(inList){out.push('</ul>');inList=false;}
      out.push(ln.trim()===''?'<br>':'<div>'+ln+'</div>');
    }
    if(inList)out.push('</ul>');
    let html=out.join('');
    html=html.replace(/\\u0000B(\\d+)\\u0000/g,(m,i)=>{const b=blocks[i];return '<div class="cb"><div class="cbh"><span>'+esc(b.lang||'code')+'</span><button class="cpy" onclick="copyCode(this)">copy</button></div><pre><code>'+esc(b.code)+'</code></pre></div>';});
    return html;
  }
  function copyCode(btn){const c=btn.closest('.cb').querySelector('code').textContent;navigator.clipboard.writeText(c).then(()=>{btn.textContent='copied';setTimeout(()=>btn.textContent='copy',1200);}).catch(()=>{});}

  /* --- sessions (persisted locally) --- */
  let sessions=[], curId=null;
  function loadSessions(){try{sessions=JSON.parse(localStorage.getItem('eli_sessions')||'[]');}catch(e){sessions=[];} curId=localStorage.getItem('eli_cur')||null; if(!sessions.length)newChat(); else{if(!sessions.find(s=>s.id===curId))curId=sessions[0].id; const s=curSession(); session=s?s.server:null; renderSessionSel(); renderLog();}}
  function persist(){try{localStorage.setItem('eli_sessions',JSON.stringify(sessions.slice(0,50)));localStorage.setItem('eli_cur',curId||'');}catch(e){}}
  function curSession(){return sessions.find(s=>s.id===curId);}
  function newChat(){const id='s'+Date.now();sessions.unshift({id:id,title:'New chat',ts:Date.now(),msgs:[],server:null});curId=id;session=null;persist();renderSessionSel();renderLog();if(box)box.focus();}
  function switchSession(id){curId=id;const s=curSession();session=s?s.server:null;persist();renderLog();}
  function deleteSession(){if(!curId)return;sessions=sessions.filter(s=>s.id!==curId);if(!sessions.length){newChat();return;}curId=sessions[0].id;const s=curSession();session=s.server;persist();renderSessionSel();renderLog();}
  function renderSessionSel(){const sel=$('#sessionsel');if(!sel)return;sel.innerHTML=sessions.map(s=>'<option value="'+s.id+'"'+(s.id===curId?' selected':'')+'>'+esc((s.title||'Chat').slice(0,40))+'</option>').join('')||'<option>—</option>';}
  function renderLog(){const s=curSession();log.innerHTML='';if(!s||!s.msgs.length){log.innerHTML='<div class="meta">New chat — say hello to ELI.</div>';return;}s.msgs.forEach(m=>{const d=document.createElement('div');d.className='msg '+m.who;if(m.who==='eli')d.innerHTML=mdRender(m.text);else d.textContent=m.text;log.appendChild(d);});log.scrollTop=log.scrollHeight;}
  function pushMsg(who,text){const s=curSession();if(!s)return;s.msgs.push({who:who,text:text});if(who==='user'&&(!s.title||s.title==='New chat'))s.title=text.slice(0,40);s.ts=Date.now();persist();renderSessionSel();}

  function add(t,who){const d=document.createElement('div');d.className='msg '+who;d.textContent=t;log.appendChild(d);log.scrollTop=log.scrollHeight;return d;}
  function setBusy(b){send.textContent=b?'Stop':'Send';send.classList.toggle('stop',b);}
  f.addEventListener('submit',e=>{e.preventDefault();if(abortCtl){abortCtl.abort();return;}const text=box.value.trim();if(!text)return;box.value='';streamChat(text);});

  async function streamChat(text){
    if(!curSession())newChat();
    add(text,'user');pushMsg('user',text);
    const p=add('','eli');p.innerHTML='<span class="typing"><i></i><i></i><i></i></span>';
    let raw='',got=false; abortCtl=new AbortController(); setBusy(true);
    try{
      const r=await fetch('/v1/chat/stream',{method:'POST',headers:H(),body:JSON.stringify({message:text,user_id:uid,session_id:session}),signal:abortCtl.signal});
      const reader=r.body.getReader(),dec=new TextDecoder();let buf='';
      for(;;){const rd=await reader.read();if(rd.done)break;
        buf+=dec.decode(rd.value,{stream:true});let i;
        while((i=buf.indexOf(SEP))>=0){const frame=buf.slice(0,i);buf=buf.slice(i+SEP.length);
          if(frame.indexOf('data:')!==0)continue;
          let j;try{j=JSON.parse(frame.slice(5).trim());}catch(_e){continue;}
          if(j.session_id){session=j.session_id;const s=curSession();if(s)s.server=session;}
          if(j.delta){if(!got){got=true;p.textContent='';}raw+=j.delta;p.textContent=raw;log.scrollTop=log.scrollHeight;}
          if(j.error)raw+=(raw?NL:'')+'[error: '+j.error+']';
        }
      }
    }catch(err){if(err.name!=='AbortError'){
      const net=(err.name==='TypeError')||((''+err).indexOf('NetworkError')>=0)||((''+err).indexOf('Failed to fetch')>=0);
      raw+=(raw?NL:'')+(net?'Connection to the server dropped. If this was the first message, the local model may still be loading (a large model can take a minute on first use) — or the server ran low on memory. Wait a few seconds and try again; if it keeps happening, run the server on its own (not alongside the desktop app) so the model only loads once.':'Error: '+err);
    }}
    finally{abortCtl=null;setBusy(false);box.focus();}
    if(!raw)raw=got?'(stopped)':'(no response)';
    p.innerHTML=mdRender(raw);pushMsg('eli',raw);log.scrollTop=log.scrollHeight;
    // Speak EVERY real reply when "Speak replies" is on — typed, regenerated, or voice.
    if(got&&raw&&spk&&spk.checked)speakReply(raw);
    return got?raw:'';
  }
  function regenerate(){
    const s=curSession();if(!s||!s.msgs.length||abortCtl)return;
    let lastUser=null;for(let k=s.msgs.length-1;k>=0;k--){if(s.msgs[k].who==='user'){lastUser=s.msgs[k].text;break;}}
    if(!lastUser)return;
    while(s.msgs.length&&s.msgs[s.msgs.length-1].who==='eli')s.msgs.pop();
    if(s.msgs.length&&s.msgs[s.msgs.length-1].who==='user')s.msgs.pop();
    persist();renderLog();streamChat(lastUser);
  }
  window.newChat=newChat; window.switchSession=switchSession; window.deleteSession=deleteSession; window.regenerate=regenerate; window.copyCode=copyCode;
  loadSessions();
  loadOverview();
  /* PWA: installable + offline shell */
  if('serviceWorker' in navigator){try{navigator.serviceWorker.register('/sw.js').catch(function(){});}catch(e){}}
  /* live: refresh the dashboard while it's open (no manual reload) */
  setInterval(function(){const v=$('#view-overview'); if(v&&v.classList.contains('active')&&!document.hidden)loadOverview();},6000);

  /* voice — local STT (whisper) in, local TTS (piper) out; nothing leaves the box */
  const mic=$('#mic'),spk=$('#spk'),vstat=$('#vstat');
  spk.checked=localStorage.getItem('eli_speak')==='1';
  spk.onchange=()=>localStorage.setItem('eli_speak',spk.checked?'1':'0');
  function vmsg(m){vstat.textContent=m||'';}
  let mediaRec=null,vchunks=[],recording=false,vstream=null;
  async function toggleMic(){
    if(recording){try{mediaRec.stop();}catch(_e){}return;}
    if(!navigator.mediaDevices||!window.MediaRecorder){
      vmsg(location.protocol==='https:'||location.hostname==='localhost'||location.hostname==='127.0.0.1'
        ? 'Mic not available in this browser.'
        : 'Mic needs a secure page — open ELI on http://127.0.0.1:8081 (this computer), or use HTTPS. Browsers block the mic on plain http://LAN-IP.');return;}
    try{vstream=await navigator.mediaDevices.getUserMedia({audio:true});}
    catch(e){vmsg('Mic blocked: '+e.name);return;}
    let mt='';['audio/webm','audio/mp4','audio/ogg'].forEach(t=>{if(!mt&&window.MediaRecorder.isTypeSupported&&MediaRecorder.isTypeSupported(t))mt=t;});
    vchunks=[];
    mediaRec=mt?new MediaRecorder(vstream,{mimeType:mt}):new MediaRecorder(vstream);
    mediaRec.ondataavailable=e=>{if(e.data&&e.data.size)vchunks.push(e.data);};
    mediaRec.onstop=async()=>{
      recording=false;mic.classList.remove('rec');
      if(vstream){vstream.getTracks().forEach(t=>t.stop());vstream=null;}
      const type=(mediaRec.mimeType||mt||'audio/webm').split(';')[0];
      const ext=type.indexOf('mp4')>=0?'mp4':type.indexOf('ogg')>=0?'ogg':'webm';
      const blob=new Blob(vchunks,{type:type});
      if(!blob.size){vmsg('No audio captured');return;}
      vmsg('Transcribing…');
      const h={'Content-Type':type};if(token)h['Authorization']='Bearer '+token;
      try{
        const r=await fetch('/v1/voice/stt?ext='+ext,{method:'POST',headers:h,body:blob});
        const j=await r.json();
        if(!j.ok){vmsg('STT error: '+(j.error||'failed'));return;}
        const text=(j.text||'').trim();
        if(!text){vmsg('Didn\\'t catch that — try again');return;}
        vmsg('');box.value='';
        await streamChat(text);   // streamChat speaks the reply itself when Speak-replies is on
      }catch(e){vmsg('Voice error: '+e);}
    };
    recording=true;mic.classList.add('rec');vmsg('Listening… tap mic to stop');mediaRec.start();
  }
  let _ttsAudio=null;
  async function speakReply(text){
    // Strip markdown/code so Piper reads prose, not asterisks and backticks.
    const clean=(''+text).replace(/```[\\s\\S]*?```/g,' ').replace(/`([^`]+)`/g,'$1')
      .replace(/[*_#>~]/g,'').replace(/\\[(.*?)\\]\\(.*?\\)/g,'$1').replace(/\\s+/g,' ').trim();
    if(!clean){return;}
    try{
      if(_ttsAudio){try{_ttsAudio.pause();}catch(_e){}}
      vmsg('Speaking…');
      const r=await fetch('/v1/voice/tts',{method:'POST',headers:H(),body:JSON.stringify({text:clean})});
      if(!r.ok){vmsg('TTS error ('+r.status+')');return;}
      _ttsAudio=new Audio(URL.createObjectURL(await r.blob()));
      _ttsAudio.onended=()=>vmsg('');
      _ttsAudio.play().then(()=>vmsg('')).catch(()=>vmsg('Tap anywhere, then try again (browser blocked autoplay)'));
    }catch(e){vmsg('TTS error: '+e);}
  }
  mic.onclick=toggleMic;

  /* commands — category sub-tabs + search */
  let CAT=[], _cmdCat='';
  function loadCommands(){api('/v1/capabilities').then(d=>{CAT=d.categories||[];cmdsLoaded=true;buildCmdCats();renderCommands(($('#cmdsearch').value||'').toLowerCase());})
    .catch(e=>{$('#cmdlist').innerHTML='<div class="err">Could not load commands: '+esc(''+e)+'</div>';});}
  function buildCmdCats(){
    const bar=$('#cmdcats');if(!bar)return;bar.innerHTML='';
    const mk=(id,label,n)=>{const b=document.createElement('button');b.className='subtab'+(_cmdCat===id?' active':'');b.innerHTML=esc(label)+(n!=null?(' <span style="opacity:.5">'+n+'</span>'):'');
      b.onclick=()=>{_cmdCat=id;bar.querySelectorAll('.subtab').forEach(x=>x.classList.remove('active'));b.classList.add('active');renderCommands(($('#cmdsearch').value||'').toLowerCase());};return b;};
    const total=CAT.reduce((n,c)=>n+(c.actions?c.actions.length:0),0);
    bar.appendChild(mk('','All',total));
    CAT.forEach(c=>bar.appendChild(mk(c.category,c.category,(c.actions||[]).length)));
  }
  $('#cmdsearch').addEventListener('input',e=>renderCommands(e.target.value.toLowerCase()));
  function renderCommands(q){
    const wrap=$('#cmdlist');wrap.innerHTML='';
    CAT.forEach(cat=>{
      if(_cmdCat&&cat.category!==_cmdCat)return;
      const acts=cat.actions.filter(a=>!q||a.action.toLowerCase().includes(q)||(a.description||'').toLowerCase().includes(q)||(a.phrases||[]).join(' ').toLowerCase().includes(q));
      if(!acts.length)return;
      const c=document.createElement('div');c.className='cat';c.innerHTML='<h3>'+esc(cat.category)+'</h3>';
      acts.forEach(a=>{
        const el=document.createElement('div');el.className='cmd';
        el.innerHTML='<div class="act">'+esc(a.action)+'</div><div class="desc">'+esc(a.description||'')+'</div>';
        if(a.phrases&&a.phrases.length){const ch=document.createElement('div');ch.className='chips';
          a.phrases.forEach(p=>{const s=(''+p).replace(/[“”"]/g,'').trim();if(!s)return;
            const bt=document.createElement('span');bt.className='chip';bt.textContent=s;
            bt.onclick=()=>{switchTab('chat');box.value=s;box.focus();};ch.appendChild(bt);});
          el.appendChild(ch);}
        c.appendChild(el);});
      wrap.appendChild(c);});
    if(!wrap.children.length)wrap.innerHTML='<div class="muted">No matches.</div>';
  }

  /* devices — ELI's OWN MQTT device server (no Home Assistant) */
  function loadDevices(){
    // Load driver status first so non-MQTT cards render correctly, then the device grid.
    // The grid shows whenever there are ANY devices (MQTT or driver-based) OR a broker is
    // configured — so AirPlay/Fire TV/Cast work with no MQTT broker at all.
    Promise.all([api('/v1/devices/status'), loadDrivers()]).then(([s])=>{
      const st=(s&&s.status)||{};
      api('/v1/devices/rooms').then(d=>{
        renderDevices(d.rooms||[], st);   // sub-tabbed; broker setup lives in Discover & Setup
      }).catch(e=>{$('#devices').innerHTML='<div class="err">'+esc(''+e)+'</div>';});
    }).catch(e=>{$('#devices').innerHTML='<div class="err">'+esc(''+e)+'</div>';});
  }
  function renderDevConfig(st, vals, err){
    st=st||{}; vals=vals||{};
    $('#devices').innerHTML='<div class="hconfig"><h3>Set up ELI&#39;s device server</h3>'+
      '<p><b>Find on my network</b> to add media devices — AirPlay, Fire TV, Chromecast, UPnP — controlled locally, no cloud. '+
      'For switches &amp; lights, point ELI at an <b>MQTT</b> broker (e.g. a local Mosquitto) and add devices that speak MQTT (ESPHome / Tasmota / Zigbee2MQTT) — no Home Assistant.</p>'+
      (err?'<div class="banner bad" style="margin:0 0 12px">'+esc(err)+'</div>':'')+
      '<label>Broker host</label><input id="mq_host" autocomplete="off" placeholder="192.168.1.50 or mosquitto.local" value="'+esc(vals.host||st.brokerHost||'')+'">'+
      '<label>Port</label><input id="mq_port" value="'+esc(vals.port||'1883')+'">'+
      '<label>Username (optional)</label><input id="mq_user" autocomplete="off" value="'+esc(vals.username||'')+'">'+
      '<label>Password (optional)</label><input id="mq_pass" type="password" autocomplete="new-password" value="'+esc(vals.password||'')+'">'+
      '<label>Discovery prefix (optional — auto-finds devices)</label><input id="mq_disc" placeholder="leave blank for manual devices" value="'+esc(vals.discovery_prefix||'')+'">'+
      '<div class="rrow" style="margin-top:14px"><button id="mq-save" onclick="saveDevConfig()">Save &amp; connect</button>'+
      '<button class="cbtn" id="mq-find" onclick="discoverDevices()">&#128270; Find on my network</button></div>'+
      '<div id="mq-found"></div></div>';
  }
  function discoverDevices(){
    const box=$('#mq-found'), btn=$('#mq-find');
    if(btn){btn.disabled=true;btn.textContent='Scanning…';}
    box.innerHTML='<div class="rnote">Scanning your network (mDNS + UPnP)…</div>';
    api('/v1/devices/discover',{method:'POST',body:JSON.stringify({})}).then(d=>{
      if(btn){btn.disabled=false;btn.innerHTML='&#128270; Find on my network';}
      if(!d.ok){box.innerHTML='<div class="banner bad" style="margin-top:10px">'+esc(d.error||'discovery failed')+'</div>';return;}
      const all=d.found||[], br=d.brokers||[], c=d.counts||{};
      const lab={ready:'control ready',roadmap:'control coming',cloud:'cloud only',detected:'detected'};
      const col={ready:'#2ec07a',roadmap:'#e0a72e',cloud:'#6aa3e0',detected:'#7a8699'};
      let h='';
      if(br.length){h+='<div class="rnote" style="margin-top:10px">MQTT broker(s) found — click to use:</div>';
        br.forEach(b=>{h+='<div class="src" style="cursor:pointer" onclick="useBroker(\\''+esc(b.host)+'\\','+(b.port||1883)+')"><div class="sh"><span>&#128268; '+esc(b.name||b.host)+'</span><span>'+esc(b.host)+':'+(b.port||'')+'</span></div></div>';});}
      window._disc=all;
      const others=[]; all.forEach((f,i)=>{if(f.kind!=='mqtt_broker')others.push([f,i]);});
      const ADDABLE={airplay:1,firetv:1,cast:1,upnp_renderer:1,sonos:1};
      if(others.length){
        h+='<div class="rnote" style="margin-top:12px">Devices seen on your network:</div>';
        others.forEach(([f,i])=>{
          const cs=f.control_status||'detected';
          const add=ADDABLE[f.kind]?'<button class="cbtn" style="padding:2px 10px" onclick="addDiscovered('+i+')">Add</button>':'';
          h+='<div class="src"><div class="sh"><span>'+esc(f.label||f.kind)+' — '+esc(f.name||'')+'</span>'
            +'<span style="display:flex;gap:8px;align-items:center"><span style="color:'+(col[cs]||col.detected)+'">'+(lab[cs]||'detected')+'</span>'+add+'</span></div>'
            +'<div style="font-size:.8em;opacity:.6">'+esc(f.host||'')+(f.port?(':'+f.port):'')+'</div></div>';
        });
      }
      if(all.length){
        let summ=(c.total||all.length)+' found'+(c.brokers?(', '+c.brokers+' broker'):'')+(c.controllable?(', '+c.controllable+' controllable now'):'');
        h+='<div class="rnote" style="margin-top:10px">'+esc(summ);
        if(!br.length) h+=' — no MQTT broker yet; for switches/lights run a broker (e.g. Mosquitto) and flash devices with ESPHome/Tasmota, then re-scan';
        h+='.</div>';
        if((d.errors||[]).length) h+='<div class="rnote" style="opacity:.55">'+esc((d.errors||[]).join('; '))+'</div>';
      } else {
        h='<div class="rnote" style="margin-top:10px">Nothing found. Make sure your devices are on the same Wi-Fi / LAN as this computer.</div>';
      }
      box.innerHTML=h;
    }).catch(e=>{if(btn){btn.disabled=false;btn.innerHTML='&#128270; Find on my network';}box.innerHTML='<div class="banner bad">'+esc(''+e)+'</div>';});
  }
  function useBroker(host,port){const h=$('#mq_host'),p=$('#mq_port');if(h)h.value=host;if(p)p.value=port||1883;const f=$('#mq-found');if(f)f.innerHTML='<div class="rnote" style="margin-top:10px">Broker set to '+esc(host)+'. Click &ldquo;Save &amp; connect&rdquo;.</div>';}
  function openDiscover(){let f=$('#mq-found');if(!f){f=document.createElement('div');f.id='mq-found';$('#devices').appendChild(f);}f.scrollIntoView({behavior:'smooth',block:'nearest'});discoverDevices();}
  function addDiscovered(i){const f=(window._disc||[])[i];if(!f)return;
    api('/v1/devices/add-discovered',{method:'POST',body:JSON.stringify({device:f})}).then(r=>{
      if(!r.ok){alert(r.error||'Could not add device');return;}
      loadDrivers().then(loadDevices);
    }).catch(e=>alert(''+e));}
  function saveDevConfig(){
    const body={host:($('#mq_host').value||'').trim(), port:parseInt($('#mq_port').value||'1883',10)||1883,
      username:($('#mq_user').value||'').trim(), password:$('#mq_pass').value||'',
      discovery_prefix:($('#mq_disc').value||'').trim()};
    const cfgbox=$('#broker-cfg')||$('#broker-cfg2');
    if(!body.host){renderBrokerCfg(cfgbox, body, 'Enter your MQTT broker host (e.g. 192.168.1.50 or mosquitto.local).');return;}
    const btn=$('#mq-save'); if(btn){btn.disabled=true;btn.textContent='Connecting…';}
    api('/v1/devices/config',{method:'POST',body:JSON.stringify(body)}).then(r=>{
      if(!r.ok){renderBrokerCfg(cfgbox, body, r.error||'Could not connect to the broker.');return;}
      setTimeout(loadDevices,500);
    }).catch(e=>{renderBrokerCfg(cfgbox, body, ''+e);});
  }
  // ── Local-control drivers (AirPlay / Fire TV / Cast / UPnP) ────────────────
  let DRIVERS={};
  const DRIVER_CAPS={
    airplay:['play','pause','stop','previous','next','volume'],
    firetv:['home','back','up','down','left','right','select','play','pause','on','off'],
    cast:['play','pause','stop','volume'],
    upnp:['play','pause','stop','volume'],
  };
  const CAP_LABEL={play:'▶',pause:'⏸',stop:'⏹',previous:'⏮',next:'⏭',home:'⌂',back:'↩',
    up:'▲',down:'▼',left:'◀',right:'▶',select:'OK',on:'On',off:'Off',volume:'🔊'};
  function loadDrivers(){return api('/v1/devices/drivers').then(d=>{DRIVERS={};(d.drivers||[]).forEach(x=>DRIVERS[x.name]=x);return DRIVERS;}).catch(()=>DRIVERS);}
  function isPaired(dv){const a=dv.attrs||{};
    if(dv.driver==='airplay')return !!a.airplay_credentials;
    if(dv.driver==='firetv')return !!a.adbkey;
    return true;}
  function driverCard(dv){
    const card=document.createElement('div');card.className='card';
    const drv=DRIVERS[dv.driver]||{};
    const head='<div><div class="nm">'+esc(dv.name||dv.id)+'</div><div class="dom">'+esc((drv.label||dv.driver))+'</div></div>';
    let h=head;
    if(!drv.installed){
      h+='<div class="row"><span class="st" style="color:#e0a72e">driver needed</span>'
        +'<button class="cbtn" data-act="install">Install</button></div>'
        +'<div style="font-size:.78em;opacity:.6">one-click — installs '+esc(drv.pip||dv.driver)+' locally</div>';
    } else if(drv.needs_pairing && !isPaired(dv)){
      h+='<div class="row"><span class="st" style="color:#e0a72e">not paired</span>'
        +'<button class="cbtn" data-act="pair">Pair</button></div>';
    } else {
      const caps=DRIVER_CAPS[dv.driver]||[];
      h+='<div class="row" style="flex-wrap:wrap;gap:6px">';
      caps.forEach(c=>{h+='<button class="cbtn" data-cap="'+c+'" title="'+c+'">'+(CAP_LABEL[c]||c)+'</button>';});
      h+='</div><div style="font-size:.78em;opacity:.55">'+esc(dv.host||'')+' · ready</div>';
    }
    card.innerHTML=h;
    const ib=card.querySelector('[data-act=install]');
    if(ib)ib.onclick=()=>{ib.disabled=true;ib.textContent='Installing…';
      api('/v1/devices/driver/install',{method:'POST',body:JSON.stringify({name:dv.driver})}).then(r=>{
        if(!r.ok){ib.disabled=false;ib.textContent='Install';alert('Install failed: '+(r.error||'')+(r.log?('\\n'+r.log):''));return;}
        loadDrivers().then(loadDevices);
      }).catch(e=>{ib.disabled=false;ib.textContent='Install';alert(''+e);});};
    const pb=card.querySelector('[data-act=pair]');
    if(pb)pb.onclick=()=>pairDialog(dv);
    card.querySelectorAll('[data-cap]').forEach(b=>{b.onclick=()=>{
      let v=null; if(b.dataset.cap==='volume'){v=prompt('Volume 0–100:','30');if(v===null)return;v=parseInt(v,10)||0;}
      b.disabled=true;api('/v1/devices/control',{method:'POST',body:JSON.stringify({device_id:dv.id,command:b.dataset.cap,value:v})}).then(r=>{
        b.disabled=false; if(!r.ok){if(r.need_pair){loadDevices();}else alert('Failed: '+(r.error||''));}
      }).catch(e=>{b.disabled=false;alert(''+e);});};});
    const rm=document.createElement('button');rm.className='cbtn';rm.textContent='remove';rm.style.cssText='margin-top:8px;opacity:.6';
    rm.onclick=()=>{if(confirm('Remove '+(dv.name||dv.id)+'?'))api('/v1/devices/remove',{method:'POST',body:JSON.stringify({device_id:dv.id})}).then(loadDevices);};
    card.appendChild(rm);
    return card;
  }
  // Guided pairing — adapts to the driver's style (accept-on-device vs PIN entry).
  function pairDialog(dv){
    const drv=DRIVERS[dv.driver]||{};
    const ov=document.createElement('div');ov.className='pairov';
    ov.style.cssText='position:fixed;inset:0;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center;z-index:9999';
    const box=document.createElement('div');box.className='card';box.style.cssText='max-width:440px;width:92%;padding:20px';
    ov.appendChild(box);document.body.appendChild(ov);
    const close=()=>{ov.remove();loadDevices();};
    function render(state){
      let h='<div class="nm" style="font-size:1.1em">Pair '+esc(dv.name||dv.id)+'</div>';
      if(state.instructions&&state.instructions.length){h+='<ol style="margin:10px 0 4px;padding-left:18px;line-height:1.5">'+state.instructions.map(s=>'<li>'+esc(s)+'</li>').join('')+'</ol>';}
      if(state.error)h+='<div class="banner bad" style="margin:8px 0">'+esc(state.error)+'</div>';
      if(state.need_code){h+='<div style="margin:10px 0">'+esc(state.prompt||'Enter the code shown on the device:')+'</div><input id="pcode" inputmode="numeric" placeholder="PIN" style="width:120px">';}
      if(state.paired){h+='<div class="banner ok" style="margin:8px 0">Paired — '+esc(dv.name||dv.id)+' is ready.</div>';}
      h+='<div class="row" style="margin-top:14px;gap:8px;justify-content:flex-end">';
      if(state.paired){h+='<button class="cbtn" data-x="done">Done</button>';}
      else{h+='<button class="cbtn" data-x="cancel" style="opacity:.6">Cancel</button>'
        +'<button class="cbtn" data-x="go">'+(state.need_code?'Finish':(drv.pair_style==='pin'?'Start':'Pair'))+'</button>';}
      h+='</div>';box.innerHTML=h;
      const go=box.querySelector('[data-x=go]'),cn=box.querySelector('[data-x=cancel]'),dn=box.querySelector('[data-x=done]');
      if(cn)cn.onclick=()=>ov.remove();
      if(dn)dn.onclick=close;
      if(go)go.onclick=()=>{
        const code=state.need_code?((box.querySelector('#pcode')||{}).value||'').trim():null;
        go.disabled=true;go.textContent='…';
        api('/v1/devices/pair',{method:'POST',body:JSON.stringify({device_id:dv.id,code:code})}).then(r=>{
          if(r.paired){render({paired:true});return;}
          render(r);
        }).catch(e=>render({error:''+e}));
      };
    }
    // Fire TV starts with instructions; AirPlay starts with a Start button.
    render(drv.pair_style==='accept'?{instructions:[
      'On the Fire TV: Settings → My Fire TV → Developer Options → enable ADB debugging.',
      'Click Pair, then accept “Allow debugging from this computer?” on the TV.']}:{});
  }
  const DEV_ICON={light:'&#128161;',switch:'&#9211;',fan:'&#10052;',outlet:'&#128268;',sensor:'&#128200;',climate:'&#127777;',media:'&#9654;',cover:'&#129003;'};
  function devCard(dv){
    if(dv.driver && dv.driver!=='mqtt') return driverCard(dv);
    const t=dv.type||'switch', card=document.createElement('div');
    const sv=(''+(dv.state||'')).toUpperCase(), on=sv==='ON', off=sv==='OFF';
    card.className='card'+(on?' on':(off?' off':''));
    const icon='<span class="dicon">'+(DEV_ICON[t]||'&#9670;')+'</span>';
    const head='<div class="chead">'+icon+'<div class="cmeta"><div class="nm">'+esc(dv.name||dv.id)+'</div><div class="dom" title="click to change room">'+esc(dv.room||t)+'</div></div></div>';
    if(t==='light'||t==='switch'||t==='fan'||t==='outlet'){
      let h=head+'<div class="row"><span class="st">'+(on?'Online':(off?'Off':esc(''+(dv.state||'—'))))+'</span><label class="sw"><input type="checkbox" '+(on?'checked':'')+'><span></span></label></div>';
      const briTopic=(dv.attrs||{}).brightness_command_topic;
      if(t==='light'&&briTopic) h+='<input class="brange" type="range" min="1" max="100" value="100">';
      card.innerHTML=h;
      const tg=card.querySelector('.sw input');tg.onchange=()=>ctlDev(dv.id,tg.checked?'on':'off');
      const sl=card.querySelector('input[type=range]');
      if(sl){let t2;sl.oninput=()=>{clearTimeout(t2);t2=setTimeout(()=>ctlDev(dv.id,'brightness',+sl.value),250);};}
    } else {
      const num=parseFloat(dv.state), isNum=!isNaN(num)&&isFinite(num);
      if(isNum && num>=0 && num<=100){
        card.innerHTML=head+'<div class="gauge" style="--p:'+num+'"><i>'+Math.round(num)+'</i></div>';
      } else {
        card.innerHTML=head+'<div class="row"><span class="st">'+esc(''+(dv.state||'unknown'))+'</span></div>';
      }
    }
    const dom=card.querySelector('.dom');if(dom){dom.style.cursor='pointer';dom.onclick=()=>moveDevice(dv);}
    return card;
  }
  function moveDevice(dv){
    const r=prompt('Room for "'+(dv.name||dv.id)+'" (blank = Unassigned):', dv.room||'');
    if(r===null)return;
    api('/v1/devices/room',{method:'POST',body:JSON.stringify({device_id:dv.id,room:r.trim()})}).then(()=>loadDevices());
  }
  // ── Generic sub-tab framework (reused across main tabs) ────────────────
  function mountSubtabs(host, tabs, initial, onSwitch){
    host.innerHTML='';
    const bar=document.createElement('div');bar.className='subtabs';
    const body=document.createElement('div');body.className='subbody';
    tabs.forEach(t=>{
      const b=document.createElement('button');b.className='subtab'+(t.id===initial?' active':'');b.textContent=t.label;
      b.onclick=()=>{if(onSwitch)onSwitch(t.id);bar.querySelectorAll('.subtab').forEach(x=>x.classList.remove('active'));b.classList.add('active');body.className='subbody';body.innerHTML='';t.render(body);};
      bar.appendChild(b);
    });
    host.appendChild(bar);host.appendChild(body);
    (tabs.find(t=>t.id===initial)||tabs[0]).render(body);
  }
  // ── Home: live status strip + sub-tabbed command console ───────────────
  let _homeSub='devices';
  function homeStatusStrip(rooms, st){
    const devs=[];rooms.forEach(r=>(r.devices||[]).forEach(d=>devs.push(d)));
    const on=devs.filter(d=>(''+(d.state||'')).toUpperCase()==='ON').length;
    const off=devs.filter(d=>(''+(d.state||'')).toUpperCase()==='OFF').length;
    const idle=devs.length-on-off;
    const strip=document.createElement('div');strip.className='livestrip';
    const conn=st&&st.connected;
    strip.innerHTML='<span class="lstitle">&#9670; ELI HOME</span>'
      +'<span class="lspill"><span class="ld '+(conn?'live':'warn')+'"></span>'+(conn?('broker '+esc(st.broker||'online')):'no broker')+'</span>'
      +'<span class="lspill"><span class="ld live"></span><b>'+on+'</b> on</span>'
      +'<span class="lspill"><span class="ld off"></span><b>'+off+'</b> off</span>'
      +(idle?'<span class="lspill"><span class="ld warn"></span><b>'+idle+'</b> idle</span>':'')
      +'<span class="lspill"><b>'+devs.length+'</b> devices</span>'
      +'<span class="lspill" id="ls-autos"><b>&middot;</b> automations</span>';
    api('/v1/home/automations').then(d=>{const n=((d&&d.automations)||[]).length;const e=$('#ls-autos');if(e)e.innerHTML='<b>'+n+'</b> automations';}).catch(()=>{});
    return strip;
  }
  function renderDevices(rooms, st){
    const h=$('#devices');h.innerHTML='';
    h.appendChild(homeStatusStrip(rooms, st));
    const sg=document.createElement('div');sg.id='home-sugg';h.appendChild(sg);loadHomeSuggestions();
    const shell=document.createElement('div');shell.className='subwrap';h.appendChild(shell);
    mountSubtabs(shell,[
      {id:'devices',label:'Devices',render:el=>paneDevices(el,rooms,st)},
      {id:'autos',label:'Automations',render:paneAutomations},
      {id:'scenes',label:'Scenes',render:paneScenes},
      {id:'discover',label:'Discover & Setup',render:paneDiscover},
      {id:'advanced',label:'Advanced',render:paneAdvanced},
    ],_homeSub,(id)=>{_homeSub=id;});
  }
  function paneDevices(el, rooms, st){
    const total=rooms.reduce((n,r)=>n+(r.devices?r.devices.length:0),0);
    if(!total){const m=document.createElement('div');m.className='muted';m.style.cssText='padding:22px 0;line-height:1.7';
      m.innerHTML='No devices yet. Open <b>Discover &amp; Setup</b> to find media devices (AirPlay, Fire TV, Cast, UPnP) on your network, or connect an MQTT broker for switches &amp; lights.';el.appendChild(m);}
    rooms.forEach(rm=>{
      const sec=document.createElement('div');sec.className='roomsec';
      const hd=document.createElement('div');hd.className='roomhd';
      hd.innerHTML='<span class="roomnm">'+esc(rm.room)+'</span><span class="roomct">'+(rm.devices?rm.devices.length:0)+'</span>';
      const on=document.createElement('button');on.className='roombtn';on.textContent='All on';on.onclick=()=>ctlRoom(rm.room,'on');
      const off=document.createElement('button');off.className='roombtn';off.textContent='All off';off.onclick=()=>ctlRoom(rm.room,'off');
      hd.appendChild(on);hd.appendChild(off);sec.appendChild(hd);
      const grid=document.createElement('div');grid.className='grid';(rm.devices||[]).forEach(dv=>grid.appendChild(devCard(dv)));sec.appendChild(grid);
      el.appendChild(sec);
    });
    const foot=document.createElement('div');foot.className='afilter';foot.style.marginTop='14px';
    foot.innerHTML='<button class="cbtn" onclick="loadDevices()">&#10227; Refresh</button><button onclick="addDevicePrompt()">+ Add device manually</button>';
    el.appendChild(foot);
    const slot=document.createElement('div');slot.id='dev-add';el.appendChild(slot);
  }
  function paneScenes(el){
    el.innerHTML='<div class="jhead">Scenes</div><div id="scenes-panel"><div class="muted">Loading…</div></div>';
    loadScenesPanel();
  }
  function paneAutomations(el){
    el.innerHTML='<div class="jhead">Active automations</div><div id="autos-list"><div class="muted">Loading…</div></div>'
      +'<div class="jhead">New automation</div><div id="autos-builder"></div>';
    loadAutomationsList();
    Promise.all([api('/v1/devices'),api('/v1/home/scenes')]).then(r=>{
      _bdevs=((r[0]&&r[0].devices)||[]).map(d=>({id:d.id,name:d.name||d.id}));
      _bscenes=((r[1]&&r[1].scenes)||[]).map(s=>s.name);
      renderAutoBuilder($('#autos-builder'));
    }).catch(()=>{});
  }
  function loadAutomationsList(){
    api('/v1/home/automations').then(d=>{
      const box=$('#autos-list');if(!box)return;const autos=(d&&d.automations)||[];
      if(!autos.length){box.innerHTML='<div class="muted">No automations yet — create one below.</div>';return;}
      let h='';autos.forEach(a=>{const dot=a.enabled?'<span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:#2ec07a;box-shadow:0 0 8px #2ec07a;margin-right:8px"></span>':'<span style="opacity:.4;margin-right:8px">○</span>';
        h+='<div class="src"><div class="sh"><span>'+dot+esc(a.name||a.id)+'</span><span class="link au-rm" data-id="'+esc(a.id)+'">remove</span></div></div>';});
      box.innerHTML=h;
      box.querySelectorAll('.au-rm').forEach(b=>b.onclick=()=>api('/v1/home/automations/remove',{method:'POST',body:JSON.stringify({id:b.dataset.id})}).then(()=>{loadAutomationsList();}));
    }).catch(()=>{});
  }
  function renderAutoBuilder(box){
    if(!box)return;
    box.innerHTML='<div class="syscard">'+
      '<div class="rrow"><span class="rnote" style="align-self:center;min-width:42px">When</span><select id="au-trig" onchange="autoTrigFields()"><option value="time">at a time</option><option value="sunset">at sunset</option><option value="sunrise">at sunrise</option><option value="device_state">a device turns on/off</option></select><span id="au-tf"></span></div>'+
      '<div class="rrow"><span class="rnote" style="align-self:center;min-width:42px">Then</span><select id="au-act" onchange="autoActFields()"><option value="device">control a device</option><option value="scene">activate a scene</option></select><span id="au-af"></span></div>'+
      '<div class="rrow"><span class="rnote" style="align-self:center;min-width:42px">Only if</span><select id="au-cond"><option value="">(always)</option>'+_bdevs.map(d=>'<option value="'+esc(d.id)+'">'+esc(d.name)+'</option>').join('')+'</select><select id="au-condstate"><option value="ON">is on</option><option value="OFF">is off</option></select></div>'+
      '<div class="rrow"><button onclick="createAutomation()">Create automation</button><span id="au-status" class="rnote" style="align-self:center"></span></div></div>';
    autoTrigFields();autoActFields();
  }
  function paneDiscover(el){
    el.innerHTML='<div class="jhead">Find devices on your network</div>'+
      '<div class="syscard"><p class="rnote" style="margin:0 0 10px;line-height:1.6">Scan via mDNS + UPnP for media devices (AirPlay, Fire TV, Chromecast, UPnP/DLNA) and MQTT brokers. Add what you find — controlled locally, never the cloud.</p>'+
      '<button class="cbtn" id="mq-find" onclick="discoverDevices()">&#128270; Find on my network</button><div id="mq-found"></div></div>'+
      '<div class="jhead">MQTT broker — switches &amp; lights</div><div id="broker-cfg"></div>';
    renderBrokerCfg($('#broker-cfg'));
  }
  function paneAdvanced(el){
    el.innerHTML='<div class="jhead">Location — for sun-based automations</div>'+
      '<div class="syscard"><div class="rrow"><input id="loc-lat" placeholder="latitude" style="max-width:140px"><input id="loc-lon" placeholder="longitude" style="max-width:140px">'+
      '<button class="cbtn" onclick="useMyLocation()">&#128205; Use my location</button><button onclick="saveLocation()">Save</button></div><div id="loc-status" class="rnote"></div></div>'+
      '<div class="jhead">Broker / connection</div><div id="broker-cfg2"></div>';
    renderBrokerCfg($('#broker-cfg2'));
  }
  function renderBrokerCfg(box, vals, err){
    if(!box)return; vals=vals||{};
    api('/v1/devices/status').then(s=>{
      const st=(s&&s.status)||{};
      box.innerHTML='<div class="syscard">'+
        (st.configured?('<div class="rnote" style="margin-bottom:10px">'+(st.connected?'<span style="color:#2ec07a">&#9679; connected to '+esc(st.broker||'')+'</span>':'<span style="color:#e0a72e">&#9675; configured ('+esc(st.broker||'')+') — not connected</span>')+'</div>'):'')+
        (err?'<div class="banner bad" style="margin:0 0 12px">'+esc(err)+'</div>':'')+
        '<label>Broker host</label><input id="mq_host" autocomplete="off" placeholder="192.168.1.50 or mosquitto.local" value="'+esc(vals.host||st.brokerHost||'')+'">'+
        '<label>Port</label><input id="mq_port" value="'+esc(vals.port||'1883')+'">'+
        '<label>Username (optional)</label><input id="mq_user" autocomplete="off" value="'+esc(vals.username||'')+'">'+
        '<label>Password (optional)</label><input id="mq_pass" type="password" autocomplete="new-password" value="'+esc(vals.password||'')+'">'+
        '<label>Discovery prefix (optional — auto-finds MQTT devices)</label><input id="mq_disc" placeholder="leave blank for manual devices" value="'+esc(vals.discovery_prefix||'')+'">'+
        '<div class="rrow" style="margin-top:14px"><button id="mq-save" onclick="saveDevConfig()">Save &amp; connect</button>'+
        (st.connected?'<button class="cbtn" onclick="api(\\'/v1/devices/disconnect\\',{method:\\'POST\\'}).then(loadDevices)">Disconnect</button>':'')+'</div></div>';
    }).catch(()=>{});
  }
  /* scenes + automation builder state */
  let _bdevs=[], _bscenes=[];
  function loadScenesPanel(){
    Promise.all([api('/v1/home/scenes'),api('/v1/devices')]).then(function(res){
      const box=$('#scenes-panel'); if(!box)return;
      const scenes=(res[0]&&res[0].scenes)||[], devs=((res[1]&&res[1].devices)||[]);
      _bdevs=devs.map(d=>({id:d.id,name:d.name||d.id})); _bscenes=scenes.map(s=>s.name);
      let h='<div class="syscard">';
      if(scenes.length){scenes.forEach(s=>{h+='<div class="src"><div class="sh"><span>'+esc(s.name)+' <span class="rnote">('+(s.actions||[]).length+')</span></span><span><button class="roombtn scene-go" data-id="'+esc(s.id)+'">Activate</button> <span class="link scene-rm" data-id="'+esc(s.id)+'">remove</span></span></div></div>';});}
      else h+='<div class="muted">No scenes yet. Set your devices how you like, then snapshot them as a scene.</div>';
      h+='<div class="rrow" style="margin-top:10px"><input id="sc-name" placeholder="scene name (e.g. Movie mode)"><button onclick="createScene()">Snapshot current state</button></div></div>';
      box.innerHTML=h;
      box.querySelectorAll('.scene-go').forEach(b=>b.onclick=()=>activateScene(b.dataset.id));
      box.querySelectorAll('.scene-rm').forEach(b=>b.onclick=()=>removeScene(b.dataset.id));
    }).catch(()=>{});
  }
  function _devSelect(id){return '<select id="'+id+'">'+_bdevs.map(d=>'<option value="'+esc(d.id)+'">'+esc(d.name)+'</option>').join('')+'</select>';}
  function autoTrigFields(){
    const t=$('#au-trig').value, box=$('#au-tf'); if(!box)return;
    if(t==='time')box.innerHTML='<input id="au-time" placeholder="HH:MM" style="max-width:110px" value="20:00">';
    else if(t==='sunset'||t==='sunrise')box.innerHTML='<input id="au-off" placeholder="offset min (e.g. -15)" style="max-width:150px" value="0">';
    else box.innerHTML=_devSelect('au-tdev')+'<select id="au-tstate"><option value="ON">turns on</option><option value="OFF">turns off</option></select>';
  }
  function autoActFields(){
    const a=$('#au-act').value, box=$('#au-af'); if(!box)return;
    if(a==='device')box.innerHTML=_devSelect('au-adev')+'<select id="au-acmd"><option value="on">on</option><option value="off">off</option></select>';
    else box.innerHTML='<select id="au-ascene">'+_bscenes.map(s=>'<option value="'+esc(s)+'">'+esc(s)+'</option>').join('')+'</select>'+(_bscenes.length?'':'<span class="rnote">create a scene first</span>');
  }
  function createScene(){
    const name=($('#sc-name').value||'').trim(); if(!name)return;
    api('/v1/devices').then(d=>{
      const devs=(d&&d.devices)||[];
      const actions=devs.filter(x=>x.command_topic).map(x=>({device:x.id,command:(''+(x.state||'')).toUpperCase()==='ON'?'on':'off'}));
      api('/v1/home/scenes/add',{method:'POST',body:JSON.stringify({name:name,actions:actions})}).then(()=>{const n=$('#sc-name');if(n)n.value='';loadScenesPanel();});
    }).catch(()=>{});
  }
  function activateScene(id){api('/v1/home/scenes/activate',{method:'POST',body:JSON.stringify({scene:id})}).then(()=>setTimeout(loadDevices,400)).catch(()=>{});}
  function removeScene(id){api('/v1/home/scenes/remove',{method:'POST',body:JSON.stringify({id:id})}).then(()=>loadScenesPanel()).catch(()=>{});}
  function createAutomation(){
    const tt=$('#au-trig').value, at=$('#au-act').value, st=$('#au-status');
    let trigger;
    if(tt==='time')trigger={type:'time',time:($('#au-time').value||'').trim(),days:'daily'};
    else if(tt==='sunset'||tt==='sunrise')trigger={type:'sun',event:tt,offset:parseInt($('#au-off').value||'0',10)||0};
    else trigger={type:'device_state',device:$('#au-tdev').value,state:$('#au-tstate').value};
    let action;
    if(at==='device')action={kind:'device',device:$('#au-adev').value,command:$('#au-acmd').value};
    else action={kind:'scene',scene:$('#au-ascene')?$('#au-ascene').value:''};
    const cd=$('#au-cond')?$('#au-cond').value:'';
    const condition=cd?[{device:cd,state:$('#au-condstate').value}]:[];
    if(st)st.textContent='Creating…';
    api('/v1/home/automations/create',{method:'POST',body:JSON.stringify({name:'',trigger:trigger,action:action,condition:condition})}).then(r=>{
      if(st)st.innerHTML=r.ok?'Created.':'<span style="color:#f87171">'+esc(r.error||'failed')+'</span>';
      if(r.ok)loadHomeSuggestions();
    }).catch(e=>{if(st)st.textContent=''+e;});
  }
  function useMyLocation(){
    const stt=$('#loc-status'); if(!navigator.geolocation){if(stt)stt.textContent='Geolocation not available — type it in.';return;}
    if(stt)stt.textContent='Locating…';
    navigator.geolocation.getCurrentPosition(function(p){
      const la=$('#loc-lat'),lo=$('#loc-lon'); if(la)la.value=p.coords.latitude.toFixed(4); if(lo)lo.value=p.coords.longitude.toFixed(4);
      if(stt)stt.textContent='Got it — click Save.';
    },function(e){if(stt)stt.textContent='Location blocked: '+e.message;});
  }
  function saveLocation(){
    const lat=parseFloat($('#loc-lat').value), lon=parseFloat($('#loc-lon').value), stt=$('#loc-status');
    if(isNaN(lat)||isNaN(lon)){if(stt)stt.textContent='Enter latitude and longitude (or use my location).';return;}
    api('/v1/home/location',{method:'POST',body:JSON.stringify({lat:lat,lon:lon})}).then(r=>{
      if(stt)stt.innerHTML=r.ok?('Saved. Sunrise '+esc((r.sun||{}).sunrise||'?')+' · Sunset '+esc((r.sun||{}).sunset||'?')):'<span style="color:#f87171">failed</span>';
    }).catch(()=>{});
  }
  function ctlRoom(room,cmd){
    api('/v1/devices/room/control',{method:'POST',body:JSON.stringify({room:room,command:cmd})}).then(()=>setTimeout(loadDevices,500));
  }
  function addDevicePrompt(){
    $('#dev-add').innerHTML='<div class="rsec" style="margin-top:12px"><h4>Register a device</h4>'+
      '<div class="rrow"><input id="d-id" placeholder="device id (unique)"><input id="d-name" placeholder="name"></div>'+
      '<div class="rrow"><select id="d-type"><option>light</option><option>switch</option><option>fan</option><option>outlet</option><option>sensor</option></select>'+
      '<input id="d-room" placeholder="room (optional)"></div>'+
      '<div class="rrow"><input id="d-cmd" placeholder="command topic (e.g. home/lamp/set)"><input id="d-state" placeholder="state topic (e.g. home/lamp/state)"></div>'+
      '<div class="rrow"><button onclick="addDevice()">Add</button></div></div>';
  }
  function addDevice(){
    const body={device_id:($('#d-id').value||'').trim(), name:($('#d-name').value||'').trim(),
      type:$('#d-type').value, command_topic:($('#d-cmd').value||'').trim(), state_topic:($('#d-state').value||'').trim(),
      room:($('#d-room').value||'').trim()};
    if(!body.device_id){return;}
    api('/v1/devices/register',{method:'POST',body:JSON.stringify(body)}).then(()=>loadDevices());
  }
  function ctlDev(id,cmd,value){
    const body={device_id:id,command:cmd};if(value!=null)body.value=value;
    api('/v1/devices/control',{method:'POST',body:JSON.stringify(body)}).then(()=>{if(cmd!=='brightness')setTimeout(loadDevices,400);});
  }

  /* system — sub-tabbed console: Live | Model | Network */
  function sgauge(v,label){return '<div><div class="gauge" style="--p:'+(v||0)+'"><i>'+Math.round(v||0)+'</i></div><div class="glabel">'+esc(label)+'</div></div>';}
  let _sysSub='live', _sysData={};
  function loadSystem(){
    Promise.all([api('/v1/system'), api('/v1/net').catch(()=>({})), api('/v1/net/egress').catch(()=>({}))]).then(function(r){
      const d=r[0]||{}; if(!d.ok){$('#system').innerHTML='<div class="err">'+esc(d.error||'unavailable')+'</div>';return;}
      _sysData={s:d.status||{}, net:(r[1]&&r[1].net)||{}, eg:r[2]||{}};
      const s=_sysData.s, g=s.gpu||{}, c=s.cpu||{};
      const host=$('#system');host.innerHTML='';
      const strip=document.createElement('div');strip.className='livestrip';
      strip.innerHTML='<span class="lstitle">&#9670; SYSTEM</span>'
        +'<span class="lspill"><span class="ld live"></span>'+esc(((s.model||{}).name)||'model')+'</span>'
        +(g.name?'<span class="lspill">GPU <b>'+Math.round(g.util_pct||0)+'%</b></span>':'')
        +'<span class="lspill">CPU <b>'+Math.round(c.usage_pct||0)+'%</b></span>'
        +'<span class="lspill">up '+esc(s.uptime||'?')+'</span>';
      host.appendChild(strip);
      const shell=document.createElement('div');shell.className='subwrap';host.appendChild(shell);
      mountSubtabs(shell,[
        {id:'live',label:'Live',render:sysLive},
        {id:'model',label:'Model',render:sysModel},
        {id:'network',label:'Network',render:sysNet},
      ],_sysSub,id=>{_sysSub=id;});
    }).catch(e=>{$('#system').innerHTML='<div class="err">'+esc(''+e)+'</div>';});
  }
  function sysLive(el){
    const s=_sysData.s||{}, g=s.gpu, c=s.cpu, r=s.ram; let h='<div class="grid">';
    if(g){const vp=g.vram_total_mb?Math.round(g.vram_used_mb/g.vram_total_mb*100):0;
      h+='<div class="syscard"><h4>GPU</h4><div class="nm" style="margin-bottom:10px">'+esc(g.name||'')+'</div>'+
        '<div class="row" style="gap:14px">'+sgauge(g.temp_c,'°C')+sgauge(g.util_pct,'% util')+'</div>'+
        '<div class="kv">VRAM<span>'+g.vram_used_mb+' / '+g.vram_total_mb+' MB</span></div><div class="bar"><i style="width:'+vp+'%"></i></div></div>';}
    if(c){h+='<div class="syscard"><h4>CPU</h4><div class="row" style="gap:14px">'+sgauge(c.usage_pct,'% load')+(c.temp_c!=null?sgauge(c.temp_c,'°C'):'')+'</div>'+
        '<div class="kv">Cores<span>'+(c.cores||'?')+'</span></div></div>';}
    if(r){h+='<div class="syscard"><h4>Memory</h4><div class="kv">RAM<span>'+r.used_mb+' / '+r.total_mb+' MB</span></div><div class="bar"><i style="width:'+(r.pct||0)+'%"></i></div></div>';}
    el.innerHTML=h+'</div><div class="rrow" style="margin-top:12px"><button class="cbtn" onclick="loadSystem()">&#10227; Refresh</button></div>';
  }
  function sysModel(el){
    const s=_sysData.s||{}, m=s.model||{};
    el.innerHTML='<div class="jhead">Loaded model</div><div class="syscard"><div class="nm" style="font-size:16px">'+esc(m.name||'—')+'</div>'+
      '<div class="kv">context window<span>'+(m.n_ctx||'?')+' tokens</span></div>'+
      '<div class="kv">GPU layers<span>'+(m.n_gpu_layers!=null?m.n_gpu_layers:'?')+'</span></div>'+
      (m.n_batch?'<div class="kv">batch<span>'+m.n_batch+'</span></div>':'')+
      '<div class="kv">uptime<span>'+esc(s.uptime||'?')+'</span></div></div>'+
      '<div class="rnote">Generation parameters (temperature, top-p, deep thinking…) live in <b>Settings &#8594; Generation</b>. The model loads via the adaptive VRAM-aware loader — no name is hardcoded.</div>';
  }
  function sysNet(el){
    const net=_sysData.net||{}, eg=_sysData.eg||{};
    let h='<div class="jhead">Internet gate</div><div class="syscard">'+
      '<div class="row"><span class="st">'+(net.blocked?'<span style="color:#e0a72e">&#9679; OFFLINE — sealed at the socket</span>':'<span style="color:#2ec07a">&#9679; ONLINE — monitored</span>')+'</span></div>'+
      '<div class="kv">policy<span>'+(net.enabled?'enabled':'disabled')+'</span></div>'+
      '<div class="kv">permitted LAN hosts<span>'+((net.local_services||[]).length)+'</span></div>'+
      '<div class="kv">outbound connections recorded<span>'+(net.egress_total!=null?net.egress_total:(eg.total||0))+'</span></div></div>'+
      '<div class="jhead">Recent egress (live tail)</div><div class="syscard">';
    const list=(eg.egress&&eg.egress.length?eg.egress:(net.egress_recent||[]));
    if(list.length){list.slice().reverse().forEach(x=>{const t=x.ts?new Date(x.ts*1000).toLocaleTimeString():'';
      h+='<div class="src"><div class="sh"><span>&#11167; '+esc(x.host||'')+':'+esc(''+(x.port||''))+'</span><span class="rnote">'+esc(t)+'</span></div></div>';});}
    else h+='<div class="muted">No outbound connections recorded — ELI is offline or hasn\\'t reached out.</div>';
    el.innerHTML=h+'</div>';
  }
  /* research */
  function _ropt(list){return list.length
    ? list.map(c=>'<option value="'+esc(c.corpus)+'">'+esc(c.corpus)+' ('+c.documents+' docs · '+(c.members||0)+' member'+((c.members||0)===1?'':'s')+')</option>').join('')
    : '<option value="" disabled selected>(no corpora yet)</option>';}
  function researchName(){return (localStorage.getItem('eli_name')||uid);}
  function setResearchName(){localStorage.setItem('eli_name',($('#r-name').value||'').trim()||uid);}
  function _curCorpus(){const dd=$('#rq-corpus');return (dd&&dd.value)||($('#ing-name')?($('#ing-name').value||'').trim():'');}
  let _resSub='docs', _resDocs=null, _resAct=null;
  function loadResearch(){
    api('/v1/research/corpora').then(d=>renderResearch((d&&d.corpora)||[]))
      .catch(e=>{$('#research').innerHTML='<div class="err">'+esc(''+e)+'</div>';});
  }
  function renderResearch(list){
    const host=$('#research');host.innerHTML='';
    const strip=document.createElement('div');strip.className='livestrip';
    strip.innerHTML='<span class="lstitle">&#9670; RESEARCH</span><span class="lspill"><b>'+list.length+'</b> corpora</span><span class="lspill"><span class="ld live"></span>local · grounded · cited</span>';
    host.appendChild(strip);
    const hd=document.createElement('div');hd.className='syscard';hd.style.marginBottom='14px';
    hd.innerHTML='<div class="rrow"><span class="rnote" style="align-self:center;min-width:52px">Corpus</span><select id="rq-corpus" onchange="loadCorpusDetail()" style="flex:1">'+_ropt(list)+'</select></div>'+
      '<div class="rrow"><span class="rnote" style="align-self:center;min-width:52px">You</span><input id="r-name" autocomplete="off" placeholder="your name (for who-added-what)" value="'+esc(researchName())+'" onchange="setResearchName()"></div>'+
      '<div class="rnote">Corpora are shared across everyone on this server — ingest, note, and ask together, all local; every contribution is attributed in the tamper-evident Audit trail.</div>';
    host.appendChild(hd);
    const shell=document.createElement('div');shell.className='subwrap';host.appendChild(shell);
    mountSubtabs(shell,[
      {id:'docs',label:'Documents',render:resDocs},
      {id:'ingest',label:'Ingest',render:resIngest},
      {id:'ask',label:'Ask',render:resAsk},
      {id:'activity',label:'Activity',render:resActivity},
    ],_resSub,id=>{_resSub=id;});
    loadCorpusDetail();
  }
  function refreshCorpusSelect(sel){
    api('/v1/research/corpora').then(d=>{
      const dd=$('#rq-corpus'); if(!dd)return;
      dd.innerHTML=_ropt((d&&d.corpora)||[]); if(sel)dd.value=sel;
      loadCorpusDetail();
    }).catch(()=>{});
  }
  function loadCorpusDetail(){
    const c=_curCorpus();
    if(!c){_resDocs={documents:[],members:[]};_resAct={activity:[]};_rerenderRes();return;}
    Promise.all([api('/v1/research/documents?corpus='+encodeURIComponent(c)),
                 api('/v1/research/activity?corpus='+encodeURIComponent(c))])
      .then(function(r){_resDocs=r[0]||{};_resAct=r[1]||{};_rerenderRes();}).catch(()=>{});
  }
  function _rerenderRes(){const b=document.querySelector('#research .subbody');if(!b)return;
    if(_resSub==='docs')resDocs(b); else if(_resSub==='activity')resActivity(b);}
  function resDocs(el){
    const d=_resDocs||{}, members=(d.members)||[], docs=(d.documents)||[], c=_curCorpus();
    let h='<div class="jhead">Documents'+(c?(' — '+esc(c)):'')+'</div>';
    h+='<div class="rnote" style="margin-bottom:8px">Members: '+(members.map(esc).join(', ')||'—')+'</div>';
    if(!docs.length)h+='<div class="muted">No documents yet — add some in the Ingest tab.</div>';
    docs.forEach(doc=>{h+='<div class="src"><div class="sh"><span>'+(doc.kind==='note'?'&#128221; ':'&#128196; ')+esc(doc.source)+'</span><span class="rmv link" data-s="'+esc(doc.source)+'">remove</span></div>'+
      '<div class="sx">added by '+esc(doc.added_by)+' · '+esc(fmtTime(doc.added_at))+' · '+doc.chunks+' chunk(s)</div></div>';});
    el.innerHTML=h;
    el.querySelectorAll('.rmv').forEach(b=>b.onclick=()=>removeDoc(_curCorpus(),b.dataset.s));
  }
  function resIngest(el){
    el.innerHTML='<div class="jhead">Ingest documents</div>'+
      '<div class="syscard"><div class="rrow"><input id="ing-name" autocomplete="off" placeholder="corpus name (new or existing)"></div>'+
      '<div class="rrow"><input id="ing-path" autocomplete="off" placeholder="path under the research root (.pdf / .txt / .md)"><button id="ing-btn" onclick="ingestCorpus()">Ingest</button></div>'+
      '<div class="rnote">Documents must live under the server\\'s research root (default <code>artifacts/research/_sources/</code>, or set <code>ELI_RESEARCH_ROOT</code>). Paths outside it are rejected.</div><div id="ing-status" class="rnote"></div></div>'+
      '<div class="jhead">Add a note</div><div class="syscard"><div class="rrow"><input id="note-title" autocomplete="off" placeholder="note title"></div>'+
      '<div class="rrow"><textarea id="note-text" placeholder="type or paste text to add to the selected corpus…" style="flex:1;min-height:74px;padding:10px;border-radius:9px;border:1px solid var(--line);background:var(--input);color:var(--fg);font-size:14px;font-family:inherit;"></textarea></div>'+
      '<div class="rrow"><button onclick="addNote()">Add note</button><span id="note-status" class="rnote" style="align-self:center"></span></div></div>';
  }
  function resAsk(el){
    el.innerHTML='<div class="jhead">Ask — answered only from the corpus</div>'+
      '<div class="syscard"><div class="rrow"><input id="ask-q" autocomplete="off" placeholder="Ask a question answered only from this corpus…" style="flex:1"><button id="ask-btn" onclick="askCorpus()">Ask</button></div><div id="ask-out"></div></div>';
  }
  function resActivity(el){
    const act=(_resAct&&_resAct.activity)||[];
    let h='<div class="jhead">Activity feed</div>';
    if(!act.length)h+='<div class="muted">No activity yet.</div>';
    act.forEach(ev=>{h+='<div class="arow"><div class="at">'+esc(fmtTime(ev.timestamp))+'</div><div><span class="aa">'+esc(ev.action)+'</span> <span class="au">'+esc(ev.user)+'</span><div class="as">'+esc(ev.detail||'')+'</div></div><div></div></div>';});
    el.innerHTML=h;
  }
  function ingestCorpus(){
    const name=($('#ing-name').value||'').trim(), path=($('#ing-path').value||'').trim();
    const st=$('#ing-status'), btn=$('#ing-btn');
    if(!name||!path){st.textContent='Enter a corpus name and a file/folder path.';return;}
    btn.disabled=true; st.textContent='Ingesting… (extracting + embedding locally, this can take a while)';
    api('/v1/research/ingest',{method:'POST',body:JSON.stringify({corpus:name,path:path,user:researchName()})}).then(d=>{
      if(!d.ok){st.innerHTML='<span style="color:#f87171">'+esc(d.error||'ingest failed')+'</span>';return;}
      st.textContent='Added '+d.docs_added+' document(s), '+d.chunks_added+' chunk(s). Corpus "'+d.corpus+'" now holds '+d.total_chunks+' chunks'+
        (d.skipped&&d.skipped.length?' — skipped '+d.skipped.length+' file(s) with no extractable text':'')+'.';
      refreshCorpusSelect(d.corpus);
    }).catch(e=>{st.innerHTML='<span style="color:#f87171">'+esc(''+e)+'</span>';})
      .finally(()=>{btn.disabled=false;});
  }
  function addNote(){
    const c=_curCorpus(), title=($('#note-title').value||'').trim(), text=($('#note-text').value||'').trim(), st=$('#note-status');
    if(!c){st.textContent='Select a corpus, or type a name in Ingest first.';return;}
    if(!text){st.textContent='Type some note text.';return;}
    st.textContent='Adding…';
    api('/v1/research/note',{method:'POST',body:JSON.stringify({corpus:c,title:title,text:text,user:researchName()})}).then(d=>{
      if(!d.ok){st.innerHTML='<span style="color:#f87171">'+esc(d.error||'failed')+'</span>';return;}
      st.textContent='Note "'+esc(d.note)+'" added.'; $('#note-text').value=''; $('#note-title').value='';
      refreshCorpusSelect(d.corpus);
    }).catch(e=>{st.innerHTML='<span style="color:#f87171">'+esc(''+e)+'</span>';});
  }
  function removeDoc(corpus,source){
    if(!confirm('Remove "'+source+'" from '+corpus+'?'))return;
    api('/v1/research/remove',{method:'POST',body:JSON.stringify({corpus:corpus,source:source,user:researchName()})})
      .then(()=>refreshCorpusSelect(corpus)).catch(()=>{});
  }
  function askCorpus(){
    const q=($('#ask-q').value||'').trim(), out=$('#ask-out'), btn=$('#ask-btn'), corpus=_curCorpus();
    if(!corpus){out.innerHTML='<div class="rnote">Ingest or select a corpus first.</div>';return;}
    if(!q){out.innerHTML='<div class="rnote">Type a question.</div>';return;}
    btn.disabled=true; out.innerHTML='<div class="rnote">Searching the corpus and synthesising with the local model…</div>';
    api('/v1/research/query',{method:'POST',body:JSON.stringify({corpus:corpus,question:q,k:6,user:researchName()})}).then(d=>{
      if(!d.ok){out.innerHTML='<div class="err">'+esc(d.error||'query failed')+'</div>';return;}
      let h='<div class="answer">'+esc(d.answer||'')+'</div>';
      (d.sources||[]).forEach(s=>{h+='<div class="src"><div class="sh"><span>'+esc(s.source||'?')+'</span><span>'+(s.score!=null?esc(s.score):'')+'</span></div><div class="sx">'+esc(s.excerpt||'')+'</div></div>';});
      out.innerHTML=h; loadCorpusDetail();
    }).catch(e=>{out.innerHTML='<div class="err">'+esc(''+e)+'</div>';})
      .finally(()=>{btn.disabled=false;});
  }

  function loadHomeSuggestions(){
    Promise.all([api('/v1/home/suggestions'),api('/v1/home/automations')]).then(function(res){
      const box=$('#home-sugg'); if(!box)return;
      const s=(res[0]&&res[0].suggestions)||[], autos=(res[1]&&res[1].automations)||[];
      let h='';
      if(s.length){
        h+='<div class="syscard" style="margin-bottom:14px"><h4>&#10024; ELI suggests</h4>';
        s.forEach(x=>{h+='<div class="src"><div class="sh"><span class="sx">'+esc(x.text)+'</span>'+
          '<button class="roombtn sugg-accept" data-dev="'+esc(x.device)+'" data-hour="'+(x.hour||0)+'" data-name="'+esc(x.name||'')+'">Automate</button></div></div>';});
        h+='</div>';
      }
      if(autos.length){
        h+='<div class="syscard" style="margin-bottom:14px"><h4>&#9201; Automations</h4>';
        autos.forEach(a=>{h+='<div class="src"><div class="sh"><span>'+(a.enabled?'':'&#9208; ')+esc(a.name||a.id)+'</span>'+
          '<span><label class="sw"><input type="checkbox" class="auto-toggle" data-id="'+esc(a.id)+'" '+(a.enabled?'checked':'')+'><span></span></label> <span class="link auto-rm" data-id="'+esc(a.id)+'">remove</span></span></div></div>';});
        h+='</div>';
      }
      box.innerHTML=h;
      box.querySelectorAll('.sugg-accept').forEach(b=>b.onclick=()=>acceptSugg(b.dataset.dev,+b.dataset.hour,b.dataset.name));
      box.querySelectorAll('.auto-toggle').forEach(c=>c.onchange=()=>toggleAuto(c.dataset.id,c.checked));
      box.querySelectorAll('.auto-rm').forEach(r=>r.onclick=()=>removeAuto(r.dataset.id));
    }).catch(()=>{});
  }
  function acceptSugg(device,hour,name){api('/v1/home/suggestions/accept',{method:'POST',body:JSON.stringify({device:device,command:'on',hour:hour,name:name})}).then(()=>loadHomeSuggestions()).catch(()=>{});}
  function toggleAuto(id,en){api('/v1/home/automations/toggle',{method:'POST',body:JSON.stringify({id:id,enabled:en})}).catch(()=>{});}
  function removeAuto(id){api('/v1/home/automations/remove',{method:'POST',body:JSON.stringify({id:id})}).then(()=>loadHomeSuggestions()).catch(()=>{});}
  window.renderDevConfig=renderDevConfig; window.saveDevConfig=saveDevConfig; window.ctlDev=ctlDev; window.addDevicePrompt=addDevicePrompt; window.addDevice=addDevice; window.loadDevices=loadDevices; window.ctlRoom=ctlRoom; window.moveDevice=moveDevice; window.discoverDevices=discoverDevices; window.useBroker=useBroker; window.openDiscover=openDiscover; window.addDiscovered=addDiscovered; window.pairDialog=pairDialog;
  window.loadScenesPanel=loadScenesPanel; window.createScene=createScene; window.activateScene=activateScene; window.removeScene=removeScene; window.autoTrigFields=autoTrigFields; window.autoActFields=autoActFields; window.createAutomation=createAutomation; window.useMyLocation=useMyLocation; window.saveLocation=saveLocation;
  /* audit — tamper-evident trail + chain verification (Events | Integrity) */
  let auditUser='', _audSub='events', _audData=null;
  function fmtTime(ts){try{return new Date(ts*1000).toLocaleString();}catch(_e){return ''+ts;}}
  function loadAudit(){
    const q=auditUser?('?user_id='+encodeURIComponent(auditUser)):'';
    api('/v1/audit'+q).then(renderAudit)
      .catch(e=>{$('#audit').innerHTML='<div class="err">'+esc(''+e)+'</div>';});
  }
  function renderAudit(d){
    if(!d||!d.ok){$('#audit').innerHTML='<div class="err">'+esc((d&&d.error)||'unavailable')+'</div>';return;}
    _audData=d; const ig=d.integrity||{};
    const host=$('#audit');host.innerHTML='';
    const strip=document.createElement('div');strip.className='livestrip';
    strip.innerHTML='<span class="lstitle">&#9670; AUDIT</span>'
      +(ig.ok?'<span class="lspill"><span class="ld live"></span>chain intact</span>':'<span class="lspill"><span class="ld warn"></span>TAMPERING</span>')
      +'<span class="lspill"><b>'+(ig.chained||0)+'</b> events</span>'
      +'<span class="lspill">'+(ig.keyed?'HMAC-keyed':'hash-chained')+'</span>';
    host.appendChild(strip);
    const shell=document.createElement('div');shell.className='subwrap';host.appendChild(shell);
    mountSubtabs(shell,[
      {id:'events',label:'Events',render:audEvents},
      {id:'integrity',label:'Integrity',render:audIntegrity},
    ],_audSub,id=>{_audSub=id;});
  }
  function audEvents(el){
    const d=_audData||{};
    let h='<div class="afilter" style="margin-bottom:10px"><input id="aud-user" autocomplete="off" placeholder="filter by user id…" value="'+esc(auditUser)+'"><button onclick="filterAudit()">Filter</button><button onclick="clearAudit()">All</button></div>';
    const ev=d.events||[];
    if(!ev.length)h+='<div class="muted">No audit events yet.</div>';
    ev.forEach(e=>{const oc=(e.outcome||'').toLowerCase();
      h+='<div class="arow"><div><div class="at">'+esc(fmtTime(e.timestamp))+'</div>'+(e.user_id?'<div class="au">'+esc(e.user_id)+'</div>':'')+'</div>'+
         '<div><span class="aa">'+esc(e.action||e.event_type||'')+'</span>'+(e.subject?' <span class="as">'+esc(e.subject)+'</span>':'')+'<div class="at">'+esc(e.source||'')+'</div></div>'+
         '<div class="ao '+esc(oc)+'">'+esc(e.outcome||'')+'</div></div>';});
    el.innerHTML=h;
  }
  function audIntegrity(el){
    const ig=(_audData&&_audData.integrity)||{};
    let h='<div class="jhead">Chain integrity</div>';
    if(ig.ok)h+='<div class="abadge ok"><span class="dot"></span><span>Audit chain verified intact — '+(ig.chained||0)+' event(s) '+(ig.keyed?'HMAC-keyed':'hash-chained')+(ig.legacy?(', '+ig.legacy+' legacy'):'')+'. No tampering detected.</span></div>';
    else{const b=ig.first_break||{};h+='<div class="abadge bad"><span class="dot"></span><span>TAMPERING DETECTED at event #'+esc(b.id)+' — '+esc(b.reason||'chain broken')+'.</span></div>';}
    h+='<div class="syscard"><div class="kv">chained events<span>'+(ig.chained||0)+'</span></div>'+
       '<div class="kv">keying<span>'+(ig.keyed?'HMAC-SHA-256':'hash-only')+'</span></div>'+
       (ig.legacy?'<div class="kv">legacy (unkeyed)<span>'+ig.legacy+'</span></div>':'')+'</div>'+
       '<div class="rnote">Every event is hash-chained to the one before it and HMAC-keyed with a secret stored separately from the database — so any edited, deleted, or reordered row is detected.</div>';
    el.innerHTML=h;
  }
  function filterAudit(){auditUser=($('#aud-user').value||'').trim();loadAudit();}
  function clearAudit(){auditUser='';loadAudit();}

  /* admin — enterprise console: integrity + users + approval/risk gate */
  function loadAdmin(){
    api('/v1/admin/overview').then(renderAdmin)
      .catch(e=>{$('#admin').innerHTML='<div class="err">'+esc(''+e)+'</div>';});
  }
  let _admData=null, _admSub='console';
  function renderAdmin(d){
    if(!d||!d.ok){$('#admin').innerHTML='<div class="err">'+esc((d&&d.error)||'unavailable')+'</div>';return;}
    _admData=d; const ig=d.integrity||{}, t=d.totals||{};
    const host=$('#admin');host.innerHTML='';
    const strip=document.createElement('div');strip.className='livestrip';
    strip.innerHTML='<span class="lstitle">&#9670; ADMIN</span>'
      +(ig.ok?'<span class="lspill"><span class="ld live"></span>chain intact</span>':'<span class="lspill"><span class="ld warn"></span>TAMPERING</span>')
      +'<span class="lspill"><b>'+(t.events||0)+'</b> events</span>'
      +'<span class="lspill"><b>'+(t.users||0)+'</b> users</span>'
      +'<span class="lspill"><b>'+(t.failed||0)+'</b> failures</span>';
    host.appendChild(strip);
    const shell=document.createElement('div');shell.className='subwrap';host.appendChild(shell);
    mountSubtabs(shell,[
      {id:'console',label:'Console',render:admConsole},
      {id:'users',label:'Users',render:admUsers},
      {id:'policy',label:'Risk Policy',render:admPolicy},
    ],_admSub,id=>{_admSub=id;});
  }
  function admConsole(el){
    const d=_admData||{}, ig=d.integrity||{}, t=d.totals||{};
    let h='';
    if(ig.ok)h+='<div class="abadge ok"><span class="dot"></span><span>Audit chain verified intact — '+(ig.chained||0)+' '+(ig.keyed?'HMAC-keyed':'hash-chained')+' event(s). No tampering.</span></div>';
    else{const b=ig.first_break||{};h+='<div class="abadge bad"><span class="dot"></span><span>TAMPERING DETECTED at event #'+esc(b.id)+' — '+esc(b.reason||'')+'.</span></div>';}
    h+='<div class="adtot"><div class="syscard"><div class="big">'+(t.events||0)+'</div><div class="lbl">events</div></div>'+
       '<div class="syscard"><div class="big">'+(t.users||0)+'</div><div class="lbl">users</div></div>'+
       '<div class="syscard"><div class="big">'+(t.failed||0)+'</div><div class="lbl">failures</div></div></div>';
    el.innerHTML=h;
  }
  function admUsers(el){
    const d=_admData||{}, users=d.users||[], rbac=d.rbac||{enabled:false,accounts:[]};
    let h='<div class="jhead">User activity</div><div class="syscard"><div class="uhdr"><span>user</span><span>events</span><span>failed</span><span>last seen</span></div>'+
      (users.length?'':'<div class="muted">No activity yet.</div>')+'<div id="ulist"></div><div id="udetail"></div></div>';
    h+='<div class="jhead">Accounts &amp; access (RBAC)</div><div class="syscard">'+
      '<div class="abadge '+(rbac.enabled?'ok':'bad')+'" style="margin:6px 0"><span class="dot"></span><span>'+
      (rbac.enabled?('Role-based access ON — '+(rbac.accounts||[]).length+' account(s). Each token maps to a user + role; attribution is authenticated.')
       :'Single-operator mode — the operator is admin. Add a user below to enable role-based access (admin / member).')+'</span></div>'+
      '<div id="acctlist"></div>'+
      '<div class="afilter" style="margin-top:10px"><input id="nu-id" autocomplete="off" placeholder="new user id"><select id="nu-role"><option value="viewer">viewer</option><option value="member" selected>member</option><option value="admin">admin</option></select><button onclick="addUser()">Add user</button></div>'+
      '<div id="nu-token" class="rnote"></div></div>';
    el.innerHTML=h;
    const ul=$('#ulist');
    users.forEach(u=>{const row=document.createElement('div');row.className='urow';
      row.innerHTML='<span class="un">'+esc(u.user_id)+'</span><span>'+u.events+'</span><span class="uf '+(u.failed?'bad':'')+'">'+u.failed+'</span><span class="ut">'+esc(fmtTime(u.last_seen))+'</span>';
      row.onclick=()=>drillUser(u.user_id);ul.appendChild(row);});
    const al=$('#acctlist');
    (rbac.accounts||[]).forEach(ac=>{const row=document.createElement('div');row.className='emrow';
      row.innerHTML='<div class="em">'+esc(ac.user_id)+'</div><div class="ec" style="display:flex;justify-content:space-between;align-items:center"><span class="tag '+(ac.role==='admin'?'manual':'auto')+'">'+esc(ac.role)+'</span><span class="rmv link">remove</span></div>';
      row.querySelector('.rmv').onclick=()=>removeUser(ac.user_id);al.appendChild(row);});
  }
  function admPolicy(el){
    const pol=(_admData||{}).policy||{};
    let h='<div class="jhead">Approval / risk gate</div><div class="syscard">';
    if(pol.full_control)h+='<div class="abadge bad" style="margin:6px 0"><span class="dot"></span><span>ELI Full Control is ON — approval barriers lifted (every proposal auto-approved).</span></div>';
    h+='<div class="rnote">Action classes — how the risk gate treats each:</div><div class="pol">';
    (pol.action_classes||[]).forEach(ac=>{const auto=(pol.auto_approve||[]).indexOf(ac)>=0;h+='<span class="tag '+(auto?'auto':'manual')+'">'+esc(ac)+' · '+(auto?'auto-approve':'manual')+'</span>';});
    h+='</div><div class="rnote">Which agent (emitter) may propose which classes:</div>';
    const ep=pol.emitter_policy||{};Object.keys(ep).forEach(em=>{h+='<div class="emrow"><div class="em">'+esc(em)+'</div><div class="ec">'+ep[em].map(esc).join(', ')+'</div></div>';});
    el.innerHTML=h+'</div>';
  }
  function addUser(){
    const id=($('#nu-id').value||'').trim(), role=$('#nu-role').value, box=$('#nu-token');
    if(!id){box.textContent='Enter a user id.';return;}
    api('/v1/admin/users/add',{method:'POST',body:JSON.stringify({user_id:id,role:role})}).then(d=>{
      if(!d.ok){box.innerHTML='<span style="color:#f87171">'+esc(d.error||'failed')+'</span>';return;}
      box.innerHTML='Created <b>'+esc(d.user_id)+'</b> ('+esc(d.role)+'). Share this token — shown ONCE: <code style="color:#a3be8c">'+esc(d.token)+'</code>';
      $('#nu-id').value='';
      const al=$('#acctlist'); if(al){const row=document.createElement('div');row.className='emrow';row.innerHTML='<div class="em">'+esc(d.user_id)+'</div><div class="ec"><span class="tag '+(d.role==='admin'?'manual':'auto')+'">'+esc(d.role)+'</span></div>';al.appendChild(row);}
    }).catch(e=>{box.innerHTML='<span style="color:#f87171">'+esc(''+e)+'</span>';});
  }
  function removeUser(id){
    if(!confirm('Remove user "'+id+'"? Their token stops working.'))return;
    api('/v1/admin/users/remove',{method:'POST',body:JSON.stringify({user_id:id})}).then(d=>{
      if(!d.ok){alert(d.error||'failed');return;} loadAdmin();
    }).catch(()=>{});
  }
  function drillUser(u){
    const box=$('#udetail'); if(!box)return; box.innerHTML='<div class="muted">Loading '+esc(u)+'…</div>';
    api('/v1/admin/user?user_id='+encodeURIComponent(u)+'&limit=40').then(d=>{
      if(!d.ok){box.innerHTML='<div class="err">'+esc(d.error||'failed')+'</div>';return;}
      let h='<div class="rnote" style="margin-top:10px">Recent activity — '+esc(u)+'</div>';
      const ev=d.events||[];
      if(!ev.length) h+='<div class="muted">No events.</div>';
      ev.forEach(e=>{const oc=(e.outcome||'').toLowerCase();
        h+='<div class="arow"><div class="at">'+esc(fmtTime(e.timestamp))+'</div><div><span class="aa">'+esc(e.action||e.event_type||'')+'</span>'+(e.subject?' <span class="as">'+esc(e.subject)+'</span>':'')+'<div class="at">'+esc(e.source||'')+'</div></div><div class="ao '+esc(oc)+'">'+esc(e.outcome||'')+'</div></div>';});
      box.innerHTML=h;
    }).catch(e=>{box.innerHTML='<div class="err">'+esc(''+e)+'</div>';});
  }

  window.ingestCorpus=ingestCorpus; window.askCorpus=askCorpus; window.addNote=addNote; window.removeDoc=removeDoc; window.loadCorpusDetail=loadCorpusDetail; window.setResearchName=setResearchName;
  window.filterAudit=filterAudit; window.clearAudit=clearAudit; window.loadAdmin=loadAdmin; window.drillUser=drillUser; window.addUser=addUser; window.removeUser=removeUser;

  /* overview dashboard */
  let ovClockTimer=null;
  function ovGauge(v,label){v=Math.round(v||0);return '<div class="ovg"><div class="ring" style="--p:'+Math.max(0,Math.min(100,v))+'"><span>'+v+'</span></div><div class="ovg-l">'+esc(label)+'</div></div>';}
  function tickClock(){const el=$('#ov-clock');if(!el)return;const d=new Date();const t=el.querySelector('.t'),dd=el.querySelector('.d');if(t)t.textContent=d.toLocaleTimeString();if(dd)dd.textContent=d.toLocaleDateString(undefined,{weekday:'long',month:'short',day:'numeric'});}
  function loadOverview(){
    Promise.all([api('/v1/system').catch(()=>({})),api('/v1/audit?limit=8').catch(()=>({})),
                 api('/v1/devices').catch(()=>({})),api('/v1/research/corpora').catch(()=>({})),
                 api('/v1/net').catch(()=>({}))])
      .then(([sys,aud,dev,res,net])=>renderOverview(sys,aud,dev,res,net))
      .catch(e=>{$('#overview').innerHTML='<div class="err">'+esc(''+e)+'</div>';});
  }
  function setNet(on){
    const reason = on ? (prompt('Enable internet access for ELI?\\nOptionally note why (logged to the audit trail):','')||'') : '';
    if(on && reason===null) return;
    api('/v1/net',{method:'POST',body:JSON.stringify({enabled:!!on,reason:reason})})
      .then(d=>{ if(!d||!d.ok){alert('Could not change internet access: '+esc((d&&d.error)||'unknown'));} loadOverview(); })
      .catch(e=>{alert('Could not change internet access: '+esc(''+e)); loadOverview();});
  }
  window.setNet=setNet;
  function ovCtl(id,cmd){api('/v1/devices/control',{method:'POST',body:JSON.stringify({device_id:id,command:cmd})}).then(()=>setTimeout(loadOverview,400)).catch(()=>{});}
  window.ovCtl=ovCtl;
  function renderOverview(sys,aud,dev,res,net){
    const s=(sys&&sys.status)||{}, g=s.gpu, c=s.cpu, r=s.ram, m=s.model||{};
    const ig=(aud&&aud.integrity)||{}, ev=(aud&&aud.events)||[];
    const devs=(dev&&dev.devices)||[], on=devs.filter(d=>(''+(d.state||'')).toUpperCase()==='ON').length;
    const corpora=(res&&res.corpora)||[];
    const n=(net&&net.net)||{}, netOn=!!n.enabled, isAdmin=(window.MY_ROLE==='admin'||!window.MY_ROLE);
    let h='<div class="ovwrap"><div class="ovhero">'+
      '<div id="ov-clock" class="clock"><div class="t">--:--:--</div><div class="d"></div></div>'+
      '<div class="ovstat">'+
        '<div class="ovstat-row"><span class="dot ok"></span> System online &middot; model <b>'+esc(m.name||'—')+'</b></div>'+
        '<div class="ovstat-row"><span class="dot '+(ig.ok?'ok':'bad')+'"></span> Audit '+(ig.ok?('verified &middot; '+(ig.chained||0)+' events'):'TAMPER DETECTED')+'</div>'+
        '<div class="ovstat-row"><span class="dot '+(netOn?'warn':'ok')+'"></span> Internet '+(netOn?('<b>ON</b> &middot; '+(n.egress_total||0)+' outbound logged'):'off &middot; offline-by-default')+(n.override_active?' &middot; temp-allow active':'')+'</div>'+
        '<div class="ovstat-row"><span class="dot ok"></span> '+devs.length+' device(s) &middot; '+on+' on &middot; '+corpora.length+' corpora</div>'+
      '</div></div>';
    h+='<div class="ov-grid"><div class="widget"><h4>Internet access</h4>'+
       '<div class="netrow"><span class="netstate '+(netOn?'on':'off')+'">'+(netOn?'ENABLED':'OFF')+'</span>'+
       '<button class="netbtn '+(netOn?'on':'off')+'" '+(isAdmin?'':'disabled title="Admin only"')+' onclick="setNet('+(netOn?'false':'true')+')">'+(netOn?'Turn off':'Turn on')+'</button></div>'+
       (netOn&&(n.egress_recent||[]).length?('<div class="netegress">Recent outbound: '+(n.egress_recent||[]).slice(-5).map(e=>esc(e.host+(e.port?(':'+e.port):''))).join(' &middot; ')+'</div>'):'')+
       '<div class="muted" style="margin-top:6px">ELI is offline-by-default and hard-gated at the socket boundary. Turning this on lets ELI reach the internet — and every outbound connection (host:port) is recorded to the tamper-evident audit trail, as is the on/off flip itself.</div></div>';
    h+='<div class="widget"><h4>Vitals</h4><div class="ovgauges">';
    if(g){h+=ovGauge(g.util_pct,'GPU')+ovGauge(g.temp_c,'GPU °C');}
    if(c){h+=ovGauge(c.usage_pct,'CPU');}
    if(r){h+=ovGauge(r.pct!=null?r.pct:(r.total_mb?Math.round(r.used_mb/r.total_mb*100):0),'RAM');}
    if(!g&&!c&&!r)h+='<div class="muted">Telemetry unavailable.</div>';
    h+='</div></div>';
    h+='<div class="widget"><h4>Quick actions</h4><div class="qa">'+
       '<button class="qchip" onclick="switchTab(\\'chat\\')">&#128172; Chat</button>'+
       '<button class="qchip" onclick="switchTab(\\'devices\\')">&#127968; Home</button>'+
       '<button class="qchip" onclick="switchTab(\\'research\\')">&#128300; Research</button>'+
       '<button class="qchip" onclick="switchTab(\\'system\\')">&#128202; Telemetry</button>'+
       '<button class="qchip" onclick="switchTab(\\'audit\\')">&#128737; Audit</button>'+
       '</div></div>';
    const ctl=devs.filter(x=>x.command_topic||['airplay','firetv','cast','upnp'].indexOf(x.driver)>=0).slice(0,8);
    h+='<div class="widget"><h4>Quick controls</h4>';
    if(!ctl.length)h+='<div class="muted">No controllable devices yet — add some in Home.</div>';
    ctl.forEach(x=>{const xon=(''+(x.state||'')).toUpperCase()==='ON';
      const media=['airplay','firetv','cast','upnp'].indexOf(x.driver)>=0;
      h+='<div class="ovact"><span class="aa">'+esc(x.name||x.id)+'</span>'+
        (media?('<span><button class="roombtn" onclick="ovCtl(\\''+esc(x.id)+'\\',\\'play\\')">&#9654;</button> <button class="roombtn" onclick="ovCtl(\\''+esc(x.id)+'\\',\\'pause\\')">&#9208;</button></span>')
          :('<button class="roombtn" onclick="ovCtl(\\''+esc(x.id)+'\\',\\''+(xon?'off':'on')+'\\')">'+(xon?'Turn off':'Turn on')+'</button>'))+'</div>';});
    h+='</div>';
    h+='<div class="widget wide"><h4>Recent activity</h4>';
    if(!ev.length)h+='<div class="muted">No activity yet.</div>';
    ev.slice(0,8).forEach(e=>{h+='<div class="ovact"><span class="aa">'+esc(e.action||e.event_type||'')+'</span><span class="au">'+esc(e.user_id||'system')+'</span><span class="at">'+esc(fmtTime(e.timestamp))+'</span></div>';});
    h+='</div></div></div>';
    $('#overview').innerHTML=h;
    tickClock(); if(ovClockTimer)clearInterval(ovClockTimer); ovClockTimer=setInterval(tickClock,1000);
  }
  window.loadOverview=loadOverview;

  /* who am I — reflect role; a read-only viewer can browse dashboards but not act */
  (function initMe(){
    api('/v1/me').then(m=>{
      if(!m||!m.ok)return;
      window.MY_ROLE=m.role;
      const rb=$('#rolebadge'); if(rb) rb.textContent=m.role+(m.role==='viewer'?' · read-only':' · local');
      if(m.role==='viewer'){
        const send=$('#send'), box=$('#box'), mic=$('#mic');
        if(send){send.disabled=true;send.textContent='read-only';}
        if(box){box.disabled=true;box.placeholder='Read-only (viewer) — browse dashboards; you can\\'t send actions.';}
        if(mic){mic.disabled=true;}
        const adminBtn=document.querySelector('nav.tabs button[data-tab="admin"]'); if(adminBtn) adminBtn.style.display='none';
      }
    }).catch(()=>{});
  })();
</script></body></html>"""

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

class DevicePair(BaseModel):
    device_id: str
    code: Optional[str] = None    # PIN for AirPlay; omit to begin pairing

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
    return HTMLResponse(_WEB_UI)

# ── PWA: make the web app installable (home-screen icon) + an offline shell ──
_PWA_ICON = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">'
    '<rect width="512" height="512" rx="96" fill="#05070d"/>'
    '<text x="50%" y="56%" font-family="monospace" font-size="240" font-weight="800" '
    'text-anchor="middle" fill="#22d3ee">E</text>'
    '<rect x="96" y="372" width="320" height="14" rx="7" fill="#f637ec"/></svg>'
)
_PWA_MANIFEST = {
    "name": "ELI", "short_name": "ELI", "start_url": "/", "scope": "/",
    "display": "standalone", "background_color": "#05070d", "theme_color": "#05070d",
    "icons": [{"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any maskable"}],
}
_SERVICE_WORKER = """
const C='eli-shell-v1';
self.addEventListener('install',e=>self.skipWaiting());
self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));
self.addEventListener('fetch',e=>{
  if(e.request.method!=='GET')return;
  const u=new URL(e.request.url);
  if(u.pathname.startsWith('/v1/')||u.pathname.startsWith('/docs'))return; // never cache live API
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

@app.post("/v1/chat/stream", tags=["Chat"], dependencies=[Depends(_require_token)])
def chat_stream(request: ChatRequest):
    """Stream ELI's reply incrementally as Server-Sent Events — same LOCAL model and
    same pipeline as /v1/chat, just token-by-token so the UI isn't blank for a minute.
    Frames: {"session_id":…} first, then {"delta":"…"} chunks, then {"done":true}."""
    engine = get_engine()
    session_id = request.session_id or str(int(time.time()))

    def _frame(obj) -> str:
        return "data: " + json.dumps(obj) + "\n\n"

    def _gen():
        yield _frame({"session_id": session_id})
        try:
            result = engine.process(request.message, source=f"api:{request.user_id}", stream=True)
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

@app.post("/v1/chat/completions", tags=["Chat"], dependencies=[Depends(_require_token)])
def chat_completions(request: CompletionRequest):
    """Standard chat-completions shape, answered by ELI's LOCAL model + pipeline.
    Honours `stream`; returns the canonical `chat.completion` / `chat.completion.chunk`
    objects (and the `[DONE]` sentinel) so standard clients work drop-in."""
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
def devices_discover(timeout: float = 3.0):
    """Scan the LAN (mDNS + SSDP/UPnP) for brokers, media devices, AirPlay, Fire TV, Cast."""
    from eli.runtime.device_server import discover
    return discover(timeout=min(8.0, max(1.0, float(timeout))))

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

def _connect_url() -> dict:
    """Everything the 'Connect a phone' tab needs: the LAN IP, port, the ready-to-open URL
    (token included when set), and whether the server is actually reachable from the LAN."""
    host = os.environ.get("ELI_API_HOST", "127.0.0.1")
    port = os.environ.get("ELI_API_PORT", "8081")
    lan_accessible = host in ("0.0.0.0", "::", "")  # bound to all interfaces
    scheme = os.environ.get("ELI_API_SCHEME", "http")
    ip = _lan_ip()
    token = _api_token()
    url = f"{scheme}://{ip}:{port}/" + (f"?token={token}" if token else "")
    return {"lan_ip": ip, "port": port, "bind_host": host, "scheme": scheme,
            "https": scheme == "https", "lan_accessible": lan_accessible,
            "url": url, "has_token": bool(token)}

@app.get("/v1/connect", tags=["System"], dependencies=[Depends(_require_token)])
def connect_info():
    """Phone-connect details (URL + LAN reachability) for the Connect tab."""
    return {"ok": True, **_connect_url()}

@app.get("/v1/connect/qr.svg", tags=["System"], dependencies=[Depends(_require_token)])
def connect_qr():
    """A scannable QR (SVG) of the phone URL — point the phone camera at it and the
    dashboard opens, token and all. Generated locally with segno (no cloud, no deps)."""
    info = _connect_url()
    try:
        import segno
        svg = segno.make(info["url"], error="m").svg_inline(scale=6, dark="#22d3ee", light=None)
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
    port = args.port or int(os.environ.get("ELI_API_PORT", "8081"))
    reload = args.reload or os.environ.get("ELI_API_RELOAD", "0").strip().lower() in ("1", "true", "yes", "on")
    if args.token:
        os.environ["ELI_API_TOKEN"] = args.token
    # Record the actual bind host/port so the "Connect a phone" tab can tell whether the
    # server is reachable from the LAN (0.0.0.0) or loopback-only, and build the phone URL.
    os.environ["ELI_API_HOST"] = host
    os.environ["ELI_API_PORT"] = str(port)

    # Optional HTTPS (self-signed) so the phone browser allows the microphone.
    use_https = args.https or os.environ.get("ELI_API_HTTPS", "0").strip().lower() in ("1", "true", "yes", "on")
    ssl_kw = {}
    if use_https:
        try:
            _crt, _key = _ensure_lan_cert()
            ssl_kw = {"ssl_certfile": _crt, "ssl_keyfile": _key}
        except Exception as _e:
            print(f"  HTTPS requested but cert setup failed ({_e}); serving over HTTP.", flush=True)
            use_https = False
    os.environ["ELI_API_SCHEME"] = "https" if use_https else "http"

    # The auth gate (_require_token) fails CLOSED by default: with no token and no explicit
    # opt-out, every gated endpoint returns 401. main() is where we relax that for the two
    # safe cases — and ONLY here, so a raw `uvicorn api.server:app` (which never runs main())
    # stays locked down.
    if _is_loopback_host(host):
        # Genuinely local bind (127.0.0.0/8, ::1) — enable tokenless serving for
        # zero-friction same-machine use. This is the ONLY place it is enabled.
        # An explicit ELI_API_ALLOW_TOKENLESS=0 (lock down even local) is respected.
        os.environ.setdefault("ELI_API_ALLOW_TOKENLESS", "1")
    else:
        # Non-loopback bind — would expose device control + file ingest to the whole
        # network. A token is mandatory: reuse ELI_API_TOKEN if set, else auto-generate.
        # Tokenless stays OFF here regardless.
        os.environ.pop("ELI_API_ALLOW_TOKENLESS", None)
        token = _api_token()
        auto_generated = not token
        if auto_generated:
            token = secrets.token_urlsafe(32)
            os.environ["ELI_API_TOKEN"] = token
        _scheme = "https" if use_https else "http"
        url = f"{_scheme}://{_lan_ip()}:{port}/?token={token}"
        _bar = "=" * 72
        print(_bar, flush=True)
        print(f"  ELI web server exposed on the LAN  ({host}:{port}, {_scheme.upper()})", flush=True)
        print(f"  Open this on your phone (same Wi-Fi):   {url}", flush=True)
        print(f"  Or send header:   Authorization: Bearer {token}", flush=True)
        if use_https:
            print("  HTTPS is self-signed: your phone will warn once — tap Advanced -> Proceed.", flush=True)
            print("  (That accept is what unlocks the phone microphone.)", flush=True)
        else:
            print("  Tip: add --https to unlock the phone microphone (voice).", flush=True)
        if auto_generated:
            print("  (Token auto-generated; pass --token <secret> or set ELI_API_TOKEN "
                  "for one stable across restarts.)", flush=True)
        print(_bar, flush=True)

    uvicorn.run("api.server:app", host=host, port=port, reload=reload, log_level="info", **ssl_kw)

if __name__ == "__main__":
    main()
