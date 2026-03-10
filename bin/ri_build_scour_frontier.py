#!/usr/bin/env python3
import json
import os
import subprocess
from pathlib import Path

DB_URL = os.environ.get("DATABASE_URL", "postgresql:///research_intelligence")
PLAYBOOK_PATH = Path.home() / "ri_db" / "seeds" / "scour_discovery_playbook.json"
OUT_PATH = Path.home() / "ri_db" / "work" / "scour_frontier.json"

def fetch_rows(sql):
    cmd = [
        "/opt/homebrew/opt/postgresql@16/bin/psql",
        DB_URL,
        "-At",
        "-F",
        "\t",
        "-c",
        sql,
    ]
    out = subprocess.check_output(cmd, text=True)
    rows = []
    for line in out.splitlines():
        if not line.strip():
            continue
        rows.append(line.split("\t"))
    return rows

playbook = json.loads(PLAYBOOK_PATH.read_text())

seed_accounts = []
for cluster in playbook.get("clusters", []):
    for acct in cluster.get("seed_accounts", []):
        seed_accounts.append({
            "type": "seed_account",
            "cluster": cluster.get("name"),
            "platforms": playbook.get("platforms", []),
            "value": acct
        })

queries = []
dq = playbook.get("discovery_queries", {})
for source_name, values in dq.items():
    for v in values:
        queries.append({
            "type": "discovery_query",
            "source": source_name,
            "value": v
        })

frontier_rows = fetch_rows("""
select creator_handle, platform, coalesce(cluster,'unknown'), coalesce(frontier_score,0)::text
from v_creator_graph_frontier
limit 25;
""")

graph_candidates = [
    {
        "type": "graph_candidate",
        "creator_handle": row[0],
        "platform": row[1],
        "cluster": row[2],
        "frontier_score": float(row[3]),
    }
    for row in frontier_rows
]

payload = {
    "playbook_version": playbook.get("version"),
    "domain": playbook.get("domain"),
    "objective": playbook.get("objective"),
    "seed_accounts": seed_accounts[:50],
    "discovery_queries": queries[:80],
    "graph_candidates": graph_candidates,
}

OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
OUT_PATH.write_text(json.dumps(payload, indent=2))
print(str(OUT_PATH))
