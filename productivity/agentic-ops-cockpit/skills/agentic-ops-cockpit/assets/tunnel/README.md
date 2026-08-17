# cockpit-tunnel

Cloudflare Tunnel zwischen dem Cockpit-Worker (Cloud) und dem PC-Handler (`127.0.0.1:8787` auf dem Windows-PC). Ausgehende Verbindung — **kein offener Port**, keine Router-Freigabe.

```
Worker  ──HTTPS──►  Cloudflare Edge  ──Access-Check──►  Tunnel  ──►  127.0.0.1:8787 (Handler)
                         │                                              (nur lokal gebunden)
                    (Service Token)
```

> **Verifikationshinweis:** `setup-cloudflared.ps1` läuft nicht in der CI (kein Windows/cloudflared dort). Auf dem PC verifizierst du den Tunnel mit `cloudflared tunnel ingress validate` (im Skript enthalten) und dem End-to-End-`curl` aus der Referenz.

## Zwei Teile — beide nötig

1. **Tunnel** (dieses Verzeichnis) — macht den Handler unter `https://cockpit-pc.<domain>` erreichbar.
2. **Cloudflare Access davor** — Service-Token-Policy, damit **nur der Worker** durchkommt. Ohne Access stünde der Handler-Hostname offen im Netz. Das ist der Sicherheitskern und wird im Dashboard/API gesetzt.

Vollständige Schritt-für-Schritt-Anleitung inkl. Access: [`../../references/cloudflare_tunnel.md`](../../references/cloudflare_tunnel.md).

## Quickstart

```powershell
winget install --id Cloudflare.cloudflared

# Tunnel + DNS-Route + config.yml + Dienst (Admin-Shell für Autostart):
.\setup-cloudflared.ps1 -Hostname cockpit-pc.example.com

# danach im Cloudflare-Dashboard: Access Service Token + Access Application
# (references/cloudflare_tunnel.md), dann im Worker:
npx wrangler secret put CF_ACCESS_CLIENT_ID
npx wrangler secret put CF_ACCESS_CLIENT_SECRET
```

## Dateien

- `config.example.yml` — cloudflared-Ingress (Hostname → `127.0.0.1:8787`, catch-all 404). Das Skript befüllt Tunnel-ID/Hostname/Port.
- `setup-cloudflared.ps1` — idempotent: Login, Tunnel anlegen (falls fehlt), DNS-Route, `config.yml` schreiben, Ingress validieren, Dienst installieren.

## Sicherheit in einem Satz

Access ist der **Edge-Filter** (hält das offene Internet vom Hostname fern), die **HMAC bleibt Pflicht** am Handler (authentifiziert den konkreten Request) — Access ersetzt sie nicht, beides zusammen ist Defense-in-Depth.
