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


def _require_token(authorization: str = Header(default="")):
    token = _api_token()
    if not token:
        return
    if not secrets.compare_digest(authorization or "", f"Bearer {token}"):
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
  :root { color-scheme: dark; --bg:#0e0f13; --card:#1b1d23; --line:#2a2d35; --accent:#1a5fb4; --teal:#38bdf8; --mut:#6b7280; }
  * { box-sizing: border-box; }
  body { margin:0; font-family: system-ui,-apple-system,Segoe UI,Roboto,sans-serif; background:var(--bg); color:#e6e6e6; height:100dvh; display:flex; flex-direction:column; }
  header { padding:10px 14px; border-bottom:1px solid #23252b; display:flex; align-items:center; gap:10px; }
  header b { font-weight:600; letter-spacing:.5px; } header small { color:var(--mut); }
  nav.tabs { margin-left:auto; display:flex; gap:4px; }
  nav.tabs button { padding:7px 14px; border:0; border-radius:8px; background:transparent; color:var(--mut); font-size:14px; cursor:pointer; }
  nav.tabs button.active { background:#15171c; color:#e6e6e6; }
  .view { flex:1; min-height:0; display:none; flex-direction:column; }
  .view.active { display:flex; }
  #log { flex:1; overflow-y:auto; padding:16px; display:flex; flex-direction:column; gap:10px; }
  .msg { max-width:82%; padding:10px 13px; border-radius:14px; white-space:pre-wrap; line-height:1.45; }
  .user { align-self:flex-end; background:var(--accent); color:#fff; border-bottom-right-radius:4px; }
  .eli  { align-self:flex-start; background:var(--card); border:1px solid var(--line); border-bottom-left-radius:4px; }
  .meta { font-size:11px; color:var(--mut); align-self:center; }
  form#f { display:flex; gap:8px; padding:12px; border-top:1px solid #23252b; }
  #box { flex:1; padding:12px; border-radius:10px; border:1px solid var(--line); background:#15171c; color:#e6e6e6; font-size:16px; }
  form#f button { padding:0 18px; border:0; border-radius:10px; background:var(--accent); color:#fff; font-size:16px; }
  form#f button:disabled { opacity:.5; }
  #commands, #home { overflow-y:auto; padding:14px; }
  #cmdsearch { width:100%; padding:11px 13px; border-radius:10px; border:1px solid var(--line); background:#15171c; color:#e6e6e6; font-size:15px; margin-bottom:12px; }
  .cat h3 { margin:18px 0 8px; font-size:13px; text-transform:uppercase; letter-spacing:.6px; color:var(--teal); }
  .cmd { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:11px 13px; margin-bottom:8px; }
  .cmd .act { font-weight:600; font-size:13px; }
  .cmd .desc { color:#b8bcc4; font-size:13px; margin:3px 0 7px; }
  .chips { display:flex; flex-wrap:wrap; gap:6px; }
  .chip { font-size:12px; padding:4px 9px; border-radius:14px; background:#15171c; border:1px solid var(--line); color:#cdd2da; cursor:pointer; }
  .chip:hover { border-color:var(--teal); color:#fff; }
  .hconfig { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:16px; max-width:520px; margin:8px auto; }
  .hconfig h3 { margin:0 0 4px; } .hconfig p { color:var(--mut); font-size:13px; margin:0 0 14px; }
  .hconfig label { display:block; font-size:13px; color:#b8bcc4; margin:10px 0 4px; }
  .hconfig input { width:100%; padding:10px; border-radius:9px; border:1px solid var(--line); background:#15171c; color:#e6e6e6; font-size:14px; }
  .hconfig button { margin-top:14px; padding:10px 18px; border:0; border-radius:9px; background:var(--accent); color:#fff; font-size:15px; cursor:pointer; }
  .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(168px,1fr)); gap:12px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:16px; padding:14px; display:flex; flex-direction:column; gap:10px; min-height:120px; }
  .card .nm { font-size:14px; font-weight:600; } .card .dom { font-size:11px; color:var(--mut); text-transform:uppercase; letter-spacing:.5px; }
  .card .row { display:flex; align-items:center; justify-content:space-between; margin-top:auto; }
  .st { font-size:13px; color:#cdd2da; }
  .sw { position:relative; width:46px; height:26px; flex:none; }
  .sw input { opacity:0; width:0; height:0; }
  .sw span { position:absolute; inset:0; background:#3a3d45; border-radius:26px; transition:.2s; cursor:pointer; }
  .sw span:before { content:""; position:absolute; height:20px; width:20px; left:3px; top:3px; background:#fff; border-radius:50%; transition:.2s; }
  .sw input:checked + span { background:var(--teal); }
  .sw input:checked + span:before { transform:translateX(20px); }
  .gauge { width:84px; height:84px; border-radius:50%; margin:0 auto; display:grid; place-items:center; background:conic-gradient(var(--teal) calc(var(--p)*1%), #2a2d35 0); }
  .gauge i { width:64px; height:64px; border-radius:50%; background:var(--card); display:grid; place-items:center; font-size:16px; font-weight:600; font-style:normal; }
  .err { color:#f87171; font-size:13px; padding:10px; } .muted { color:var(--mut); font-size:13px; text-align:center; padding:30px; }
  a.link { color:var(--teal); cursor:pointer; }
</style></head><body>
  <header>
    <b>ELI</b><small>local &middot; private</small>
    <nav class="tabs">
      <button data-tab="chat" class="active">Chat</button>
      <button data-tab="commands">Commands</button>
      <button data-tab="home">Home</button>
    </nav>
  </header>
  <section class="view active" id="view-chat">
    <div id="log"><div class="meta">Connected to your ELI server. Say hello.</div></div>
    <form id="f"><input id="box" autocomplete="off" placeholder="Message ELI..."><button id="send">Send</button></form>
  </section>
  <section class="view" id="view-commands">
    <div id="commands">
      <input id="cmdsearch" autocomplete="off" placeholder="Search commands…">
      <div id="cmdlist"><div class="muted">Loading…</div></div>
    </div>
  </section>
  <section class="view" id="view-home"><div id="home"><div class="muted">Loading…</div></div></section>
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
  function switchTab(t){document.querySelector('nav.tabs button[data-tab="'+t+'"]').click();}

  let cmdsLoaded=false;
  document.querySelectorAll('nav.tabs button').forEach(b=>b.onclick=()=>{
    document.querySelectorAll('nav.tabs button').forEach(x=>x.classList.remove('active'));
    b.classList.add('active');
    document.querySelectorAll('.view').forEach(v=>v.classList.remove('active'));
    $('#view-'+b.dataset.tab).classList.add('active');
    if(b.dataset.tab==='commands' && !cmdsLoaded) loadCommands();
    if(b.dataset.tab==='home') loadHome();
  });

  /* chat */
  const log=$('#log'),box=$('#box'),send=$('#send'),f=$('#f');
  let session=null;
  function add(t,who){const d=document.createElement('div');d.className='msg '+who;d.textContent=t;log.appendChild(d);log.scrollTop=log.scrollHeight;return d;}
  f.addEventListener('submit',e=>{e.preventDefault();const text=box.value.trim();if(!text)return;
    add(text,'user');box.value='';send.disabled=true;const p=add('…','eli');
    api('/v1/chat',{method:'POST',body:JSON.stringify({message:text,user_id:uid,session_id:session})})
      .then(j=>{session=j.session_id||session;p.textContent=j.response||j.detail||'(no response)';})
      .catch(err=>{p.textContent='Error: '+err;}).finally(()=>{send.disabled=false;box.focus();});});

  /* commands */
  let CAT=[];
  function loadCommands(){api('/v1/capabilities').then(d=>{CAT=d.categories||[];cmdsLoaded=true;renderCommands('');})
    .catch(e=>{$('#cmdlist').innerHTML='<div class="err">Could not load commands: '+esc(''+e)+'</div>';});}
  $('#cmdsearch').addEventListener('input',e=>renderCommands(e.target.value.toLowerCase()));
  function renderCommands(q){
    const wrap=$('#cmdlist');wrap.innerHTML='';
    CAT.forEach(cat=>{
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

  /* home */
  const TOGGLE_DOMAINS=['light','switch','fan','input_boolean'];
  function loadHome(){
    api('/v1/smarthome/config').then(cfg=>{
      if(!cfg.configured){renderHomeConfig(cfg.hass_url||'');return;}
      api('/v1/smarthome/devices').then(d=>{
        if(!d.ok){$('#home').innerHTML='<div class="err">'+esc(d.error||'Home Assistant unreachable')+'</div>'+cfgLink();return;}
        renderDevices(d.devices||[]);});
    }).catch(e=>{$('#home').innerHTML='<div class="err">'+esc(''+e)+'</div>';});
  }
  function cfgLink(){return '<div class="muted"><span class="link" onclick="editHome()">Edit Home Assistant connection</span></div>';}
  function renderHomeConfig(url){
    $('#home').innerHTML='<div class="hconfig"><h3>Home Assistant</h3>'+
      '<p>Connect Home Assistant to control your devices here. Paste your server URL and a long-lived access token (HA &rarr; Profile &rarr; Security &rarr; Long-lived access tokens).</p>'+
      '<label>Server URL</label><input id="ha_url" placeholder="http://homeassistant.local:8123" value="'+esc(url)+'">'+
      '<label>Long-lived token</label><input id="ha_tok" type="password" placeholder="paste token (blank = keep existing)">'+
      '<button onclick="saveHome()">Save &amp; connect</button></div>';
  }
  function saveHome(){const url=$('#ha_url').value.trim(),tok=$('#ha_tok').value.trim();
    $('#home').innerHTML='<div class="muted">Saving…</div>';
    api('/v1/smarthome/config',{method:'POST',body:JSON.stringify({hass_url:url,hass_token:tok})})
      .then(()=>loadHome()).catch(e=>{$('#home').innerHTML='<div class="err">'+esc(''+e)+'</div>';});}
  function renderDevices(devs){
    if(!devs.length){$('#home').innerHTML='<div class="muted">No devices found.</div>'+cfgLink();return;}
    const grid=document.createElement('div');grid.className='grid';
    devs.forEach(dv=>{
      const dom=(dv.entity_id.split('.')[0]||''),num=parseFloat(dv.state),isNum=!isNaN(num)&&isFinite(num);
      const card=document.createElement('div');card.className='card';
      if(TOGGLE_DOMAINS.includes(dom)){
        const on=(''+dv.state).toLowerCase()==='on';
        card.innerHTML='<div><div class="nm">'+esc(dv.name)+'</div><div class="dom">'+esc(dom)+'</div></div>'+
          '<div class="row"><span class="st">'+(on?'On':'Off')+'</span>'+
          '<label class="sw"><input type="checkbox" '+(on?'checked':'')+'><span></span></label></div>';
        const inp=card.querySelector('input');inp.onchange=()=>control(dv.entity_id,inp.checked?'on':'off');
      } else if(isNum && num>=0 && num<=100){
        card.innerHTML='<div class="nm">'+esc(dv.name)+'</div><div class="gauge" style="--p:'+num+'"><i>'+Math.round(num)+'</i></div>';
      } else {
        card.innerHTML='<div><div class="nm">'+esc(dv.name)+'</div><div class="dom">'+esc(dom)+'</div></div>'+
          '<div class="row"><span class="st">'+esc(''+dv.state)+'</span></div>';
      }
      grid.appendChild(card);});
    const h=$('#home');h.innerHTML='';h.appendChild(grid);
    const foot=document.createElement('div');foot.innerHTML=cfgLink();h.appendChild(foot);
  }
  function control(entity,cmd){api('/v1/smarthome/control',{method:'POST',body:JSON.stringify({entity_id:entity,command:cmd})}).then(()=>setTimeout(loadHome,400));}
  function editHome(){renderHomeConfig('');}
  window.renderHomeConfig=renderHomeConfig; window.saveHome=saveHome; window.control=control; window.editHome=editHome;
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

class SmartHomeConfig(BaseModel):
    hass_url: str = ""
    hass_token: str = ""

class SmartHomeControl(BaseModel):
    entity_id: str
    command: str  # "on" | "off"
    brightness: Optional[int] = None

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
# Smart-home  (powers the "Home" tab — reuses the Home Assistant plugin)
# ----------------------------------------------------------------------
def _smart_home():
    from eli.plugins.smart_home.plugin import SmartHomePlugin
    return SmartHomePlugin()

@app.get("/v1/smarthome/config", tags=["Smart Home"], dependencies=[Depends(_require_token)])
async def smarthome_get_config():
    """Current Home Assistant connection (URL + whether a token is set). The token
    itself is never returned."""
    from eli.core import config
    url = (config.get("hass_url") or "").strip()
    return {"hass_url": url, "configured": bool(url and (config.get("hass_token") or "").strip())}

@app.post("/v1/smarthome/config", tags=["Smart Home"], dependencies=[Depends(_require_token)])
async def smarthome_set_config(cfg: SmartHomeConfig):
    """Save the Home Assistant URL and long-lived token (token-gated endpoint)."""
    from eli.core import config
    config.set("hass_url", cfg.hass_url.strip().rstrip("/"))
    if cfg.hass_token.strip():
        config.set("hass_token", cfg.hass_token.strip())
    return {"ok": True}

@app.get("/v1/smarthome/devices", tags=["Smart Home"], dependencies=[Depends(_require_token)])
async def smarthome_devices():
    """List Home Assistant entities (lights/switches/climate/media/sensors/covers)."""
    res = _smart_home().list_devices({})
    ok = bool(res.get("ok"))
    return {"ok": ok, "devices": res.get("devices", []),
            "error": None if ok else (res.get("content") or "unavailable")}

@app.post("/v1/smarthome/control", tags=["Smart Home"], dependencies=[Depends(_require_token)])
async def smarthome_control(req: SmartHomeControl):
    """Turn an entity on/off (optionally set brightness on lights)."""
    sh = _smart_home()
    args = {"entity_id": req.entity_id}
    if req.brightness is not None:
        args["brightness"] = int(req.brightness)
    res = sh.turn_on(args) if (req.command or "").lower() == "on" else sh.turn_off(args)
    return {"ok": bool(res.get("ok")), "message": res.get("response") or res.get("content")}

# ----------------------------------------------------------------------
# Run the server
# ----------------------------------------------------------------------
def main():
    # Safe-by-default: bind loopback unless explicitly told otherwise (the launcher sets
    # ELI_API_HOST=0.0.0.0 only with --lan, and then also sets ELI_API_TOKEN).
    host = os.environ.get("ELI_API_HOST", "127.0.0.1")
    port = int(os.environ.get("ELI_API_PORT", "8081"))
    reload = os.environ.get("ELI_API_RELOAD", "0").strip().lower() in ("1", "true", "yes", "on")

    # Fail-closed network guard — the "token-gated by default" guarantee must NOT
    # depend on the launcher script. Started any other way (ELI_API_HOST=0.0.0.0
    # python -m api.server, a systemd unit, Docker) a non-loopback bind with no token
    # would expose /v1/execute — screenshots, file reads, app open/close — to the whole
    # network unauthenticated. So if we're binding beyond loopback with no token, refuse
    # the silent fail-open: auto-generate one, enforce it (the gate reads it live), and
    # announce it loudly. Opt out only by setting ELI_API_TOKEN yourself.
    if not _is_loopback_host(host) and not _api_token():
        _gen = secrets.token_urlsafe(32)
        os.environ["ELI_API_TOKEN"] = _gen
        _bar = "=" * 72
        print(_bar, flush=True)
        print(f"  SECURITY: binding to non-loopback host {host!r} with no ELI_API_TOKEN set.", flush=True)
        print("  Auto-generated a token so the API is NOT exposed unauthenticated.", flush=True)
        print(f"  Clients must send header:   Authorization: Bearer {_gen}", flush=True)
        print("  Set ELI_API_TOKEN yourself for a token that's stable across restarts.", flush=True)
        print(_bar, flush=True)

    uvicorn.run("api.server:app", host=host, port=port, reload=reload, log_level="info")

if __name__ == "__main__":
    main()
