# Forschungs-Tools (nicht für den Betrieb nötig)

Diese Skripte sind beim Reverse-Engineering entstanden. Sie brauchen
Zertifikate/Material, das nicht im Repo liegt (siehe `docs/FINDINGS.md`).

| Datei | Zweck |
|---|---|
| `gen_ca.py` | Rekonstruiert die acht schwachen eMudhra-Intermediate-Keys und baut Test-Ketten (`src/impacted-intermediates.json`) |
| `run_capture.sh` | mitmproxy als Reverse-Proxy für 19973 (MQTT) und 13267 (API) |
| `addons/mqtt_dump.py` | mitmproxy-Addon: ClientHello + MQTT-Decoder + HTTP-Dump |
| `local_broker.py` | Minimal-Broker (Vorgänger des Add-ons), FIFO-Kommandos |
| `port_relay.py` | leitet einen Portbereich auf den Broker (Port unbekannt) |
| `mqtt_observe.py` | passiver zweiter MQTT-Client am echten Dreame-Broker |
| `login_probe.py` | Dreame-Login + `bindDomain`/`did`/`model` ausgeben (ohne Token) |
| `api_cmd.py` | `sendCommand` an die Dreame-API (Token nötig) |

Benötigt: `mitmproxy`, `cryptography`, `requests`, `paho-mqtt`.
Die Zertifikate für `run_capture.sh`/`local_broker.py` kommen aus der
Dreame-App (`assets/flutter_assets/assets/cert/`) bzw. aus `gen_ca.py`.
