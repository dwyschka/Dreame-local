"""Minimaler MQTT-Broker (TLS) als Cloud-Ersatz fuer Dreame-Roboter.

Unterstuetzt CONNECT, SUBSCRIBE, PUBLISH (QoS 0/1/2), PING, DISCONNECT
und routet Nachrichten anhand der Topic-Filter. Authentifizierung wird
bewusst nicht geprueft (der Roboter ist der einzige Client).
"""
from __future__ import annotations

import asyncio
import logging
import ssl
import struct
from dataclasses import dataclass, field
from typing import Awaitable, Callable

log = logging.getLogger("broker")

PublishCb = Callable[[str, bytes], Awaitable[None]]
EventCb = Callable[[str, str | None], Awaitable[None]]


def _enc_str(s: str) -> bytes:
    b = s.encode()
    return struct.pack("!H", len(b)) + b


def _enc_len(n: int) -> bytes:
    out = b""
    while True:
        d = n % 128
        n //= 128
        out += bytes([d | (0x80 if n else 0)])
        if not n:
            return out


def _packet(typ: int, flags: int, body: bytes) -> bytes:
    return bytes([(typ << 4) | flags]) + _enc_len(len(body)) + body


def topic_matches(flt: str, topic: str) -> bool:
    ft, tt = flt.split("/"), topic.split("/")
    for i, part in enumerate(ft):
        if part == "#":
            return True
        if i >= len(tt):
            return False
        if part != "+" and part != tt[i]:
            return False
    return len(ft) == len(tt)


@dataclass
class Session:
    client_id: str = ""
    username: str = ""
    filters: list[str] = field(default_factory=list)
    writer: asyncio.StreamWriter | None = None
    peer: str = ""
    _pid: int = 0

    def next_pid(self) -> int:
        self._pid = (self._pid % 65534) + 1
        return self._pid


class MqttBroker:
    def __init__(
        self,
        port: int,
        cert: str,
        key: str,
        on_publish: PublishCb,
        on_connect: EventCb | None = None,
        on_disconnect: EventCb | None = None,
    ) -> None:
        self.port = port
        self.on_publish = on_publish
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect
        self.sessions: dict[str, Session] = {}
        self.ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.ctx.load_cert_chain(cert, key)
        try:
            self.ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            self.ctx.set_ciphers("ALL:@SECLEVEL=0")
        except Exception:  # pragma: no cover
            pass
        # Der Roboter schickt kein Client-Zertifikat, wir fragen auch keins ab.
        self.ctx.verify_mode = ssl.CERT_NONE

    async def start(self) -> None:
        server = await asyncio.start_server(self._handle, "0.0.0.0", self.port, ssl=self.ctx)
        log.info("MQTT-Broker lauscht auf :%d (TLS)", self.port)
        async with server:
            await server.serve_forever()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = str(writer.get_extra_info("peername"))
        sess = Session(writer=writer, peer=peer)
        log.info("Client verbunden: %s", peer)
        try:
            while True:
                typ, flags, body = await self._read(reader)
                if typ == 1:
                    self._connect(sess, body)
                    self.sessions[sess.client_id] = sess
                    writer.write(_packet(2, 0, b"\x00\x00"))
                    await writer.drain()
                    log.info("CONNECT %s user=%s von %s", sess.client_id, sess.username, peer)
                    if self.on_connect:
                        await self.on_connect(sess.client_id, sess.username or None)
                elif typ == 8:
                    pid = body[0:2]
                    p, granted = 2, []
                    while p < len(body):
                        ln = int.from_bytes(body[p : p + 2], "big")
                        flt = body[p + 2 : p + 2 + ln].decode(errors="replace")
                        p += 2 + ln + 1
                        if flt not in sess.filters:
                            sess.filters.append(flt)
                        granted.append(1)
                        log.info("SUBSCRIBE %s von %s", flt, sess.client_id)
                    writer.write(_packet(9, 0, pid + bytes(granted)))
                    await writer.drain()
                elif typ == 3:
                    ln = int.from_bytes(body[0:2], "big")
                    topic = body[2 : 2 + ln].decode(errors="replace")
                    qos = (flags >> 1) & 3
                    off = 2 + ln
                    pid = body[off : off + 2] if qos else b""
                    payload = body[off + (2 if qos else 0) :]
                    if qos == 1:
                        writer.write(_packet(4, 0, pid))
                        await writer.drain()
                    elif qos == 2:
                        writer.write(_packet(5, 0, pid))
                        await writer.drain()
                    await self.on_publish(topic, payload)
                elif typ == 6:  # PUBREL
                    writer.write(_packet(7, 0, body[:2]))
                    await writer.drain()
                elif typ == 12:  # PINGREQ
                    writer.write(_packet(13, 0, b""))
                    await writer.drain()
                elif typ == 10:  # UNSUBSCRIBE
                    writer.write(_packet(11, 0, body[0:2]))
                    await writer.drain()
                elif typ == 14:  # DISCONNECT
                    break
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        except Exception:  # pragma: no cover
            log.exception("Broker-Fehler bei %s", peer)
        finally:
            if sess.client_id and self.sessions.get(sess.client_id) is sess:
                self.sessions.pop(sess.client_id, None)
            writer.close()
            log.info("Client getrennt: %s (%s)", sess.client_id, peer)
            if self.on_disconnect:
                await self.on_disconnect(sess.client_id, sess.username or None)

    @staticmethod
    async def _read(reader: asyncio.StreamReader) -> tuple[int, int, bytes]:
        h = await reader.readexactly(1)
        typ, flags = h[0] >> 4, h[0] & 0x0F
        mult, rl = 1, 0
        while True:
            d = await reader.readexactly(1)
            rl += (d[0] & 0x7F) * mult
            mult *= 128
            if not d[0] & 0x80:
                break
        body = await reader.readexactly(rl) if rl else b""
        return typ, flags, body

    @staticmethod
    def _connect(sess: Session, body: bytes) -> None:
        ln = int.from_bytes(body[0:2], "big")
        p = 2 + ln
        flags = body[p + 1]
        p += 4
        ln = int.from_bytes(body[p : p + 2], "big")
        sess.client_id = body[p + 2 : p + 2 + ln].decode(errors="replace")
        p += 2 + ln
        if flags & 0x04:
            for _ in range(2):
                ln = int.from_bytes(body[p : p + 2], "big")
                p += 2 + ln
        if flags & 0x80:
            ln = int.from_bytes(body[p : p + 2], "big")
            sess.username = body[p + 2 : p + 2 + ln].decode(errors="replace")
            p += 2 + ln
        if flags & 0x40:
            ln = int.from_bytes(body[p : p + 2], "big")
            p += 2 + ln

    async def publish(self, topic: str, payload: bytes | str, qos: int = 1) -> int:
        if isinstance(payload, str):
            payload = payload.encode()
        sent = 0
        for sess in list(self.sessions.values()):
            if not sess.writer or not any(topic_matches(f, topic) for f in sess.filters):
                continue
            try:
                if qos:
                    sess.writer.write(
                        _packet(3, (qos << 1) & 0x06, _enc_str(topic) + struct.pack("!H", sess.next_pid()) + payload)
                    )
                else:
                    sess.writer.write(_packet(3, 0, _enc_str(topic) + payload))
                await sess.writer.drain()
                sent += 1
            except (ConnectionError, ssl.SSLError):
                pass
        return sent
