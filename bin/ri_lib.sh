#!/usr/bin/env bash
set -euo pipefail

RI_DB_ROOT="${RI_DB_ROOT:-$HOME/ri_db}"
RI_LOG_DIR="$RI_DB_ROOT/logs"

ri_now_utc() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

ri_ts_compact() {
  date -u +"%Y%m%d_%H%M%S"
}

ri_shortid() {
  python3 - <<'PY'
import secrets
print(secrets.token_hex(3))
PY
}

ri_session_id() {
  local agent="$1"
  echo "${agent}_$(ri_ts_compact)_$(ri_shortid)"
}

ri_session_dir() {
  local agent="$1"
  local session_id="$2"
  echo "$RI_DB_ROOT/work/$agent/$session_id"
}

ri_append_jsonl() {
  local log_file="$1"
  local json_line="$2"
  mkdir -p "$(dirname "$log_file")"
  printf '%s\n' "$json_line" >> "$log_file"
}
