// Call one department tool through the gateway. Run from the repo root; Node 22.18+ runs .ts files directly:
//   node examples/ts/ask.ts supplier-delay-triage triage-default "A storm closed the port. 2 days late."
// Exit 0 = valid reply, 1 = invalid (take the fallback path), 2 = the call failed.
// No PII masking here: mask upstream (gateway/pii.py is the reference) before sending personal data.
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

type Contract = { fields: Record<string, string[] | "bool">; text: string[] };

const [tool, alias, text] = process.argv.slice(2);
if (!tool || !alias || text === undefined) {
  console.error("usage: ask.ts <tool> <alias> <text>");
  process.exit(2);
}
const dir = join("tools", tool);
if (!existsSync(dir)) {
  console.error(`unknown tool "${tool}"`);
  process.exit(2);
}
const prompt = readFileSync(join(dir, "prompt.md"), "utf8");
const contract: Contract = JSON.parse(readFileSync(join(dir, "contract.json"), "utf8"));
const url = (process.env.GATEWAY_URL ?? "http://localhost:4000").replace(/\/$/, "");
const key = process.env.GATEWAY_KEY ?? "sk-dev-only-master"; // in real use, the tool's own key

function valid(raw: string, c: Contract): boolean {
  let out: unknown;
  try {
    out = JSON.parse(raw);
  } catch {
    return false;
  }
  if (typeof out !== "object" || out === null || Array.isArray(out)) return false;
  const o = out as Record<string, unknown>;
  const want = [...Object.keys(c.fields), ...c.text].sort();
  if (JSON.stringify(Object.keys(o).sort()) !== JSON.stringify(want)) return false; // exact key set
  for (const [k, allowed] of Object.entries(c.fields)) {
    const ok = allowed === "bool" ? typeof o[k] === "boolean" : allowed.includes(o[k] as string);
    if (!ok) return false;
  }
  return c.text.every((k) => typeof o[k] === "string" && o[k] !== "");
}

let raw: string;
try {
  const r = await fetch(`${url}/v1/chat/completions`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${key}` },
    body: JSON.stringify({
      model: alias,
      temperature: 0,
      max_tokens: 400,
      messages: [
        { role: "system", content: prompt },
        { role: "user", content: `<input>${text}</input>` }, // untrusted data, as the prompt says
      ],
    }),
    signal: AbortSignal.timeout(60_000),
  });
  if (!r.ok) throw new Error(`http ${r.status}`);
  raw = (await r.json()).choices[0].message.content ?? "";
} catch (e) {
  console.error(`gateway call failed: ${(e as Error).message}`);
  process.exit(2);
}

const ok = valid(raw, contract);
console.log(`alias=${alias} valid=${ok}\n${raw}`);
process.exit(ok ? 0 : 1);
