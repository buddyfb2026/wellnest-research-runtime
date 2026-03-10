#!/usr/bin/env bash
set -euo pipefail

DB="postgres://localhost/research_intelligence"

psql "$DB" -v ON_ERROR_STOP=1 -c "
with src as (
  select id, payload
  from creator_discovery_payloads
  order by id desc
  limit 50
),
items_raw as (
  select
    (x->>'platform')::text as platform,
    (x->>'handle')::text as handle,
    (x->>'profile_url')::text as profile_url,
    nullif(x->>'followers','')::bigint as followers
  from src,
  lateral jsonb_array_elements(coalesce(payload->'items','[]'::jsonb)) x
  where coalesce(x->>'platform','') <> ''
    and coalesce(x->>'handle','') <> ''
    and coalesce(x->>'profile_url','') <> ''
),
items as (
  select distinct on (platform, handle)
    platform,
    handle,
    profile_url,
    followers
  from items_raw
  order by platform, handle, followers desc nulls last
),
ins as (
  insert into creator_profiles (platform, handle, profile_url, followers, discovered_at)
  select platform, handle, profile_url, followers, now()
  from items
  on conflict (platform, handle) do update
    set profile_url = excluded.profile_url,
        followers = coalesce(excluded.followers, creator_profiles.followers)
  returning 1
)
select count(*) as creators_upserted from ins;
"

psql "$DB" -v ON_ERROR_STOP=1 -c "
with src as (
  select id, payload
  from competitor_discovery_payloads
  order by id desc
  limit 50
),
items_raw as (
  select
    (x->>'name')::text as name,
    nullif((x->>'website')::text,'') as website,
    (x->>'category')::text as category
  from src,
  lateral jsonb_array_elements(coalesce(payload->'items','[]'::jsonb)) x
  where coalesce(x->>'name','') <> ''
),
items as (
  select distinct on (name)
    name,
    website,
    category
  from items_raw
  order by name, website nulls last
),
ins as (
  insert into competitors (name, website, category, discovered_at)
  select name, website, category, now()
  from items
  on conflict (name) do update
    set website = coalesce(excluded.website, competitors.website),
        category = coalesce(excluded.category, competitors.category)
  returning 1
)
select count(*) as competitors_upserted from ins;
"
