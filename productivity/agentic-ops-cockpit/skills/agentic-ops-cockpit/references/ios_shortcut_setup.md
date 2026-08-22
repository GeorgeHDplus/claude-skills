# iOS-Zugriff einrichten — Kurzbefehle + Siri

Schritt-für-Schritt-Anleitung für die iPhone-Seite des Cockpits. Am Ende hast du:

- **einen Haupt-Kurzbefehl „Cockpit"** — nimmt Text oder Siri-Diktat entgegen, schickt ihn an den Worker, zeigt die Antwort als Mitteilung, fragt bei bestätigungspflichtigen Aktionen nach
- **Mini-Kurzbefehle** für feste Phrasen („Cockpit Feierabend", „Cockpit Status", „Cockpit Tages-Summary") — je ein Satz zu Siri, kein Tippen
- **Siri-Sprachtrigger** für alles davon
- **einen Executor-Kurzbefehl „Cockpit Ausführen"** — dreht die Richtung um: holt `phone.*`-Aktionen ab, die das Cockpit für dein iPhone gequeued hat, und führt sie phone-seitig aus

Die iOS-Aktionsnamen stehen auf Deutsch mit dem englischen Original in Klammern — falls Apple die Übersetzungen mal wieder ändert.

## Voraussetzungen

1. Worker ist deployed und der Smoketest ist grün — sonst debuggst du nachher am iPhone, was eigentlich ein Server-Problem ist:
   ```bash
   python3 scripts/cockpit_smoketest.py --url https://cockpit-worker.<sub>.workers.dev --token <SHORTCUT_TOKEN>
   ```
   (Deployment: [`worker_deployment.md`](worker_deployment.md))
2. `SHORTCUT_TOKEN` liegt bereit (erzeugt mit `scripts/generate_secrets.py`).
3. iPhone mit iOS 17+ und der App **Kurzbefehle** (Shortcuts).

## Der Request-Kontrakt

Was der Kurzbefehl sendet und zurückbekommt. Referenz-Implementierung zum Nachschlagen und Vorab-Testen am Rechner: `scripts/shortcut_payload_builder.py --curl`.

**`POST /ask`** — Header `Authorization: Bearer <SHORTCUT_TOKEN>`, `Content-Type: application/json`

```json
{"prompt": "Feierabend", "source": "shortcut", "device": "iphone"}
```

Antwort:

```json
{
  "trace_id": "3f2a…",
  "status": "done | needs_confirmation",
  "reply": "Kompakte deutsche Antwort für die Mitteilung",
  "results": [{"action": "summary.day", "result": {…}}],
  "pending": [{"action": "pc.sleep", "params": {}}]
}
```

**`POST /confirm`** — gleiche Header

```json
{"trace_id": "3f2a…"}
```

Wichtig: Bestätigungen sind **60 Sekunden** gültig (Guard-Block). Danach antwortet der Worker mit HTTP 410 und die Aktion muss neu angestoßen werden.

## Haupt-Kurzbefehl „Cockpit"

Neuen Kurzbefehl anlegen, Name exakt **„Cockpit"** — der Name ist gleichzeitig die Siri-Phrase.

### Eingabe-Konfiguration

Oben über die Info-/Detailansicht des Kurzbefehls:

- **„Bei Teilen anzeigen" / Eingabe empfangen** (Receive input): **Text**
- **„Wenn keine Eingabe"** (If there's no input): **„Nach Text fragen"** (Ask for Text), Hinweistext: `Was soll das Cockpit tun?`

Damit funktioniert derselbe Kurzbefehl in drei Modi: per Siri diktiert, per Tipp mit Abfrage, und von Mini-Kurzbefehlen mit fester Phrase aufgerufen.

### Aktionen (in dieser Reihenfolge)

1. **„Inhalt der URL abrufen"** (Get Contents of URL)
   - URL: `https://cockpit-worker.<sub>.workers.dev/ask`
   - **Methode**: `POST`
   - **Header** (aufklappen → „Header hinzufügen"):
     - `Authorization` = `Bearer <SHORTCUT_TOKEN>` (Wort „Bearer", Leerzeichen, Token — direkt hier einfügen, nirgendwo sonst speichern)
   - **Body anfordern** (Request Body): `JSON`, drei Felder:
     - `prompt` = Variable **„Kurzbefehl-Eingabe"** (Shortcut Input)
     - `source` = `shortcut`
     - `device` = `iphone`
   - `Content-Type: application/json` setzt iOS bei JSON-Body automatisch.

2. **„Wert aus Wörterbuch abrufen"** (Get Dictionary Value) — Schlüssel `status` aus „Inhalt der URL" → **„Variable festlegen"** (Set Variable): `Status`

3. **„Wert aus Wörterbuch abrufen"** — Schlüssel `reply` aus „Inhalt der URL" → Variable `Antwort`

4. **„Wert aus Wörterbuch abrufen"** — Schlüssel `trace_id` aus „Inhalt der URL" → Variable `TraceID`

5. **„Wenn"** (If): `Status` **ist** `needs_confirmation`

6. *(Innerhalb von „Wenn")* **„Aus Menü auswählen"** (Choose from Menu)
   - Hinweis/Titel: Variable `Antwort`
   - Menüpunkte: **„Ausführen"** und **„Abbrechen"**

7. *(Unter „Ausführen")* **„Inhalt der URL abrufen"**
   - URL: `https://cockpit-worker.<sub>.workers.dev/confirm`
   - Methode `POST`, Header wie in Aktion 1
   - Body `JSON`, ein Feld: `trace_id` = Variable `TraceID`
   - Danach **„Ergebnis anzeigen"** (Show Result) mit „Inhalt der URL" — zeigt das Ausführungsergebnis.

8. *(Unter „Abbrechen")* **„Benachrichtigung anzeigen"** (Show Notification): `Abgebrochen — nichts ausgeführt.`

9. *(„Andernfalls"-Zweig / Otherwise)* **„Benachrichtigung anzeigen"**
   - Titel: `Cockpit`
   - Text: Variable `Antwort`, neue Zeile, `Trace: ` + Variable `TraceID`

10. **„Wenn beenden"** (End If)

Die Trace-ID gehört sichtbar in jede Mitteilung — ohne sie ist kein Debugging über Worker-Log und Datadog möglich (Anti-Pattern aus dem Skill: „Shortcut ohne Trace-ID-Anzeige").

### Test

Kurzbefehl antippen → Eingabe `Was läuft gerade auf Spotify?` → nach 2–10 s kommt die Mitteilung mit Antwort + Trace-ID. Dann der Bestätigungspfad: Eingabe `PC in Standby` → Menü „Ausführen?/Abbrechen" erscheint. Solange der PC-Handler noch nicht steht, liefert „Ausführen" sauber `not_configured` zurück — genau richtig, die iOS-Kette ist damit end-to-end verifiziert.

## Siri-Sprachtrigger

- **„Hey Siri, Cockpit"** funktioniert sofort — der Kurzbefehl-Name ist die Phrase. Siri fragt „Was soll das Cockpit tun?" und nimmt die Antwort als Diktat.
- Siri liest anschließend den Mitteilungstext vor — mehr Voice-Feedback gibt es nicht (bekannte Grenze, siehe SKILL.md).

### Mini-Kurzbefehle für feste Phrasen

Je ein Kurzbefehl mit **einer** Aktion:

1. **„Kurzbefehl ausführen"** (Run Shortcut) → Kurzbefehl: `Cockpit` → **Eingabe** (Input): fester Text, z. B. `Feierabend`

Empfohlene drei:

| Name (= Siri-Phrase) | Eingabe-Text |
|---|---|
| `Cockpit Feierabend` | `Feierabend` |
| `Cockpit Status` | `Wie geht es dem PC? Status bitte.` |
| `Cockpit Tages-Summary` | `Tages-Summary` |

„Hey Siri, Cockpit Feierabend" läuft dann ohne jede Rückfrage bis zum Bestätigungs-Menü für `pc.sleep`.

### Screenshot anzeigen (eigener Kurzbefehl „Cockpit Bildschirm")

Ein Screenshot ist kein Text — der generische „Cockpit"-Kurzbefehl zeigt nur `reply` und würde das Bild **nicht** darstellen. Das Bild steckt in der `/ask`-Antwort unter `results` → dem Element mit `action = pc.screenshot` → `result.image_base64` (Base64-JPEG). Dafür ein eigener Mini-Kurzbefehl mit Bild-Flow:

1. **„Inhalt der URL abrufen"** — `POST …/ask` mit Header + Body wie im Haupt-Kurzbefehl, Prompt fest: `Mach einen Screenshot vom primären Monitor` (für den zweiten: „… vom sekundären Monitor").
2. **„Wörterbuchwert abrufen"** — Schlüssel `results` aus „Inhalt der URL" → Liste.
3. **„Wiederhole mit jedem"** über `results`:
   - **„Wörterbuchwert abrufen"** Schlüssel `result` aus dem Wiederholungselement, dann erneut **„Wörterbuchwert abrufen"** Schlüssel `image_base64`.
   - **„Wenn"** „hat einen Wert" → **„Variable festlegen"** `Bild64`.
4. **„Base64 codieren"** mit Umschalter auf **Decodieren** angewandt auf `Bild64` → Bilddaten.
5. **„Schnellansicht"** (Quick Look) auf die Bilddaten → zeigt den Screenshot.

Bis der PC-Handler steht, kommt `not_configured` zurück und `Bild64` bleibt ungesetzt — dann als Fallback eine Mitteilung mit `reply` zeigen. (Base64 hält die Payload klein: `screenshot.jpeg_quality`/`max_width` in der Handler-`config.json` steuern die Größe; die R2-URL-Variante ist in der Handler-README beschrieben.)

### Schneller Zugriff ohne Siri

- **Home-Bildschirm**: Kurzbefehl-Details → „Zum Home-Bildschirm" — Cockpit als App-Icon.
- **Widget**: Kurzbefehle-Widget auf den Home-/Sperrbildschirm, „Cockpit" auswählen.
- **Action Button** (iPhone 15 Pro+): Einstellungen → Aktionstaste → Kurzbefehl → `Cockpit`.

## Das iPhone als Aktor — Executor-Kurzbefehl „Cockpit Ausführen"

Bis hierhin steuert das iPhone den Stack. Die **Outbox** dreht die Richtung um: `/ask` kann `phone.*`-Aktionen queuen (Mitteilung zeigen, Playlist starten, Fokus setzen), und dieser zweite Kurzbefehl holt sie ab und führt sie aus. Wichtig fürs Erwartungsmanagement: iOS lässt sich nicht von außen fernsteuern — Apple erlaubt das niemandem. Kurzbefehle sind der sanktionierte Weg, und die Whitelist gilt auch hier: Der Executor führt **nur** Aktionen aus, für die er einen expliziten „Wenn"-Zweig hat; alles andere wird ignoriert.

### Aktionen

1. **„Inhalt der URL abrufen"** — `GET https://cockpit-worker.<sub>.workers.dev/outbox`, Header `Authorization` wie im Haupt-Kurzbefehl, **kein Body** (Methode GET). Vorab am Rechner testbar: `python3 scripts/shortcut_payload_builder.py --outbox --curl`
2. **„Wert aus Wörterbuch abrufen"** — Schlüssel `items` → Variable `Aktionen`
3. **„Mit jedem Element wiederholen"** (Repeat with Each) über `Aktionen`:
   - „Wert aus Wörterbuch abrufen": `action` aus „Wiederholungselement" → Variable `Slug`; ebenso `params`
   - **„Wenn"** `Slug` ist `phone.notify` → **„Benachrichtigung anzeigen"** mit `params.text` (Titel: `params.title`)
   - **„Wenn"** `Slug` ist `phone.play_playlist` → Apple Music: **„Musik abspielen"** mit Playlist `params.name`; Spotify: **„URL öffnen"** mit dem Playlist-Link oder die Spotify-Shortcut-Aktion
   - **„Wenn"** `Slug` ist `phone.set_focus` → **„Fokus festlegen"** (Set Focus) auf `params.name`
4. **„Ende Wiederholen"**

### Wann läuft der Executor?

- **Empfohlen:** Als letzte Aktion im Haupt-Kurzbefehl „Cockpit" ein **„Kurzbefehl ausführen"** → `Cockpit Ausführen` anhängen. Dann wird alles, was dein `/ask` gerade gequeued hat, **im selben Lauf** ausgeführt — gefühlt null Latenz.
- **Zeit-Automationen** (Kurzbefehle → Automation → Tageszeit, mehrere Uhrzeiten anlegen, „Sofort ausführen" aktivieren) für regelmäßiges Abholen ohne Zutun.
- **Push von außen** (optional): Wenn nicht dein iPhone, sondern eine andere Quelle queuet und es sofort passieren soll, kann eine App wie Pushcut (Free-Tier) per Server-Push einen Kurzbefehl anstoßen. Für den Normalfall unnötig.

### Eigenschaften (ehrlich)

- **Abholung leert die Outbox** (at-most-once): Bricht der Executor mitten im Lauf ab, sind die abgeholten Aktionen weg. Für benigne, selbst-anzeigende Aktionen die richtige Wahl — lieber verlieren als doppeln.
- Max. 20 Einträge, 24 h TTL — die Outbox ist ein Briefkasten, kein Archiv.
- Stärkere Phone-Aktionen (Nachricht senden, Anruf, …) sind bewusst **nicht** in der Whitelist. Wer sie ergänzt: `requires_confirmation: true` in `tools.js` **und** eigener „Wenn"-Zweig im Executor — beides.

## Secret-Disziplin am iPhone

- Der Token lebt **ausschließlich im Header-Feld des Kurzbefehls** — nicht in iCloud-Notizen, nicht in einer Textdatei, nicht im Verlauf eines Messengers.
- Kurzbefehl **niemals per Link/Galerie teilen** — der Token wandert sonst mit. Wenn es doch passiert ist: Token sofort rotieren (`generate_secrets.py --only shortcut`, `wrangler secret put SHORTCUT_TOKEN`, Header im Kurzbefehl aktualisieren).
- iCloud-Sync der Kurzbefehle auf eigene Geräte ist in Ordnung.

## Grenzen der iOS-Seite (ehrlich)

- **60-Sekunden-Timeout**: Länger darf der Worker nicht brauchen, sonst bricht iOS ab. Der Worker hält dafür jede Aktion unter 15 s und den Claude-Loop unter 3 Runden. Langläufer brauchen später ein Job-Muster mit Push-Nachreichung.
- **Keine echten Buttons in Mitteilungen**: Kurzbefehle können keine actionable Notifications erzeugen. Die Bestätigung läuft deshalb als Menü **im selben Lauf** (Aktion 6). Die Push-Variante mit separatem Confirm-Kurzbefehl ist Stufe-2-Ausbau.
- **Kein Hintergrund-Polling**: Der Kurzbefehl lebt nur, solange er läuft.

## Troubleshooting

| Symptom | Ursache | Fix |
|---|---|---|
| HTTP 401 | Token falsch/fehlt, „Bearer " vergessen | Header prüfen: exakt `Bearer <Token>`; Token gegen `wrangler secret` abgleichen |
| HTTP 429 | > 20 Requests/Minute | Guard-Rate-Limit — kurz warten; Schleifen im Kurzbefehl suchen |
| HTTP 410 bei Bestätigen | > 60 s bis zum Tipp auf „Ausführen" | Aktion neu anstoßen; Bestätigung zügig beantworten |
| Timeout nach ~60 s | Worker/Claude zu langsam, Aktion hängt | `wrangler tail` mit der Trace-ID; 15-s-Aktions-Timeout greift normal vorher |
| Mitteilung leer / „Wörterbuch"-Fehler | Antwort war kein JSON (z. B. HTML-Fehlerseite) | URL prüfen (`/ask`, nicht `/`); `cockpit_smoketest.py` laufen lassen |
| `not_configured` als Antwort | Zielsystem hat noch keine Secrets | Erwartet — [`worker_deployment.md`](worker_deployment.md) Schritt 4/5 für das jeweilige System |
| Siri versteht den Namen nicht | Phrase kollidiert mit App-Namen | Kurzbefehl umbenennen (z. B. „Ops Cockpit"), Phrase = neuer Name |

Debug-Reihenfolge bleibt immer: **Worker-Log (`wrangler tail`) → Handler-Log → Datadog**, mit der Trace-ID aus der Mitteilung als rotem Faden.
