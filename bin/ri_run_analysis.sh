#!/usr/bin/env bash
set -euo pipefail

DB_NAME="${RI_DB_NAME:-research_intelligence}"
BIN_DIR="$HOME/ri_db/bin"
OUT_DIR="$HOME/ri_db/outputs"
INBOX_DIR="$HOME/ri_db/inbox"

mkdir -p "$OUT_DIR" "$INBOX_DIR/scout" "$INBOX_DIR/franz"

ts="$(date +%Y-%m-%d_%H%M%S)"
scout_in="$OUT_DIR/scout_input_$ts.json"
franz_in="$OUT_DIR/franz_input_$ts.json"

psql "postgres://localhost/$DB_NAME" -v ON_ERROR_STOP=1 -Atc "
WITH c AS (
  SELECT cp.id, cp.platform, cp.handle, cp.profile_url, cp.followers
  FROM creator_profiles cp
  LEFT JOIN creator_intel ci ON ci.creator_profile_id = cp.id
  WHERE ci.id IS NULL
  ORDER BY cp.discovered_at DESC
  LIMIT 25
)
SELECT COALESCE(jsonb_pretty(jsonb_build_object(
  'run_id', '$ts',
  'max_items', 25,
  'creators', COALESCE(jsonb_agg(jsonb_build_object(
    'creator_profile_id', id,
    'platform', platform,
    'handle', handle,
    'profile_url', profile_url,
    'followers', followers
  )), '[]'::jsonb)
)), '{\"run_id\":\"$ts\",\"max_items\":0,\"creators\":[]}') AS payload
FROM c;
" > "$scout_in"

psql "postgres://localhost/$DB_NAME" -v ON_ERROR_STOP=1 -Atc "
WITH c AS (
  SELECT c.id, c.name, c.website, c.category
  FROM competitors c
  LEFT JOIN competitor_intel ci ON ci.competitor_id = c.id
  WHERE ci.id IS NULL
  ORDER BY c.discovered_at DESC
  LIMIT 25
)
SELECT COALESCE(jsonb_pretty(jsonb_build_object(
  'run_id', '$ts',
  'max_items', 25,
  'competitors', COALESCE(jsonb_agg(jsonb_build_object(
    'competitor_id', id,
    'name', name,
    'website', website,
    'category', category
  )), '[]'::jsonb)
)), '{\"run_id\":\"$ts\",\"max_items\":0,\"competitors\":[]}') AS payload
FROM c;
" > "$franz_in"

test -s "$scout_in"
test -s "$franz_in"

scout_out="$INBOX_DIR/scout/${ts}.scout.json"
franz_out="$INBOX_DIR/franz/${ts}.franz.json"

"$BIN_DIR/with_lock.sh" "ri_scout" "$BIN_DIR/oc_invoke_retry.sh" scout "$scout_in" > "$scout_out" || true
"$BIN_DIR/with_lock.sh" "ri_franz" "$BIN_DIR/oc_invoke_retry.sh" franz "$franz_in" > "$franz_out" || true

test -s "$scout_out" || rm -f "$scout_out" 2>/dev/null || true
test -s "$franz_out" || rm -f "$franz_out" 2>/dev/null || true
