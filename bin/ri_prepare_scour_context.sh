#!/bin/zsh
set -euo pipefail

export DATABASE_URL="postgresql:///research_intelligence"
~/ri_db/bin/ri_build_scour_frontier.py >/dev/null

python3 - <<'PY'
import json
from pathlib import Path

playbook = Path.home() / "ri_db" / "seeds" / "scour_discovery_playbook.json"
frontier = Path.home() / "ri_db" / "work" / "scour_frontier.json"
out = Path.home() / "ri_db" / "work" / "scour_runtime_context.json"

payload = {
    "playbook": json.loads(playbook.read_text()),
    "frontier": json.loads(frontier.read_text())
}
out.write_text(json.dumps(payload, indent=2))
print(out)
PY
