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

from aiohttp import web

from api import DreameApi
from broker import MqttBroker
from device import Device
from ha import HaBridge
from web import Web

HERE = Path(__file__).resolve().parent
OPTIONS = Path(os.environ.get("OPTIONS_FILE", "/data/options.json"))


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


async def upload_server(device: Device, port: int, cert: str, key: str, data_dir: Path) -> None:
    """HTTPS-Endpunkt, an den der Roboter Karten/Logs hochlaedt."""
    app = web.Application(client_max_size=1024 * 1024 * 1024)

    async def put(request: web.Request) -> web.Response:
        name = request.match_info["name"].replace("..", "_")
        target = data_dir / "uploads" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        size = 0
        with target.open("wb") as f:
            async for chunk in request.content.iter_chunked(65536):
                f.write(chunk)
                size += len(chunk)
        logging.getLogger("upload").info("Upload %s (%d Bytes)", target, size)
        return web.Response(text="ok")

    app.add_routes([web.put("/upload/{name:.*}", put), web.post("/upload/{name:.*}", put)])
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port, ssl_context=ctx)
    await site.start()
    logging.getLogger("upload").info("HTTPS-Upload auf :%d", port)


async def amain() -> int:
    opts = load_options()
    level = getattr(logging, str(opts.get("log_level", "info")).upper(), logging.INFO)
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    log = logging.getLogger("main")

    data_dir = Path(os.environ.get("DATA_DIR", "/data"))
    data_dir.mkdir(parents=True, exist_ok=True)
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
    upload_base = f"https://{lan_ip}:{upload_port}" if lan_ip else ""

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
        if client_id.startswith("device_"):
            device.did = client_id[len("device_"):] or device.did
        elif username:
            device.did = username
        log.info("Roboter verbunden: did=%s", device.did)
        await device.set_online(True)

    async def on_disconnect(client_id: str, username: str | None) -> None:
        log.info("Roboter getrennt: %s", client_id)
        await device.set_online(False)

    broker = MqttBroker(
        broker_port,
        cert,
        key,
        on_publish=on_publish,
        on_connect=on_connect,
        on_disconnect=on_disconnect,
    )

    loop = asyncio.get_running_loop()
    ha: HaBridge | None = None
    if opts.get("mqtt_host"):
        ha = HaBridge(device, opts, loop=loop)

        async def _on_state() -> None:
            ha.publish_state()

        device.listeners.append(_on_state)
        ha.start()

    web_ui = Web(device, web_port, data_dir)
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
            await upload_server(device, upload_port, cert, key, data_dir)
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
