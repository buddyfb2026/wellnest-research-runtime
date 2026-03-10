#!/usr/bin/env bash
set -euo pipefail

artifact_id="${1:-}"

if [ -z "$artifact_id" ]; then
  artifact_id="$(psql "$DATABASE_URL" -X -q -A -t -c "select artifact_id from artifacts where artifact_type='creator_discovery_signal' and status='ready' order by created_at desc limit 1;")"
fi

if [ -z "$artifact_id" ]; then
  echo "no creator_discovery_signal artifact found" >&2
  exit 1
fi

psql "$DATABASE_URL" <<SQL
INSERT INTO jobs (
  job_type, lane, agent, status, priority, input_ref, input_artifact_id, idempotency_key
)
VALUES (
  'workflow_extraction',
  'creator',
  'scout',
  'queued',
  100,
  'workflow extraction from creator discovery',
  '$artifact_id',
  'scout:$artifact_id'
);
SQL
