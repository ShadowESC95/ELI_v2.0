
  const $ = s => document.querySelector(s);
  let uid=localStorage.getItem('eli_uid');
  if(!uid){uid='web-'+Math.random().toString(36).slice(2,8);localStorage.setItem('eli_uid',uid);}
  // Pull the token from the URL FRAGMENT (#token=…) — fragments aren't sent to the server,
  // so the token never reaches the access log. (Accept ?token= too for old links.) Store it,
  // then strip both query + fragment from history so the token doesn't linger.
  let _tk='';
  try{ if(location.hash){_tk=new URLSearchParams(location.hash.replace(/^#/,'')).get('token')||'';} }catch(e){}
  if(!_tk){_tk=new URLSearchParams(location.search).get('token')||'';}
  if(_tk){localStorage.setItem('eli_token',_tk);history.replaceState({},'',location.pathname);}
  const token=localStorage.getItem('eli_token')||'';
  const H=()=>{const h={'Content-Type':'application/json'};if(token)h['Authorization']='Bearer '+token;return h;};
  // Self-healing fetch. A phone waking from Wi-Fi power-save drops the FIRST request:
  // fetch() REJECTS with a network error before any HTTP response arrives. Auto-retry
  // those with short backoff so a transient never reaches the user. Safety: only a
  // pre-response rejection is retried — a resolved response (ANY http status) is never
  // retried, and a deliberate AbortError is never retried. Because fetch() only rejects
  // before the server responds, retrying a POST cannot double-deliver a streamed reply.
  const _sleep=ms=>new Promise(r=>setTimeout(r,ms));
  const _isNetErr=err=>!!err&&(err.name==='TypeError'||(''+err).indexOf('NetworkError')>=0||(''+err).indexOf('Failed to fetch')>=0);
  async function _fetchHeal(path,opts,tries){
    tries=tries||3;let lastErr;
    for(let a=0;a<tries;a++){
      try{return await fetch(path,opts);}
      catch(err){
        if(err&&err.name==='AbortError')throw err;
        lastErr=err;
        if(!_isNetErr(err)||a===tries-1)throw err;
        await _sleep(250*Math.pow(2,a)); // 250ms, then 500ms
      }
    }
    throw lastErr;
  }
  const api=(path,opts)=>_fetchHeal(path,Object.assign({headers:H()},opts||{})).then(r=>r.json());
  function esc(s){return (''+s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
  // ── Settings (real, typed options wired to ELI's config) ───────────────
  let _setSub='General', _setSchema=[], _setVals={}, _setVoices=[], _setModels=[], _setModelActive='';
  function loadSettings(){
    Promise.all([api('/v1/settings'), api('/v1/voice/voices').catch(()=>({})), api('/v1/me').catch(()=>({})), api('/v1/models/installed').catch(()=>({}))]).then(function(r){
      const s=r[0]||{}, v=r[1]||{}, me=r[2]||{}, mo=r[3]||{};
      _setSchema=s.schema||[]; _setVals=s.values||{};
      _setVoices=((v.voices)||[]).map(x=>x.id||x.name||x);
      _setModels=(mo.models)||[]; _setModelActive=mo.active||'';
      // Inject a "Model" group at the top: a safe dropdown of installed models.
      // Switching hot-reloads via /v1/model (never a free-text path that could strand it).
      if(_setModels.length)_setSchema=[{key:'__model',type:'model',group:'Model',label:'Active model',hint:'Switch the loaded model — reloads, may take a moment'}].concat(_setSchema);
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
    if(it.type==='model'){const av=(_setModelActive||'').split('/').pop();return '<select class="setinput" onchange="switchModel(this.value)">'+_setModels.map(m=>'<option value="'+esc(m.path)+'" '+(m.name===av?'selected':'')+'>'+esc(m.name)+' ('+esc(''+m.size_gb)+'GB)</option>').join('')+'</select> <span id="model-switch-status" class="rnote"></span>';}
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
    if(isAdmin)h+='<div class="rrow" style="margin-top:14px"><button onclick="saveSettings(\''+esc(group)+'\')">Save '+esc(group)+'</button><span id="set-status-'+esc(group)+'" class="rnote" style="align-self:center"></span></div>';
    else h+='<div class="rnote" style="margin-top:10px">Sign in as admin to change settings.</div>';
    el.innerHTML=h;
    if(!isAdmin)el.querySelectorAll('[data-k]').forEach(x=>x.disabled=true);
  }
  function switchModel(path){
    const st=$('#model-switch-status');if(st)st.textContent='Switching… reloading (may take a moment)…';
    api('/v1/model',{method:'POST',body:JSON.stringify({path:path})}).then(function(r){
      if(r&&r.ok){_setModelActive=path;if(st)st.innerHTML='Switched &#10003; '+esc(path.split('/').pop());}
      else{if(st)st.innerHTML='<span style="color:#f87171">'+esc((r&&r.error)||'switch failed')+'</span>';}
    }).catch(e=>{if(st)st.textContent=''+e;});
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
          '<div class="rnote" style="margin-bottom:10px">Open your phone&#39;s camera and point it at this code — the dashboard opens automatically, already signed in. (Plain HTTP, so any phone opens it.)</div>'+
          '<div class="qrbox"><div id="qr-img" class="qrimg"><span class="muted">generating…</span></div></div>'+
          '<div class="connecturl"><code id="conn-url">'+esc(d.url)+'</code></div>'+
          '<div class="rrow" style="justify-content:center;margin-top:10px"><button class="cbtn" onclick="copyConnUrl()">&#128203; Copy link</button>'+
          '<button class="cbtn" onclick="loadConnect()">&#10227; Refresh</button></div>'+
          '<div class="rnote" style="margin-top:8px">Make sure the phone is on the <b>same Wi-Fi</b> as this computer.</div></div>';
        h+='<div class="jhead">Server port</div>'+
          '<div class="syscard">'+
          '<div class="rnote" style="margin-bottom:8px">ELI listens on port <b>'+esc(''+(d.port||'8081'))+'</b>. If that clashes with another device or app on your network, set a different one here — it applies the next time you start the server.</div>'+
          '<div class="rrow" style="gap:8px;align-items:center"><input id="apiport" type="number" min="1024" max="65535" placeholder="8081" value="'+esc(''+(d.saved_port||''))+'" style="width:130px">'+
          '<button class="cbtn" onclick="saveApiPort()">&#128190; Save port</button>'+
          '<button class="cbtn" onclick="saveApiPort(0)">Reset to 8081</button></div>'+
          '<div id="portmsg" class="rnote" style="margin-top:8px"></div></div>';
        if(d.https_available){
          h+='<div class="jhead">Phone microphone (voice)</div>'+
            '<div class="syscard" style="text-align:center">'+
            '<div class="rnote" style="margin-bottom:10px">The mic needs HTTPS. Scan <b>this</b> code instead to open the secure version — your phone shows a <b>“connection not private”</b> warning once (the cert is self-signed &amp; local); tap <b>Advanced &#8594; Proceed</b>. That accept unlocks the mic.</div>'+
            '<div class="qrbox"><div id="qr-voice" class="qrimg"><span class="muted">generating…</span></div></div>'+
            '<div class="connecturl"><code>'+esc(d.voice_url||'')+'</code></div></div>';
        } else {
          h+='<div class="syscard"><div class="row" style="gap:8px"><span class="ld warn" style="width:8px;height:8px;border-radius:50%;background:#e0a72e;box-shadow:0 0 8px #e0a72e"></span><b>Want the phone microphone too?</b></div>'+
            '<div class="rnote" style="margin-top:6px">Typed chat &amp; “Speak replies” already work on the phone. For the phone <b>mic</b>, also start HTTPS — one flag, cert generated locally; a second QR appears here for it:</div>'+
            '<div class="connecturl" style="margin:8px 0"><code>python api/server.py --lan --https</code></div></div>';
        }
        // Behavioural firewall detection: has any LAN device actually reached us yet?
        const fw=d.firewall||{}, cmds=(fw.commands||[]);
        const cmdHtml=cmds.map(c=>'<div class="connecturl" style="margin:6px 0"><code>'+esc(c)+'</code></div>').join('');
        if(!d.lan_clients_seen){
          h+='<div class="jhead">Phone can&#39;t connect?</div>'+
            '<div class="syscard"><div class="row" style="gap:8px"><span class="ld warn" style="width:9px;height:9px;border-radius:50%;background:#e0a72e;box-shadow:0 0 8px #e0a72e"></span><b>No device has reached the server yet.</b></div>'+
            '<div class="rnote" style="margin:6px 0 8px">The server is listening, but nothing on the network has connected — almost always your computer&#39;s <b>firewall</b> ('+esc(fw.tool||'firewall')+') blocking the port. Allow it for your LAN'+(cmds.length?':':'.')+'</div>'+
            cmdHtml+
            '<div class="rnote" style="margin-top:6px">Then re-scan. (Also: phone on the <b>same Wi-Fi</b>, and router <b>AP/client isolation</b> off.) This banner clears the moment any device gets through.</div></div>';
        } else {
          h+='<div class="syscard"><div class="row" style="gap:8px"><span class="ld live" style="width:9px;height:9px;border-radius:50%;background:#2ec07a;box-shadow:0 0 8px #2ec07a"></span><b>Devices are reaching the server</b> <span class="rnote">('+d.lan_client_count+' LAN request(s))</span></div>'+
            (cmds.length?('<div class="rnote" style="margin-top:6px">If a new device can&#39;t connect, allow the port through the firewall ('+esc(fw.tool||'')+'):</div>'+cmdHtml):'')+'</div>';
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
      if(d.lan_accessible){
        // Fetch the QR(s) WITH auth (an <img> can't send the token) and inject inline.
        fetch('/v1/connect/qr.svg?kind=connect',{headers:H()}).then(r=>r.ok?r.text():'').then(svg=>{
          const e=$('#qr-img'); if(e&&svg)e.innerHTML=svg;
        }).catch(()=>{});
        if(d.https_available){
          fetch('/v1/connect/qr.svg?kind=voice',{headers:H()}).then(r=>r.ok?r.text():'').then(svg=>{
            const e=$('#qr-voice'); if(e&&svg)e.innerHTML=svg;
          }).catch(()=>{});
        }
      }
    }).catch(e=>{$('#connect-tab').innerHTML='<div class="err">'+esc(''+e)+'</div>';});
  }
  function copyConnUrl(){const u=($('#conn-url')||{}).textContent||'';
    if(navigator.clipboard)navigator.clipboard.writeText(u).then(()=>{const b=event&&event.target;if(b){const o=b.textContent;b.textContent='Copied \u2713';setTimeout(()=>b.textContent=o,1400);}}).catch(()=>{});}
  function saveApiPort(reset){
    const el=$('#apiport'); const msg=$('#portmsg');
    let p = reset===0 ? 0 : parseInt((el&&el.value||'').trim(),10);
    if(reset!==0 && (!p || p<1024 || p>65535)){ if(msg)msg.innerHTML='<span style="color:#e0a72e">Enter a port between 1024 and 65535.</span>'; return; }
    fetch('/v1/connect/port',{method:'POST',headers:H({'Content-Type':'application/json'}),body:JSON.stringify({port:p})})
      .then(r=>r.json()).then(d=>{ if(msg)msg.innerHTML = d.ok
        ? '<span style="color:#33c07a">'+esc(d.note||'Saved.')+'</span>'
        : '<span style="color:#e05a5a">'+esc(d.detail||'Could not save.')+'</span>'; })
      .catch(e=>{ if(msg)msg.innerHTML='<span style="color:#e05a5a">'+esc(''+e)+'</span>'; });
  }
  window.loadConnect=loadConnect; window.copyConnUrl=copyConnUrl; window.saveApiPort=saveApiPort;
  function switchTab(t){document.querySelector('nav.tabs button[data-tab="'+t+'"]').click();}
  try{
    const _openTab=new URLSearchParams(location.search).get('open')||'';
    if(_openTab) switchTab(_openTab);
  }catch(e){}

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
    src=src.replace(/```(\w*)\n?([\s\S]*?)```/g,(m,lang,code)=>{blocks.push({lang:lang,code:code.replace(/\n$/,'')});return '\u0000B'+(blocks.length-1)+'\u0000';});
    src=esc(src);
    src=src.replace(/`([^`]+)`/g,(m,c)=>'<code class="ic">'+c+'</code>');
    src=src.replace(/\*\*([^*]+)\*\*/g,'<b>$1</b>').replace(/(^|[^*])\*([^*]+)\*/g,'$1<i>$2</i>');
    src=src.replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g,'<a href="$2" target="_blank" rel="noopener">$1</a>');
    const lines=src.split('\n'); let out=[],inList=false;
    for(let ln of lines){
      let h=ln.match(/^(#{1,4})\s+(.*)$/);
      if(h){if(inList){out.push('</ul>');inList=false;} const lv=Math.min(6,h[1].length+2); out.push('<h'+lv+' class="mh">'+h[2]+'</h'+lv+'>'); continue;}
      let li=ln.match(/^\s*[-*]\s+(.*)$/);
      if(li){if(!inList){out.push('<ul class="ml">');inList=true;} out.push('<li>'+li[1]+'</li>'); continue;}
      if(inList){out.push('</ul>');inList=false;}
      out.push(ln.trim()===''?'<br>':'<div>'+ln+'</div>');
    }
    if(inList)out.push('</ul>');
    let html=out.join('');
    html=html.replace(/\u0000B(\d+)\u0000/g,(m,i)=>{const b=blocks[i];return '<div class="cb"><div class="cbh"><span>'+esc(b.lang||'code')+'</span><button class="cpy" onclick="copyCode(this)">copy</button></div><pre><code>'+esc(b.code)+'</code></pre></div>';});
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
      // tries=2: one connection-establishment retry (power-save wake). Never retries once
      // the server has responded, so a partially-streamed reply can't be resubmitted.
      const r=await _fetchHeal('/v1/chat/stream',{method:'POST',headers:H(),body:JSON.stringify({message:text,user_id:uid,session_id:session}),signal:abortCtl.signal},2);
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
  /* Defer the first dashboard load to a macrotask so it runs AFTER the whole script has
     executed — loadOverview() touches OV_* state (let) declared further down; calling it
     synchronously here would hit the temporal dead zone and abort the rest of the script. */
  setTimeout(loadOverview,0);
  /* PWA: installable + offline shell. Force a fresh-code check on every load and
     auto-reload once a new worker takes control, so an installed PWA can never get
     stranded on a stale cached shell (e.g. one cached during a transient bad build). */
  // A service worker is great for offline PWA on localhost / a real HTTPS domain — but HARMFUL
  // on a self-signed LAN HTTPS origin (an IP host). There the browser treats the cert as
  // errored: SW registration is flaky and a stale one strands the phone on a blank/spinning
  // shell. That's exactly why the http://LAN-IP connect page works (no SW allowed there) while
  // the https://LAN-IP voice page goes blank (SW is the only difference). So on an IP-address
  // HTTPS origin we SKIP the SW and actively unregister any stale one + wipe its caches, which
  // also heals a phone already stranded by a previously-registered worker.
  var _ipHost=/^\d{1,3}(\.\d{1,3}){3}$/.test(location.hostname);
  if('serviceWorker' in navigator){try{
    if(location.protocol==='https:'&&_ipHost){
      navigator.serviceWorker.getRegistrations()
        .then(function(rs){rs.forEach(function(r){try{r.unregister();}catch(e){}});}).catch(function(){});
      if(window.caches){caches.keys()
        .then(function(ks){ks.forEach(function(k){try{caches.delete(k);}catch(e){}});}).catch(function(){});}
    } else {
      var _swReloading=false, _hadCtrl=!!navigator.serviceWorker.controller;
      navigator.serviceWorker.addEventListener('controllerchange',function(){
        // Reload only for a genuine UPDATE (a controller already existed) — never on the
        // first-ever claim, which used to race page load into a blank reload.
        if(_swReloading||!_hadCtrl)return; _swReloading=true; location.reload();
      });
      navigator.serviceWorker.register('/sw.js').then(function(reg){
        try{reg.update();}catch(e){}                       // check for a newer /sw.js now
        if(reg.waiting){try{reg.waiting.postMessage('skip');}catch(e){}}
      }).catch(function(){});
    }
  }catch(e){}}
  /* live: refresh the dashboard while it's open (no manual reload) */
  setInterval(function(){const v=$('#view-overview'); if(v&&v.classList.contains('active')&&!document.hidden&&!OV_EDIT&&!isOvEditingField())loadOverview();},6000);
  /* live: refresh Home connectivity (BT + speakers + LAN players) while that tab is open */
  setInterval(function(){
    if(document.hidden)return;
    const dev=$('#view-devices');
    if(!dev||!dev.classList.contains('active'))return;
    refreshHomeConnectivity();
    loadAudioOutputs();
    if(window._btBusy)return;
    const btBox=$('#home-bt-box'), btBtn=$('#home-bt-scan');
    api('/v1/devices/discover?kind=bluetooth&quick=1',{method:'POST',body:JSON.stringify({})})
      .then(d=>{if(d&&d.ok)renderBluetoothResults(d,btBox,btBtn,false);}).catch(()=>{});
    const netBox=$('#home-net-box'), netBtn=$('#home-net-scan');
    if(netBox&&!window._homeNetScanBusy){
      window._homeNetScanBusy=1;
      api('/v1/devices/discover?kind=network&timeout=6',{method:'POST',body:JSON.stringify({})})
        .then(d=>{
          window._homeNetScanBusy=0;
          if(!d||!d.ok||!netBox)return;
          const others=(d.found||[]).filter(f=>f.kind!=='mqtt_broker'&&f.kind!=='bluetooth');
          if(!others.length)return;
          window._homeNetDisc=others;
          let h='<div class="rnote" style="margin-bottom:8px">Devices on your network (auto-refreshed):</div>';
          const ADDABLE={airplay:1,firetv:1,cast:1,upnp_renderer:1,sonos:1};
          others.forEach((f,i)=>{
            const add=ADDABLE[f.kind]?'<button class="cbtn" style="padding:2px 10px" onclick="addHomeNetDevice('+i+')">Add</button>':'';
            h+='<div class="src"><div class="sh"><span>'+esc(f.label||f.kind)+' — '+esc(f.name||'')+'</span><span>'+add+'</span></div></div>';
          });
          netBox.innerHTML=h;
        }).catch(()=>{window._homeNetScanBusy=0;});
    }
  },12000);

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
        if(!text){vmsg('Didn\'t catch that — try again');return;}
        vmsg('');box.value='';
        await streamChat(text);   // streamChat speaks the reply itself when Speak-replies is on
      }catch(e){vmsg('Voice error: '+e);}
    };
    recording=true;mic.classList.add('rec');vmsg('Listening… tap mic to stop');mediaRec.start();
  }
  let _ttsAudio=null;
  async function speakReply(text){
    // Strip markdown/code so Piper reads prose, not asterisks and backticks.
    const clean=(''+text).replace(/```[\s\S]*?```/g,' ').replace(/`([^`]+)`/g,'$1')
      .replace(/[*_#>~]/g,'').replace(/\[(.*?)\]\(.*?\)/g,'$1').replace(/\s+/g,' ').trim();
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
      '<button class="cbtn" id="mq-find" onclick="discoverDevices()">&#128270; Find on my network</button>'+
      '<button class="cbtn" id="bt-find" onclick="searchBluetooth()">&#127911; Search Bluetooth</button></div>'+
      '<div id="mq-found"></div></div>';
  }
  function discoverDevices(boxSel, btnSel){
    const box=$(boxSel||'#mq-found'), btn=$(btnSel||'#mq-find');
    if(btn){btn.disabled=true;btn.textContent='Scanning…';}
    if(box)box.innerHTML='<div class="rnote">Scanning your LAN (mDNS + UPnP) — no cloud…</div>';
    api('/v1/devices/discover',{method:'POST',body:JSON.stringify({})}).then(d=>{
      if(btn){btn.disabled=false;btn.innerHTML='&#128270; Find on my network';}
      if(!box)return;
      if(!d.ok){box.innerHTML='<div class="banner bad" style="margin-top:10px">'+esc(d.error||'discovery failed')+'</div>';return;}
      const all=d.found||[], br=d.brokers||[], c=d.counts||{};
      const lab={ready:'control ready',roadmap:'control coming',cloud:'not local',detected:'detected'};
      const col={ready:'#2ec07a',roadmap:'#e0a72e',cloud:'#6aa3e0',detected:'#7a8699'};
      let h='';
      if(br.length){h+='<div class="rnote" style="margin-top:10px">MQTT broker(s) found — click to use:</div>';
        br.forEach(b=>{h+='<div class="src" style="cursor:pointer" onclick="useBroker(\''+esc(b.host)+'\','+(b.port||1883)+')"><div class="sh"><span>&#128268; '+esc(b.name||b.host)+'</span><span>'+esc(b.host)+':'+(b.port||'')+'</span></div></div>';});}
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
    }).catch(e=>{if(btn){btn.disabled=false;btn.innerHTML='&#128270; Find on my network';}if(box)box.innerHTML='<div class="banner bad">'+esc(''+e)+'</div>';});
  }
  window._btStatus=window._btStatus||{};
  window._btBusy=false;
  function _btKey(f){return String((f&&f.host)||'').toUpperCase();}
  function _btPaintStatus(key){
    const s=window._btStatus[key]; if(!s)return;
    const el=document.querySelector('.bt-st[data-bt="'+key+'"]');
    if(el)el.innerHTML=s.html;
  }
  function _btSetStatus(key,html,busy){
    window._btStatus[key]={html:html,t:Date.now(),busy:!!busy};
    if(busy)window._btBusy=true;
    _btPaintStatus(key);
  }
  function _btClearBusy(key){
    const s=window._btStatus[key]; if(s)s.busy=false;
    window._btBusy=Object.keys(window._btStatus).some(function(k){return window._btStatus[k].busy;});
  }
  function renderBluetoothResults(d, box, btn, scanning){
    if(!box)return;
    if(btn&&!scanning&&!window._btBusy){btn.disabled=false;btn.innerHTML='&#127911; Search Bluetooth';}
    if(!d.ok){box.innerHTML='<div class="banner bad" style="margin-top:10px">'+esc(d.error||'scan failed')+'</div>';return;}
    const bt=(d.found||[]).filter(f=>f.kind==='bluetooth'); window._bt=bt;
    let h='';
    if(!bt.length){
      const errs=d.errors||[];
      const radio=errs.find(e=>/radio unavailable|adapter down|replug/i.test(e));
      const note=radio||errs.find(e=>/bluetooth/i.test(e)&&!/BLE scan failed/i.test(e))||errs.find(e=>/bluetooth/i.test(e));
      if(radio){
        h='<div class="banner bad" style="margin-top:10px"><b>Bluetooth radio is off</b><br>ELI cannot scan until the adapter is up.<br><span style="opacity:.9">'+esc(note.replace(/^Bluetooth radio unavailable — /i,''))+'</span></div>';
      } else {
        h='<div class="rnote" style="margin-top:10px">No Bluetooth devices found. '+(note?esc(note):'Turn Bluetooth on and put headphones or speakers in pairing mode.')+'</div>';
      }
    } else {
      const connected=bt.filter(f=>f.connected);
      const adapters=connected.filter(f=>f.bt_type==='adapter'&&!f.audio_capable);
      if(adapters.length){
        h+='<div class="banner bad" style="margin-bottom:8px"><b>Connected to a BT adapter, not headphones</b><br>'
          +esc(adapters.map(f=>f.name||f.host).join(', '))+' is a Bluetooth adapter — pair <b>your headphones</b> for audio instead.</div>';
      } else if(connected.length){
        h+='<div class="rnote" style="margin-bottom:8px;color:#2ec07a">&#10003; Connected: '+connected.map(f=>esc(f.name||f.host)).join(', ')+'</div>';
      }
      h+='<div class="rnote" style="margin-top:8px">'+(scanning?'Scanning for more devices… ':'')
        +'<b>Headphones:</b> put them in pairing mode (LED flashing), then tap <b>Connect for music</b> — one step, full quality audio.</div>';
      bt.forEach((f,i)=>{
        const tag=f.label||f.bt_type||'device';
        const cap=f.audio_capable?'&#127911; ':'&#128268; ';
        const st=f.connected?' &middot; <span style="color:#2ec07a">connected</span>':(f.paired?' &middot; paired':'');
        const bkey=_btKey(f);
        const saved=window._btStatus[bkey];
        const stHtml=saved&&saved.html?saved.html:'';
        const busy=saved&&saved.busy;
        let btns='';
        if(f.bt_type==='printer'||f.bt_type==='adapter'){
          btns='<span class="rnote" style="font-size:.85em">'+(f.bt_type==='printer'?'Printer — not for audio':'BT adapter — pair headphones instead')+'</span>';
        } else if(f.audio_capable){
          btns='<button class="cbtn pri" style="padding:4px 14px"'+(busy?' disabled':'')+' onclick="btDo('+i+',2)">Connect for music</button>'
            +'<button class="cbtn" style="padding:2px 10px;opacity:.75"'+(busy?' disabled':'')+' onclick="btDo('+i+',3)">Disconnect</button>';
        } else {
          btns='<button class="cbtn" style="padding:2px 10px"'+(busy?' disabled':'')+' onclick="btDo('+i+',1)">Pair</button>'
            +'<button class="cbtn" style="padding:2px 10px"'+(busy?' disabled':'')+' onclick="btDo('+i+',3)">Disconnect</button>';
        }
        h+='<div class="src"><div class="sh"><span>'+cap+esc(f.name||'Bluetooth device')+'</span>'
          +'<span style="font-size:.75em;opacity:.7">'+esc(tag)+st+'</span>'
          +'<span style="display:flex;gap:6px;flex-wrap:wrap">'+btns+'</span></div>'
          +'<div style="font-size:.8em;opacity:.6">'+esc(f.host||'')+(f.rssi?(' &middot; '+esc(f.rssi)+' dBm'):'')+'</div>'
          +'<div class="rnote bt-st" data-bt="'+esc(bkey)+'" id="bt-st-'+i+'" style="opacity:.75">'+stHtml+'</div></div>';
      });
    }
    box.innerHTML=h;
  }
  function searchBluetooth(boxSel, btnSel){
    if(window._btBusy)return;
    const box=$(boxSel||'#mq-found'), btn=$(btnSel||'#bt-find');
    if(btn){btn.disabled=true;btn.textContent='Scanning…';}
    if(box)box.innerHTML='<div class="rnote">Loading known Bluetooth devices…</div>';
    api('/v1/devices/discover?kind=bluetooth&fresh=true&quick=1',{method:'POST',body:JSON.stringify({})}).then(d=>{
      renderBluetoothResults(d, box, btn, true);
      return api('/v1/devices/discover?kind=bluetooth&fresh=false&timeout=15',{method:'POST',body:JSON.stringify({})});
    }).then(d=>{
      if(d)renderBluetoothResults(d, box, btn, false);
    }).catch(e=>{if(btn){btn.disabled=false;btn.innerHTML='&#127911; Search Bluetooth';}if(box)box.innerHTML='<div class="banner bad">'+esc(''+e)+'</div>';});
  }
  function btDoAddr(addr,cmd,name){
    if(!addr){alert('No Bluetooth address');return;}
    api('/v1/devices/bluetooth',{method:'POST',body:JSON.stringify({address:addr,name:name||'',command:cmd||'connect'})}).then(r=>{
      if(!r.ok)alert((r.error||'Bluetooth failed').slice(0,200));
      else if(cmd==='use_for_audio'){loadAudioOutputs();refreshHomeConnectivity();}
      loadDevices();
    }).catch(e=>alert(''+e));
  }
  function btDo(i,c){
    const f=(window._bt||[])[i]; if(!f||window._btBusy)return;
    const cmd=['connect','pair','use_for_audio','disconnect'][c]||'connect';
    const key=_btKey(f);
    const labels={pair:'Pairing headphones (keep LED flashing)',connect:'Connecting',use_for_audio:'Connecting for music — pairing + high-quality audio',disconnect:'Disconnecting'};
    let elapsed=0;
    window._btBusy=true;
    _btSetStatus(key,esc(labels[cmd]||cmd)+' (0s)…',true);
    const tick=setInterval(function(){
      elapsed++;
      _btSetStatus(key,esc(labels[cmd]||cmd)+' ('+elapsed+'s)…',true);
    },1000);
    api('/v1/devices/bluetooth',{method:'POST',body:JSON.stringify({address:f.host||'',name:f.name||'',command:cmd})}).then(r=>{
      clearInterval(tick);
      const dur=r&&r.duration_s?(' ('+Math.round(r.duration_s)+'s)'):'';
      const done={pair:'paired',connect:'connected',use_for_audio:'playing music here',disconnect:'disconnected'};
      if(r&&r.ok){
        _btSetStatus(key,'&#10003; '+esc(r.device_name||f.name||'device')+' '+esc(done[cmd]||'done')+dur+(r.sink?(' &rarr; '+esc(r.sink)):''),false);
      } else {
        const hint=(r&&r.error)||(r&&r.output&&r.output.slice(0,160))||'failed';
        _btSetStatus(key,'<span style="color:#f87171">'+esc(hint)+dur+'</span>',false);
      }
      _btClearBusy(key);
      if(r&&r.ok&&cmd==='use_for_audio'){
        loadAudioOutputs();refreshHomeConnectivity();
        if(r.sink)setAudioOutput(r.sink);
      }
      loadAudioOutputs();
      setTimeout(function(){
        if(window._btBusy)return;
        const btBox=$('#home-bt-box'), btBtn=$('#home-bt-scan');
        api('/v1/devices/discover?kind=bluetooth&quick=1',{method:'POST',body:JSON.stringify({})})
          .then(function(d){if(d&&d.ok)renderBluetoothResults(d,btBox,btBtn,false);}).catch(function(){});
      },4000);
    }).catch(e=>{
      clearInterval(tick);
      _btSetStatus(key,'<span style="color:#f87171">'+esc(''+e)+'</span>',false);
      _btClearBusy(key);
    });
  }
  function refreshHomeConnectivity(){
    api('/v1/connectivity/status').then(d=>{
      const w=(d&&d.wifi)||{}, a=(d&&d.audio)||{}, b=(d&&d.bluetooth)||{};
      const ws=$('#ls-wifi'), as=$('#ls-audio'), bs=$('#ls-bt');
      if(ws)ws.innerHTML=w.connected?('<span class="ld live"></span>'+esc(w.ssid||'WiFi')):'<span class="ld warn"></span>WiFi';
      if(as)as.innerHTML=a.default_sink?('<span class="ld live"></span>'+esc((a.default_sink||'').split('.').pop().slice(0,24))):'<span class="ld warn"></span>audio';
      if(bs)bs.innerHTML=b.available?(b.powered?'<span class="ld live"></span>BT':(b.radio_down?'<span class="ld warn"></span>BT down':'<span class="ld warn"></span>BT off')):'<span class="ld off"></span>BT';
      const alias=b.adapter_name||'Eli · Home';
      const btHint=b.recovery_hint||'';
      const homeBt=$('#home-bt-box');
      if(homeBt&&btHint&&b.radio_down&&!homeBt.querySelector('.src')){
        homeBt.innerHTML='<div class="banner bad" style="margin-top:8px"><b>Bluetooth radio is off</b><br>'+esc(btHint)+'</div>';
      }
      const hint=$('#bt-alias-hint'); if(hint)hint.textContent=alias;
      const homeHint=$('#home-bt-alias'); if(homeHint)homeHint.textContent=alias;
      const pill=$('#home-wifi-pill'); if(pill&&w.connected)pill.innerHTML='&#10003; Connected to <b>'+esc(w.ssid)+'</b>'+(w.signal?(' &middot; '+w.signal+'%'):'');
      else if(pill&&!w.connected&&w.available)pill.innerHTML='Not on WiFi — scan and join below so LAN devices can be found.';
      else if(pill&&pill.dataset)pill.innerHTML=pill.dataset.fallback||'';
    }).catch(()=>{});
  }
  function wifiScan(){
    const box=$('#home-wifi-list'); if(!box)return;
    box.innerHTML='<div class="rnote">Scanning nearby networks…</div>';
    api('/v1/connectivity/wifi/networks').then(d=>{
      if(!d.ok){box.innerHTML='<div class="banner bad">'+esc(d.error||'scan failed')+'</div>';return;}
      const nets=d.networks||[];
      if(!nets.length){box.innerHTML='<div class="rnote">No networks found. Check WiFi is on, or use your system settings.</div>';return;}
      window._wifiNets=nets;
      let h='<div class="rnote" style="margin-bottom:8px">Tap a network to join — credentials stay on this machine only.</div>';
      nets.forEach((n,i)=>{
        const sec=n.security&&n.security!=='--'?esc(n.security):'open';
        h+='<div class="src" style="cursor:pointer" onclick="wifiConnectAt('+i+')">'
          +'<div class="sh"><span>'+(n.in_use?'&#10003; ':'')+esc(n.ssid)+'</span>'
          +'<span>'+esc(''+n.signal)+'% &middot; '+sec+'</span></div></div>';
      });
      box.innerHTML=h;
    }).catch(e=>{box.innerHTML='<div class="banner bad">'+esc(''+e)+'</div>';});
  }
  function wifiConnectAt(i){
    const n=(window._wifiNets||[])[i]; if(!n)return;
    wifiConnectPrompt(n.ssid||'');
  }
  function wifiConnectPrompt(ssid){
    const pw=prompt('Password for "'+ssid+'" (leave blank if open):','');
    if(pw===null)return;
    const st=$('#home-wifi-status'); if(st)st.textContent='Joining '+ssid+'…';
    api('/v1/connectivity/wifi/connect',{method:'POST',body:JSON.stringify({ssid:ssid,password:pw||''})}).then(r=>{
      if(st)st.innerHTML=r.ok?('<span style="color:#2ec07a">&#10003; Connected to '+esc(ssid)+'</span>'):('<span style="color:#f87171">'+esc(r.error||r.output||'failed')+'</span>');
      if(r.ok){refreshHomeConnectivity();wifiScan();}
    }).catch(e=>{if(st)st.innerHTML='<span style="color:#f87171">'+esc(''+e)+'</span>';});
  }
  function setAudioAlias(i,name){
    const s=(window._audioSinks||[])[i]; if(!s)return;
    api('/v1/connectivity/audio/alias',{method:'POST',body:JSON.stringify({sink:s.id,name:name||''})})
      .then(()=>{loadAudioOutputs();refreshHomeConnectivity();});
  }
  function loadAudioOutputs(){
    const box=$('#home-audio-list'); if(!box)return;
    box.innerHTML='<div class="rnote">Loading speakers…</div>';
    api('/v1/connectivity/audio/outputs?refresh=1').then(d=>{
      if(!d.ok){box.innerHTML='<div class="banner bad">'+esc(d.error||'unavailable')+'</div>';return;}
      const sinks=d.sinks||[];
      if(!sinks.length){box.innerHTML='<div class="rnote">No audio outputs found. Connect speakers via cable or Bluetooth first.</div>';return;}
      window._audioSinks=sinks;
      let h='<div class="rnote" style="margin-bottom:8px">Name your speakers so you can say <b>Eli, play music to kitchen speaker</b> or <b>device 1</b>.</div>';
      sinks.forEach((s,i)=>{
        const nm=esc(s.display_name||s.name||s.id);
        const def=s.is_default?' <span style="color:#2ec07a">(current)</span>':'';
        const kind=s.kind==='bluetooth'?'&#127911; ':'&#128266; ';
        const devNum=s.device_number|| (i+1);
        h+='<div class="src"><div class="sh"><span>'+kind+nm+def+'</span>'
          +'<span style="font-size:.75em;opacity:.65">Device '+devNum+'</span>'
          +(s.is_default?'':'<button class="cbtn pri" style="padding:2px 10px" onclick="setAudioOutputAt('+i+')">Use this</button>')
          +'</div>'
          +'<div style="display:flex;gap:6px;margin-top:6px;flex-wrap:wrap">'
          +'<input class="inp" style="flex:1;min-width:140px" placeholder="Name e.g. Kitchen speaker" value="'+esc(s.alias||'')+'" onchange="setAudioAlias('+i+',this.value)">'
          +'</div></div>';
      });
      box.innerHTML=h;
    }).catch(e=>{box.innerHTML='<div class="banner bad">'+esc(''+e)+'</div>';});
  }
  function setAudioOutputAt(i){
    const s=(window._audioSinks||[])[i]; if(!s)return;
    setAudioOutput(s.id||s.name||'');
  }
  function setAudioOutput(sink){
    const st=$('#home-audio-status'); if(st)st.textContent='Switching output…';
    api('/v1/connectivity/audio/default',{method:'POST',body:JSON.stringify({sink:sink})}).then(r=>{
      if(st)st.innerHTML=r.ok?'<span style="color:#2ec07a">&#10003; Audio routed</span>':'<span style="color:#f87171">'+esc(r.error||'failed')+'</span>';
      if(r.ok){loadAudioOutputs();refreshHomeConnectivity();}
    }).catch(e=>{if(st)st.innerHTML='<span style="color:#f87171">'+esc(''+e)+'</span>';});
  }
  function homeQuickScan(){
    wifiScan();
    searchBluetooth('#home-bt-box','#home-bt-scan');
    loadAudioOutputs();
    discoverDevices('#home-net-box','#home-net-scan');
    refreshHomeConnectivity();
  }
  function useBroker(host,port){const h=$('#mq_host'),p=$('#mq_port');if(h)h.value=host;if(p)p.value=port||1883;const f=$('#mq-found');if(f)f.innerHTML='<div class="rnote" style="margin-top:10px">Broker set to '+esc(host)+'. Click &ldquo;Save &amp; connect&rdquo;.</div>';}
  function openDiscover(){let f=$('#mq-found');if(!f){f=document.createElement('div');f.id='mq-found';$('#devices').appendChild(f);}f.scrollIntoView({behavior:'smooth',block:'nearest'});discoverDevices();}
  function addDiscovered(i){const f=(window._disc||[])[i];if(!f)return;
    api('/v1/devices/add-discovered',{method:'POST',body:JSON.stringify({device:f})}).then(r=>{
      if(!r.ok){alert(r.error||'Could not add device');return;}
      loadDrivers().then(loadDevices);
    }).catch(e=>alert(''+e));}
  function addHomeNetDevice(i){const f=(window._homeNetDisc||[])[i];if(!f)return;
    api('/v1/devices/add-discovered',{method:'POST',body:JSON.stringify({device:f})}).then(r=>{
      if(!r.ok){alert(r.error||'Could not add device');return;}
      loadDrivers().then(loadDevices);
    }).catch(e=>alert(''+e));}
  function saveDevConfig(){
    const body={host:($('#mq_host').value||'').trim(), port:parseInt($('#mq_port').value||'1883',10)||1883,
      username:($('#mq_user').value||'').trim(), password:$('#mq_pass').value||'',
      discovery_prefix:($('#mq_disc').value||'').trim(), tls:!!($('#mq_tls')&&$('#mq_tls').checked)};
    const cfgbox=$('#broker-cfg-mqtt')||$('#broker-cfg')||$('#broker-cfg2');
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
    const card=document.createElement('div');card.className='card hubopen'+(_devHubId===dv.id?' devsel':'');
    card.onclick=(e)=>{if(e.target.closest('button,input,label'))return;openDeviceHub(dv.id);};
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
        if(!r.ok){ib.disabled=false;ib.textContent='Install';alert('Install failed: '+(r.error||'')+(r.log?('\n'+r.log):''));return;}
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
    card.className='card hubopen'+(_devHubId===dv.id?' devsel':'')+(on?' on':(off?' off':''));
    card.onclick=(e)=>{if(e.target.closest('button,input,label,.sw'))return;openDeviceHub(dv.id);};
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
    } else if(['media','speaker','tv','cast','chromecast','airplay','dlna','upnp','firetv','sonos','player','renderer'].indexOf(t)>=0){
      // Advanced media tile: inline transport + volume so common actions don't need the hub.
      card.innerHTML=head+'<div class="row mediactl" style="gap:6px;flex-wrap:wrap">'
        +'<button class="cbtn" title="Play">&#9654;</button>'
        +'<button class="cbtn" title="Pause">&#10073;&#10073;</button>'
        +'<button class="cbtn" title="Stop">&#9632;</button>'
        +'<input class="brange" type="range" min="0" max="100" value="'+(parseInt(dv.volume,10)||40)+'" title="Volume" style="flex:1;min-width:70px">'
        +'</div>';
      const mb=card.querySelectorAll('.mediactl button');
      if(mb[0])mb[0].onclick=()=>ctlDev(dv.id,'play');
      if(mb[1])mb[1].onclick=()=>ctlDev(dv.id,'pause');
      if(mb[2])mb[2].onclick=()=>ctlDev(dv.id,'stop');
      const vol=card.querySelector('input[type=range]');
      if(vol){let vt;vol.oninput=()=>{clearTimeout(vt);vt=setTimeout(()=>ctlDev(dv.id,'volume',+vol.value),250);};}
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
  let _homeSub='setup', _devHubId='', _devHubSub='connect';
  function openDeviceHub(id){_devHubId=id;_homeSub='devices';loadDevices();}
  function playOnDevice(id, url, contentType){
    const u=(url||'').trim(); if(!u){alert('Enter a URL');return;}
    const body={device_id:id,command:'play_url',value:u};
    if(contentType)body.value={url:u,content_type:contentType};
    api('/v1/devices/control',{method:'POST',body:JSON.stringify(body)}).then(r=>{
      if(!r.ok)alert('Play failed: '+(r.error||'')); else alert('Sent to device');
    }).catch(e=>alert(''+e));
  }
  function devHubCaps(dv){
    const drv=DRIVERS[dv.driver]||{};
    if(dv.driver&&dv.driver!=='mqtt')return DRIVER_CAPS[dv.driver]||[];
    const t=dv.type||'switch';
    if(t==='light'||t==='switch'||t==='fan'||t==='outlet')return['on','off'].concat(t==='light'&&((dv.attrs||{}).brightness_command_topic)?['volume']:'');
    return[];
  }
  function paneDevConnect(el,dv){
    const drv=DRIVERS[dv.driver]||{};
    let btAddr='';
    let h='<div class="devhub-hd"><span class="dicon">'+(DEV_ICON[dv.type]||'&#9670;')+'</span><div><div class="nm">'+esc(dv.name||dv.id)+'</div><div class="dom">'+esc(dv.room||'Unassigned')+' · '+esc(drv.label||dv.driver||'device')+'</div></div></div>';
    if(dv.driver==='bluetooth'||(dv.attrs||{}).address){
      btAddr=dv.host||(dv.attrs||{}).address||'';
      h+='<div class="syscard"><div class="jhead">Bluetooth</div><p class="rnote">'+esc(btAddr||'no address')+'</p><div class="devact">'
        +'<button class="cbtn" data-bt="pair">Pair</button>'
        +'<button class="cbtn" data-bt="connect">Connect</button>'
        +'<button class="cbtn pri" data-bt="use_for_audio">Use for audio</button></div></div>';
    } else if(drv.needs_pairing&&!isPaired(dv)){
      h+='<div class="syscard"><div class="jhead">Pairing required</div><p class="rnote">This device must be paired before control or casting.</p>'
        +'<button class="cbtn pri" id="dh-connect-pair">Pair now</button></div>';
    } else if(['cast','upnp','airplay','firetv'].indexOf(dv.driver)>=0){
      h+='<div class="syscard"><div class="jhead">Network device</div><p class="rnote">Reachable on your LAN at <b>'+esc(dv.host||'?')+'</b>. No extra pairing needed'+(dv.driver==='cast'||dv.driver==='upnp'?' for basic casting':'')+'.</p></div>';
    } else {
      h+='<div class="syscard"><div class="jhead">WiFi &amp; LAN</div><p class="rnote">WiFi is configured on this hub (not per device). Use <b>Quick setup</b> to join a network and scan for players.</p>'
        +'<button class="cbtn" onclick="_homeSub=\'setup\';loadDevices()">Open Quick setup</button></div>';
    }
    if(!drv.installed&&dv.driver&&dv.driver!=='mqtt'){
      h+='<div class="banner bad" style="margin-top:10px">Driver not installed — install from the Controls tab.</div>';
    }
    el.innerHTML=h;
    const cp=el.querySelector('#dh-connect-pair');if(cp)cp.onclick=()=>pairDialog(dv);
    el.querySelectorAll('[data-bt]').forEach(b=>{b.onclick=()=>btDoAddr(btAddr,b.dataset.bt,dv.name||'');});
  }
  function paneDevMedia(el,dv){
    const drv=DRIVERS[dv.driver]||{};
    const canCast=['cast','upnp','firetv'].indexOf(dv.driver)>=0;
    const needsPair=drv.needs_pairing&&!isPaired(dv);
    let h='<div class="jhead">Play media on this device</div>';
    if(needsPair){
      h+='<div class="muted">Pair this device first (Connect tab).</div>';
    } else if(canCast||dv.driver==='airplay'){
      h+='<div class="syscard"><p class="rnote">Push a URL — video, audio, or image — to '+esc(dv.name||dv.id)+'.</p>'
        +'<div class="devurl"><input id="dh-url-'+esc(dv.id)+'" type="url" placeholder="https://… mp4, mp3, or image URL">'
        +'<button class="cbtn pri" onclick="playOnDevice(\''+esc(dv.id)+'\',document.getElementById(\'dh-url-'+esc(dv.id)+'\').value)">Play</button></div>'
        +'<div class="devact" style="margin-top:8px">'
        +'<button class="cbtn" onclick="document.getElementById(\'dh-url-'+esc(dv.id)+'\').value=\'https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4\';playOnDevice(\''+esc(dv.id)+'\',document.getElementById(\'dh-url-'+esc(dv.id)+'\').value)">Sample video</button>'
        +'</div></div>';
    } else if(dv.driver==='bluetooth'){
      h+='<div class="syscard"><p class="rnote">Route system audio to this Bluetooth device, then play from Spotify, VLC, or ELI voice on this PC.</p>'
        +'<button class="cbtn pri" id="dh-bt-audio">Use for audio</button></div>';
    } else {
      h+='<div class="muted">Media push is for Cast, UPnP, Fire TV, and AirPlay devices. MQTT lights use Controls.</div>';
    }
    h+='<div class="jhead" style="margin-top:16px">Cast ELI to a screen</div>'
      +'<div class="syscard"><p class="rnote">Open this page on your TV browser, or use Chrome &ldquo;Cast tab&rdquo; to mirror the ELI dashboard. Phone screen mirroring (WebRTC) is planned for a later release.</p>'
      +'<div class="devact"><button class="cbtn" onclick="navigator.clipboard&&navigator.clipboard.writeText(location.href);alert(\'Link copied — open on your TV browser\')">Copy dashboard URL</button></div></div>';
    el.innerHTML=h;
    const ba=el.querySelector('#dh-bt-audio');if(ba)ba.onclick=()=>btDoAddr(dv.host||'','use_for_audio',dv.name||'');
  }
  function paneDevControls(el,dv){
    const drv=DRIVERS[dv.driver]||{};
    let h='<div class="jhead">Controls</div>';
    if(!drv.installed&&dv.driver&&dv.driver!=='mqtt'){
      h+='<div class="syscard"><span class="st" style="color:#e0a72e">driver needed</span> '
        +'<button class="cbtn" id="dh-install">Install '+esc(drv.pip||dv.driver)+'</button></div>';
    } else if(drv.needs_pairing&&!isPaired(dv)){
      h+='<div class="syscard"><button class="cbtn pri" id="dh-pair">Pair device</button></div>';
    } else {
      const caps=devHubCaps(dv);
      h+='<div class="syscard"><div class="devact">';
      caps.forEach(c=>{
        const lbl=CAP_LABEL[c]||c;
        h+='<button class="cbtn" data-cap="'+c+'">'+lbl+'</button>';
      });
      h+='</div></div>';
      if((dv.type==='light'||dv.type==='switch')&&dv.driver==='mqtt'){
        const on=(''+(dv.state||'')).toUpperCase()==='ON';
        h+='<div class="syscard" style="margin-top:10px"><label class="sw"><input type="checkbox" id="dh-sw" '+(on?'checked':'')+'><span></span></label> Power</div>';
        if(dv.type==='light'&&(dv.attrs||{}).brightness_command_topic){
          h+='<div class="syscard" style="margin-top:10px"><input class="brange" type="range" id="dh-bri" min="1" max="100" value="100"></div>';
        }
      }
    }
    el.innerHTML=h;
    const ib=el.querySelector('#dh-install');
    if(ib)ib.onclick=()=>{ib.disabled=true;api('/v1/devices/driver/install',{method:'POST',body:JSON.stringify({name:dv.driver})}).then(r=>{
      if(!r.ok){ib.disabled=false;alert(r.error||'install failed');}else loadDevices();
    });};
    const pb=el.querySelector('#dh-pair');if(pb)pb.onclick=()=>pairDialog(dv);
    el.querySelectorAll('[data-cap]').forEach(b=>{b.onclick=()=>{
      let v=null;if(b.dataset.cap==='volume'){v=prompt('Volume 0–100:','30');if(v===null)return;v=parseInt(v,10)||0;}
      ctlDev(dv.id,b.dataset.cap,v);
    };});
    const sw=el.querySelector('#dh-sw');if(sw)sw.onchange=()=>ctlDev(dv.id,sw.checked?'on':'off');
    const bri=el.querySelector('#dh-bri');if(bri){let t;bri.oninput=()=>{clearTimeout(t);t=setTimeout(()=>ctlDev(dv.id,'brightness',+bri.value),250);};}
  }
  function paneDevInfo(el,dv){
    const drv=DRIVERS[dv.driver]||{};
    el.innerHTML='<div class="syscard">'
      +'<div class="kv">ID<span>'+esc(dv.id)+'</span></div>'
      +'<div class="kv">Name<span>'+esc(dv.name||'—')+'</span></div>'
      +'<div class="kv">Room<span>'+esc(dv.room||'Unassigned')+'</span></div>'
      +'<div class="kv">Type<span>'+esc(dv.type||'—')+'</span></div>'
      +'<div class="kv">Driver<span>'+esc(drv.label||dv.driver||'mqtt')+'</span></div>'
      +'<div class="kv">Host<span>'+esc(dv.host||'—')+'</span></div>'
      +'<div class="kv">State<span>'+esc(''+(dv.state||'—'))+'</span></div>'
      +'</div><div class="devact" style="margin-top:12px">'
      +'<button class="cbtn" id="dh-info-room">Change room</button>'
      +'<button class="cbtn" id="dh-info-rm">Remove</button>'
      +'</div>';
    const rb=el.querySelector('#dh-info-room');if(rb)rb.onclick=()=>moveDevice(dv);
    const rm=el.querySelector('#dh-info-rm');
    if(rm)rm.onclick=()=>{if(confirm('Remove this device?'))api('/v1/devices/remove',{method:'POST',body:JSON.stringify({device_id:dv.id})}).then(loadDevices);};
  }
  function paneMeshBrains(el){
    el.innerHTML='<div class="syscard"><div class="muted">Loading mesh…</div></div>';
    api('/v1/home/mesh/status').then(d=>{
      if(!d||!d.ok){el.innerHTML='<div class="err">mesh unavailable</div>';return;}
      const cfg=d.config||{}, rt=d.runtime||{}, node=d.node||{};
      const mode=rt.mode||'off';
      const modeLbl={cognition:'Primary brain — full cognition',standby:'Standby — watching primary',acting_secondary:'Secondary brain ACTIVE (primary down)',acting_tertiary:'Tertiary brain ACTIVE',reflex:'Reflex mode — local devices only',off:'Mesh off'}[mode]||mode;
      let h='<div class="syscard" style="border-color:rgba(34,211,238,.3);margin-bottom:14px">'
        +'<div class="jhead">Home mesh</div>'
        +'<p class="rnote" style="line-height:1.65">Tiered brains for smart home. Primary runs full ELI. Secondary / tertiary nodes watch heartbeats and take over if the main PC dies — stays on your LAN, no cloud.</p>'
        +'<div class="kv">Status<span><b>'+esc(modeLbl)+'</b></span></div>'
        +'<div class="kv">This node<span>'+esc(node.node_name||cfg.node_name||'?')+' <span class="rnote">('+esc(cfg.role||'off')+')</span></span></div>'
        +'<div class="kv">Acting brain<span>'+esc(rt.acting_brain||'—')+'</span></div>'
        +'<div class="kv">Primary reachable<span>'+(rt.primary_alive?'yes':'no')+'</span></div>'
        +(rt.failover_reason?'<div class="banner bad" style="margin-top:10px">'+esc(rt.failover_reason)+'</div>':'')
        +'</div>';
      h+='<div class="syscard"><div class="jhead">Configure this machine</div>'
        +'<div class="setrow"><span class="setlbl">Enable mesh</span><label class="sw"><input type="checkbox" id="mh-en" '+(cfg.enabled?'checked':'')+'><span></span></label></div>'
        +'<div class="setrow"><span class="setlbl">Role</span><select id="mh-role" class="setinput"><option value="off">off</option><option value="primary">primary (main PC)</option><option value="secondary">secondary (2nd brain)</option><option value="tertiary">tertiary (3rd brain)</option><option value="reflex">reflex (edge only)</option></select></div>'
        +'<div class="setrow"><span class="setlbl">Node name</span><input id="mh-name" class="setinput" value="'+esc(cfg.node_name||'')+'"></div>'
        +'<div class="setrow"><span class="setlbl">Primary URL</span><input id="mh-primary" class="setinput" placeholder="https://192.168.1.10:8765" value="'+esc(cfg.primary_url||location.origin)+'"></div>'
        +'<div class="setrow"><span class="setlbl">Failover after (sec)</span><input id="mh-fail" type="number" class="setinput" min="6" max="120" value="'+(cfg.failover_after_sec||18)+'"></div>'
        +'<div class="setrow"><span class="setlbl">Auto takeover</span><label class="sw"><input type="checkbox" id="mh-auto" '+(cfg.auto_takeover!==false?'checked':'')+'><span></span></label></div>'
        +'<div class="jhead" style="margin-top:14px">Other brains on LAN</div>'
        +'<div id="mh-peers"></div>'
        +'<button class="cbtn" id="mh-add-peer">+ Add peer</button>'
        +'<div class="rrow" style="margin-top:14px">'
        +'<button class="cbtn pri" id="mh-save">Save</button>'
        +'<button class="cbtn" id="mh-take">Take over now</button>'
        +'<span id="mh-st" class="rnote"></span></div></div>';
      el.innerHTML=h;
      const rs=$('#mh-role'); if(rs)rs.value=cfg.role||'off';
      function renderPeers(){
        const box=$('#mh-peers'); if(!box)return;
        const peers=cfg.peers||[];
        if(!peers.length){box.innerHTML='<div class="rnote">No peers yet — add your 2nd/3rd brain URL.</div>';return;}
        let ph=''; peers.forEach((p,i)=>{
          ph+='<div class="rrow" style="margin-bottom:8px;flex-wrap:wrap">'
            +'<input class="setinput" data-pi="'+i+'" data-f="name" placeholder="name" value="'+esc(p.name||'')+'" style="min-width:100px">'
            +'<input class="setinput" data-pi="'+i+'" data-f="url" placeholder="https://…" value="'+esc(p.url||'')+'" style="flex:1;min-width:160px">'
            +'<select class="setinput" data-pi="'+i+'" data-f="role"><option value="primary">primary</option><option value="secondary">secondary</option><option value="tertiary">tertiary</option></select>'
            +'<button class="cbtn" data-prm="'+i+'">remove</button></div>';
        });
        box.innerHTML=ph;
        box.querySelectorAll('[data-prm]').forEach(b=>b.onclick=()=>{cfg.peers.splice(+b.dataset.prm,1);renderPeers();});
        box.querySelectorAll('select[data-f=role]').forEach(s=>{s.value=(peers[+s.dataset.pi]||{}).role||'secondary';});
      }
      renderPeers();
      const ap=$('#mh-add-peer'); if(ap)ap.onclick=()=>{(cfg.peers=cfg.peers||[]).push({name:'',url:'',role:'secondary'});renderPeers();};
      const save=$('#mh-save');
      if(save)save.onclick=()=>{
        const peers=[]; ($('#mh-peers')||{querySelectorAll:()=>[]}).querySelectorAll('.rrow').forEach(row=>{
          const name=(row.querySelector('[data-f=name]')||{}).value||'';
          const url=(row.querySelector('[data-f=url]')||{}).value||'';
          const role=(row.querySelector('[data-f=role]')||{}).value||'secondary';
          if(url.trim())peers.push({name:name.trim(),url:url.trim(),role:role});
        });
        const body={enabled:!!($('#mh-en')&&$('#mh-en').checked),role:($('#mh-role')||{}).value||'off',
          node_name:($('#mh-name')||{}).value||'',primary_url:($('#mh-primary')||{}).value||'',
          failover_after_sec:parseFloat(($('#mh-fail')||{}).value)||18,auto_takeover:!!($('#mh-auto')&&$('#mh-auto').checked),
          peers:peers};
        save.disabled=true;
        api('/v1/home/mesh/config',{method:'POST',body:JSON.stringify(body)}).then(r=>{
          save.disabled=false;
          const st=$('#mh-st'); if(st)st.textContent=r.ok?'saved':'failed: '+(r.error||'');
          if(r.ok)loadDevices();
        }).catch(e=>{save.disabled=false;const st=$('#mh-st');if(st)st.textContent=''+e;});
      };
      const tk=$('#mh-take');
      if(tk)tk.onclick=()=>api('/v1/home/mesh/takeover',{method:'POST',body:'{}'}).then(r=>{
        alert(r.ok?'This node is now acting brain':'Takeover failed: '+(r.error||''));
        loadDevices();
      }).catch(e=>alert(''+e));
    }).catch(e=>{el.innerHTML='<div class="err">'+esc(''+e)+'</div>';});
  }
  function homeStatusStrip(rooms, st){
    const devs=[];rooms.forEach(r=>(r.devices||[]).forEach(d=>devs.push(d)));
    const on=devs.filter(d=>(''+(d.state||'')).toUpperCase()==='ON').length;
    const off=devs.filter(d=>(''+(d.state||'')).toUpperCase()==='OFF').length;
    const idle=devs.length-on-off;
    const strip=document.createElement('div');strip.className='livestrip';
    const conn=st&&st.connected;
    strip.innerHTML='<span class="lstitle">&#9670; ELI HOME</span>'
      +'<span class="lspill" style="border-color:rgba(46,192,122,.35);background:rgba(46,192,122,.08)"><span class="ld live"></span>100% local</span>'
      +'<span class="lspill" id="ls-wifi"><span class="ld warn"></span>WiFi</span>'
      +'<span class="lspill" id="ls-bt"><span class="ld off"></span>BT</span>'
      +'<span class="lspill" id="ls-audio"><span class="ld warn"></span>audio</span>'
      +'<span class="lspill"><span class="ld '+(conn?'live':'warn')+'"></span>'+(conn?('MQTT '+esc(st.broker||'online')):'MQTT optional')+'</span>'
      +'<span class="lspill"><span class="ld live"></span><b>'+on+'</b> on</span>'
      +'<span class="lspill"><span class="ld off"></span><b>'+off+'</b> off</span>'
      +(idle?'<span class="lspill"><span class="ld warn"></span><b>'+idle+'</b> idle</span>':'')
      +'<span class="lspill"><b>'+devs.length+'</b> devices</span>'
      +'<span class="lspill" id="ls-mesh"><span class="ld warn"></span>mesh</span>'
      +'<span class="lspill" id="ls-autos"><b>&middot;</b> automations</span>';
    api('/v1/home/automations').then(d=>{const n=((d&&d.automations)||[]).length;const e=$('#ls-autos');if(e)e.innerHTML='<b>'+n+'</b> automations';}).catch(()=>{});
    api('/v1/home/mesh/status').then(d=>{
      const e=$('#ls-mesh'); if(!e||!d||!d.ok)return;
      const rt=d.runtime||{}, mode=rt.mode||'off';
      const live=mode==='cognition'||mode==='acting_secondary'||mode==='acting_tertiary';
      const lbl=mode==='cognition'?'primary':(mode==='acting_secondary'?'2nd brain':(mode==='acting_tertiary'?'3rd brain':(mode==='standby'?'standby':'mesh off')));
      e.innerHTML='<span class="ld '+(live?'live':(mode==='standby'?'warn':'off'))+'"></span>'+esc(lbl);
    }).catch(()=>{});
    refreshHomeConnectivity();
    return strip;
  }
  function paneQuickSetup(el, st){
    el.innerHTML='<div class="syscard" style="border-color:rgba(46,192,122,.25);background:rgba(46,192,122,.05);margin-bottom:14px;line-height:1.65">'
      +'<b>ELI is sovereign.</b> WiFi, Bluetooth, speakers, and smart devices are discovered and controlled on <b>your LAN</b> only — no cloud accounts, no telemetry. '
      +'Models, voice, and memory run on this machine.</div>'
      +'<div class="rrow" style="margin-bottom:16px"><button class="cbtn pri" onclick="homeQuickScan()">&#9889; Scan everything</button>'
      +'<span class="rnote">WiFi + Bluetooth + speakers + LAN devices in one go</span></div>'
      +'<div class="jhead">1 — WiFi</div>'
      +'<div class="syscard"><p id="home-wifi-pill" class="rnote" style="margin:0 0 10px" data-fallback="Join your WiFi so ELI can find lights, speakers, and brokers on your home network.">Checking…</p>'
      +'<div class="rrow"><button class="cbtn" onclick="wifiScan()">&#128246; Scan networks</button></div>'
      +'<div id="home-wifi-status" class="rnote" style="min-height:1.2em;margin-top:8px"></div>'
      +'<div id="home-wifi-list" style="margin-top:8px"></div></div>'
      +'<div class="jhead">2 — Headphones &amp; speakers (Bluetooth)</div>'
      +'<div class="syscard"><p class="rnote" style="margin:0 0 10px;line-height:1.6">'
      +'<b>One tap:</b> put headphones in pairing mode (LED flashing), tap <b>Search Bluetooth</b>, then <b>Connect for music</b>. '
      +'ELI pairs, connects, and switches sound — high-quality music mode, not phone/handsfree. '
      +'This hub shows as <b id="home-bt-alias">Eli · Home</b> on their screen.</p>'
      +'<div class="rrow"><button class="cbtn pri" id="home-bt-scan" onclick="searchBluetooth(\'#home-bt-box\',\'#home-bt-scan\')">&#127911; Search Bluetooth</button></div>'
      +'<div id="home-bt-box" style="margin-top:8px"></div></div>'
      +'<div class="jhead">3 — Where sound plays</div>'
      +'<div class="syscard"><p class="rnote" style="margin:0 0 10px">Pick the speaker or HDMI output for ELI and desktop media — switch anytime.</p>'
      +'<div class="rrow"><button class="cbtn" onclick="loadAudioOutputs()">&#128266; List speakers</button></div>'
      +'<div id="home-audio-status" class="rnote" style="min-height:1.2em;margin-top:8px"></div>'
      +'<div id="home-audio-list" style="margin-top:8px"></div></div>'
      +'<div class="jhead">4 — Devices on your LAN</div>'
      +'<div class="syscard"><p class="rnote" style="margin:0 0 10px">AirPlay, Chromecast, Fire TV, MQTT brokers — found via mDNS on your network, never via a cloud API.</p>'
      +'<div class="rrow"><button class="cbtn" id="home-net-scan" onclick="discoverDevices(\'#home-net-box\',\'#home-net-scan\')">&#128270; Find on my network</button></div>'
      +'<div id="home-net-box" style="margin-top:8px"></div></div>'
      +(st&&!st.connected?('<div class="jhead">5 — Lights &amp; switches (optional MQTT)</div>'
      +'<div class="syscard"><p class="rnote" style="margin:0 0 10px">MQTT is only needed for broker-backed hardware. Media and Bluetooth work without it.</p>'
      +'<button class="cbtn" onclick="_homeSub=\'mqtt\';loadDevices()">Open MQTT Setup &rarr;</button></div>'):'');
    refreshHomeConnectivity();
    loadAudioOutputs();
    searchBluetooth('#home-bt-box','#home-bt-scan');
  }
  function paneMediaOutput(el){
    el.innerHTML='<div class="jhead">Play on this machine</div>'
      +'<div class="syscard"><p class="rnote" style="margin:0 0 10px">Route system audio to built-in speakers, HDMI, or a paired Bluetooth device.</p>'
      +'<div class="rrow"><button class="cbtn pri" onclick="loadAudioOutputs()">&#128266; Choose speaker</button>'
      +'<button class="cbtn" onclick="searchBluetooth(\'#media-bt-box\',\'#media-bt-scan\')">&#127911; Bluetooth</button></div>'
      +'<div id="home-audio-status" class="rnote" style="min-height:1.2em;margin-top:8px"></div>'
      +'<div id="home-audio-list" style="margin-top:8px"></div>'
      +'<div id="media-bt-box" style="margin-top:10px"></div>'
      +'<button class="cbtn" id="media-bt-scan" style="display:none"></button></div>'
      +'<div class="jhead">Play on a network device</div>'
      +'<div class="syscard"><p class="rnote" style="margin:0 0 12px;line-height:1.65">Add AirPlay, Chromecast, Fire TV, or UPnP renderers from your LAN. Control them from <b>Devices</b> or say &ldquo;play on living room TV&rdquo; — all local drivers.</p>'
      +'<button class="cbtn" onclick="discoverDevices(\'#media-net-box\',\'#media-net-scan\')">&#128270; Find media players</button>'
      +'<div id="media-net-box" style="margin-top:10px"></div>'
      +'<button class="cbtn" id="media-net-scan" style="display:none"></button></div>'
      +'<div class="jhead">Now playing (this PC)</div>'
      +'<div class="syscard" id="media-now-local"><div class="rnote">Loading…</div></div>';
    loadAudioOutputs();
    api('/v1/media').then(d=>{
      const box=$('#media-now-local'); if(!box)return;
      const ps=(d&&d.players)||[];
      const renderNow=(sinks)=>{
        let audio='';
        if(sinks&&sinks.length){
          audio='<div class="npaudio" style="margin-top:12px"><label style="display:block;font-size:11px;color:var(--mut);margin-bottom:6px">SOUND OUTPUT</label><div class="nprow" style="display:flex;gap:6px">'
            +'<select id="media-local-out" style="flex:1;background:var(--input);color:var(--fg);border:1px solid var(--line);border-radius:8px;padding:6px 8px">'
            +sinks.map((s,i)=>'<option value="'+esc(s.id||s.name||'')+'"'+(s.is_default?' selected':'')+'>'+esc(s.name||s.id)+(s.is_default?' (current)':'')+'</option>').join('')
            +'</select><button class="cbtn pri" onclick="var _o=document.getElementById(\'media-local-out\');setAudioOutput(_o?_o.value:\'\')">Apply</button></div></div>';
        }
        if(!ps.length){box.innerHTML='<div class="muted">Nothing playing locally. Start Spotify, VLC, or a browser — or add a network player above.</div>'+audio;return;}
        const cur=ps.find(p=>p.is_active)||ps[0];
        box.innerHTML='<div class="nm">'+esc(cur.title||'(no title)')+'</div>'
          +'<div class="rnote">'+esc([cur.artist,cur.album].filter(Boolean).join(' — ')||cur.player||'')+'</div>'
          +'<div class="rrow" style="margin-top:10px">'
          +'<button class="cbtn" onclick="mediaCtl(\'play-pause\')">Play / pause</button>'
          +'<button class="cbtn" onclick="mediaCtl(\'next\')">Next</button></div>'+audio;
      };
      api('/v1/connectivity/audio/outputs').then(a=>renderNow((a&&a.ok&&a.sinks)||[])).catch(()=>renderNow([]));
    }).catch(()=>{});
  }
  function renderDevices(rooms, st){
    const h=$('#devices');h.innerHTML='';
    h.appendChild(homeStatusStrip(rooms, st));
    if(st&&!st.connected){
      const b=document.createElement('div');
      b.className='banner';
      b.style.cssText='margin:0 0 12px;line-height:1.65;border-color:rgba(255,209,102,.35);background:rgba(255,209,102,.08)';
      b.innerHTML='<b>MQTT optional.</b> WiFi, Bluetooth, and media players work without a broker. For MQTT lights/switches, open <b>MQTT Setup</b> or use the guided flow in <b>Quick setup</b>.';
      h.appendChild(b);
    }
    const sg=document.createElement('div');sg.id='home-sugg';h.appendChild(sg);loadHomeSuggestions();
    const shell=document.createElement('div');shell.className='subwrap';h.appendChild(shell);
    const initial=_homeSub||'setup';
    mountSubtabs(shell,[
      {id:'setup',label:'Quick setup',render:el=>paneQuickSetup(el,st)},
      {id:'media',label:'Media & output',render:paneMediaOutput},
      {id:'devices',label:'Devices',render:el=>paneDevices(el,rooms,st)},
      {id:'brains',label:'Brains',render:paneMeshBrains},
      {id:'mqtt',label:'MQTT Setup',render:el=>paneMqttSetup(el,st)},
      {id:'autos',label:'Automations',render:paneAutomations},
      {id:'scenes',label:'Scenes',render:paneScenes},
      {id:'discover',label:'LAN scan',render:paneDiscover},
      {id:'advanced',label:'Advanced',render:paneAdvanced},
    ],initial,(id)=>{_homeSub=id;});
  }
  function paneDevices(el, rooms, st){
    el.innerHTML='';
    const all=[];rooms.forEach(rm=>(rm.devices||[]).forEach(d=>all.push(d)));
    if(all.length){
      if(!_devHubId||!all.find(d=>d.id===_devHubId))_devHubId=all[0].id;
      const sel=all.find(d=>d.id===_devHubId)||all[0];
      const hub=document.createElement('div');hub.className='devhub';
      const pick=document.createElement('div');pick.className='devpick';
      all.forEach(dv=>{
        const ch=document.createElement('button');ch.type='button';ch.className='devchip'+(_devHubId===dv.id?' active':'');
        ch.textContent=dv.name||dv.id;
        ch.onclick=()=>{_devHubId=dv.id;paneDevices(el,rooms,st);};
        pick.appendChild(ch);
      });
      hub.appendChild(pick);
      const hd=document.createElement('div');hd.className='devhub-hd';
      hd.innerHTML='<span class="dicon">'+(DEV_ICON[sel.type]||'&#9670;')+'</span><div><div class="nm">'+esc(sel.name||sel.id)+'</div><div class="dom">'+esc(sel.room||'Unassigned')+'</div></div>';
      hub.appendChild(hd);
      const shell=document.createElement('div');shell.className='devhub-body subwrap';
      hub.appendChild(shell);
      mountSubtabs(shell,[
        {id:'connect',label:'Connect',render:el2=>paneDevConnect(el2,sel)},
        {id:'media',label:'Media',render:el2=>paneDevMedia(el2,sel)},
        {id:'controls',label:'Controls',render:el2=>paneDevControls(el2,sel)},
        {id:'info',label:'Info',render:el2=>paneDevInfo(el2,sel)},
      ],_devHubSub,id=>{_devHubSub=id;});
      el.appendChild(hub);
    }
    const total=all.length;
    if(!total){const m=document.createElement('div');m.className='muted';m.style.cssText='padding:22px 0;line-height:1.7';
      m.innerHTML=(st&&st.connected)
        ?'No devices yet. Use <b>Quick setup</b> or <b>LAN scan</b> to find players, or <b>MQTT Setup</b> for lights.'
        :'Use <b>Quick setup</b> to join WiFi and scan for Bluetooth &amp; media players — MQTT is optional for lights.';el.appendChild(m);}
    if(total){
      const jh=document.createElement('div');jh.className='jhead';jh.textContent='By room';el.appendChild(jh);
    }
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
    el.innerHTML='<div class="jhead">LAN device scan</div>'+
      '<div class="syscard"><p class="rnote" style="margin:0 0 10px;line-height:1.6">Find AirPlay, Fire TV, Chromecast, UPnP/DLNA, and MQTT brokers via mDNS on <b>your network</b> — no cloud lookup. For a guided flow use <b>Quick setup</b>.</p>'+
      '<button class="cbtn" id="mq-find" onclick="discoverDevices()">&#128270; Scan LAN</button><div id="mq-found"></div></div>';
  }
  function paneMqttSetup(el, st){
    st=st||{};
    el.innerHTML='<div class="jhead">MQTT broker — for lights, switches &amp; sensors</div>'+
      '<div class="syscard"><p class="rnote" style="margin:0 0 12px;line-height:1.65">Optional unless you use broker-backed hardware (ESPHome, Tasmota, Zigbee2MQTT). WiFi, Bluetooth, and media players work without MQTT. All broker traffic stays on your LAN.</p>'+
      '<div class="rrow" style="gap:8px;flex-wrap:wrap;margin-bottom:10px">'+
      '<button class="cbtn" onclick="discoverBrokersOnly()">&#128270; Scan network for brokers</button>'+
      '<button class="cbtn" onclick="loadMqttGuide()">&#128214; Show setup guide for my OS</button>'+
      '</div>'+
      '<div id="mqtt-guide" class="rnote" style="display:none;margin-bottom:12px;line-height:1.65"></div>'+
      '<div id="mqtt-scan"></div></div>'+
      '<div id="broker-cfg-mqtt"></div>';
    renderBrokerCfg($('#broker-cfg-mqtt'), {}, '');
    if(!st.connected){setTimeout(discoverBrokersOnly, 400);}
  }
  function loadMqttGuide(){
    const box=$('#mqtt-guide'); if(!box)return;
    box.style.display='block'; box.textContent='Loading guide…';
    api('/v1/devices/mqtt/guide').then(g=>{
      if(!g.ok){box.innerHTML='<span style="color:#f87171">Could not load guide</span>';return;}
      let h='<b>'+esc(g.title||'MQTT setup')+'</b><ol style="margin:8px 0 0 18px">';
      (g.steps||[]).forEach(s=>{h+='<li>'+esc(s)+'</li>';});
      h+='</ol>';
      if(g.notes) h+='<div style="margin-top:8px;opacity:.85">'+esc(g.notes)+'</div>';
      if((g.suggested_hosts||[]).length){
        h+='<div style="margin-top:10px">Quick try: ';
        g.suggested_hosts.slice(0,4).forEach(hst=>{
          h+='<button class="cbtn" style="padding:2px 8px;margin:2px" onclick="quickBrokerHost(\''+esc(hst)+'\')">'+esc(hst)+'</button> ';
        });
        h+='</div>';
      }
      box.innerHTML=h;
    }).catch(e=>{box.innerHTML='<span style="color:#f87171">'+esc(''+e)+'</span>';});
  }
  function quickBrokerHost(host){
    const h=$('#mq_host'),p=$('#mq_port'); if(h)h.value=host; if(p&&!p.value)p.value='1883';
    const n=$('#mqtt-scan'); if(n)n.innerHTML='<div class="rnote">Host set to '+esc(host)+' — click <b>Test connection</b> or <b>Save &amp; connect</b>.</div>';
  }
  function discoverBrokersOnly(){
    const box=$('#mqtt-scan'); if(!box)return;
    box.innerHTML='<div class="rnote">Scanning for MQTT brokers on your LAN…</div>';
    api('/v1/devices/discover',{method:'POST',body:JSON.stringify({})}).then(d=>{
      if(!d.ok){box.innerHTML='<div class="banner bad">'+esc(d.error||'scan failed')+'</div>';return;}
      const br=d.brokers||[];
      if(!br.length){
        box.innerHTML='<div class="rnote">No MQTT broker found on the network yet. Use the setup guide above to install Mosquitto (or point ELI at your Home Assistant / Pi IP).</div>';
        return;
      }
      let h='<div class="rnote">Brokers found — click one to fill the form:</div>';
      br.forEach(b=>{
        h+='<div class="src" style="cursor:pointer" onclick="useBroker(\''+esc(b.host)+'\','+(b.port||1883)+')"><div class="sh"><span>&#128268; '+esc(b.name||b.host)+'</span><span>'+esc(b.host)+':'+(b.port||1883)+'</span></div></div>';
      });
      box.innerHTML=h;
    }).catch(e=>{box.innerHTML='<div class="banner bad">'+esc(''+e)+'</div>';});
  }
  function testMqttConnection(){
    const body={host:($('#mq_host').value||'').trim(), port:parseInt($('#mq_port').value||'1883',10)||1883,
      username:($('#mq_user').value||'').trim(), password:($('#mq_pass').value||''),
      discovery_prefix:($('#mq_disc').value||'').trim(), tls:!!($('#mq_tls')&&$('#mq_tls').checked)};
    const stt=$('#mqtt-test-status'); if(stt)stt.textContent='Testing…';
    if(!body.host){if(stt)stt.innerHTML='<span style="color:#f87171">Enter a broker host first.</span>';return;}
    api('/v1/devices/mqtt/test',{method:'POST',body:JSON.stringify(body)}).then(r=>{
      if(stt){
        if(r.ok) stt.innerHTML='<span style="color:#2ec07a">&#10003; '+esc(r.message||'Connected')+'</span>';
        else stt.innerHTML='<span style="color:#f87171">'+esc(r.error||'failed')+'</span>'+(r.hint?('<div class="rnote" style="margin-top:6px">'+esc(r.hint)+'</div>'):'');
      }
    }).catch(e=>{if(stt)stt.innerHTML='<span style="color:#f87171">'+esc(''+e)+'</span>';});
  }
  function applyDiscoveryPreset(val){
    const d=$('#mq_disc'); if(d) d.value=val||'';
  }
  function paneAdvanced(el){
    el.innerHTML='<div class="jhead">Location — for sun-based automations</div>'+
      '<div class="syscard"><div class="rrow"><input id="loc-lat" placeholder="latitude" style="max-width:140px"><input id="loc-lon" placeholder="longitude" style="max-width:140px">'+
      '<button class="cbtn" onclick="useMyLocation()">&#128205; Use my location</button><button onclick="saveLocation()">Save</button></div><div id="loc-status" class="rnote"></div></div>'+
      '<div class="jhead">Broker / connection</div>'+
      '<div class="syscard"><p class="rnote" style="margin:0 0 12px;line-height:1.65">Same MQTT settings as the <b>MQTT Setup</b> tab. If status shows <code>not connected</code>, the broker is not running, the host/IP is wrong, or a firewall is blocking port 1883.</p></div>'+
      '<div id="broker-cfg2"></div>';
    renderBrokerCfg($('#broker-cfg2'));
  }
  function renderBrokerCfg(box, vals, err){
    if(!box)return; vals=vals||{};
    Promise.all([api('/v1/devices/status'), api('/v1/devices/mqtt/guide')]).then(function(res){
      const st=(res[0]&&res[0].status)||{};
      const guide=res[1]||{};
      const presets=(guide.discovery_presets||[]);
      let presetOpts='';
      presets.forEach(p=>{presetOpts+='<option value="'+esc(p.id||'')+'">'+esc(p.label||p.id||'manual')+'</option>';});
      box.innerHTML='<div class="syscard">'+
        (st.configured?('<div class="rnote" style="margin-bottom:10px">'+(st.connected?'<span style="color:#2ec07a">&#9679; connected to '+esc(st.broker||'')+'</span>':'<span style="color:#e0a72e">&#9675; configured ('+esc(st.broker||'')+') — not connected</span>')+(st.error?('<div style="color:#f87171;margin-top:6px">'+esc(st.error)+'</div>'):'')+'</div>'):'<div class="rnote" style="margin-bottom:10px;color:#e0a72e">&#9888; No broker configured yet — ELI cannot control MQTT lights/switches until you connect one.</div>')+
        (err?'<div class="banner bad" style="margin:0 0 12px">'+esc(err)+'</div>':'')+
        '<label>Broker host <span class="rnote">(IP or hostname on your LAN)</span></label><input id="mq_host" autocomplete="off" placeholder="127.0.0.1 · 192.168.1.50 · mosquitto.local" value="'+esc(vals.host||st.brokerHost||'')+'">'+
        '<label>Port <span class="rnote">(default 1883)</span></label><input id="mq_port" value="'+esc(vals.port||st.brokerPort||'1883')+'">'+
        '<label>Username <span class="rnote">(leave blank if your broker has no login)</span></label><input id="mq_user" autocomplete="off" value="'+esc(vals.username||st.username||'')+'">'+
        '<label>Password</label><input id="mq_pass" type="password" autocomplete="new-password" value="'+esc(vals.password||'')+'">'+
        '<label>Device discovery preset</label><select id="mq_preset" onchange="applyDiscoveryPreset(this.value)">'+presetOpts+'</select>'+
        '<label>Discovery prefix <span class="rnote">(advanced — auto-finds MQTT devices)</span></label><input id="mq_disc" placeholder="homeassistant" value="'+esc(vals.discovery_prefix||st.discovery_prefix||'')+'">'+
        '<label class="rrow" style="gap:8px;align-items:center"><input type="checkbox" id="mq_tls" '+(st.tls?'checked':'')+'> Use TLS (port 8883)</label>'+
        '<div id="mqtt-test-status" class="rnote" style="min-height:1.2em;margin-top:8px"></div>'+
        '<div class="rrow" style="margin-top:14px;flex-wrap:wrap;gap:8px">'+
        '<button class="cbtn" onclick="testMqttConnection()">Test connection</button>'+
        '<button id="mq-save" onclick="saveDevConfig()">Save &amp; connect</button>'+
        (st.connected?'<button class="cbtn" onclick="api(\'/v1/devices/disconnect\',{method:\'POST\'}).then(loadDevices)">Disconnect</button>':'')+
        '</div></div>';
      const presetSel=$('#mq_preset'), disc=$('#mq_disc');
      if(presetSel&&disc){
        const cur=disc.value||'';
        for(let i=0;i<presetSel.options.length;i++){if(presetSel.options[i].value===cur){presetSel.selectedIndex=i;break;}}
      }
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
    else h+='<div class="muted">No outbound connections recorded — ELI is offline or hasn\'t reached out.</div>';
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
      '<div class="rnote">Documents must live under the server\'s research root (default <code>artifacts/research/_sources/</code>, or set <code>ELI_RESEARCH_ROOT</code>). Paths outside it are rejected.</div><div id="ing-status" class="rnote"></div></div>'+
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
  // ── Overview: customizable widget dashboard ───────────────────────────────
  let OV_LAYOUT=null, OV_EDIT=false, OV_PREFS_LOADED=false, OV_DRAG=null;
  // Full catalog (palette order). Each user composes their own subset — the layout
  // decides which endpoints get fetched, so unused widgets cost nothing.
  const OV_CATALOG=['ask','mesh','goals','tasks','nowplaying','devicenames','graph','model','gpu','vitals','internet','egress','connect','quickcontrols','rooms','scenes','automations','suggestions','quickactions','corpora','capabilities','sun','note','activity','audit'];
  const OV_DEFAULT=['ask','mesh','tasks','goals','graph','nowplaying','devicenames','quickcontrols'];
  const OV_TITLES={ask:'Ask ELI',mesh:'Cognition mesh',goals:'Autonomy & goals',tasks:'Scheduled tasks',nowplaying:'Now playing',devicenames:'Device names',graph:'Live vitals',model:'Model & runtime',gpu:'GPU',vitals:'Vitals',internet:'Internet access',egress:'Network egress',connect:'Connect a phone',quickcontrols:'Quick controls',rooms:'Rooms',scenes:'Scenes',automations:'Automations',suggestions:'Suggestions',quickactions:'Quick actions',corpora:'Research corpora',capabilities:'Capabilities',sun:'Sun',note:'Note',activity:'Recent activity',audit:'Audit integrity'};
  const OV_WIDE={mesh:1,activity:1,capabilities:1};
  const OV_SRC={system:'/v1/system',audit:'/v1/audit?limit=8',devices:'/v1/devices',corpora:'/v1/research/corpora',net:'/v1/net',media:'/v1/media',audio:'/v1/connectivity/audio/outputs?refresh=1',devnames:'/v1/devices/names',automations:'/v1/home/automations',scenes:'/v1/home/scenes',suggestions:'/v1/home/suggestions',sun:'/v1/home/sun',capabilities:'/v1/capabilities',connect:'/v1/connect',rooms:'/v1/devices/rooms',orchestration:'/v1/cognition/orchestration',goals:'/v1/autonomy/goals',tasks:'/v1/tasks'};
  const OV_NEEDS={ask:[],mesh:['orchestration'],goals:['goals'],tasks:['tasks'],nowplaying:['media','audio'],devicenames:['devnames'],graph:['system'],model:['system'],gpu:['system'],vitals:['system'],internet:['net'],egress:['net'],connect:['connect'],quickcontrols:['devices'],rooms:['rooms'],scenes:['scenes'],automations:['automations','devices'],suggestions:['suggestions'],quickactions:[],corpora:['corpora'],capabilities:['capabilities'],sun:['sun'],note:[],activity:['audit'],audit:['audit']};
  const OV_BASE=['system','audit','devices','corpora','net'];   // the hero always needs these
  function ovLayout(){
    if(!OV_LAYOUT||!Array.isArray(OV_LAYOUT.order))OV_LAYOUT={order:OV_DEFAULT.slice(),hidden:[],note:''};
    if(!Array.isArray(OV_LAYOUT.hidden))OV_LAYOUT.hidden=[];
    OV_LAYOUT.order=OV_LAYOUT.order.filter(id=>OV_CATALOG.indexOf(id)>=0);   // drop unknown ids
    return OV_LAYOUT;
  }
  function ovVisible(){const l=ovLayout();return l.order.filter(id=>l.hidden.indexOf(id)<0);}
  function ovSaveLayout(){try{localStorage.setItem('eli_ov_layout',JSON.stringify(OV_LAYOUT));}catch(_e){}
    api('/v1/ui/prefs',{method:'POST',body:JSON.stringify({prefs:{overview:OV_LAYOUT}})}).catch(()=>{});}
  function ovLoadPrefs(){
    try{const ls=localStorage.getItem('eli_ov_layout');if(ls)OV_LAYOUT=JSON.parse(ls);}catch(_e){}
    return api('/v1/ui/prefs').then(d=>{if(d&&d.ok&&d.prefs&&d.prefs.overview)OV_LAYOUT=d.prefs.overview;}).catch(()=>{});
  }
  function loadOverview(){
    const run=()=>{
      try{const sel=document.querySelector('.npaudio select');if(sel)window._ovAudioSink=sel.value;}catch(_e){}
      const need={}; OV_BASE.forEach(s=>need[s]=1);
      ovVisible().forEach(id=>(OV_NEEDS[id]||[]).forEach(s=>need[s]=1));
      const keys=Object.keys(need);
      return Promise.all(keys.map(k=>api(OV_SRC[k]).catch(()=>({}))))
        .then(results=>{const D={};keys.forEach((k,i)=>D[k]=results[i]);renderOverview(D);})
        .catch(e=>{$('#overview').innerHTML='<div class="err">'+esc(''+e)+'</div>';});
    };
    if(!OV_PREFS_LOADED){OV_PREFS_LOADED=true;return ovLoadPrefs().then(run);}
    return run();
  }
  function setNet(on){
    const reason = on ? (prompt('Enable internet access for ELI?\nOptionally note why (logged to the audit trail):','')||'') : '';
    if(on && reason===null) return;
    api('/v1/net',{method:'POST',body:JSON.stringify({enabled:!!on,reason:reason})})
      .then(d=>{ if(!d||!d.ok){alert('Could not change internet access: '+esc((d&&d.error)||'unknown'));} loadOverview(); })
      .catch(e=>{alert('Could not change internet access: '+esc(''+e)); loadOverview();});
  }
  window.setNet=setNet;
  function ovCtl(id,cmd){api('/v1/devices/control',{method:'POST',body:JSON.stringify({device_id:id,command:cmd})}).then(()=>setTimeout(loadOverview,400)).catch(()=>{});}
  function ovScene(id){api('/v1/home/scenes/activate',{method:'POST',body:JSON.stringify({scene:id})}).then(()=>setTimeout(loadOverview,400)).catch(()=>{});}
  function ovRoom(room,cmd){api('/v1/devices/room/control',{method:'POST',body:JSON.stringify({room:room,command:cmd})}).then(()=>setTimeout(loadOverview,500)).catch(()=>{});}
  function ovNote(t){const l=ovLayout();l.note=t.value;clearTimeout(window._ovNoteT);window._ovNoteT=setTimeout(ovSaveLayout,600);}
  window.ovCtl=ovCtl; window.ovScene=ovScene; window.ovRoom=ovRoom; window.ovNote=ovNote;
  function mediaCtl(cmd){const p=window._ovPlayer||null;
    api('/v1/media/control',{method:'POST',body:JSON.stringify({command:cmd,player:p})}).then(()=>setTimeout(loadOverview,350)).catch(()=>{});}
  function mediaPick(sel){window._ovPlayer=sel.value;loadOverview();}
  function ovSetAudioAlias(sink,name){
    api('/v1/connectivity/audio/alias',{method:'POST',body:JSON.stringify({sink:sink,name:name||''})})
      .then(()=>setTimeout(loadOverview,200)).catch(()=>{});
  }
  function ovSaveDeviceName(key,inputId,btn){
    const inp=document.getElementById(inputId);
    const name=(inp&&inp.value||'').trim();
    if(!key){alert('Missing device key');return;}
    if(btn){btn.disabled=true;btn.textContent='Saving…';}
    api('/v1/devices/name',{method:'POST',body:JSON.stringify({key:key,name:name})})
      .then(r=>{
        if(r&&r.ok){
          if(btn){btn.textContent='✓ Saved';btn.disabled=false;setTimeout(()=>{btn.textContent='Save';},2200);}
          setTimeout(loadOverview,350);
        }else{
          alert('Could not save name: '+esc((r&&r.error)||'unknown'));
          if(btn){btn.textContent='Save';btn.disabled=false;}
        }
      }).catch(e=>{alert('Could not save name: '+esc(''+e));if(btn){btn.textContent='Save';btn.disabled=false;}});
  }
  function ovSetAudioOutput(sel){
    const sink=(sel&&sel.value)||'';
    if(!sink)return;
    api('/v1/connectivity/audio/default',{method:'POST',body:JSON.stringify({sink:sink})})
      .then(r=>{if(r&&r.ok)setTimeout(loadOverview,300);})
      .catch(()=>{});
  }
  window.mediaCtl=mediaCtl; window.mediaPick=mediaPick; window.ovSetAudioOutput=ovSetAudioOutput; window.ovSetAudioAlias=ovSetAudioAlias; window.ovSaveDeviceName=ovSaveDeviceName;
  // Ask ELI — talk to the full engine straight from the dashboard. Last Q/A is kept in
  // window._ovAsk so the 6s auto-refresh re-renders the answer instead of wiping it.
  function ovAsk(preset){
    const inp=$('#ask-in'),out=$('#ask-out');
    const q=(preset!=null?preset:((inp&&inp.value)||'')).trim();
    if(!q)return;
    if(inp&&preset==null)inp.value='';
    window._ovAsk={q:q,a:''};
    if(out){out.classList.remove('muted');out.textContent='…';}
    api('/v1/chat',{method:'POST',body:JSON.stringify({message:q})}).then(r=>{
      const a=(r&&r.response)||'(no reply)'; window._ovAsk={q:q,a:a};
      const o=$('#ask-out'); if(o){o.classList.remove('muted');o.textContent=a;}
    }).catch(e=>{const o=$('#ask-out'); if(o)o.textContent='Error: '+esc(''+e);});
  }
  function ovGlance(){ovAsk('what is currently on my screen?');}
  window.ovAsk=ovAsk; window.ovGlance=ovGlance;
  // Add / manage device automations from the dashboard.
  function ovAutoAdd(){const dev=(($('#au-dev')||{}).value||''),cmd=(($('#au-cmd')||{}).value||'on'),time=(($('#au-time')||{}).value||'');
    if(!dev||!time){return;}
    api('/v1/home/automations/add',{method:'POST',body:JSON.stringify({device:dev,command:cmd,time:time})}).then(()=>setTimeout(loadOverview,300)).catch(()=>{});}
  function ovAutoRemove(id){api('/v1/home/automations/remove',{method:'POST',body:JSON.stringify({id:id})}).then(()=>setTimeout(loadOverview,200)).catch(()=>{});}
  function ovAutoToggle(id,en){api('/v1/home/automations/toggle',{method:'POST',body:JSON.stringify({id:id,enabled:!!en})}).catch(()=>{});}
  window.ovAutoAdd=ovAutoAdd; window.ovAutoRemove=ovAutoRemove; window.ovAutoToggle=ovAutoToggle;
  // Queue / cancel ELI's scheduled (overnight) tasks straight from the dashboard.
  function ovTaskAdd(){const r=((($('#tk-req')||{}).value)||'').trim(); if(!r)return;
    const when=(($('#tk-when')||{}).value)||'overnight', kind=(($('#tk-kind')||{}).value)||'';
    api('/v1/tasks',{method:'POST',body:JSON.stringify({request:r,when:when,kind:kind})}).then(()=>setTimeout(loadOverview,300)).catch(()=>{});}
  function ovTaskRemove(pid){api('/v1/tasks/remove',{method:'POST',body:JSON.stringify({pid:pid})}).then(()=>setTimeout(loadOverview,200)).catch(()=>{});}
  window.ovTaskAdd=ovTaskAdd; window.ovTaskRemove=ovTaskRemove;
  // Live vitals sparklines — rolling history drawn on <canvas>.
  function ovDrawGraphs(){const H=window._ovHist||{};
    document.querySelectorAll('.gph canvas').forEach(cv=>{
      const k=cv.getAttribute('data-k'),data=H[k]||[];
      const c=cv.getContext&&cv.getContext('2d'); if(!c)return;
      const w=cv.width,h=cv.height; c.clearRect(0,0,w,h);
      if(data.length<2)return;
      const grd=c.createLinearGradient(0,0,w,0); grd.addColorStop(0,'#22d3ee'); grd.addColorStop(1,'#f637ec');
      c.lineWidth=2; c.strokeStyle=grd; c.beginPath();
      data.forEach((v,i)=>{const x=i/(data.length-1)*w,y=h-(Math.max(0,Math.min(100,v))/100)*(h-5)-2; i?c.lineTo(x,y):c.moveTo(x,y);});
      c.stroke(); c.lineTo(w,h); c.lineTo(0,h); c.closePath(); c.fillStyle='rgba(34,211,238,.09)'; c.fill();
    });}
  window.ovDrawGraphs=ovDrawGraphs;
  function isOvEditingField(){const ae=document.activeElement;return !!(ae&&/^(INPUT|SELECT|TEXTAREA)$/.test(ae.tagName||''));}
  function ovBar(used,total){const p=total?Math.max(0,Math.min(100,Math.round(used/total*100))):0;return '<div class="ovbar"><i style="width:'+p+'%"></i></div>';}
  function kv(k,v){return '<div class="ovkv"><span class="k">'+k+'</span><span class="v">'+v+'</span></div>';}
  // Widget body builders — each returns inner HTML (without the header). D = fetched data.
  function ovWidget(id,D){
    const sys=(D.system&&D.system.status)||{};
    if(id==='ask'){
      const last=window._ovAsk||{};
      return '<div class="askwrap"><div id="ask-out" class="askout'+(last.a?'':' muted')+'">'+(last.a?esc(last.a):'Ask ELI anything — it routes through the full local engine (chat, actions, vision).')+'</div>'+
        '<div class="askrow"><input id="ask-in" placeholder="Ask ELI…" onkeydown="if(event.key===\'Enter\')ovAsk()">'+
        '<button class="qchip" onclick="ovAsk()">Send</button>'+
        '<button class="qchip" onclick="ovGlance()" title="What is on my screen? (local vision)">&#128065;</button></div></div>';
    }
    if(id==='graph'){
      const g=sys.gpu,c=sys.cpu,r=sys.ram;
      const H=window._ovHist||(window._ovHist={gpu:[],cpu:[],ram:[]});
      if(g)H.gpu.push(g.util_pct||0); if(c)H.cpu.push(c.usage_pct||0); if(r)H.ram.push(r.pct!=null?r.pct:(r.total_mb?Math.round(r.used_mb/r.total_mb*100):0));
      ['gpu','cpu','ram'].forEach(k=>{if(H[k].length>48)H[k]=H[k].slice(-48);});
      setTimeout(ovDrawGraphs,0);
      const cur=k=>{const a=H[k];return a&&a.length?a[a.length-1]:0;};
      return '<div class="gph">'+
        '<div class="gphrow"><span>GPU '+cur('gpu')+'%</span><canvas data-k="gpu" width="240" height="34"></canvas></div>'+
        '<div class="gphrow"><span>CPU '+cur('cpu')+'%</span><canvas data-k="cpu" width="240" height="34"></canvas></div>'+
        '<div class="gphrow"><span>RAM '+cur('ram')+'%</span><canvas data-k="ram" width="240" height="34"></canvas></div></div>';
    }
    if(id==='mesh'){
      const o=D.orchestration||{}, layers=o.execution_layers||[], agents=o.agents||[];
      if(!agents.length)return '<div class="muted">'+esc(o.error||'Orchestration unavailable.')+'</div>';
      let h='<div class="ovkv"><span class="k">Engine</span><span class="v">'+esc(o.engine||'—')+'</span></div>'+
        '<div class="ovkv"><span class="k">Agents</span><span class="v">'+(o.count||agents.length)+' on the bus</span></div>'+
        '<div class="ovkv"><span class="k">Parallel layers</span><span class="v">'+(o.critical_path||layers.length)+'</span></div>';
      if(layers.length){
        h+='<div class="mesh">';
        layers.forEach((L,i)=>{h+='<div class="meshcol"><div class="meshl">L'+(i+1)+'</div>'+
          (L||[]).map(a=>'<span class="meshnode">'+esc(a)+'</span>').join('')+'</div>'+
          (i<layers.length-1?'<div class="masharrow">&#8594;</div>':'');});
        h+='</div>';
      }
      return h;
    }
    if(id==='goals'){
      const g=D.goals||{};
      const list=(g.goals&&g.goals.length)?g.goals:((g.titles||[]).map(t=>({title:t})));
      let h='<div class="ovkv"><span class="k">Active goals</span><span class="v">'+(g.active||list.length||0)+' / '+(g.total||list.length||0)+'</span></div>';
      if(!list.length)h+='<div class="muted" style="margin-top:6px">No active goals yet — ELI generates its own as it runs (autonomy tick).</div>';
      list.slice(0,8).forEach(x=>{h+='<div class="ovact"><span class="aa">&#9883; '+esc((x.title||'goal').slice(0,72))+'</span>'+(x.kind?('<span class="at">'+esc(x.kind)+'</span>'):'')+'</div>';});
      return h;
    }
    if(id==='tasks'){
      const t=(D.tasks&&D.tasks.tasks)||[];
      const badge={code:'#22d3ee',research:'#a78bfa',eval:'#2ec07a',testgen:'#e0a72e',self_upgrade:'#ff6b8a',reflection:'#6aa3e0',lora:'#f637ec'};
      let h='';
      if(!t.length)h+='<div class="muted" style="margin-bottom:8px">No scheduled tasks. Queue one below — e.g. &ldquo;review the codebase for bugs&rdquo; overnight.</div>';
      t.slice(0,6).forEach(x=>{const col=badge[x.kind]||'#7a8699',when=x.when_ts?fmtTime(x.when_ts):esc(x.when_spec||'');
        h+='<div class="ovact"><span class="aa"><span class="kindbadge" style="background:'+col+'22;color:'+col+';border-color:'+col+'66">'+esc(x.kind||'task')+'</span>'+esc((x.request||'').slice(0,56))+'</span>'+
          '<span style="display:flex;gap:6px;align-items:center"><span class="at">'+when+(x.recurring?' &#8635;':'')+'</span><button class="wbtn rm" onclick="ovTaskRemove(\''+esc(x.pid)+'\')" title="Cancel">&#10005;</button></span></div>';});
      h+='<div class="ovform">'+
        '<input id="tk-req" placeholder="Tell ELI to do something…" style="flex:1;min-width:150px">'+
        '<select id="tk-when"><option value="overnight">Overnight</option><option value="tonight">Tonight</option><option value="in 1 hour">In 1 hour</option><option value="in 10 minutes">In 10 min</option></select>'+
        '<select id="tk-kind"><option value="">Auto</option><option value="code">Code</option><option value="research">Research</option><option value="eval">Eval</option><option value="reflection">Reflect</option></select>'+
        '<button class="qchip" onclick="ovTaskAdd()">+ Schedule</button></div>';
      return h;
    }
    if(id==='nowplaying'){
      const md=D.media, ps=(md&&md.players)||[];
      const sinks=((D.audio&&D.audio.ok)&&D.audio.sinks)||[];
      let audioSel='';
      if(sinks.length){
        const opts=sinks.map(s=>{
          const id=esc(s.id||s.name||'');
          const nm=esc(s.display_name||s.name||s.id||'output');
          const dev=s.device_number?(' · Device '+s.device_number):'';
          const tag=s.is_default?' (current)':'';
          const picked=window._ovAudioSink||'';
          const selOn=picked?(picked===id):(!!s.is_default);
          return '<option value="'+id+'"'+(selOn?' selected':'')+'>'+nm+dev+tag+'</option>';
        }).join('');
        const rename=sinks.map((s,i)=>'<div class="npaudio-row" style="margin-top:6px;display:flex;gap:6px;flex-wrap:wrap;align-items:center">'
          +'<span style="opacity:.7;font-size:.85em;min-width:5em">Device '+(s.device_number||'?')+'</span>'
          +'<span style="opacity:.55;font-size:.8em;max-width:100px;overflow:hidden;text-overflow:ellipsis" title="'+esc(s.os_name||s.name||'')+'">'+esc(s.os_name||s.name||'')+'</span>'
          +'<input class="inp" id="ov-sink-'+i+'" style="flex:1;min-width:120px" placeholder="Name for voice control" value="'+esc(s.custom_name||s.alias||'')+'">'
          +'<button class="cbtn pri" onclick="ovSaveDeviceName('+JSON.stringify(s.name_key||'')+','+JSON.stringify('ov-sink-'+i)+',this)">Save</button></div>').join('');
        audioSel='<div class="npaudio"><label>Sound output</label><div class="nprow">'
          +'<select onchange="ovSetAudioOutput(this)">'+opts+'</select>'
          +'<button class="cbtn pri" onclick="ovSetAudioOutput(this.previousElementSibling)">Apply</button></div>'
          +'<div class="rnote" style="margin-top:6px">Name speakers for voice — click <b>Save</b>: <i>play music to kitchen speaker</i></div>'
          +rename+'</div>';
      }
      if(!ps.length)return '<div class="muted">Nothing playing. Start Spotify, VLC or a browser video and it&#39;ll appear here with live controls.</div>'+audioSel;
      const cur=ps.find(p=>p.player===window._ovPlayer)||ps.find(p=>p.is_active)||ps[0];
      const playing=(cur.status==='playing');
      const ic={spotify:'&#127925;',vlc:'&#127916;',mpv:'&#127916;',firefox:'&#127760;',chromium:'&#127760;',chrome:'&#127760;'};
      const key=Object.keys(ic).find(k=>(''+(cur.player||'')).toLowerCase().startsWith(k));
      const icon=ic[key]||'&#9835;';
      const sub=esc([cur.artist,cur.album].filter(Boolean).join(' — ')||cur.status||'');
      let h='<div class="nowp"><div class="npart">'+icon+'</div><div class="npmeta">'+
        '<div class="nptitle">'+(cur.title?esc(cur.title):'(no title)')+'</div>'+
        '<div class="npsub">'+sub+'</div>'+
        '<div class="npplayer">'+esc(cur.player||'')+(playing?' &middot; playing':(cur.status?(' &middot; '+esc(cur.status)):''))+'</div>'+
        '</div></div>';
      h+='<div class="nptrans">'+
        '<button onclick="mediaCtl(\'previous\')" title="Previous">&#9198;</button>'+
        '<button class="big" onclick="mediaCtl(\'play-pause\')" title="Play / pause">'+(playing?'&#9208;':'&#9654;')+'</button>'+
        '<button onclick="mediaCtl(\'next\')" title="Next">&#9197;</button>'+
        '<button onclick="mediaCtl(\'stop\')" title="Stop">&#9209;</button>'+
        '</div>';
      if(ps.length>1)h+='<div class="npsel"><select onchange="mediaPick(this)">'+ps.map(p=>'<option value="'+esc(p.player)+'"'+(p.player===cur.player?' selected':'')+'>'+esc(p.player)+(p.title?(' — '+esc(p.title)):'')+'</option>').join('')+'</select></div>';
      return h+audioSel;
    }
    if(id==='devicenames'){
      const rows=(D.devnames&&D.devnames.devices)||[];
      if(!rows.length)return '<div class="muted">No devices yet — pair Bluetooth, add Home devices, or connect speakers, then name them here.</div>';
      let h='<div class="rnote" style="margin-bottom:8px">ELI matches these names in voice commands — e.g. <i>connect reflex</i>, <i>turn on bedroom light</i>. Names are saved until you clear them.</div>';
      rows.forEach((r,i)=>{
        const kid='dn-'+i, key=r.key||'';
        const kind=esc((r.kind||'device').slice(0,12));
        const os=esc(r.os_name||'');
        const saved=esc(r.saved_name||r.custom_name||'');
        h+='<div class="npaudio-row" style="margin-top:6px;display:flex;gap:6px;flex-wrap:wrap;align-items:center">'
          +'<span style="opacity:.7;font-size:.8em;min-width:4.5em">'+kind+'</span>'
          +'<span style="opacity:.5;font-size:.78em;max-width:110px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="'+os+'">'+os+'</span>'
          +'<input class="inp" id="'+kid+'" style="flex:1;min-width:130px" placeholder="Your name (voice keyword)" value="'+saved+'">'
          +'<button class="cbtn pri" onclick="ovSaveDeviceName('+JSON.stringify(key)+','+JSON.stringify(kid)+',this)">Save</button>'
          +(saved?('<button class="cbtn" onclick="document.getElementById(\''+kid+'\').value=\'\';ovSaveDeviceName('+JSON.stringify(key)+','+JSON.stringify(kid)+',this)" title="Remove custom name">Clear</button>'):'')
          +'</div>';
      });
      return h;
    }
    if(id==='internet'){
      const net=(D.net&&D.net.net)||{}, netOn=!!net.enabled, isAdmin=(window.MY_ROLE==='admin'||!window.MY_ROLE);
      return '<div class="netrow"><span class="netstate '+(netOn?'on':'off')+'">'+(netOn?'ENABLED':'OFF')+'</span>'+
        '<button class="netbtn '+(netOn?'on':'off')+'" '+(isAdmin?'':'disabled title="Admin only"')+' onclick="setNet('+(netOn?'false':'true')+')">'+(netOn?'Turn off':'Turn on')+'</button></div>'+
        (netOn&&(net.egress_recent||[]).length?('<div class="netegress">Recent outbound: '+(net.egress_recent||[]).slice(-5).map(e=>esc(e.host+(e.port?(':'+e.port):''))).join(' &middot; ')+'</div>'):'')+
        '<div class="muted" style="margin-top:6px">ELI is offline-by-default and hard-gated at the socket boundary. Turning this on lets ELI reach the internet — and every outbound connection (host:port) is recorded to the tamper-evident audit trail, as is the on/off flip itself.</div>';
    }
    if(id==='vitals'){
      const g=sys.gpu,c=sys.cpu,r=sys.ram;
      let v='<div class="ovgauges">';
      if(g){v+=ovGauge(g.util_pct,'GPU')+ovGauge(g.temp_c,'GPU °C');}
      if(c){v+=ovGauge(c.usage_pct,'CPU');}
      if(r){v+=ovGauge(r.pct!=null?r.pct:(r.total_mb?Math.round(r.used_mb/r.total_mb*100):0),'RAM');}
      if(!g&&!c&&!r)v+='<div class="muted">Telemetry unavailable.</div>';
      return v+'</div>';
    }
    if(id==='gpu'){
      const g=sys.gpu; if(!g)return '<div class="muted">No GPU telemetry.</div>';
      return '<div class="ovgauges">'+ovGauge(g.util_pct,'Util')+ovGauge(g.temp_c,'°C')+'</div>'+
        kv(esc(g.name||'GPU'),(g.vram_used_mb||0)+' / '+(g.vram_total_mb||0)+' MB')+ovBar(g.vram_used_mb,g.vram_total_mb);
    }
    if(id==='model'){
      const m=sys.model||{}; if(!m.name)return '<div class="muted">Model info unavailable.</div>';
      return kv('Model',esc(m.name))+kv('Context',(m.n_ctx||'—'))+kv('GPU layers',(m.n_gpu_layers!=null?m.n_gpu_layers:'—'))+
        kv('Batch',(m.n_batch||'—'))+kv('Uptime',esc(sys.uptime||'—'));
    }
    if(id==='quickactions'){
      return '<div class="qa">'+
        '<button class="qchip" onclick="switchTab(\'chat\')">&#128172; Chat</button>'+
        '<button class="qchip" onclick="switchTab(\'devices\')">&#127968; Home</button>'+
        '<button class="qchip" onclick="switchTab(\'research\')">&#128300; Research</button>'+
        '<button class="qchip" onclick="switchTab(\'system\')">&#128202; Telemetry</button>'+
        '<button class="qchip" onclick="switchTab(\'audit\')">&#128737; Audit</button></div>';
    }
    if(id==='quickcontrols'){
      const devs=(D.devices&&D.devices.devices)||[];
      const ctl=devs.filter(z=>z.command_topic||['airplay','firetv','cast','upnp'].indexOf(z.driver)>=0).slice(0,8);
      if(!ctl.length)return '<div class="muted">No controllable devices yet — add some in Home.</div>';
      let cb='';
      ctl.forEach(z=>{const xon=(''+(z.state||'')).toUpperCase()==='ON';
        const md=['airplay','firetv','cast','upnp'].indexOf(z.driver)>=0;
        cb+='<div class="ovact"><span class="aa">'+esc(z.display_name||z.name||z.id)+'</span>'+
          (md?('<span><button class="roombtn" onclick="ovCtl(\''+esc(z.id)+'\',\'play\')">&#9654;</button> <button class="roombtn" onclick="ovCtl(\''+esc(z.id)+'\',\'pause\')">&#9208;</button></span>')
            :('<button class="roombtn" onclick="ovCtl(\''+esc(z.id)+'\',\''+(xon?'off':'on')+'\')">'+(xon?'Turn off':'Turn on')+'</button>'))+'</div>';});
      return cb;
    }
    if(id==='rooms'){
      const rooms=(D.rooms&&D.rooms.rooms)||[];
      if(!rooms.length)return '<div class="muted">No rooms yet — assign devices to rooms in Home.</div>';
      let h='';
      rooms.forEach(rm=>{const nm=rm.room||'Room',ds=rm.devices||[];
        h+='<div class="ovroom"><div class="ovroomh"><span class="aa">'+esc(nm)+' <span class="muted">('+ds.length+')</span></span>'+
          '<span><button class="roombtn" onclick="ovRoom(\''+esc(nm)+'\',\'on\')">All on</button> '+
          '<button class="roombtn" onclick="ovRoom(\''+esc(nm)+'\',\'off\')">All off</button></span></div>';
        ds.forEach(z=>{const sv=(''+(z.state||'')).toUpperCase(),on=sv==='ON',off=sv==='OFF';
          const media=['airplay','firetv','cast','upnp'].indexOf(z.driver)>=0;
          const dot=on?'on':(off?'':'idle');
          h+='<div class="ovdev"><span class="aa"><span class="ddot '+dot+'"></span>'+esc(z.display_name||z.name||z.id)+'</span>'+
            (media?('<span><button class="roombtn" onclick="ovCtl(\''+esc(z.id)+'\',\'play\')">&#9654;</button> <button class="roombtn" onclick="ovCtl(\''+esc(z.id)+'\',\'pause\')">&#9208;</button></span>')
              :('<button class="roombtn" onclick="ovCtl(\''+esc(z.id)+'\',\''+(on?'off':'on')+'\')">'+(on?'Off':'On')+'</button>'))+'</div>';});
        h+='</div>';});
      return h;
    }
    if(id==='scenes'){
      const sc=(D.scenes&&D.scenes.scenes)||[];
      if(!sc.length)return '<div class="muted">No scenes yet — create scenes in Home.</div>';
      let h='';sc.forEach(s=>{const nm=s.name||s.id||'Scene';
        h+='<div class="ovact"><span class="aa">'+esc(nm)+'</span><button class="roombtn" onclick="ovScene(\''+esc(s.id||nm)+'\')">Activate</button></div>';});
      return h;
    }
    if(id==='automations'){
      const au=(D.automations&&D.automations.automations)||[];
      const devs=(D.devices&&D.devices.devices)||[];
      let h='';
      if(!au.length)h+='<div class="muted" style="margin-bottom:8px">No automations yet — add one below.</div>';
      au.slice(0,8).forEach(a=>{const tr=a.trigger||{},ac=a.action||{};
        h+='<div class="ovact"><span class="aa">'+esc(a.name||ac.device||'Automation')+
          ' <span class="muted">'+esc((tr.time||'')+' &middot; '+(ac.command||''))+'</span></span>'+
          '<span style="display:flex;gap:8px;align-items:center"><label class="miniSw"><input type="checkbox" '+(a.enabled?'checked':'')+' onchange="ovAutoToggle(\''+esc(a.id)+'\',this.checked)"></label>'+
          '<button class="wbtn rm" onclick="ovAutoRemove(\''+esc(a.id)+'\')" title="Remove">&#10005;</button></span></div>';});
      const opts=devs.map(d=>'<option value="'+esc(d.id)+'">'+esc(d.display_name||d.name||d.id)+'</option>').join('');
      h+='<div class="ovform">'+
        '<select id="au-dev">'+(opts||'<option value="">no devices</option>')+'</select>'+
        '<select id="au-cmd"><option value="on">On</option><option value="off">Off</option></select>'+
        '<input id="au-time" type="time" value="08:00">'+
        '<button class="qchip" onclick="ovAutoAdd()">+ Add</button></div>';
      return h;
    }
    if(id==='suggestions'){
      const sg=(D.suggestions&&D.suggestions.suggestions)||[];
      if(!sg.length)return '<div class="muted">No suggestions right now — ELI proposes automations as it learns your habits.</div>';
      let h='';sg.slice(0,6).forEach(s=>{h+='<div class="ovact"><span class="aa">'+esc(s.title||s.name||s.text||s.description||'Suggestion')+'</span></div>';});
      return h+'<button class="qchip" style="margin-top:8px" onclick="switchTab(\'devices\')">Review in Home</button>';
    }
    if(id==='corpora'){
      const co=(D.corpora&&D.corpora.corpora)||[];
      if(!co.length)return '<div class="muted">No research corpora yet.</div>';
      let h='';co.slice(0,8).forEach(z=>{const cnt=(z.documents!=null?z.documents:(z.count!=null?z.count:(z.docs!=null?z.docs:'')));
        h+='<div class="ovact"><span class="aa">'+esc(z.name||z.id||'corpus')+'</span><span class="at">'+(cnt!==''?(cnt+' docs'):'')+'</span></div>';});
      return h+'<button class="qchip" style="margin-top:8px" onclick="switchTab(\'research\')">Open Research</button>';
    }
    if(id==='capabilities'){
      const cp=D.capabilities||{}, cats=cp.categories||[];
      let h=kv('Total actions',(cp.total||0));
      cats.slice(0,8).forEach(z=>{h+='<div class="ovact"><span class="aa">'+esc(z.category||'')+'</span><span class="at">'+((z.actions||[]).length||'')+'</span></div>';});
      return h+'<button class="qchip" style="margin-top:8px" onclick="switchTab(\'commands\')">Browse commands</button>';
    }
    if(id==='sun'){
      const su=(D.sun&&D.sun.sun)||{};
      if(!su.sunrise&&!su.sunset)return '<div class="muted">Sun times unavailable.</div>';
      return kv('&#127749; Sunrise',esc(su.sunrise||'—'))+kv('&#127751; Sunset',esc(su.sunset||'—'));
    }
    if(id==='connect'){
      const cn=D.connect||{}, acc=cn.lan_accessible;
      return kv('Address',esc(cn.url||((cn.scheme||'http')+'://'+(cn.lan_ip||'')+':'+(cn.port||''))))+
        kv('LAN reachable','<span style="color:'+(acc?'#2ec07a':'#e0a72e')+'">'+(acc?'yes':'check firewall')+'</span>')+
        '<button class="qchip" style="margin-top:8px" onclick="switchTab(\'connect\')">Open Connect &amp; QR</button>';
    }
    if(id==='egress'){
      const net=(D.net&&D.net.net)||{};
      if(!net.enabled)return '<div class="muted">Internet is off — no outbound traffic. (Offline-by-default.)</div>';
      const rec=net.egress_recent||[];
      if(!rec.length)return '<div class="muted">Internet on; no outbound connections logged yet.</div>';
      let h=kv('Total outbound',(net.egress_total||0));
      rec.slice(-8).reverse().forEach(e=>{h+='<div class="ovact"><span class="aa">'+esc((e.host||'')+(e.port?(':'+e.port):''))+'</span><span class="at">'+esc(e.ts?fmtTime(e.ts):'')+'</span></div>';});
      return h;
    }
    if(id==='note'){
      const l=ovLayout();
      return '<textarea class="ovnote" oninput="ovNote(this)" onfocus="window._ovNoteFocus=1" onblur="window._ovNoteFocus=0" placeholder="Private notes — saved to your profile, synced across your devices.">'+esc(l.note||'')+'</textarea>';
    }
    if(id==='activity'){
      const ev=(D.audit&&D.audit.events)||[];
      if(!ev.length)return '<div class="muted">No activity yet.</div>';
      let ab='';
      ev.slice(0,8).forEach(e=>{ab+='<div class="ovact"><span class="aa">'+esc(e.action||e.event_type||'')+'</span><span class="au">'+esc(e.user_id||'system')+'</span><span class="at">'+esc(fmtTime(e.timestamp))+'</span></div>';});
      return ab;
    }
    if(id==='audit'){
      const ig=(D.audit&&D.audit.integrity)||{};
      return kv('Integrity','<span style="color:'+(ig.ok?'#2ec07a':'#ff6b8a')+'">'+(ig.ok?'verified':'TAMPER')+'</span>')+
        kv('Chained events',(ig.chained||0))+
        '<button class="qchip" style="margin-top:8px" onclick="switchTab(\'audit\')">Open Audit</button>';
    }
    return '<div class="muted">No data.</div>';
  }
  function renderOverview(D){
    const sys=(D.system&&D.system.status)||{}, m=sys.model||{};
    const ig=(D.audit&&D.audit.integrity)||{};
    const devs=(D.devices&&D.devices.devices)||[], on=devs.filter(d=>(''+(d.state||'')).toUpperCase()==='ON').length;
    const corpora=(D.corpora&&D.corpora.corpora)||[];
    const net=(D.net&&D.net.net)||{}, netOn=!!net.enabled;
    const hero='<div class="ovhero">'+
      '<div id="ov-clock" class="clock"><div class="t">--:--:--</div><div class="d"></div></div>'+
      '<div class="ovstat">'+
        '<div class="ovstat-row"><span class="dot ok"></span> System online &middot; model <b>'+esc(m.name||'—')+'</b></div>'+
        '<div class="ovstat-row"><span class="dot '+(ig.ok?'ok':'bad')+'"></span> Audit '+(ig.ok?('verified &middot; '+(ig.chained||0)+' events'):'TAMPER DETECTED')+'</div>'+
        '<div class="ovstat-row"><span class="dot '+(netOn?'warn':'ok')+'"></span> Internet '+(netOn?('<b>ON</b> &middot; '+(net.egress_total||0)+' outbound logged'):'off &middot; offline-by-default')+(net.override_active?' &middot; temp-allow active':'')+'</div>'+
        '<div class="ovstat-row"><span class="dot ok"></span> '+devs.length+' device(s) &middot; '+on+' on &middot; '+corpora.length+' corpora</div>'+
      '</div></div>';
    const vis=ovVisible();
    let grid='';
    vis.forEach(id=>{
      const body=ovWidget(id,D);
      grid+='<div class="widget'+(OV_WIDE[id]?' wide':'')+'" data-wid="'+id+'"'+(OV_EDIT?' draggable="true"':'')+'>'+
        '<div class="whead"><h4>'+esc(OV_TITLES[id]||id)+'</h4>'+
        (OV_EDIT?('<span class="wctl"><button class="wbtn" onclick="ovMove(\''+id+'\',-1)" title="Move up">&#9650;</button>'+
          '<button class="wbtn" onclick="ovMove(\''+id+'\',1)" title="Move down">&#9660;</button>'+
          '<button class="wbtn rm" onclick="ovRemove(\''+id+'\')" title="Remove">&#10005;</button></span>'):'')+
        '</div>'+(body||'')+'</div>';
    });
    const editbar='<div class="oveditbar"><button class="cbtn" onclick="ovToggleEdit()">'+(OV_EDIT?'&#10003; Done':'&#9998; Customize')+'</button>'+
      (OV_EDIT?'<button class="cbtn" style="opacity:.7" onclick="ovResetLayout()">Reset</button><span class="muted">Drag tiles, or use &#9650;&#9660; &middot; &#10005; removes &middot; add more tiles below</span>':'')+'</div>';
    let pal='';
    if(OV_EDIT){
      const avail=OV_CATALOG.filter(id=>vis.indexOf(id)<0);
      pal='<div class="ovpal"><div class="muted" style="margin-bottom:6px">'+(avail.length?('Available tiles ('+avail.length+') — tap to add:'):'Every tile is on your dashboard.')+'</div>'+
        avail.map(id=>'<button class="qchip" onclick="ovAdd(\''+id+'\')">+ '+esc(OV_TITLES[id]||id)+'</button>').join('')+'</div>';
    }
    $('#overview').innerHTML='<div class="ovwrap">'+hero+editbar+'<div class="ov-grid'+(OV_EDIT?' editing':'')+'" id="ov-grid">'+grid+'</div>'+pal+'</div>';
    if(OV_EDIT)ovBindDnd();
    tickClock(); if(ovClockTimer)clearInterval(ovClockTimer); ovClockTimer=setInterval(tickClock,1000);
  }
  function ovToggleEdit(){OV_EDIT=!OV_EDIT;loadOverview();}
  function ovMove(id,dir){const o=ovLayout().order,i=o.indexOf(id),j=i+dir;if(i<0||j<0||j>=o.length)return;const t=o[i];o[i]=o[j];o[j]=t;ovSaveLayout();loadOverview();}
  function ovRemove(id){const l=ovLayout();if(l.hidden.indexOf(id)<0)l.hidden.push(id);ovSaveLayout();loadOverview();}
  function ovAdd(id){const l=ovLayout();l.hidden=l.hidden.filter(z=>z!==id);if(l.order.indexOf(id)<0)l.order.push(id);ovSaveLayout();loadOverview();}
  function ovResetLayout(){const note=(OV_LAYOUT&&OV_LAYOUT.note)||'';OV_LAYOUT={order:OV_DEFAULT.slice(),hidden:[],note:note};ovSaveLayout();loadOverview();}
  function ovReorder(src,dst){const o=ovLayout().order,i=o.indexOf(src);if(i<0)return;o.splice(i,1);const j=o.indexOf(dst);o.splice(j<0?o.length:j,0,src);ovSaveLayout();loadOverview();}
  function ovBindDnd(){const grid=$('#ov-grid');if(!grid)return;
    grid.querySelectorAll('.widget').forEach(w=>{
      w.addEventListener('dragstart',()=>{OV_DRAG=w.getAttribute('data-wid');w.classList.add('drag');});
      w.addEventListener('dragend',()=>{w.classList.remove('drag');grid.querySelectorAll('.dragover').forEach(e=>e.classList.remove('dragover'));OV_DRAG=null;});
      w.addEventListener('dragover',e=>{e.preventDefault();if(OV_DRAG&&w.getAttribute('data-wid')!==OV_DRAG)w.classList.add('dragover');});
      w.addEventListener('dragleave',()=>w.classList.remove('dragover'));
      w.addEventListener('drop',e=>{e.preventDefault();const dst=w.getAttribute('data-wid');if(OV_DRAG&&dst!==OV_DRAG)ovReorder(OV_DRAG,dst);});
    });
  }
  window.ovToggleEdit=ovToggleEdit;window.ovMove=ovMove;window.ovRemove=ovRemove;window.ovAdd=ovAdd;window.ovResetLayout=ovResetLayout;
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
        if(box){box.disabled=true;box.placeholder='Read-only (viewer) — browse dashboards; you can\'t send actions.';}
        if(mic){mic.disabled=true;}
        const adminBtn=document.querySelector('nav.tabs button[data-tab="admin"]'); if(adminBtn) adminBtn.style.display='none';
      }
    }).catch(()=>{});
  })();

