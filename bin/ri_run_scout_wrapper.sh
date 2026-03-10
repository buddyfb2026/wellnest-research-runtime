#!/bin/zsh
set -euo pipefail

ROOT="${RI_DB_ROOT:-$HOME/ri_db}"
JOB_FILE="${1:?}"
LOG_FILE="$ROOT/log/workers/scout.jsonl"
SESSION_ID="scout_$(date +%Y%m%d_%H%M%S)_$RANDOM"

export OLLAMA_API_KEY="${OLLAMA_API_KEY:-ollama-local}"
export OLLAMA_KEEP_ALIVE="${OLLAMA_KEEP_ALIVE:-30m}"

"$ROOT/bin/ri_log_jsonl.sh" "$LOG_FILE" "worker_started" "worker" "scout" "session_id" "$SESSION_ID" "job_file" "$JOB_FILE"

"$ROOT/bin/ri_validate_json.mjs" "$ROOT/schemas/scout-job.schema.json" "$JOB_FILE"

"$ROOT/bin/ri_adapt_discovery_payloads.sh"
"$ROOT/bin/ri_log_jsonl.sh" "$LOG_FILE" "scout_stage_finished" "worker" "scout" "session_id" "$SESSION_ID" "stage" "adapt_discovery_payloads"

python3 "$ROOT/bin/ri_load_creator_signals.py"
"$ROOT/bin/ri_log_jsonl.sh" "$LOG_FILE" "scout_stage_finished" "worker" "scout" "session_id" "$SESSION_ID" "stage" "load_creator_signals"

"$ROOT/bin/ri_extract_wellnest_workflows.sh"
"$ROOT/bin/ri_log_jsonl.sh" "$LOG_FILE" "scout_stage_finished" "worker" "scout" "session_id" "$SESSION_ID" "stage" "extract_wellnest_workflows"

"$ROOT/bin/ri_log_jsonl.sh" "$LOG_FILE" "worker_finished" "worker" "scout" "session_id" "$SESSION_ID" "job_file" "$JOB_FILE"
