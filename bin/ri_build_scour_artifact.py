#!/usr/bin/env python3
import json
import sys
import hashlib
from pathlib import Path
from datetime import datetime, timezone, timedelta

def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0)

def utc_now_str():
    return utc_now().isoformat().replace("+00:00", "Z")

def sha256_text(s):
    return hashlib.sha256(s.encode()).hexdigest()

def load_json(path):
    return json.loads(Path(path).read_text())

def normalize_handle(handle):
    if not handle:
        return None
    h = handle.strip().lower()
    if not h.startswith("@"):
        h = "@" + h
    return h

def titleize_handle(handle):
    return handle.lstrip("@").replace(".", " ").replace("_", " ").title()

def score_creator(cluster, discovery_method, platform):
    base = 0.55
    if cluster == "product_discovery_moms":
        base += 0.20
    elif cluster == "household_systems_moms":
        base += 0.18
    elif cluster == "working_mom_career_balance":
        base += 0.14
    elif cluster == "honest_motherhood_creators":
        base += 0.10
    elif cluster == "kids_activity_creators":
        base += 0.08

    if discovery_method == "graph_frontier":
        base += 0.08
    elif discovery_method == "revisit_queue":
        base += 0.06
    elif discovery_method == "playbook_seed_account":
        base += 0.04

    if platform in ("instagram", "tiktok", "youtube"):
        base += 0.03

    return round(min(base, 0.98), 2)

def next_review(priority_score):
    now = utc_now()
    if priority_score >= 0.90:
        return (now + timedelta(days=7)).isoformat().replace("+00:00", "Z")
    if priority_score >= 0.80:
        return (now + timedelta(days=14)).isoformat().replace("+00:00", "Z")
    return (now + timedelta(days=30)).isoformat().replace("+00:00", "Z")

def why_it_matters(cluster, discovery_method):
    if cluster == "product_discovery_moms":
        return "High-value product discovery creator likely to influence affiliate commerce, shopping intent, and household purchase behavior."
    if cluster == "household_systems_moms":
        return "Strong fit for WellNest because this creator likely shares repeatable routines, household systems, and family operations content."
    if cluster == "working_mom_career_balance":
        return "Important because this creator likely surfaces working-parent logistics, scheduling pressure, and household/career tradeoffs."
    if cluster == "honest_motherhood_creators":
        return "Important because this creator likely expresses mental-load pain points and unmet emotional household-management needs."
    if cluster == "kids_activity_creators":
        return "Useful because this creator likely reveals high-frequency family planning and kids-activity workflow patterns."
    if discovery_method == "graph_frontier":
        return "Selected from the creator frontier because the graph suggests this creator is strategically useful for expansion."
    return "Potentially relevant household-management creator worth evaluating for downstream workflow extraction."

def cluster_topics(taxonomy, cluster):
    return taxonomy.get("cluster_topic_map", {}).get(cluster, [])

def normalize_seed_accounts(frontier, taxonomy):
    creators = []
    for item in frontier.get("seed_accounts", [])[:30]:
        handle = normalize_handle(item.get("value"))
        cluster = item.get("cluster", "unknown")
        for platform in item.get("platforms", ["instagram"]):
            priority_score = score_creator(cluster, "playbook_seed_account", platform)
            creators.append({
                "creator_handle": handle,
                "display_name": titleize_handle(handle),
                "platform": platform,
                "cluster": cluster,
                "profile_url": None,
                "bio_summary": "Seed creator from Scour playbook.",
                "topic_tags": cluster_topics(taxonomy, cluster),
                "tools_or_products": [],
                "workflow_patterns": [],
                "evidence": [
                    {
                        "kind": "seed_account",
                        "platform": platform,
                        "title": "Playbook Seed Account",
                        "snippet": "Seeded from Scour discovery playbook.",
                        "url": None,
                        "seen_at": utc_now_str()
                    }
                ],
                "confidence_score": priority_score,
                "priority_score": priority_score,
                "engagement_score": None,
                "why_it_matters": why_it_matters(cluster, "playbook_seed_account"),
                "next_review_at": next_review(priority_score),
                "discovered_from": "playbook_seed",
                "discovery_method": "playbook_seed_account",
                "discovery_bucket": "playbook_seed"
            })
    return creators

def normalize_graph_candidates(frontier, taxonomy):
    creators = []
    for item in frontier.get("graph_candidates", [])[:20]:
        handle = normalize_handle(item.get("creator_handle"))
        if not handle:
            continue
        cluster = item.get("cluster", "unknown")
        platform = item.get("platform", "web")
        priority_score = round(max(float(item.get("frontier_score", 0.0)), 0.60), 2)
        creators.append({
            "creator_handle": handle,
            "display_name": titleize_handle(handle),
            "platform": platform,
            "cluster": cluster,
            "profile_url": None,
            "bio_summary": "Creator candidate prioritized from creator graph frontier.",
            "topic_tags": cluster_topics(taxonomy, cluster) + ["graph_frontier"],
            "tools_or_products": [],
            "workflow_patterns": [],
            "evidence": [
                {
                    "kind": "graph_candidate",
                    "platform": platform,
                    "title": "Creator Graph Frontier Candidate",
                    "snippet": "Selected from Scour frontier graph.",
                    "url": None,
                    "seen_at": utc_now_str()
                }
            ],
            "confidence_score": priority_score,
            "priority_score": priority_score,
            "engagement_score": float(item.get("frontier_score", 0.0)),
            "why_it_matters": item.get("why_it_matters") or why_it_matters(cluster, "graph_frontier"),
            "next_review_at": next_review(priority_score),
            "discovered_from": "creator_graph",
            "discovery_method": "graph_frontier",
            "discovery_bucket": "graph_frontier"
        })
    return creators

def normalize_revisit_candidates(frontier, taxonomy):
    creators = []
    for item in frontier.get("revisit_candidates", [])[:15]:
        handle = normalize_handle(item.get("creator_handle"))
        if not handle:
            continue
        cluster = item.get("cluster", "unknown")
        platform = item.get("platform", "web")
        priority_score = round(max(float(item.get("priority_score", 0.0)), 0.65), 2)
        creators.append({
            "creator_handle": handle,
            "display_name": titleize_handle(handle),
            "platform": platform,
            "cluster": cluster,
            "profile_url": None,
            "bio_summary": "Creator candidate scheduled for revisit from Scour review queue.",
            "topic_tags": cluster_topics(taxonomy, cluster) + ["revisit_queue"],
            "tools_or_products": [],
            "workflow_patterns": [],
            "evidence": [
                {
                    "kind": "revisit_candidate",
                    "platform": platform,
                    "title": "Scour Revisit Queue Candidate",
                    "snippet": "Selected from revisit scheduling queue.",
                    "url": None,
                    "seen_at": utc_now_str()
                }
            ],
            "confidence_score": priority_score,
            "priority_score": priority_score,
            "engagement_score": None,
            "why_it_matters": item.get("why_it_matters") or why_it_matters(cluster, "revisit_queue"),
            "next_review_at": next_review(priority_score),
            "discovered_from": "revisit_queue",
            "discovery_method": "revisit_queue",
            "discovery_bucket": "revisit_queue"
        })
    return creators

def dedupe_creators(creators):
    seen = set()
    out = []
    for c in creators:
        key = (c.get("creator_handle", "").lower(), c.get("platform", "").lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out

def main():
    if len(sys.argv) != 5:
        print("usage: ri_build_scour_artifact.py <job_json> <artifact_id> <session_id> <output_path>", file=sys.stderr)
        sys.exit(1)

    job_json_path = Path(sys.argv[1])
    artifact_id = sys.argv[2]
    session_id = sys.argv[3]
    output_path = Path(sys.argv[4])

    frontier_path = Path.home() / "ri_db" / "work" / "scour_frontier.json"
    taxonomy_path = Path.home() / "ri_db" / "seeds" / "scour_topic_taxonomy.json"

    frontier = load_json(frontier_path)
    taxonomy = load_json(taxonomy_path)
    job = load_json(job_json_path)

    creators = []
    creators.extend(normalize_seed_accounts(frontier, taxonomy))
    creators.extend(normalize_graph_candidates(frontier, taxonomy))
    creators.extend(normalize_revisit_candidates(frontier, taxonomy))
    creators = dedupe_creators(creators)

    query = job.get("query") or job.get("payload", {}).get("query") or "scour-frontier-run"

    artifact = {
        "artifact_type": "creator_discovery_signal",
        "artifact_version": "3.0",
        "artifact_id": artifact_id,
        "job_id": job.get("job_id", ""),
        "session_id": session_id,
        "agent": "scour",
        "query": query,
        "platform": "multi",
        "title": "Scour Frontier Creator Discovery",
        "summary": "Multi-creator discovery artifact generated from Scour playbook seeds, graph frontier, and revisit queue.",
        "creators": creators,
        "verification_status": "frontier_seeded",
        "confidence_score": 0.82,
        "discovered_at": utc_now_str(),
        "content_hash": "",
        "idempotency_key": job.get("idempotency_key", ""),
        "validation_status": "pass"
    }

    artifact["content_hash"] = sha256_text(json.dumps(artifact, sort_keys=True))
    output_path.write_text(json.dumps(artifact, indent=2))
    print(str(output_path))

if __name__ == "__main__":
    main()
