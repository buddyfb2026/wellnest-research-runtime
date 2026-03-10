#!/usr/bin/env bash
set -euo pipefail

workflow_artifact_id="${1:-}"
competitor_artifact_id="${2:-}"

if [ -z "$workflow_artifact_id" ]; then
  workflow_artifact_id="$(psql "$DATABASE_URL" -X -q -A -t -c "select artifact_id from artifacts where artifact_type='workflow_candidate' and status='ready' order by created_at desc limit 1;")"
fi

if [ -z "$competitor_artifact_id" ]; then
  competitor_artifact_id="$(psql "$DATABASE_URL" -X -q -A -t -c "select artifact_id from artifacts where artifact_type='competitor_analysis' and status='ready' order by created_at desc limit 1;")"
fi

if [ -z "$workflow_artifact_id" ] || [ -z "$competitor_artifact_id" ]; then
  echo "missing workflow_candidate or competitor_analysis artifact" >&2
  exit 1
fi

psql "$DATABASE_URL" <<SQL
INSERT INTO jobs (
  job_type,
  lane,
  agent,
  status,
  priority,
  input_ref,
  input_artifact_id,
  input_artifact_id_2,
  idempotency_key
)
VALUES (
  'opportunity_ranking',
  'opportunity',
  'atlas',
  'queued',
  100,
  'merge explicit workflow and competitor artifacts',
  '$workflow_artifact_id',
  '$competitor_artifact_id',
  'atlas:$workflow_artifact_id:$competitor_artifact_id'
);
SQL
