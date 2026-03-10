#!/usr/bin/env bash
set -euo pipefail

AGENT="${1:-}"
shift || true
INPUT="${1:-}"

[ -n "$AGENT" ] || { echo "usage: oc_invoke_agent.sh <agent> <input_json_path>"; exit 2; }
[ -n "$INPUT" ] || { echo "missing input path"; exit 2; }

export OLLAMA_API_KEY="${OLLAMA_API_KEY:-ollama-local}"
export OLLAMA_KEEP_ALIVE="${OLLAMA_KEEP_ALIVE:-30m}"

exec "$HOME/ri_db/bin/oc_ws_invoke_file.mjs" "$AGENT" "$INPUT"
