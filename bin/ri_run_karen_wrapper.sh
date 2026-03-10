#!/bin/zsh
set -euo pipefail

ROOT="${RI_DB_ROOT:-$HOME/ri_db}"
JOB_FILE="${1:?}"
LOG_FILE="$ROOT/log/workers/karen.jsonl"
SESSION_ID="karen_$(date +%Y%m%d_%H%M%S)_$RANDOM"

export OLLAMA_API_KEY="${OLLAMA_API_KEY:-ollama-local}"
export OLLAMA_KEEP_ALIVE="${OLLAMA_KEEP_ALIVE:-30m}"

"$ROOT/bin/ri_log_jsonl.sh" "$LOG_FILE" "worker_started" "worker" "karen" "session_id" "$SESSION_ID" "job_file" "$JOB_FILE"

"$ROOT/bin/ri_validate_json.mjs" "$ROOT/schemas/karen-job.schema.json" "$JOB_FILE"

"$ROOT/bin/ri_build_karen_from_atlas.sh"

"$ROOT/bin/ri_log_jsonl.sh" "$LOG_FILE" "worker_finished" "worker" "karen" "session_id" "$SESSION_ID" "job_file" "$JOB_FILE"
