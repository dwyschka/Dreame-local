"""Web-UI / REST-API (HA-Ingress oder direkt auf Port 8099)."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from aiohttp import web

import events
from device import Device, MODE, SUCTION, WATER

log = logging.getLogger("web")

PAGE = """<!doctype html>
<html lang="de"><head><meta charset="utf-8">
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
<h1>Dreame Local Cloud</h1>
<div class="card"><span class="k">Verbindung</span><div class="v" id="conn">…</div></div>
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
<button id="mapreq">Karte anfordern</button></div>
<pre id="log"></pre>
<h3 style="font-size:1rem">Diagnose</h3>
<pre id="diag">…</pre>
<script>
async function j(p, opt){ const r = await fetch(p, opt); return r.json(); }
function card(k,v){ return `<div class="card"><div class="k">${k}</div><div class="v">${v??'–'}</div></div>`; }
async function tick(){
  try {
    const s = await j('api/state');
    document.getElementById('conn').innerHTML = s.online ? '<span class="on">online</span>' : '<span class="off">offline</span>';
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
    document.getElementById('diag').textContent=lines.join('\n');
  }catch(e){ document.getElementById('diag').textContent='Diagnose nicht verfügbar'; }
}
document.getElementById('refresh').onclick=()=>{tick();diag();};
diag(); setInterval(diag, 5000);
tick(); setInterval(tick, 3000);
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


class Web:
    def __init__(self, device: Device, port: int = 8099, data_dir: Path | None = None, clients_fn=None) -> None:
        self.dev = device
        self.clients_fn = clients_fn
        self.port = port
        self.data_dir = data_dir or Path("/data")
        self.app = web.Application(client_max_size=512 * 1024 * 1024, middlewares=[ingress_middleware])
        self.app.add_routes(
            [
                web.get("/", self.index),
                web.get("/api/state", self.state),
                web.get("/api/uploads", self.uploads),
                web.get("/api/diagnostics", self.diagnostics),
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
        if self.clients_fn:
            # Online-Status direkt aus den aktiven MQTT-Sessions ableiten,
            # damit eine verspaetete alte Session ihn nicht dauerhaft kippt.
            snap["online"] = any(
                str(c.get("client_id", "")).startswith("device_")
                for c in self.clients_fn()
            )
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
