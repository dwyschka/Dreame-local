#!/usr/bin/env bash
# Installiert die API-CA des Add-ons in die certifi-Datei des HA-Core-
# Containers. Die Tasshack-Integration prueft TLS mit einem eigenen Stack
# gegen certifi; der System-Trust-Store (update-ca-certificates) wird dabei
# ignoriert.
#
# Ausfuehren auf dem HA-OS-Host bzw. im Terminal/SSH-Add-on mit
# deaktiviertem Protection-Modus. Das Skript wird vom Add-on ausgeliefert:
#
#   curl -fsSL http://<HA-IP>:19980/install-ca.sh -o /tmp/install-ca.sh
#   bash /tmp/install-ca.sh [/share/dreame-local-ca.pem]
#
# Das Add-on exportiert die CA beim Start nach /share. Danach HA Core neu
# starten (ha core restart), damit die Integration den neuen Trust-Store
# aufbaut. Nach jedem Core-Update erneut ausfuehren.
set -euo pipefail

CONTAINER="${CONTAINER:-homeassistant}"
CA_FILE="${1:-${CA_FILE:-/share/dreame-local-ca.pem}}"
API_HOST="${API_HOST:-eu.iot.dreame.tech}"
API_CONNECT_HOST="${API_CONNECT_HOST:-$API_HOST}"
API_PORT="${API_PORT:-13267}"

if [[ ! -f "$CA_FILE" ]]; then
    echo "CA nicht gefunden: $CA_FILE" >&2
    echo "Add-on einmal starten (exportiert nach /share) oder Pfad als Argument angeben." >&2
    exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
    echo "docker nicht gefunden – im Terminal/SSH-Add-on Protection deaktivieren." >&2
    exit 1
fi
if ! docker inspect "$CONTAINER" >/dev/null 2>&1; then
    echo "Container '$CONTAINER' nicht gefunden (CONTAINER=... setzen)." >&2
    exit 1
fi

CERTIFI="$(docker exec "$CONTAINER" python3 -c 'import certifi; print(certifi.where())')"
docker cp "$CA_FILE" "$CONTAINER:/tmp/dreame-local-ca.pem"

docker exec -i "$CONTAINER" python3 - "$CERTIFI" <<'PY'
import pathlib
import shutil
import sys

ca = pathlib.Path("/tmp/dreame-local-ca.pem").read_bytes().strip()
target = pathlib.Path(sys.argv[1])
data = target.read_bytes()

if ca in data:
    print(f"CA bereits vorhanden: {target}")
else:
    backup = target.with_name(target.name + ".bak")
    if not backup.exists():
        shutil.copy2(target, backup)
    with target.open("ab") as f:
        f.write(b"\n" + ca + b"\n")
    print(f"CA angehaengt: {target}")
    print(f"Backup: {backup}")
PY

docker exec -i "$CONTAINER" python3 - "$CERTIFI" "$API_HOST" "$API_PORT" "$API_CONNECT_HOST" <<'PY'
import socket
import ssl
import sys

cafile, host, port, connect_host = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
ctx = ssl.create_default_context(cafile=cafile)
print(f"certifi: {cafile} ({len(ctx.get_ca_certs())} CAs)")

try:
    with socket.create_connection((connect_host, port), timeout=5) as raw:
        with ctx.wrap_socket(raw, server_hostname=host) as tls:
            issuer = dict(x[0] for x in tls.getpeercert()["issuer"])
            subject = dict(x[0] for x in tls.getpeercert()["subject"])
            print(f"TLS OK: {host}:{port} {tls.version()} "
                  f"subject={subject.get('commonName')} issuer={issuer.get('commonName')}")
            if issuer.get("commonName") != "Dreame Local CA":
                print("WARNUNG: Nicht das lokale Add-on-Zertifikat. DNS-Rewrite fuer "
                      f"{host} pruefen oder API_HOST auf die HA-IP setzen.", file=sys.stderr)
except Exception as exc:
    print(f"TLS-Pruefung fehlgeschlagen: {exc}", file=sys.stderr)
    sys.exit(1)
PY

echo
echo "Fertig. Jetzt HA Core neu starten: ha core restart"
echo "Danach die Integration neu einrichten (Dreame Home, Region eu, beliebige Zugangsdaten)."
