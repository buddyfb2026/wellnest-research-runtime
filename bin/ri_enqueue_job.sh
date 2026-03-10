#!/bin/zsh
set -euo pipefail

QUEUE_ROOT="${RI_QUEUE_ROOT:-$HOME/ri_db/queue}"
PENDING="$QUEUE_ROOT/pending"
JOB_TYPE="${1:?}"
PAYLOAD_FILE="${2:?}"

mkdir -p "$PENDING"

JOB_ID="$(date +%Y%m%d_%H%M%S)_$RANDOM"
JOB_FILE="$PENDING/${JOB_ID}.${JOB_TYPE}.json"

cp "$PAYLOAD_FILE" "$JOB_FILE"

echo "$JOB_FILE"
