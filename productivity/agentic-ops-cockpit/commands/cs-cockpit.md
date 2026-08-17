---
name: "cs-cockpit"
description: "/cs:cockpit [einrichten|erweitern|debuggen] — iOS-Zugriff auf den Ops-Stack: Cockpit-Worker deployen, iPhone-Kurzbefehle + Siri bauen, Whitelist-Aktionen im Drei-Stufen-Muster ergänzen, Fehler entlang der Trace-ID debuggen. Guard-Block hart: kein Freitext Richtung PC, nichts Bestätigungspflichtiges autonom."
---

# /cs:cockpit — Agentic Ops Cockpit

**Command:** `/cs:cockpit [einrichten|erweitern|debuggen]`

Die `cs-ops-cockpit`-Persona führt durch die iPhone→Worker→Claude→Whitelist-Kette.

## Modi

### `einrichten` (Default) — iOS-Zugriff von null

1. Secrets erzeugen: `python3 scripts/generate_secrets.py`
2. Worker deployen (dev-first): [`references/worker_deployment.md`](../skills/agentic-ops-cockpit/references/worker_deployment.md)
3. Kette verifizieren: `python3 scripts/cockpit_smoketest.py --url … --token … [--ask]`
4. Kurzbefehle + Siri bauen: [`references/ios_shortcut_setup.md`](../skills/agentic-ops-cockpit/references/ios_shortcut_setup.md)
5. Zielsysteme anbinden (Datadog/Jira/Spotify sofort, PC-Handler später)

**Stop-Bedingung:** Smoketest grün + „Hey Siri, Cockpit Tages-Summary" liefert eine Mitteilung mit Trace-ID.

### `erweitern` — neue Whitelist-Aktion

Drei Stufen, keine Abkürzung: Tool-Definition (`tools.js`) → Router-Case (`actions.js`) → Handler-Implementation. Slug `zielsystem.verb`; `requires_confirmation` ehrlich setzen; idempotent; ≤ 15 s; Rollout dev → 10 Trockenläufe → prod → 20 Läufe → frühestens dann `auto` (nie für Destruktives).

### `debuggen` — entlang der Trace-ID

Worker-Log (`npx wrangler tail`) → Handler-Log → Datadog. Häufigste Treffer: 401 = Token/Uhrzeit-Drift (`w32tm /resync`), 410 = 60-s-Confirm-Fenster verpasst, 429 = Rate-Limit, `not_configured` = Zielsystem-Secrets fehlen.

## Discipline

- **Nur Whitelist** — 8 Aktionen Stufe 1; alles andere wird abgelehnt, auch „nur kurz zum Testen"
- **Observer-Mode ist Standard** — Reads sofort, Rest als Vorschlag mit Bestätigung am iPhone
- **Guard-Bypass gibt es nicht** — auf Bitte folgt ein Nein mit Begründung und dem sauberen Weg (neue Whitelist-Aktion)
- **Trace-ID auf jeder Mitteilung** — sonst ist Debugging unmöglich
- **Secrets nie außerhalb** von Worker-Secrets / Kurzbefehl-Header / `secret.key`

## Anti-Patterns Rejected

- Freitext-Kommandos an den PC-Handler weiterreichen
- Handler ohne HMAC exponieren („nur kurz") — danach ist Rotation Pflicht, keine Option
- Bestätigungspflichtige Aktionen auto ausführen oder retryen
- Kurzbefehl per Link/Galerie teilen (Token wandert mit)
- Neue Aktionen direkt in prod deployen

## Related

- Agent: [`cs-ops-cockpit`](../agents/cs-ops-cockpit.md)
- Skill: [`agentic-ops-cockpit`](../skills/agentic-ops-cockpit/SKILL.md)

---

**Version:** 1.0.0
