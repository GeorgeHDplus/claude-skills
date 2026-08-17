// Action-Router — führt ausschließlich Whitelist-Aktionen aus.
// PC-Aktionen gehen HMAC-signiert durch den Cloudflare Tunnel an den Handler,
// Cloud-Aktionen (Datadog/Jira/Spotify) direkt an die jeweilige API.
// Nicht konfigurierte Systeme antworten ehrlich mit status "not_configured".

import { GUARD, assertAllowed, hmacSign, withTimeout } from "./guard.js";

export async function execute(slug, params, env, traceId) {
  assertAllowed(slug, params);
  const handler = HANDLERS[slug];
  return withTimeout(handler(params ?? {}, env, traceId), GUARD.ACTION_TIMEOUT_MS, slug);
}

const HANDLERS = {
  "pc.wake": pcWake,
  "pc.sleep": (p, env, t) => callPcHandler(env, "pc.sleep", p, t),
  "pc.status": (p, env, t) => callPcHandler(env, "pc.status", p, t),
  "pc.run_script": (p, env, t) => callPcHandler(env, "pc.run_script", p, t),
  "pc.screenshot": (p, env, t) => callPcHandler(env, "pc.screenshot", p, t),
  "datadog.alerts": datadogAlerts,
  "jira.my_tickets": jiraMyTickets,
  "spotify.now_playing": spotifyNowPlaying,
  "summary.day": summaryDay,
  "phone.notify": (p, env) => enqueuePhone(env, "phone.notify", p),
  "phone.play_playlist": (p, env) => enqueuePhone(env, "phone.play_playlist", p),
  "phone.set_focus": (p, env) => enqueuePhone(env, "phone.set_focus", p),
};

function notConfigured(system, hint) {
  return { status: "not_configured", system, hint };
}

// --- PC über Tunnel + HMAC -------------------------------------------------

async function callPcHandler(env, action, params, traceId) {
  if (!env.PC_HANDLER_URL || !env.PC_HMAC_SECRET) {
    return notConfigured(
      "pc-handler",
      "PC_HANDLER_URL (Var) + PC_HMAC_SECRET (Secret) setzen — references/worker_deployment.md, Schritt 5."
    );
  }
  const body = JSON.stringify({ action, params: params ?? {}, trace_id: traceId });
  const ts = String(Math.floor(Date.now() / 1000));
  const sig = await hmacSign(env.PC_HMAC_SECRET, ts, body);
  const headers = {
    "content-type": "application/json",
    "x-cockpit-timestamp": ts,
    "x-cockpit-signature": sig,
  };
  // Cloudflare Access Service Token — Edge-Filter VOR dem Tunnel: hält alles
  // außer dem Worker vom Handler-Hostname fern. Optional (nur wenn gesetzt),
  // aber empfohlen. Ersetzt NICHT die HMAC — beides zusammen = Defense-in-Depth.
  // Setup: references/cloudflare_tunnel.md.
  if (env.CF_ACCESS_CLIENT_ID && env.CF_ACCESS_CLIENT_SECRET) {
    headers["CF-Access-Client-Id"] = env.CF_ACCESS_CLIENT_ID;
    headers["CF-Access-Client-Secret"] = env.CF_ACCESS_CLIENT_SECRET;
  }
  const res = await fetch(new URL("/action", env.PC_HANDLER_URL), {
    method: "POST",
    headers,
    body,
  });
  if (res.status === 503) {
    return { status: "kill_switch", hint: "KILL-Datei auf dem PC aktiv — Handler antwortet nicht." };
  }
  if (!res.ok) {
    // Handler-Fehler kommen als JSON; Cloudflare Access weist am Edge mit HTML
    // ab (der Request erreicht den Handler nie) — daran unterscheidbar.
    const ctype = res.headers.get("content-type") || "";
    if (!ctype.includes("application/json")) {
      return {
        status: "access_denied",
        http: res.status,
        hint:
          "Von Cloudflare Access abgewiesen (nicht vom Handler) — CF_ACCESS_CLIENT_ID/SECRET " +
          "und die Access-Policy prüfen: references/cloudflare_tunnel.md.",
      };
    }
    throw new Error(`PC-Handler HTTP ${res.status}`);
  }
  return res.json();
}

async function pcWake(params, env) {
  // Worker können kein UDP/WoL ins LAN senden — und der Handler schläft ja.
  // Daher: LAN-seitiger Wake-Endpoint (Router / Pi / Home Assistant Webhook).
  if (!env.PC_WAKE_WEBHOOK_URL) {
    return notConfigured(
      "pc.wake",
      "PC_WAKE_WEBHOOK_URL auf einen LAN-seitigen Wake-Endpoint setzen (Router/Pi/Home Assistant)."
    );
  }
  const res = await fetch(env.PC_WAKE_WEBHOOK_URL, { method: "POST" });
  return { status: res.ok ? "ok" : "error", http: res.status };
}

// --- Cloud-APIs (read-only) ------------------------------------------------

async function datadogAlerts(params, env) {
  if (!env.DATADOG_API_KEY || !env.DATADOG_APP_KEY) {
    return notConfigured("datadog", "DATADOG_API_KEY + DATADOG_APP_KEY als Worker-Secrets setzen.");
  }
  const site = env.DD_SITE || "datadoghq.com";
  const res = await fetch(`https://api.${site}/api/v1/monitor?group_states=alert,warn`, {
    headers: {
      "DD-API-KEY": env.DATADOG_API_KEY,
      "DD-APPLICATION-KEY": env.DATADOG_APP_KEY,
    },
  });
  if (!res.ok) throw new Error(`Datadog HTTP ${res.status}`);
  const monitors = await res.json();
  const alerting = monitors.filter((m) => ["Alert", "Warn"].includes(m.overall_state));
  return {
    status: "ok",
    count: alerting.length,
    alerts: alerting.slice(0, 10).map((m) => ({ name: m.name, state: m.overall_state, id: m.id })),
  };
}

async function jiraMyTickets(params, env) {
  if (!env.JIRA_BASE_URL || !env.JIRA_EMAIL || !env.JIRA_API_TOKEN) {
    return notConfigured(
      "jira",
      "JIRA_BASE_URL (Var) + JIRA_EMAIL/JIRA_API_TOKEN (Secrets) setzen."
    );
  }
  const jql = "assignee = currentUser() AND statusCategory != Done ORDER BY updated DESC";
  const url =
    `${env.JIRA_BASE_URL}/rest/api/3/search/jql?jql=${encodeURIComponent(jql)}` +
    "&maxResults=10&fields=summary,status,priority";
  const res = await fetch(url, {
    headers: {
      authorization: "Basic " + btoa(`${env.JIRA_EMAIL}:${env.JIRA_API_TOKEN}`),
      accept: "application/json",
    },
  });
  if (!res.ok) throw new Error(`Jira HTTP ${res.status}`);
  const data = await res.json();
  const issues = (data.issues ?? []).map((i) => ({
    key: i.key,
    summary: i.fields?.summary,
    status: i.fields?.status?.name,
    priority: i.fields?.priority?.name,
  }));
  return { status: "ok", count: issues.length, issues };
}

async function spotifyNowPlaying(params, env) {
  if (!env.SPOTIFY_CLIENT_ID || !env.SPOTIFY_CLIENT_SECRET || !env.SPOTIFY_REFRESH_TOKEN) {
    return notConfigured(
      "spotify",
      "SPOTIFY_CLIENT_ID/SPOTIFY_CLIENT_SECRET/SPOTIFY_REFRESH_TOKEN als Worker-Secrets setzen."
    );
  }
  const tok = await fetch("https://accounts.spotify.com/api/token", {
    method: "POST",
    headers: {
      "content-type": "application/x-www-form-urlencoded",
      authorization: "Basic " + btoa(`${env.SPOTIFY_CLIENT_ID}:${env.SPOTIFY_CLIENT_SECRET}`),
    },
    body: new URLSearchParams({
      grant_type: "refresh_token",
      refresh_token: env.SPOTIFY_REFRESH_TOKEN,
    }),
  });
  if (!tok.ok) throw new Error(`Spotify Token HTTP ${tok.status}`);
  const { access_token } = await tok.json();
  const res = await fetch("https://api.spotify.com/v1/me/player/currently-playing", {
    headers: { authorization: `Bearer ${access_token}` },
  });
  if (res.status === 204) return { status: "ok", playing: false };
  if (!res.ok) throw new Error(`Spotify HTTP ${res.status}`);
  const data = await res.json();
  return {
    status: "ok",
    playing: Boolean(data.is_playing),
    track: data.item?.name ?? null,
    artist: (data.item?.artists ?? []).map((a) => a.name).join(", ") || null,
  };
}

// --- iPhone als Aktor: Outbox ---------------------------------------------
// phone.*-Aktionen werden nicht server-seitig ausgefuehrt, sondern in eine
// KV-Outbox gelegt. Der Executor-Kurzbefehl holt sie mit GET /outbox ab und
// fuehrt sie phone-seitig aus — mit eigener Wenn-Zweig-Whitelist. Drain ist
// at-most-once (bewusst): lieber eine benigne Aktion verlieren als doppeln.

const OUTBOX_KEY = "outbox";
const OUTBOX_MAX = 20;
const OUTBOX_TTL_S = 86400;

async function enqueuePhone(env, action, params) {
  if (!env.COCKPIT_KV) {
    return { status: "error", error: "COCKPIT_KV fehlt — Outbox braucht das KV-Binding." };
  }
  const items = JSON.parse((await env.COCKPIT_KV.get(OUTBOX_KEY)) || "[]");
  items.push({ id: crypto.randomUUID(), action, params: params ?? {}, created: Date.now() });
  await env.COCKPIT_KV.put(OUTBOX_KEY, JSON.stringify(items.slice(-OUTBOX_MAX)), {
    expirationTtl: OUTBOX_TTL_S,
  });
  return {
    status: "queued",
    queue_length: Math.min(items.length, OUTBOX_MAX),
    note: "Wartet auf Abholung durch das iPhone (Executor-Kurzbefehl 'Cockpit Ausfuehren').",
  };
}

export async function drainOutbox(env) {
  if (!env.COCKPIT_KV) return { items: [] };
  const raw = await env.COCKPIT_KV.get(OUTBOX_KEY);
  if (!raw) return { items: [] };
  await env.COCKPIT_KV.delete(OUTBOX_KEY);
  return { items: JSON.parse(raw) };
}

async function summaryDay(params, env) {
  const [jira, datadog] = await Promise.allSettled([
    jiraMyTickets({}, env),
    datadogAlerts({}, env),
  ]);
  const part = (r) =>
    r.status === "fulfilled" ? r.value : { status: "error", error: String(r.reason?.message ?? r.reason) };
  return {
    status: "ok",
    jira: part(jira),
    datadog: part(datadog),
    note: "Kalender-Anbindung folgt (CalDAV/MCP) — v1 aggregiert Jira + Datadog.",
  };
}
