# Dreame Local Cloud

Lokaler Cloud-Ersatz für Dreame-Roboter. Der Roboter verbindet sich mit
diesem Add-on statt mit der Dreame-Cloud — **Home Assistant übernimmt die
Rolle der Dreame-App**.

Empfohlen: die bestehende **Dreame-Vacuum-Integration** (HACS) läuft
unverändert gegen dieses Add-on, inklusive Karte und Karten-Cards.
Optional gibt es einen schlanken MQTT-Discovery-Modus ohne HACS.

> 🇬🇧 **English installation guide:** [full guide in the repository README](https://github.com/dwyschka/Dreame-local/blob/main/README.md#english-installation-guide)

## English Installation (short)

1. In Home Assistant open **Settings → Add-ons → Add-on Store → ⋮ →
   Repositories** and add
   `https://github.com/dwyschka/Dreame-local`.
2. Install **Dreame Local Cloud**, open **Configuration**, set `lan_ip` to the
   HA host IP reachable by the robot, and start the add-on.
3. Add DNS rewrites:
   ```text
   eu.iot.dreame.tech        ->  <HA-IP>   # API for the integration
   *.mt.eu.iot.dreame.tech   ->  <HA-IP>   # MQTT for the robot
   ```
   Without wildcard support, use the exact name from `bindDomain`
   (`10000.mt.eu.iot.dreame.tech` on most robots).
4. Install **Dreame Vacuum** through HACS, add the integration, choose
   **Dreame Home**, region `eu`, username/password can be arbitrary.
5. Power-cycle the robot and wait 30–90 seconds. It should connect to the
   local add-on; the log shows `CONNECT device_<did>` and `SUBSCRIBE`.
6. Keep `mqtt_host` empty for the integration mode. Use
   `upload_host: eu.iot.dreame.tech` if the robot rejects IP-based upload
   URLs.

Ports: `19973` (MQTT), `13267` (API), `8443` (uploads), `8099` (Web UI).
Never expose them to the internet.

## Installation

1. Einstellungen → Add-ons → Add-on-Store → ⋮ → **Repositories**
   → `https://github.com/dwyschka/Dreame-local` hinzufügen.
2. „Dreame Local Cloud" installieren und starten.
3. DNS-Rewrites (AdGuard Home → DNS rewrites):

   ```
   eu.iot.dreame.tech        ->  <IP des HA-Hosts>   # API für die Integration
   *.mt.eu.iot.dreame.tech   ->  <IP des HA-Hosts>   # MQTT für den Roboter
   ```

   Ohne Wildcard-Unterstützung den exakten MQTT-Namen eintragen
   (`{shard}.mt.{region}.iot.dreame.tech`, z. B.
   `10000.mt.eu.iot.dreame.tech`).

4. Integration **Dreame Vacuum** (HACS) einrichten:
   - Konto-Typ: **Dreame Home**
   - Region: **`eu`**
   - Benutzername/Passwort: **beliebig** (lokal wird alles akzeptiert)
5. Roboter stromlos machen und wieder einschalten. Nach ~1 Minute ist er
   in Home Assistant verfügbar.

> Nur Discovery-Modus ohne Integration: dann reicht der zweite Rewrite
> (`*.mt…`), und `mqtt_host` muss auf `core-mosquitto` gesetzt werden.

## Konfiguration

```yaml
device_did: ""                 # leer = automatisch
device_uid: ""                 # leer = automatisch
device_model: "dreame.vacuum.r2469a"
region: "eu"
device_name: "Dreame"
mac: ""                        # optional (für die Integration)
mqtt_host: ""                  # leer = keine Discovery-Entitäten (empfohlen)
mqtt_port: 1883
mqtt_username: ""
mqtt_password: ""
discovery_prefix: "homeassistant"
lan_ip: "10.10.48.10"          # IP des HA-Hosts (BindDomain + Karten-URLs)
upload_host: ""                # optional: Hostname statt lan_ip, z. B. eu.iot.dreame.tech
device_ip: ""                  # optional: nur dieser Host darf sich als Roboter verbinden
broker_port: 19973
api_port: 13267
web_port: 8099
upload_port: 8443
log_level: "info"
```

## Entitäten

- **Integration (empfohlen):** Vacuum, Karte (`camera.*_map`), Räume, Zonen,
  Verbrauchsmaterial, alle Einstellungen — wie in der Dreame-App.
- **Discovery-Modus:** Vacuum, Batterie/Status/Fehler, Fläche/Zeit,
  Bürsten/Filter/Sensor, Saugstufe/Wassermenge/Modus, Buttons.

## Karten

Die ersten Map-Daten kommen nach **einer** Reinigung: Der Roboter lädt den
Kartenblob zu diesem Add-on (`/data/uploads`), die Integration holt ihn
über `getDownloadUrl` und rendert ihn.

Der Roboter fordert Upload-URLs nur selten an (etwa stündlich, nach einem
Neustart oder nach einer Kartenänderung) und merkt sie sich. Nach einem
Add-on-Update deshalb einmal den Roboter neu starten oder kurz reinigen
lassen. Diagnose: Web-UI → „Karte anfordern“, dann unter *Diagnose* die
Events `presigned_urls`, `upload` und `map_url` prüfen; die Dateien liegen
im Add-on unter `/data/uploads`.

Dashboard-Beispiele:
[docs/HA-ALS-APP.md](https://github.com/dwyschka/Dreame-local/blob/main/docs/HA-ALS-APP.md)

## Hinweise

- Die Dreame-App ist im Alltag nicht mehr nötig. Sie wird nur noch für
  Werksreset, WLAN-Wechsel und Firmware-Updates gebraucht.
- Während der lokale Broker läuft, ist der Roboter in der Dreame-App
  offline (kein Fernzugriff).
- Nur im LAN betreiben; der Broker akzeptiert jede Authentifizierung.
- Vollständige Anleitung und Fehlerbehebung:
  <https://github.com/dwyschka/Dreame-local>
