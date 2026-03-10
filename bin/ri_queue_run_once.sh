#!/bin/zsh
set -euo pipefail

ROOT="${RI_DB_ROOT:-$HOME/ri_db}"
QUEUE_ROOT="${RI_QUEUE_ROOT:-$ROOT/queue}"
LOG_ROOT="${RI_LOG_ROOT:-$ROOT/log}"
PENDING="$QUEUE_ROOT/pending"
RUNNING="$QUEUE_ROOT/running"
DONE="$QUEUE_ROOT/done"
FAILED="$QUEUE_ROOT/failed"
QUEUE_LOG="$LOG_ROOT/queue/queue.jsonl"

mkdir -p "$PENDING" "$RUNNING" "$DONE" "$FAILED" "$(dirname "$QUEUE_LOG")"

JOB_FILE="$(ls "$PENDING"/*.json 2>/dev/null | head -n 1 || true)"

if [ -z "$JOB_FILE" ]; then
  exit 0
fi

BASE="$(basename "$JOB_FILE")"
RUN_FILE="$RUNNING/$BASE"

mv "$JOB_FILE" "$RUN_FILE"

TYPE="$(echo "$BASE" | sed -E 's/^[^.]+\.([^.]+)\.json$/\1/')"
JOB_ID="$(echo "$BASE" | sed -E 's/^([^.]+)\..*$/\1/')"

"$ROOT/bin/ri_log_jsonl.sh" "$QUEUE_LOG" "job_started" "job_id" "$JOB_ID" "type" "$TYPE" "file" "$RUN_FILE"

case "$TYPE" in
  karen)
    WORKER_CMD=("$ROOT/bin/ri_run_karen_wrapper.sh" "$RUN_FILE")
    ;;
  atlas)
    WORKER_CMD=("$ROOT/bin/ri_run_atlas_wrapper.sh" "$RUN_FILE")
    ;;
  scout)
    WORKER_CMD=("$ROOT/bin/ri_run_scout_wrapper.sh" "$RUN_FILE")
    ;;
  franz)
    WORKER_CMD=("$ROOT/bin/ri_run_franz_wrapper.sh" "$RUN_FILE")
    ;;
  *)
    "$ROOT/bin/ri_log_jsonl.sh" "$QUEUE_LOG" "job_failed" "job_id" "$JOB_ID" "type" "$TYPE" "reason" "unknown_job_type"
    mv "$RUN_FILE" "$FAILED/$BASE"
    exit 1
    ;;
esac

if "${WORKER_CMD[@]}"; then
  mv "$RUN_FILE" "$DONE/$BASE"
  "$ROOT/bin/ri_log_jsonl.sh" "$QUEUE_LOG" "job_finished" "job_id" "$JOB_ID" "type" "$TYPE" "file" "$DONE/$BASE"
else
  mv "$RUN_FILE" "$FAILED/$BASE"
  "$ROOT/bin/ri_log_jsonl.sh" "$QUEUE_LOG" "job_failed" "job_id" "$JOB_ID" "type" "$TYPE" "file" "$FAILED/$BASE"
  exit 1
fi
