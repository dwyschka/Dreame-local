#!/bin/sh
# Startet den Capture-Proxy fuer den Roboter.
#
# Voraussetzung: DNS-Rewrite in AdGuard Home
#   *.iot.dreame.tech   -> 10.10.48.124
#   *.dreame.tech       -> 10.10.48.124
# und der Roboter verbindet sich danach auf Port 19973 (MQTT) bzw. 13267 (API).
#
# Upstream-IPs: bewusst als IP, weil der Mac selbst den AdGuard-Rewrite
# benutzt und sonst in eine Schleife laufen wuerde.
#
#   ./run_capture.sh                 # Standard: EU-Broker + API
#   BROKER=47.91.92.111:19973 ./run_capture.sh
set -eu
cd "$(dirname "$0")"

BROKER="${BROKER:-47.91.92.111:19973}"   # 10000.mt.eu.iot.dreame.tech:19973
API="${API:-47.254.176.95:13267}"        # eu.iot.dreame.tech:13267

PORT_BROKER="${BROKER##*:}"
PORT_API="${API##*:}"

exec mitmdump \
  --set confdir="$PWD/.conf" \
  --mode "reverse:tls://${BROKER}@${PORT_BROKER}" \
  --mode "reverse:https://${API}@${PORT_API}" \
  --certs "*=$PWD/certs/dreame_server_chain.pem" \
  --set connection_strategy=lazy \
  --set ssl_insecure=true \
  --set keep_host_header=true \
  -s addons/mqtt_dump.py
