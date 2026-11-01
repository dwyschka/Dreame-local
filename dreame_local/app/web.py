"""Web-UI / REST-API (HA-Ingress oder direkt auf Port 8099)."""
from __future__ import annotations

import base64
import binascii
import json
import logging
import math
import re
import struct
import zlib
from pathlib import Path
from typing import Any

from aiohttp import web

import events
from device import Device, MODE, SUCTION, WATER

log = logging.getLogger("web")

PAGE = """<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<meta http-equiv="cache-control" content="no-store">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dreame Local</title>
<style>
:root{color-scheme:light dark}
body{font:15px/1.4 system-ui,sans-serif;margin:0;padding:16px;max-width:780px}
h1{font-size:1.2rem;margin:.2rem 0 1rem}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px}
.card{background:#8882;border-radius:10px;padding:10px}
.k{font-size:.75rem;opacity:.7;text-transform:uppercase;letter-spacing:.04em}
.v{font-size:1.15rem;font-weight:600;margin-top:2px}
button{font:inherit;padding:10px 14px;border-radius:10px;border:1px solid #8886;background:#8881;cursor:pointer}
button:active{transform:scale(.97)}
.row{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}
pre{background:#8881;padding:10px;border-radius:10px;overflow:auto;font-size:12px}
input,select,textarea{font:inherit;padding:8px;border-radius:8px;border:1px solid #8886;background:transparent}
.off{color:#e55}.on{color:#3c5}
</style></head><body>
<h1>Dreame Local Cloud <small id="ver" style="font-size:.7rem;opacity:.6"></small></h1>
<div class="card"><span class="k">Verbindung</span><div class="v" id="conn">…</div>
<div class="k" id="clients" style="margin-top:6px;text-transform:none;letter-spacing:0"></div></div>
<div class="grid" id="cards" style="margin-top:8px"></div>
<div class="row">
  <button data-cmd="start">Start</button>
  <button data-cmd="pause">Pause</button>
  <button data-cmd="stop">Stop</button>
  <button data-cmd="return_to_base">Zur Basis</button>
  <button data-cmd="locate">Finden</button>
</div>
<div class="row">
  <select id="suction"><option value="">Saugstufe…</option><option>quiet</option><option>standard</option><option>strong</option><option>turbo</option></select>
  <select id="water"><option value="">Wassermenge…</option><option>low</option><option>medium</option><option>high</option></select>
  <select id="mode"><option value="">Modus…</option><option>sweeping</option><option>mopping</option><option>sweeping_and_mopping</option></select>
</div>
<div class="row"><button id="refresh">Aktualisieren</button>
<button id="mapreq">Karte anfordern</button>
<button id="mapcheck">Karte prüfen</button>
<a href="rooms" style="align-self:center">Karte &amp; Räume →</a></div>
<pre id="log"></pre>
<h3 style="font-size:1rem">Diagnose</h3>
<pre id="diag">…</pre>
<script>
async function j(p, opt){ const r = await fetch(p, opt); return r.json(); }
function card(k,v){ return `<div class="card"><div class="k">${k}</div><div class="v">${v??'–'}</div></div>`; }
async function tick(){
  try {
    const s = await j('api/state?t=' + Date.now());
    document.getElementById('ver').textContent = s.version ? 'v' + s.version : '';
    document.getElementById('conn').innerHTML = s.online ? '<span class="on">online</span>' : '<span class="off">offline</span>';
    document.getElementById('clients').textContent = (s.clients || []).map(c => c.client_id).join(', ') || 'keine MQTT-Clients';
    document.getElementById('cards').innerHTML = [
      card('Akku', s.battery!=null ? s.battery+' %' : null),
      card('Status', s.state), card('Fehler', s.error||'–'),
      card('Fläche', s.cleaned_area), card('Zeit', s.cleaning_time!=null ? s.cleaning_time+' s' : null),
      card('Saugen', s.suction), card('Wasser', s.water), card('Modus', s.mode),
      card('Firmware', s.ver)
    ].join('');
    if(s.suction) document.getElementById('suction').value = s.suction;
    if(s.water) document.getElementById('water').value = s.water;
    if(s.mode) document.getElementById('mode').value = s.mode;
    document.getElementById('log').textContent = JSON.stringify(s.props,null,1).slice(0,4000);
  } catch(e){ document.getElementById('conn').textContent = 'Add-on nicht erreichbar'; }
}
document.querySelectorAll('button[data-cmd]').forEach(b=>b.onclick=async()=>{
  await j('api/command',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:b.dataset.cmd})});
  setTimeout(tick,500);
});
for (const [id,prop] of [['suction','SUCTION_LEVEL'],['water','WATER_VOLUME'],['mode','CLEANING_MODE']]){
  const el=document.getElementById(id);
  el.onchange=async()=>{ if(!el.value) return;
    await j('api/command',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({set:prop,value:el.value})});
    setTimeout(tick,500); };
}
document.getElementById('mapreq').onclick=async()=>{
  const s=await j('api/state');
  const frame = JSON.stringify({req_type:1,frame_type:'I',force_type:1,time:Date.now()});
  await j('api/command',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({method:'action',params:{did:String(s.did),siid:6,aiid:1,
      in:[{piid:2,value:frame}]}})});
  setTimeout(diag,1000);
};
async function diag(){
  try{
    const d=await j('api/diagnostics');
    const lines=[];
    lines.push('Clients:');
    (d.clients||[]).forEach(c=>lines.push(`  ${c.client_id}  ${c.peer}  ${(c.topics||[]).join(', ')}`));
    lines.push('', 'Uploads:');
    (d.uploads||[]).slice(0,10).forEach(u=>lines.push(`  ${u.name}  ${u.size} B  ${new Date(u.mtime*1000).toLocaleString()}`));
    lines.push('', 'Events:');
    (d.events||[]).slice(0,30).forEach(e=>{
      const {ts,kind,...rest}=e; lines.push(`  ${ts} ${kind} ${JSON.stringify(rest).slice(0,220)}`);
    });
    document.getElementById('diag').textContent=lines.join('\\n');
  }catch(e){ document.getElementById('diag').textContent='Diagnose nicht verfügbar'; }
}
document.getElementById('mapcheck').onclick=async()=>{
  try {
    const r=await j('api/mapcheck');
    document.getElementById('diag').textContent=JSON.stringify(r,null,2);
  }catch(e){ document.getElementById('diag').textContent='Kartenprüfung fehlgeschlagen'; }
};
document.getElementById('refresh').onclick=()=>{tick();diag();};
diag(); setInterval(diag, 5000);
tick(); setInterval(tick, 3000);
</script></body></html>"""


ROOMS_PAGE = """<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<meta http-equiv="cache-control" content="no-store">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Karte &amp; Räume – Dreame Local</title>
<style>
:root{color-scheme:light dark}
body{font:14px/1.4 system-ui,sans-serif;margin:0;padding:16px;max-width:1200px}
h1{font-size:1.2rem;margin:.2rem 0 .2rem}
a{color:#49a}
.editor{display:flex;gap:16px;align-items:flex-start;flex-wrap:wrap;margin-top:10px}
.mapwrap{position:relative;flex:1 1 520px;min-width:300px;max-width:100%}
#mapimg{width:100%;height:auto;display:block;border-radius:10px;background:#222}
#overlay{position:absolute;inset:0;width:100%;height:100%}
#overlay rect{cursor:pointer}
#overlay text{pointer-events:none;font-size:9px;fill:#fff;font-weight:700;paint-order:stroke;stroke:#000;stroke-width:2px}
.panel{flex:0 1 320px;min-width:260px}
.card{background:#8882;border-radius:10px;padding:10px;margin-bottom:10px}
.k{font-size:.72rem;opacity:.7;text-transform:uppercase;letter-spacing:.04em}
button{font:inherit;padding:8px 10px;border-radius:8px;border:1px solid #8886;background:#8881;cursor:pointer;margin:2px}
button:disabled{opacity:.4;cursor:default}
button.active{background:#49a;border-color:#49a;color:#fff}
.room{display:flex;align-items:center;gap:8px;padding:6px;border-radius:8px;cursor:pointer;border:1px solid transparent}
.room.sel{border-color:#49a;background:#49a2}
.dot{width:12px;height:12px;border-radius:50%;flex:none}
small{opacity:.7}
#hint{min-height:2.5em;opacity:.8}
#zonehint{min-height:2.5em;opacity:.8;margin-top:6px}
</style></head><body>
<h1>Karte &amp; Räume <small id="mapid"></small></h1>
<a href="./">← Zurück</a>
<div class="editor">
  <div class="mapwrap">
    <img id="mapimg" alt="Karte">
    <svg id="overlay" preserveAspectRatio="none"></svg>
  </div>
  <div class="panel">
    <div class="card"><div class="k">Status</div><div id="status">lade …</div></div>
    <div class="card"><div class="k">Räume</div><div id="roomlist"></div></div>
    <div class="card">
      <div class="k">Zonen</div>
      <div class="row">
        <button data-zone="nogo">Sperrzone</button>
        <button data-zone="nomop">Wisch-Verbot</button>
        <button data-zone="wall">Virtuelle Wand</button>
        <button data-zone="clean">Reinigungszone</button>
      </div>
      <div class="row">
        <button id="zoneSave">Zonen speichern</button>
        <button id="zoneClean" disabled>Bereich reinigen</button>
        <button id="zoneClear">Alle Zonen löschen</button>
      </div>
      <div id="zonehint"></div>
    </div>
    <div class="card">
      <div class="k">Aktionen</div>
      <button id="rename" disabled>Umbenennen</button>
      <button id="merge" disabled>Zusammenführen</button>
      <button id="split" disabled>Teilen</button>
      <button id="clean" disabled>Räume reinigen</button>
      <button id="reload">Aktualisieren</button>
      <div class="row" style="margin-top:8px">
        <button id="request">Karte anfordern</button>
        <button id="backup">Karte sichern</button>
        <button id="fastmap">Schnellkartierung</button>
      </div>
      <div id="hint"></div>
    </div>
  </div>
</div>
<script>
const palette=['#4c78a8','#f58518','#54a24b','#b279a2','#72b7b2','#e45756','#9d755d','#bab0ac'];
let data=null, selected=new Set(), splitMode=false, splitPts=[];
let zones={line:[],rect:[],mop:[]}, cleanZones=[], zoneMode=null, zonePts=[];
const ZONE_NAMES={nogo:'Sperrzone',nomop:'Wisch-Verbot',wall:'Virtuelle Wand',clean:'Reinigungszone'};
const $=id=>document.getElementById(id);
const img=$('mapimg'), overlay=$('overlay'), statusEl=$('status'), listEl=$('roomlist'), hint=$('hint');

async function j(url,opt){const r=await fetch(url,opt); const t=await r.text(); try{return JSON.parse(t)}catch(e){throw new Error(t.slice(0,300))}}
function colorFor(id){return palette[(Number(id)-1+palette.length)%palette.length]}
function toPx(x,y){return [(x-data.origin[0])/data.grid,(y-data.origin[1])/data.grid]}
function toMap(px,py){return [Math.round(data.origin[0]+px*data.grid),Math.round(data.origin[1]+py*data.grid)]}

async function load(force){
  try{
    data=await j('api/rooms?t='+Date.now());
    if(!data.ok){statusEl.textContent=data.error||'Keine Kartendaten';return}
    if(force){
      const z=data.zones||{};
      zones={
        line:(z.line||[]).map(a=>a.slice(0,4)),
        rect:(z.rect||[]).map(a=>a.slice(0,4)),
        mop:(z.mop||[]).map(a=>a.slice(0,4))
      };
      cleanZones=[];
    }
    $('mapid').textContent='Map '+data.map_id+' · '+data.width+'×'+data.height;
    img.src='api/map.png?t='+Date.now();
    overlay.setAttribute('viewBox',`0 0 ${data.width} ${data.height}`);
    statusEl.textContent=(data.rooms||[]).length+' Räume geladen';
    render();
  }catch(e){statusEl.textContent='Fehler: '+e.message}
}
function render(){
  if(!data) return;
  overlay.innerHTML='';
  const NS='http://www.w3.org/2000/svg';
  for(const r of data.rooms||[]){
    const b=r.bbox;
    const rect=document.createElementNS(NS,'rect');
    rect.setAttribute('x',b[0]); rect.setAttribute('y',b[1]);
    rect.setAttribute('width',Math.max(1,b[2]-b[0])); rect.setAttribute('height',Math.max(1,b[3]-b[1]));
    rect.setAttribute('fill',(r.color||colorFor(r.id))+'33');
    rect.setAttribute('stroke',selected.has(r.id)?'#fff':'#0008');
    rect.setAttribute('stroke-width',selected.has(r.id)?2:1);
    rect.addEventListener('click',ev=>{ if(splitMode||zoneMode) return; ev.stopPropagation(); toggle(r.id)});
    overlay.appendChild(rect);
    const t=document.createElementNS(NS,'text');
    t.setAttribute('x',(b[0]+b[2])/2); t.setAttribute('y',(b[1]+b[3])/2);
    t.setAttribute('text-anchor','middle'); t.setAttribute('dominant-baseline','middle');
    t.textContent=r.name||('Raum '+r.id);
    overlay.appendChild(t);
  }
  if(data.path && data.path.length>1){
    const pl=document.createElementNS(NS,'polyline');
    pl.setAttribute('points',data.path.map(p=>p[0]+','+p[1]).join(' '));
    pl.setAttribute('fill','none'); pl.setAttribute('stroke','#ffd166');
    pl.setAttribute('stroke-width',1.3); pl.setAttribute('stroke-opacity','0.9');
    overlay.appendChild(pl);
  }
  if(data.robot){
    const r=data.robot;
    const c=document.createElementNS(NS,'circle');
    c.setAttribute('cx',r.px); c.setAttribute('cy',r.py); c.setAttribute('r',3);
    c.setAttribute('fill','#fff'); c.setAttribute('stroke','#111'); c.setAttribute('stroke-width',1);
    overlay.appendChild(c);
    const l=document.createElementNS(NS,'line');
    l.setAttribute('x1',r.px); l.setAttribute('y1',r.py);
    l.setAttribute('x2',r.px+Math.cos(r.a*Math.PI/180)*7);
    l.setAttribute('y2',r.py+Math.sin(r.a*Math.PI/180)*7);
    l.setAttribute('stroke','#111'); l.setAttribute('stroke-width',1.5);
    overlay.appendChild(l);
  }
  const drawRectZone=(area,stroke,fill,dash)=>{
    const a=toPx(area[0],area[1]), b=toPx(area[2],area[3]);
    const x=Math.min(a[0],b[0]), y=Math.min(a[1],b[1]);
    const w=Math.max(0.5,Math.abs(b[0]-a[0])), h=Math.max(0.5,Math.abs(b[1]-a[1]));
    const el=document.createElementNS(NS,'rect');
    el.setAttribute('x',x); el.setAttribute('y',y);
    el.setAttribute('width',w); el.setAttribute('height',h);
    el.setAttribute('fill',fill); el.setAttribute('stroke',stroke);
    el.setAttribute('stroke-width',1.5); el.setAttribute('pointer-events','none');
    if(dash) el.setAttribute('stroke-dasharray','3 2');
    overlay.appendChild(el);
  };
  const drawLineZone=(line,stroke,dash)=>{
    const a=toPx(line[0],line[1]), b=toPx(line[2],line[3]);
    const el=document.createElementNS(NS,'line');
    el.setAttribute('x1',a[0]); el.setAttribute('y1',a[1]);
    el.setAttribute('x2',b[0]); el.setAttribute('y2',b[1]);
    el.setAttribute('stroke',stroke); el.setAttribute('stroke-width',2);
    el.setAttribute('pointer-events','none');
    if(dash) el.setAttribute('stroke-dasharray','3 2');
    overlay.appendChild(el);
  };
  for(const z of zones.rect) drawRectZone(z,'#e45756','#e4575633',false);
  for(const z of zones.mop) drawRectZone(z,'#f58518','#f5851833',false);
  for(const z of zones.line) drawLineZone(z,'#ffffff',false);
  for(const z of cleanZones) drawRectZone(z,'#54a24b','#54a24b33',true);
  if(zonePts.length===1){
    const c=document.createElementNS(NS,'circle');
    c.setAttribute('cx',zonePts[0][0]); c.setAttribute('cy',zonePts[0][1]);
    c.setAttribute('r',2); c.setAttribute('fill','#fff'); overlay.appendChild(c);
  }
  if(splitPts.length===1){
    const c=document.createElementNS(NS,'circle');
    c.setAttribute('cx',splitPts[0][0]); c.setAttribute('cy',splitPts[0][1]);
    c.setAttribute('r',2); c.setAttribute('fill','#fff'); overlay.appendChild(c);
  }
  listEl.innerHTML='';
  for(const r of data.rooms||[]){
    const div=document.createElement('div');
    div.className='room'+(selected.has(r.id)?' sel':'');
    div.innerHTML=`<span class="dot" style="background:${r.color||colorFor(r.id)}"></span><span>${r.name||('Raum '+r.id)}</span><small>#${r.id}</small>`;
    div.onclick=()=>toggle(r.id);
    listEl.appendChild(div);
  }
  $('rename').disabled=selected.size!==1;
  $('merge').disabled=selected.size!==2;
  $('split').disabled=selected.size!==1;
  $('clean').disabled=selected.size===0;
  $('zoneClean').disabled=cleanZones.length===0;
  $('split').textContent=splitMode?'Teilen abbrechen':'Teilen';
  document.querySelectorAll('button[data-zone]').forEach(b=>b.classList.toggle('active',b.dataset.zone===zoneMode));
  hint.textContent=splitMode?'Zwei Punkte auf der Karte anklicken, um den Raum zu teilen.':'Räume anklicken, um sie auszuwählen.';
  $('zonehint').textContent=zoneMode
    ? ZONE_NAMES[zoneMode]+': zwei Punkte auf der Karte anklicken.'
    : (zones.rect.length+' Sperrzonen, '+zones.mop.length+' Wisch-Verbote, '+zones.line.length+' virtuelle Wände, '+cleanZones.length+' Reinigungszonen');
}
function toggle(id){if(selected.has(id))selected.delete(id);else selected.add(id);render()}
overlay.addEventListener('click',ev=>{
  if(!data) return;
  const p=overlay.createSVGPoint(); p.x=ev.clientX; p.y=ev.clientY;
  const q=p.matrixTransform(overlay.getScreenCTM().inverse());
  const px=Math.max(0,Math.min(data.width,q.x)), py=Math.max(0,Math.min(data.height,q.y));
  if(zoneMode){
    zonePts.push([px,py]);
    if(zonePts.length===2){
      const a=toMap(zonePts[0][0],zonePts[0][1]);
      const b=toMap(zonePts[1][0],zonePts[1][1]);
      if(zoneMode==='wall'){
        zones.line.push([a[0],a[1],b[0],b[1]]);
      }else{
        const area=[a[0],a[1],b[0],b[1]];
        if(zoneMode==='nogo') zones.rect.push(area);
        else if(zoneMode==='nomop') zones.mop.push(area);
        else cleanZones.push(area);
      }
      zonePts=[]; zoneMode=null;
    }
    render(); return;
  }
  if(!splitMode||selected.size!==1) return;
  splitPts.push([px,py]);
  if(splitPts.length===2){
    const [a,b]=splitPts;
    const line=[data.origin[0]+a[0]*data.grid, data.origin[1]+a[1]*data.grid,
                data.origin[0]+b[0]*data.grid, data.origin[1]+b[1]*data.grid];
    post({action:'split', id:[...selected][0], line});
    splitPts=[]; splitMode=false;
  }
  render();
});
async function post(body){
  statusEl.textContent='Sende …';
  try{
    const r=await j('api/rooms/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    statusEl.textContent=r.ok?'Befehl gesendet – Karte wird aktualisiert …':('Fehler: '+(r.error||'unbekannt'));
    setTimeout(load,2500);
  }catch(e){statusEl.textContent='Fehler: '+e.message}
}
$('rename').onclick=()=>{
  if(selected.size!==1) return;
  const id=[...selected][0];
  const r=(data.rooms||[]).find(x=>x.id===id)||{};
  const name=prompt('Neuer Raumname:',r.name||('Raum '+id));
  if(name!==null&&name.trim()!=='') post({action:'rename',id,name:name.trim()});
};
$('merge').onclick=()=>{
  if(selected.size!==2) return;
  const ids=[...selected];
  if(confirm('Räume '+ids.join(' + ')+' zusammenführen?')) post({action:'merge',ids});
};
$('split').onclick=()=>{ if(selected.size!==1) return; zoneMode=null; zonePts=[]; splitMode=!splitMode; splitPts=[]; render(); };
document.querySelectorAll('button[data-zone]').forEach(b=>b.onclick=()=>{
  splitMode=false; splitPts=[]; zonePts=[];
  zoneMode = zoneMode===b.dataset.zone ? null : b.dataset.zone;
  render();
});
$('zoneSave').onclick=()=>post({action:'zones',walls:zones.line,zones:zones.rect,no_mops:zones.mop});
$('zoneClean').onclick=()=>{
  if(cleanZones.length===0) return;
  if(confirm(cleanZones.length+' Reinigungszone(n) jetzt reinigen?')) post({action:'zone_clean',areas:cleanZones});
};
$('zoneClear').onclick=()=>{
  if(!confirm('Alle gespeicherten Zonen auf der Karte löschen?')) return;
  zones={line:[],rect:[],mop:[]}; cleanZones=[]; zonePts=[]; zoneMode=null;
  render();
  post({action:'zones',walls:[],zones:[],no_mops:[]});
};
$('clean').onclick=()=>{
  if(selected.size===0) return;
  const ids=[...selected];
  if(confirm('Räume '+ids.join(', ')+' jetzt reinigen?')) post({action:'clean',ids});
};
$('request').onclick=async()=>{
  const frame=JSON.stringify({req_type:1,frame_type:'I',force_type:1,time:Date.now()});
  await post({action:'request_map',frame});
};
$('backup').onclick=()=>post({action:'backup_map'});
$('fastmap').onclick=()=>{
  if(confirm('Schnellkartierung starten?')) post({action:'fast_map'});
};
$('reload').onclick=()=>load(true);
load(true); setInterval(()=>load(false),5000);
</script></body></html>"""


@web.middleware
async def ingress_middleware(request: web.Request, handler):
    """HA-Ingress stellt /api/hassio_ingress/<token>/... voran."""
    path = request.path
    if path.startswith("/api/hassio_ingress/"):
        parts = path.split("/", 4)
        rest = "/" + (parts[4] if len(parts) > 4 else "")
        request = request.clone(rel_url=request.rel_url.with_path(rest))
    return await handler(request)


@web.middleware
async def no_cache(request: web.Request, handler):
    response = await handler(request)
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return response


class Web:
    def __init__(
        self,
        device: Device,
        port: int = 8099,
        data_dir: Path | None = None,
        clients_fn=None,
        version: str = "",
    ) -> None:
        self.dev = device
        self.clients_fn = clients_fn
        self.version = version
        self.port = port
        self.data_dir = data_dir or Path("/data")
        self.app = web.Application(
            client_max_size=512 * 1024 * 1024,
            middlewares=[ingress_middleware, no_cache],
        )
        self.app.add_routes(
            [
                web.get("/", self.index),
                web.get("/api/state", self.state),
                web.get("/api/uploads", self.uploads),
                web.get("/api/diagnostics", self.diagnostics),
                web.get("/api/mapcheck", self.mapcheck),
                web.get("/rooms", self.rooms_page),
                web.get("/api/rooms", self.rooms_data),
                web.get("/api/map.png", self.map_png),
                web.post("/api/rooms/action", self.room_action),
                web.post("/api/command", self.command),
                web.put("/upload/{name:.*}", self.upload),
            ]
        )

    async def start(self) -> None:
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", self.port)
        await site.start()
        log.info("Web-UI auf :%d", self.port)

    async def index(self, request: web.Request) -> web.Response:
        return web.Response(text=PAGE, content_type="text/html")

    async def state(self, request: web.Request) -> web.Response:
        snap = self.dev.snapshot()
        snap["version"] = self.version
        if self.clients_fn:
            # Online-Status direkt aus den aktiven MQTT-Sessions ableiten,
            # damit eine verspaetete alte Session ihn nicht dauerhaft kippt.
            clients = self.clients_fn()
            snap["online"] = any(
                str(c.get("client_id", "")).startswith("device_") for c in clients
            )
            snap["clients"] = clients
        return web.json_response(snap)

    async def uploads(self, request: web.Request) -> web.Response:
        root = self.data_dir / "uploads"
        files = []
        if root.exists():
            for p in root.rglob("*"):
                if p.is_file():
                    st = p.stat()
                    files.append({"name": str(p.relative_to(root)), "size": st.st_size,
                                  "mtime": int(st.st_mtime)})
        files.sort(key=lambda x: x["mtime"], reverse=True)
        return web.json_response({"uploads": files, "log": str(self.data_dir / "api.log")})

    async def diagnostics(self, request: web.Request) -> web.Response:
        root = self.data_dir / "uploads"
        uploads = []
        if root.exists():
            for p in root.rglob("*"):
                if p.is_file():
                    st = p.stat()
                    uploads.append({"name": str(p.relative_to(root)), "size": st.st_size,
                                    "mtime": int(st.st_mtime)})
        uploads.sort(key=lambda x: x["mtime"], reverse=True)
        clients = self.clients_fn() if self.clients_fn else []
        return web.json_response({"clients": clients, "events": events.all(), "uploads": uploads})

    async def mapcheck(self, request: web.Request) -> web.Response:
        """Prueft den zuletzt hochgeladenen Kartenblob (Format/Header)."""
        root = self.data_dir / "uploads"
        name = request.query.get("name") or f"ali_dreame/{self.dev.uid}/{self.dev.did}/9"
        target = root / name
        if not target.is_file():
            candidates = (
                [p for p in root.rglob("*") if p.is_file() and not p.name.startswith("__")]
                if root.exists()
                else []
            )
            if not candidates:
                return web.json_response({"ok": False, "error": "keine Uploads vorhanden"})
            target = max(candidates, key=lambda p: p.stat().st_mtime)
            name = str(target.relative_to(root))

        result: dict[str, Any] = {
            "ok": False,
            "name": name,
            "size": target.stat().st_size,
        }
        try:
            data = target.read_bytes()
            text = data.decode("utf-8", "replace").strip()
            result["text_len"] = len(text)
            result["head"] = text[:60]
            key = None
            if "," in text:
                text, key = text.split(",", 1)
                result["embedded_key"] = True
            raw_b64 = text.replace("_", "/").replace("-", "+")
            while len(raw_b64) % 4:
                raw_b64 += "="
            raw = base64.b64decode(raw_b64, validate=False)
            result["decoded_len"] = len(raw)
            result["magic"] = raw[:4].hex()
            try:
                plain = zlib.decompress(raw)
                result["zlib"] = True
            except Exception:
                plain = raw
                result["zlib"] = False
            result["plain_len"] = len(plain)
            if result["zlib"] and len(plain) >= 27:
                result["map_id"] = int.from_bytes(plain[0:2], "little")
                result["frame_id"] = int.from_bytes(plain[2:4], "little")
                result["frame_type"] = plain[4]
                width = int.from_bytes(plain[19:21], "little")
                height = int.from_bytes(plain[21:23], "little")
                result["width"] = width
                result["height"] = height
                image_size = 27 + width * height
                result["image_size"] = image_size
                if len(plain) >= image_size:
                    try:
                        meta = json.loads(plain[image_size:].decode("utf-8"))
                        result["json_keys"] = sorted(meta.keys())
                        result["json_timestamp_ms"] = meta.get("timestamp_ms")
                    except Exception as exc:
                        result["json_error"] = str(exc)
                result["ok"] = True
            elif not result["zlib"]:
                result["error"] = (
                    "kein zlib-Header – Blob ist vermutlich verschlüsselt "
                    "oder keine Karte (Magic %s)" % result["magic"]
                )
        except Exception as exc:
            result["error"] = str(exc)
        return web.json_response(result)

    # ---------------------------------------------------------- Raum-Editor
    @staticmethod
    def _decode_map_text(text: str):
        text = text.strip()
        if not text or text.startswith("{"):
            return None
        if "," in text:
            text = text.split(",", 1)[0]
        t = text.replace("_", "/").replace("-", "+")
        t += "=" * (-len(t) % 4)
        try:
            raw = zlib.decompress(base64.b64decode(t, validate=False))
        except Exception:
            return None
        if len(raw) < 27:
            return None
        width = int.from_bytes(raw[19:21], "little")
        height = int.from_bytes(raw[21:23], "little")
        image_end = 27 + width * height
        if width <= 0 or height <= 0 or len(raw) < image_end:
            return None
        try:
            info = json.loads(raw[image_end:].decode("utf-8"))
        except Exception:
            return None
        return raw, width, height, info

    def _load_map(self):
        root = self.data_dir / "uploads" / f"ali_dreame/{self.dev.uid}/{self.dev.did}"
        best = None
        for name in ("9", "9.frame"):
            path = root / name
            try:
                if not path.is_file():
                    continue
                decoded = self._decode_map_text(path.read_text(errors="replace"))
                if not decoded:
                    continue
                raw, width, height, info = decoded
                item = {
                    "raw": raw, "width": width, "height": height, "info": info,
                    "map_id": int.from_bytes(raw[0:2], "little"),
                    "grid": int.from_bytes(raw[17:19], "little") or 50,
                    "origin": info.get("origin") or [
                        int.from_bytes(raw[23:25], "little", signed=True),
                        int.from_bytes(raw[25:27], "little", signed=True),
                    ],
                    "name": name, "mtime": path.stat().st_mtime,
                }
                if best is None or item["mtime"] > best["mtime"]:
                    best = item
            except Exception:
                continue
        if best is None:
            live = self.dev.props.get("6.1")
            if isinstance(live, str) and live:
                decoded = self._decode_map_text(live)
                if decoded:
                    raw, width, height, info = decoded
                    best = {
                        "raw": raw, "width": width, "height": height, "info": info,
                        "map_id": int.from_bytes(raw[0:2], "little"),
                        "grid": int.from_bytes(raw[17:19], "little") or 50,
                        "origin": info.get("origin") or [0, 0],
                        "name": "live", "mtime": 0,
                    }
        return best

    def _room_names(self) -> dict[str, str]:
        try:
            data = json.loads((self.data_dir / "room_names.json").read_text())
            return {str(k): str(v) for k, v in data.items()}
        except Exception:
            return {}

    def _save_room_name(self, room_id: int, name: str) -> None:
        names = self._room_names()
        names[str(room_id)] = name
        try:
            (self.data_dir / "room_names.json").write_text(json.dumps(names, ensure_ascii=False))
        except OSError:
            pass

    def _room_list(self, m):
        raw, width, height = m["raw"], m["width"], m["height"]
        origin_x, origin_y = m["origin"][0], m["origin"][1]
        grid = m["grid"] or 50
        names = self._room_names()
        img = raw[27:27 + width * height]
        bboxes = {}
        for y in range(height):
            for x in range(width):
                v = img[y * width + x]
                if 0 < v < 64:
                    b = bboxes.get(v)
                    if b is None:
                        bboxes[v] = [x, y, x, y]
                    else:
                        if x < b[0]: b[0] = x
                        if y < b[1]: b[1] = y
                        if x > b[2]: b[2] = x
                        if y > b[3]: b[3] = y
        palette = ['#4c78a8', '#f58518', '#54a24b', '#b279a2', '#72b7b2', '#e45756', '#9d755d', '#bab0ac']
        rooms = []
        for rid, b in sorted(bboxes.items()):
            rooms.append({
                "id": rid,
                "name": names.get(str(rid)) or f"Raum {rid}",
                "color": palette[(rid - 1) % len(palette)],
                "bbox": b,
                "center": [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2],
                "map_bbox": [
                    origin_x + b[0] * grid, origin_y + b[1] * grid,
                    origin_x + b[2] * grid, origin_y + b[3] * grid,
                ],
            })
        return rooms

    def _map_png(self, m) -> bytes:
        raw, width, height = m["raw"], m["width"], m["height"]
        img = raw[27:27 + width * height]
        palette = ['#4c78a8', '#f58518', '#54a24b', '#b279a2', '#72b7b2', '#e45756', '#9d755d', '#bab0ac']

        def rgb(hex_color):
            hex_color = hex_color.lstrip('#')
            return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))

        room_colors = [rgb(c) for c in palette]
        colors = {
            0: (250, 250, 250), 255: (45, 45, 45), 254: (43, 108, 176),
            253: (160, 174, 192), 252: (160, 160, 160), 251: (210, 80, 80),
            250: (235, 180, 100), 249: (72, 187, 120), 248: (160, 220, 160),
        }
        scale = 4
        rows = []
        for y in range(height * scale):
            row = bytearray([0])
            for x in range(width * scale):
                v = img[(y // scale) * width + (x // scale)]
                if 0 < v < 64:
                    c = room_colors[(v - 1) % len(room_colors)]
                elif 100 < v < 200:
                    c = room_colors[(v - 101) % len(room_colors)]
                else:
                    c = colors.get(v, (120, 120, 120))
                row += bytes(c)
            rows.append(bytes(row))
        W, H = width * scale, height * scale

        def chunk(tag, data):
            return struct.pack("!I", len(data)) + tag + data + struct.pack(
                "!I", binascii.crc32(tag + data) & 0xFFFFFFFF
            )

        return (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack("!IIBBBBB", W, H, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
            + chunk(b"IEND", b"")
        )

    async def rooms_page(self, request: web.Request) -> web.Response:
        return web.Response(text=ROOMS_PAGE, content_type="text/html")

    async def rooms_data(self, request: web.Request) -> web.Response:
        m = self._load_map()
        if not m:
            return web.json_response({"ok": False, "error": "keine Kartendaten gefunden"})
        origin_x, origin_y = m["origin"][0], m["origin"][1]
        grid = m["grid"] or 50
        robot = None
        live = self.dev.props.get("6.1")
        if isinstance(live, str) and live:
            decoded = self._decode_map_text(live)
            if decoded:
                lraw, _lw, _lh, _linfo = decoded
                x = int.from_bytes(lraw[5:7], "little", signed=True)
                y = int.from_bytes(lraw[7:9], "little", signed=True)
                a = int.from_bytes(lraw[9:11], "little", signed=True)
                if x != 32767 and y != 32767:
                    robot = {
                        "x": x, "y": y, "a": a,
                        "px": (x - origin_x) / grid,
                        "py": (y - origin_y) / grid,
                    }
        path = []
        raw_path = getattr(self.dev, "map_path", "")
        if isinstance(raw_path, str) and raw_path:
            current = (0, 0)
            for match in re.finditer(r"([MWSLl])(-?\d+),(-?\d+)", raw_path):
                operator = match.group(1)
                x = int(match.group(2))
                y = int(match.group(3))
                if operator == "L":
                    current = (current[0] + x, current[1] + y)
                else:
                    current = (x, y)
                path.append([
                    (current[0] - origin_x) / grid,
                    (current[1] - origin_y) / grid,
                ])
            if len(path) > 4000:
                path = path[-4000:]
        return web.json_response({
            "ok": True,
            "map_id": m["map_id"],
            "width": m["width"],
            "height": m["height"],
            "origin": m["origin"],
            "grid": m["grid"],
            "source": m["name"],
            "mtime": int(m["mtime"]),
            "rooms": self._room_list(m),
            "zones": m["info"].get("vw") or {},
            "robot": robot,
            "path": path,
        })

    async def map_png(self, request: web.Request) -> web.Response:
        m = self._load_map()
        if not m:
            raise web.HTTPNotFound()
        return web.Response(body=self._map_png(m), content_type="image/png")

    async def room_action(self, request: web.Request) -> web.Response:
        body = await request.json()
        action = str(body.get("action") or "")
        try:
            if action == "request_map":
                frame = str(body.get("frame") or '{"frame_type":"I"}')
                result = await self.dev.raw_action(6, 1, [{"piid": 2, "value": frame}])
                events.add("map_request", result=result)
                return web.json_response({"ok": True, "result": result})
            if action == "fast_map":
                # START_CUSTOM mit Status 21 = Schnellkartierung
                result = await self.dev.raw_action(4, 1, [{"piid": 1, "value": 21}])
                events.add("fast_map", result=result)
                return web.json_response({"ok": True, "result": result})

            m = self._load_map()
            if not m:
                return web.json_response({"ok": False, "error": "keine Karte geladen"})
            map_id = int(body.get("map_id") or m["map_id"])

            if action == "clean":
                ids = [int(v) for v in (body.get("ids") or [])]
                if not ids:
                    raise ValueError("keine Räume ausgewählt")
                fan = int(self.dev.get("SUCTION_LEVEL") or 2)
                water = int(self.dev.get("WATER_VOLUME") or 2)
                cleanlist = [[rid, 1, fan, water, 1] for rid in ids]
                payload = {"selects": cleanlist}
                params = {
                    "did": self.dev.did,
                    "siid": 4,
                    "aiid": 1,
                    "in": [
                        {"piid": 1, "value": 18},  # SEGMENT_CLEANING
                        {"piid": 10, "value": json.dumps(payload, separators=(",", ":"))},
                    ],
                }
                log.info("Raumreinigung %s", payload)
                result = await self.dev.send("action", params, timeout=20)
                events.add("room_clean", ids=ids, result=result)
                if isinstance(result, dict) and result.get("code") not in (0, None):
                    return web.json_response({"ok": False, "error": str(result), "result": result})
                return web.json_response({"ok": True, "result": result})

            if action == "zone_clean":
                areas = []
                for area in (body.get("areas") or []):
                    coords = [int(round(float(v))) for v in area[:4]]
                    if len(coords) == 4:
                        areas.append(coords)
                if not areas:
                    raise ValueError("keine Reinigungszone ausgewählt")
                payload = {"areas": areas}
                params = {
                    "did": self.dev.did,
                    "siid": 4,
                    "aiid": 1,
                    "in": [
                        {"piid": 1, "value": 19},  # ZONE_CLEANING
                        {"piid": 10, "value": json.dumps(payload, separators=(",", ":"))},
                    ],
                }
                log.info("Zonenreinigung %s", payload)
                result = await self.dev.send("action", params, timeout=20)
                events.add("zone_clean", areas=areas, result=result)
                if isinstance(result, dict) and result.get("code") not in (0, None):
                    return web.json_response({"ok": False, "error": str(result), "result": result})
                return web.json_response({"ok": True, "result": result})

            if action == "backup_map":
                result = await self.dev.raw_action(6, 3, [{"piid": 4, "value": str(map_id)}])
                events.add("map_backup", map_id=map_id, result=result)
                return web.json_response({"ok": True, "result": result})

            if action == "rename":
                rid = int(body.get("id"))
                name = str(body.get("name") or "").strip()
                if not name:
                    raise ValueError("leerer Raumname")
                payload = {
                    "nsr": {str(rid): {
                        "name": base64.b64encode(name.encode("utf-8")).decode("ascii"),
                        "type": 0,
                        "index": 0,
                    }},
                    "mapid": map_id,
                }
            elif action == "merge":
                ids = [int(v) for v in (body.get("ids") or [])]
                if len(ids) != 2:
                    raise ValueError("genau zwei Räume auswählen")
                payload = {"msr": ids, "mapid": map_id}
            elif action == "split":
                rid = int(body.get("id"))
                line = [int(round(float(v))) for v in (body.get("line") or [])]
                if len(line) != 4:
                    raise ValueError("Teilungslinie fehlt")
                payload = {"dsrid": line + [rid], "mapid": map_id}
            elif action == "zones":
                walls = [[int(round(float(v))) for v in wall[:4]] for wall in (body.get("walls") or [])]
                zones = [[int(round(float(v))) for v in zone[:4]] for zone in (body.get("zones") or [])]
                no_mops = [[int(round(float(v))) for v in zone[:4]] for zone in (body.get("no_mops") or [])]
                payload = {"vw": {"line": walls, "rect": zones, "mop": no_mops}}
            else:
                raise ValueError("unbekannte Aktion")
            params = {
                "did": self.dev.did,
                "siid": 6,
                "aiid": 2,
                "in": [{"piid": 4, "value": json.dumps(payload, separators=(",", ":"))}],
            }
            log.info("Raum-Aktion %s: %s", action, payload)
            result = await self.dev.send("action", params, timeout=20)
            events.add("room_edit", action=action, map_id=map_id, result=result)
            if isinstance(result, dict) and result.get("code") not in (0, None):
                return web.json_response({"ok": False, "error": str(result), "result": result})
            if action == "rename":
                self._save_room_name(rid, name)
            return web.json_response({"ok": True, "result": result})
        except Exception as exc:
            log.warning("Raum-Aktion fehlgeschlagen: %s", exc)
            return web.json_response({"ok": False, "error": str(exc)})

    async def command(self, request: web.Request) -> web.Response:
        body: dict[str, Any] = await request.json()
        try:
            if "action" in body:
                res = await self.dev.action(str(body["action"]))
            elif "method" in body:
                res = await self.dev.send(str(body["method"]), body.get("params"))
            elif "set" in body:
                prop = str(body["set"])
                value = body.get("value")
                if prop == "SUCTION_LEVEL" and isinstance(value, str):
                    value = SUCTION.get(value.upper(), value)
                elif prop == "WATER_VOLUME" and isinstance(value, str):
                    value = WATER.get(value.upper(), value)
                elif prop == "CLEANING_MODE" and isinstance(value, str):
                    value = MODE.get(value.upper(), value)
                res = await self.dev.set_property(prop, value)
            elif "get" in body:
                res = await self.dev.get_properties(list(body["get"]))
            else:
                return web.json_response({"ok": False, "error": "action|method|set|get fehlt"}, status=400)
            return web.json_response({"ok": True, "result": res})
        except Exception as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=500)

    async def upload(self, request: web.Request) -> web.Response:
        name = request.match_info["name"].replace("..", "_")
        target = self.data_dir / "uploads" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        size = 0
        with target.open("wb") as f:
            async for chunk in request.content.iter_chunked(65536):
                f.write(chunk)
                size += len(chunk)
        log.info("Upload gespeichert: %s (%d Bytes)", target, size)
        return web.Response(text="ok")
