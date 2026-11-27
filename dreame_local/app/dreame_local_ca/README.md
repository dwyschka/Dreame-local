# Dreame Local CA Bridge

Kleine Custom Component, die die CA des Add-ons **dauerhaft** in den
`certifi`-Store von HA Core einträgt. Damit muss `install-ca.sh` nach einem
HA-Core-Update nicht erneut ausgeführt werden.

## Einmalige Installation

Im Terminal/SSH-Add-on (Protection Mode kann anbleiben):

```bash
curl -fsSL http://<HA-IP>:19980/install-bridge.sh -o /tmp/install-bridge.sh
bash /tmp/install-bridge.sh
ha core restart
```

Danach **Einstellungen → Geräte & Dienste → Integration hinzufügen →
„Dreame Local CA“** auswählen und bestätigen.

Manuell: Ordner `dreame_local/app/dreame_local_ca` aus dem Repo nach
`/config/custom_components/dreame_local_ca` kopieren.

Die Bridge:

- liest `/share/dreame-local-ca.pem` (Fallback `/config/dreame-local-ca.pem`),
- hängt die CA bei jedem HA-Start an `certifi/cacert.pem` an, falls sie fehlt,
- setzt den TLS-Store-Cache der Dreame-Vacuum-Integration zurück,
- lädt vorhandene `dreame_vacuum`-Einträge nach dem HA-Start neu.

Wenn das Add-on beim HA-Start noch nicht gestartet ist, wartet die Bridge
bis zu 10 Minuten auf den CA-Export.

## Grenzen

- Die Datei muss im HA-Core-Container beschreibbar sein. Im offiziellen
  HA-OS-Container ist sie das.
- Wird die Custom Component gelöscht, greift wieder der manuelle Weg über
  `install-ca.sh`.
- Der manuelle Weg bleibt als Fallback erhalten, falls `certifi` einmal
  nicht beschreibbar ist.
