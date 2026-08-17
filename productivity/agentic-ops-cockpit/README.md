# Agentic Ops Cockpit — iOS-Zugriff

Steuere deinen Ops-Stack vom iPhone: ein Satz zu Siri, und die Kette **Kurzbefehl → Cloudflare Worker → Claude API → Aktions-Whitelist** liefert Status, Summaries und (nach Bestätigung) PC-Aktionen als Push-Mitteilung zurück.

Dieses Plugin ist die **iOS-Zugriffsschicht** des Cockpits — deploybar und end-to-end testbar, bevor der Windows-PC-Handler existiert: die fünf Cloud-Aktionen (Status, Datadog-Alerts, Jira-Tickets, Spotify, Tages-Summary) laufen direkt über den Worker.

## Was drin ist

```
agentic-ops-cockpit/
├── skills/agentic-ops-cockpit/
│   ├── SKILL.md                          # Architektur, Setup-Workflow, Whitelist, Guard
│   ├── assets/worker/                    # Deploybarer Cloudflare Worker (zero-dependency)
│   │   ├── wrangler.toml                 #   dev + prod Environments, KV, Vars
│   │   └── src/{index,tools,guard,actions,claude}.js
│   ├── references/
│   │   ├── ios_shortcut_setup.md         # Kurzbefehle Aktion für Aktion + Siri + Action Button
│   │   ├── worker_deployment.md          # Deploy in 6 Schritten + PC-Handler-Kontrakt
│   │   └── security_model.md             # Guard→Code-Mapping, HMAC-Spec, Rotation, Threat-Model
│   └── scripts/
│       ├── generate_secrets.py           # SHORTCUT_TOKEN + PC_HMAC_SECRET (32 Byte)
│       ├── cockpit_smoketest.py          # Health/Auth/E2E gegen den deployten Worker
│       └── shortcut_payload_builder.py   # Request-Kontrakt-Referenz + curl-Generator
├── agents/cs-ops-cockpit.md              # Persona: Cockpit-Operator (Guard-treu)
└── commands/cs-cockpit.md                # /cs:cockpit
```

## Quickstart

```bash
# 1. Secrets
python3 skills/agentic-ops-cockpit/scripts/generate_secrets.py

# 2. Worker deployen (KV anlegen, Secrets setzen — Details: references/worker_deployment.md)
cp -r skills/agentic-ops-cockpit/assets/worker ~/cockpit-worker && cd ~/cockpit-worker
npx wrangler kv namespace create COCKPIT_KV        # ID in wrangler.toml eintragen
npx wrangler secret put ANTHROPIC_API_KEY
npx wrangler secret put SHORTCUT_TOKEN
npx wrangler deploy --env dev

# 3. Verifizieren, BEVOR das iPhone ins Spiel kommt
python3 …/scripts/cockpit_smoketest.py --url https://cockpit-worker-dev.<sub>.workers.dev --token <TOKEN>

# 4. Kurzbefehle + Siri bauen
#    -> references/ios_shortcut_setup.md (Aktion für Aktion, inkl. Troubleshooting)
```

Danach: „Hey Siri, Cockpit Tages-Summary."

## Sicherheitsmodell in einem Absatz

Stufe-1-Whitelist mit 8 Aktionen (`zielsystem.verb`), hart kodiert in Worker **und** (später) PC-Handler. Reads laufen sofort; `pc.wake`/`pc.sleep`/`pc.run_script` kommen als Vorschlag zurück und laufen erst nach Bestätigung am iPhone (60-s-Fenster). Bearer-Token fürs iPhone, HMAC-SHA256 + Cloudflare Tunnel Richtung PC, 20 Requests/min, Audit-Log mit Trace-ID auf jeder Mitteilung, Kill-Switch per Datei. Kein Freitext Richtung PC — niemals. Details: [`skills/agentic-ops-cockpit/references/security_model.md`](skills/agentic-ops-cockpit/references/security_model.md)

## Status + Roadmap

- ✅ **v1 (dieses Paket):** iOS-Zugriff end-to-end — Worker, Kurzbefehle, Siri, 5 Cloud-Aktionen live, PC-Aktionen als sauberes `not_configured` bis der Handler steht
- ⬜ PC-Handler (PowerShell, HMAC-Verifikation, eigene Whitelist, Kill-Switch) + Cloudflare Tunnel
- ⬜ Push-Confirm statt Menü (actionable Notifications via Job-Muster)
- ⬜ Kalender-Quelle für `summary.day`
- ⬜ Stufe 2: Selective Autonomy für nachweislich fehlerfreie, nicht-destruktive Aktionen

## Lizenz

MIT
