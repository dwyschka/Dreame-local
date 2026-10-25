#!/usr/bin/env python3
"""
Minimaler lokaler MQTT-Broker als „Cloud-Ersatz" fuer den Dreame-Roboter.

* TLS mit dem eMudhra-Leaf (fullchain: Leaf + Intermediate)
* akzeptiert jede Authentifizierung (Username/Passwort/client_id egal)
* beantwortet CONNECT/SUBSCRIBE/PING, routet PUBLISH nach Topic-Filter
* protokolliert alles nach capture/broker.log (JSONL)
* Kommandos einspeisen:  echo '<topic>\t<payload>' > /tmp/dreame_cmd

Start (Port 19973 muss frei sein, also mitmproxy vorher stoppen):

    ./local_broker.py --port 19973 \
        --cert certs/leaf_EM_DV_TLS_CA_-_G3B__sectigo.pem \
        --key  certs/leaf_EM_DV_TLS_CA_-_G3B__sectigo.key
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import ssl
import struct
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOG = HERE / "capture" / "broker.log"
FIFO = "/tmp/dreame_cmd"


def enc_str(s: str) -> bytes:
    b = s.encode()
    return struct.pack("!H", len(b)) + b


def enc_len(n: int) -> bytes:
    out = b""
    while True:
        d = n % 128
        n //= 128
        out += bytes([d | (0x80 if n else 0)])
        if not n:
            return out


def pkt(typ: int, flags: int, body: bytes) -> bytes:
    return bytes([(typ << 4) | flags]) + enc_len(len(body)) + body


def log(entry: dict) -> None:
    entry["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(json.dumps(entry, ensure_ascii=False)[:800], flush=True)


def topic_matches(flt: str, topic: str) -> bool:
    ft, tt = flt.split("/"), topic.split("/")
    i = 0
    for i, part in enumerate(ft):
        if part == "#":
            return True
        if i >= len(tt):
            return False
        if part != "+" and part != tt[i]:
            return False
    return len(ft) == len(tt)


class Broker:
    def __init__(self, cert: str, key: str) -> None:
        self.ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.ctx.load_cert_chain(cert, key)
        # alte Clients zulassen
        try:
            self.ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            self.ctx.set_ciphers("ALL:@SECLEVEL=0")
        except Exception:
            pass
        self.ctx.verify_mode = ssl.CERT_OPTIONAL
        self.ctx.check_hostname = False
        self.clients: dict[str, "Client"] = {}
        self.subs: dict[str, set[str]] = {}

    async def start(self, port: int) -> None:
        srv = await asyncio.start_server(self.handle, "0.0.0.0", port, ssl=self.ctx)
        print(f"[broker] lauscht auf :{port} (TLS)", flush=True)
        self._fifo_task = asyncio.create_task(self.fifo_task())
        async with srv:
            await srv.serve_forever()

    async def fifo_task(self) -> None:
        try:
            os.unlink(FIFO)
        except FileNotFoundError:
            pass
        os.mkfifo(FIFO)
        loop = asyncio.get_running_loop()
        while True:
            line = await loop.run_in_executor(None, lambda: open(FIFO).readline())
            if not line:
                continue
            if "\t" not in line:
                print("[broker] cmd braucht <topic>\\t<payload>", flush=True)
                continue
            topic, payload = line.rstrip("\n").split("\t", 1)
            await self.publish(topic, payload.encode())

    async def on_publish(self, client: "Client", topic: str, payload: bytes) -> None:
        """Antwortet auf Query-Topics, die sonst die Cloud beantwortet."""
        did = topic.split("/")[2] if topic.startswith("/query/") and len(topic.split("/")) > 2 else None
        if did:
            try:
                msg = json.loads(payload)
            except Exception:
                msg = {}
            data = msg.get("data") or {}
            method = data.get("method")
            mid = msg.get("id", data.get("id"))
            if method == "local.query_time":
                await self.publish(
                    f"/result/{did}/",
                    json.dumps({"id": mid, "method": "local.time", "params": int(time.time())}).encode(),
                )
                return
            if isinstance(method, str) and method.startswith("_sync."):
                log({"event": "sync_request", "method": method, "params": data.get("params")})
                await self.publish(
                    f"/result/{did}/",
                    json.dumps({"id": mid, "result": {"ok": False}}).encode(),
                )
                return
        await self.publish(topic, payload)

    async def publish(self, topic: str, payload: bytes) -> None:
        n = 0
        for cid, cl in list(self.clients.items()):
            if any(topic_matches(f, topic) for f in cl.filters):
                cl.w.write(pkt(3, 0, enc_str(topic) + payload))
                await cl.w.drain()
                n += 1
        log({"dir": "out", "topic": topic, "payload": payload.decode("utf-8", "replace"), "to": n})

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        cl = Client(reader, writer, self)
        try:
            await cl.run()
        except (ConnectionError, asyncio.IncompleteReadError, ssl.SSLError) as e:
            log({"event": "error", "peer": str(peer), "error": repr(e)})
        finally:
            self.clients.pop(cl.client_id or "", None)
            writer.close()
            log({"event": "disconnect", "peer": str(peer), "client_id": cl.client_id})


class Client:
    def __init__(self, reader, writer, broker: Broker) -> None:
        self.r = reader
        self.w = writer
        self.b = broker
        self.client_id: str | None = None
        self.filters: list[str] = []

    async def read_packet(self):
        h = await self.r.readexactly(1)
        typ, flags = h[0] >> 4, h[0] & 0x0F
        mult, rl = 1, 0
        while True:
            d = await self.r.readexactly(1)
            rl += (d[0] & 0x7F) * mult
            mult *= 128
            if not d[0] & 0x80:
                break
        body = await self.r.readexactly(rl) if rl else b""
        return typ, flags, body

    async def run(self) -> None:
        while True:
            typ, flags, body = await self.read_packet()
            if typ == 1:  # CONNECT
                p = 0
                ln = int.from_bytes(body[0:2], "big")
                proto = body[2 : 2 + ln].decode(errors="replace")
                p = 2 + ln
                level, cflags = body[p], body[p + 1]
                p += 4
                ln = int.from_bytes(body[p : p + 2], "big")
                self.client_id = body[p + 2 : p + 2 + ln].decode(errors="replace")
                p += 2 + ln
                user = pw = ""
                if cflags & 0x04:
                    for _ in range(2):
                        ln = int.from_bytes(body[p : p + 2], "big")
                        p += 2 + ln
                if cflags & 0x80:
                    ln = int.from_bytes(body[p : p + 2], "big")
                    user = body[p + 2 : p + 2 + ln].decode(errors="replace")
                    p += 2 + ln
                if cflags & 0x40:
                    ln = int.from_bytes(body[p : p + 2], "big")
                    pw = body[p + 2 : p + 2 + ln].decode(errors="replace")
                    p += 2 + ln
                self.b.clients[self.client_id] = self
                log(
                    {
                        "event": "connect",
                        "peer": str(self.w.get_extra_info("peername")),
                        "proto": f"{proto}{level}",
                        "client_id": self.client_id,
                        "username": user,
                        "password_len": len(pw),
                        "password_prefix": pw[:12],
                    }
                )
                self.w.write(pkt(2, 0, b"\x00\x00"))  # CONNACK ok
                await self.w.drain()
            elif typ == 8:  # SUBSCRIBE
                pid = body[0:2]
                p, granted = 2, []
                while p < len(body):
                    ln = int.from_bytes(body[p : p + 2], "big")
                    flt = body[p + 2 : p + 2 + ln].decode(errors="replace")
                    p += 2 + ln + 1
                    self.filters.append(flt)
                    granted.append(0)
                    log({"event": "subscribe", "client_id": self.client_id, "filter": flt})
                self.w.write(pkt(9, 0, pid + bytes(granted)))
                await self.w.drain()
            elif typ == 6:  # PUBREL (QoS2 Abschluss)
                self.w.write(pkt(7, 0, body[:2]))
                await self.w.drain()
            elif typ == 3:  # PUBLISH
                ln = int.from_bytes(body[0:2], "big")
                topic = body[2 : 2 + ln].decode(errors="replace")
                qos = (flags >> 1) & 3
                p = 2 + ln + (2 if qos else 0)
                payload = body[p:]
                log(
                    {
                        "event": "publish",
                        "client_id": self.client_id,
                        "topic": topic,
                        "payload": payload.decode("utf-8", "replace"),
                    }
                )
                if qos == 1:
                    self.w.write(pkt(4, 0, body[2 + ln : 4 + ln]))
                    await self.w.drain()
                elif qos == 2:
                    self.w.write(pkt(5, 0, body[2 + ln : 4 + ln]))  # PUBREC
                    await self.w.drain()
                await self.b.on_publish(self, topic, payload)
            elif typ == 12:  # PINGREQ
                self.w.write(pkt(13, 0, b""))
                await self.w.drain()
            elif typ == 14:  # DISCONNECT
                log({"event": "disconnect", "client_id": self.client_id})
                return
            elif typ == 10:  # UNSUBSCRIBE
                self.w.write(pkt(11, 0, body[0:2]))
                await self.w.drain()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=19973)
    ap.add_argument("--cert", default=str(HERE / "certs" / "leaf_EM_DV_TLS_CA_-_G3B__sectigo.pem"))
    ap.add_argument("--key", default=str(HERE / "certs" / "leaf_EM_DV_TLS_CA_-_G3B__sectigo.key"))
    a = ap.parse_args()
    try:
        asyncio.run(Broker(a.cert, a.key).start(a.port))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
