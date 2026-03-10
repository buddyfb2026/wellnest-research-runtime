#!/bin/zsh
set -euo pipefail

ROOT="${RI_DB_ROOT:-$HOME/ri_db}"
JOB_FILE="${1:?}"
LOG_FILE="$ROOT/log/workers/franz.jsonl"
SESSION_ID="franz_$(date +%Y%m%d_%H%M%S)_$RANDOM"
DB_NAME="${RI_DB_NAME:-research_intelligence}"
BIN_DIR="$ROOT/bin"
OUT_DIR="$ROOT/outputs"
INBOX_DIR="$ROOT/inbox"

export OLLAMA_API_KEY="${OLLAMA_API_KEY:-ollama-local}"
export OLLAMA_KEEP_ALIVE="${OLLAMA_KEEP_ALIVE:-30m}"

mkdir -p "$OUT_DIR" "$INBOX_DIR/franz"

"$ROOT/bin/ri_log_jsonl.sh" "$LOG_FILE" "worker_started" "worker" "franz" "session_id" "$SESSION_ID" "job_file" "$JOB_FILE"

"$ROOT/bin/ri_validate_json.mjs" "$ROOT/schemas/franz-job.schema.json" "$JOB_FILE"

ts="$(date +%Y-%m-%d_%H%M%S)"
franz_in="$OUT_DIR/franz_input_$ts.json"
franz_out="$INBOX_DIR/franz/${ts}.franz.json"

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

test -s "$franz_in"
"$ROOT/bin/ri_log_jsonl.sh" "$LOG_FILE" "franz_stage_finished" "worker" "franz" "session_id" "$SESSION_ID" "stage" "build_input" "input_file" "$franz_in"

rm -f "$franz_out"

if python3 - "$BIN_DIR" "$franz_in" "$franz_out" <<'PY'
import subprocess
import sys

bin_dir, franz_in, franz_out = sys.argv[1], sys.argv[2], sys.argv[3]

with open(franz_out, "w") as out:
    result = subprocess.run(
        [f"{bin_dir}/with_lock.sh", "ri_franz", f"{bin_dir}/oc_invoke_retry.sh", "franz", franz_in],
        stdout=out,
        stderr=subprocess.DEVNULL,
        timeout=45,
        check=False,
        text=True,
    )

if result.returncode != 0:
    raise SystemExit(result.returncode)
PY
then
  test -s "$franz_out"
  python3 - "$franz_out" <<'PY'
import json, sys
p = sys.argv[1]
with open(p, "r") as f:
    json.load(f)
PY
  "$ROOT/bin/ri_log_jsonl.sh" "$LOG_FILE" "franz_stage_finished" "worker" "franz" "session_id" "$SESSION_ID" "stage" "invoke_agent" "output_file" "$franz_out"
else
  rm -f "$franz_out" 2>/dev/null || true
  "$ROOT/bin/ri_log_jsonl.sh" "$LOG_FILE" "worker_failed" "worker" "franz" "session_id" "$SESSION_ID" "stage" "invoke_agent_timeout_or_error" "input_file" "$franz_in"
  exit 1
fi

"$ROOT/bin/ri_log_jsonl.sh" "$LOG_FILE" "worker_finished" "worker" "franz" "session_id" "$SESSION_ID" "job_file" "$JOB_FILE"
