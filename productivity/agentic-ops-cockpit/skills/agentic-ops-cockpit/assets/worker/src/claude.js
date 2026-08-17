// Claude-Schicht: interpretiert den iPhone-Prompt, wählt Tool-Calls aus der
// Whitelist, führt Read-Aktionen sofort aus und sammelt bestätigungspflichtige
// Aktionen als "pending" (Observer-Mode). Max. 3 Runden, dann Synthese.

import { anthropicTools, fromApiName, bySlug } from "./tools.js";
import { execute } from "./actions.js";
import { GUARD } from "./guard.js";

const SYSTEM = [
  "Du bist der Action-Router von Georges Agentic Ops Cockpit.",
  "Du bekommst einen kurzen Sprach- oder Text-Prompt vom iPhone und wählst",
  "ausschließlich aus den definierten Tools. Du erfindest keine Tools und",
  "führst nichts außerhalb der Whitelist aus.",
  "Bestätigungspflichtige Aktionen (pc.wake, pc.sleep, pc.run_script) werden",
  "vom System als Vorschlag ans iPhone geschickt — kündige sie in deiner",
  "Antwort kurz an, behaupte aber nie, sie seien schon ausgeführt.",
  "Antworte auf Deutsch, kompakt genug für eine Push-Notification",
  "(maximal 3 kurze Sätze). Keine URLs, keine Secrets, keine Trace-IDs im Text.",
  "Zeitangaben in Europe/Berlin.",
].join(" ");

export async function interpret(prompt, env, traceId) {
  const messages = [{ role: "user", content: prompt }];
  const results = [];
  const pending = [];
  let reply = "";

  for (let round = 0; round < GUARD.MAX_CLAUDE_ROUNDS; round++) {
    const resp = await anthropicCall(env, messages);
    const text = resp.content
      .filter((b) => b.type === "text")
      .map((b) => b.text)
      .join("\n")
      .trim();
    if (text) reply = text;

    const toolUses = resp.content.filter((b) => b.type === "tool_use");
    if (resp.stop_reason !== "tool_use" || toolUses.length === 0) break;

    const toolResults = [];
    for (const tu of toolUses) {
      const slug = fromApiName(tu.name);
      const tool = bySlug(slug);
      if (!tool) {
        toolResults.push(toolResult(tu.id, { status: "rejected", error: "Nicht in Whitelist." }, true));
        continue;
      }
      if (tool.requires_confirmation) {
        pending.push({ action: slug, params: tu.input ?? {} });
        toolResults.push(
          toolResult(tu.id, {
            status: "pending_confirmation",
            note: "Wird erst nach Bestätigung am iPhone ausgeführt.",
          })
        );
        continue;
      }
      try {
        const out = await execute(slug, tu.input ?? {}, env, traceId);
        results.push({ action: slug, result: out });
        toolResults.push(toolResult(tu.id, out));
      } catch (e) {
        const err = { status: "error", error: String(e.message) };
        results.push({ action: slug, result: err });
        toolResults.push(toolResult(tu.id, err, true));
      }
    }
    messages.push({ role: "assistant", content: resp.content });
    messages.push({ role: "user", content: toolResults });
  }

  return { reply, results, pending };
}

function toolResult(id, payload, isError = false) {
  const block = {
    type: "tool_result",
    tool_use_id: id,
    content: JSON.stringify(payload).slice(0, 4000),
  };
  if (isError) block.is_error = true;
  return block;
}

async function anthropicCall(env, messages) {
  const res = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "x-api-key": env.ANTHROPIC_API_KEY,
      "anthropic-version": "2023-06-01",
      "content-type": "application/json",
    },
    body: JSON.stringify({
      model: env.CLAUDE_MODEL || "claude-sonnet-5",
      max_tokens: 1024,
      system: SYSTEM,
      tools: anthropicTools(),
      messages,
    }),
  });
  if (!res.ok) {
    const detail = (await res.text()).slice(0, 300);
    throw new Error(`Claude API HTTP ${res.status}: ${detail}`);
  }
  return res.json();
}
