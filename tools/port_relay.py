#!/usr/bin/env python3
"""
Port-Range-Relay: nimmt Verbindungen auf einem Bereich an und schiebt sie
an den Capture-Proxy (mitmproxy) weiter. Damit muss der MQTT-Port des
Roboters (bindDomain) nicht vorher bekannt sein.

    sudo ./port_relay.py 19000 21000            # -> 127.0.0.1:19973
    ./port_relay.py 19000 21000 --target 19973

Jeder Treffer wird geloggt (Port + Peer), damit wir den echten Port sehen.
"""
from __future__ import annotations

import argparse
import asyncio
import socket
import sys
import time


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, asyncio.IncompleteReadError):
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def handle(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter, target_port: int, port: int
) -> None:
    peer = writer.get_extra_info("peername")
    print(f"[relay] {time.strftime('%H:%M:%S')} port {port} <- {peer}", flush=True)
    try:
        up_r, up_w = await asyncio.open_connection("127.0.0.1", target_port)
    except OSError as e:
        print(f"[relay] upstream {target_port} nicht erreichbar: {e}", flush=True)
        writer.close()
        return
    await asyncio.gather(pipe(reader, up_w), pipe(up_r, writer))


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("start", type=int)
    ap.add_argument("end", type=int)
    ap.add_argument("--target", type=int, default=19973)
    ap.add_argument("--bind", default="0.0.0.0")
    ap.add_argument("--exclude", type=int, nargs="*", default=[])
    a = ap.parse_args()

    servers = []
    skipped = []
    for port in range(a.start, a.end + 1):
        if port in a.exclude:
            continue
        try:
            srv = await asyncio.start_server(
                lambda r, w, p=port: handle(r, w, a.target, p),
                host=a.bind,
                port=port,
                reuse_address=True,
            )
            servers.append(srv)
        except OSError as e:
            skipped.append((port, e.errno))

    print(f"[relay] {len(servers)} Ports {a.start}-{a.end} -> 127.0.0.1:{a.target}")
    if skipped:
        print(f"[relay] {len(skipped)} belegt/übersprungen: {skipped[:8]}…")
    await asyncio.gather(*(s.serve_forever() for s in servers))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        pass
