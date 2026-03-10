#!/usr/bin/env bash
set -euo pipefail

query="${1:?query required}"
priority="${2:-100}"

key_slug="$(printf '%s' "$query" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-')"
idempotency_key="hans:${key_slug}"

psql "$DATABASE_URL" <<SQL
INSERT INTO jobs (
  job_type, lane, agent, status, priority, input_ref, idempotency_key
)
VALUES (
  'competitor_discovery',
  'competitor',
  'hans',
  'queued',
  $priority,
  '$query',
  '$idempotency_key'
);
SQL
