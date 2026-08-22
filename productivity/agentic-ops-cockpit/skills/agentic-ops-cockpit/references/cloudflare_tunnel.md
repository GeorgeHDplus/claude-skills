# Cloudflare Tunnel + Access — den PC-Handler sicher erreichbar machen

Der Worker läuft in Cloudflares Cloud, der PC-Handler auf `127.0.0.1:8787` hinter Georges Router. Der Tunnel verbindet beide, **ohne einen Port zu öffnen**: `cloudflared` baut auf dem PC eine ausgehende Verbindung zu Cloudflare auf, und Requests an `https://cockpit-pc.<domain>` fließen durch diese Verbindung zum lokalen Handler zurück.

Das allein macht den Handler aber weltweit erreichbar. Deshalb steht **Cloudflare Access** davor: eine Service-Token-Policy, die alles außer dem Worker schon am Edge abweist. Erst dahinter greift die HMAC des Handlers.

```
iPhone ─► Worker ─HTTPS+ServiceToken─► Cloudflare Edge ─Access-Policy─► Tunnel ─► 127.0.0.1:8787
                                            │                                         │
                                    weist Fremde ab (403)                      HMAC-Pflicht (401)
```

**Zwei Schichten, klare Rollen:** Access = Edge-Filter (nur der Worker kommt überhaupt durch), HMAC = Request-Authentifizierung am Handler (signiert den konkreten Aufruf, 90-s-Fenster). Access **ersetzt die HMAC nicht** — fällt eine Schicht aus, hält die andere.

## Voraussetzungen

- Eine Domain (Zone) in deinem Cloudflare-Account (Free-Plan genügt, auch für Access/Zero Trust bis 50 Nutzer).
- `cloudflared` auf dem PC: `winget install --id Cloudflare.cloudflared`.
- Der PC-Handler läuft und ist lokal erreichbar (`assets/pc-handler/`, `curl`-Test grün).

## Schritt 1 — Tunnel einrichten

Aus [`../assets/tunnel/`](../assets/tunnel/):

```powershell
.\setup-cloudflared.ps1 -Hostname cockpit-pc.example.com
```

Das Skript ist idempotent und erledigt: Login (Browser, Zone wählen) → Tunnel `cockpit-pc` anlegen (falls fehlt) → `config.yml` aus dem Template befüllen → DNS-Route (CNAME auf den Tunnel) → Ingress validieren → in einer Admin-Shell zusätzlich `cloudflared service install` für den Autostart.

Zum Testen im Vordergrund statt als Dienst: `cloudflared tunnel run cockpit-pc`.

Nach diesem Schritt ist `https://cockpit-pc.example.com` erreichbar — **noch ungeschützt**. Weiter mit Schritt 2, bevor du `PC_HANDLER_URL` im Worker setzt.

## Schritt 2 — Cloudflare Access davor (Sicherheitskern)

Ziel: nur Requests mit einem gültigen **Service Token** dürfen den Hostname erreichen. Der Worker sendet diesen Token als zwei Header; alles andere fängt Access am Edge ab.

### 2a. Service Token erzeugen

Cloudflare-Dashboard → **Zero Trust** → **Access** → **Service Auth** → **Create Service Token**:

- Name z. B. `cockpit-worker`.
- Cloudflare zeigt **Client ID** und **Client Secret** genau einmal — beide kopieren.

### 2b. Access Application für den Hostname

Zero Trust → **Access** → **Applications** → **Add an application** → **Self-hosted**:

- **Application domain:** `cockpit-pc.example.com`.
- **Policy** anlegen: Action **Service Auth**, Include-Regel **Service Token** → den eben erzeugten `cockpit-worker`-Token wählen.
- Wichtig: keine weitere „Allow"-Policy mit E-Mail/IdP hinzufügen — sonst gäbe es einen zweiten Weg hinein. Nur Service Auth.

Damit gilt: Requests ohne gültige `CF-Access-Client-Id` + `CF-Access-Client-Secret` → **403** am Edge, bevor sie den Tunnel erreichen.

### 2c. Token in den Worker

```bash
npx wrangler secret put CF_ACCESS_CLIENT_ID       # die Client ID
npx wrangler secret put CF_ACCESS_CLIENT_SECRET   # das Client Secret
# dev analog mit --env dev
```

Der Worker hängt beide Header automatisch an jeden Handler-Call (`callPcHandler` in `assets/worker/src/actions.js`), sobald die Secrets gesetzt sind — sonst lässt er sie weg (abwärtskompatibel, aber dann ist der Hostname ungeschützt).

## Schritt 3 — Worker mit dem Tunnel verbinden

```bash
# In wrangler.toml:
PC_HANDLER_URL = "https://cockpit-pc.example.com"

npx wrangler secret put PC_HMAC_SECRET   # derselbe Wert wie in %COCKPIT_HOME%\secret.key
npx wrangler deploy --env dev
```

## Schritt 4 — End-to-End testen

**Ohne Token muss Access abweisen** (403, HTML von der Edge — nicht vom Handler):

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://cockpit-pc.example.com/action
# erwartet: 403
```

**Mit Service Token + HMAC muss der Handler antworten:**

```bash
# HMAC signieren (mit deinem echten PC_HMAC_SECRET):
python3 ../scripts/hmac_test_vector.py --secret "$(cat ~/cockpit/secret.key)" --ts now \
  --body '{"action":"pc.status","params":{},"trace_id":"t-tunnel"}' --json
# die Signatur + timestamp aus der Ausgabe unten einsetzen:

curl -sS -X POST https://cockpit-pc.example.com/action \
  -H 'content-type: application/json' \
  -H "CF-Access-Client-Id: <CLIENT_ID>" \
  -H "CF-Access-Client-Secret: <CLIENT_SECRET>" \
  -H "x-cockpit-timestamp: <TS>" \
  -H "x-cockpit-signature: <SIG>" \
  --data-binary '{"action":"pc.status","params":{},"trace_id":"t-tunnel"}'
# erwartet: 200 + Status-JSON
```

Danach der echte Pfad über den Worker: `cockpit_smoketest.py --ask` mit einem Prompt wie „Status vom PC bitte" → die Antwort enthält die Handler-Daten statt `not_configured`.

## Betrieb

- **Dienst:** `cloudflared` läuft als Autostart-Dienst; Status `Get-Service cloudflared`, Logs `cloudflared tunnel info cockpit-pc` bzw. Windows-Ereignisanzeige.
- **Handler down:** Tunnel steht, aber Origin (Handler) antwortet nicht → Cloudflare liefert **502**. Der Worker gibt das als HTTP-Fehler ans iPhone; Handler mit `START-HIER.bat` starten.
- **Kill-Switch bleibt lokal:** Die `KILL`-Datei stoppt den Handler (503) unabhängig vom Tunnel — der Tunnel transportiert nur.

## Troubleshooting

| Symptom | Ursache | Fix |
|---|---|---|
| Worker meldet `access_denied` | Service-Token-Header fehlen/falsch, oder Access-Policy erlaubt sie nicht | `CF_ACCESS_CLIENT_ID/SECRET` prüfen; Policy = Service Auth mit genau diesem Token |
| `curl` ohne Token gibt 200 statt 403 | Access Application deckt den Hostname nicht (Domain-Tippfehler) oder zusätzliche Allow-Policy | Application-Domain exakt `cockpit-pc.<domain>`; nur die Service-Auth-Policy behalten |
| 502 vom Hostname | Handler läuft nicht / falscher Port | Handler starten; `config.yml` `service: http://127.0.0.1:<port>` gegen Handler-`config.json` abgleichen |
| 401 trotz gültigem Access | HMAC — meist Uhrzeit-Drift auf dem PC | `w32tm /resync`; `hmac_test_vector.py` Self-Check muss PASS sein |
| `cloudflared: command not found` | nicht installiert / nicht im PATH | `winget install --id Cloudflare.cloudflared`, Shell neu öffnen |

## Sicherheitshinweise

- **Access ist keine Ausrede, die HMAC zu lockern.** Beide Schichten bleiben. Wäre der Service Token geleakt, hielte die HMAC den Handler; wäre das HMAC-Secret geleakt, hielte Access den Hostname.
- **Token-Rotation:** Service Token im Dashboard neu erzeugen → alte Anwendung invalidieren → `wrangler secret put` beider Werte. HMAC-Rotation getrennt (siehe `security_model.md`).
- **Keine zweite Access-Policy** mit E-Mail/IdP am selben Hostname — sie öffnete einen menschlichen Login-Weg zum Handler, der nicht gebraucht wird.
- **Nur der Cockpit-Hostname** läuft durch diesen Tunnel; die Ingress-catch-all-Regel gibt für alles andere 404.
