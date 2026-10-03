// Builds one bench case from the exact Scrum4Me task text. Usage: node s4m-case.mjs <sprint_id> <task_id> <id> <repo_url> <base> <ref> <hidden,...> <lines> <kind>
// The server config (command, args, env) comes from ~/.claude.json; no env value is printed.
import { readFileSync } from "node:fs";
import { homedir } from "node:os";
const SDK = "/Users/janpetervisser/Development/scrum4me-mcp-stable/node_modules/@modelcontextprotocol/sdk/dist/esm/client";
const { Client } = await import(`${SDK}/index.js`);
const { StdioClientTransport, getDefaultEnvironment } = await import(`${SDK}/stdio.js`);
const [sprint_id, task_id, id, repo_url, base, ref, hidden, lines, kind] = process.argv.slice(2);
const cfg = JSON.parse(readFileSync(`${homedir()}/.claude.json`, "utf8")).mcpServers.scrum4me;
const transport = new StdioClientTransport({ command: cfg.command, args: cfg.args, env: { ...getDefaultEnvironment(), ...cfg.env }, stderr: "ignore" });
const client = new Client({ name: "m7-case", version: "1.0.0" });
await client.connect(transport);
try {
  const res = await client.callTool({ name: "get_sprint_context", arguments: { sprint_id, task_id } }, undefined, { timeout: 120000 });
  if (res.isError) throw new Error((res.content || []).map((c) => c.text || "").join("\n").slice(0, 300));
  const t = JSON.parse(res.content.map((c) => c.text || "").join("")).selected_task;
  if (!t || t.status !== "done") throw new Error("taak niet gevonden of niet done");
  const c = { id, repo_url, base_commit: base, ref_commit: ref,
    task: { code: t.code, title: t.title, description: t.description ?? null, implementation_plan: t.implementation_plan ?? null },
    story: { title: t.story.title, description: t.story.description ?? null, acceptance_criteria: t.story.acceptance_criteria ?? null },
    hidden_tests: hidden.split(","), lines: Number(lines), kind };
  process.stdout.write(JSON.stringify(c) + "\n");
} finally { await client.close(); }
