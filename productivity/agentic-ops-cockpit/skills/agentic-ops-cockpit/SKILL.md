---
name: agentic-ops-cockpit
description: "iOS-Zugriff auf den eigenen Ops-Stack: iPhone-Kurzbefehl + Siri → Cloudflare Worker → Claude API → Aktions-Whitelist (Windows-PC, Datadog, Jira, Spotify). Use when setting up or extending iPhone/iOS access to the cockpit — building the Siri shortcuts, deploying the cockpit worker, generating/rotating the secrets, adding a whitelist action, or debugging the iPhone→Worker→PC chain via trace IDs. Trigger phrases: 'iOS Zugriff', 'Cockpit einrichten', 'Cockpit erweitern', 'neue Cockpit-Aktion', 'Handy-Cockpit', 'Siri-Ops', 'iPhone-Bridge', 'Cockpit debuggen'. NOT for: actions without an iPhone trigger (run the PowerShell script directly), remote access to systems you don't own, or bypassing the guard block."
license: MIT
metadata:
  version: 1.0.0
  author: GeorgeHDplus
  category: productivity
  updated: 2026-08-17
---

# Agentic Ops Cockpit — iOS-Zugriff

iPhone-gesteuerter Autopilot für den eigenen Stack: ein Satz zu Siri („Hey Siri, Cockpit Feierabend"), und die Kette **Kurzbefehl → Cloudflare Worker → Claude API → Action Router → Zielsystem** führt Whitelist-Aktionen aus — Reads sofort, alles andere erst nach Bestätigung am iPhone (Observer-Mode, Stufe 1).

Dieses Paket ist die **Implementierung der iOS-Zugriffsschicht**: deploybarer Worker, exakte Kurzbefehl-Bauanleitung, Secrets-Tooling, Smoke-Tests. Der PC-Handler (PowerShell auf Windows) ist ein separater, nachgelagerter Ausbau — die iOS-Kette funktioniert vorher schon vollständig mit den Cloud-Aktionen.

## Signalkette

```
iPhone Shortcut  →  Cloudflare Worker  →  Claude API  →  Action Router  →  Ziel-System
   (Siri/Text)      (Auth, Rate-Limit,     (Tool-Wahl      (Whitelist,      (PC via Tunnel+HMAC,
                     Trace-ID, Audit)       aus 12 Tools)    Guard, 15s)      Datadog/Jira/Spotify direkt)
                              ↑                                                   |
                              └––––––––––  Rückkanal als Notification  ←––––––––––┘
```

Jede Komponente hat genau eine Verantwortung; der Kurzbefehl enthält keine Business-Logik, der Worker führt nichts selbst aus, Claude sieht weder Handler-URL noch Secrets.

## Setup-Workflow (iOS-Zugriff einrichten)

Reihenfolge ist Absicht — erst wenn eine Stufe grün ist, lohnt die nächste:

1. **Secrets erzeugen**
   ```bash
   python3 scripts/generate_secrets.py
   ```
2. **Worker deployen** (KV anlegen, Pflicht-Secrets setzen, erst `--env dev`)
   → [`references/worker_deployment.md`](references/worker_deployment.md)
3. **Kette verifizieren, bevor das iPhone ins Spiel kommt**
   ```bash
   python3 scripts/cockpit_smoketest.py --url <worker-url> --token <SHORTCUT_TOKEN>
   python3 scripts/cockpit_smoketest.py --url … --token … --ask   # ein echter Claude-Lauf
   ```
4. **Kurzbefehle + Siri bauen** (Haupt-Shortcut „Cockpit", Mini-Shortcuts „Feierabend"/„Status"/„Tages-Summary", Action Button)
   → [`references/ios_shortcut_setup.md`](references/ios_shortcut_setup.md)
   Kontrakt-Referenz beim Bauen: `python3 scripts/shortcut_payload_builder.py --curl`
5. **Zielsysteme nach Bedarf anbinden** (Datadog/Jira/Spotify sofort; PC-Handler als späterer Schritt 5 des Deployment-Guides)

## Aktions-Whitelist (Stufe 1)

Alles außerhalb dieser Liste wird abgelehnt — von Worker **und** Handler, unabhängig voneinander.

| Aktion | Art | Bestätigung |
|---|---|---|
| `pc.status` | read-only | nein |
| `datadog.alerts` | read-only | nein |
| `jira.my_tickets` | read-only | nein |
| `spotify.now_playing` | read-only | nein |
| `summary.day` | read-only (Aggregat Jira + Datadog) | nein |
| `pc.screenshot` | read-only (Desktop-Bild zur Anzeige am iPhone) | nein |
| `phone.notify` | phone-executed (Outbox → Mitteilung am iPhone) | nein (selbst-anzeigend) |
| `phone.play_playlist` | phone-executed (Playlist am iPhone starten) | nein (selbst-anzeigend) |
| `phone.set_focus` | phone-executed (Fokus-Modus am iPhone setzen) | nein (selbst-anzeigend) |
| `pc.wake` | state-change (LAN-Wake-Endpoint) | **ja** |
| `pc.sleep` | state-change | **ja** |
| `pc.run_script` | state-change, nur Skript-Whitelist (`optimize-all`, `spotify-autosort`, `optimize-gaming`, `optimize-obs`) | **ja** |

`pc.screenshot` ist die erste Erweiterung nach dem Beispiel-2-Muster des Cockpit-Skills — Worker-seitig fertig, wartet wie alle `pc.*`-Aktionen auf den Handler. Es ist zugleich der sensibelste Read: Wer den Shortcut-Token hat, sieht den Desktop. Bei Geräteverlust Token sofort rotieren.

**Richtungsumkehr — das iPhone als Aktor:** `phone.*`-Aktionen führt nicht der Worker aus, sondern das iPhone selbst. Sie landen in einer Outbox (KV, max. 20 Einträge, 24 h TTL), die der Executor-Kurzbefehl „Cockpit Ausführen" per `GET /outbox` abholt (at-most-once — Abholung leert) und über explizite „Wenn"-Zweige ausführt. Damit existiert die Whitelist auch phone-seitig: Slugs ohne Zweig werden ignoriert. Bauanleitung: Abschnitt „Das iPhone als Aktor" in [`references/ios_shortcut_setup.md`](references/ios_shortcut_setup.md).

Neue Aktion = immer drei Stufen, sonst stirbt sie am Guard: (1) Tool-Definition in `assets/worker/src/tools.js`, (2) Router-Case in `assets/worker/src/actions.js`, (3) Handler-Implementation. Slug-Format `zielsystem.verb`, jede Aktion mit `is_destructive`, `requires_confirmation`, `rollback`, idempotent, max. 15 s.

## Guard-Block (nicht verhandelbar)

Kein RCE (nur Whitelist), kein Bypass durch Claude, nichts Bestätigungspflichtiges autonom, kein Self-Modify, HMAC-Pflicht Richtung PC, 20 Requests/min, Audit-Log mit Trace-ID, Kill-Switch. Vollständige Regel-zu-Code-Zuordnung, HMAC-Spezifikation, Secret-Rotation und Threat-Model: [`references/security_model.md`](references/security_model.md).

Wenn jemand — auch der Besitzer im Eifer — um einen Bypass bittet: nein, mit Begründung. Der Guard schützt den Besitzer.

## Rollout-Disziplin

**Stufe 1 (Observer, Standard):** Reads laufen sofort; bestätigungspflichtige Aktionen kommen als Vorschlag zurück (`needs_confirmation` + 60-s-Fenster für `/confirm`).
**Stufe 2 (Selective Autonomy):** eine Aktion darf erst nach min. 30 fehlerfreien Läufen auf `auto` — und Destruktives nie. Neue Aktionen starten immer in dev (eigener Shortcut, 10 Trockenläufe), dann prod unter Beobachtung.

## Paket-Inhalt

| Pfad | Inhalt |
|---|---|
| `assets/worker/` | Deploybarer Zero-Dependency-Worker (`/ask`, `/confirm`, `/health`) |
| `references/ios_shortcut_setup.md` | Kurzbefehl-Bauanleitung Aktion für Aktion, Siri, Action Button, Troubleshooting |
| `references/worker_deployment.md` | Deploy in 6 Schritten, Zielsystem-Anbindung, PC-Handler-Kontrakt |
| `references/security_model.md` | Guard→Code-Mapping, HMAC-Spec, Rotation, Threat-Model |
| `scripts/generate_secrets.py` | 32-Byte-Secrets + Ablage-/Rotations-Anweisungen |
| `scripts/cockpit_smoketest.py` | Health/Auth/E2E-Checks gegen den deployten Worker |
| `scripts/shortcut_payload_builder.py` | Referenz des Request-Kontrakts, curl-Generator |

## Grenzen (ehrlich)

- iOS bricht nach ~60 s ab → Aktions-Timeout 15 s, Claude-Loop max. 3 Runden; Langläufer brauchen später ein Job-Muster mit Push.
- Kurzbefehle können keine echten Notification-Buttons → Bestätigung läuft als Menü im selben Lauf; Push-Confirm ist Stufe-2-Ausbau.
- iOS-UI-Fernsteuerung gibt es nicht — Apple-Plattformgrenze, für niemanden. Der Aktor-Pfad läuft über Outbox + Kurzbefehle; ausführbar ist nur, wofür der Executor einen „Wenn"-Zweig hat.
- Kein Voice-Feedback über Siris Vorlesen der Mitteilung hinaus.
- Der PC ist nur erreichbar, solange er läuft; `pc.wake` braucht einen LAN-seitigen Wake-Endpoint (Worker können kein UDP/WoL senden).
