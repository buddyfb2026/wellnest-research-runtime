#!/usr/bin/env bash
set -euo pipefail

AGENT="${1:-}"
shift || true
ARG="${1:-}"

[ -n "$AGENT" ] || { echo "usage: oc_invoke_retry.sh <agent> <prompt_or_json_file>"; exit 2; }
[ -n "$ARG" ] || { echo "missing prompt_or_json_file"; exit 2; }

MAX_TRIES="${MAX_TRIES:-4}"
SLEEP_BASE="${SLEEP_BASE:-2}"

run_once() {
  if [ -f "$ARG" ]; then
    "$HOME/ri_db/bin/oc_ws_invoke_file.mjs" "$AGENT" "$ARG"
  else
    "$HOME/ri_db/bin/oc_invoke_agent.sh" "$AGENT" "$ARG"
  fi
}

i=1
while [ "$i" -le "$MAX_TRIES" ]; do
  if out="$(run_once 2>&1)"; then
    printf "%s\n" "$out"
    exit 0
  fi

  printf "%s\n" "$out" >&2

  if [ "$i" -eq "$MAX_TRIES" ]; then
    exit 1
  fi

  jitter=$((RANDOM % 3))
  sleep_for=$((SLEEP_BASE * i + jitter))
  sleep "$sleep_for"
  i=$((i + 1))
done

exit 1
