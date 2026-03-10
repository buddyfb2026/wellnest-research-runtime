#!/usr/bin/env bash
set -euo pipefail

DB="${DB:-research_intelligence}"
ROOT="${ROOT:-$HOME/ri_db}"
LOGDIR="$ROOT/logs"
mkdir -p "$LOGDIR" "$ROOT/processed" "$ROOT/errors"

ts="$(date '+%Y-%m-%d_%H%M%S')"
log="$LOGDIR/ri_process_inbox_$ts.log"

echo "START $ts" | tee -a "$log"

escape_sql_literal () {
  # doubles single quotes for SQL string literal safety
  sed "s/'/''/g"
}

ingest_payload_table () {
  local table="$1"
  local file="$2"
  local topic="${3:-}"

  local payload_escaped topic_escaped
  payload_escaped="$(cat "$file" | escape_sql_literal)"
  topic_escaped="$(printf "%s" "$topic" | escape_sql_literal)"

  if [[ "$table" == "creator_discovery_payloads" || "$table" == "competitor_discovery_payloads" ]]; then
    psql "$DB" -v ON_ERROR_STOP=1 -c \
      "INSERT INTO $table (topic, payload) VALUES ('$topic_escaped', '$payload_escaped'::jsonb);" >>"$log" 2>&1
  elif [[ "$table" == "creator_intel" || "$table" == "competitor_intel" ]]; then
    psql "$DB" -v ON_ERROR_STOP=1 -c \
      "INSERT INTO $table (payload) VALUES ('$payload_escaped'::jsonb);" >>"$log" 2>&1
  elif [[ "$table" == "feature_specs" ]]; then
    psql "$DB" -v ON_ERROR_STOP=1 -c \
      "INSERT INTO feature_specs (opportunity_id, spec)
       SELECT
         (
           SELECT po.id
           FROM product_opportunities po
           WHERE po.title = COALESCE(j->>'opportunity_title', j->>'title', '')
           ORDER BY po.created_at DESC
           LIMIT 1
         ),
         j::jsonb
       FROM jsonb_array_elements(COALESCE(('$payload_escaped'::jsonb)->'feature_specs', '[]'::jsonb)) AS j;" >>"$log" 2>&1
  else
    echo "Unknown payload table: $table" >>"$log"
    return 1
  fi
}

ingest_product_opportunities () {
  local file="$1"
  local payload_escaped
  payload_escaped="$(cat "$file" | escape_sql_literal)"

  psql "$DB" -v ON_ERROR_STOP=1 -c \
    "INSERT INTO product_opportunities (title, description, signal_strength, evidence_sources, priority)
     SELECT
       COALESCE(j->>'title',''),
       COALESCE(j->>'description',''),
       NULLIF((j->>'signal_strength'),'')::float,
       COALESCE((j->'evidence_sources')::jsonb,'[]'::jsonb),
       COALESCE(j->>'priority','')
     FROM jsonb_array_elements(('$payload_escaped'::jsonb)->'opportunities') AS j;" >>"$log" 2>&1
}

process_dir () {
  local sub="$1"
  local kind="$2"   # payload_table | opportunities
  local table="${3:-}"
  local dir="$ROOT/inbox/$sub"
  [ -d "$dir" ] || return 0

  shopt -s nullglob
  for f in "$dir"/*.json; do
    echo "PROCESS $f" | tee -a "$log"
    if [[ "$kind" == "opportunities" ]]; then
      if ingest_product_opportunities "$f"; then
        mv "$f" "$ROOT/processed/$(basename "$f" .json).$sub.$ts.json"
      else
        mv "$f" "$ROOT/errors/$(basename "$f" .json).$sub.$ts.json"
      fi
    else
      if ingest_payload_table "$table" "$f" "$sub"; then
        mv "$f" "$ROOT/processed/$(basename "$f" .json).$sub.$ts.json"
      else
        mv "$f" "$ROOT/errors/$(basename "$f" .json).$sub.$ts.json"
      fi
    fi
  done
}

process_dir "scour" "payload_table" "creator_discovery_payloads"
process_dir "scout" "payload_table" "creator_intel"
process_dir "hans"  "payload_table" "competitor_discovery_payloads"
process_dir "franz" "payload_table" "competitor_intel"
process_dir "atlas" "opportunities"
process_dir "karen" "payload_table" "feature_specs"

echo "DONE $ts" | tee -a "$log"
