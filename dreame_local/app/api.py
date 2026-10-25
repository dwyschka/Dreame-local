"""Dreame-Cloud-API-Emulation (HTTP) – kompatibel zur Tasshack-Integration.

Die Integration (custom_components/dreame_vacuum) spricht ausschliesslich
diese Endpunkte an; wenn DNS `eu.iot.dreame.tech` hierher zeigt, laeuft sie
unveraendert weiter – inklusive Karten/Kartenkarten.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from aiohttp import web

from device import Device

log = logging.getLogger("api")

TOKEN = "local-access-token"
REFRESH = "local-refresh-token"


def _ok(data: Any = None) -> web.Response:
    body: dict[str, Any] = {"code": 0, "success": True, "msg": None}
    if data is not None:
        body["data"] = data
    return web.json_response(body)


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
        self.app = web.Application(client_max_size=64 * 1024 * 1024)
        self.app.add_routes(
            [
                web.get("/files/{name:.*}", self.file),
                web.post("/dreame-auth/oauth/token", self.token),
                web.post("/dreame-auth/oauth/refresh", self.token),
                web.post("/dreame-user-iot/iotuserbind/device/listV2", self.devices),
                web.post("/dreame-user-iot/iotuserbind/device/getDeviceListByHomeV2", self.devices),
                web.post("/dreame-user-iot/iotuserbind/device/info", self.device_info),
                web.post("/dreame-user-iot/iotstatus/devOTCInfo", self.otc_info),
                web.post("/dreame-user-iot/iotstatus/props", self.props),
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
        name = request.match_info["name"].replace("..", "_")
        target = self.data_dir / "uploads" / name
        if not target.exists():
            raise web.HTTPNotFound()
        return web.FileResponse(target)

    async def token(self, request: web.Request) -> web.Response:
        log.info("Login von %s", request.remote)
        return _ok(
            {
                "access_token": TOKEN,
                "refresh_token": REFRESH,
                "expires_in": 86400,
                "token_type": "bearer",
                "scope": "all",
                "region": self.dev.region or "eu",
                "tenant_id": "000000",
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
        keys = body.get("keys") or []
        log.info("props %s", keys)
        data: dict[str, Any] = {}
        out = []
        for key in keys:
            value = self.dev.get(str(key).upper())
            if value is not None:
                out.append({"piid": 1, "value": value, "siid": 1, "did": self.dev.did})
                data[str(key)] = value
        return _ok({"props": out, **data})

    async def download_url(self, request: web.Request) -> web.Response:
        body = await request.json()
        name = str(body.get("filename") or "").lstrip("/")
        log.info("getDownloadUrl %s", name)
        return _ok(f"https://{self.public_host}:{self.port}/files/{name}")

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
        log.info("sendCommand %s", method)
        try:
            result = await self.dev.send(str(method), params, timeout=15)
            return web.json_response({"code": 0, "success": True, "data": {"id": rid, "result": result}})
        except Exception as exc:
            log.warning("sendCommand %s fehlgeschlagen: %s", method, exc)
            return web.json_response({"code": -1, "success": False, "msg": str(exc)})

    async def fallback(self, request: web.Request) -> web.Response:
        log.info("unbekannter Aufruf: %s %s", request.method, request.path)
        return _ok({})
