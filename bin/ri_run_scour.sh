#!/usr/bin/env bash
set -euo pipefail

export DATABASE_URL="${DATABASE_URL:-postgresql:///research_intelligence}"
export PATH="/opt/homebrew/opt/postgresql@16/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

PLAYBOOK_PATH="$HOME/ri_db/seeds/scour_discovery_playbook.json"

if [ -f "$PLAYBOOK_PATH" ]; then
  export SCOUR_DISCOVERY_PLAYBOOK_PATH="$PLAYBOOK_PATH"
  export SCOUR_DISCOVERY_PLAYBOOK_JSON="$(python3 "$HOME/ri_db/bin/ri_load_scour_playbook.py")"
else
  echo "WARN: missing Scour playbook at $PLAYBOOK_PATH" >&2
fi

"$HOME/ri_db/bin/ri_prepare_scour_context.sh" >/dev/null

tmp_output="$(mktemp)"
"$HOME/ri_db/bin/ri_run_scour_core.sh" | tee "$tmp_output"

artifact_id="$(tail -n 1 "$tmp_output" | tr -d '\r')"

if [ -n "${artifact_id:-}" ]; then
  artifact_path="$HOME/ri_db/out/scour/${artifact_id}.json"

  if [ -f "$artifact_path" ]; then
    python3 "$HOME/ri_db/bin/ri_build_scour_artifact.py" "$artifact_path" "$artifact_id" "$artifact_id" "$artifact_path" >/dev/null
    python3 "$HOME/ri_db/bin/ri_sync_artifact_metadata.py" "$artifact_path" >/dev/null
    python3 "$HOME/ri_db/bin/ri_update_creator_graph.py" "$artifact_path" >/dev/null
    echo "scour_frontier_artifact_updated: $artifact_path" >&2
  else
    echo "WARN: expected artifact path not found: $artifact_path" >&2
  fi
fi

rm -f "$tmp_output"
printf '%s\n' "$artifact_id"
