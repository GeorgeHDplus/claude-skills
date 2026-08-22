#!/usr/bin/env python3
"""Generate the two Cockpit secrets (stdlib-only, deterministic contract).

Erzeugt kryptographisch starke Secrets für die iOS-Zugriffskette:

  SHORTCUT_TOKEN   iPhone-Shortcut -> Cloudflare Worker (Bearer-Token)
  PC_HMAC_SECRET   Cloudflare Worker -> PC-Handler (HMAC-SHA256)

Beide haben 32 Byte Entropie (base64url, ~43 Zeichen) — Minimum laut
Guard-Block. Ausgabe wahlweise menschenlesbar (mit den passenden
`wrangler secret put`-Kommandos) oder als JSON für Automation.

Usage:
  python3 generate_secrets.py
  python3 generate_secrets.py --json
  python3 generate_secrets.py --only shortcut
"""

import argparse
import json
import secrets
import sys

ENTROPY_BYTES = 32

SECRET_SPECS = {
    "shortcut": {
        "name": "SHORTCUT_TOKEN",
        "purpose": "iPhone-Shortcut -> Worker (Authorization: Bearer <token>)",
        "storage": (
            "Direkt im Kurzbefehl im Header-Feld der Aktion 'Inhalt der URL abrufen' "
            "speichern — NICHT in iCloud-Notizen, NICHT im Klartext teilen."
        ),
    },
    "hmac": {
        "name": "PC_HMAC_SECRET",
        "purpose": "Worker -> PC-Handler (HMAC-SHA256 ueber timestamp.body)",
        "storage": (
            "Worker: `npx wrangler secret put PC_HMAC_SECRET`. "
            "PC: %COCKPIT_HOME%\\secret.key mit ACL nur fuer den User."
        ),
    },
}


def generate(only=None):
    keys = [only] if only else list(SECRET_SPECS)
    out = []
    for key in keys:
        spec = SECRET_SPECS[key]
        out.append(
            {
                "id": key,
                "name": spec["name"],
                "value": secrets.token_urlsafe(ENTROPY_BYTES),
                "entropy_bytes": ENTROPY_BYTES,
                "purpose": spec["purpose"],
                "storage": spec["storage"],
            }
        )
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Erzeugt SHORTCUT_TOKEN + PC_HMAC_SECRET fuer das Agentic Ops Cockpit."
    )
    parser.add_argument(
        "--only",
        choices=sorted(SECRET_SPECS),
        help="Nur eines der beiden Secrets erzeugen (z.B. bei Rotation).",
    )
    parser.add_argument("--json", action="store_true", help="Maschinenlesbare JSON-Ausgabe.")
    args = parser.parse_args(argv)

    generated = generate(args.only)

    if args.json:
        print(json.dumps({"secrets": generated}, indent=2, ensure_ascii=False))
        return 0

    print("Agentic Ops Cockpit — neue Secrets (32 Byte Entropie, base64url)")
    print("=" * 64)
    for s in generated:
        print(f"\n{s['name']}")
        print(f"  Wert:    {s['value']}")
        print(f"  Zweck:   {s['purpose']}")
        print(f"  Ablage:  {s['storage']}")
    print("\nWorker-Seite setzen mit:")
    for s in generated:
        if s["id"] == "shortcut":
            print("  npx wrangler secret put SHORTCUT_TOKEN")
        if s["id"] == "hmac":
            print("  npx wrangler secret put PC_HMAC_SECRET")
    print("\nHinweis: Nach jedem versehentlichen Leak (Screenshot, geteilter")
    print("Kurzbefehl, offener Handler) betroffenes Secret SOFORT rotieren —")
    print("einfach dieses Skript erneut ausfuehren und beide Seiten aktualisieren.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
