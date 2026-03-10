#!/opt/homebrew/bin/node
import fs from "node:fs";
import process from "node:process";
import { spawnSync } from "node:child_process";

const agentId = process.argv[2];
const inputPath = process.argv[3];

if (!agentId || !inputPath) {
  console.error("usage: oc_ws_invoke_file.mjs <agentId> <input_json_path>");
  process.exit(2);
}

const raw = fs.readFileSync(inputPath, "utf8").trim();
if (!raw) {
  console.error("ERROR: input file empty");
  process.exit(1);
}

let contract = `Return JSON only. Follow your identity output contract strictly.\n`;

if (agentId === "scout") {
  contract = `Return JSON only.

You MUST output EXACTLY this schema:

{
  "schema":"wellnest.workflow.discovery.v1",
  "run_id":"<string>",
  "wellnest_workflows":[
    {"title":"...","description":"...","trigger":"...","steps":["..."],"failure_points":["..."]}
  ],
  "pain_signals":["..."],
  "automation_opportunities":[{"title":"...","description":"..."}]
}

Rules:
- Generate 5–15 wellnest_workflows from INPUT_JSON creators list.
- steps must be concrete and sequential.
- Return JSON only.`;
}

if (agentId === "franz") {
  contract = `Return JSON only.

You MUST output EXACTLY this schema:

{
  "schema":"wellnest.competitor.intel.v1",
  "run_id":"<string>",
  "feature_map":[{"product":"...","features":["..."]}],
  "workflow_gaps":["..."],
  "opportunities":[{"title":"...","description":"..."}]
}

Rules:
- Derive workflow_gaps/opportunities from INPUT_JSON competitors list.
- Return JSON only.`;
}

if (agentId === "atlas") {
  contract = `Return JSON only.

You MUST output EXACTLY this schema:

{
  "schema":"wellnest.opportunity.ranking.v1",
  "run_id":"<string>",
  "top_opportunities":[
    {
      "title":"...",
      "workflow_id": 0,
      "workflow_title":"...",
      "problem":"...",
      "solution":"...",
      "expected_user_value":"...",
      "frequency":"daily|weekly|monthly|seasonal",
      "effort":"S|M|L",
      "confidence": 0.0,
      "reasoning":"..."
    }
  ]
}

Rules:
- Use INPUT_JSON.wellnest_workflows as the only source.
- Produce 5–12 opportunities.
- Return JSON only.`;
}

if (agentId === "karen") {
  contract = `Return JSON only.

You MUST output EXACTLY this schema:

{
  "schema":"wellnest.feature_specs.v2",
  "run_id":"<string>",
  "feature_specs":[
    {
      "feature_name":"...",
      "summary":"...",
      "problem":"...",
      "target_users":["..."],
      "research_basis":{
        "opportunity_summary":"...",
        "creator_signals":["..."],
        "workflow_signals":["..."],
        "competitor_context":["..."],
        "evidence":["..."]
      },
      "product_goals":["..."],
      "feature_description":"...",
      "key_screens":["..."],
      "user_flows":["..."],
      "system_behavior":"...",
      "data_objects":["..."],
      "inputs":["..."],
      "outputs":["..."],
      "edge_cases":["..."],
      "non_functional_requirements":["..."],
      "test_cases":["..."],
      "acceptance_criteria":["..."],
      "mvp_scope":["..."],
      "future_enhancements":["..."],
      "dependencies":["..."],
      "success_metrics":["..."],
      "implementation_notes":"..."
    }
  ]
}

Rules:
- Use INPUT_JSON.top_opportunities as the primary source.
- Ground each spec in INPUT_JSON.creator_signals, INPUT_JSON.wellnest_workflows, and INPUT_JSON.competitors when relevant.
- Produce 3–8 feature_specs.
- Write app-build-ready SaaS functional specs, not concept blurbs.
- Include concrete user flows, system behavior, edge cases, test cases, and success metrics.
- Prefer proactive household operating behavior over passive checklist behavior.
- Return JSON only.`;
}

const prompt = `${contract}

INPUT_JSON:
${raw}
`;

function stripFences(s) {
  let out = s.trim();
  if (out.startsWith("```json")) {
    out = out.replace(/^```json\s*/i, "").replace(/\s*```\s*$/i, "").trim();
  } else if (out.startsWith("```")) {
    out = out.replace(/^```\s*/i, "").replace(/\s*```\s*$/i, "").trim();
  }
  return out;
}

function extractJsonBlock(s) {
  const text = stripFences(s);
  const starts = [];
  const objIdx = text.indexOf("{");
  const arrIdx = text.indexOf("[");
  if (objIdx >= 0) starts.push(objIdx);
  if (arrIdx >= 0) starts.push(arrIdx);
  if (starts.length === 0) return null;

  const start = Math.min(...starts);
  const open = text[start];
  const close = open === "{" ? "}" : "]";
  let depth = 0;
  let inString = false;
  let escape = false;

  for (let i = start; i < text.length; i++) {
    const ch = text[i];

    if (inString) {
      if (escape) {
        escape = false;
      } else if (ch === "\\") {
        escape = true;
      } else if (ch === "\"") {
        inString = false;
      }
      continue;
    }

    if (ch === "\"") {
      inString = true;
      continue;
    }

    if (ch === open) depth++;
    if (ch === close) depth--;

    if (depth === 0) {
      return text.slice(start, i + 1).trim();
    }
  }

  return null;
}

const r = spawnSync(
  "openclaw",
  ["agent", "--local", "--agent", agentId, "--session-id", `ri-${agentId}-${Date.now()}`, "-m", prompt],
  {
    stdio: ["ignore", "pipe", "inherit"],
    env: { ...process.env, OLLAMA_API_KEY: process.env.OLLAMA_API_KEY || "ollama-local" },
    cwd: process.env.HOME + "/ri_db",
    encoding: "utf8"
  }
);

const stdout = (r.stdout || "").trim();
const extracted = extractJsonBlock(stdout);

if (!extracted) {
  console.error("ERROR: no JSON found in agent output");
  process.exit(r.status || 1 || 1);
}

try {
  JSON.parse(extracted);
} catch (err) {
  console.error("ERROR: extracted output is not valid JSON");
  process.exit(1);
}

process.stdout.write(extracted + "\n");
process.exit(0);
