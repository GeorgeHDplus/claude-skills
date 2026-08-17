#!/usr/bin/env python3
"""Smoke test for the deployed Cockpit worker (stdlib-only).

Prueft die iOS-Zugriffskette VOR dem Shortcut-Bau, damit Fehler nicht erst
am iPhone auftauchen. Standard-Checks (kostenlos, kein Claude-Call):

  1. GET  /health                -> 200 + status "ok"
  2. POST /ask ohne Token        -> 401 (Auth greift)
  3. POST /ask mit falschem Token-> 401 (kein Token-Bypass)

Mit --ask zusaetzlich ein echter End-to-End-Lauf (kostet einen Claude-Call):

  4. POST /ask mit Token         -> 200 + trace_id + status done/needs_confirmation

Exit-Code 0 = alle Checks bestanden, 1 = mindestens ein Check rot.

Usage:
  python3 cockpit_smoketest.py --url https://cockpit-worker.<sub>.workers.dev --token <SHORTCUT_TOKEN>
  python3 cockpit_smoketest.py --url ... --token ... --ask --prompt "Was laeuft gerade auf Spotify?"
  python3 cockpit_smoketest.py --url ... --token ... --json
"""

import argparse
import json
import sys
import urllib.error
import urllib.request

TIMEOUT_S = 60  # iOS-Obergrenze — was hier langsamer ist, scheitert auch am iPhone


def _request(method, url, token=None, payload=None):
    """Return (http_status, parsed_json_or_none). Never raises on HTTP errors."""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            body = resp.read().decode("utf-8", "replace")
            status = resp.status
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        status = e.code
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return None, {"transport_error": str(e)}
    try:
        return status, json.loads(body)
    except ValueError:
        return status, {"raw": body[:200]}


def run_checks(base_url, token, do_ask, prompt):
    base = base_url.rstrip("/")
    checks = []

    status, body = _request("GET", f"{base}/health")
    checks.append(
        {
            "name": "health",
            "ok": status == 200 and isinstance(body, dict) and body.get("status") == "ok",
            "detail": f"HTTP {status}, body={json.dumps(body, ensure_ascii=False)[:120]}",
        }
    )

    status, body = _request("POST", f"{base}/ask", payload={"prompt": "ping"})
    checks.append(
        {
            "name": "auth_missing_token",
            "ok": status == 401,
            "detail": f"HTTP {status} (erwartet 401)",
        }
    )

    status, body = _request(
        "POST", f"{base}/ask", token="wrong-token-smoketest", payload={"prompt": "ping"}
    )
    checks.append(
        {
            "name": "auth_wrong_token",
            "ok": status == 401,
            "detail": f"HTTP {status} (erwartet 401)",
        }
    )

    if do_ask:
        status, body = _request(
            "POST",
            f"{base}/ask",
            token=token,
            payload={"prompt": prompt, "source": "smoketest", "device": "cli"},
        )
        ok = (
            status == 200
            and isinstance(body, dict)
            and bool(body.get("trace_id"))
            and body.get("status") in ("done", "needs_confirmation")
        )
        detail = f"HTTP {status}"
        if isinstance(body, dict):
            detail += (
                f", status={body.get('status')}, trace_id={body.get('trace_id')}, "
                f"reply={str(body.get('reply'))[:80]!r}"
            )
        checks.append({"name": "ask_end_to_end", "ok": ok, "detail": detail})

    return checks


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Smoke-Test gegen den deployten Cockpit-Worker (vor dem Shortcut-Bau)."
    )
    parser.add_argument("--url", required=True, help="Worker-Basis-URL (https://...workers.dev)")
    parser.add_argument("--token", required=True, help="SHORTCUT_TOKEN (Bearer)")
    parser.add_argument(
        "--ask",
        action="store_true",
        help="Zusaetzlich echten /ask-Lauf testen (kostet einen Claude-API-Call).",
    )
    parser.add_argument(
        "--prompt",
        default="Kurzer Ping — antworte nur mit einem Satz, keine Aktionen.",
        help="Prompt fuer den --ask End-to-End-Check.",
    )
    parser.add_argument("--json", action="store_true", help="Maschinenlesbare JSON-Ausgabe.")
    args = parser.parse_args(argv)

    checks = run_checks(args.url, args.token, args.ask, args.prompt)
    passed = sum(1 for c in checks if c["ok"])
    failed = len(checks) - passed

    if args.json:
        print(
            json.dumps(
                {"url": args.url, "passed": passed, "failed": failed, "checks": checks},
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        print(f"Cockpit-Smoketest gegen {args.url}")
        print("=" * 64)
        for c in checks:
            mark = "PASS" if c["ok"] else "FAIL"
            print(f"[{mark}] {c['name']:<18} {c['detail']}")
        print("-" * 64)
        print(f"{passed} bestanden, {failed} fehlgeschlagen")
        if failed == 0 and not args.ask:
            print("Tipp: mit --ask einmal den echten End-to-End-Pfad testen,")
            print("bevor du den iPhone-Shortcut baust.")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
