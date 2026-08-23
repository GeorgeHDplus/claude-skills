# Credential Hygiene — Reading the Audit and Acting Safely

This reference explains how to turn the audit output into decisions, and where
this metadata tool stops and other tools (Password Checkup, a password manager)
begin. The guiding principle throughout: **passwords are never exported or
decrypted** — you clean up *accounts*, and you rotate secrets *inside* the
browser/manager UI, never by moving plaintext credentials around.

## 1. The two questions this tool answers

The audit exists to separate signal from a long, intimidating password list:

1. **"Is this account dead?"** — decided from `date_last_used` and `times_used`.
   An entry never used, or unused for many months, is a cleanup candidate.
2. **"For the accounts I keep, is the password stale?"** — decided from
   `date_password_modified`. A password you have not changed in years, on an
   account you still use, is a rotation candidate.

Everything else (is it breached? is it reused? is it weak?) is deliberately out
of scope — see §4.

## 2. A safe delete-and-rotate workflow

Order matters. Delete first, then check, then rotate — so you spend effort only
on accounts you are keeping.

1. **Triage the 🪦/⚪ list.** Sort your mental model into: *definitely gone*
   (defunct services, throwaway signups), *not sure* (delete later), and *keep
   despite looking dead* (annual/seasonal logins).
2. **Delete in the browser UI**, not by editing the database:
   - Chrome/Chromium: `chrome://password-manager/passwords`
   - Edge: `edge://settings/passwords`
   - Brave: `brave://settings/passwords`
   - Or the synced view at `passwords.google.com`.
   Deleting here also removes the entry from sync, so it will not reappear on
   your other devices.
3. **Run Password Checkup** on what remains
   (`chrome://password-manager/checkup`). This is where breached/reused/weak
   passwords surface. It uses a privacy-preserving check (see §4) — your
   passwords are not sent in the clear.
4. **Rotate** the passwords the audit flagged under 🔁, and any Checkup flags,
   by changing them at the site and letting the browser save the new value.
   Rotation means *set a new password on the site* — not copying the old one out.
5. **Re-run the audit** in a month to confirm the dead entries are gone.

## 3. Why "unused" is a heuristic, not a verdict

`date_last_used` reflects the last time the browser auto-filled or you used the
saved credential *on this browser*. It will understate usage when:

- you sign in on a **different browser or device** for that account;
- the account uses **"Sign in with Google/Apple"** (a federated login) rather
  than a stored password — there may be no password entry to update at all;
- the credential was **synced in** from another device with a zeroed timestamp,
  showing up as *never used*.

Practical rule: treat 🪦/⚪ as a **shortlist to review**, not a delete queue.
Seasonal logins (tax, travel, a conference portal) are the classic false
positive. Skim before you delete.

## 4. Where this tool stops: Password Checkup and managers

This skill is intentionally narrow. Two adjacent capabilities it does **not**
provide:

- **Breach / reuse / strength analysis** → Chrome (and Google Password Manager)
  **Password Checkup**. It compares your credentials against known-breached
  datasets using *k-anonymity*: only a short hash prefix leaves the device, so
  the service never learns your actual passwords. This is the right, safe way to
  answer "which of my passwords are compromised" — far better than any workflow
  that decrypts and inspects them.
- **Long-term secret management** → a dedicated password manager (the browser's
  own, or a standalone one). If you find yourself with hundreds of entries and
  heavy reuse, a manager with generated unique passwords is the durable fix; the
  audit just tells you how big the cleanup is.

If you ever feel tempted to "just export all passwords to a file to look at
them," stop: a plaintext export is a high-value target that outlives the task,
gets copied into backups and cloud sync, and is exactly what this skill is
designed to make unnecessary.

## 5. Rotation priorities for accounts you keep

Not all stale passwords are equally urgent. Rotate in this order:

1. **Email and phone/carrier accounts** — they are the reset path for everything
   else; compromise here cascades.
2. **Financial and payment** — banks, brokerages, anything with stored payment.
3. **Identity providers** — the Google/Apple/Microsoft account you "Sign in
   with" elsewhere.
4. **Anything reused** — if Password Checkup flags a password as reused, every
   site sharing it inherits the weakest one's risk.
5. **Everything else**, oldest-password-first (the audit's 🔁 ordering).

Turning on multi-factor authentication (MFA) on the top three categories buys
more safety than rotating a dozen low-value passwords.

## Sources

1. Google — *Manage passwords* & *Password Checkup* help
   (support.google.com/chrome, passwords.google.com/checkup/start).
2. Google Security Blog — *Protect your accounts from data breaches with Password
   Checkup* (k-anonymity design of the breach check).
3. NIST SP 800-63B — *Digital Identity Guidelines: Authentication and Lifecycle
   Management* (guidance against forced periodic rotation absent evidence of
   compromise; rotate on breach/staleness signals).
4. Have I Been Pwned — Pwned Passwords range-query API (k-anonymity model for
   checking exposure without revealing the secret).
5. The Chromium Projects — *Login Database* schema notes (`logins` table columns:
   `date_last_used`, `date_password_modified`, `times_used`,
   `blacklisted_by_user`).
6. Chromium source — `components/password_manager` (WebKit/Windows timestamp
   epoch: microseconds since 1601-01-01 UTC).
7. OWASP — *Credential Stuffing Prevention* & *Authentication Cheat Sheet*
   (why reuse is the dominant real-world risk).
8. CISA — *Use Strong Passwords* / *Turn on MFA* guidance (MFA prioritization on
   high-value accounts).
