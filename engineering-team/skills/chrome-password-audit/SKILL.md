---
name: "chrome-password-audit"
description: "Use when auditing saved browser logins to find dead/unused accounts and see which are still active, or when cleaning up a Chrome/Edge/Brave password list. Reads login METADATA only (site, username, last-used dates) and never decrypts or exposes the passwords themselves. Complements Chrome's built-in Password Checkup, which covers compromised/reused/weak passwords."
---

# Chrome Password Audit

A local, read-only audit of saved-login **metadata** for Chromium-family browsers
(Chrome, Edge, Brave, Chromium). It answers two practical questions:

1. **Which saved logins are "dead"?** — never used, or not used in many months.
2. **Which do I still use?** — actively-used accounts, plus which of those have a
   stale password worth rotating.

This is a hygiene/cleanup tool. It is **not** a password extractor and it does
**not** check breaches — for compromised/reused/weak passwords, use Chrome's
built-in Password Checkup (`chrome://password-manager/checkup`). This skill and
that feature are complementary: Checkup tells you which passwords are *unsafe*;
this skill tells you which accounts are *stale* and safe to delete.

---

## Table of Contents

- [Safety Model](#safety-model)
- [Overview](#overview)
- [The Audit Tool](#the-audit-tool)
- [Workflow](#workflow)
- [Interpreting the Buckets](#interpreting-the-buckets)
- [Limitations](#limitations)
- [References](#references)

---

## Safety Model

The single most important property of this skill: **it never reads, decrypts, or
prints your passwords.**

- The tool selects only non-secret metadata columns from the browser's `logins`
  table (`origin_url`, `username_value`, `date_created`, `date_last_used`,
  `date_password_modified`, `times_used`, `blacklisted_by_user`). The encrypted
  `password_value` column is never named in a query, and a defensive assertion
  refuses to run if it ever were.
- It makes **no network calls**.
- It never writes to your live browser profile — the database is copied to a
  temporary file, read from the copy, and the copy is deleted afterward.
- Usernames are the only mildly-sensitive field shown. Use `--mask` before
  sharing output, pasting it into a chat, or taking a screenshot.

Because passwords never leave your machine in plaintext (they are never touched
at all), this is a fundamentally different and safer operation than "export my
passwords." Prefer this over any workflow that dumps decrypted credentials.

## Overview

Chromium stores saved logins in a SQLite database called `Login Data` inside each
browser profile. Every row carries the password in an OS-encrypted blob **plus**
plaintext usage metadata. This skill mines only that metadata:

- `date_last_used` / `times_used` → is this account dead or alive?
- `date_created` → how long has it existed?
- `date_password_modified` → is the password stale (rotation candidate)?
- `blacklisted_by_user` → a "never save for this site" marker (not a credential).

Timestamps are Chromium/WebKit format (microseconds since 1601-01-01 UTC) and are
converted to calendar dates for the report.

## The Audit Tool

`scripts/chrome_password_audit.py` — stdlib-only Python 3, no dependencies.

```bash
# Audit every detected browser + profile
python3 scripts/chrome_password_audit.py

# Only Chrome, and treat "unused >= 6 months" as dead
python3 scripts/chrome_password_audit.py --browser chrome --stale-months 6

# Also list actively-used accounts, mask usernames for a screenshot
python3 scripts/chrome_password_audit.py --include-active --mask

# Machine-readable output
python3 scripts/chrome_password_audit.py --json

# Audit an explicit copied database (e.g. copied off another machine)
python3 scripts/chrome_password_audit.py --db "/path/to/Login Data"

# See example output without touching your real data
python3 scripts/chrome_password_audit.py --sample --include-active
```

Key flags:

| Flag | Default | Meaning |
|------|---------|---------|
| `--browser` | `all` | `chrome` / `chromium` / `edge` / `brave` / `all` |
| `--stale-months` | `12` | Unused for ≥ N months ⇒ **dead** |
| `--active-months` | `3` | Used within N months ⇒ **active** |
| `--rotate-months` | `24` | Kept accounts with a password older than N months are flagged for rotation |
| `--include-active` | off | Also print the actively-used list |
| `--mask` | off | Mask usernames (safe for sharing) |
| `--json` | off | Emit structured JSON |
| `--sample` | off | Run on a built-in fake DB (demo / smoke test) |

Auto-detected database locations (per OS):

- **Chrome** — Win: `%LOCALAPPDATA%\Google\Chrome\User Data\<Profile>\Login Data` ·
  macOS: `~/Library/Application Support/Google/Chrome/<Profile>/Login Data` ·
  Linux: `~/.config/google-chrome/<Profile>/Login Data`
- **Edge / Brave / Chromium** — same layout under
  `Microsoft/Edge`, `BraveSoftware/Brave-Browser`, `Chromium` respectively.

All profiles (`Default`, `Profile 1`, …) are scanned automatically.

## Workflow

1. **Close the browser** (optional but recommended, so metadata is fully flushed).
2. **Run the audit** — start with defaults, then tune `--stale-months` to taste.
3. **Review the cleanup list** — deadest entries first. You decide what goes.
4. **Delete** unwanted accounts in `chrome://password-manager/passwords` (or at
   `passwords.google.com`). The tool never deletes anything itself.
5. **Run Password Checkup** (`chrome://password-manager/checkup`) for the accounts
   you keep, to catch compromised/reused/weak passwords.
6. **Rotate** the passwords the tool flagged under 🔁 for accounts you keep.

## Interpreting the Buckets

| Bucket | Meaning | Typical action |
|--------|---------|----------------|
| 🪦 **dead** | Last used ≥ `stale-months` ago | Delete unless you know you need it |
| ⚪ **never used** | Saved but `times_used = 0` / no last-used date | Strong delete candidate |
| 🕓 **aging** | Between active and dead | Keep an eye on; rotate if password is old |
| ✅ **active** | Used within `active-months` | Keep; rotate if flagged |
| 🚫 **never save** | A "don't save for this site" marker, not a credential | Ignore |

## Limitations

- **"Dead" is a heuristic, not proof.** A once-a-year tax portal will look dead in
  March. Read the list; don't bulk-delete blindly.
- **Metadata can be sparse.** Very old entries, or logins synced from another
  device, may have `date_last_used = 0`; they surface as *never used*.
- **No breach/strength check.** That is exactly what Chrome Password Checkup does —
  run it alongside this tool.
- **Encrypted-at-rest passwords are out of scope by design.** This skill will never
  decrypt them.

## References

- `references/credential-hygiene.md` — how to read the buckets, a safe
  delete-and-rotate workflow, and the boundary between this tool and Password
  Checkup / a dedicated password manager. Cites Chrome/Google, NIST 800-63B,
  Have I Been Pwned, and Chromium source documentation.
