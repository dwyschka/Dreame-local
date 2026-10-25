# Home Assistant als Dreame-App

Ziel: Die Dreame-App wird im Alltag **nicht** mehr gebraucht. Home
Assistant übernimmt Steuerung, Status, Karte, Räume/Zonen und Einstellungen.
Das Add-on liefert dafür die lokale Cloud (MQTT + API).

```
┌────────────────────────── Home Assistant ──────────────────────────┐
│  Lovelace (Dreame Vacuum Card / Xiaomi Vacuum Map Card)            │
│        │                                                           │
│  Integration „Dreame Vacuum“ (HACS)                                │
│        │  HTTPS 13267        │ MQTT 19973                          │
│        ▼                    ▼                                      │
│  Add-on „Dreame Local Cloud“ (API-Emulation + Broker)              │
└────────────────────────────────┬───────────────────────────────────┘
                                 │ TLS/MQTT
                            Dreame-Roboter
```

Die Integration bleibt unverändert — sie glaubt, mit der Dreame-Cloud zu
sprechen. Deshalb funktionieren auch alle Karten und Kartenfunktionen.

---

## 1. Voraussetzungen

- Add-on „Dreame Local Cloud“ installiert und gestartet
- HACS installiert
- DNS-Einträge (AdGuard/Pi-hole/Router)
- Roboter im WLAN (die Ersteinrichtung/Werksreset braucht weiterhin die
  Dreame-App — danach nicht mehr)

---

## 2. DNS-Rewrites

| Host | Ziel |
|---|---|
| `eu.iot.dreame.tech` | `<HA-IP>` |
| `*.mt.eu.iot.dreame.tech` | `<HA-IP>` |

`eu…` ist für die Integration (API), `*.mt…` für den Roboter (MQTT).

Prüfen:

```bash
dig +short eu.iot.dreame.tech @10.10.48.3
dig +short 10000.mt.eu.iot.dreame.tech @10.10.48.3
# beide -> HA-IP
```

---

## 3. Add-on konfigurieren

```yaml
mqtt_host: ""            # leer lassen! Sonst doppelte Entities
lan_ip: "10.10.48.10"    # IP des HA-Hosts
region: "eu"
device_model: "dreame.vacuum.r2469a"
log_level: "info"
```

`mqtt_host` leer = keine MQTT-Discovery-Entitäten. Die Entitäten kommen
aus der Integration.

---

## 4. Integration einrichten

1. HACS → Integrationen → **Dreame Vacuum** installieren, HA neu starten.
2. Einstellungen → Geräte & Dienste → Integration hinzufügen →
   **Dreame Vacuum**.
3. Konto-Typ: **Dreame Home**
4. Region/Land: **`eu`** (muss zum DNS-Rewrite passen)
5. Benutzername/Passwort: **beliebig** (der lokale Server akzeptiert alles)
6. Fertig — das Gerät erscheint mit Vacuum, Sensoren, Karte und
   Verbrauchsmaterial.

> Beim ersten Start kann die Karte noch leer sein. Nach **einer**
> Reinigung lädt der Roboter den Kartenblob zu unserem Server, die
> Integration holt ihn über `getDownloadUrl` und rendert ihn.

---

## 5. Dashboard (App-Ersatz)

### Variante A: Dreame Vacuum Card (empfohlen, kostenpflichtig)

Die offizielle Karte ist ein vollständiger App-Ersatz (interaktiver
Karteneditor, Zeitpläne, DND, Einstellungen) und ist bei der Integration
dabei — sie braucht nur eine Lizenz pro Gerät.

```yaml
type: custom:dreame-vacuum-card
entity: vacuum.dreame
```

Panel-Ansicht (Dashboard → Ansicht bearbeiten → Panel-Modus) macht daraus
eine Vollbild-App.

### Variante B: kostenlos

```yaml
type: vertical-stack
cards:
  - type: picture-entity
    entity: camera.dreame_map
    camera_view: live
    show_name: false
    show_state: false
  - type: entities
    title: Dreame
    entities:
      - entity: vacuum.dreame
      - entity: sensor.dreame_battery
      - entity: sensor.dreame_status
      - entity: select.dreame_suction_level
      - entity: select.dreame_water_volume
      - entity: select.dreame_cleaning_mode
      - entity: button.dreame_locate
```

Für interaktive Karten (Räume/Zonen antippen) zusätzlich die
**Xiaomi Vacuum Map Card** (HACS) mit `camera.dreame_map_data` als
`map_source` — dann rendert der Browser die Karte, was CPU auf dem
HA-Host spart.

> Entitätsnamen (`vacuum.dreame`, `camera.dreame_map`, …) je nach
> Gerätename anpassen.

---

## 6. Was die App noch kann, HA aber nicht (mehr)

| Funktion | Status |
|---|---|
| Steuerung, Status, Akku, Verbrauchsmaterial | ✅ |
| Karte, Räume, Zonen, Sperrzonen | ✅ (Integration/Karte) |
| Zeitpläne, DND | ✅ über die Dreame Vacuum Card; eingeschränkt über die Integration |
| Kartenhistorie | ✅ (Integration) |
| Firmware-Update | ❌ nur über die App/Dreame-Cloud |
| Fernzugriff von unterwegs | ❌ (nur im LAN/VPN) |
| Ersteinrichtung / Werksreset / WLAN-Wechsel | ❌ App nötig |

Die App also am besten installiert lassen, aber im Alltag nicht mehr
benutzen: Sie wird nur noch für Werksreset, WLAN-Wechsel und
Firmware-Updates gebraucht.

---

## 7. Wenn etwas nicht geht

| Problem | Prüfen |
|---|---|
| Integration meldet Login-Fehler | DNS `eu.iot.dreame.tech` → HA-IP? Port 13267 offen? Add-on-Log |
| Gerät wird nicht gefunden | `device_did` leer? Roboter verbunden (`Roboter verbunden` im Log)? |
| Gerät offline | DNS `*.mt…` → HA-IP? Port 19973? |
| Karte leer | Einmal reinigen lassen; `MAP_LIST` im Log? Datei in `/data/uploads`? |
| Doppelte Entitäten | `mqtt_host` im Add-on leeren |
| App geht nicht mehr | `eu.iot.dreame.tech`-Rewrite entfernen (dann ist die API wieder Cloud) |

---

## 8. WLAN zurücksetzen / wechseln

Ein WLAN-Reset ist **kein** Firmware-Reset: Karte und Einstellungen bleiben
erhalten, nur die Netzwerkdaten werden gelöscht.

### Variante 1: Tastenkombination (ohne Datenverlust)

Am Roboter **Spot Cleaning + Dock** gleichzeitig ~3 Sekunden halten, bis
die Sprachansage „Waiting for network configuration" kommt und die
WLAN-LED **langsam blinkt**.

- L10s-Familie (L10s Ultra, L10s Pro, L10 Pro, Z10 Pro): so dokumentiert
- L10s Ultra Gen 2: beide Tasten sind vorhanden; falls die Kombination
  nicht greift, ist laut Handbuch der offizielle Weg, in der App erneut
  „Gerät hinzufügen" → QR-Code scannen (Provisioning per BLE)

Danach verbindet sich der Roboter mit dem **2,4-GHz**-Netz (kein 5 GHz,
WPA2, kein Captive Portal, keine AP-Isolation).

### Variante 2: Routerwechsel ohne Reset (bester Weg ohne App)

Wenn nur der Router/AP getauscht wird: **SSID, Passwort, Verschlüsselung
(WPA2) und 2,4 GHz exakt gleich lassen**. Der Roboter verbindet sich
automatisch, es ist kein Reset und keine App nötig.

### Variante 3: Werksreset (alles löschen)

Abdeckung öffnen, **Reset-Taste** mit einem Stift/Büroklammer ~3 s halten
→ „Start to restore factory settings". Dabei werden **Karte, Zeitpläne und
Einstellungen gelöscht**. Danach ist eine komplette Neueinrichtung über
die App nötig (die einzige Situation, in der die App noch gebraucht wird).

### Wichtig bei Provisioning über die App

Vorher die DNS-Rewrites für `eu.iot.dreame.tech` und
`*.mt.eu.iot.dreame.tech` **deaktivieren** (oder auf die echte Cloud
zeigen lassen). Sonst landet die App beim Koppeln auf unserem lokalen
Server und die Einrichtung schlägt fehl. Nach dem Provisioning die
Rewrites wieder setzen — der Roboter verbindet sich dann mit dem Add-on.

### Kein Software-Reset möglich

Das Dreame-Protokoll hat keine Aktion zum Zurücksetzen der WLAN-Daten
(weder über die Cloud-API noch über MQTT). Es geht nur über die Tasten
oder die App.
