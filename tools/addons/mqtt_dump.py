"""
mitmproxy-Addon: protokolliert den kompletten TCP-Strom einer Verbindung
und dekodiert MQTT-Pakete (CONNECT, SUBSCRIBE, PUBLISH ...).

Aufruf:
    mitmdump -s mitm/addons/mqtt_dump.py --mode reverse:https://eu.iot.dreame.tech:13267@13267 \
             --certs "*=mitm/certs/mitm_leaf.pem" --set connection_strategy=lazy \
             --set confdir=mitm/.conf

Ergebnis:
    mitm/capture/<zeit>-<id>/client.bin   (Bytes Roboter -> Cloud)
    mitm/capture/<zeit>-<id>/server.bin   (Bytes Cloud -> Roboter)
    mitm/capture/<zeit>-<id>/mqtt.log     (lesbare Pakete)
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from mitmproxy import tcp

BASE = Path(__file__).resolve().parent.parent / "capture"

MQTT_NAMES = {
    1: "CONNECT",
    2: "CONNACK",
    3: "PUBLISH",
    4: "PUBACK",
    5: "PUBREC",
    6: "PUBREL",
    7: "PUBCOMP",
    8: "SUBSCRIBE",
    9: "SUBACK",
    10: "UNSUBSCRIBE",
    11: "UNSUBACK",
    12: "PINGREQ",
    13: "PINGRESP",
    14: "DISCONNECT",
}


def _str(buf: bytes, pos: int) -> tuple[str, int]:
    ln = int.from_bytes(buf[pos : pos + 2], "big")
    return buf[pos + 2 : pos + 2 + ln].decode("utf-8", "replace"), pos + 2 + ln


def parse_mqtt(buf: bytes, start: int = 0) -> tuple[list[str], int]:
    """Dekodiert so viele vollstaendige MQTT-Pakete wie moeglich."""
    out: list[str] = []
    pos = start
    while pos < len(buf):
        if len(buf) - pos < 2:
            break
        b0 = buf[pos]
        typ = b0 >> 4
        # Remaining Length (varint)
        mult, rl, i = 1, 0, pos + 1
        while i < len(buf):
            d = buf[i]
            rl += (d & 0x7F) * mult
            mult *= 128
            i += 1
            if not d & 0x80:
                break
        else:
            break
        end = i + rl
        if end > len(buf):
            break
        body = buf[i:end]
        name = MQTT_NAMES.get(typ, f"TYPE{typ}")
        detail = ""
        if typ == 1:  # CONNECT
            p = 0
            proto, p = _str(body, p)
            level = body[p]
            flags = body[p + 1]
            keepalive = int.from_bytes(body[p + 2 : p + 4], "big")
            p += 4
            cid, p = _str(body, p)
            user = pw = ""
            if flags & 0x04:  # will
                _wt, p = _str(body, p)
                _wm, p = _str(body, p)
            if flags & 0x80:
                user, p = _str(body, p)
            if flags & 0x40:
                pw, p = _str(body, p)
            detail = (
                f"proto={proto}{level} keepalive={keepalive} "
                f"client_id={cid!r} username={user!r} password={pw!r} flags=0x{flags:02x}"
            )
        elif typ == 3:  # PUBLISH
            qos = (b0 >> 1) & 0x03
            topic, p = _str(body, 0)
            if qos:
                p += 2
            payload = body[p:]
            try:
                txt = payload.decode("utf-8")
                detail = f"topic={topic!r} qos={qos} payload={txt}"
            except UnicodeDecodeError:
                detail = f"topic={topic!r} qos={qos} payload_hex={payload.hex()}"
        elif typ == 8:  # SUBSCRIBE
            pid = int.from_bytes(body[0:2], "big")
            p = 2
            topics = []
            while p < len(body):
                t, p = _str(body, p)
                p += 1
                topics.append(t)
            detail = f"packet_id={pid} topics={topics}"
        elif typ == 10:  # UNSUBSCRIBE
            pid = int.from_bytes(body[0:2], "big")
            p = 2
            topics = []
            while p < len(body):
                t, p = _str(body, p)
                topics.append(t)
            detail = f"packet_id={pid} topics={topics}"
        elif typ == 2:
            detail = f"return_code={body[1] if len(body) > 1 else '?'}"
        out.append(f"{name} len={rl} {detail}".rstrip())
        pos = end
    return out, pos


class MqttDump:
    def __init__(self) -> None:
        self.state: dict[str, dict] = {}

    # --- HTTP-API (Port 13267) mitschreiben
    def response(self, flow) -> None:
        if not flow.request:
            return
        try:
            req = flow.request.get_text(strict=False) or ""
        except Exception:
            req = ""
        try:
            res = flow.response.get_text(strict=False) or "" if flow.response else ""
        except Exception:
            res = ""
        line = (
            f"{time.strftime('%H:%M:%S')} {flow.request.method} {flow.request.pretty_url}\n"
            f"  --> {req[:4000]}\n"
            f"  <-- {flow.response.status_code if flow.response else '?'} {res[:4000]}"
        )
        d = BASE
        d.mkdir(parents=True, exist_ok=True)
        with (d / "http.log").open("a") as f:
            f.write(line + "\n")
        with (d / "http-headers.log").open("a") as f:
            f.write(
                f"{time.strftime('%H:%M:%S')} {flow.request.method} {flow.request.path}\n"
                + "\n".join(f"  {k}: {v}" for k, v in flow.request.headers.items())
                + "\n"
            )
        print("[http] " + line[:1200], flush=True)

    # --- TLS-Handshake auch dann sehen, wenn der Client unser Zertifikat ablehnt
    def tls_clienthello(self, data) -> None:
        ch = data.client_hello
        print(
            "[tls] ClientHello "
            f"sni={ch.sni!r} alpn={ch.alpn_protocols!r} "
            f"ciphers={len(ch.cipher_suites)} "
            f"extensions={[t for t, _ in ch.extensions]}"
        )

    def tls_failed_client(self, data) -> None:
        print(f"[tls] Handshake FEHLGESCHLAGEN ({data.conn.peername})")

    def _dir(self, flow: tcp.TCPFlow) -> Path:
        key = flow.id
        if key not in self.state:
            d = BASE / f"{time.strftime('%Y%m%d-%H%M%S')}-{key[:8]}"
            d.mkdir(parents=True, exist_ok=True)
            self.state[key] = {"dir": d, "c": b"", "s": b"", "cc": 0, "sc": 0, "log": []}
            print(f"[mqtt_dump] capture -> {d}")
        return self.state[key]["dir"]

    def tcp_start(self, flow: tcp.TCPFlow) -> None:
        self._dir(flow)

    def tcp_message(self, flow: tcp.TCPFlow) -> None:
        st = self.state[flow.id]
        msg = flow.messages[-1]
        side = "c" if msg.from_client else "s"
        (st["dir"] / ("client.bin" if side == "c" else "server.bin")).open("ab").write(
            msg.content
        )
        buf_key = "c" if side == "c" else "s"
        pos_key = "cc" if side == "c" else "sc"
        st[buf_key] += msg.content
        pkts, newpos = parse_mqtt(st[buf_key], st[pos_key])
        st[pos_key] = newpos
        for p in pkts:
            arrow = "-->" if side == "c" else "<--"
            line = f"{arrow} {p}"
            st["log"].append(line)
            with (st["dir"] / "mqtt.log").open("a") as f:
                f.write(line + "\n")
            print(f"[mqtt_dump] {line[:400]}")

    def tcp_end(self, flow: tcp.TCPFlow) -> None:
        st = self.state.pop(flow.id, None)
        if st:
            (st["dir"] / "summary.json").write_text(
                json.dumps(
                    {
                        "id": flow.id,
                        "client": str(flow.client_conn.peername),
                        "server": str(flow.server_conn.peername),
                        "sni": flow.server_conn.sni,
                        "packets": st["log"],
                    },
                    indent=2,
                )
            )
            print(f"[mqtt_dump] closed {flow.id}")

    def tcp_error(self, flow: tcp.TCPFlow) -> None:
        print(f"[mqtt_dump] error {flow.id}: {flow.error}")


addons = [MqttDump()]
