"""
ELI API Server – Enterprise edition.
Provides REST endpoints for chat and command execution.
"""

from fastapi import FastAPI, HTTPException, Depends, Header, Request
from fastapi.responses import HTMLResponse, StreamingResponse, Response
from pydantic import BaseModel
from typing import Optional
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
  #mic { padding:0 14px; border:1px solid var(--line); border-radius:10px; background:#15171c; color:#e6e6e6; font-size:18px; cursor:pointer; }
  #mic.rec { background:#b42a2a; border-color:#b42a2a; color:#fff; animation:pulse 1.1s infinite; }
  @keyframes pulse { 0%,100%{opacity:1;} 50%{opacity:.55;} }
  .voicebar { display:flex; align-items:center; gap:12px; padding:0 12px 10px; font-size:13px; color:var(--mut); }
  .voicebar .spk { display:flex; align-items:center; gap:6px; cursor:pointer; }
  .voicebar #vstat { color:var(--teal); }
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
  a.link, .link { color:var(--teal); cursor:pointer; }
  input[type=range] { width:100%; accent-color:var(--teal); margin-top:4px; }
  .media { display:flex; gap:6px; justify-content:center; }
  .media button { background:#15171c; border:1px solid var(--line); color:#e6e6e6; border-radius:8px; padding:6px 9px; font-size:15px; cursor:pointer; }
  .clim { display:flex; align-items:center; justify-content:space-between; }
  .clim button { width:32px; height:32px; border-radius:8px; border:1px solid var(--line); background:#15171c; color:#e6e6e6; font-size:18px; cursor:pointer; }
  .bar { height:8px; border-radius:6px; background:#2a2d35; overflow:hidden; margin-top:4px; }
  .bar i { display:block; height:100%; background:var(--teal); }
  .syscard { background:var(--card); border:1px solid var(--line); border-radius:16px; padding:16px; }
  .syscard h4 { margin:0 0 12px; font-size:12px; color:var(--teal); text-transform:uppercase; letter-spacing:.5px; }
  .kv { display:flex; justify-content:space-between; font-size:13px; margin:6px 0; color:#cdd2da; }
  .glabel { text-align:center; font-size:11px; color:var(--mut); margin-top:4px; }
  #research { overflow-y:auto; padding:14px; }
  .rwrap { max-width:760px; margin:0 auto; }
  .rsec { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:16px; margin-bottom:14px; }
  .rsec h4 { margin:0 0 10px; font-size:12px; color:var(--teal); text-transform:uppercase; letter-spacing:.5px; }
  .rrow { display:flex; gap:8px; margin:8px 0; flex-wrap:wrap; }
  .rrow input, .rrow select { flex:1; min-width:140px; padding:10px; border-radius:9px; border:1px solid var(--line); background:#15171c; color:#e6e6e6; font-size:14px; }
  .rrow button { padding:10px 16px; border:0; border-radius:9px; background:var(--accent); color:#fff; font-size:14px; cursor:pointer; }
  .rrow button:disabled { opacity:.5; }
  .answer { background:#15171c; border:1px solid var(--line); border-radius:10px; padding:13px; white-space:pre-wrap; line-height:1.5; font-size:14px; margin-top:6px; }
  .src { background:#15171c; border:1px solid var(--line); border-radius:9px; padding:9px 11px; margin-top:7px; font-size:13px; }
  .src .sh { display:flex; justify-content:space-between; color:var(--teal); font-weight:600; margin-bottom:4px; }
  .src .sx { color:#b8bcc4; }
  .rnote { font-size:12px; color:var(--mut); margin-top:6px; }
</style></head><body>
  <header>
    <b>ELI</b><small>local &middot; private</small>
    <nav class="tabs">
      <button data-tab="chat" class="active">Chat</button>
      <button data-tab="commands">Commands</button>
      <button data-tab="home">Home</button>
      <button data-tab="system">System</button>
      <button data-tab="research">Research</button>
    </nav>
  </header>
  <section class="view active" id="view-chat">
    <div id="log"><div class="meta">Connected to your ELI server. Say hello.</div></div>
    <form id="f"><button type="button" id="mic" title="Tap to talk">&#127908;</button><input id="box" autocomplete="off" placeholder="Message ELI..."><button id="send">Send</button></form>
    <div class="voicebar"><label class="spk"><input type="checkbox" id="spk"> Speak replies</label><span id="vstat"></span></div>
  </section>
  <section class="view" id="view-commands">
    <div id="commands">
      <input id="cmdsearch" autocomplete="off" placeholder="Search commands…">
      <div id="cmdlist"><div class="muted">Loading…</div></div>
    </div>
  </section>
  <section class="view" id="view-home"><div id="home"><div class="muted">Loading…</div></div></section>
  <section class="view" id="view-system"><div id="system"><div class="muted">Loading…</div></div></section>
  <section class="view" id="view-research"><div id="research"><div class="muted">Loading…</div></div></section>
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
    if(b.dataset.tab==='system') loadSystem();
    if(b.dataset.tab==='research') loadResearch();
  });

  /* chat */
  const log=$('#log'),box=$('#box'),send=$('#send'),f=$('#f');
  let session=null;
  function add(t,who){const d=document.createElement('div');d.className='msg '+who;d.textContent=t;log.appendChild(d);log.scrollTop=log.scrollHeight;return d;}
  const NL=String.fromCharCode(10), SEP=NL+NL;
  f.addEventListener('submit',e=>{e.preventDefault();const text=box.value.trim();if(!text)return;box.value='';streamChat(text);});
  async function streamChat(text){
    add(text,'user');send.disabled=true;const p=add('…','eli');let got=false;
    try{
      const r=await fetch('/v1/chat/stream',{method:'POST',headers:H(),body:JSON.stringify({message:text,user_id:uid,session_id:session})});
      const reader=r.body.getReader(),dec=new TextDecoder();let buf='';
      for(;;){const rd=await reader.read();if(rd.done)break;
        buf+=dec.decode(rd.value,{stream:true});let i;
        while((i=buf.indexOf(SEP))>=0){const frame=buf.slice(0,i);buf=buf.slice(i+SEP.length);
          if(frame.indexOf('data:')!==0)continue;
          let j;try{j=JSON.parse(frame.slice(5).trim());}catch(_e){continue;}
          if(j.session_id)session=j.session_id;
          if(j.delta){if(!got){p.textContent='';got=true;}p.textContent+=j.delta;log.scrollTop=log.scrollHeight;}
          if(j.error)p.textContent+=(p.textContent?NL:'')+'[error: '+j.error+']';
        }
      }
      if(!p.textContent)p.textContent='(no response)';
    }catch(err){p.textContent='Error: '+err;}
    finally{send.disabled=false;box.focus();}
    return got?p.textContent:'';
  }

  /* voice — local STT (whisper) in, local TTS (piper) out; nothing leaves the box */
  const mic=$('#mic'),spk=$('#spk'),vstat=$('#vstat');
  spk.checked=localStorage.getItem('eli_speak')==='1';
  spk.onchange=()=>localStorage.setItem('eli_speak',spk.checked?'1':'0');
  function vmsg(m){vstat.textContent=m||'';}
  let mediaRec=null,vchunks=[],recording=false,vstream=null;
  async function toggleMic(){
    if(recording){try{mediaRec.stop();}catch(_e){}return;}
    if(!navigator.mediaDevices||!window.MediaRecorder){vmsg('Voice not supported here');return;}
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
        const reply=await streamChat(text);
        if(spk.checked&&reply)speakReply(reply);
      }catch(e){vmsg('Voice error: '+e);}
    };
    recording=true;mic.classList.add('rec');vmsg('Listening… tap mic to stop');mediaRec.start();
  }
  async function speakReply(text){
    try{
      const r=await fetch('/v1/voice/tts',{method:'POST',headers:H(),body:JSON.stringify({text:text})});
      if(!r.ok)return;
      const a=new Audio(URL.createObjectURL(await r.blob()));
      a.play().catch(()=>{});
    }catch(_e){}
  }
  mic.onclick=toggleMic;

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
  function deviceCard(dv){
    const dom=dv.domain||(dv.entity_id.split('.')[0]||''), a=dv.attrs||{};
    const card=document.createElement('div');card.className='card';
    const head='<div><div class="nm">'+esc(dv.name)+'</div><div class="dom">'+esc(dom)+'</div></div>';
    const on=(''+dv.state).toLowerCase()==='on';
    if(dom==='light'){
      let h=head+'<div class="row"><span class="st">'+(on?'On':'Off')+'</span><label class="sw"><input type="checkbox" '+(on?'checked':'')+'><span></span></label></div>';
      if(on && a.brightness_pct!=null) h+='<input type="range" min="1" max="100" value="'+a.brightness_pct+'">';
      card.innerHTML=h;
      const tg=card.querySelector('.sw input');tg.onchange=()=>control(dv.entity_id,tg.checked?'on':'off');
      const sl=card.querySelector('input[type=range]');
      if(sl){let t;sl.oninput=()=>{clearTimeout(t);t=setTimeout(()=>control(dv.entity_id,'on',+sl.value),250);};}
    } else if(dom==='switch'||dom==='fan'||dom==='input_boolean'){
      card.innerHTML=head+'<div class="row"><span class="st">'+(on?'On':'Off')+'</span><label class="sw"><input type="checkbox" '+(on?'checked':'')+'><span></span></label></div>';
      const tg=card.querySelector('.sw input');tg.onchange=()=>control(dv.entity_id,tg.checked?'on':'off');
    } else if(dom==='media_player'){
      const title=a.media_title?(esc(a.media_title)+(a.media_artist?' — '+esc(a.media_artist):'')):esc(''+dv.state);
      card.innerHTML=head+'<div class="st">'+title+'</div><div class="media"><button data-c="previous">⏮</button><button data-c="play_pause">⏯</button><button data-c="next">⏭</button><button data-c="stop">⏹</button></div>';
      card.querySelectorAll('.media button').forEach(b=>b.onclick=()=>media(dv.entity_id,b.dataset.c));
    } else if(dom==='climate'){
      const cur=a.current_temperature, mn=(a.min_temp!=null?+a.min_temp:7), mx=(a.max_temp!=null?+a.max_temp:35);
      let target=(a.temperature!=null?+a.temperature:20);
      card.innerHTML=head+'<div class="st">'+(cur!=null?cur+'° now':esc(''+dv.state))+'</div>'+
        '<div class="clim"><button data-d="-1">−</button><span class="st sp">'+(a.temperature!=null?target+'°':'—')+'</span><button data-d="1">+</button></div>';
      const sp=card.querySelector('.sp');
      card.querySelectorAll('.clim button').forEach(b=>b.onclick=()=>{target=Math.max(mn,Math.min(mx,target+(+b.dataset.d)));sp.textContent=target+'°';climate(dv.entity_id,target);});
    } else {
      const num=parseFloat(dv.state), isNum=!isNaN(num)&&isFinite(num), unit=a.unit_of_measurement||'';
      if(isNum && (unit==='%'||(!unit && num>=0 && num<=100))){
        card.innerHTML='<div class="nm">'+esc(dv.name)+'</div><div class="gauge" style="--p:'+num+'"><i>'+Math.round(num)+'</i></div>';
      } else {
        card.innerHTML=head+'<div class="row"><span class="st">'+esc(''+dv.state)+(unit?' '+esc(unit):'')+'</span></div>';
      }
    }
    return card;
  }
  function renderDevices(devs){
    if(!devs.length){$('#home').innerHTML='<div class="muted">No devices found.</div>'+cfgLink();return;}
    const grid=document.createElement('div');grid.className='grid';
    devs.forEach(dv=>grid.appendChild(deviceCard(dv)));
    const h=$('#home');h.innerHTML='';h.appendChild(grid);
    const foot=document.createElement('div');foot.innerHTML=cfgLink();h.appendChild(foot);
  }
  function control(entity,cmd,bri){const b={entity_id:entity,command:cmd};if(bri!=null)b.brightness=bri;
    api('/v1/smarthome/control',{method:'POST',body:JSON.stringify(b)}).then(()=>{if(bri==null)setTimeout(loadHome,400);});}
  function media(entity,cmd){api('/v1/smarthome/media',{method:'POST',body:JSON.stringify({entity_id:entity,command:cmd})}).then(()=>setTimeout(loadHome,600));}
  function climate(entity,temp){api('/v1/smarthome/climate',{method:'POST',body:JSON.stringify({entity_id:entity,temperature:temp})});}
  function editHome(){renderHomeConfig('');}

  /* system */
  function sgauge(v,label){return '<div><div class="gauge" style="--p:'+(v||0)+'"><i>'+Math.round(v||0)+'</i></div><div class="glabel">'+esc(label)+'</div></div>';}
  function loadSystem(){
    api('/v1/system').then(d=>{ if(!d.ok){$('#system').innerHTML='<div class="err">'+esc(d.error||'unavailable')+'</div>';return;} renderSystem(d.status||{}); })
      .catch(e=>{$('#system').innerHTML='<div class="err">'+esc(''+e)+'</div>';});
  }
  function renderSystem(s){
    const g=s.gpu,c=s.cpu,r=s.ram,m=s.model||{}; let h='<div class="grid">';
    if(g){const vp=g.vram_total_mb?Math.round(g.vram_used_mb/g.vram_total_mb*100):0;
      h+='<div class="syscard"><h4>GPU</h4><div class="nm" style="margin-bottom:10px">'+esc(g.name||'')+'</div>'+
        '<div class="row" style="gap:14px">'+sgauge(g.temp_c,'°C')+sgauge(g.util_pct,'% util')+'</div>'+
        '<div class="kv">VRAM<span>'+g.vram_used_mb+' / '+g.vram_total_mb+' MB</span></div><div class="bar"><i style="width:'+vp+'%"></i></div></div>';}
    if(c){h+='<div class="syscard"><h4>CPU</h4><div class="row" style="gap:14px">'+sgauge(c.usage_pct,'% load')+(c.temp_c!=null?sgauge(c.temp_c,'°C'):'')+'</div>'+
        '<div class="kv">Cores<span>'+(c.cores||'?')+'</span></div></div>';}
    if(r){h+='<div class="syscard"><h4>Memory</h4><div class="kv">RAM<span>'+r.used_mb+' / '+r.total_mb+' MB</span></div><div class="bar"><i style="width:'+(r.pct||0)+'%"></i></div></div>';}
    h+='<div class="syscard"><h4>Model</h4><div class="nm">'+esc(m.name||'—')+'</div>'+
       '<div class="kv">ctx<span>'+(m.n_ctx||'?')+'</span></div><div class="kv">gpu layers<span>'+(m.n_gpu_layers||'?')+'</span></div>'+
       '<div class="kv">uptime<span>'+esc(s.uptime||'?')+'</span></div></div>';
    $('#system').innerHTML=h+'</div>';
  }
  /* research */
  function _ropt(list){return list.length
    ? list.map(c=>'<option value="'+esc(c.corpus)+'">'+esc(c.corpus)+' ('+c.documents+' docs · '+c.chunks+' chunks)</option>').join('')
    : '<option value="" disabled selected>(no corpora yet)</option>';}
  function loadResearch(){
    api('/v1/research/corpora').then(d=>renderResearch((d&&d.corpora)||[]))
      .catch(e=>{$('#research').innerHTML='<div class="err">'+esc(''+e)+'</div>';});
  }
  function renderResearch(list){
    let h='<div class="rwrap">';
    h+='<div class="rsec"><h4>Corpora</h4><div class="rrow"><select id="rq-corpus">'+_ropt(list)+'</select></div>'+
       '<div class="rnote">Each corpus is an isolated local index — your documents never mix with ELI\\'s memory, and nothing leaves this machine.</div></div>';
    h+='<div class="rsec"><h4>Ingest documents</h4>'+
       '<div class="rrow"><input id="ing-name" autocomplete="off" placeholder="corpus name (new or existing)"></div>'+
       '<div class="rrow"><input id="ing-path" autocomplete="off" placeholder="local file or folder path (.pdf / .txt / .md)"><button id="ing-btn" onclick="ingestCorpus()">Ingest</button></div>'+
       '<div id="ing-status" class="rnote"></div></div>';
    h+='<div class="rsec"><h4>Ask (grounded in the corpus)</h4>'+
       '<div class="rrow"><input id="ask-q" autocomplete="off" placeholder="Ask a question answered only from this corpus…"><button id="ask-btn" onclick="askCorpus()">Ask</button></div>'+
       '<div id="ask-out"></div></div>';
    $('#research').innerHTML=h+'</div>';
  }
  function refreshCorpusSelect(sel){
    api('/v1/research/corpora').then(d=>{
      const dd=$('#rq-corpus'); if(!dd)return;
      dd.innerHTML=_ropt((d&&d.corpora)||[]); if(sel)dd.value=sel;
    }).catch(()=>{});
  }
  function ingestCorpus(){
    const name=($('#ing-name').value||'').trim(), path=($('#ing-path').value||'').trim();
    const st=$('#ing-status'), btn=$('#ing-btn');
    if(!name||!path){st.textContent='Enter a corpus name and a file/folder path.';return;}
    btn.disabled=true; st.textContent='Ingesting… (extracting + embedding locally, this can take a while)';
    api('/v1/research/ingest',{method:'POST',body:JSON.stringify({corpus:name,path:path})}).then(d=>{
      if(!d.ok){st.innerHTML='<span style="color:#f87171">'+esc(d.error||'ingest failed')+'</span>';return;}
      st.textContent='Added '+d.docs_added+' document(s), '+d.chunks_added+' chunk(s). Corpus "'+d.corpus+'" now holds '+d.total_chunks+' chunks'+
        (d.skipped&&d.skipped.length?' — skipped '+d.skipped.length+' file(s) with no extractable text':'')+'.';
      refreshCorpusSelect(d.corpus);
    }).catch(e=>{st.innerHTML='<span style="color:#f87171">'+esc(''+e)+'</span>';})
      .finally(()=>{btn.disabled=false;});
  }
  function askCorpus(){
    const dd=$('#rq-corpus'), q=($('#ask-q').value||'').trim(), out=$('#ask-out'), btn=$('#ask-btn');
    const corpus=dd?dd.value:'';
    if(!corpus){out.innerHTML='<div class="rnote">Ingest a corpus first.</div>';return;}
    if(!q){out.innerHTML='<div class="rnote">Type a question.</div>';return;}
    btn.disabled=true; out.innerHTML='<div class="rnote">Searching the corpus and synthesising with the local model…</div>';
    api('/v1/research/query',{method:'POST',body:JSON.stringify({corpus:corpus,question:q,k:6})}).then(d=>{
      if(!d.ok){out.innerHTML='<div class="err">'+esc(d.error||'query failed')+'</div>';return;}
      let h='<div class="answer">'+esc(d.answer||'')+'</div>';
      (d.sources||[]).forEach(s=>{h+='<div class="src"><div class="sh"><span>'+esc(s.source||'?')+'</span><span>'+(s.score!=null?esc(s.score):'')+'</span></div><div class="sx">'+esc(s.excerpt||'')+'</div></div>';});
      out.innerHTML=h;
    }).catch(e=>{out.innerHTML='<div class="err">'+esc(''+e)+'</div>';})
      .finally(()=>{btn.disabled=false;});
  }

  window.renderHomeConfig=renderHomeConfig; window.saveHome=saveHome; window.control=control; window.media=media; window.climate=climate; window.editHome=editHome;
  window.ingestCorpus=ingestCorpus; window.askCorpus=askCorpus;
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
    brightness: Optional[int] = None  # 0-100 (%)

class MediaControl(BaseModel):
    entity_id: str
    command: str  # play | pause | play_pause | next | previous | stop

class ClimateControl(BaseModel):
    entity_id: str
    temperature: float

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

class ResearchQuery(BaseModel):
    corpus: str
    question: str
    k: int = 6

class TTSRequest(BaseModel):
    text: str
    voice: Optional[str] = None

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
    """Turn an entity on/off (optionally set brightness % on lights)."""
    sh = _smart_home()
    args = {"entity_id": req.entity_id}
    if req.brightness is not None:
        args["brightness_pct"] = int(req.brightness)
    res = sh.turn_on(args) if (req.command or "").lower() == "on" else sh.turn_off(args)
    return {"ok": bool(res.get("ok")), "message": res.get("response") or res.get("content")}

@app.post("/v1/smarthome/media", tags=["Smart Home"], dependencies=[Depends(_require_token)])
async def smarthome_media(req: MediaControl):
    """Transport control for a media_player (play/pause/next/previous/stop)."""
    res = _smart_home().media_control({"entity_id": req.entity_id, "command": req.command})
    return {"ok": bool(res.get("ok")), "message": res.get("response") or res.get("content")}

@app.post("/v1/smarthome/climate", tags=["Smart Home"], dependencies=[Depends(_require_token)])
async def smarthome_climate(req: ClimateControl):
    """Set a climate entity's target temperature."""
    res = _smart_home().set_temperature({"entity_id": req.entity_id, "temperature": req.temperature})
    return {"ok": bool(res.get("ok")), "message": res.get("response") or res.get("content")}

# ----------------------------------------------------------------------
# System telemetry  (powers the "System" tab — real, measured, never guessed)
# ----------------------------------------------------------------------
@app.get("/v1/system", tags=["System"], dependencies=[Depends(_require_token)])
async def system_status():
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
# Research workspaces  (powers the "Research" tab — fully local, no external surface)
# Ingest your own documents into an isolated corpus, then ask grounded questions
# answered ONLY from those sources (with citations). Reuses ELI's nomic embedder +
# FAISS + the local model; nothing leaves the box.
# ----------------------------------------------------------------------
@app.get("/v1/research/corpora", tags=["Research"], dependencies=[Depends(_require_token)])
def research_corpora():
    from eli.runtime.research_corpus import corpora
    return {"ok": True, "corpora": corpora()}

@app.post("/v1/research/ingest", tags=["Research"], dependencies=[Depends(_require_token)])
def research_ingest(req: ResearchIngest):
    """Ingest a local file or folder of documents (.pdf/.txt/.md) into a corpus.
    Synchronous; a very large corpus may take a while (embedding is CPU-local)."""
    from eli.runtime.research_corpus import ingest
    return ingest(req.corpus, req.path)

@app.post("/v1/research/query", tags=["Research"], dependencies=[Depends(_require_token)])
def research_query(req: ResearchQuery):
    """Retrieve the most relevant passages from a corpus and synthesise a grounded,
    cited answer with the LOCAL model. Returns {answer, sources}."""
    from eli.runtime.research_corpus import query
    res = query(req.corpus, req.question, k=req.k)
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

@app.post("/v1/voice/stt", tags=["Voice"], dependencies=[Depends(_require_token)])
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
        text = (transcribe_file(tmp_path) or "").strip()
        return {"ok": True, "text": text}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

@app.post("/v1/voice/tts", tags=["Voice"], dependencies=[Depends(_require_token)])
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
