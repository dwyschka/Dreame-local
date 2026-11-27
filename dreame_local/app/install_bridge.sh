#!/usr/bin/env bash
# Installiert die Custom Component dreame_local_ca in /config/custom_components.
# Laeuft im Terminal/SSH-Add-on; Protection Mode kann anbleiben.
#
#   curl -fsSL http://<HA-IP>:19980/install-bridge.sh -o /tmp/install-bridge.sh
#   bash /tmp/install-bridge.sh
#
# Danach HA Core neu starten und "Dreame Local CA" einmal hinzufuegen.
set -euo pipefail

BASE_URL="__BASE_URL__"
DEST="${1:-/config/custom_components}"
NAME="dreame_local_ca"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

curl -fsSL "$BASE_URL/dreame_local_ca.tar.gz" -o "$TMP/$NAME.tar.gz"

mkdir -p "$DEST"
rm -rf "$DEST/$NAME"
tar -xzf "$TMP/$NAME.tar.gz" -C "$DEST"

test -f "$DEST/$NAME/manifest.json"
echo "Installiert: $DEST/$NAME"
echo "Jetzt HA Core neu starten und die Integration 'Dreame Local CA' hinzufuegen."
