#!/usr/bin/env bash
set -euo pipefail

source "$HOME/ri_db/bin/ri_lib.sh"

level="${1:?level required}"
agent="${2:-}"
lane="${3:-}"
job_id="${4:-}"
session_id="${5:-}"
event="${6:?event required}"
status="${7:-}"
message="${8:-}"

if [ $# -ge 9 ]; then
  metadata="$9"
else
  metadata='{}'
fi

timestamp="$(ri_now_utc)"
tmp_metadata="$(mktemp)"
printf '%s' "$metadata" > "$tmp_metadata"

json_line="$(
python3 - "$timestamp" "$level" "$agent" "$lane" "$job_id" "$session_id" "$event" "$status" "$message" "$tmp_metadata" <<'PY'
import json
import sys
from pathlib import Path

timestamp, level, agent, lane, job_id, session_id, event, status, message, metadata_path = sys.argv[1:]
metadata = Path(metadata_path).read_text()

try:
    md = json.loads(metadata)
except Exception:
    md = {"raw": metadata}

print(json.dumps({
    "timestamp": timestamp,
    "level": level,
    "agent": agent,
    "lane": lane,
    "job_id": job_id,
    "session_id": session_id,
    "event": event,
    "status": status,
    "message": message,
    "metadata": md
}, separators=(",", ":")))
PY
)"

rm -f "$tmp_metadata"

ri_append_jsonl "$HOME/ri_db/logs/pipeline.jsonl" "$json_line"

if [ -n "$agent" ]; then
  ri_append_jsonl "$HOME/ri_db/logs/${agent}.jsonl" "$json_line"
fi

printf '%s\n' "$json_line"
