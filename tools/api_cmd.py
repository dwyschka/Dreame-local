#!/usr/bin/env python3
"""
Schickt ein sendCommand an die (echte) Dreame-API — entweder direkt per IP
oder через den lokalen Capture-Proxy. Nutzt den bereits vorhandenen Token
aus capture/creds.txt, kein neuer Login.

    ./api_cmd.py --method get_properties --params '[{"did":"909669328","siid":14,"piid":4}]'
    ./api_cmd.py --method action --params '{"did":"909669328","siid":4,"aiid":1,"in":[]}'

Der Request geht an 127.0.0.1:13267 (Capture-Proxy), SNI/Host bleiben
eu.iot.dreame.tech. Damit sehen wir im Observer, was die Cloud auf
/msg/<uid>/ publiziert.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import ssl
import time
import urllib.request
from pathlib import Path

CID = "EETjszu*XI5znHsI"
DID = "909669328"

HERE = Path(__file__).resolve().parent


def spliced(obj, top=True) -> str:
    parts = []
    for k in sorted(obj.keys()):
        v = obj[k]
        if isinstance(v, dict):
            inner = spliced(v, False)
            parts.append(f"{k}=[{inner}]" if inner else f"{k}=]")
        elif isinstance(v, list):
            if top:
                parts.append(f"{k}={json.dumps(v, sort_keys=True, separators=(',', ':'), ensure_ascii=False)}")
        elif isinstance(v, bool):
            parts.append(f"{k}={'true' if v else 'false'}")
        elif v is None:
            parts.append(f"{k}=null")
        elif top:
            parts.append(f"{k}={v}")
        else:
            parts.append(f"{k}={json.dumps(v, ensure_ascii=False)}")
    return "&".join(parts)


def sign(params) -> dict:
    ms = int(time.time() * 1000)
    base = spliced(params) + str(ms) + CID
    out = dict(params)
    out["sign"] = hashlib.md5(base.encode()).hexdigest()
    out["timestamp"] = ms
    return out


def rlc(region="eu", lang="de", ccode="de") -> str:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    raw = f"{region}|{lang}|{ccode}".encode()
    raw += b" " * (-len(raw) % 16)
    e = Cipher(algorithms.AES(CID.encode()), modes.ECB()).encryptor()
    return base64.b64encode(e.update(raw) + e.finalize()).decode()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--method", default="get_properties")
    ap.add_argument("--params", default=f'[{{"did":"{DID}","siid":14,"piid":4}}]')
    ap.add_argument("--id", type=int, default=9001)
    ap.add_argument("--url", default="https://127.0.0.1:13267")
    ap.add_argument("--creds", default=str(HERE / "capture" / "creds.txt"))
    ap.add_argument("--api-token-file", default=str(HERE / "capture" / "api_token.txt"))
    a = ap.parse_args()

    _, user, mqtt_token = Path(a.creds).read_text().splitlines()[:3]
    try:
        api_token, captured_rlc = Path(a.api_token_file).read_text().splitlines()[:2]
    except (OSError, ValueError):
        api_token, captured_rlc = mqtt_token, ""
    data = {
        "did": DID,
        "id": a.id,
        "method": a.method,
        "params": json.loads(a.params),
    }
    body = sign({"did": DID, "id": a.id, "data": data})
    raw = json.dumps(body, separators=(",", ":")).encode()
    headers = {
        "User-Agent": "Dreame_Smarthome/2.1.9 (iPhone; iOS 18.4.1; Scale/3.00)",
        "dreame-meta": "cv=a_102060300",
        "dreame-rlc": captured_rlc or rlc(),
        "tenant-id": "000000",
        "authorization": "Basic ZHJlYW1lX2FwcHYxOkFQXmR2QHpAU1FZVnhOODg=",
        "dreame-auth": api_token,
        "content-type": "application/json",
    }
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(
        a.url + f"/dreame-iot-com-10000/device/sendCommand",
        data=raw,
        headers={**headers, "Host": "eu.iot.dreame.tech:13267"},
        method="POST",
    )
    with urllib.request.urlopen(req, context=ctx, timeout=20) as r:
        txt = r.read().decode()
        print(f"HTTP {r.status}")
        print(txt[:800])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
