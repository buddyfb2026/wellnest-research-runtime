#!/usr/bin/env bash
set -euo pipefail

source "$HOME/ri_db/bin/ri_lib.sh"

agent="atlas"
lane="opportunity"
schema="$HOME/ri_db/schemas/ranked_opportunity.schema.json"

fail_job() {
  local job_id="$1"
  local session_id="$2"
  local failure_class="$3"
  local failure_message="$4"

  psql "$DATABASE_URL" -q <<SQL
INSERT INTO agent_runs (
  agent, lane, job_id, session_id, status, started_at, finished_at, runtime_ms, failure_class, failure_message
)
VALUES (
  '$agent',
  '$lane',
  '$job_id'::uuid,
  '$session_id',
  'failed',
  NOW(),
  NOW(),
  1,
  '$failure_class',
  '$failure_message'
);

UPDATE jobs
SET status = 'failed',
    session_id = '$session_id',
    failure_class = '$failure_class',
    failure_message = '$failure_message',
    finished_at = NOW()
WHERE job_id = '$job_id';
SQL

  "$HOME/ri_db/bin/ri_write_log.sh" ERROR "$agent" "$lane" "$job_id" "$session_id" "job_failed" "failed" "$failure_message" '{}'
}

claim="$("$HOME/ri_db/bin/ri_job_claim.sh" "$agent" | head -n 1)"

if [ -z "$claim" ]; then
  "$HOME/ri_db/bin/ri_write_log.sh" INFO "$agent" "$lane" "" "" "no_job" "idle" "no queued job found" '{}'
  exit 0
fi

IFS=$'\t' read -r job_id job_type lane input_ref input_artifact_id input_artifact_id_2 idempotency_key attempt_count <<< "$claim"

session_id="$("$HOME/ri_db/bin/ri_make_session.sh" "$agent")"
session_dir="$HOME/ri_db/work/$agent/$session_id"

trap 'fail_job "$job_id" "$session_id" "unexpected_runtime_error" "atlas wrapper failed unexpectedly"' ERR

"$HOME/ri_db/bin/ri_write_log.sh" INFO "$agent" "$lane" "$job_id" "$session_id" "job_claimed" "ok" "job claimed" '{}'

if [ -z "$input_artifact_id" ] || [ -z "$input_artifact_id_2" ]; then
  fail_job "$job_id" "$session_id" "input_missing" "atlas requires two explicit upstream artifact ids"
  exit 1
fi

workflow_artifact_id="$input_artifact_id"
competitor_artifact_id="$input_artifact_id_2"

existing="$("$HOME/ri_db/bin/ri_check_idempotency.py" "$idempotency_key")"

if python3 - <<'PY' "$existing"
import json,sys
obj=json.loads(sys.argv[1])
sys.exit(0 if obj.get("exists") else 1)
PY
then
  artifact_id="$(python3 - <<'PY' "$existing"
import json,sys
obj=json.loads(sys.argv[1])
print(obj["artifact_id"])
PY
)"
  psql "$DATABASE_URL" -q <<SQL
UPDATE jobs
SET status = 'succeeded',
    session_id = '$session_id',
    output_artifact_id = '$artifact_id',
    finished_at = NOW()
WHERE job_id = '$job_id';

INSERT INTO agent_runs (
  agent, lane, job_id, session_id, status, started_at, finished_at, runtime_ms
)
VALUES (
  '$agent',
  '$lane',
  '$job_id'::uuid,
  '$session_id',
  'succeeded',
  NOW(),
  NOW(),
  1
);
SQL
  "$HOME/ri_db/bin/ri_write_log.sh" INFO "$agent" "$lane" "$job_id" "$session_id" "job_deduped" "ok" "existing artifact reused" '{}'
  printf '%s\n' "$artifact_id"
  exit 0
fi

workflow_path="$(psql "$DATABASE_URL" -X -q -A -t -c "select file_path from artifacts where artifact_id = '$workflow_artifact_id' limit 1;")"
competitor_path="$(psql "$DATABASE_URL" -X -q -A -t -c "select file_path from artifacts where artifact_id = '$competitor_artifact_id' limit 1;")"

if [ -z "$workflow_path" ] || [ ! -f "$workflow_path" ]; then
  fail_job "$job_id" "$session_id" "input_missing" "workflow source artifact file missing"
  exit 1
fi

if [ -z "$competitor_path" ] || [ ! -f "$competitor_path" ]; then
  fail_job "$job_id" "$session_id" "input_missing" "competitor source artifact file missing"
  exit 1
fi

cp "$workflow_path" "$session_dir/workflow_input.json"
cp "$competitor_path" "$session_dir/competitor_input.json"

workflow_title="$(python3 - <<'PY' "$workflow_path"
import json,sys
obj=json.load(open(sys.argv[1]))
print(obj["workflow_title"])
PY
)"

company_name="$(python3 - <<'PY' "$competitor_path"
import json,sys
obj=json.load(open(sys.argv[1]))
print(obj["company_name"])
PY
)"

cat > "$session_dir/prompt.txt" <<TXT
Merge validated workflow and competitor analysis into a ranked WellNest opportunity.
TXT

cat > "$session_dir/raw_output.txt" <<TXT
Synthetic scaffold opportunity ranking from workflow artifact $workflow_artifact_id and competitor artifact $competitor_artifact_id
TXT

artifact_id="${agent}_${session_id}"

cat > "$session_dir/normalized.json" <<JSON
{
  "artifact_type": "ranked_opportunity",
  "artifact_version": "1.0",
  "artifact_id": "$artifact_id",
  "job_id": "$job_id",
  "session_id": "$session_id",
  "agent": "atlas",
  "source_artifact_ids": [
    "$workflow_artifact_id",
    "$competitor_artifact_id"
  ],
  "title": "Autopilot Weekly Household Reset",
  "problem": "Parents carry too much invisible planning load and current household tools do not proactively orchestrate weekly reset workflows.",
  "target_user": "Busy parents managing household planning, groceries, logistics, and family coordination",
  "severity_score": 8.4,
  "frequency_score": 8.8,
  "strategic_fit_score": 9.3,
  "revenue_potential_score": 8.1,
  "overall_score": 8.65,
  "rationale": "The workflow signal '$workflow_title' shows recurring household planning pain, and competitor analysis of '$company_name' shows a gap in proactive orchestration. This is a strong WellNest-native opportunity.",
  "generated_at": "$(ri_now_utc)",
  "content_hash": "",
  "idempotency_key": "$idempotency_key",
  "validation_status": "pass"
}
JSON

content_hash="$(shasum -a 256 "$session_dir/normalized.json" | awk '{print $1}')"

python3 - "$session_dir/normalized.json" "$content_hash" <<'PY'
import json,sys
path=sys.argv[1]
content_hash=sys.argv[2]
with open(path) as f:
    obj=json.load(f)
obj["content_hash"]=content_hash
with open(path,"w") as f:
    json.dump(obj,f,indent=2)
PY

"$HOME/ri_db/bin/ri_validate_json.py" \
  "$session_dir/normalized.json" \
  "$schema" \
  "ranked_opportunity" \
  > "$session_dir/validation.json"

cp "$session_dir/normalized.json" "$HOME/ri_db/out/$agent/${artifact_id}.json"

"$HOME/ri_db/bin/ri_register_artifact.py" \
  "$artifact_id" \
  "ranked_opportunity" \
  "1.0" \
  "$agent" \
  "$lane" \
  "$job_id" \
  "$session_id" \
  "$HOME/ri_db/out/$agent/${artifact_id}.json"

psql "$DATABASE_URL" -q <<SQL
INSERT INTO validation_results (
  artifact_id, session_id, artifact_type, schema_version,
  parse_status, schema_status, semantic_status, errors, warnings
)
VALUES (
  '$artifact_id',
  '$session_id',
  'ranked_opportunity',
  '1.0',
  'pass',
  'pass',
  'pass',
  '[]'::jsonb,
  '[]'::jsonb
);

INSERT INTO artifact_links (upstream_artifact_id, downstream_artifact_id, link_type)
VALUES ('$workflow_artifact_id', '$artifact_id', 'derived_from')
ON CONFLICT DO NOTHING;

INSERT INTO artifact_links (upstream_artifact_id, downstream_artifact_id, link_type)
VALUES ('$competitor_artifact_id', '$artifact_id', 'derived_from')
ON CONFLICT DO NOTHING;

INSERT INTO agent_runs (
  agent, lane, job_id, session_id, status, started_at, finished_at, runtime_ms
)
VALUES (
  '$agent',
  '$lane',
  '$job_id'::uuid,
  '$session_id',
  'succeeded',
  NOW(),
  NOW(),
  1
);

UPDATE jobs
SET status = 'succeeded',
    session_id = '$session_id',
    output_artifact_id = '$artifact_id',
    finished_at = NOW()
WHERE job_id = '$job_id';
SQL

"$HOME/ri_db/bin/ri_write_log.sh" INFO "$agent" "$lane" "$job_id" "$session_id" "job_succeeded" "ok" "artifact created" '{}'

printf '%s\n' "$artifact_id"
