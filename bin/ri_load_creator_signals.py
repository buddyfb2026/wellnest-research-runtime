#!/usr/bin/env python3
import json
import subprocess

DB = "research_intelligence"
PSQL = "/opt/homebrew/opt/postgresql@16/bin/psql"

WORKFLOW_HINTS = [
    "reset","routine","system","schedule","checklist","weekly","daily",
    "meal plan","grocery","laundry","command center","zone cleaning",
    "closing shift","prep","rotation","family","home","organization","declutter","cleaning"
]

def sql(q):
    return subprocess.check_output([PSQL, "-d", DB, "-Atqc", q], text=True)

def q(v):
    if v is None:
        return "NULL"
    return "'" + str(v).replace("'", "''") + "'"

def score(text):
    text_l = (text or "").lower()

    workflow_hits = [k for k in WORKFLOW_HINTS if k in text_l]
    workflow_density = min(1.0, len(workflow_hits) / 6.0)

    relevance_hits = sum(
        1 for k in [
            "household", "family", "mom", "home", "planning",
            "organization", "cleaning", "declutter", "routine"
        ]
        if k in text_l
    )
    relevance = min(1.0, relevance_hits / 5.0)

    engagement = 0.0
    consistency = 0.5
    cross_platform = 0.0

    score_val = (
        engagement * 0.30 +
        workflow_density * 0.30 +
        consistency * 0.15 +
        relevance * 0.15 +
        cross_platform * 0.10
    )

    return round(score_val, 4), workflow_density >= 0.30, json.dumps(workflow_hits)

rows = sql("""
SELECT id, payload::text
FROM creator_discovery_payloads
ORDER BY id DESC
LIMIT 500
""").splitlines()

loaded = 0

for r in rows:
    parts = r.split("|", 1)
    if len(parts) != 2:
        continue

    payload_id, payload = parts

    try:
        obj = json.loads(payload)
    except Exception:
        continue

    creators = []
    topic = None
    run_id = None

    if isinstance(obj, dict):
        creators = obj.get("creators") or []
        topic = obj.get("topic")
        run_id = obj.get("run_id")

    if not isinstance(creators, list):
        continue

    for item in creators:
        if not isinstance(item, dict):
            continue

        platform = item.get("platform") or "unknown"
        creator_handle = item.get("handle") or item.get("creator_handle") or "unknown"
        creator_name = item.get("name") or item.get("creator_name")
        content_url = item.get("profile_url") or item.get("url")
        content_title = f"{creator_handle} profile"
        content_type = "creator_profile"
        content_text = item.get("notes") or ""
        discovery_query = topic

        if not content_url:
            continue

        score_val, detected, keywords_json = score(
            " ".join(
                x for x in [
                    topic or "",
                    content_text or "",
                    creator_handle or "",
                    platform or ""
                ] if x
            )
        )

        insert = f"""
        INSERT INTO creator_signals (
          platform,
          creator_handle,
          creator_name,
          content_url,
          content_title,
          content_type,
          content_text,
          discovery_query,
          workflow_keywords,
          workflow_detected,
          source_quality_score
        )
        VALUES (
          {q(platform)},
          {q(creator_handle)},
          {q(creator_name)},
          {q(content_url)},
          {q(content_title)},
          {q(content_type)},
          {q(content_text)},
          {q(discovery_query)},
          {q(keywords_json)}::jsonb,
          {'TRUE' if detected else 'FALSE'},
          {score_val}
        )
        ON CONFLICT (platform, content_url) DO UPDATE SET
          creator_handle = EXCLUDED.creator_handle,
          creator_name = EXCLUDED.creator_name,
          content_title = EXCLUDED.content_title,
          content_type = EXCLUDED.content_type,
          content_text = EXCLUDED.content_text,
          discovery_query = EXCLUDED.discovery_query,
          workflow_keywords = EXCLUDED.workflow_keywords,
          workflow_detected = EXCLUDED.workflow_detected,
          source_quality_score = EXCLUDED.source_quality_score;
        """
        sql(insert)
        loaded += 1

print(f"loaded_or_updated={loaded}")
