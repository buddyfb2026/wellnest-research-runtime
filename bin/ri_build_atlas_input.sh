#!/usr/bin/env bash
set -euo pipefail

DB="${DB:-research_intelligence}"
OUTDIR="${OUTDIR:-$HOME/ri_db/outputs}"
mkdir -p "$OUTDIR"

N_CREATORS="${N_CREATORS:-20}"
N_COMP="${N_COMP:-20}"

PSQL_BIN="${PSQL_BIN:-/opt/homebrew/opt/postgresql@16/bin/psql}"

creators_json="$("$PSQL_BIN" "$DB" -t -A -v ON_ERROR_STOP=1 -c "SELECT COALESCE(jsonb_agg(payload ORDER BY created_at DESC),'[]'::jsonb) FROM (SELECT payload, created_at FROM creator_intel ORDER BY created_at DESC LIMIT $N_CREATORS) t;")"
competitors_json="$("$PSQL_BIN" "$DB" -t -A -v ON_ERROR_STOP=1 -c "SELECT COALESCE(jsonb_agg(payload ORDER BY created_at DESC),'[]'::jsonb) FROM (SELECT payload, created_at FROM competitor_intel ORDER BY created_at DESC LIMIT $N_COMP) t;")"

python3 - <<PY > "$OUTDIR/atlas_input.json"
import json, datetime
creators = json.loads('''${creators_json}'''.strip() or "[]")
competitors = json.loads('''${competitors_json}'''.strip() or "[]")
out = {
  "created_at": datetime.datetime.utcnow().isoformat() + "Z",
  "creator_intel": creators,
  "competitor_intel": competitors
}
print(json.dumps(out, indent=2))
PY

echo "OK: wrote $OUTDIR/atlas_input.json"
