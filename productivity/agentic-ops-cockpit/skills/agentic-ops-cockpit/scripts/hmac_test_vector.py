#!/usr/bin/env python3
"""HMAC-Testvektor fuer die Worker<->PC-Handler-Signatur (stdlib-only).

Die Signatur ist die kritischste Kompatibilitaet der Kette: der Worker
(assets/worker/src/guard.js) und der PC-Handler (assets/pc-handler/lib/hmac.ps1)
muessen bitgenau dieselbe HMAC erzeugen — sonst weist der Handler jede Anfrage
mit HTTP 401 ab.

Kontrakt:
  string_to_sign = "<unix_timestamp>.<roher_request_body>"
  signature      = hex( HMAC-SHA256( secret, string_to_sign ) )

Ohne Argumente gibt das Tool einen bekannten Vektor + erwartete Signatur aus und
prueft die eigene Berechnung dagegen (Self-Check — exit 1 bei Abweichung). Der
Erwartungswert wurde gegen den echten Worker-Code (guard.js via node) verifiziert.

Mit --secret/--ts/--body erzeugt es die Signatur fuer eigene Werte und optional
den fertigen curl-Request gegen den laufenden Handler — so testest du den Handler
auf dem PC direkt (Cockpit-Standard-Schritt 4: "curl direkt gegen Handler").

Usage:
  python3 hmac_test_vector.py                       # Self-Check + Vektor
  python3 hmac_test_vector.py --json
  python3 hmac_test_vector.py --secret S --ts 1700000000 --body '{"action":"pc.status","params":{},"trace_id":"t1"}'
  python3 hmac_test_vector.py --secret S --body '...' --curl --url http://127.0.0.1:8787
"""

import argparse
import hashlib
import hmac
import json
import sys
import time

# Bekannter Vektor — gegen guard.js (node) verifiziert. Body als Literal, damit
# keine Serialisierungs-Ambiguitaet entsteht (exakt wie JSON.stringify im Worker).
KNOWN = {
    "secret": "test-secret-0123456789",
    "ts": "1700000000",
    "body": '{"action":"pc.status","params":{},"trace_id":"abc-123"}',
    "sig": "5033a7e5e23ac8830f1b7959888fdccac110bb196848b904d2395bb9cc201af4",
}


def sign(secret, ts, body):
    """Exakt die Formel aus guard.js/hmac.ps1: HMAC-SHA256 ueber '<ts>.<body>'."""
    msg = (str(ts) + "." + body).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def self_check():
    got = sign(KNOWN["secret"], KNOWN["ts"], KNOWN["body"])
    return got == KNOWN["sig"], got


def build_curl(url, ts, body, sig):
    base = url.rstrip("/")
    return " \\\n".join(
        [
            "curl -sS -X POST",
            f"  '{base}/action'",
            "  -H 'content-type: application/json'",
            f"  -H 'x-cockpit-timestamp: {ts}'",
            f"  -H 'x-cockpit-signature: {sig}'",
            f"  --data-binary '{body}'",
        ]
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="HMAC-Testvektor + Signatur-Helfer fuer die Worker<->Handler-Kette."
    )
    parser.add_argument("--secret", help="HMAC-Secret (Default: bekannter Vektor).")
    parser.add_argument("--ts", help="Unix-Timestamp (Default: bekannter Vektor; 'now' fuer jetzt).")
    parser.add_argument("--body", help="Roher Request-Body (Default: bekannter Vektor).")
    parser.add_argument("--url", help="Handler-URL fuer --curl (z.B. http://127.0.0.1:8787).")
    parser.add_argument("--curl", action="store_true", help="Signierten curl-Request ausgeben.")
    parser.add_argument("--json", action="store_true", help="Maschinenlesbare JSON-Ausgabe.")
    args = parser.parse_args(argv)

    ok, got = self_check()

    custom = any([args.secret, args.ts, args.body])
    if custom:
        secret = args.secret or KNOWN["secret"]
        ts = str(int(time.time())) if args.ts == "now" else (args.ts or KNOWN["ts"])
        body = args.body if args.body is not None else KNOWN["body"]
        sig = sign(secret, ts, body)
    else:
        secret, ts, body, sig = KNOWN["secret"], KNOWN["ts"], KNOWN["body"], got

    if args.curl:
        print(build_curl(args.url or "http://127.0.0.1:8787", ts, body, sig))
        return 0 if ok else 1

    if args.json:
        print(
            json.dumps(
                {
                    "self_check_passed": ok,
                    "ts": ts,
                    "body": body,
                    "signature": sig,
                    "header_timestamp": "x-cockpit-timestamp",
                    "header_signature": "x-cockpit-signature",
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0 if ok else 1

    print("HMAC-Testvektor (Worker <-> PC-Handler)")
    print("=" * 64)
    print(f"Self-Check (bekannter Vektor): {'PASS' if ok else 'FAIL'}")
    if not ok:
        print(f"  erwartet: {KNOWN['sig']}")
        print(f"  erhalten: {got}")
    print()
    print(f"timestamp : {ts}")
    print(f"body      : {body}")
    print(f"signature : {sig}")
    print()
    print("Header fuer den Request an den Handler:")
    print(f"  x-cockpit-timestamp: {ts}")
    print(f"  x-cockpit-signature: {sig}")
    print()
    print("Tipp: --curl --url http://127.0.0.1:8787 gibt den fertigen Test-Request aus.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
