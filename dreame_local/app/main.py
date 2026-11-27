"""Dreame Local Cloud – Einstiegspunkt.

Startet den MQTT-Broker (Cloud-Ersatz), die Geraeteprotokoll-Schicht,
die Home-Assistant-MQTT-Bruecke und die Web-UI.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import ssl
import sys
import tarfile
import zlib
from pathlib import Path

import aiohttp
from aiohttp import web

from api import DreameApi
from certutil import ensure_api_cert, export_ca, resolve_material
import events
from broker import MqttBroker
from device import Device
from ha import HaBridge
from web import Web

HERE = Path(__file__).resolve().parent
OPTIONS = Path(os.environ.get("OPTIONS_FILE", "/data/options.json"))
VERSION = "0.9.6"


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
        "upload_http_port",
        "upload_scheme",
        "discovery_prefix",
        "api_cert",
        "api_key",
        "api_port",
        "mac",
        "log_level",
    ):
        env = os.environ.get(key.upper())
        if env:
            opts[key] = env
    return opts


async def upload_server(
    device: Device, port: int, cert: str, key: str, data_dir: Path, lan_ip: str = "",
    http_port: int = 0,
) -> None:
    """HTTPS-/HTTP-Endpunkt, an den der Roboter Karten/Logs hochlaedt."""
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

    # Die Web-UI (8099) ist bei HA OS nur ueber Ingress erreichbar. Der
    # Upload-Port 19980 ist gemappt und unverschluesselt; dort gibt es die
    # CA fuer die einmalige Installation in certifi.
    async def ca_pem(_request: web.Request) -> web.Response:
        target = data_dir / "certs" / "ca.pem"
        if not target.is_file():
            raise web.HTTPNotFound(text="CA noch nicht erzeugt")
        return web.Response(
            body=target.read_bytes(),
            content_type="application/x-pem-file",
            headers={"Content-Disposition": "attachment; filename=dreame-local-ca.pem"},
        )

    app.add_routes([web.get("/ca.pem", ca_pem)])

    def _bridge_tar() -> bytes:
        """Custom Component als tar.gz (ohne __pycache__) verpacken."""
        buf = io.BytesIO()

        def _filter(info: tarfile.TarInfo):
            if info.name.endswith(".pyc") or Path(info.name).name in ("__pycache__", ".DS_Store"):
                return None
            return info

        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            tar.add(HERE / "dreame_local_ca", arcname="dreame_local_ca", filter=_filter)
        return buf.getvalue()

    async def bridge_tar(_request: web.Request) -> web.Response:
        return web.Response(
            body=_bridge_tar(),
            content_type="application/gzip",
            headers={"Content-Disposition": 'attachment; filename="dreame_local_ca.tar.gz"'},
        )

    async def install_bridge(request: web.Request) -> web.Response:
        base = (
            f"http://{lan_ip}:{http_port}"
            if lan_ip and http_port
            else f"{request.scheme}://{request.host}"
        )
        template = (HERE / "install_bridge.sh").read_text()
        return web.Response(
            text=template.replace("__BASE_URL__", base),
            content_type="text/x-shellscript",
            headers={"Content-Disposition": 'attachment; filename="install-bridge.sh"'},
        )

    app.add_routes(
        [
            web.get("/dreame_local_ca.tar.gz", bridge_tar),
            web.get("/install-bridge.sh", install_bridge),
        ]
    )

    async def install_ca(_request: web.Request) -> web.Response:
        target = HERE / "install_ca.sh"
        if not target.is_file():
            raise web.HTTPNotFound(text="Installationsskript fehlt")
        return web.Response(
            body=target.read_bytes(),
            content_type="text/x-shellscript",
            headers={"Content-Disposition": 'attachment; filename="install-ca.sh"'},
        )

    app.add_routes([web.get("/install-ca.sh", install_ca)])

    # Alle Methoden, damit GET/HEAD/OPTIONS-Probes nicht mit 405 abbrechen.
    routes = [
        "/iot/tmp/000000/{name:.*}",
        "/device-log/pack/000000/{name:.*}",
        "/upload/{name:.*}",
    ]
    app.add_routes([web.route("*", path, upload) for path in routes])
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)

    # Diagnose: Kommt der Roboter ueberhaupt per TLS an (sonst Firewall) und
    # bricht er den Handshake ab (z. B. Alert 48 unknown_ca / 42 bad_cert)?
    def _tls_hello(_sslobj, server_name, _ctx) -> None:
        ulog.info("TLS-Handshake eingehend (SNI=%s)", server_name)
        events.add("upload_tls", sni=server_name or "")

    def _tls_msg(_conn, direction, _version, content_type, _msg_type, data) -> None:
        if direction == "read" and int(content_type) == 21 and len(data) >= 2:
            ulog.warning("TLS-Alert vom Client: level=%d desc=%d", data[0], data[1])
            events.add("upload_tls_alert", level=data[0], desc=data[1])

    ctx.sni_callback = _tls_hello
    try:
        ctx._msg_callback = _tls_msg  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover
        pass
    runner = web.AppRunner(app, access_log=ulog)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port, ssl_context=ctx)
    await site.start()
    ulog.info("HTTPS-Upload auf :%d", port)
    # Der HTTP-Client des Roboters prueft das Upload-Zertifikat gegen sein
    # oeffentliches CA-Bundle und bricht mit Alert 48 (unknown_ca) ab. Die
    # Dreame-eigene Kette wird nur fuer MQTT akzeptiert. Deshalb zusaetzlich
    # unverschluesselt im LAN.
    if http_port:
        await web.TCPSite(runner, "0.0.0.0", http_port).start()
        ulog.info("HTTP-Upload auf :%d", http_port)

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
    api_cert_opt = str(opts.get("api_cert") or "").strip()
    api_key_opt = str(opts.get("api_key") or "").strip()
    if api_cert_opt or api_key_opt:
        api_cert = resolve_material(api_cert_opt, cert, data_dir, "api_chain.pem")
        api_key = resolve_material(api_key_opt, key, data_dir, "api.key")
    else:
        api_cert, api_key, api_ca = ensure_api_cert(data_dir, region)
        log.info("API-Zertifikat automatisch erzeugt: %s (CA: %s)", api_cert, api_ca)
        for path in export_ca(data_dir, Path("/share")):
            log.info("CA fuer die Integration liegt unter %s", path)
        log.info(
            "Tasshack-Integration >= 2.0.3 prueft gegen certifi, nicht gegen den "
            "System-Trust-Store. Einmalig http://<HA-IP>:19980/install-bridge.sh "
            "ausfuehren und die Integration 'Dreame Local CA' hinzufuegen; "
            "Fallback: install-ca.sh."
        )
    broker_port = int(opts.get("broker_port") or 19973)
    web_port = int(opts.get("web_port") or 8099)
    upload_port = int(opts.get("upload_port") or 8443)
    upload_http_port = int(opts.get("upload_http_port") or 19980)
    upload_scheme = str(opts.get("upload_scheme") or "http").strip().lower()
    api_port = int(opts.get("api_port") or 13267)
    lan_ip = str(opts.get("lan_ip") or "")
    # Optionaler Hostname fuer die Upload-URLs (statt der LAN-IP). Manche
    # Roboter-Firmware akzeptiert keine IP-basierten Presigned-URLs.
    upload_host = str(opts.get("upload_host") or "").strip() or lan_ip
    if upload_scheme == "https":
        upload_base = f"https://{upload_host}:{upload_port}" if upload_host else ""
    else:
        upload_base = f"http://{upload_host}:{upload_http_port}" if upload_host else ""

    # Auto-Provisioning: DID/UID/Modell kommen aus dem MQTT-CONNECT bzw. dev_start.
    if not did:
        did = "unknown"

    device = Device(did, uid, model, region, publish=None, upload_base=upload_base, data_dir=data_dir)  # type: ignore[arg-type]

    # Map-ID der gespeicherten Karte (24) ermitteln. Die Live-P-Frames des
    # Roboters tragen eine temporaere Map-ID (z.B. 5); die Integration
    # verwirft sie dann. Beim Weiterleiten an die Integration wird nur die
    # Map-ID auf die gespeicherte Karte umgeschrieben, Frame-ID und Position
    # bleiben die des Live-Frames.
    def _saved_map_id() -> int:
        root = device.upload_root()
        try:
            frame = (root / "9.frame").read_text().strip()
            text = frame.replace("_", "/").replace("-", "+")
            raw = zlib.decompress(base64.b64decode(text + "=" * (-len(text) % 4)))
            return int.from_bytes(raw[0:2], "little")
        except Exception:
            pass
        try:
            info = json.loads((root / "9").read_text())
            for entry in info.get("mapstr") or []:
                blob = entry.get("map") or ""
                text = blob.replace("_", "/").replace("-", "+")
                raw = zlib.decompress(base64.b64decode(text + "=" * (-len(text) % 4)))
                return int.from_bytes(raw[0:2], "little")
        except Exception:
            pass
        return 0

    # Erst bei Bedarf ermitteln: DID/UID stehen oft erst nach CONNECT bzw.
    # dev_start fest. Gefundene ID merken, sonst beim naechsten Frame erneut.
    saved_map_id = _saved_map_id()

    def map_transform(topic: str, payload: bytes) -> bytes:
        nonlocal saved_map_id
        if "/status/" not in topic:
            return payload
        if not saved_map_id:
            saved_map_id = _saved_map_id()
        if not saved_map_id:
            return payload
        try:
            msg = json.loads(payload)
            data = msg.get("data") or {}
            if data.get("method") != "properties_changed":
                return payload
            changed = False
            for param in data.get("params") or []:
                if param.get("siid") != 6 or param.get("piid") != 1:
                    continue
                value = param.get("value")
                if not isinstance(value, str) or not value:
                    continue
                text = value.replace("_", "/").replace("-", "+")
                raw = bytearray(zlib.decompress(base64.b64decode(text + "=" * (-len(text) % 4))))
                if len(raw) < 27:
                    continue
                # Pfadsegment (tr) aus dem Live-Frame sammeln. Der I-Frame
                # (Map 24) enthaelt keinen Pfad; ohne diese Sammlung wuerde
                # die Action-Antwort die gefahrene Spur immer wieder leeren.
                lw = int.from_bytes(raw[19:21], "little")
                lh = int.from_bytes(raw[21:23], "little")
                try:
                    linfo = json.loads(bytes(raw[27 + lw * lh:]).decode("utf8"))
                    tr = linfo.get("tr")
                    if isinstance(tr, str) and tr and not device.map_path.endswith(tr):
                        device.map_path += tr
                        if len(device.map_path) > 30000:
                            device.map_path = device.map_path[-30000:]
                        try:
                            (data_dir / "map_path.txt").write_text(device.map_path)
                        except OSError:
                            pass
                except Exception:
                    pass
                raw[0:2] = saved_map_id.to_bytes(2, "little")
                param["value"] = base64.b64encode(zlib.compress(bytes(raw), 9)).decode("ascii")
                changed = True
            return json.dumps(msg, separators=(",", ":")).encode() if changed else payload
        except Exception:
            return payload

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
        transform=map_transform,
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
        api_cert,
        api_key,
        data_dir,
        public_host=lan_ip,
        mac=str(opts.get("mac") or ""),
    )

    async def safe_upload() -> None:
        try:
            await upload_server(
                device, upload_port, cert, key, data_dir, lan_ip=lan_ip, http_port=upload_http_port
            )
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
