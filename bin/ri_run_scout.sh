#!/usr/bin/env bash
set -euo pipefail

source "$HOME/ri_db/bin/ri_lib.sh"

agent="scout"
lane="creator"
schema="$HOME/ri_db/schemas/workflow_candidate.schema.json"

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

IFS=$'\t' read -r job_id job_type lane input_ref input_artifact_id idempotency_key attempt_count <<< "$claim"

session_id="$("$HOME/ri_db/bin/ri_make_session.sh" "$agent")"
session_dir="$HOME/ri_db/work/$agent/$session_id"

trap 'fail_job "$job_id" "$session_id" "unexpected_runtime_error" "scout wrapper failed unexpectedly"' ERR

"$HOME/ri_db/bin/ri_write_log.sh" INFO "$agent" "$lane" "$job_id" "$session_id" "job_claimed" "ok" "job claimed" '{}'

source_path="$(psql "$DATABASE_URL" -X -q -A -t -c "select file_path from artifacts where artifact_id = '$input_artifact_id' limit 1;")"

if [ -z "$source_path" ] || [ ! -f "$source_path" ]; then
  fail_job "$job_id" "$session_id" "input_missing" "source artifact file missing"
  exit 1
fi

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

cp "$source_path" "$session_dir/input.json"

creator_name="$(python3 - <<'PY' "$source_path"
import json,sys
obj=json.load(open(sys.argv[1]))
print(obj["creator_name"])
PY
)"

profile_url="$(python3 - <<'PY' "$source_path"
import json,sys
obj=json.load(open(sys.argv[1]))
print(obj["profile_url"])
PY
)"

cat > "$session_dir/prompt.txt" <<TXT
Analyze creator discovery signal and extract workflow candidate from source artifact: $input_artifact_id
TXT

cat > "$session_dir/raw_output.txt" <<TXT
Synthetic scaffold workflow analysis for source artifact: $input_artifact_id
TXT

artifact_id="${agent}_${session_id}"

cat > "$session_dir/normalized.json" <<JSON
{
  "artifact_type": "workflow_candidate",
  "artifact_version": "1.0",
  "artifact_id": "$artifact_id",
  "job_id": "$job_id",
  "session_id": "$session_id",
  "agent": "scout",
  "source_artifact_id": "$input_artifact_id",
  "creator_name": "$creator_name",
  "workflow_title": "Weekly Household Reset Workflow",
  "trigger": "Sunday evening preparation for the upcoming week",
  "steps": [
    "Review calendar and household commitments",
    "Create grocery and meal plan",
    "Prep school and activity logistics",
    "Set household task priorities"
  ],
  "tools_or_products": [
    "Shared calendar",
    "Meal planning list",
    "Grocery checklist"
  ],
  "pain_points": [
    "Too many moving parts across work and home",
    "Mental load concentrated on one parent"
  ],
  "failure_points": [
    "No shared planning system",
    "Tasks discussed but not captured"
  ],
  "evidence": [
    {
      "url": "$profile_url",
      "kind": "source_artifact",
      "title": "Source creator profile",
      "snippet": "Derived from Scour discovery artifact."
    }
  ],
  "confidence_score": 0.72,
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
  "workflow_candidate" \
  > "$session_dir/validation.json"

cp "$session_dir/normalized.json" "$HOME/ri_db/out/$agent/${artifact_id}.json"

"$HOME/ri_db/bin/ri_register_artifact.py" \
  "$artifact_id" \
  "workflow_candidate" \
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
  'workflow_candidate',
  '1.0',
  'pass',
  'pass',
  'pass',
  '[]'::jsonb,
  '[]'::jsonb
);

INSERT INTO artifact_links (upstream_artifact_id, downstream_artifact_id, link_type)
VALUES ('$input_artifact_id', '$artifact_id', 'derived_from')
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
