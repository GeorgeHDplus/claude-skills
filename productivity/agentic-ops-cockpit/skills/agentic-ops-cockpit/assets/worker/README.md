# cockpit-worker

Cloudflare Worker des Agentic Ops Cockpit — die Gegenstelle für den iPhone-Shortcut.

**Zero-Dependency:** kein `package.json`, kein Build. Deploy direkt mit `npx wrangler`.

## Quickstart

```bash
# 1. KV-Namespace anlegen, ausgegebene IDs in wrangler.toml eintragen
npx wrangler kv namespace create COCKPIT_KV
npx wrangler kv namespace create COCKPIT_KV --env dev

# 2. Pflicht-Secrets setzen (Werte via generate_secrets.py erzeugen)
npx wrangler secret put ANTHROPIC_API_KEY
npx wrangler secret put SHORTCUT_TOKEN

# 3. Deploy (erst dev, dann prod)
npx wrangler deploy --env dev
npx wrangler deploy

# 4. Verifizieren
python3 ../../scripts/cockpit_smoketest.py --url https://cockpit-worker.<subdomain>.workers.dev --token <SHORTCUT_TOKEN>
```

Vollständige Anleitung: [`../../references/worker_deployment.md`](../../references/worker_deployment.md)
API-Kontrakt + Shortcut-Bau: [`../../references/ios_shortcut_setup.md`](../../references/ios_shortcut_setup.md)
Sicherheitsmodell (Guard-Block, HMAC, Rotation): [`../../references/security_model.md`](../../references/security_model.md)

## Endpunkte

| Route | Methode | Auth | Zweck |
|-------|---------|------|-------|
| `/health` | GET | keine | Reachability-Probe (`{"status":"ok","mode":"observer"}`) |
| `/ask` | POST | Bearer `SHORTCUT_TOKEN` | Prompt interpretieren; Reads sofort, Rest als `needs_confirmation` |
| `/confirm` | POST | Bearer `SHORTCUT_TOKEN` | Pending-Aktionen einer Trace-ID ausführen (max. 60s alt) |
| `/outbox` | GET | Bearer `SHORTCUT_TOKEN` | Executor-Kurzbefehl holt gequeue-te `phone.*`-Aktionen ab (Abholung leert) |

## Dateien

- `src/index.js` — Routing, Auth (Hash-Vergleich), Rate-Limit (KV), Confirm-Flow, Audit-Log
- `src/tools.js` — Aktions-Whitelist (12 Aktionen) inkl. Cockpit-Metadaten
- `src/guard.js` — Guard-Block: Whitelist-Erzwingung, HMAC-Signierung, Timeouts, Limits
- `src/actions.js` — Router: PC via Tunnel+HMAC, Datadog/Jira/Spotify direkt, `summary.day` als Aggregat, `phone.*` in die Outbox
- `src/claude.js` — Anthropic-Messages-Call mit Tool-Loop (max. 3 Runden), Observer-Mode-Trennung
