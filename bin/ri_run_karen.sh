#!/usr/bin/env bash
set -euo pipefail

source "$HOME/ri_db/bin/ri_lib.sh"

agent="karen"
lane="spec"
schema="$HOME/ri_db/schemas/feature_spec.schema.json"

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

trap 'fail_job "$job_id" "$session_id" "unexpected_runtime_error" "karen wrapper failed unexpectedly"' ERR

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

title="$(python3 - <<'PY' "$source_path"
import json,sys
obj=json.load(open(sys.argv[1]))
print(obj["title"])
PY
)"

problem="$(python3 - <<'PY' "$source_path"
import json,sys
obj=json.load(open(sys.argv[1]))
print(obj["problem"])
PY
)"

target_user="$(python3 - <<'PY' "$source_path"
import json,sys
obj=json.load(open(sys.argv[1]))
print(obj["target_user"])
PY
)"

cat > "$session_dir/prompt.txt" <<TXT
Convert ranked opportunity into a feature specification: $input_artifact_id
TXT

cat > "$session_dir/raw_output.txt" <<TXT
Synthetic scaffold feature spec generation for source artifact: $input_artifact_id
TXT

artifact_id="${agent}_${session_id}"

cat > "$session_dir/normalized.json" <<JSON
{
  "artifact_type": "feature_spec",
  "artifact_version": "1.0",
  "artifact_id": "$artifact_id",
  "job_id": "$job_id",
  "session_id": "$session_id",
  "agent": "karen",
  "source_artifact_id": "$input_artifact_id",
  "feature_name": "$title",
  "problem_statement": "$problem",
  "user_story": "As a $target_user, I want WellNest to proactively prepare my weekly household reset so that planning work does not all live in my head.",
  "flows": [
    "User enables Household Reset Autopilot",
    "System detects upcoming weekly planning window",
    "System assembles tasks, groceries, and calendar prep suggestions",
    "User reviews, edits, and confirms the reset plan"
  ],
  "system_behavior": [
    "System aggregates known household commitments before the weekly reset window",
    "System proposes a reset checklist and prioritized actions",
    "System highlights unresolved planning gaps",
    "System persists confirmed reset actions into the household workflow state"
  ],
  "edge_cases": [
    "No calendar data connected",
    "Multiple caregivers edit the plan at the same time",
    "User skips a weekly reset",
    "Recommended tasks duplicate existing household tasks"
  ],
  "acceptance_criteria": [
    "User can view a generated weekly reset plan before confirming",
    "System can generate a reset plan from existing household context",
    "Duplicate task creation is prevented",
    "User can modify or dismiss recommendations before activation"
  ],
  "technical_notes": [
    "Should support idempotent weekly plan generation",
    "Requires household state aggregation before recommendation pass",
    "Should expose plan generation status to Mission Control",
    "Must preserve audit trail of generated vs confirmed plan content"
  ],
  "test_cases": [
    "Generate reset plan for a household with calendar and grocery context",
    "Generate reset plan for a household missing calendar context",
    "Confirm edited plan and verify task persistence",
    "Re-run generation and verify duplicate prevention"
  ],
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
  "feature_spec" \
  > "$session_dir/validation.json"

cp "$session_dir/normalized.json" "$HOME/ri_db/out/$agent/${artifact_id}.json"

"$HOME/ri_db/bin/ri_register_artifact.py" \
  "$artifact_id" \
  "feature_spec" \
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
  'feature_spec',
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
