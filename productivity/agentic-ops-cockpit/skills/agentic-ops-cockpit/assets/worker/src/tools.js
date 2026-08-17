// Aktions-Whitelist Stufe 1 — einzige Quelle der Wahrheit im Worker.
// Alles, was hier nicht steht, wird abgelehnt (Guard-Block Regel 1+2).
//
// Anthropic-Tool-Namen erlauben keine Punkte (^[a-zA-Z0-9_-]{1,64}$),
// daher: Slug "pc.sleep" <-> API-Name "pc__sleep". Mapping unten.

export const SCRIPT_WHITELIST = [
  "optimize-all",
  "spotify-autosort",
  "optimize-gaming",
  "optimize-obs",
];

export const TOOLS = [
  {
    slug: "pc.wake",
    description:
      "Weckt den Windows-PC auf (Wake-on-LAN über einen LAN-seitigen Wake-Endpoint).",
    input_schema: { type: "object", properties: {}, additionalProperties: false },
    is_destructive: false,
    requires_confirmation: true,
    rollback: "pc.sleep",
  },
  {
    slug: "pc.sleep",
    description: "Versetzt den Windows-PC in Standby.",
    input_schema: { type: "object", properties: {}, additionalProperties: false },
    is_destructive: false,
    requires_confirmation: true,
    rollback: "pc.wake",
  },
  {
    slug: "pc.status",
    description:
      "Liest Uptime, CPU-Last, RAM-Auslastung und aktiven User vom PC (read-only).",
    input_schema: { type: "object", properties: {}, additionalProperties: false },
    is_destructive: false,
    requires_confirmation: false,
    rollback: null,
  },
  {
    slug: "pc.run_script",
    description:
      "Startet ein Skript aus der festen Skript-Whitelist auf dem PC. " +
      `Erlaubt sind ausschließlich: ${SCRIPT_WHITELIST.join(", ")}.`,
    input_schema: {
      type: "object",
      properties: {
        script: {
          type: "string",
          enum: SCRIPT_WHITELIST,
          description: "Name des Whitelist-Skripts.",
        },
      },
      required: ["script"],
      additionalProperties: false,
    },
    is_destructive: false,
    requires_confirmation: true,
    rollback: null,
  },
  {
    slug: "datadog.alerts",
    description:
      "Ruft aktuell alarmierende Datadog-Monitore ab (Alert/Warn, read-only).",
    input_schema: { type: "object", properties: {}, additionalProperties: false },
    is_destructive: false,
    requires_confirmation: false,
    rollback: null,
  },
  {
    slug: "jira.my_tickets",
    description:
      "Ruft die offenen Jira-Tickets des Users ab (assignee = currentUser, read-only).",
    input_schema: { type: "object", properties: {}, additionalProperties: false },
    is_destructive: false,
    requires_confirmation: false,
    rollback: null,
  },
  {
    slug: "spotify.now_playing",
    description: "Liest den aktuell laufenden Spotify-Track (read-only).",
    input_schema: { type: "object", properties: {}, additionalProperties: false },
    is_destructive: false,
    requires_confirmation: false,
    rollback: null,
  },
  {
    slug: "summary.day",
    description:
      "Generiert eine kompakte Tages-Summary aus offenen Jira-Tickets und aktiven Datadog-Alerts (read-only).",
    input_schema: { type: "object", properties: {}, additionalProperties: false },
    is_destructive: false,
    requires_confirmation: false,
    rollback: null,
  },
];

export const bySlug = (slug) => TOOLS.find((t) => t.slug === slug);
export const toApiName = (slug) => slug.replace(/\./g, "__");
export const fromApiName = (name) => name.replace(/__/g, ".");

// Nur die Felder, die die Anthropic Messages API kennt.
export const anthropicTools = () =>
  TOOLS.map((t) => ({
    name: toApiName(t.slug),
    description: t.description,
    input_schema: t.input_schema,
  }));
