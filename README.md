# BrokerShield

**Lokales Dashboard für digitale Souveränität: Datenbroker-Löschungsanfragen verwalten, statt 100 €/Jahr für Incogni/DeleteMe zu zahlen.**

BrokerShield läuft komplett lokal in einem Proxmox-LXC, ohne Cloud, ohne Account. Es verwaltet:

- **770+ Broker** vorgeladen – Seed aus [eraser](https://github.com/digisamroc/eraser) (MIT) plus kuratierte EU-/DE-Broker (SCHUFA, Boniversum, CRIF, BÜRGEL, DeltaVista, …)
- **Löschungsanfragen** mit automatisch erzeugten Texten: DSGVO Art. 17, CCPA oder generisch
- **Status-Pipeline**: geplant → angefragt → bestätigt → gelöscht → wieder-aufgetaucht
- **Wiedervorlagen**: Datenbroker re-scrapen laufend – nach „gelöscht“ erinnert BrokerShield nach N Tagen an den Re-Check
- **Optional**: SMTP-Versand (z. B. Gmail-App-Password) und Ollama-Assistent (extern) zum Formulieren von Briefen

## Installation (Proxmox VE, Einzeiler auf dem Host)

```bash
bash -c "$(wget -qLO - https://raw.githubusercontent.com/HatchetMan111/DataBrokerShield/main/install/brokershield.sh)"
```

> **Hinweis:** Der Installer klappt das Repo `HatchetMan111/DataBrokerShield` in den Container – bei einem Fork beide URLs (`UPSTREAM_REPO`, `SCRIPT_URL`) im Installer anpassen.

Der Installer (Community-Scripts-Stil) erstellt automatisch:
- unprivilegierten LXC (Debian 13, Standard: 2 vCPU / 2 GB RAM / 8 GB Disk, `onboot: 1`)
- systemd-Service `brokershield` (bindet `0.0.0.0:8080`, `Restart=always`)
- SQLite-Datenbank unter `/var/lib/brokershield` (überlebt Updates)
- prüft selbst: Service aktiv + Web-UI antwortet (HTTP-Check) + finale URL

Erwartete Ausgabe am Ende:

```
========================================================================
  Installation abgeschlossen ✔  —  Deine Daten. Deine Hoheit.
------------------------------------------------------------------------
  Web-UI   :  http://<CT-IP>:8080
  Login    :  Passwort 'brokershield' (bitte sofort ändern!)
  ...
========================================================================
```

**Login-Passwort ändern:** `pct enter <CTID>` → `EDITOR=nano systemctl edit brokershield` oder direkt `/etc/brokershield/brokershield.env` → `BROKERSHIELD_ADMIN_PASSWORD=...` → `systemctl restart brokershield`.

## Erste Schritte in der UI

1. **Profil anlegen** (`/profiles/new`): Name, Adresse, E-Mail – dient Brokern zur Identifikation. Bleibt lokal in der SQLite-DB.
2. **Broker aussuchen** (`/brokers`): filterbar nach Region (eu/us/global) und Name; 13 global + 751 US + 8 kuratierte EU.
3. **Anfrage erzeugen** (`/requests/new`): Rechtsgrundlage wählen (in DE: DSGVO Art. 17), Text wird automatisch erzeugt.
4. **Versenden**: per SMTP (falls konfiguriert) oder Text kopieren und an die Broker-E-Mail / übers Opt-out-Formular senden.
5. **Status pflegen** und **Wiedervorlagen** abarbeiten (`/rechecks`): Broker tauchen wieder auf → Status „wieder-aufgetaucht“ und erneut anfragen.

## Ollama (optional, extern)

BrokerShield hostet selbst kein LLM (spart RAM im LXC). Stattdessen in den Einstellungen die URL eines vorhandenen Ollama-Servers eintragen, z. B.:

```
BROKERSHIELD_OLLAMA_URL=http://192.168.1.50:11434
BROKERSHIELD_OLLAMA_MODEL=llama3.1:8b
```

Dann hilft der Assistent (`/assistant`) beim Formulieren von Nachfass-Erinnerungen und Datenschutz-Fragen.

## SMTP (optional)

Für direkten Mailversand aus der UI (z. B. Gmail mit App-Password):

```
BROKERSHIELD_SMTP_HOST=smtp.gmail.com
BROKERSHIELD_SMTP_PORT=587
BROKERSHIELD_SMTP_FROM=du@gmail.com
BROKERSHIELD_SMTP_USER=du@gmail.com
BROKERSHIELD_SMTP_PASSWORD=<16-stelliges App-Passwort>
```

Ohne SMTP: Anfragetexte einfach aus der Detailseite kopieren. Hinweis: Gmail erlaubt ~500 Mails/Tag – Bulk-Versand besser auf mehrere Tage verteilen (siehe Broker-Detail „manuell“).

## Update

Einzeiler erneut auf dem Proxmox-Host ausführen – der Installer erkennt den vorhandenen Container automatisch und installiert den neuesten Stand (Datenbank bleibt erhalten). Oder gezielt:

```bash
./brokershield.sh --update
```

## Deinstallation

```bash
./brokershield.sh --uninstall   # fragt interaktiv nach Bestätigung
```

Entfernt den Container inklusive aller Daten (Profile, Anfrage-Historie).

## Troubleshooting

- **Volles Trace-Log bei Fehlern:** `DEBUG=1 bash -c "$(wget -qLO - …)"` schreibt jede Anweisung mit.
- Log auf dem Host: `/tmp/brokershield-install-*.log` · Log im Container: `/var/log/brokershield-install.log`
- `journalctl -u brokershield -n 100` im Container (`pct enter <CTID>`)
- Bei Installationsfehlern gibt das Script automatisch die komplette Fehlerkette aus: Exit-Code, fehlgeschlagener Befehl, Call-Stack, Service-Status, Ports, Log-Auszüge.

## Akzeptanztest / Reboot-Verifikation

Nach der Installation einmal durchführen und die Ausgaben belegen:

```bash
# 1. Service-Status im Container
pct exec <CTID> -- systemctl is-active brokershield
# erwartet: active

# 2. HTTP-Check im Container
pct exec <CTID> -- curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8080/healthz
# erwartet: 200

# 3. Container-Config: Autostart
pct config <CTID> | grep onboot
# erwartet: onboot: 1

# 4. Reboot-Test: Container neu starten und erneut prüfen
pct reboot <CTID> && sleep 15
pct exec <CTID> -- systemctl is-active brokershield
curl -s -o /dev/null -w '%{http_code}\n' http://<CT-IP>:8080/healthz
# erwartet: active bzw. 200 – Web-UI nach Reboot wieder erreichbar
```

Beispiel-Beleg (Soll-Ausgabe):

```
$ pct exec 160 -- systemctl is-active brokershield
active
$ pct config 160 | grep onboot
onboot: 1
$ curl -s -o /dev/null -w '%{http_code}\n' http://192.168.1.60:8080/healthz
200
```

## Projektstruktur

```
install/brokershield.sh   # Proxmox-Einzeiler-Installer (Host- + Gast-Phase)
deploy/brokershield.service  # systemd-Unit (Referenz; Installer schreibt sie selbst)
app/                      # FastAPI-App (routers, templates, static)
app/data/brokers_seed.json # 764 Broker aus eraser (MIT)
app/seed.py               # + 8 kuratierte EU-/DE-Broker
tests/                    # pytest-Testschutz (8 Tests)
```

## Quellen & Lizenzen

- Broker-Seed: [digisamroc/eraser](https://github.com/digisamroc/eraser) (MIT) – automatische Löschungsanfragen an 750+ Broker
- Konzept-Inspiration: [k7cfo/remove-your-data](https://github.com/k7cfo/remove-your-data) (AGPL) – First-Party-Opt-outs; nicht als Code übernommen (AGPL + „Do not fork“)
- BrokerShield selbst: MIT

**Keine Rechtsberatung.** Nicht jeder Broker muss reagieren; Fristen variieren (DSGVO: i. d. R. 30 Tage). Datenbroker re-scrapen – regelmäßig erneut prüfen.
