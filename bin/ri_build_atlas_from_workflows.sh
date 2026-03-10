#!/usr/bin/env bash
set -euo pipefail
DB="postgres://localhost/research_intelligence"
OUT="$HOME/ri_db/outputs/atlas_input.json"

psql "$DB" -Atc "
select jsonb_pretty(jsonb_build_object(
  'created_at', now(),
  'wellnest_workflows', coalesce(jsonb_agg(jsonb_build_object(
    'workflow_id', id,
    'title', title,
    'description', description,
    'trigger', trigger,
    'steps', steps,
    'failure_points', failure_points
  ) order by id desc), '[]'::jsonb)
))
from (select * from wellnest_workflows order by id desc limit 200) w;
" > "$OUT"

test -s "$OUT"
echo "OK: wrote $OUT"
