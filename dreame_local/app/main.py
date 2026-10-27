"""Dreame Local Cloud – Einstiegspunkt.

Startet den MQTT-Broker (Cloud-Ersatz), die Geraeteprotokoll-Schicht,
die Home-Assistant-MQTT-Bruecke und die Web-UI.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import ssl
import sys
from pathlib import Path

import aiohttp
from aiohttp import web

from api import DreameApi
import events
from broker import MqttBroker
from device import Device
from ha import HaBridge
from web import Web

HERE = Path(__file__).resolve().parent
OPTIONS = Path(os.environ.get("OPTIONS_FILE", "/data/options.json"))
VERSION = "0.3.16"


def load_options() -> dict:
    opts: dict = {}
    if OPTIONS.exists():
        opts.update(json.loads(OPTIONS.read_text()))
    # Umgebungsvariablen fuer den Testbetrieb ausserhalb von HA
    for key in (
        "device_did",
        "device_uid",
        "device_model",
        "region",
        "mqtt_host",
        "mqtt_port",
        "mqtt_username",
        "mqtt_password",
        "device_name",
        "lan_ip",
        "upload_host",
        "device_ip",
        "broker_port",
        "web_port",
        "upload_port",
        "discovery_prefix",
        "api_port",
        "mac",
        "log_level",
    ):
        env = os.environ.get(key.upper())
        if env:
            opts[key] = env
    return opts


async def upload_server(
    device: Device, port: int, cert: str, key: str, data_dir: Path, lan_ip: str = ""
) -> None:
    """HTTPS-Endpunkt, an den der Roboter Karten/Logs hochlaedt."""
    ulog = logging.getLogger("upload")
    root = data_dir / "uploads"

    @web.middleware
    async def upload_log(request: web.Request, handler):
        ulog.info(
            "-> %s %s von %s (%s Bytes, %s)",
            request.method,
            request.path_qs,
            request.remote,
            request.content_length,
            request.headers.get("User-Agent", "?"),
        )
        try:
            response = await handler(request)
        except Exception as exc:  # pragma: no cover
            ulog.warning("Upload-Fehler %s %s: %s", request.method, request.path_qs, exc)
            events.add(
                "upload_error",
                path=request.path,
                method=request.method,
                error=str(exc),
            )
            raise
        ulog.info("<- %s %s", response.status, request.path_qs)
        return response

    app = web.Application(client_max_size=1024 * 1024 * 1024, middlewares=[upload_log])

    async def upload(request: web.Request) -> web.Response:
        name = request.match_info["name"].replace("..", "_").lstrip("/")
        if name.strip("/") == "__selftest":
            return web.Response(text="ok")
        # Der Roboter prueft die Presigned-URL offenbar vor dem PUT mit einer
        # anderen Methode (GET/HEAD/OPTIONS). Frueher antwortete aiohttp dort
        # mit 405, worauf der Roboter den Upload abbrach.
        if request.method not in ("PUT", "POST"):
            ulog.info(
                "Upload-Probe %s %s (kein Body erwartet)", request.method, request.path_qs
            )
            return web.Response(
                text="ok", headers={"Allow": "PUT, POST, GET, HEAD, OPTIONS"}
            )
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        size = 0
        tmp = target.with_suffix(target.suffix + ".part")
        with tmp.open("wb") as f:
            async for chunk in request.content.iter_chunked(65536):
                f.write(chunk)
                size += len(chunk)
        tmp.replace(target)
        ulog.info("Upload gespeichert: %s (%d Bytes)", target, size)
        events.add("upload", name=name, size=size)
        return web.Response(text="ok")

    # Alle Methoden, damit GET/HEAD/OPTIONS-Probes nicht mit 405 abbrechen.
    routes = [
        "/iot/tmp/000000/{name:.*}",
        "/device-log/pack/000000/{name:.*}",
        "/upload/{name:.*}",
    ]
    app.add_routes([web.route("*", path, upload) for path in routes])
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    runner = web.AppRunner(app, access_log=ulog)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port, ssl_context=ctx)
    await site.start()
    ulog.info("HTTPS-Upload auf :%d", port)

    async def _put_once(url: str) -> tuple[bool, str]:
        try:
            timeout = aiohttp.ClientTimeout(total=8)
            connector = aiohttp.TCPConnector(ssl=False)
            async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
                async with session.put(url, data=b"selftest") as resp:
                    body = (await resp.text())[:40]
                    return resp.status == 200, f"HTTP {resp.status} {body}"
        except Exception as exc:
            return False, str(exc)

    async def _selftest() -> None:
        await asyncio.sleep(2)
        loopback = f"https://127.0.0.1:{port}/iot/tmp/000000/__selftest"
        ok, detail = await _put_once(loopback)
        ulog.info("Upload-Selbsttest (intern): %s (%s)", "ok" if ok else "FEHLER", detail)
        events.add("upload_selftest", target="intern", ok=ok, detail=detail)
        if lan_ip:
            public = f"https://{lan_ip}:{port}/iot/tmp/000000/__selftest"
            ok2, detail2 = await _put_once(public)
            ulog.info("Upload-Selbsttest (LAN-IP): %s (%s)", "ok" if ok2 else "FEHLER", detail2)
            events.add("upload_selftest", target="lan_ip", ok=ok2, detail=detail2)
            if not ok2:
                ulog.warning(
                    "Upload-Port %d ist über %s:%d nicht erreichbar – "
                    "Portmapping/Firewall prüfen, sonst kann der Roboter nichts hochladen",
                    port,
                    lan_ip,
                    port,
                )

    asyncio.create_task(_selftest(), name="upload-selftest")


async def amain() -> int:
    opts = load_options()
    level = getattr(logging, str(opts.get("log_level", "info")).upper(), logging.INFO)
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    log = logging.getLogger("main")

    data_dir = Path(os.environ.get("DATA_DIR", "/data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    # Testdateien aus dem Upload-Verzeichnis entfernen (nie als Karte ausliefern).
    for junk in ("__test", "__selftest"):
        try:
            (data_dir / "uploads" / junk).unlink()
        except OSError:
            pass
    cert = str(HERE / "certs" / "server_chain.pem")
    key = str(HERE / "certs" / "server.key")

    did = str(opts.get("device_did") or "")
    uid = str(opts.get("device_uid") or "")
    model = str(opts.get("device_model") or "dreame.vacuum.r2469a")
    region = str(opts.get("region") or "eu")
    broker_port = int(opts.get("broker_port") or 19973)
    web_port = int(opts.get("web_port") or 8099)
    upload_port = int(opts.get("upload_port") or 8443)
    api_port = int(opts.get("api_port") or 13267)
    lan_ip = str(opts.get("lan_ip") or "")
    # Optionaler Hostname fuer die Upload-URLs (statt der LAN-IP). Manche
    # Roboter-Firmware akzeptiert keine IP-basierten Presigned-URLs.
    upload_host = str(opts.get("upload_host") or "").strip() or lan_ip
    upload_base = f"https://{upload_host}:{upload_port}" if upload_host else ""

    # Auto-Provisioning: DID/UID/Modell kommen aus dem MQTT-CONNECT bzw. dev_start.
    if not did:
        did = "unknown"

    device = Device(did, uid, model, region, publish=None, upload_base=upload_base, data_dir=data_dir)  # type: ignore[arg-type]

    broker: MqttBroker

    async def publish(topic: str, payload: str) -> int:
        return await broker.publish(topic, payload)

    device._publish = publish  # type: ignore[attr-defined]

    async def on_publish(topic: str, payload: bytes) -> None:
        log.debug("%s %s", topic, payload[:400])
        await device.on_message(topic, payload)

    async def on_connect(client_id: str, username: str | None) -> None:
        # Nur der Roboter meldet sich als "device_<did>". Andere Clients
        # (z. B. die Tasshack-Integration) duerfen den Zustand nicht aendern.
        if not client_id.startswith("device_"):
            return
        device.did = client_id[len("device_"):] or device.did
        log.info("Roboter verbunden: did=%s", device.did)
        await device.set_online(True)

    async def on_disconnect(client_id: str, username: str | None) -> None:
        if not client_id.startswith("device_"):
            return
        log.info("Roboter getrennt: %s", client_id)
        await device.set_online(False)

    broker = MqttBroker(
        broker_port,
        cert,
        key,
        on_publish=on_publish,
        on_connect=on_connect,
        on_disconnect=on_disconnect,
        device_ip=str(opts.get("device_ip") or ""),
    )

    loop = asyncio.get_running_loop()
    ha: HaBridge | None = None
    if opts.get("mqtt_host"):
        ha = HaBridge(device, opts, loop=loop)

        async def _on_state() -> None:
            ha.publish_state()

        device.listeners.append(_on_state)
        ha.start()

    web_ui = Web(device, web_port, data_dir, clients_fn=broker.clients, version=VERSION)
    api = DreameApi(
        device,
        api_port,
        cert,
        key,
        data_dir,
        public_host=lan_ip,
        mac=str(opts.get("mac") or ""),
    )

    async def safe_upload() -> None:
        try:
            await upload_server(device, upload_port, cert, key, data_dir, lan_ip=lan_ip)
        except OSError as exc:
            log.warning("HTTPS-Upload auf :%d nicht verfügbar (%s) – Karten-Uploads bleiben aus", upload_port, exc)

    async def safe_api() -> None:
        try:
            await api.start()
        except OSError as exc:
            log.warning("Dreame-API auf :%d nicht verfügbar (%s)", api_port, exc)

    tasks = [
        asyncio.create_task(broker.start(), name="broker"),
        asyncio.create_task(web_ui.start(), name="web"),
        asyncio.create_task(safe_upload(), name="upload"),
        asyncio.create_task(safe_api(), name="api"),
    ]
    if upload_base:
        log.info("Upload-Basis: %s (Presigned-URLs mit index + OSS-Query)", upload_base)
    else:
        log.warning(
            "lan_ip ist leer – der Roboter bekommt keine Upload-URLs, "
            "die Karte kann nicht ankommen"
        )
    if opts.get("device_ip"):
        log.info("Roboter-IP-Filter: device_* nur von %s", opts["device_ip"])
    log.info("Dreame Local Cloud v%s", VERSION)
    log.info(
        "Bereit: Broker :%d, API :%d, Web :%d, Upload :%d, Discovery %s, Auto-DID=%s",
        broker_port,
        api_port,
        web_port,
        upload_port,
        "an" if ha else "aus",
        did == "unknown",
    )
    try:
        await asyncio.gather(*tasks, return_exceptions=True)
    except asyncio.CancelledError:  # pragma: no cover
        pass
    finally:
        if ha:
            ha.stop()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(amain()))
    except KeyboardInterrupt:
        pass
