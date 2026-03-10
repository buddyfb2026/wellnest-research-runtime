#!/bin/zsh
set -euo pipefail

tmp_output="$(mktemp)"
~/ri_db/bin/ri_run_scour.sh | tee "$tmp_output"

artifact_path="$(python3 - "$tmp_output" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])

for raw in path.read_text().splitlines():
    line = raw.strip()
    if not line.startswith("{"):
        continue
    try:
        obj = json.loads(line)
    except Exception:
        continue
    if obj.get("ok") is True and obj.get("file_path"):
        print(obj["file_path"])
        break
PY
)"

rm -f "$tmp_output"

if [ -n "$artifact_path" ] && [ -f "$artifact_path" ]; then
  DATABASE_URL="postgresql:///research_intelligence" ~/ri_db/bin/ri_update_creator_graph.py "$artifact_path"
  echo "creator_graph_updated: $artifact_path"
else
  echo "creator_graph_skipped: no artifact path found" >&2
fi
