"""Dreame-Cloud-API-Emulation (HTTP) – kompatibel zur Tasshack-Integration.

Die Integration (custom_components/dreame_vacuum) spricht ausschliesslich
diese Endpunkte an; wenn DNS `eu.iot.dreame.tech` hierher zeigt, laeuft sie
unveraendert weiter – inklusive Karten/Kartenkarten.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

from aiohttp import web

import events
from device import Device

log = logging.getLogger("api")

TOKEN = "local-access-token"
REFRESH = "local-refresh-token"


def _ok(data: Any = None) -> web.Response:
    body: dict[str, Any] = {"code": 0, "success": True, "msg": None}
    if data is not None:
        body["data"] = data
    return web.json_response(body)


@web.middleware
async def api_log_middleware(request: web.Request, handler):
    """Schreibt jeden API-Aufruf nach /data/api.log (Diagnose)."""
    body = ""
    try:
        body = await request.text()
    except Exception:
        pass
    response = await handler(request)
    try:
        events.add("api", path=request.path, status=response.status)
        logfile = request.app["logfile"]
        with open(logfile, "a") as f:
            f.write(
                json.dumps(
                    {
                        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "method": request.method,
                        "path": request.path,
                        "body": body[:800],
                        "status": response.status,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    except Exception:
        pass
    return response


class DreameApi:
    def __init__(
        self,
        device: Device,
        port: int,
        cert: str,
        key: str,
        data_dir: Path,
        public_host: str = "",
        mac: str = "",
    ) -> None:
        self.dev = device
        self.port = port
        self.cert = cert
        self.key = key
        self.data_dir = data_dir
        self.public_host = public_host
        self.mac = mac
        self.app = web.Application(client_max_size=64 * 1024 * 1024, middlewares=[api_log_middleware])
        self.app["logfile"] = str(data_dir / "api.log")
        self.app.add_routes(
            [
                web.get("/files/{name:.*}", self.file),
                web.get("/api/uploads", self.uploads),
                web.post("/dreame-auth/oauth/token", self.token),
                web.post("/dreame-auth/oauth/refresh", self.token),
                web.post("/dreame-user-iot/iotuserbind/device/listV2", self.devices),
                web.post("/dreame-user-iot/iotuserbind/device/getDeviceListByHomeV2", self.devices),
                web.post("/dreame-user-iot/iotuserbind/device/info", self.device_info),
                web.post("/dreame-user-iot/iotstatus/devOTCInfo", self.otc_info),
                web.post("/dreame-user-iot/iotstatus/props", self.props),
                web.post("/dreame-user-iot/iotstatus/getDeviceData", self.device_data),
                web.post("/dreame-user-iot/iotstatus/history", self.history),
                web.post("/dreame-user-iot/iotfile/getDownloadUrl", self.download_url),
                web.post("/dreame-user-iot/iotfile/getOss1dDownloadUrl", self.download_url),
                web.post("/file-bridge/user/getDeiviceFile", self.device_file),
                web.post("/dreame-iot-com-{shard}/device/sendCommand", self.send_command),
                web.post("/{tail:.*}", self.fallback),
            ]
        )

    async def start(self) -> None:
        import ssl

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(self.cert, self.key)
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", self.port, ssl_context=ctx)
        await site.start()
        log.info("Dreame-API-Emulation auf :%d (HTTPS)", self.port)

    # ------------------------------------------------------------------ helper
    @property
    def bind_domain(self) -> str:
        return f"{self.public_host}:19973" if self.public_host else "10000.mt.eu.iot.dreame.tech:19973"

    def _device_record(self) -> dict[str, Any]:
        return {
            "did": int(self.dev.did) if str(self.dev.did).isdigit() else self.dev.did,
            "model": self.dev.model,
            "subModel": self.dev.model,
            "masterUid": self.dev.uid,
            "bindDomain": self.bind_domain,
            "property": json.dumps({"iotId": f"{self.dev.did}-local"}),
            "mac": self.mac or "00:00:00:00:00:00",
            "ver": self.dev.ver or "4.3.9_1642",
            "name": "Dreame",
            "customName": "Dreame",
            "deviceInfo": {"model": self.dev.model, "productId": "10335"},
        }

    # ------------------------------------------------------------------ routes
    async def file(self, request: web.Request) -> web.Response:
        name = request.match_info["name"].replace("..", "_").lstrip("/")
        # Die Integration haengt an eine gecachte URL "&current=<ts>" an.
        # Bei URLs ohne "?" landet das im Pfad – defensiv abschneiden.
        name = name.split("&current=")[0]
        if name.startswith("iot/tmp/000000/"):
            name = name[len("iot/tmp/000000/"):]
        target = self.data_dir / "uploads" / name
        if not target.exists():
            target = self.data_dir / "uploads" / self._resolve(name)
        if not target.exists():
            log.warning("GET /files/%s: nicht gefunden", name)
            raise web.HTTPNotFound()
        return web.FileResponse(target)

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
        return web.json_response({"files": files})

    async def token(self, request: web.Request) -> web.Response:
        log.info("Login von %s", request.remote)
        # ACHTUNG: Die Integration liest access_token/refresh_token/uid/region
        # auf der obersten Ebene (OAuth-Standard), nicht unter "data".
        return web.json_response(
            {
                "access_token": TOKEN,
                "refresh_token": REFRESH,
                "expires_in": 86400,
                "token_type": "bearer",
                "scope": "all",
                "region": self.dev.region or "eu",
                "tenant_id": "000000",
                "uid": self.dev.uid or str(self.dev.did),
                "country": "de",
                "lang": "de",
            }
        )

    async def devices(self, request: web.Request) -> web.Response:
        log.info("listV2")
        return _ok({"page": {"records": [self._device_record()], "total": 1, "size": 20, "current": 1}})

    async def device_info(self, request: web.Request) -> web.Response:
        log.info("device/info")
        return _ok(self._device_record())

    async def otc_info(self, request: web.Request) -> web.Response:
        log.info("devOTCInfo")
        return _ok(
            {
                "otcInfo": {
                    "partner_id": "",
                    "params": {
                        "hw_ver": "Linux",
                        "fw_ver": self.dev.ver or "4.3.9_1642",
                        "model": self.dev.model,
                        "netif": {"localIp": "", "mask": "", "gw": ""},
                        "ap": {"siid": "", "bssid": "", "rssi": 0},
                    },
                }
            }
        )

    async def props(self, request: web.Request) -> web.Response:
        body = await request.json()
        keys = body.get("keys")
        if isinstance(keys, str):
            keys = [keys]
        keys = keys or []
        log.info("props %s", keys)
        out = []
        for key in keys:
            key = str(key)
            parts = key.split(".")
            if len(parts) == 2:
                siid, piid = parts
                value = self.dev.props.get(f"{siid}.{piid}")
                item = {"siid": int(siid), "piid": int(piid), "value": value, "code": 0,
                        "did": self.dev.did}
                try:
                    item["updateDate"] = int(time.time() * 1000)
                except Exception:
                    pass
                out.append(item)
            else:
                value = self.dev.get(key.upper())
                out.append({"piid": 0, "siid": 0, "value": value, "code": 0, "did": self.dev.did})
        # Die Integration erwartet data[0].value
        return _ok(out)

    async def device_data(self, request: web.Request) -> web.Response:
        """Historische Property-Daten (Map-Frames). Lokal gibt es keinen Verlauf."""
        body = await request.json()
        log.info("getDeviceData siid=%s piid=%s limit=%s", body.get("siid"), body.get("piid"), body.get("limit"))
        return _ok({"list": []})

    async def history(self, request: web.Request) -> web.Response:
        """Reinigungsverlauf – lokal (noch) nicht vorhanden, aber gueltige Antwort."""
        log.info("history")
        return _ok([])

    def _resolve(self, name: str) -> str:
        """Existiert die Datei? Sonst die neueste hochgeladene Datei nehmen."""
        root = self.data_dir / "uploads"
        target = root / name
        if name and target.is_file():
            return name
        candidates = (
            [p for p in root.rglob("*") if p.is_file() and not p.name.startswith("__")]
            if root.exists()
            else []
        )
        if not candidates:
            log.warning("Datei %r fehlt und es gibt keine Uploads", name)
            return name
        newest = max(candidates, key=lambda p: p.stat().st_mtime)
        rel = str(newest.relative_to(root))
        if name:
            log.warning("Datei %r fehlt, liefere stattdessen %r", name, rel)
        else:
            log.info("Kein Dateiname angegeben, liefere %r", rel)
        return rel

    async def download_url(self, request: web.Request) -> web.Response:
        body = await request.json()
        name = str(body.get("filename") or "").lstrip("/")
        resolved = self._resolve(name)
        # Die Integration laedt die Karte ueber denselben Host, ueber den sie
        # auch die API aufruft (z. B. eu.iot.dreame.tech:13267). Ein Wechsel
        # auf die LAN-IP bricht bei ihrem eigenen TLS-Client.
        host = (request.host.split(":")[0] if request.host else "") or self.public_host or "localhost"
        # Wichtig: eine Query muss vorhanden sein, denn die Integration haengt
        # beim Wiederverwenden einer gecachten URL "&current=<ts>" an.
        expires = int(time.time()) + 1800
        url = (
            f"https://{host}:{self.port}/files/{quote(resolved, safe='/')}"
            f"?Expires={expires}&obj={quote(resolved, safe='/')}"
        )
        log.info("getDownloadUrl %r -> %s", name, url)
        events.add("map_url", requested=name, served=resolved, url=url)
        return _ok(url)

    async def device_file(self, request: web.Request) -> web.Response:
        body = await request.json()
        info = body.get("fileinfo") or "{}"
        try:
            info = json.loads(info) if isinstance(info, str) else info
        except Exception:
            info = {}
        name = str(info.get("filename") or "").lstrip("/")
        target = self.data_dir / "uploads" / name
        log.info("getDeiviceFile %s (%s)", name, "ok" if target.exists() else "fehlt")
        if not target.exists():
            return web.Response(status=404)
        return web.Response(body=target.read_bytes(), content_type="application/octet-stream")

    async def send_command(self, request: web.Request) -> web.Response:
        body = await request.json()
        data = body.get("data") or {}
        method = data.get("method")
        params = data.get("params")
        rid = data.get("id") or body.get("id")
        log.info("sendCommand %s %s", method, json.dumps(params)[:300] if params is not None else "")
        try:
            result = await self.dev.send(str(method), params, timeout=15)
            if method == "get_properties":
                result = self._complete_properties(result, params)
            return web.json_response({"code": 0, "success": True, "data": {"id": rid, "result": result}})
        except Exception as exc:
            log.warning("sendCommand %s fehlgeschlagen: %s", method, exc)
            return web.json_response({"code": -1, "success": False, "msg": str(exc)})

    def _complete_properties(self, result: Any, requested: Any) -> Any:
        """Fehlende Properties aus dem Cache ergaenzen.

        Der Roboter beantwortet je nach Auslastung nur einen Teil eines
        get_properties-Blocks. Die Integration uebernimmt aber genau die
        zurueckgegebenen Werte – fehlende Keys bleiben dann veraltet.
        """
        if not isinstance(result, list) or not isinstance(requested, list):
            return result
        have: set[tuple[int, int]] = set()
        for item in result:
            if not isinstance(item, dict):
                continue
            try:
                have.add((int(item["siid"]), int(item["piid"])))
            except (KeyError, TypeError, ValueError):
                continue
        changed = False
        for q in requested:
            if not isinstance(q, dict):
                continue
            try:
                siid, piid = int(q["siid"]), int(q["piid"])
            except (KeyError, TypeError, ValueError):
                continue
            if (siid, piid) in have:
                continue
            value = self.dev.props.get(f"{siid}.{piid}")
            if value is None:
                continue
            result.append(
                {"did": self.dev.did, "siid": siid, "piid": piid, "value": value, "code": 0}
            )
            changed = True
        if changed:
            log.debug("get_properties: fehlende Werte aus Cache ergaenzt")
        return result

    async def fallback(self, request: web.Request) -> web.Response:
        log.info("unbekannter Aufruf: %s %s", request.method, request.path)
        return _ok({})
