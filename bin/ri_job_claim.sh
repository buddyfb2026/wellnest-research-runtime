#!/usr/bin/env bash
set -euo pipefail

agent="${1:?agent required}"

psql "$DATABASE_URL" -X -q -A -t -F $'\t' <<SQL
WITH next_job AS (
  SELECT job_id
  FROM jobs
  WHERE status = 'queued'
    AND agent = '$agent'
    AND attempt_count < max_attempts
  ORDER BY priority ASC, created_at ASC
  LIMIT 1
  FOR UPDATE SKIP LOCKED
)
UPDATE jobs j
SET status = 'claimed',
    claimed_at = NOW(),
    attempt_count = attempt_count + 1
FROM next_job
WHERE j.job_id = next_job.job_id
RETURNING
  j.job_id,
  j.job_type,
  j.lane,
  j.input_ref,
  j.input_artifact_id,
  j.input_artifact_id_2,
  j.idempotency_key,
  j.attempt_count;
SQL
