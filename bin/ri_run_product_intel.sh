#!/usr/bin/env bash
set -euo pipefail

ROOT="$HOME/ri_db"
LOG="$ROOT/logs/product_intel_runner.log"

echo "RUN $(date)" >> "$LOG"

OC_GATEWAY_HTTP="http://127.0.0.1:18791"
OC_ORIGIN="http://127.0.0.1:18789"

ATLAS_INPUT=$(cat "$ROOT/outputs/atlas_input.json")

"$ROOT/bin/oc_invoke_agent.sh" atlas \
"Return JSON only. Use the following research intelligence to identify product opportunities.

$ATLAS_INPUT" \
>> "$LOG" 2>&1

KAREN_INPUT=$(cat "$ROOT/outputs/karen_input.json")

"$ROOT/bin/oc_invoke_agent.sh" karen \
"Return JSON only. Convert these opportunities into feature specs.

$KAREN_INPUT" \
>> "$LOG" 2>&1

echo "DONE $(date)" >> "$LOG"
