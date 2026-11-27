#!/usr/bin/env bash
# Lokale CA + Server-Zertifikat fuer die API (:13267) erzeugen.
# Die Tasshack-Integration prueft TLS vollstaendig; das Default-Zertifikat
# des Add-ons (CN=client, Dreame-Kette) besteht die Pruefung fuer
# <region>.iot.dreame.tech nicht. Dieses Skript erzeugt stattdessen ein
# Leaf mit passendem SAN, signiert von einer lokalen CA, die in den
# Trust-Store von Home Assistant installiert wird.
#
# Nutzung: tools/gen_local_api_cert.sh [zielverzeichnis]
# SANs anpassen: SANS="DNS:eu.iot.dreame.tech,DNS:*.iot.dreame.tech" tools/...
set -euo pipefail

OUT="${1:-api-certs}"
SANS="${SANS:-DNS:eu.iot.dreame.tech,DNS:*.iot.dreame.tech,DNS:*.mt.eu.iot.dreame.tech}"
mkdir -p "$OUT"

openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes \
    -keyout "$OUT/ca.key" -out "$OUT/ca.pem" -days 3650 \
    -subj "/CN=Dreame Local CA" 2>/dev/null

openssl req -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes \
    -keyout "$OUT/api.key" -out "$OUT/api.csr" \
    -subj "/CN=eu.iot.dreame.tech" 2>/dev/null

EXT="$(mktemp)"
trap 'rm -f "$EXT"' EXIT
printf 'subjectAltName=%s\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n' \
    "$SANS" > "$EXT"

openssl x509 -req -in "$OUT/api.csr" -CA "$OUT/ca.pem" -CAkey "$OUT/ca.key" \
    -CAcreateserial -out "$OUT/api.pem" -days 825 -extfile "$EXT" 2>/dev/null

cat "$OUT/api.pem" "$OUT/ca.pem" > "$OUT/api_chain.pem"
rm -f "$OUT/api.csr"
chmod 600 "$OUT/ca.key" "$OUT/api.key"

cat <<EOF
Erzeugt in $OUT:
  ca.pem         -> CA-Zertifikat, in den Trust-Store von Home Assistant installieren
  api_chain.pem  -> Leaf + CA (Add-on-Option api_cert)
  api.key        -> Leaf-Key (Add-on-Option api_key)

1) CA in die certifi-Datei von HA Core installieren (Terminal/SSH-Add-on,
   Protection AUS):
     curl -fsSL http://<HA-IP>:19980/install-ca.sh -o /tmp/install-ca.sh
     bash /tmp/install-ca.sh <pfad>/ca.pem
     ha core restart
   Der System-Trust-Store (update-ca-certificates) wird von der
   Tasshack-Integration ignoriert; sie prueft ausschliesslich gegen certifi.
   Nach einem Core-Update erneut ausfuehren.

2) api_chain.pem + api.key ins Add-on kopieren, z. B. nach /data/certs/
   (Samba-Share/Studio Code Server), dann in der Add-on-Konfiguration:
     api_cert: /data/certs/api_chain.pem
     api_key: /data/certs/api.key
   Alternativ die PEM-Inhalte direkt inline in api_cert/api_key eintragen.

3) Add-on neu starten, dann die Integration "Dreame Vacuum" in HA neu einrichten
   (Dreame Home, Region eu, beliebige Zugangsdaten). Im Add-on-Log muss
   "Login von ..." erscheinen.
EOF
