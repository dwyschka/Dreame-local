# Dreame Local Cloud

Lokaler Cloud-Ersatz für Dreame-Roboter (L10s Ultra Gen 2 & verwandte
Modelle) — als Home-Assistant-Add-on. **Home Assistant übernimmt die Rolle
der Dreame-App**: Steuerung, Status, Karte, Räume/Zonen und Einstellungen.

Der Roboter verbindet sich mit diesem Add-on statt mit der Dreame-Cloud.
Die bestehende **Dreame-Vacuum-Integration** (Tasshack) läuft unverändert
dagegen — inklusive Karten und Kartenfunktionen. Alternativ gibt es einen
schlanken MQTT-Discovery-Modus ohne HACS.

> **Status:** Steuerung, Status und API-Emulation verifiziert auf
> `dreame.vacuum.r2469a`, FW `4.3.9_1642`. Kartenblobs werden angenommen
> und ausgeliefert; die Anzeige übernimmt die Integration/Karte.

> 🇬🇧 **English installation guide:** [jump to English](#english-installation-guide)

---

## 1. Voraussetzungen

| Was | Warum |
|---|---|
| Home Assistant OS oder Supervised | Add-ons |
| HACS + Integration „Dreame Vacuum" | Entitäten, Karte, Karten-Cards (Modus B) |
| Mosquitto + MQTT-Integration | nur für den optionalen Discovery-Modus A |
| AdGuard Home, Pi-hole oder Router mit DNS-Einträgen | Der Roboter muss hierher finden |
| Roboter im WLAN, mit der Dreame-App gekoppelt | Die Kopplung bleibt bestehen |
| Zertifikate in `dreame_local/app/certs/` | Liegen im Repo (aus der Dreame-App) |

---

## 2. Zwei Betriebsmodi

| Modus | Was du bekommst | Voraussetzung |
|---|---|---|
| **B – Dreame-API (empfohlen)** | Die bestehende **Tasshack-Integration** + Karten-Cards laufen unverändert gegen den lokalen Server. Home Assistant ersetzt die Dreame-App. | DNS-Rewrite für `eu.iot.dreame.tech` **und** `*.mt…` |
| A – MQTT-Discovery | Eigene, schlanke HA-Entitäten (Vacuum, Sensoren, Selects, Buttons), kein HACS nötig | Nur DNS-Rewrite für `*.mt…` |

Beides gleichzeitig geht, erzeugt aber doppelte Entitäten. Empfehlung:
**B**. Die komplette Anleitung inkl. Dashboard-Cards steht in
[`docs/HA-ALS-APP.md`](docs/HA-ALS-APP.md).

### Modus B: Tasshack-Integration lokal

1. Add-on läuft (Broker 19973 + API 13267).
2. DNS-Rewrites:

   ```
   eu.iot.dreame.tech          ->  <HA-IP>
   *.mt.eu.iot.dreame.tech     ->  <HA-IP>
   ```

3. In HA die Integration **Dreame Vacuum** (HACS) einrichten:
   - Konto-Typ: **Dreame Home**
   - Land/Region: `eu`
   - Benutzername/Passwort: **beliebig** (der lokale Server akzeptiert alles)
4. Die Integration bekommt von uns `bindDomain = <HA-IP>:19973` und
   verbindet sich direkt mit dem lokalen Broker. Steuerung, Status und
   Karten funktionieren wie gewohnt; die Karten-Cards bleiben kompatibel,
   weil die Integration den Kartenblob selbst dekodiert.
5. Im Add-on `mqtt_host: ""` setzen, wenn du keine doppelten
   Discovery-Entitäten willst.

> Die Karte erscheint, sobald der Roboter nach einer Reinigung einen
> Kartenblob hochgeladen hat (landet unter `/data/uploads`, wird über
> `getDownloadUrl` ausgeliefert). Ohne Upload bleibt die Karte leer.

---

## 3. Installation (über das Add-on-Repository)

1. **Repository hinzufügen**
   - Einstellungen → Add-ons → Add-on-Store
   - oben rechts ⋮ → **Repositories**
   - `https://github.com/dwyschka/Dreame-local` eintragen → **Hinzufügen**

2. **Add-on installieren**
   - Store neu laden (Seite aktualisieren)
   - „Dreame Local Cloud" öffnen → **Installieren** (baut das Image lokal)

3. **Konfigurieren** (Tab „Konfiguration"):

   ```yaml
   device_did: ""                        # leer = automatisch beim Verbinden
   device_uid: ""                        # leer = automatisch (dev_start)
   device_model: "dreame.vacuum.r2469a"
   region: "eu"
   device_name: "Dreame"
   mqtt_host: ""                         # leer = keine Discovery-Duplikate (Modus B)
   mqtt_port: 1883
   mqtt_username: ""
   mqtt_password: ""
   discovery_prefix: "homeassistant"
   lan_ip: "10.10.48.10"                 # IP des HA-Hosts (BindDomain + Upload-URLs)
   upload_host: ""                       # optional: Hostname statt lan_ip, z. B. eu.iot.dreame.tech
   device_ip: ""                         # optional: nur dieser Host darf sich als Roboter verbinden
   mac: ""                               # optional, für die Integration
   broker_port: 19973
   api_port: 13267
   web_port: 8099
   upload_port: 8443
   log_level: "info"
   ```

   `lan_ip` ist die IP, unter der der Roboter den HA-Host erreicht
   (bei HA OS meist die LAN-IP der VM/des Hosts).

   `upload_host` überschreibt nur den Host in den Upload-URLs (Port bleibt
   `upload_port`). Manche Firmware akzeptiert keine IP-basierten
   Presigned-URLs; dann `eu.iot.dreame.tech` eintragen (DNS-Rewrite auf den
   HA-Host). Die Karten-Download-URLs nutzen weiterhin den Host, über den die
   Integration die API aufruft.

   `device_ip` ist eine optionale Absicherung: Ist sie gesetzt, werden
   MQTT-Clients mit der Kennung `device_<did>` nur von dieser IP akzeptiert.
   Das verhindert, dass ein Testclient mit den Roboter-Zugangsdaten die
   echte Roboter-Session besetzt. Der Broker wirft außerdem bei gleicher
   Client-ID die alte Session aktiv raus (MQTT-Takeover).

4. **Starten** → Logs beobachten:
   ```
   MQTT-Broker lauscht auf :19973 (TLS)
   Web-UI auf :8099
   HTTPS-Upload auf :8443
   ```

> Manuell (ohne Repository): Ordner `dreame_local` nach
> `/addons/dreame_local/` kopieren, dann Store neu laden.

---

## 4. DNS-Rewrite (der wichtigste Schritt)

Der Roboter fragt `{shard}.mt.{region}.iot.dreame.tech` ab (bei mir
`10000.mt.eu.iot.dreame.tech`). Diese Namen müssen auf die HA-IP zeigen.

**AdGuard Home** → Filter → **DNS rewrites** → Eintrag hinzufügen:

```
*.mt.eu.iot.dreame.tech      ->  10.10.48.10
```

**Pi-hole** → Local DNS → DNS Records: gleicher Eintrag.
**Fritzbox/Router** ohne Wildcard: exakt `10000.mt.eu.iot.dreame.tech`
eintragen (den Shard-Namen bekommst du aus der Cloud, Feld `bindDomain`).

> ⚠️ Für Modus B muss `eu.iot.dreame.tech` auf den HA-Host zeigen (API und
> Karten-Downloads). **Nicht** umleiten: `dreame-eu.iot.dreame.tech`,
> `oss.iot.dreame.tech`, `*.dreame.tech` — sonst brechen OTA/CDN.

Prüfen:

```bash
dig +short 10000.mt.eu.iot.dreame.tech @10.10.48.3
# muss die HA-IP liefern
```

---

## 5. Roboter umstellen

1. Roboter **stromlos** machen (1–2 s warten) und wieder einschalten.
2. Im Add-on-Log erscheint nach ~1 Minute:
   ```
   CONNECT device_909669328 user=909669328
   Roboter verbunden: did=909669328
   SUBSCRIBE /ctrl/909669328/
   ```
3. In Home Assistant erscheint das Gerät **„Dreame"** mit Vacuum, Sensoren,
   Selects und Buttons.

---

## 6. Entitäten in Home Assistant (Modus A)

| Entität | Typ | Funktion |
|---|---|---|
| Vacuum | `vacuum` | Start, Stop, Pause, Zur Basis, Finden, Akku |
| Batterie | `sensor` | % |
| Status / Fehler | `sensor` | z. B. `CHARGING_COMPLETED`, Fehlertext |
| Fläche / Reinigungszeit | `sensor` | letzter Lauf |
| Hauptbürste / Seitenbürste / Filter / Sensor | `sensor` | Reststand in % |
| Gesamtfläche / -zeit / Reinigungen | `sensor` | Lebenszeit |
| Saugstufe / Wassermenge / Modus | `select` | direkt schaltbar |
| Finden / Absaugen / Mopp waschen | `button` | Aktionen |
| `props` (Attribut am Vacuum) | Attribute | alle nicht-leeren Properties |

---

## 7. Web-UI und REST

Über das Add-on-Panel (Ingress) oder `http://<HA-IP>:8099`:

```
GET  /api/state
POST /api/command   {"action":"start"}
POST /api/command   {"set":"SUCTION_LEVEL","value":"turbo"}
POST /api/command   {"method":"get_properties","params":[{"did":"…","siid":3,"piid":1}]}
PUT  /upload/<name>          (für den Roboter, HTTPS auf 8443)
```

---

## 8. Fehlerbehebung

| Symptom | Ursache / Lösung |
|---|---|
| Add-on startet nicht | Port 19973 belegt (z. B. alter Testbroker) → Prozess stoppen, Add-on neu starten |
| Roboter verbindet nicht | DNS-Rewrite prüfen (`dig`), Port 19973 in der Firewall, `lan_ip` korrekt |
| „Roboter verbunden" von falscher IP | Ein Testclient nutzt `device_<did>`; `device_ip` auf die echte Roboter-IP setzen und den Testclient stoppen. Der Broker wirft die alte Session bei gleicher Client-ID raus |
| `TLS handshake failed` im Log | falsches Zertifikat in `app/certs/` (muss die Dreame-Kette sein) |
| Keine Entitäten in HA | Mosquitto/MQTT-Integration prüfen, `discovery_prefix` = `homeassistant` |
| Roboter „offline" in der Dreame-App | **normal** im lokalen Betrieb |
| Karte fehlt | Uploads landen in `/data/uploads`; Diagnose: `/api/diagnostics` → `uploads`, `presigned_urls`, `upload`. Der Roboter holt neue Upload-URLs nur etwa stündlich bzw. nach Neustart/Kartenänderung – nach einem Add-on-Update einmal Roboter neu starten oder kurz reinigen lassen |
| `GET /files/...` 404 | Datei wurde noch nie hochgeladen (kein Upload in `events`) oder der Roboter nutzt eine alte URL aus dem Cache (30 min) |
| Zurück zur Cloud | DNS-Rewrite löschen, Roboter neu starten |

---

## 9. Wie es funktioniert

```
                     ┌──────────── Add-on ────────────┐
Roboter ─TLS/MQTT───►│ :19973 Broker                 │
                     │    │                           │
                     │    ├─ Device-Layer (siid/piid) │
                     │    ├─ :13267 Dreame-API-Emu ───┼──► Tasshack-Integration (HA)
                     │    ├─ MQTT-Discovery ──────────┼──► HA-Entitäten (Modus A)
                     │    └─ :8099 Web-UI / REST      │
                     └────────────────────────────────┘
```

- Der Roboter meldet sich als `device_<did>` an, abonniert
  `/ctrl/<did>/` und `/result/<did>/` und publiziert Status auf
  `/status/<did>/<uid>/<model>/<region>/`.
- Das Add-on beantwortet `local.query_time` und
  `_sync.gen_*presigned_url` (Upload-URLs auf sich selbst) und schickt
  Kommandos als `/ctrl/`-Envelopes (`action`, `set_properties`,
  `get_properties`).
- Die TLS-Kette stammt aus der Dreame-App und wird vom Roboter
  akzeptiert (er prüft die Kette, nicht den Hostnamen).

Mehr Hintergrund, Messungen und die Reverse-Engineering-Notizen:
[`docs/FINDINGS.md`](docs/FINDINGS.md).

---

## 10. Sicherheit und Grenzen

- Der Broker akzeptiert **jede** Authentifizierung. Nur in einem
  vertrauenswürdigen LAN/VLAN betreiben, **nicht** ins Internet öffnen.
- `dreame_local/app/certs/server.key` ist ein Schlüssel aus der
  Dreame-App. Nicht weitergeben, nicht in öffentliche Repos stellen.
- Solange der Roboter lokal läuft: kein Fernzugriff, keine App-Karte,
  kein OTA über die App.
- Zeitpläne/DND werden nicht verwaltet. Karten werden gespeichert, aber
  nicht gerendert.
- Kein offizielles Dreame-Produkt, keine Garantie. Nutzung auf eigene
  Gefahr, nur für eigene Geräte.

---

## 11. Repository-Struktur

```
.
├── repository.yaml          # macht das Repo zum HA-Add-on-Repository
├── dreame_local/            # das Add-on
│   ├── config.yaml
│   ├── Dockerfile
│   ├── run.sh
│   ├── requirements.txt
│   └── app/                 # Broker, Protokoll, HA-Bridge, Web-UI, Mapping
├── docs/FINDINGS.md         # Reverse-Engineering-Notizen
└── tools/                   # Forschungs-Skripte (Capture, eMudhra, MQTT-Observer)
```

## 12. Entwicklung ohne HA

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r dreame_local/requirements.txt
DEVICE_DID=909669328 DEVICE_UID=VB847569 DEVICE_MODEL=dreame.vacuum.r2469a \
REGION=eu LAN_IP=<deine-ip> DATA_DIR=./data \
python dreame_local/app/main.py
```

Ohne `MQTT_HOST` startet nur Broker + Web-UI (Port 8099), ohne Discovery.

---

## English Installation Guide

This guide installs **Dreame Local Cloud** as a Home Assistant add-on and
moves a Dreame robot (for example the L10s Ultra Gen 2, `dreame.vacuum.r2469a`)
from the Dreame cloud to the local add-on. The existing **Dreame Vacuum**
integration (Tasshack) and its map cards keep working against the local API
(Mode B, recommended).

> Tested with add-on **0.3.18+**. That version includes the local map fallback,
> live robot position and the persisted cleaning trail.

### 1. Requirements

| Item | Why |
|---|---|
| Home Assistant OS or Supervised | Required for add-ons |
| HACS + **Dreame Vacuum** (Tasshack) | Entities, map and map cards (Mode B) |
| Mosquitto + MQTT integration | Only for the optional Mode A (discovery) |
| AdGuard Home, Pi-hole or a router with DNS rewrites | The robot must resolve the local add-on |
| Robot already paired with the Dreame app | Pairing and certificates stay as they are |
| Add-on certificates in `dreame_local/app/certs/` | Already included; keep them private |

### 2. Ports

| Port | Purpose |
|---|---|
| `19973/tcp` | MQTT over TLS for the robot (DNS rewrite target) |
| `13267/tcp` | Dreame API emulation (DNS rewrite target for the integration) |
| `8443/tcp` | HTTPS upload endpoint for map/log files |
| `8099/tcp` | Web UI, diagnostics and REST API |

Open `19973`, `13267` and `8443` from the robot/integration VLAN to the HA
host. Do **not** expose any of these ports to the internet.

### 3. Install the add-on

1. In Home Assistant open **Settings → Add-ons → Add-on Store**.
2. Open the three-dot menu (⋮) → **Repositories**.
3. Add `https://github.com/dwyschka/Dreame-local` and confirm.
4. Reload the store, open **Dreame Local Cloud** and click **Install**.
5. Open the **Configuration** tab and paste the configuration below, then
   start the add-on.

```yaml
device_did: ""                        # empty = auto-detect on connect
device_uid: ""                        # empty = auto-detect (dev_start)
device_model: "dreame.vacuum.r2469a"
region: "eu"
device_name: "Dreame"
mqtt_host: ""                         # empty = no discovery duplicates (Mode B)
mqtt_port: 1883
mqtt_username: ""
mqtt_password: ""
discovery_prefix: "homeassistant"
lan_ip: "192.168.1.10"                # HA host IP reachable by the robot
upload_host: ""                       # optional: e.g. eu.iot.dreame.tech instead of lan_ip
device_ip: ""                         # optional: only this robot IP may use device_<did>
mac: ""                               # optional
broker_port: 19973
api_port: 13267
web_port: 8099
upload_port: 8443
log_level: "info"
```

Notes:

- `lan_ip` is the HA host IP that the robot can reach (normally the LAN IP of
  the HA OS VM/host).
- `upload_host` only changes the host in the presigned upload URLs; the port
  stays `upload_port`. Some firmware rejects IP-based URLs. In that case set
  `upload_host: eu.iot.dreame.tech` and make that name resolve to the HA host.
- `device_ip` is optional. Leave it empty unless you need to lock the robot
  session to one IP. The broker also performs an MQTT session takeover when the
  same client ID reconnects.
- `device_did`/`device_uid` can stay empty. Set them if auto-detection is not
  desired.
- `mqtt_host` stays empty for Mode B. Set it only for the optional Mode A.

After start, the log should contain:

```text
MQTT-Broker lauscht auf :19973 (TLS)
Web-UI auf :8099
HTTPS-Upload auf :8443
Dreame-API-Emulation auf :13267 (HTTPS)
```

### 4. DNS rewrites (most important step)

The robot resolves its MQTT broker and the API through DNS. Point these names
to the HA host:

```text
eu.iot.dreame.tech          ->  <HA-IP>
*.mt.eu.iot.dreame.tech     ->  <HA-IP>
```

If your DNS server has no wildcard support, add the exact broker name from the
robot's `bindDomain`, usually:

```text
10000.mt.eu.iot.dreame.tech ->  <HA-IP>
```

**Do not rewrite** `dreame-eu.iot.dreame.tech`, `oss.iot.dreame.tech` or
`*.dreame.tech`; these are used for OTA/CDN and must keep resolving to the real
cloud. `eu.iot.dreame.tech` is required locally for the API and map download
URLs in Mode B.

Verify from a client in the robot/integration VLAN:

```bash
dig +short eu.iot.dreame.tech
dig +short 10000.mt.eu.iot.dreame.tech
```

Both must return the HA IP.

### 5. Start the robot against the add-on

1. Power-cycle the robot completely (switch it off, wait a few seconds, switch
   it on).
2. Wait 30–90 seconds.
3. In the add-on log you should see:

```text
CONNECT device_<did> user=<uid> von ('<robot-ip>', ...)
Roboter verbunden: did=<did>
SUBSCRIBE /ctrl/<did>/
SUBSCRIBE /result/<did>/
```

If you see `mqtt_reject`, the connecting IP does not match `device_ip`. If a
test client uses the robot credentials, set `device_ip` to the real robot IP
and stop the test client.

### 6. Home Assistant integration (Mode B)

1. Install **Dreame Vacuum** (Tasshack) through HACS if it is not installed.
2. Open **Settings → Devices & Services → Add Integration → Dreame Vacuum**.
3. Select account type **Dreame Home**, country/region `eu`.
4. Username and password can be arbitrary values; the local add-on accepts
   them. Use the same values consistently.
5. The integration receives the local `bindDomain` (`<HA-IP>:19973`) and
   connects to the add-on through the DNS rewrites.
6. Keep `mqtt_host` empty in the add-on to avoid duplicate discovery entities.

The existing vacuum entity, sensors, map camera and map cards keep working.
Reload the integration after an add-on update.

### 7. Map, live position and trail

The map is served by the add-on through the Dreame API emulation. With 0.3.18:

- The add-on answers `REQUEST_MAP` and `getDeviceData` with a full I-frame.
- The current robot position is taken from the live P-frames.
- The cleaning trail is accumulated, shown on the map and persisted in
  `/data/map_path.txt`.
- A new cleaning (`START`) clears the old trail.

If the map is empty:

1. Open the add-on Web UI (`http://<HA-IP>:8099`) and use **Karte prüfen**.
2. Check `/api/diagnostics` for `uploads`, `presigned_urls` and `upload`.
3. Confirm that the robot can reach `8443` and that `upload_host`/`upload_port`
   are correct.
4. Trigger a short cleaning or power-cycle the robot so it requests fresh
   presigned URLs.
5. Reload the integration.

The map room colors are a renderer/color-scheme detail: the imported cloud map
does not contain the app's per-room color indexes, so the integration may use
its first palette color for all rooms. Change the integration's color scheme or
enrich the map with color indexes if you need the exact cloud colors.

### 8. Verify

- Add-on Web UI: `http://<HA-IP>:8099`
  - Clients list shows `device_<did>` and `p_...` (the integration).
  - State shows the robot as online.
- Log: `CONNECT`, `SUBSCRIBE`, `presigned_urls`, `upload`.
- Home Assistant: vacuum entity, map camera and map card are available.

Useful REST calls:

```text
GET  http://<HA-IP>:8099/api/state
GET  http://<HA-IP>:8099/api/diagnostics
GET  http://<HA-IP>:8099/api/mapcheck
POST http://<HA-IP>:8099/api/command   {"action":"start"}
```

### 9. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Add-on does not start | Port `19973`/`13267`/`8443` already in use; stop the old test broker/container |
| Robot does not connect | Check DNS rewrites, port `19973` and the firewall; verify `lan_ip` |
| `mqtt_reject` in the log | `device_ip` does not match the robot; correct it or clear it |
| Robot connects from the wrong IP | A test client is using `device_<did>`; stop it and/or set `device_ip` |
| `TLS handshake failed` | Wrong certificate in `app/certs/`; use the Dreame chain from the app |
| No integration entities | Check HACS integration, DNS for `eu.iot.dreame.tech`, and reload the integration |
| Map empty / `GET /files/...` 404 | No upload yet or stale URL; check `8443`, `upload_host`, `uploads` and power-cycle the robot |
| Map has no trail | Update to 0.3.18+, trigger a cleaning; the trail is persisted per run |
| Robot offline in the Dreame app | Expected in local mode |
| Return to the cloud | Remove the DNS rewrites and power-cycle the robot |

### 10. Security

- The broker accepts any authentication. Run it only in a trusted LAN/VLAN.
- Never expose ports `19973`, `13267`, `8443` or `8099` to the internet.
- `dreame_local/app/certs/server.key` is a key extracted from the Dreame app.
  Keep it private and never publish it in a public repository.
- Local mode means no remote access, no cloud map in the Dreame app and no OTA
  through the app.
- This is not an official Dreame product. Use it at your own risk and only with
  your own robot.

### 11. Optional Mode A (MQTT discovery)

Set `mqtt_host` to the Mosquitto host, configure `mqtt_username`/
`mqtt_password`, and keep `discovery_prefix: homeassistant`. The add-on then
publishes a vacuum, sensors, selects and buttons directly through MQTT
discovery. No HACS integration is required. Do not run Mode A and Mode B at the
same time unless you want duplicate entities.

### 12. Development without Home Assistant

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r dreame_local/requirements.txt
DEVICE_DID=909669328 DEVICE_UID=VB847569 DEVICE_MODEL=dreame.vacuum.r2469a \
REGION=eu LAN_IP=<your-ip> DATA_DIR=./data \
python dreame_local/app/main.py
```

Without `MQTT_HOST`, only the broker, API and Web UI (port 8099) start.
