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

> ⚠️ **Nicht** umleiten: `eu.iot.dreame.tech`, `dreame-eu.iot.dreame.tech`,
> `oss.iot.dreame.tech`, `*.dreame.tech`. Sonst brechen App, OTA und
> Karten-Downloads.

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
