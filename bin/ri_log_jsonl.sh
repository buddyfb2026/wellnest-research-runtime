#!/bin/zsh
set -euo pipefail

LOG_FILE="${1:?}"
EVENT="${2:?}"
SHIFTED=("${@:3}")

mkdir -p "$(dirname "$LOG_FILE")"

TS="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

JSON="{\"ts\":\"$TS\",\"event\":\"$EVENT\""

i=1
while [ $i -le ${#SHIFTED[@]} ]; do
  KEY="${SHIFTED[$i]}"
  VAL="${SHIFTED[$((i+1))]}"
  JSON="$JSON,\"$KEY\":\"$VAL\""
  i=$((i+2))
done

JSON="$JSON}"
printf '%s\n' "$JSON" >> "$LOG_FILE"
