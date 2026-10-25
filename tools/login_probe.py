#!/usr/bin/env python3
"""
Login gegen die Dreame-Cloud und Ausgabe der Geraete-Metadaten.

Zweck: `bindDomain` (MQTT-Host:Port) und `did`/`model` ermitteln, ohne
die Cloud-Zugangsdaten an Dritte weiterzugeben. Das Skript ist eine
Minimal-Reimplementierung des Login-Flows aus der Dreame-App
(Nachbau der API, siehe FINDINGS.md).

    ./login_probe.py --user mail@example.com --password '...'
    ./login_probe.py --refresh-token <token>

Gibt NICHT den Access-Token aus (nur Laenge).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
import time
from urllib.parse import quote

import requests

UA = "Dreame_Smarthome/2.1.9 (iPhone; iOS 18.4.1; Scale/3.00)"
BASIC = "ZHJlYW1lX2FwcHYxOkFQXmR2QHpAU1FZVnhOODg="
SALT = "RAylYC%fmSKp7%Tq"
CID = "EETjszu*XI5znHsI"          # Client-ID, dient auch als AES-Key
APPVER = "102060300"
TENANT = "000000"

SESSION = requests.Session()
SESSION.verify = True


def url(country: str) -> str:
    return f"https://{country}.iot.dreame.tech:13267"


def headers(token: str | None = None, region: str | None = None, ccode: str = "de", lang: str = "de"):
    h = {
        "User-Agent": UA,
        "dreame-meta": f"cv=a_{APPVER}",
        "accept-encoding": "gzip",
        "tenant-id": TENANT,
        "content-type": "application/json",
    }
    if token:
        h["authorization"] = f"Bearer {token}"
    if region:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        raw = f"{region}|{lang}|{ccode}".encode()
        raw += b" " * (-len(raw) % 16)
        enc = Cipher(algorithms.AES(CID.encode()), modes.ECB()).encryptor()
        h["dreame-rlc"] = base64.b64encode(enc.update(raw) + enc.finalize()).decode()
    return h


def signed(params: dict) -> dict:
    """sign = md5(<sorted kv-join><ms><client_id>)"""
    parts = []
    for k in sorted(params):
        v = params[k]
        if isinstance(v, bool):
            parts.append(f"{k}={'true' if v else 'false'}")
        elif isinstance(v, (dict, list)):
            parts.append(f"{k}={json.dumps(v, sort_keys=True, separators=(',', ':'), ensure_ascii=False)}")
        elif v is None:
            parts.append(f"{k}=null")
        else:
            parts.append(f"{k}={v}")
    ms = int(time.time() * 1000)
    base = "&".join(parts) + str(ms) + CID
    out = dict(params)
    out["sign"] = hashlib.md5(base.encode()).hexdigest()
    out["timestamp"] = ms
    return out


def login(country: str, user: str, password: str | None = None, refresh: str | None = None):
    if refresh:
        body = f"grant_type=refresh_token&scope=all&platform=ANDROID&type=account&refresh_token={refresh}"
    else:
        pw = hashlib.md5((password + SALT).encode()).hexdigest()
        body = (
            "grant_type=password&scope=all&platform=ANDROID&type=account"
            f"&username={quote(user, safe='')}&password={pw}&country={country}&lang=de"
        )
    r = SESSION.post(
        f"{url(country)}/dreame-auth/oauth/token",
        headers={
            "User-Agent": UA,
            "dreame-meta": f"cv=a_{APPVER}",
            "tenant-id": TENANT,
            "authorization": f"Basic {BASIC}",
            "content-type": "application/x-www-form-urlencoded",
        },
        data=body,
        timeout=15,
    )
    print(f"[login] HTTP {r.status_code}")
    if r.status_code != 200:
        print(r.text[:500])
        return None
    return r.json()


def api(country, path, token, region, payload: dict | None = None):
    body = json.dumps(signed(payload), separators=(",", ":")) if payload is not None else None
    r = SESSION.post(
        f"{url(country)}/{path}", headers=headers(token, region), data=body, timeout=15
    )
    return r.status_code, (r.json() if r.text[:1] in "{[" else r.text[:300])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", default="")
    ap.add_argument("--password", default="")
    ap.add_argument("--refresh-token", default="")
    ap.add_argument("--country", default="de")
    a = ap.parse_args()

    data = login(a.country, a.user, a.password, a.refresh_token or None)
    if not data:
        return 1
    token = data.get("access_token")
    region = data.get("region") or ""
    print(f"[login] ok, region={region!r} tenant={data.get('tenant_id')!r} "
          f"access_token_len={len(token or '')} refresh_token_len={len(data.get('refresh_token') or '')}")

    st, dev = api(a.country, "dreame-user-iot/iotuserbind/device/listV2", token, region)
    print(f"[devices] HTTP {st}")
    if st != 200 or not isinstance(dev, dict) or dev.get("code") != 0:
        print(json.dumps(dev, indent=2)[:1500] if isinstance(dev, dict) else dev)
        return 1

    recs = dev["data"]["page"]["records"]
    print(f"[devices] {len(recs)} gefunden")
    for d in recs:
        print("\n--- Geraet")
        for k in ("did", "model", "masterUid", "bindDomain", "mac", "name", "displayName"):
            if k in d:
                print(f"  {k:12} = {d[k]!r}")
        prop = d.get("property")
        if prop:
            try:
                prop = json.loads(prop)
            except Exception:
                pass
            print(f"  property     = {json.dumps(prop)[:300]}")

        info = api(
            a.country,
            "dreame-user-iot/iotuserbind/device/info",
            token,
            region,
            {"did": d["did"]},
        )
        if info[0] == 200 and isinstance(info[1], dict) and info[1].get("code") == 0:
            i = info[1]["data"]
            print(f"  deviceInfo   = {json.dumps({k: i.get(k) for k in ('did','model','masterUid','bindDomain','property')})[:400]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
