#!/usr/bin/env bash
set -euo pipefail

source "$HOME/ri_db/bin/ri_lib.sh"

agent="${1:?agent required}"

session_id="$(ri_session_id "$agent")"
session_dir="$(ri_session_dir "$agent" "$session_id")"

mkdir -p "$session_dir"

touch \
  "$session_dir/input.json" \
  "$session_dir/prompt.txt" \
  "$session_dir/raw_output.txt" \
  "$session_dir/normalized.json" \
  "$session_dir/validation.json" \
  "$session_dir/status.json" \
  "$session_dir/run.log"

printf '%s\n' "$session_id"
