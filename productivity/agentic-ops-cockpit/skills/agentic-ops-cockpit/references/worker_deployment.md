# Worker-Deployment — Cloudflare-Seite des iOS-Zugriffs

Der Worker in [`../assets/worker/`](../assets/worker/) ist die Gegenstelle des iPhone-Shortcuts: Auth, Rate-Limit, Claude-Call mit Tool-Whitelist, Action-Routing, Audit-Log. Zero-Dependency — kein `package.json`, kein Build.

## Schritt 0 — Voraussetzungen

- Cloudflare-Account (Free-Plan reicht für Stufe 1)
- Node 18+ (`npx wrangler` lädt die CLI on demand), `npx wrangler login` einmal ausgeführt
- Anthropic-API-Key (console.anthropic.com)
- Zwei Verzeichnisse im Spiel: das **Skill-Verzeichnis** (enthält `scripts/`, `references/`, `assets/`) für die Helfer-Skripte, und eine **Kopie des Workers** als Deployment-Verzeichnis. Die `wrangler`-Befehle laufen in der Kopie, die `python3 scripts/…`-Helfer bleiben im Skill-Verzeichnis (nur dort liegt `scripts/`).
  ```bash
  cp -r assets/worker ~/cockpit-worker   # Deployment-Verzeichnis; NICHT hineinwechseln für die Helfer
  ```

## Schritt 1 — Secrets erzeugen

```bash
# Aus dem Skill-Verzeichnis (hier liegt scripts/), nicht aus ~/cockpit-worker:
python3 scripts/generate_secrets.py
```

Erzeugt `SHORTCUT_TOKEN` (iPhone → Worker) und `PC_HMAC_SECRET` (Worker → PC-Handler, wird erst in Schritt 5 gebraucht). Beide 32 Byte Entropie — Guard-Block-Minimum.

## Schritt 2 — KV-Namespace anlegen

KV trägt den Confirm-Flow (Pending-Aktionen, 60 s TTL) und das Rate-Limit. Ohne KV kein `needs_confirmation`-Pfad. Die `wrangler`-Befehle ab hier laufen im Deployment-Verzeichnis (`cd ~/cockpit-worker`).

```bash
npx wrangler kv namespace create COCKPIT_KV
npx wrangler kv namespace create COCKPIT_KV --env dev
```

Die beiden ausgegebenen IDs in `wrangler.toml` bei `REPLACE_WITH_KV_ID` / `REPLACE_WITH_DEV_KV_ID` eintragen.

## Schritt 3 — Pflicht-Secrets setzen

```bash
npx wrangler secret put ANTHROPIC_API_KEY --env dev
npx wrangler secret put SHORTCUT_TOKEN --env dev
# prod (ohne --env) analog, sobald dev sauber läuft:
npx wrangler secret put ANTHROPIC_API_KEY
npx wrangler secret put SHORTCUT_TOKEN
```

Für dev und prod **verschiedene** `SHORTCUT_TOKEN` verwenden — der Dev-Shortcut am iPhone bekommt den Dev-Token (Rollout-Regel: erst dev, min. 10 Trockenläufe, dann prod).

## Schritt 4 — Zielsysteme anbinden (optional, je nach Bedarf)

Jedes System ist unabhängig; nicht Konfiguriertes antwortet ehrlich mit `not_configured` statt zu raten.

| System | Was setzen | Woher |
|---|---|---|
| Datadog | Secrets `DATADOG_API_KEY`, `DATADOG_APP_KEY`; Var `DD_SITE` (`datadoghq.eu` bei EU-Org) | Datadog → Organization Settings → API/Application Keys (read-only Scope reicht) |
| Jira | Var `JIRA_BASE_URL` (`https://<org>.atlassian.net`); Secrets `JIRA_EMAIL`, `JIRA_API_TOKEN` | id.atlassian.com → Security → API tokens |
| Spotify | Secrets `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `SPOTIFY_REFRESH_TOKEN` | developer.spotify.com App + einmaliger OAuth-Flow mit Scope `user-read-currently-playing` |

Vars stehen in `wrangler.toml`, Secrets ausschließlich via `wrangler secret put`. `summary.day` aggregiert automatisch alles, was konfiguriert ist.

## Schritt 5 — PC-Handler anbinden (macht die `pc.*`-Aktionen real)

Der Handler liegt fertig bei: [`../assets/pc-handler/`](../assets/pc-handler/) (PowerShell, User-Rechte, `START-HIER.bat`). Vollständige Setup- und Test-Anleitung: [`../assets/pc-handler/README.md`](../assets/pc-handler/README.md). Kurz:

1. Handler-Verzeichnis auf den Windows-PC kopieren; `config.json` aus `config.example.json` anlegen und die 4 Skript-Pfade eintragen.
2. `PC_HMAC_SECRET` (aus Schritt 1) nach `%COCKPIT_HOME%\secret.key` schreiben, ACL nur für den User (`icacls … /grant:r "$env:USERNAME:(R)"`).
3. `START-HIER.bat` starten (nicht als Admin). Ersten Kontakt lokal testen — `curl` gegen `127.0.0.1:8787`, signiert via `scripts/hmac_test_vector.py --secret … --ts now --curl` (siehe Handler-README).
4. Cloudflare Tunnel + Access einrichten — liegt fertig bei: [`../assets/tunnel/`](../assets/tunnel/) (`setup-cloudflared.ps1` + `config.example.yml`), vollständige Anleitung inkl. Service-Token-Policy in [`cloudflare_tunnel.md`](cloudflare_tunnel.md). Ergebnis: `https://cockpit-pc.<domain>` → `127.0.0.1:8787`, am Edge durch Cloudflare Access geschützt.
5. `PC_HANDLER_URL` in `wrangler.toml` auf die Tunnel-URL setzen; `npx wrangler secret put PC_HMAC_SECRET` (derselbe Wert wie in `secret.key`); `CF_ACCESS_CLIENT_ID` + `CF_ACCESS_CLIENT_SECRET` als Secrets setzen (Service Token aus Schritt 4).
6. `pc.wake` extra: Worker können kein UDP/Wake-on-LAN ins LAN senden, und der Handler schläft ja gerade. `PC_WAKE_WEBHOOK_URL` auf einen LAN-seitigen Wake-Endpoint zeigen lassen (Router-API, Raspberry Pi, Home Assistant Webhook).

**Kontrakt, den der mitgelieferte Handler erfüllt** (`POST /action`):

- Header `x-cockpit-timestamp` (Unix-Sekunden) und `x-cockpit-signature` = HMAC-SHA256(`PC_HMAC_SECRET`, `"<timestamp>.<raw-body>"`), hex
- Body `{"action": "pc.sleep", "params": {…}, "trace_id": "…"}`
- Handler prüft: Kill-Switch-Datei (→ 503), |now − timestamp| ≤ 90 s (Replay-Fenster, → 401), Signatur über den **rohen** Body (→ 401), Aktion in **seiner eigenen** Whitelist (→ 403) — dann erst ausführen
- Antwort `{"status": "ok", …}` bzw. 401/403/503

Details: [`security_model.md`](security_model.md). Die Signatur-Kompatibilität ist per Testvektor gegen den echten Worker-Code abgesichert: `python3 scripts/hmac_test_vector.py` (Self-Check muss PASS sein).

## Schritt 6 — Deploy + Smoke

```bash
npx wrangler deploy --env dev
npx wrangler tail --env dev   # zweites Terminal: Audit-Log live

# wieder aus dem Skill-Verzeichnis (hier liegt scripts/):
python3 scripts/cockpit_smoketest.py \
  --url https://cockpit-worker-dev.<sub>.workers.dev \
  --token <DEV_SHORTCUT_TOKEN>

# wenn grün, einmal den echten End-to-End-Pfad (kostet einen Claude-Call):
python3 scripts/cockpit_smoketest.py --url … --token … --ask
```

Erst wenn beides grün ist, den iPhone-Shortcut bauen ([`ios_shortcut_setup.md`](ios_shortcut_setup.md)) — gegen dev. Nach 10 sauberen Trockenläufen: `npx wrangler deploy` (prod) und den Prod-Shortcut anlegen.

## Modell + Budget

- `CLAUDE_MODEL` steht in `wrangler.toml` (Default `claude-sonnet-5`; die ursprüngliche Cockpit-Spec nannte Sonnet 4.6 — einfach umtragen, falls gewünscht). Sonnet ist hier die richtige Klasse: Tool-Auswahl aus 8 Optionen braucht kein Opus, aber Latenz zählt (60-s-iOS-Fenster).
- Budget-Rechnung pro `/ask`: 1–3 Claude-Calls à ~1k Token + Aktionslaufzeit (≤ 15 s je Aktion). Typisch 2–10 s Gesamtlaufzeit.
- Workers-Free-Plan: 100k Requests/Tag — mehr als genug für einen einzelnen Shortcut-Token mit 20/min-Limit.

## Betrieb

- **Logs**: `npx wrangler tail` zeigt das strukturierte Audit-Log (`event: ask / ask_done / confirmed / auth_failed / rate_limited / error`) mit Trace-IDs. Für Dauerbetrieb: Cloudflare Logpush → Datadog (Guard-Regel 7).
- **Debug-Reihenfolge**: Worker-Log → Handler-Log → Datadog; Trace-ID aus der iPhone-Mitteilung ist der rote Faden.
- **Stufe 2 (Selective Autonomy)**: erst nach 30 fehlerfreien Läufen einer Aktion; Kriterien und Grenzen in [`security_model.md`](security_model.md).
