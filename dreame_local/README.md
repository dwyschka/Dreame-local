# Dreame Local Cloud

Lokaler Cloud-Ersatz für Dreame-Roboter. Der Roboter verbindet sich mit
diesem Add-on statt mit der Dreame-Cloud; Home Assistant steuert ihn per
MQTT-Discovery — ohne Internet, ohne Dreame-App.

## Installation

1. Einstellungen → Add-ons → Add-on-Store → ⋮ → **Repositories**
   → `https://github.com/dwyschka/Dreame-local` hinzufügen.
2. „Dreame Local Cloud" installieren und starten.
3. DNS-Rewrite anlegen (z. B. AdGuard Home → DNS rewrites):

   ```
   *.mt.eu.iot.dreame.tech  ->  <IP des HA-Hosts>
   ```

   Ohne Wildcard-Unterstützung den exakten Namen eintragen
   (`{shard}.mt.{region}.iot.dreame.tech`, z. B.
   `10000.mt.eu.iot.dreame.tech`).

   **Nicht** umleiten: `eu.iot.dreame.tech`, `dreame-eu.iot.dreame.tech`,
   `oss.iot.dreame.tech`.

4. Roboter stromlos machen und wieder einschalten. Nach ~1 Minute
   erscheint er in Home Assistant als Gerät „Dreame".

## Konfiguration

```yaml
device_did: ""                 # leer = automatisch
device_uid: ""                 # leer = automatisch
device_model: "dreame.vacuum.r2469a"
region: "eu"
device_name: "Dreame"
mqtt_host: "core-mosquitto"
mqtt_port: 1883
mqtt_username: ""
mqtt_password: ""
discovery_prefix: "homeassistant"
lan_ip: "10.10.48.10"          # IP des HA-Hosts für Karten-Uploads
broker_port: 19973
web_port: 8099
upload_port: 8443
log_level: "info"
```

## Entitäten

- **Vacuum**: Start, Stop, Pause, Zur Basis, Finden, Akku
- **Sensoren**: Batterie, Status, Fehler, Fläche, Reinigungszeit,
  Haupt-/Seitenbürste, Filter, Sensor, Gesamtwerte
- **Selects**: Saugstufe, Wassermenge, Modus
- **Buttons**: Finden, Absaugen, Mopp waschen

## Kompatibel zur Tasshack-Integration

Das Add-on emuliert zusätzlich die Dreame-Cloud-API auf Port **13267**
(`/dreame-auth/oauth/token`, `device/listV2`, `device/info`, `devOTCInfo`,
`sendCommand`, `iotfile/getDownloadUrl`, `file-bridge/...`). Zeigt
`eu.iot.dreame.tech` per DNS auf den HA-Host, läuft die bestehende
**Dreame-Vacuum-Integration (HACS)** unverändert dagegen – inklusive
Karten-Cards. Die Integration bekommt `bindDomain = <lan_ip>:19973` und
verbindet sich direkt mit dem lokalen Broker.

Für diesen Modus zusätzlich umleiten:

```
eu.iot.dreame.tech  ->  <IP des HA-Hosts>
```

und im Add-on `mqtt_host: ""` setzen, wenn keine doppelten
Discovery-Entitäten entstehen sollen.

## Hinweise

- Während der lokale Broker läuft, ist der Roboter in der Dreame-App
  offline (kein Fernzugriff, kein OTA über die App). Zurück: DNS-Rewrite
  löschen, Roboter neu starten.
- Karten-Uploads werden unter `/data/uploads` gespeichert, aber noch
  nicht gerendert.
- Nur im LAN betreiben; der Broker akzeptiert jede Authentifizierung.
- Vollständige Anleitung, Fehlerbehebung und Hintergründe:
  <https://github.com/dwyschka/Dreame-local>
