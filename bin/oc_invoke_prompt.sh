#!/usr/bin/env bash
set -euo pipefail

AGENT="${1:-}"
shift || true
PROMPT="${*:-}"

[ -n "$AGENT" ] || { echo "usage: oc_invoke_prompt.sh <agent> <prompt>"; exit 2; }
[ -n "$PROMPT" ] || { echo "missing prompt"; exit 2; }

export OLLAMA_API_KEY="${OLLAMA_API_KEY:-ollama-local}"
export OLLAMA_KEEP_ALIVE="${OLLAMA_KEEP_ALIVE:-30m}"

openclaw agent --local --agent "$AGENT" --session-id "ri-${AGENT}-$(date +%s)" -m "$PROMPT"
