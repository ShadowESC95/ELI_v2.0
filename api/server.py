"""
ELI API Server – Enterprise edition.
Provides REST endpoints for chat and command execution.
"""

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional
import time
import uvicorn

from eli.kernel.engine import get_engine
from eli.memory.memory import get_memory

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
  function add(t,who){const d=document.createElement('div');d.className='msg '+who;d.textContent=t;
    log.appendChild(d);log.scrollTop=log.scrollHeight;return d;}
  f.addEventListener('submit',async e=>{e.preventDefault();
    const text=box.value.trim();if(!text)return;
    add(text,'user');box.value='';send.disabled=true;const p=add('...','eli');
    try{const r=await fetch('/v1/chat',{method:'POST',headers:{'Content-Type':'application/json'},
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

@app.post("/v1/chat", response_model=ChatResponse, tags=["Chat"])
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
            response=result.get("content", ""),
            session_id=session_id,
            user_id=request.user_id,
            timestamp=time.time()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/v1/execute", response_model=ExecuteResponse, tags=["Commands"])
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
    uvicorn.run(
        "api.server:app",
        host="0.0.0.0",
        port=8081,
        reload=True,
        log_level="info"
    )

if __name__ == "__main__":
    main()
