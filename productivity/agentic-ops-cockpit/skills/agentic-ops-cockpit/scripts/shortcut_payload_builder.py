#!/usr/bin/env python3
"""Build the exact request the iPhone shortcut must send (stdlib-only).

Der Kurzbefehl ist am iPhone muehsam zu debuggen. Dieses Skript ist die
Referenz-Implementierung des Request-Kontrakts: es zeigt fuer /ask und
/confirm exakt die URL, Header und den JSON-Body, die der Kurzbefehl
senden muss — und generiert auf Wunsch das passende curl-Kommando, um den
Request vom Rechner aus zu testen, bevor er ins iPhone uebertragen wird.

Usage:
  python3 shortcut_payload_builder.py "Feierabend"
  python3 shortcut_payload_builder.py "Status?" --source siri --json
  python3 shortcut_payload_builder.py --confirm 3f2a... --url https://... --token XYZ --curl
  python3 shortcut_payload_builder.py --outbox --url https://... --token XYZ --curl
"""

import argparse
import json
import sys

SOURCES = ("shortcut", "siri")


def build(args):
    base = args.url.rstrip("/") if args.url else "https://<worker-url>"
    auth = {"Authorization": f"Bearer {args.token or '<SHORTCUT_TOKEN>'}"}

    if args.outbox:
        return {"method": "GET", "url": base + "/outbox", "headers": auth, "body": None}
    if args.confirm:
        path = "/confirm"
        body = {"trace_id": args.confirm}
    else:
        path = "/ask"
        body = {"prompt": args.prompt, "source": args.source, "device": "iphone"}

    headers = {"Content-Type": "application/json", **auth}
    return {"method": "POST", "url": base + path, "headers": headers, "body": body}


def as_curl(req):
    parts = [f"curl -sS -X {req['method']}", f"  '{req['url']}'"]
    for k, v in req["headers"].items():
        parts.append(f"  -H '{k}: {v}'")
    if req["body"] is not None:
        parts.append(f"  -d '{json.dumps(req['body'], ensure_ascii=False)}'")
    return " \\\n".join(parts)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Referenz fuer den Request-Kontrakt des iPhone-Shortcuts (/ask + /confirm)."
    )
    parser.add_argument(
        "prompt",
        nargs="?",
        default="Feierabend",
        help="Prompt fuer /ask (Default: 'Feierabend'). Ignoriert bei --confirm.",
    )
    parser.add_argument(
        "--source",
        choices=SOURCES,
        default="shortcut",
        help="Woher der Prompt kommt (Default: shortcut).",
    )
    parser.add_argument(
        "--confirm",
        metavar="TRACE_ID",
        help="Statt /ask den /confirm-Request fuer diese Trace-ID bauen.",
    )
    parser.add_argument(
        "--outbox",
        action="store_true",
        help="Den GET /outbox-Request des Executor-Kurzbefehls bauen (leert die Outbox!).",
    )
    parser.add_argument("--url", help="Worker-Basis-URL (sonst Platzhalter).")
    parser.add_argument("--token", help="SHORTCUT_TOKEN (sonst Platzhalter).")
    parser.add_argument("--curl", action="store_true", help="Als curl-Kommando ausgeben.")
    parser.add_argument("--json", action="store_true", help="Maschinenlesbare JSON-Ausgabe.")
    args = parser.parse_args(argv)

    req = build(args)

    if args.json:
        print(json.dumps(req, indent=2, ensure_ascii=False))
        return 0
    if args.curl:
        print(as_curl(req))
        return 0

    print("Request-Kontrakt fuer den Kurzbefehl")
    print("=" * 64)
    print(f"Methode : {req['method']}")
    print(f"URL     : {req['url']}")
    print("Header  :")
    for k, v in req["headers"].items():
        print(f"  {k}: {v}")
    if req["body"] is not None:
        print("Body (JSON — im Kurzbefehl als 'Woerterbuch' / Dictionary anlegen):")
        print(json.dumps(req["body"], indent=2, ensure_ascii=False))
    else:
        print("Body    : (keiner — GET-Request)")
    print()
    print("Im Kurzbefehl entspricht das der Aktion 'Inhalt der URL abrufen'")
    print("(Get Contents of URL): Methode POST, 'JSON anfordern' = Body-Felder,")
    print("Header wie oben. Schritt-fuer-Schritt: references/ios_shortcut_setup.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
