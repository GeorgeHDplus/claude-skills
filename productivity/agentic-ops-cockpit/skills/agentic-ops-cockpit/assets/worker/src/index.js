// Agentic Ops Cockpit — Cloudflare Worker (iOS-Zugriffsschicht).
// Endpunkte:
//   GET  /health   — Reachability-Probe (ohne Auth, ohne Details)
//   POST /ask      — {prompt} -> Claude interpretiert -> Reads sofort,
//                    bestätigungspflichtige Aktionen als pending (Observer-Mode)
//   POST /confirm  — {trace_id} -> führt pending Aktionen aus (max. 60s alt)
//   GET  /outbox   — iPhone-Executor holt gequeue-te phone.*-Aktionen ab
//                    (at-most-once: Abholung leert die Outbox)
// Auth: Authorization: Bearer <SHORTCUT_TOKEN> (Hash-Vergleich, kein Timing-Leak).

import { interpret } from "./claude.js";
import { execute, drainOutbox } from "./actions.js";
import { GUARD, sha256hex } from "./guard.js";

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const traceId = crypto.randomUUID();
    try {
      if (url.pathname === "/health" && request.method === "GET") {
        return json({ status: "ok", mode: env.COCKPIT_MODE || "observer" });
      }

      const authError = await checkAuth(request, env);
      if (authError) {
        // Guard-Regel 7: auch Fehlversuche landen im Audit-Log (wrangler tail / Logpush).
        log({ trace_id: traceId, event: "auth_failed", reason: authError });
        return json({ error: "unauthorized", trace_id: traceId }, 401);
      }
      if (await rateLimited(env)) {
        log({ trace_id: traceId, event: "rate_limited" });
        return json({ error: "rate_limited", trace_id: traceId }, 429);
      }

      if (url.pathname === "/outbox" && request.method === "GET") {
        const out = await drainOutbox(env);
        if (out.items.length > 0) {
          log({ trace_id: traceId, event: "outbox_drained", actions: out.items.map((i) => i.action) });
        }
        return json({ trace_id: traceId, ...out });
      }
      if (request.method !== "POST") {
        return json({ error: "method_not_allowed", trace_id: traceId }, 405);
      }

      if (url.pathname === "/ask") return await handleAsk(request, env, traceId);
      if (url.pathname === "/confirm") return await handleConfirm(request, env, traceId);
      return json({ error: "not_found", trace_id: traceId }, 404);
    } catch (e) {
      log({ trace_id: traceId, event: "error", error: String(e.message) });
      // Keine Secrets, keine internen URLs in Fehlermeldungen ans iPhone.
      return json({ error: "internal", detail: String(e.message).slice(0, 200), trace_id: traceId }, 500);
    }
  },
};

async function handleAsk(request, env, traceId) {
  const body = await request.json().catch(() => null);
  const prompt = (body?.prompt ?? "").toString().trim();
  if (!prompt) return json({ error: "prompt_missing", trace_id: traceId }, 400);
  if (prompt.length > GUARD.MAX_PROMPT_CHARS) {
    return json({ error: "prompt_too_long", trace_id: traceId }, 400);
  }

  log({ trace_id: traceId, event: "ask", source: body?.source ?? "unknown" });
  const { reply, results, pending } = await interpret(prompt, env, traceId);

  let status = "done";
  if (pending.length > 0) {
    status = "needs_confirmation";
    await env.COCKPIT_KV.put(
      `pending:${traceId}`,
      JSON.stringify({ actions: pending, created: Date.now() }),
      { expirationTtl: GUARD.CONFIRM_TTL_S }
    );
  }

  log({
    trace_id: traceId,
    event: "ask_done",
    status,
    executed: results.map((r) => r.action),
    pending: pending.map((p) => p.action),
  });
  return json({
    trace_id: traceId,
    status,
    reply,
    results,
    pending: pending.map((p) => ({ action: p.action, params: p.params })),
  });
}

async function handleConfirm(request, env, traceId) {
  const body = await request.json().catch(() => null);
  const confirmId = (body?.trace_id ?? "").toString();
  if (!confirmId) return json({ error: "trace_id_missing", trace_id: traceId }, 400);

  const raw = await env.COCKPIT_KV.get(`pending:${confirmId}`);
  if (!raw) {
    return json(
      {
        error: "expired_or_unknown",
        hint: `Bestätigungen sind nur ${GUARD.CONFIRM_TTL_S}s gültig — Aktion neu anstoßen.`,
        trace_id: traceId,
      },
      410
    );
  }
  // Vor der Ausführung löschen -> ein Confirm kann nie doppelt ausgeführt werden.
  await env.COCKPIT_KV.delete(`pending:${confirmId}`);

  // Es wird ausschließlich der gespeicherte Zustand ausgeführt —
  // der Client kann per /confirm keine Aktionen oder Parameter injizieren.
  const { actions } = JSON.parse(raw);
  const results = [];
  for (const a of actions) {
    try {
      results.push({ action: a.action, result: await execute(a.action, a.params, env, confirmId) });
    } catch (e) {
      results.push({ action: a.action, result: { status: "error", error: String(e.message) } });
    }
  }

  log({ trace_id: confirmId, event: "confirmed", executed: results.map((r) => r.action) });
  return json({ trace_id: confirmId, status: "done", results });
}

async function checkAuth(request, env) {
  if (!env.SHORTCUT_TOKEN) return "shortcut_token_not_set";
  const header = request.headers.get("authorization") || "";
  const token = header.startsWith("Bearer ") ? header.slice(7) : "";
  if (!token) return "token_missing";
  // Vergleich über SHA-256-Digests: konstante Länge, kein Timing-Leak.
  const [a, b] = await Promise.all([sha256hex(token), sha256hex(env.SHORTCUT_TOKEN)]);
  return a === b ? null : "token_mismatch";
}

// Best-Effort-Limiter auf KV (eventual consistent — bewusst einfach gehalten;
// der Shortcut-Token ist der einzige Client, harte Fairness braucht es nicht).
async function rateLimited(env) {
  if (!env.COCKPIT_KV) return false;
  const key = `rl:${Math.floor(Date.now() / 60000)}`;
  const count = parseInt((await env.COCKPIT_KV.get(key)) || "0", 10) + 1;
  await env.COCKPIT_KV.put(key, String(count), { expirationTtl: 120 });
  return count > GUARD.RATE_LIMIT_PER_MIN;
}

function log(fields) {
  console.log(JSON.stringify({ service: "cockpit-worker", ...fields }));
}

function json(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}
