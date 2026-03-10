#!/usr/bin/env bash
set -euo pipefail

AGENT="${1:-}"
shift || true
PROMPT="${*:-}"

[ -n "$AGENT" ] || { echo "usage: oc_invoke_retry_prompt.sh <agent> <prompt>"; exit 2; }
[ -n "$PROMPT" ] || { echo "missing prompt"; exit 2; }

MAX_TRIES="${MAX_TRIES:-4}"
SLEEP_BASE="${SLEEP_BASE:-2}"

i=1
while [ "$i" -le "$MAX_TRIES" ]; do
  if out="$("$HOME/ri_db/bin/oc_invoke_prompt.sh" "$AGENT" "$PROMPT" 2>&1)"; then
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
