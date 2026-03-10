#!/usr/bin/env python3
import json
import os
import hashlib
from pathlib import Path
import subprocess
import sys

DB_URL = os.environ.get("DATABASE_URL", "postgresql:///research_intelligence")

def run_sql(sql):
    subprocess.run(
        ["/opt/homebrew/opt/postgresql@16/bin/psql", DB_URL, "-v", "ON_ERROR_STOP=1", "-c", sql],
        check=True,
    )

def q(s):
    if s is None:
        return "NULL"
    return "'" + str(s).replace("'", "''") + "'"

def normalize_handle(handle):
    if not handle:
        return None
    h = str(handle).strip().lower()
    if not h.startswith("@"):
        h = "@" + h
    return h

def creator_key(handle, platform):
    return "{}:{}".format(platform, normalize_handle(handle))

def edge_key(a, b, rel):
    raw = "{}|{}|{}".format(a, b, rel)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]

def normalize_creators(data):
    creators = []
    if not isinstance(data, dict):
        return creators

    if isinstance(data.get("creators"), list):
        creators.extend([x for x in data["creators"] if isinstance(x, dict)])

    handle = data.get("creator_handle") or data.get("handle") or data.get("account")
    if handle:
        creators.append({
            "creator_handle": handle,
            "display_name": data.get("creator_name") or data.get("display_name"),
            "platform": data.get("platform", "unknown"),
            "cluster": data.get("cluster") or data.get("topic_cluster") or "unknown",
            "bio_summary": data.get("summary"),
            "confidence_score": data.get("confidence_score"),
            "priority_score": data.get("priority_score"),
            "engagement_score": data.get("engagement_score"),
            "topic_tags": data.get("topic_tags") or data.get("topics") or [],
            "source_url": data.get("profile_url"),
            "evidence": data.get("evidence") or [],
            "why_it_matters": data.get("why_it_matters"),
            "next_review_at": data.get("next_review_at"),
            "discovered_from": data.get("discovered_from"),
            "discovery_bucket": data.get("discovery_bucket")
        })

    return creators

def main():
    if len(sys.argv) != 2:
        print("usage: ri_update_creator_graph.py <artifact_json_path>", file=sys.stderr)
        sys.exit(1)

    path = Path(sys.argv[1])
    data = json.loads(path.read_text())

    artifact_id = data.get("artifact_id") or path.stem
    default_platform = data.get("platform", "unknown")
    default_cluster = data.get("cluster") or data.get("topic_cluster") or "unknown"

    creators = normalize_creators(data)

    for item in creators:
        handle = normalize_handle(item.get("creator_handle") or item.get("handle") or item.get("account"))
        if not handle:
            continue

        item_platform = item.get("platform", default_platform)
        node_key = creator_key(handle, item_platform)
        display_name = item.get("display_name")
        display_name_normalized = display_name.lower() if display_name else None
        bio_summary = item.get("bio_summary") or item.get("content_summary")
        confidence_score = item.get("confidence_score")
        priority_score = item.get("priority_score")
        engagement_score = item.get("engagement_score")
        topic_tags = item.get("topic_tags") or item.get("topics") or []
        source_url = item.get("source_url")
        node_cluster = item.get("cluster", default_cluster)
        evidence = item.get("evidence") or []
        why_it_matters = item.get("why_it_matters")
        next_review_at = item.get("next_review_at")
        discovery_bucket = item.get("discovery_bucket") or item.get("discovery_method") or "unknown"

        sql = """
        insert into creator_graph_nodes (
          creator_key, creator_handle, canonical_handle, platform, cluster, display_name, display_name_normalized, bio_summary,
          confidence_score, priority_score, engagement_score, topic_tags, source_url, last_artifact_id,
          source_count, times_seen, evidence_count, last_checked_at, raw_evidence, why_it_matters, next_review_at,
          last_discovery_bucket, source_platforms, handle_aliases
        ) values (
          {creator_key},
          {creator_handle},
          {canonical_handle},
          {platform},
          {cluster},
          {display_name},
          {display_name_normalized},
          {bio_summary},
          {confidence_score},
          {priority_score},
          {engagement_score},
          {topic_tags}::jsonb,
          {source_url},
          {artifact_id},
          {source_count},
          1,
          {evidence_count},
          now(),
          {raw_evidence}::jsonb,
          {why_it_matters},
          {next_review_at}::timestamptz,
          {last_discovery_bucket},
          {source_platforms}::jsonb,
          {handle_aliases}::jsonb
        )
        on conflict (creator_key) do update set
          canonical_handle = excluded.canonical_handle,
          cluster = excluded.cluster,
          display_name = coalesce(excluded.display_name, creator_graph_nodes.display_name),
          display_name_normalized = coalesce(excluded.display_name_normalized, creator_graph_nodes.display_name_normalized),
          bio_summary = coalesce(excluded.bio_summary, creator_graph_nodes.bio_summary),
          confidence_score = coalesce(excluded.confidence_score, creator_graph_nodes.confidence_score),
          priority_score = coalesce(excluded.priority_score, creator_graph_nodes.priority_score),
          engagement_score = coalesce(excluded.engagement_score, creator_graph_nodes.engagement_score),
          topic_tags = excluded.topic_tags,
          source_url = coalesce(excluded.source_url, creator_graph_nodes.source_url),
          last_artifact_id = excluded.last_artifact_id,
          source_count = greatest(creator_graph_nodes.source_count, excluded.source_count),
          times_seen = creator_graph_nodes.times_seen + 1,
          evidence_count = greatest(creator_graph_nodes.evidence_count, excluded.evidence_count),
          last_checked_at = now(),
          last_seen_at = now(),
          raw_evidence = excluded.raw_evidence,
          why_it_matters = coalesce(excluded.why_it_matters, creator_graph_nodes.why_it_matters),
          next_review_at = coalesce(excluded.next_review_at, creator_graph_nodes.next_review_at),
          last_discovery_bucket = excluded.last_discovery_bucket,
          source_platforms = excluded.source_platforms,
          handle_aliases = excluded.handle_aliases;
        """.format(
            creator_key=q(node_key),
            creator_handle=q(handle),
            canonical_handle=q(handle.lstrip("@")),
            platform=q(item_platform),
            cluster=q(node_cluster),
            display_name=q(display_name),
            display_name_normalized=q(display_name_normalized),
            bio_summary=q(bio_summary),
            confidence_score=str(confidence_score) if confidence_score is not None else "NULL",
            priority_score=str(priority_score) if priority_score is not None else "NULL",
            engagement_score=str(engagement_score) if engagement_score is not None else "NULL",
            topic_tags=q(json.dumps(topic_tags)),
            source_url=q(source_url),
            artifact_id=q(artifact_id),
            source_count=str(len(evidence)),
            evidence_count=str(len(evidence)),
            raw_evidence=q(json.dumps(evidence)),
            why_it_matters=q(why_it_matters),
            next_review_at=q(next_review_at),
            last_discovery_bucket=q(discovery_bucket),
            source_platforms=q(json.dumps([item_platform])),
            handle_aliases=q(json.dumps([handle])),
        )
        run_sql(sql)

        discovered_from = item.get("discovered_from")
        if discovered_from and discovered_from not in ("playbook_seed", "creator_graph", "revisit_queue"):
            from_key = creator_key(discovered_from, item_platform)
            ek = edge_key(from_key, node_key, "discovered_from")
            edge_sql = """
            insert into creator_graph_edges (
              edge_key, from_creator_key, to_creator_key, relationship_type, evidence_source, artifact_id
            ) values (
              {edge_key},
              {from_creator_key},
              {to_creator_key},
              'discovered_from',
              {evidence_source},
              {artifact_id}
            )
            on conflict (edge_key) do nothing;
            """.format(
                edge_key=q(ek),
                from_creator_key=q(from_key),
                to_creator_key=q(node_key),
                evidence_source=q(source_url),
                artifact_id=q(artifact_id),
            )
            run_sql(edge_sql)

if __name__ == "__main__":
    main()
