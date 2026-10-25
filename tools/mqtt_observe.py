#!/usr/bin/env python3
"""
Zweiter MQTT-Client am echten Dreame-Broker: liest passiv mit, was die
Cloud an den Roboter schickt. Kein MITM noetig, nur die Zugangsdaten
(uid + JWT) aus dem App-Capture.

    ./mqtt_observe.py --host 10000.mt.eu.iot.dreame.tech --ip 47.91.92.111 \
        --uid VB847569 --did 909669328 --model dreame.vacuum.r2469a \
        --token '<JWT>'

Topics:
    /msg/<uid>/                       Kommandos Cloud -> Geraet
    /status/<did>/<uid>/<model>/#     Status Geraet -> Cloud
    /w/<did>/                         Wake/Control

Schreibt alles nach capture/mqtt-observe.log
"""
from __future__ import annotations

import argparse
import json
import socket
import ssl
import struct
import sys
import time
from pathlib import Path

LOG = Path(__file__).resolve().parent / "capture" / "mqtt-observe.log"


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


def packet(typ: int, flags: int, body: bytes) -> bytes:
    return bytes([(typ << 4) | flags]) + enc_len(len(body)) + body


def connect_pkt(client_id: str, user: str, pw: str) -> bytes:
    vh = enc_str("MQTT") + bytes([4, 0xC2]) + struct.pack("!H", 60)
    return packet(1, 0, vh + enc_str(client_id) + enc_str(user) + enc_str(pw))


def subscribe_pkt(pid: int, topics: list[str]) -> bytes:
    body = struct.pack("!H", pid)
    for t in topics:
        body += enc_str(t) + bytes([0])
    return packet(8, 2, body)


def ping_pkt() -> bytes:
    return packet(12, 0, b"")


def read_packet(sock) -> tuple[int, int, bytes] | None:
    h = sock.recv(1)
    if not h:
        return None
    typ, flags = h[0] >> 4, h[0] & 0x0F
    mult, rl = 1, 0
    while True:
        d = sock.recv(1)
        if not d:
            return None
        rl += (d[0] & 0x7F) * mult
        mult *= 128
        if not d[0] & 0x80:
            break
    body = b""
    while len(body) < rl:
        chunk = sock.recv(rl - len(body))
        if not chunk:
            return None
        body += chunk
    return typ, flags, body


def decode_publish(flags: int, body: bytes) -> tuple[str, bytes]:
    ln = int.from_bytes(body[0:2], "big")
    topic = body[2 : 2 + ln].decode()
    p = 2 + ln + (2 if (flags >> 1) & 3 else 0)
    return topic, body[p:]


def log(line: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as f:
        f.write(line + "\n")
    print(line[:600], flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--ip", required=True)
    ap.add_argument("--uid", required=True)
    ap.add_argument("--did", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--token", required=True)
    ap.add_argument("--port", type=int, default=19973)
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()

    # Der Broker nutzt eine eigene, selbstsignierte Kette (siehe FINDINGS.md)
    # -> Verifikation aus, es geht nur um passives Mitlesen.
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    raw = socket.create_connection((a.ip, a.port), 10)
    s = ctx.wrap_socket(raw, server_hostname=a.host)
    log(f"=== connect {a.host} ({a.ip}:{a.port}) {s.version()} {time.strftime('%H:%M:%S')}")

    cid = f"p_{a.uid}_observer{int(time.time()) % 100000}"
    s.sendall(connect_pkt(cid, a.uid, a.token))
    typ, _, body = read_packet(s) or (0, 0, b"")
    log(f"CONNACK rc={body[1] if len(body) > 1 else '?'}")
    if not body or body[1] != 0:
        return 1

    topics = [
        f"/msg/{a.uid}/",
        f"/status/{a.did}/{a.uid}/{a.model}/#",
        f"/w/{a.did}/",
    ]
    if a.all:
        topics.append("#")
    s.sendall(subscribe_pkt(1, topics))
    log(f"SUBSCRIBE {topics}")
    s.settimeout(1.0)
    last_ping = time.time()
    while True:
        try:
            got = read_packet(s)
        except socket.timeout:
            got = "timeout"
        if got == "timeout":
            if time.time() - last_ping > 25:
                s.sendall(ping_pkt())
                last_ping = time.time()
            continue
        if got is None:
            log("=== Verbindung beendet")
            return 0
        typ, flags, body = got
        if typ == 3:
            topic, payload = decode_publish(flags, body)
            try:
                txt = payload.decode()
                try:
                    txt = json.dumps(json.loads(txt), ensure_ascii=False)
                except json.JSONDecodeError:
                    pass
                log(f"{time.strftime('%H:%M:%S')} {topic} {txt}")
            except UnicodeDecodeError:
                log(f"{time.strftime('%H:%M:%S')} {topic} hex={payload[:200].hex()}")
        elif typ == 9:
            log(f"SUBACK codes={list(body[2:])}")
        elif typ == 2:
            log("CONNACK?")


if __name__ == "__main__":
    raise SystemExit(main())
