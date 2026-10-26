# Dreame lokal entkoppeln — Machbarkeitstest

Stand: 2026-10-25 · Ziel: Roboter aus der Dreame-Cloud holen, d. h. die
Cloud-Rolle lokal nachbauen („Cloud-Emulator"), nicht die App ersetzen.

---

## 1. Ist-Zustand (gemessen)

| Position | Wert |
|---|---|
| Roboter-IP | `10.10.48.55` (ping ok, ~7 ms) |
| PTR / Hostname | `dreame_vacuum_r2469a.localdomain` → Modell `dreame.vacuum.r2469a` |
| Offene TCP-Ports | **keine** (80, 443, 1883, 8883, 13267, 19973, 54321, 6668, 8080, 8443) |
| miIO/UDP 54321 | keine Antwort auf `21310020…`-Hello |
| mDNS `_miio._udp` | nur ein fremder `roborock-vacuum-s5` im Netz |
| DNS-Server | `10.10.48.3` (AdGuard Home, UI erreichbar, API = 401 → Login nötig) |
| Gateway | `10.10.48.1` |
| Mac | `10.10.48.124` (en1), DNS = 10.10.48.3 |

**Fazit:** Der Roboter ist ein reiner Cloud-Client. Der früher übliche
lokale Weg über miIO/UDP 54321 ist bei dieser Firmware tot. Es gibt keinen
lokalen Angriffspunkt außer „Cloud spielen".

## 2. Die Cloud-Endpunkte des Roboters

Aus dem Referenz-Client (Tasshack/dreame-vacuum v2.0.2, `protocol.py`) und
per TLS-Probe verifiziert:

| Zweck | Host | Port | Zertifikat des echten Servers |
|---|---|---|---|
| HTTP-API (Login, Kommandos, Karten) | `{region}.iot.dreame.tech` (z. B. `eu.`) | `13267` | RapidSSL/DigiCert, `CN=*.iot.dreame.tech` — **öffentliche PKI** |
| MQTT (Roboter ↔ Cloud) | `bindDomain`, z. B. `10000.mt.eu.iot.dreame.tech` | dynamisch, z. B. `19973` | **hausgemachte PKI**: `CN=iot.dreame.tech` ← `CN=GlobalSign Organization Validation CA` ← `CN=GlobalSign Root CA`, alle mit `notBefore 1969`, `notAfter 2969` und eigenen Schlüsseln |

Der MQTT-Broker gibt sich also als GlobalSign aus, verwendet aber eine
eigene, selbstsignierte Kette (SPKI ≠ echtes GlobalSign-Root). Das ist der
wichtigste Einzelfund für die Machbarkeit (siehe §4).

Der Roboter löst laut öffentlichen Beobachtungen (L40 Ultra, Reddit) ständig
`10000.mt.eu.iot.dreame.tech` auf – d. h. er benutzt DNS, kein Hardcoding.
Ein DNS-Rewrite in AdGuard ist damit der Hebel.

## 3. eMudhra-Teil: funktioniert technisch (bewiesen)

Die acht im Oktober 2026 kompromittierten eMudhra-Intermediate haben
P-384-Schlüssel, die nur 1…255 sind. Aus den öffentlichen Zertifikaten
lassen sie sich in Sekunden rekonstruieren (`mitm/gen_ca.py`):

```
EM DV TLS CA - G3B   d=156      EM DV TLS CA - G3C   d=230
EM OV TLS CA - G3B   d=155      EM OV TLS CA - G3C   d=4
EM EV TLS CA - G3B   d=115      EM EV TLS CA - G3C   d=56
EM OV CS CA - G3B    d=66       EM OV CS CA - G3C    d=237
```

Die Varianten mit **Sectigo-Cross-Sign** („AAA Certificate Services") sind
der interessante Fall: AAA/Comodo ist in praktisch jedem alten CA-Bundle
(und damit potenziell in der Roboter-Firmware). Verifikation mit *nur* dem
AAA-Root:

```
openssl verify -CAfile src/aaa-certificate-services.pem \
  -untrusted certs/leaf_EM_DV_TLS_CA_-_G3B__sectigo.pem \
  certs/leaf_EM_DV_TLS_CA_-_G3B__sectigo-leaf-only.pem
→ OK   (für alle 8 Ketten)
```

Ende-zu-Ende-Test mit mitmproxy 12.2.3 (TLS-Terminierung + Weiterleitung an
den echten Broker, Client vertraut nur AAA):

```
TLS OK: TLSv1.3 TLS_AES_256_GCM_SHA384
--> CONNECT client_id='p_deadbeef…' username='1234567890'
<-- CONNACK return_code=5        (Broker: not authorized — erwartet, Fake-Creds)
```

Damit ist die komplette MITM-Kette bewiesen: Zertifikat wird akzeptiert,
Verbindung wird entschlüsselt, MQTT wird mitgelesen, Weiterleitung an die
echte Cloud funktioniert.

**Wichtige Einschränkung:** Ob der *Roboter* AAA/Comodo (oder irgendeinen
öffentlichen Root) überhaupt prüft, ist offen. Prüft er das Serverzertifikat
gar nicht – was die gefälschte GlobalSign-Kette nahelegt –, ist eMudhra
sogar überflüssig und jedes Zertifikat genügt. Pinnt er stattdessen die
Dreame-eigene Root, hilft eMudhra nicht und der Weg ist zu, solange wir
keinen Firmware-Zugriff haben.

## 4. Was der Roboter spricht (App-Layer)

Aus dem Referenz-Client, sehr gut nachvollziehbar:

* MQTT 3.1.1 über TLS, Login per **Username/Password** (kein Client-Zert).
* Topics: `/{status|…}/{did}/{uid}/{model}/{country}/`
* Nutzlast: **reines JSON**, kein AES, kein Protobuf:
  `{"data": {"did": …, "id": …, "method": "get_properties"|"action"|…, "params": …}}`
* Die Krypto (AES-ECB-Header `dreame-rlc`, MD5-Signaturen, OAuth) sitzt nur
  in der **App↔HTTP-API**, nicht auf der Geräte-MQTT-Strecke.
* `did`, `uid`, `model`, `bindDomain` liefert `…/iotuserbind/device/listV2`.
* Kommandos gehen über `…/dreame-iot-com-{shard}/device/sendCommand` an die
  API, die sie intern auf MQTT publiziert.

Für einen lokalen Emulator heißt das: MQTT-Broker mit beliebiger
Authentifizierung + JSON-Handling + TLS. Kein Nachbau der App-Krypto nötig.

## 5. Urteil

| Baustein | Status |
|---|---|
| Cloud-Protokoll verstanden | ✅ vollständig (Referenz-Client + Capture) |
| Geräte-App-Layer trivial (JSON/MQTT) | ✅ |
| Zertifikat für MITM erzeugbar | ✅ (eMudhra, 8 Ketten, gegen AAA verifiziert) |
| MITM-Pfad technisch lauffähig | ✅ (mitmproxy, Ende-zu-Ende getestet) |
| Umleitung des Roboters | ⛔ braucht DNS-Rewrite (AdGuard-Login) oder ARP/pf (sudo) |
| Server-Verifikation im Roboter | ❓ **entscheidend** — nur vor Ort testbar |
| Lokaler Broker (mosquitto o. ä.) | ✅ sofort machbar, sobald Zertifikat akzeptiert wird |

**Erwartung:** Wenn der Roboter die TLS-Kette nicht streng prüft (Indiz:
die Broker-Kette ist selbst für GlobalSign ungültig), ist die Entkopplung
in wenigen Tagen Arbeit erledigt. Wenn er auf die Dreame-Root pinnt, ist
der saubere Weg nur über Firmware (OTA-Image analysieren/patchen) möglich.

## 6. Nächste Schritte (blockiert durch fehlende Zugänge)

1. **AdGuard-Login** (oder Rewrites selbst anlegen):
   `*.iot.dreame.tech`, `*.dreame.tech`, `*.iot.dreametech.com` → `10.10.48.124`.
   Danach im Query-Log von `10.10.48.55` die tatsächlich angefragten Namen
   und Shards ablesen.
2. **Port des Brokers** für dieses Gerät: `bindDomain` aus der Cloud holen
   (`mitm/login_probe.py`, läuft lokal, gibt keinen Token aus) oder in der
   Home-Assistant-Integration per Debug-Log mitlesen. Ohne Port kein Listener.
3. **Capture starten** (`mitm/run_capture.sh`) und den Roboter wecken
   (App öffnen / Reinigung starten). Entscheidend ist, ob der TLS-Handshake
   durchläuft oder der Roboter abbricht.
4. Bei Abbruch: ClientHello trotzdem auswerten (SNI, ALPN, Cipher) und
   Firmware-Image (OTA) ziehen → REA-Analyse der TLS-Validierung.

## 7. Dateien

```
mitm/gen_ca.py            eMudhra-Keys rekonstruieren + Leaf/CAs bauen
mitm/certs/               alle 8 Ketten, Wildcard-Leaf + Intermediate
mitm/addons/mqtt_dump.py  mitmproxy-Addon: ClientHello + MQTT-Decoder
mitm/run_capture.sh       Reverse-Proxy 19973 (MQTT) + 13267 (API)
mitm/login_probe.py       bindDomain/did/model aus der Cloud holen
mitm/src/                 Zertifikate (impacted-intermediates.json, AAA-Root)
```

Hinweis: Die eMudhra-Schlüssel sind öffentlich ableitbar (schwache
Key-Generierung), es wird nichts „gestohlen". Der Einsatz ist hier nur
gegen das eigene Gerät im eigenen Netz gedacht; Zertifikate für fremde
Hosts zu erzeugen wäre strafbar und ist nicht Teil dieses Setups.

---

## 8. Ergebnis des Gerätetests (25.10.2026, 13:51)

Der Roboter wurde neu gestartet, DNS-Rewrite aktiv, Capture-Proxy auf
`19973`. Ergebnis nach 5 Verbindungsversuchen, alle identisch:

```
[13:51:30][10.10.48.55:33932] client connect
Client TLS handshake failed. The client does not trust the proxy's
certificate for 10000.mt.eu.iot.dreame.tech (tlsv1 alert unknown ca)
```

**Der Roboter prüft das Serverzertifikat und vertraut keinem öffentlichen
Root.** Damit ist der eMudhra-Weg für das Gerät tot. Die Kette (Leaf ←
`EM DV TLS CA – G3B` ← `AAA Certificate Services`) ist gegen AAA gültig
und wurde von einem App-Client (`10.10.50.3`, Flutter) auch akzeptiert —
der Roboter lehnt sie ab.

ClientHello des Roboters:
`sni=10000.mt.eu.iot.dreame.tech`, 23 Cipher, KEIN ALPN, KEIN
status_request, Extensions `[0,11,10,35,22,23,13,43,45,51]` → **mbedTLS 3.x**
mit `VERIFY_REQUIRED` und eigenem CA-Store (Dreame-Root). Öffentliche CAs
sind dort nicht enthalten (AAA/Comodo fehlt, obwohl seit 2004 in jedem
Bundle) → **Pinning auf die Dreame-PKI**.

Konsequenz: Ein lokaler Broker kann nur funktionieren, wenn der Trust
Anchor auf dem Gerät geändert wird. Ohne Firmware-Zugriff (UART/Exploit)
ist das nicht erreichbar. Die Dreame-Root-Keys sind sauber generiert
(RSA-2048, keine gemeinsamen Primfaktoren mit dem Intermediate) — kein
Shortcut.

### Gerätedaten (aus der Cloud-API)

```
model        dreame.vacuum.r2469a   ("L10s Ultra Gen 2")
fw           4.3.9_1642
mac          70:C9:32:8D:C1:B5
did          909669328
uid          VB847569
bindDomain   10000.mt.eu.iot.dreame.tech:19973
productId    10335
```

### Was der Test zusätzlich geliefert hat (alles verwertbar)

* **API-Auth:** `authorization: Basic <app>` + **`dreame-auth: <JWT>`**
  (nicht Bearer), `dreame-rlc` (AES-ECB `region|lang|ccode`), `dreame-meta`,
  `tenant-id: 000000`, Body mit `sign` (MD5 über sortierte Felder + ms + CID)
  und `timestamp`.
* **Endpunkte:** `/dreame-auth/oauth/token`, `…/iotuserbind/device/listV2`,
  `…/iotuserbind/device/info`, `…/iotstatus/devOTCInfo`,
  `…/device/sendCommand`, `…/iotfile/getDownloadUrl`,
  `/file-bridge/user/getDeiviceFile`.
* **MQTT:** `CONNECT` mit `client_id=p_<uid>_<hash>`, `username=<uid>`,
  `password=<JWT>`; Topics `/msg/<uid>/`, `/status/<did>/<uid>/<model>/#`,
  `/w/<did>/`. Nutzlast reines JSON, z. B.
  `{"id":101,"did":909669328,"data":{"id":101,"method":"properties_changed","params":[{"did":"…","siid":14,"piid":4,"value":2}]}}`
* **Kommando-Roundtrip verifiziert:** `sendCommand` → HTTP 200 →
  `{"code":0,"data":{"id":9001,"result":[{"siid":14,"piid":4,"value":3}]}}`
* **Karten-Download** läuft über `iotfile/getDownloadUrl`
  (`filename=ali_dreame/<uid>/<did>/8`).

### Revidiertes Urteil

| Baustein | Status |
|---|---|
| Protokoll vollständig verstanden | ✅ inkl. Auth, Signatur, Topics, Kommandos |
| App-Seite MITM-fähig | ✅ (Flutter-Client akzeptiert eMudhra) |
| Lokaler Broker implementierbar | ✅ (`mitm/local_broker.py`) |
| **Roboter akzeptiert ihn** | ❌ **pinning, `unknown_ca`** |
| Ohne Cloud-Betrieb | ⛔ erst nach Änderung des Trust Anchors |

Verbleibende Wege, in absteigender Erfolgswahrscheinlichkeit:

1. **Firmware/UART:** Gerät öffnen, serielle Konsole, CA-Bundle ersetzen
   bzw. `authmode` patchen, dann DNS auf lokalen Broker.
2. **Matter:** nur neuere Modelle (Gen 3 / 2025+); beim L10s Ultra Gen 2
   nicht vorhanden.
3. **Mi-Home-Bindung:** falls das Modell sich in Mi Home pairen lässt,
   gäbe es einen miio-Token und Port 54321 → lokaler Weg ohne TLS.
   Aktuell antwortet 54321 nicht (Dreame-Bindung).
4. **Hybrid:** Roboter bleibt in der Cloud, Steuerung über lokal
   nachgebaute API (Zugangsdaten/Token gehören dem Nutzer, keine App nötig).

---

## 9. APK-Analyse (Dreame Home 2.6.6.3, `com.dreame.smartlife`)

XAPK von APKMirror, `libapp.so` (Flutter AOT, 21 MB) aus `split_config.arm64_v8a.apk`
extrahiert und Strings ausgewertet.

### Vollständige API-Oberfläche (Auszug)

```
/dreame-auth/oauth/token                     /dreame-auth/v2/oauth/sms
/dreame-user-iot/iotuserbind/device/{listV2,info,del,rename,pair,pairQRKey}
/dreame-user-iot/iotstatus/{devOTCInfo,props}
/dreame-user-iot/iotmqttdomain/v2/list       /dreame-user-iot/iotfile/getDownloadUrl
/dreame-user-iot/iotuserbind/deviceLogPackage
/dreame-user-iot/smarthome/{home,room,scene}/…
/dreame-messaging/user/device-messages[/v2]  /dreame-messaging/user/message-settings
/dreame-product/public/…                     /dreame-product/upgrades/{appplugin,h5plugin,sdk}
/dreame-system/appCommonUrl/queryUrlByCountryBatch
/dreame-third-video/tx/…                     /dreame-log/common/log/report
```

### OTA-Mechanismus in der App

```
OTAServerManager, OTAServerModule, com.dreame.flutter/module_ota_server
/otainfo, /http_server_downloads, otaFilePath, clearFirmwareDirectory
"firmwareDevelopType", "showLevelUpgradeType", "hasNewVersion", "downloadUrl"
"The specified OTA file does not exist"
```

→ Die App betreibt einen **lokalen OTA-Server** und hält das Firmware-Paket
im App-Speicher (`otaFilePath`). Der Download der Firmware läuft über die
App, nicht direkt vom Roboter. Ein fest verdrahteter Cloud-Endpunkt für
OTA existiert nicht in den Strings; die Update-Info kommt aus dem
Cloud-Flow/MQTT.

### Zertifikatsmaterial in der App (wichtig!)

| Datei | Inhalt |
|---|---|
| `res/raw/dev_cacert.crt` | **Dreame-Root** „GlobalSign Root CA", Serial `FBCC2B77C55D4120`, 1969–2969 — **identisch mit dem Root der Broker-Kette** |
| `res/raw/uat_cacert.crt` | gleiche PKI, UAT-Variante (Serial `0AA9F4D0…`) |
| `assets/…/cert/cacert.pem` | Root + Intermediate „GlobalSign Organization Validation CA" |
| `assets/…/cert/client.pem` | Client-Zert `CN=client`, ausgestellt vom Dreame-Intermediate, RSA-2048, **ohne EKU/SAN** |
| `assets/…/cert/client.key` | passender RSA-Private-Key (PKCS#1) |
| `res/raw/{dev,uat}_client.p12` | PKCS#12-Keystores (passwortgeschützt, Kandidaten bisher negativ) |
| `res/raw/{ca,client,key}.bks`, `assets/*.bks` | BKS-Keystores (u. a. Dreame-Root) |

Damit ist der **Trust Anchor des Roboters exakt bekannt** (der gefälschte
GlobalSign-Root aus `dev_cacert.crt`). Ein Serverzertifikat mit passendem
CN ist damit nicht ableitbar — aber das Client-Keypair ist ein
Dreame-signiertes Zertifikat und wird als Server-Zertifikat getestet.

### Nebenbefund OSS

`iotfile/getDownloadUrl` liefert signierte URLs der Form
`https://dreame-eu.iot.dreame.tech/iot/tmp/000000/ali_dreame/<uid>/<did>/<n>?Expires=…&Signature=…`
(Bucket privat, Listing = 403). Der `.iot.dreame.tech`-Rewrite fängt auch
diese Hosts ab — für App-Tests muss `dreame-eu.iot.dreame.tech` und
`oss.iot.dreame.tech` ausgenommen werden.

---

## 10. Durchbruch: lokale Steuerung funktioniert (25.10.2026, 14:09)

Die App enthält ein **von der Dreame-CA signiertes Client-Zertifikat samt
Private Key** (`client.pem` + `client.key`, CN=client, ohne EKU/SAN). Der
Roboter prüft offenbar nur die Kette, **nicht** Hostname/EKU. Damit ist er
MITM-fähig und ein lokaler Broker kann sich als Cloud ausgeben.

### Roboter-MQTT (vollständig mitgeschnitten)

```
client_id  device_909669328
username   909669328
password   0AHPos52SVq7ZvaY          (16 Zeichen, gerätefest)
keepalive  30
subscribe  /ctrl/909669328/         /result/909669328/
publish    /w/<did>/                (QoS2, Heartbeat)
           /pair/<did>/<uid>/<model>/      dev_start (domain, ver, uid, model, …)
           /status/<did>/<uid>/<model>/<region>/
           /query/<did>/<uid>/<model>/<region>/
           /recv/<did>/<uid>/<model>/<region>/
cloud→dev  /ctrl/<did>/             /result/<did>/
```

Kommando-Envelope (Cloud → Gerät), verifiziert:

```json
{"mid":46066993,"did":"909669328","id":88888,"method":"action","from":"userIot",
 "params":{"did":"909669328","siid":99,"in":[{"value":"","piid":10}],"aiid":2}}
```

Antwort des Roboters:

```json
{"id":88888,"did":909669328,"data":{"id":88888,"result":
 {"did":"909669328","siid":99,"aiid":2,"out":[],"code":0}}}
```

### Lokaler Broker (`mitm/local_broker.py`)

Läuft mit `certs/dreame_server_chain.pem` (Dreame-Client-Cert + Intermediate)
und `certs/dreame_server.key`. Funktionen: CONNECT (jede Auth), SUBSCRIBE,
PUBLISH QoS0/1/2, `local.query_time`-Antwort, Kommando-Injection über
FIFO `/tmp/dreame_cmd`.

**Verifiziert:** Roboter verbindet sich, abonniert `/ctrl/` + `/result/`,
sendet Status; injiziertes Kommando wird ausgeführt (`code:0`), Antwort
kommt auf `/recv/`. **Die Cloud ist damit vollständig aus dem Pfad.**

### Konsequenz für die Firmware-Frage

Die Firmware wird **nicht mehr benötigt**, um den Trust Anchor zu ändern —
das App-Zertifikat erfüllt denselben Zweck. Wer das Image trotzdem will
(z. B. für tiefere Analyse), hat jetzt zwei einfache Wege:

1. **OTA-Mitschnitt:** mitmproxy läuft mit dem Dreame-Client-Cert; Roboter
   bleibt in der Cloud, App löst Update-Check aus → `/ctrl/`-Kommando und
   Firmware-URL werden mitgeschnitten.
2. **UART/Flash-Dump** am Gerät (unabhängig von OTA-Signaturen).

---

## 11. Add-on: `dreame-local` (HA)

Vollstaendige lokale API mit HA-Anbindung. Aufbau:

```
dreame-local/
  config.yaml / Dockerfile / run.sh / requirements.txt / README.md
  app/main.py      Start, Optionen, Auto-Provisioning (DID aus MQTT-Login)
  app/broker.py    TLS-MQTT-Broker (QoS 0/1/2, SUBSCRIBE/PUBLISH/PING)
  app/device.py    Protokoll: Properties, Actions, Queries, Upload-URLs
  app/ha.py        MQTT-Discovery: vacuum, 15 Sensoren, 3 Selects, 3 Buttons
  app/web.py       Ingress-UI + REST (/api/state, /api/command, /upload)
  app/mapping.json 371 Properties + 45 Actions + Enums (aus der Referenz)
  app/certs/       Dreame-Serverkette + Key (aus der App)
```

Verifiziert auf dem echten Geraet:

```
online=True  battery=100  state=CHARGING_COMPLETED/docked
suction=strong water=medium mode=sweeping
main_brush=93 side_brush=73 filter=86 sensor=78
36 Properties automatisch geladen
set_properties SUCTION_LEVEL -> code 0
action LOCATE -> code 0  (Roboter piept)
```

Der Roboter verbindet sich selbst mit dem Add-on (DID aus `device_<did>`,
UID/Modell aus `dev_start`), die Cloud ist nicht beteiligt. Karten-/Log-
Uploads werden unter `/data/uploads` gespeichert (Rendering noch offen).

Grenzen: Dreame-App zeigt das Geraet offline; Zeitplaene/DND werden nicht
verwaltet; Karten werden nicht gerendert.

### Presigned-URL-Format (Karten-Upload)

Der Roboter fordert beim Start bzw. etwa stündlich per
`/query/...` → `_sync.gen_tmp_presigned_url {"indexes":[0,1]}` Upload-URLs
an und erwartet die Antwort auf `/result/<did>/`:

```json
{"id":52,"result":{"urls":[
  {"url":"https://…/iot/tmp/000000/ali_dreame/VB847569/909669328/0",
   "method":"PUT","ok":true,
   "obj_name":"ali_dreame/VB847569/909669328/0",
   "expires_time":1793106404,"pwd":"…","index":0}
]}}
```

Entscheidend ist **`index`**: Ohne dieses Feld ordnet der Roboter die URL
keiner Kartendatei zu, verwirft sie stillschweigend und lädt nie hoch.
Zusätzlich muss die Download-URL der Integration eine Query enthalten
(`?Expires=…`), weil sie beim Wiederverwenden `&current=<ts>` anhängt –
ohne `?` landet das im Pfad und ergibt 404.

Ablauf: `REQUEST_MAP` (siid 6/aiid 1) → Roboter lädt Dateien 0…9 hoch →
`_sync.update_vacuum_mapinfo` (Status) → Integration holt die Dateien per
`getDownloadUrl`/`getOss1dDownloadUrl` und rendert die Karte.
