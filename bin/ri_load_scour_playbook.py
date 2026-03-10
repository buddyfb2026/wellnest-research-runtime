#!/usr/bin/env python3
import json
from pathlib import Path

playbook_path = Path.home() / "ri_db" / "seeds" / "scour_discovery_playbook.json"
data = json.loads(playbook_path.read_text())

print(json.dumps(data))
