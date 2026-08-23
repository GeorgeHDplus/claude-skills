#!/usr/bin/env python3
"""
chrome_password_audit.py — Local, read-only audit of saved-login METADATA.

Finds "dead" (never-used / long-unused) saved logins and shows which accounts
you still use, across Chromium-family browsers (Chrome, Edge, Brave, Chromium).

SAFETY — READ THIS:
    This tool NEVER reads, decrypts, or prints your passwords. It deliberately
    does not SELECT the encrypted `password_value` column at all. It only reads
    non-secret metadata that Chromium stores in plaintext next to each entry:
        - origin_url / signon_realm   (which site)
        - username_value              (which account)
        - date_created / date_last_used / date_password_modified
        - times_used / blacklisted_by_user
    No network calls are made. The real database is copied to a temporary file
    and opened from there, so the live browser profile is never modified.

Why a copy? Chromium keeps "Login Data" open (often in WAL mode) while running.
Copying to a temp file avoids lock issues and guarantees the original is
untouched. The temp copy is deleted when the run finishes.

Usage:
    python3 chrome_password_audit.py                       # audit all detected browsers/profiles
    python3 chrome_password_audit.py --browser chrome      # only Chrome
    python3 chrome_password_audit.py --stale-months 6      # "dead" = unused >= 6 months
    python3 chrome_password_audit.py --include-active      # also list actively-used entries
    python3 chrome_password_audit.py --mask                # mask usernames (safe for screenshots/sharing)
    python3 chrome_password_audit.py --json                # machine-readable output
    python3 chrome_password_audit.py --db "/path/Login Data"   # audit an explicit copied DB
    python3 chrome_password_audit.py --sample              # run on a built-in fake DB (demo / smoke test)

Exit codes:
    0  audit completed (including "nothing found")
    1  no login database found / unreadable input
"""

import argparse
import json
import os
import platform
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

# Microseconds between 1601-01-01 (Chromium/WebKit epoch) and 1970-01-01 (Unix).
CHROME_EPOCH_OFFSET_SECONDS = 11_644_473_600

# Metadata columns we are willing to read. `password_value` is intentionally
# ABSENT and must never be added here.
SAFE_COLUMNS = (
    "origin_url",
    "signon_realm",
    "username_value",
    "date_created",
    "date_last_used",
    "date_password_modified",
    "times_used",
    "blacklisted_by_user",
)
FORBIDDEN_COLUMNS = ("password_value",)

DAYS_PER_MONTH = 30


# ---------------------------------------------------------------------------
# Browser profile discovery
# ---------------------------------------------------------------------------

def _user_data_dirs(browser: str) -> list:
    """Return candidate Chromium "User Data" roots for a browser on this OS."""
    home = Path.home()
    system = platform.system()
    local = os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local"))
    appsupport = home / "Library" / "Application Support"

    layout = {
        "chrome": {
            "Windows": [Path(local) / "Google" / "Chrome" / "User Data"],
            "Darwin": [appsupport / "Google" / "Chrome"],
            "Linux": [home / ".config" / "google-chrome"],
        },
        "chromium": {
            "Windows": [Path(local) / "Chromium" / "User Data"],
            "Darwin": [appsupport / "Chromium"],
            "Linux": [home / ".config" / "chromium"],
        },
        "edge": {
            "Windows": [Path(local) / "Microsoft" / "Edge" / "User Data"],
            "Darwin": [appsupport / "Microsoft Edge"],
            "Linux": [home / ".config" / "microsoft-edge"],
        },
        "brave": {
            "Windows": [Path(local) / "BraveSoftware" / "Brave-Browser" / "User Data"],
            "Darwin": [appsupport / "BraveSoftware" / "Brave-Browser"],
            "Linux": [home / ".config" / "BraveSoftware" / "Brave-Browser"],
        },
    }
    return layout.get(browser, {}).get(system, [])


def discover_login_dbs(browsers: list) -> list:
    """Find (browser, profile, path) for every "Login Data" DB under each browser."""
    found = []
    for browser in browsers:
        for root in _user_data_dirs(browser):
            if not root.exists():
                continue
            for child in sorted(root.iterdir()):
                if not child.is_dir():
                    continue
                # Chromium profile dirs: "Default", "Profile 1", "Guest Profile", ...
                db = child / "Login Data"
                if db.exists():
                    found.append({"browser": browser, "profile": child.name, "path": db})
    return found


# ---------------------------------------------------------------------------
# Reading (metadata only)
# ---------------------------------------------------------------------------

def read_login_metadata(db_path: Path) -> list:
    """Copy the DB to a temp file and read metadata rows. Never touches passwords."""
    tmpdir = tempfile.mkdtemp(prefix="cpa_")
    try:
        tmp = Path(tmpdir) / "Login Data"
        shutil.copy2(db_path, tmp)
        # Copy WAL/SHM sidecars if present so recent writes are visible.
        for suffix in ("-wal", "-shm"):
            side = Path(str(db_path) + suffix)
            if side.exists():
                shutil.copy2(side, Path(str(tmp) + suffix))

        con = sqlite3.connect(str(tmp))
        con.row_factory = sqlite3.Row
        try:
            existing = {row[1] for row in con.execute("PRAGMA table_info(logins)")}
            if not existing:
                return []
            columns = [c for c in SAFE_COLUMNS if c in existing]
            # Defensive: guarantee no secret column can ever be selected.
            assert not any(c in columns for c in FORBIDDEN_COLUMNS), "refusing to read secret columns"
            rows = con.execute(f"SELECT {', '.join(columns)} FROM logins").fetchall()
            return [dict(r) for r in rows]
        finally:
            con.close()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def chrome_time_to_dt(micros):
    """Convert Chromium timestamp (microseconds since 1601) to aware UTC datetime."""
    if not micros:
        return None
    unix_seconds = micros / 1_000_000 - CHROME_EPOCH_OFFSET_SECONDS
    if unix_seconds <= 0:
        return None
    try:
        return datetime.fromtimestamp(unix_seconds, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def domain_of(url: str) -> str:
    if not url:
        return "(unknown)"
    try:
        netloc = urlsplit(url).netloc or url
    except ValueError:
        return url
    netloc = netloc.split("@")[-1].split(":")[0]
    return netloc.lower() or url


def mask_username(username: str) -> str:
    if not username:
        return "(no username)"
    if "@" in username:
        name, _, domain = username.partition("@")
        head = name[:2] if len(name) > 2 else name[:1]
        return f"{head}***@{domain}"
    return f"{username[:2]}***" if len(username) > 2 else "***"


def _fmt_date(dt):
    return dt.strftime("%Y-%m-%d") if dt else "never"


def _age_days(dt, now):
    return None if dt is None else max(0, (now - dt).days)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify(entry, now, stale_months, active_months):
    """Bucket an entry: never_saved | never_used | dead | aging | active."""
    if entry.get("blacklisted_by_user"):
        return "never_saved"
    last_dt = entry["_last_used_dt"]
    times = entry.get("times_used") or 0
    if last_dt is None or times == 0:
        return "never_used"
    age = _age_days(last_dt, now)
    if age >= stale_months * DAYS_PER_MONTH:
        return "dead"
    if age <= active_months * DAYS_PER_MONTH:
        return "active"
    return "aging"


def build_report(sources, now, args):
    entries = []
    source_summaries = []

    for src in sources:
        rows = read_login_metadata(src["path"]) if not src.get("_rows") else src["_rows"]
        counts = {"never_saved": 0, "never_used": 0, "dead": 0, "aging": 0, "active": 0}
        for row in rows:
            row["_created_dt"] = chrome_time_to_dt(row.get("date_created"))
            row["_last_used_dt"] = chrome_time_to_dt(row.get("date_last_used"))
            row["_pw_modified_dt"] = chrome_time_to_dt(row.get("date_password_modified"))
            row["_domain"] = domain_of(row.get("origin_url") or row.get("signon_realm") or "")
            row["_bucket"] = classify(row, now, args.stale_months, args.active_months)
            row["_browser"] = src["browser"]
            row["_profile"] = src["profile"]
            counts[row["_bucket"]] += 1
            entries.append(row)
        source_summaries.append({
            "browser": src["browser"],
            "profile": src["profile"],
            "path": str(src["path"]),
            "total": len(rows),
            "counts": counts,
        })

    def serialize(row):
        return {
            "browser": row["_browser"],
            "profile": row["_profile"],
            "domain": row["_domain"],
            "url": row.get("origin_url") or row.get("signon_realm"),
            "username": mask_username(row.get("username_value")) if args.mask else (row.get("username_value") or ""),
            "bucket": row["_bucket"],
            "times_used": row.get("times_used") or 0,
            "created": _fmt_date(row["_created_dt"]),
            "last_used": _fmt_date(row["_last_used_dt"]),
            "password_modified": _fmt_date(row["_pw_modified_dt"]),
            "password_age_days": _age_days(row["_pw_modified_dt"], now),
            "last_used_age_days": _age_days(row["_last_used_dt"], now),
        }

    cleanup = [e for e in entries if e["_bucket"] in ("never_used", "dead")]
    # Deadest first: never-used, then oldest last_used.
    cleanup.sort(key=lambda e: (e["_last_used_dt"] is not None, e["_last_used_dt"] or now))

    rotate = [
        e for e in entries
        if e["_bucket"] in ("active", "aging")
        and e["_pw_modified_dt"] is not None
        and _age_days(e["_pw_modified_dt"], now) >= args.rotate_months * DAYS_PER_MONTH
    ]
    rotate.sort(key=lambda e: e["_pw_modified_dt"])

    active = [e for e in entries if e["_bucket"] == "active"]
    active.sort(key=lambda e: e["_last_used_dt"] or now, reverse=True)

    totals = {"never_saved": 0, "never_used": 0, "dead": 0, "aging": 0, "active": 0}
    for s in source_summaries:
        for k, v in s["counts"].items():
            totals[k] += v

    return {
        "generated_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "thresholds": {
            "stale_months": args.stale_months,
            "active_months": args.active_months,
            "rotate_months": args.rotate_months,
        },
        "sources": source_summaries,
        "totals": totals,
        "cleanup_candidates": [serialize(e) for e in cleanup],
        "rotate_candidates": [serialize(e) for e in rotate],
        "active": [serialize(e) for e in active],
        "safety": "Passwords are never read or decrypted. Metadata only.",
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _table(rows, cols, limit):
    if not rows:
        return "    (none)\n"
    shown = rows[:limit] if limit else rows
    widths = {c: len(h) for c, h in cols}
    for r in shown:
        for c, _ in cols:
            widths[c] = max(widths[c], len(str(r.get(c, ""))))
    out = []
    header = "  " + "  ".join(h.ljust(widths[c]) for c, h in cols)
    out.append(header)
    out.append("  " + "  ".join("-" * widths[c] for c, _ in cols))
    for r in shown:
        out.append("  " + "  ".join(str(r.get(c, "")).ljust(widths[c]) for c, _ in cols))
    if limit and len(rows) > limit:
        out.append(f"  … and {len(rows) - limit} more (raise --limit or use --json for all)")
    return "\n".join(out) + "\n"


def render_text(report, args):
    t = report["totals"]
    lines = []
    lines.append("=" * 72)
    lines.append("  CHROME / CHROMIUM SAVED-LOGIN AUDIT  (metadata only)")
    lines.append("  Passwords are NEVER read or decrypted — this reads usage dates only.")
    lines.append("=" * 72)
    lines.append("")
    lines.append(f"  Generated: {report['generated_utc']}")
    th = report["thresholds"]
    lines.append(f"  Thresholds: dead >= {th['stale_months']}mo unused | "
                 f"active <= {th['active_months']}mo | rotate >= {th['rotate_months']}mo old password")
    lines.append("")

    lines.append("  Sources scanned:")
    if not report["sources"]:
        lines.append("    (no login databases found)")
    for s in report["sources"]:
        lines.append(f"    - {s['browser']}/{s['profile']}: {s['total']} entries  ({s['path']})")
    lines.append("")

    lines.append("  Summary:")
    lines.append(f"    🪦 dead (unused >= {th['stale_months']}mo) : {t['dead']}")
    lines.append(f"    ⚪ never used                 : {t['never_used']}")
    lines.append(f"    🕓 aging                      : {t['aging']}")
    lines.append(f"    ✅ active (used recently)     : {t['active']}")
    lines.append(f"    🚫 'never save' entries       : {t['never_saved']}")
    lines.append("")

    lines.append(f"  🪦 CLEANUP CANDIDATES — dead / never-used (deadest first): "
                 f"{len(report['cleanup_candidates'])}")
    lines.append(_table(
        report["cleanup_candidates"],
        [("domain", "SITE"), ("username", "ACCOUNT"), ("last_used", "LAST USED"),
         ("created", "CREATED"), ("times_used", "USES"), ("profile", "PROFILE")],
        args.limit,
    ))

    lines.append(f"  🔁 ROTATE — actively used but password not changed in >= "
                 f"{th['rotate_months']}mo: {len(report['rotate_candidates'])}")
    lines.append(_table(
        report["rotate_candidates"],
        [("domain", "SITE"), ("username", "ACCOUNT"), ("password_modified", "PW CHANGED"),
         ("last_used", "LAST USED"), ("profile", "PROFILE")],
        args.limit,
    ))

    if args.include_active:
        lines.append(f"  ✅ ACTIVE — used within {th['active_months']}mo: {len(report['active'])}")
        lines.append(_table(
            report["active"],
            [("domain", "SITE"), ("username", "ACCOUNT"), ("last_used", "LAST USED"),
             ("times_used", "USES"), ("profile", "PROFILE")],
            args.limit,
        ))

    lines.append("  Next steps (you decide — nothing is changed automatically):")
    lines.append("    1. Review the cleanup list. Delete accounts you no longer use in")
    lines.append("       chrome://password-manager/passwords (or passwords.google.com).")
    lines.append("    2. Run Chrome's Password Checkup for compromised/reused/weak passwords:")
    lines.append("       chrome://password-manager/checkup")
    lines.append("    3. Change (rotate) the passwords flagged above for accounts you keep.")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Sample DB (demo / smoke test)
# ---------------------------------------------------------------------------

def build_sample_source(now):
    tmpdir = tempfile.mkdtemp(prefix="cpa_sample_")
    db = Path(tmpdir) / "Login Data"
    con = sqlite3.connect(str(db))
    con.execute(
        "CREATE TABLE logins (origin_url TEXT, signon_realm TEXT, username_value TEXT, "
        "password_value BLOB, date_created INTEGER, date_last_used INTEGER, "
        "date_password_modified INTEGER, times_used INTEGER, blacklisted_by_user INTEGER)"
    )

    def ct(days_ago):
        dt = now.timestamp() - days_ago * 86400
        return int((dt + CHROME_EPOCH_OFFSET_SECONDS) * 1_000_000)

    # password_value is filled with a dummy blob to PROVE the tool never reads it.
    rows = [
        ("https://old-forum.example/login", "https://old-forum.example/", "george@example.com",
         b"ENCRYPTED_BLOB", ct(1400), ct(1300), ct(1400), 3, 0),          # dead
        ("https://defunct-shop.example/", "https://defunct-shop.example/", "george",
         b"ENCRYPTED_BLOB", ct(900), 0, ct(900), 0, 0),                    # never used
        ("https://bank.example/", "https://bank.example/", "george.b@example.com",
         b"ENCRYPTED_BLOB", ct(1200), ct(5), ct(1100), 210, 0),           # active, old pw -> rotate
        ("https://news.example/", "https://news.example/", "gb@example.com",
         b"ENCRYPTED_BLOB", ct(400), ct(40), ct(120), 60, 0),            # active
        ("https://webmail.example/", "https://webmail.example/", "george@example.com",
         b"ENCRYPTED_BLOB", ct(800), ct(240), ct(800), 12, 0),           # aging
        ("https://never-save.example/", "https://never-save.example/", "",
         b"", 0, 0, 0, 0, 1),                                             # 'never save' entry
    ]
    con.executemany("INSERT INTO logins VALUES (?,?,?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()
    return {"browser": "sample", "profile": "SAMPLE", "path": db, "_tmpdir": tmpdir}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Read-only audit of saved-login metadata (passwords are never decrypted).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--browser", choices=["chrome", "chromium", "edge", "brave", "all"],
                        default="all", help="Which browser to scan (default: all detected).")
    parser.add_argument("--db", help="Path to a specific 'Login Data' file (overrides auto-detection).")
    parser.add_argument("--stale-months", type=int, default=12,
                        help="Unused for >= this many months counts as 'dead' (default 12).")
    parser.add_argument("--active-months", type=int, default=3,
                        help="Used within this many months counts as 'active' (default 3).")
    parser.add_argument("--rotate-months", type=int, default=24,
                        help="Flag kept accounts whose password is older than this (default 24).")
    parser.add_argument("--include-active", action="store_true",
                        help="Also list actively-used accounts.")
    parser.add_argument("--mask", action="store_true",
                        help="Mask usernames (use when sharing output or screenshots).")
    parser.add_argument("--limit", type=int, default=40,
                        help="Max rows per table in text output (0 = no limit).")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a text report.")
    parser.add_argument("--sample", action="store_true",
                        help="Run against a built-in fake database (demo / smoke test).")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)

    sources = []
    sample_tmpdir = None
    if args.sample:
        src = build_sample_source(now)
        sample_tmpdir = src.pop("_tmpdir")
        sources = [src]
    elif args.db:
        path = Path(args.db)
        if not path.exists():
            print(f"error: no such file: {path}", file=sys.stderr)
            sys.exit(1)
        sources = [{"browser": "custom", "profile": path.parent.name, "path": path}]
    else:
        browsers = ["chrome", "chromium", "edge", "brave"] if args.browser == "all" else [args.browser]
        sources = discover_login_dbs(browsers)

    try:
        if not sources:
            msg = ("No Chromium login database found. Make sure the browser is installed, "
                   "or pass --db with a path to a copied 'Login Data' file, or try --sample.")
            if args.json:
                print(json.dumps({"error": msg, "totals": {}, "cleanup_candidates": []}, indent=2))
            else:
                print(msg, file=sys.stderr)
            sys.exit(1)

        report = build_report(sources, now, args)
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(render_text(report, args))
        sys.exit(0)
    finally:
        if sample_tmpdir:
            shutil.rmtree(sample_tmpdir, ignore_errors=True)


if __name__ == "__main__":
    main()
