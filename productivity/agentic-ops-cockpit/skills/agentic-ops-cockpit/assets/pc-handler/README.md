# cockpit-pc-handler

Die Windows-Gegenstelle des Cockpit-Workers: nimmt HMAC-signierte Whitelist-Aktionen entgegen und führt sie **mit User-Rechten** aus. Läuft hinter einem Cloudflare Tunnel auf `127.0.0.1` — kein offener Port.

> **Verifikationshinweis (ehrlich):** Diese PowerShell-Skripte werden in der CI dieses Repos **nicht** ausgeführt (kein Windows/PowerShell dort). Die kritischste Kompatibilität — die HMAC-Signatur zwischen Worker und Handler — ist über einen Testvektor gegen den echten Worker-Code abgesichert (`scripts/hmac_test_vector.py`). Den Handler selbst verifizierst du beim ersten Start auf dem PC mit dem `curl`-Test unten.

## Handler-Aktionen

| Slug | Tut | Hinweis |
|---|---|---|
| `pc.status` | Uptime, CPU-Last, RAM, aktiver User | read-only, idempotent |
| `pc.sleep` | PC in Standby | löst verzögert (2 s) aus → Handler antwortet sofort, kein Worker-Timeout |
| `pc.run_script` | startet ein Skript aus der Config-Map | detached (kann Minuten laufen); nur die 4 Whitelist-Namen |
| `pc.screenshot` | Desktop als Base64-JPEG | self-contained, keine R2-Infra nötig |

`pc.wake` ist **nicht** hier — der PC schläft ja; Wake läuft LAN-seitig über `PC_WAKE_WEBHOOK_URL` im Worker.

## Setup

```powershell
# 1. Config anlegen und Skript-Pfade eintragen
copy config.example.json config.json
notepad config.json

# 2. HMAC-Secret ablegen (PC_HMAC_SECRET aus generate_secrets.py),
#    ACL auf nur dich einschraenken
$home = "$env:USERPROFILE\cockpit"
New-Item -ItemType Directory -Force $home | Out-Null
Set-Content "$home\secret.key" "<PC_HMAC_SECRET>" -NoNewline
icacls "$home\secret.key" /inheritance:r /grant:r "$($env:USERNAME):(R)"

# 3. Handler starten (NICHT als Admin)
.\START-HIER.bat
```

**Falls `START-HIER.bat` mit „URL-ACL fehlt" (`HttpListenerException`) abbricht:** Windows lässt einen Nicht-Admin das HTTP.sys-Prefix nur binden, wenn es einmal reserviert wurde. Der Handler gibt dann den genauen Befehl aus — einmalig in einer **Admin**-Shell, danach wieder ohne Admin starten:

```powershell
netsh http add urlacl url=http://127.0.0.1:8787/ user=%USERDOMAIN%\%USERNAME%
```

(Nur nötig, wenn der Bind fehlschlägt — auf vielen Systemen geht der Loopback-Prefix auch ohne Reservierung.)

Dann den Cloudflare Tunnel auf `http://127.0.0.1:8787` zeigen lassen und im Worker `PC_HANDLER_URL` + `PC_HMAC_SECRET` setzen — Schritt 5 in [`../../references/worker_deployment.md`](../../references/worker_deployment.md).

## Ersten Kontakt testen (ohne iPhone, ohne Worker)

Signierten Request lokal erzeugen und direkt gegen den Handler schicken:

```bash
# Auf einem Rechner mit deinem echten Secret:
python3 ../../scripts/hmac_test_vector.py \
  --secret "$(cat ~/cockpit/secret.key)" --ts now \
  --body '{"action":"pc.status","params":{},"trace_id":"t-local"}' \
  --curl --url http://127.0.0.1:8787
# -> den ausgegebenen curl-Befehl ausfuehren; erwartet: 200 + Status-JSON
```

Wichtig: `--ts now`, weil der Handler ein 90-Sekunden-Zeitfenster erzwingt. Ein `401` ist fast immer **Uhrzeit-Drift** — auf dem PC `w32tm /resync`.

## Guard-Block (redundant zum Worker — zwei Locations, absichtlich)

- **Whitelist** (`$ALLOWED` im Handler): nur `pc.status|pc.sleep|pc.run_script|pc.screenshot`; alles andere → `403`. Die Worker-Whitelist zählt hier nicht.
- **Kein RCE**: Es wird nur `actions/<slug>.ps1` aufgerufen; `pc.run_script` startet ausschließlich benannte Skripte aus `config.json`, nie einen übergebenen Pfad.
- **HMAC-Pflicht**: `<timestamp>.<roher-body>`, 90-s-Fenster, konstanter Vergleich → sonst `401`.
- **Kill-Switch**: Datei `%COCKPIT_HOME%\KILL` anlegen → Handler antwortet auf alles mit `503`. Löschen reicht zum Reaktivieren, kein Neustart.
- **User-Rechte**: kein Admin. Läuft der Handler doch als Admin, warnt er laut und loggt es. Braucht eine künftige Aktion Elevation → separate Service-Ebene mit noch engerer Whitelist, nicht diesen Handler hochstufen.
- **Audit-Log**: `%COCKPIT_HOME%\logs\handler.log`, eine JSON-Zeile pro Ereignis (`trace_id`, `action`, `verdict`, `duration_ms`) — nie Secrets, nie Body-Inhalte.

## Neue Handler-Aktion (Cockpit-Drei-Stufen-Muster)

1. `assets/worker/src/tools.js` — Tool-Definition
2. `assets/worker/src/actions.js` — Router-Case → `callPcHandler`
3. **hier**: `actions/<slug>.ps1` mit `param($Params, $Config)`, gibt eine `@{}`-Hashtable zurück; **und** den Slug in `$ALLOWED` von `cockpit-handler.ps1` eintragen (die Datei allein reicht nicht — Whitelist ist explizit)

Disziplin: idempotent; ≤ 15 s zurückkehren (Langläufer detached starten wie `pc.run_script`, blockierende System-Calls verzögert auslösen wie `pc.sleep`); keine Roh-Ausgaben auf die Pipeline (verschmutzt die JSON-Antwort).

## Screenshot: Base64 vs. R2

Default ist **Base64-JPEG** in der Antwort — self-contained, keine Zusatz-Secrets. Für sehr große Screens steuern `screenshot.max_width` und `screenshot.jpeg_quality` in der Config die Payload-Größe. Wer stattdessen eine kurzlebige **R2-URL** will (wie im Cockpit-Skill Beispiel 2): in `pc.screenshot.ps1` das Bild nach R2 laden und `@{ status='ok'; url=<presigned> }` zurückgeben — bewusst nicht Default, um R2-Credentials auf dem PC zu vermeiden.

## Dateien

- `cockpit-handler.ps1` — Listener, HMAC-Verifikation, Kill-Switch, Whitelist, Routing, Audit-Log
- `lib/hmac.ps1` — `Get-CockpitHmac` + konstanter Vergleich (Gegenstück zu `guard.js`)
- `actions/*.ps1` — je eine Whitelist-Aktion
- `config.example.json` — Port, `cockpit_home`, Skript-Map, Screenshot-Optionen
- `START-HIER.bat` — Launcher (User-Rechte, pwsh→powershell-Fallback)
