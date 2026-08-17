// Guard-Block — harte Sperren, egal was Claude vorschlägt (nicht verhandelbar).
// Dieselben Regeln stehen bewusst NOCHMAL im PC-Handler: zwei Locations,
// damit weder Worker- noch Handler-Kompromittierung allein reicht.

import { bySlug, SCRIPT_WHITELIST } from "./tools.js";

export const GUARD = {
  RATE_LIMIT_PER_MIN: 20, // Regel 6: max. 20 Requests/Minute pro Shortcut-Token
  CONFIRM_TTL_S: 60, // Bestätigungen sind max. 60s gültig
  ACTION_TIMEOUT_MS: 15000, // jede Aktion max. 15s, danach Abbruch
  MAX_PROMPT_CHARS: 2000,
  MAX_CLAUDE_ROUNDS: 3, // Tool-Loop-Deckel (Auswahl -> Ausführung -> Synthese)
};

export class GuardError extends Error {
  constructor(message) {
    super(message);
    this.name = "GuardError";
  }
}

// Regel 1+2: ausschließlich Whitelist-Aktionen mit validierten Parametern.
// Freitext-Kommandos existieren im Datenmodell schlicht nicht.
export function assertAllowed(slug, params = {}) {
  const tool = bySlug(slug);
  if (!tool) {
    throw new GuardError(`Aktion '${slug}' steht nicht in der Whitelist.`);
  }
  if (tool.slug === "pc.run_script" && !SCRIPT_WHITELIST.includes(params.script)) {
    throw new GuardError(
      `Skript '${params.script}' steht nicht in der Skript-Whitelist.`
    );
  }
  return tool;
}

// Regel 5: jeder Request Richtung PC-Handler wird HMAC-SHA256-signiert
// über `${timestamp}.${body}` — Replay-Schutz via Timestamp-Fenster im Handler.
export async function hmacSign(secret, timestamp, body) {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const sig = await crypto.subtle.sign(
    "HMAC",
    key,
    new TextEncoder().encode(`${timestamp}.${body}`)
  );
  return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export async function sha256hex(s) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export function withTimeout(promise, ms, label) {
  return Promise.race([
    promise,
    new Promise((_, reject) =>
      setTimeout(() => reject(new GuardError(`Timeout nach ${ms}ms: ${label}`)), ms)
    ),
  ]);
}
