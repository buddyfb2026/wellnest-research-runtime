#!/usr/bin/env bash
set -euo pipefail

DB="${DB:-research_intelligence}"
OUTDIR="${OUTDIR:-$HOME/ri_db/outputs}"
mkdir -p "$OUTDIR"

N_OPPS="${N_OPPS:-12}"
N_SIGNALS="${N_SIGNALS:-40}"
N_WORKFLOWS="${N_WORKFLOWS:-20}"
N_COMPETITORS="${N_COMPETITORS:-20}"

PSQL_BIN="${PSQL_BIN:-/opt/homebrew/opt/postgresql@16/bin/psql}"

opps_json="$("$PSQL_BIN" "$DB" -t -A -v ON_ERROR_STOP=1 -c "
SELECT COALESCE(jsonb_agg(to_jsonb(o) ORDER BY created_at DESC),'[]'::jsonb)
FROM (
  SELECT id,title,description,signal_strength,priority,evidence_sources,created_at
  FROM product_opportunities
  ORDER BY created_at DESC
  LIMIT $N_OPPS
) o;
")"

signals_json="$("$PSQL_BIN" "$DB" -t -A -v ON_ERROR_STOP=1 -c "
SELECT COALESCE(jsonb_agg(to_jsonb(s)),'[]'::jsonb)
FROM (
  SELECT *
  FROM creator_signals
  ORDER BY id DESC
  LIMIT $N_SIGNALS
) s;
")"

workflows_json="$("$PSQL_BIN" "$DB" -t -A -v ON_ERROR_STOP=1 -c "
SELECT COALESCE(jsonb_agg(to_jsonb(w)),'[]'::jsonb)
FROM (
  SELECT *
  FROM wellnest_workflows
  ORDER BY id DESC
  LIMIT $N_WORKFLOWS
) w;
")"

competitors_json="$("$PSQL_BIN" "$DB" -t -A -v ON_ERROR_STOP=1 -c "
SELECT COALESCE(jsonb_agg(to_jsonb(c)),'[]'::jsonb)
FROM (
  SELECT *
  FROM competitors
  ORDER BY id DESC
  LIMIT $N_COMPETITORS
) c;
")"

python3 - <<PY > "$OUTDIR/karen_input.json"
import json, datetime

opps = json.loads('''${opps_json}'''.strip() or "[]")
signals = json.loads('''${signals_json}'''.strip() or "[]")
workflows = json.loads('''${workflows_json}'''.strip() or "[]")
competitors = json.loads('''${competitors_json}'''.strip() or "[]")

out = {
  "created_at": datetime.datetime.utcnow().isoformat() + "Z",
  "spec_requirements": {
    "goal": "Generate app-build-ready WellNest feature specifications grounded in research and analysis.",
    "required_sections": [
      "feature_name",
      "summary",
      "problem",
      "target_users",
      "research_basis",
      "product_goals",
      "feature_description",
      "key_screens",
      "user_flows",
      "system_behavior",
      "data_objects",
      "inputs",
      "outputs",
      "edge_cases",
      "non_functional_requirements",
      "test_cases",
      "acceptance_criteria",
      "mvp_scope",
      "future_enhancements",
      "dependencies",
      "success_metrics",
      "implementation_notes"
    ]
  },
  "top_opportunities": opps,
  "creator_signals": signals,
  "wellnest_workflows": workflows,
  "competitors": competitors
}

print(json.dumps(out, indent=2))
PY

echo "OK: wrote $OUTDIR/karen_input.json"
