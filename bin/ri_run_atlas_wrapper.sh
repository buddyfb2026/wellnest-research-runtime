#!/bin/zsh
set -euo pipefail

ROOT="${RI_DB_ROOT:-$HOME/ri_db}"
JOB_FILE="${1:?}"
LOG_FILE="$ROOT/log/workers/atlas.jsonl"
SESSION_ID="atlas_$(date +%Y%m%d_%H%M%S)_$RANDOM"
INBOX_DIR="$ROOT/inbox/atlas"

export OLLAMA_API_KEY="${OLLAMA_API_KEY:-ollama-local}"
export OLLAMA_KEEP_ALIVE="${OLLAMA_KEEP_ALIVE:-30m}"

mkdir -p "$INBOX_DIR"

"$ROOT/bin/ri_log_jsonl.sh" "$LOG_FILE" "worker_started" "worker" "atlas" "session_id" "$SESSION_ID" "job_file" "$JOB_FILE"

"$ROOT/bin/ri_validate_json.mjs" "$ROOT/schemas/atlas-job.schema.json" "$JOB_FILE"

"$ROOT/bin/ri_build_atlas_from_workflows.sh"

LATEST_PROCESSED="$(ls -1t "$ROOT"/processed/*.atlas.*.json 2>/dev/null | head -n 1 || true)"

if [ -n "$LATEST_PROCESSED" ]; then
  PUBLISHED_FILE="$INBOX_DIR/$(date +%Y-%m-%d_%H%M%S).atlas.json"
  cp "$LATEST_PROCESSED" "$PUBLISHED_FILE"
  "$ROOT/bin/ri_log_jsonl.sh" "$LOG_FILE" "atlas_published" "worker" "atlas" "session_id" "$SESSION_ID" "published_file" "$PUBLISHED_FILE"
else
  "$ROOT/bin/ri_log_jsonl.sh" "$LOG_FILE" "atlas_publish_skipped" "worker" "atlas" "session_id" "$SESSION_ID" "reason" "no_processed_atlas_artifact_found"
  exit 1
fi

"$ROOT/bin/ri_log_jsonl.sh" "$LOG_FILE" "worker_finished" "worker" "atlas" "session_id" "$SESSION_ID" "job_file" "$JOB_FILE"
