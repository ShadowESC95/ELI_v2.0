"""
ELI API Server – Enterprise edition.
Provides REST endpoints for chat and command execution.
"""

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional
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
_API_TOKEN = os.environ.get("ELI_API_TOKEN", "").strip()


def _require_token(authorization: str = Header(default="")):
    if not _API_TOKEN:
        return
    if not secrets.compare_digest(authorization or "", f"Bearer {_API_TOKEN}"):
        raise HTTPException(status_code=401, detail="missing or invalid API token")

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
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>ELI</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin:0; font-family: system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
         background:#0e0f13; color:#e6e6e6; height:100dvh; display:flex; flex-direction:column; }
  header { padding:12px 16px; border-bottom:1px solid #23252b; font-weight:600; letter-spacing:.5px; }
  header small { color:#6b7280; font-weight:400; margin-left:8px; }
  #log { flex:1; overflow-y:auto; padding:16px; display:flex; flex-direction:column; gap:10px; }
  .msg { max-width:82%; padding:10px 13px; border-radius:14px; white-space:pre-wrap; line-height:1.45; }
  .user { align-self:flex-end; background:#1a5fb4; color:#fff; border-bottom-right-radius:4px; }
  .eli  { align-self:flex-start; background:#1b1d23; border:1px solid #2a2d35; border-bottom-left-radius:4px; }
  .meta { font-size:11px; color:#6b7280; align-self:center; }
  form { display:flex; gap:8px; padding:12px; border-top:1px solid #23252b; }
  #box { flex:1; padding:12px; border-radius:10px; border:1px solid #2a2d35; background:#15171c;
         color:#e6e6e6; font-size:16px; }
  button { padding:0 18px; border:0; border-radius:10px; background:#1a5fb4; color:#fff; font-size:16px; }
  button:disabled { opacity:.5; }
</style></head><body>
  <header>ELI <small>local &middot; private</small></header>
  <div id="log"><div class="meta">Connected to your ELI server. Say hello.</div></div>
  <form id="f"><input id="box" autocomplete="off" placeholder="Message ELI..."><button id="send">Send</button></form>
<script>
  const log=document.getElementById('log'),box=document.getElementById('box'),
        send=document.getElementById('send'),f=document.getElementById('f');
  let session=null;
  let uid=localStorage.getItem('eli_uid');
  if(!uid){uid='web-'+Math.random().toString(36).slice(2,8);localStorage.setItem('eli_uid',uid);}
  // Capture the access token the launcher puts in the URL (?token=...) once, persist it,
  // then scrub it from the address bar. Loopback runs tokenless so this stays empty.
  const qp=new URLSearchParams(location.search);
  if(qp.get('token')){localStorage.setItem('eli_token',qp.get('token'));
    history.replaceState({},'',location.pathname);}
  const token=localStorage.getItem('eli_token')||'';
  function add(t,who){const d=document.createElement('div');d.className='msg '+who;d.textContent=t;
    log.appendChild(d);log.scrollTop=log.scrollHeight;return d;}
  f.addEventListener('submit',async e=>{e.preventDefault();
    const text=box.value.trim();if(!text)return;
    add(text,'user');box.value='';send.disabled=true;const p=add('...','eli');
    const h={'Content-Type':'application/json'};if(token)h['Authorization']='Bearer '+token;
    try{const r=await fetch('/v1/chat',{method:'POST',headers:h,
        body:JSON.stringify({message:text,user_id:uid,session_id:session})});
      const j=await r.json();session=j.session_id||session;
      p.textContent=j.response||j.detail||'(no response)';
    }catch(err){p.textContent='Error: '+err;}
    finally{send.disabled=false;box.focus();}});
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

@app.post("/v1/chat", response_model=ChatResponse, tags=["Chat"], dependencies=[Depends(_require_token)])
async def chat(request: ChatRequest):
    """Send a message to ELI and get a response."""
    try:
        engine = get_engine()
        session_id = request.session_id or str(int(time.time()))
        
        result = engine.process(
            request.message,
            source=f"api:{request.user_id}",
            stream=False
        )

        return ChatResponse(
            response=_extract_response_text(result),
            session_id=session_id,
            user_id=request.user_id,
            timestamp=time.time()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/v1/execute", response_model=ExecuteResponse, tags=["Commands"], dependencies=[Depends(_require_token)])
async def execute(request: ExecuteRequest):
    """Execute a direct ELI command (OPEN_APP, SCREENSHOT, etc.)."""
    try:
        from eli.execution.executor_enhanced import execute as exec_cmd
        
        result = exec_cmd(request.action, request.args)
        
        return ExecuteResponse(
            ok=result.get("ok", False),
            result=result,
            user_id=request.user_id,
            timestamp=time.time()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/v1/status/{user_id}", response_model=StatusResponse, tags=["System"])
async def status(user_id: str):
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
# Run the server
# ----------------------------------------------------------------------
def main():
    # Safe-by-default: bind loopback unless explicitly told otherwise (the launcher sets
    # ELI_API_HOST=0.0.0.0 only with --lan, and then also sets ELI_API_TOKEN).
    host = os.environ.get("ELI_API_HOST", "127.0.0.1")
    port = int(os.environ.get("ELI_API_PORT", "8081"))
    reload = os.environ.get("ELI_API_RELOAD", "0").strip().lower() in ("1", "true", "yes", "on")
    uvicorn.run("api.server:app", host=host, port=port, reload=reload, log_level="info")

if __name__ == "__main__":
    main()
