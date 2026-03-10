#!/usr/bin/env bash
set -euo pipefail
DB="postgres://localhost/research_intelligence"

psql "$DB" -v ON_ERROR_STOP=1 -c "
with src as (
  select
    ci.creator_profile_id::text as source_ref,
    ci.payload->>'run_id' as run_id,
    ci.payload as payload
  from creator_intel ci
  where ci.payload ? 'wellnest_workflows'
),
wf as (
  select
    source_ref,
    run_id,
    w as w
  from src,
  lateral jsonb_array_elements(coalesce(src.payload->'wellnest_workflows','[]'::jsonb)) w
  where coalesce(w->>'title','') <> ''
),
ins as (
  insert into wellnest_workflows (source, source_ref, run_id, title, description, trigger, steps, failure_points)
  select
    'scout',
    wf.source_ref,
    wf.run_id,
    wf.w->>'title',
    wf.w->>'description',
    wf.w->>'trigger',
    coalesce(wf.w->'steps','[]'::jsonb),
    coalesce(wf.w->'failure_points','[]'::jsonb)
  from wf
  on conflict (source, source_ref, title) do update
    set description = coalesce(excluded.description, wellnest_workflows.description),
        trigger = coalesce(excluded.trigger, wellnest_workflows.trigger),
        steps = case when jsonb_array_length(excluded.steps) > 0 then excluded.steps else wellnest_workflows.steps end,
        failure_points = case when jsonb_array_length(excluded.failure_points) > 0 then excluded.failure_points else wellnest_workflows.failure_points end
  returning id, run_id
)
select count(*) as workflows_upserted from ins;
"
