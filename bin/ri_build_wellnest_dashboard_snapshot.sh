#!/usr/bin/env bash
set -euo pipefail

DB="postgres://localhost/research_intelligence"
OUT="$HOME/ri_db/outputs/wellnest_dashboard.json"

creators_json="$(psql "$DB" -Atc "
select coalesce(jsonb_agg(x order by id desc), '[]'::jsonb)
from (
  select id, platform, handle, profile_url, followers, discovered_at
  from creator_profiles
  order by id desc
  limit 25
) x;
")"

competitors_json="$(psql "$DB" -Atc "
select coalesce(jsonb_agg(x order by id desc), '[]'::jsonb)
from (
  select id, name, website, category, discovered_at
  from competitors
  order by id desc
  limit 25
) x;
")"

workflows_json="$(psql "$DB" -Atc "
select coalesce(jsonb_agg(x order by id desc), '[]'::jsonb)
from (
  select id, title, description, trigger, steps, failure_points, created_at
  from wellnest_workflows
  order by id desc
  limit 50
) x;
")"

creator_count="$(psql "$DB" -Atc "select count(*) from creator_profiles;")"
competitor_count="$(psql "$DB" -Atc "select count(*) from competitors;")"
workflow_count="$(psql "$DB" -Atc "select count(*) from wellnest_workflows;")"
creator_intel_count="$(psql "$DB" -Atc "select count(*) from creator_intel;")"
competitor_intel_count="$(psql "$DB" -Atc "select count(*) from competitor_intel;")"

latest_scour="$(ls -1t "$HOME/ri_db/inbox/scour"/*.scour.json 2>/dev/null | head -n 1 || true)"
latest_hans="$(ls -1t "$HOME/ri_db/inbox/hans"/*.hans.json 2>/dev/null | head -n 1 || true)"
latest_scout="$( (ls -1t "$HOME/ri_db/processed"/*.scout.scout.*.json 2>/dev/null; ls -1t "$HOME/ri_db/archive"/*.scout.json 2>/dev/null; ls -1t "$HOME/ri_db/outputs"/scout_input_*.json 2>/dev/null) | head -n 1 || true)"
latest_franz="$( (ls -1t "$HOME/ri_db/processed"/*.franz.franz.*.json 2>/dev/null; ls -1t "$HOME/ri_db/archive"/*.franz.json 2>/dev/null; ls -1t "$HOME/ri_db/outputs"/franz_input_*.json 2>/dev/null) | head -n 1 || true)"
latest_atlas="$( (ls -1t "$HOME/ri_db/processed"/*.atlas.*.json 2>/dev/null; ls -1t "$HOME/ri_db/errors"/*.atlas.*.json 2>/dev/null; ls -1t "$HOME/ri_db/outputs"/atlas_input.json 2>/dev/null) | head -n 1 || true)"
latest_karen="$( (ls -1t "$HOME/ri_db/processed"/*.karen.*.json 2>/dev/null; ls -1t "$HOME/ri_db/errors"/*.karen.*.json 2>/dev/null; ls -1t "$HOME/ri_db/outputs"/karen_input.json 2>/dev/null) | head -n 1 || true)"

latest_atlas_error="$(ls -1t "$HOME/ri_db/errors"/*.atlas.*.json 2>/dev/null | head -n 1 || true)"
latest_karen_error="$(ls -1t "$HOME/ri_db/errors"/*.karen.*.json 2>/dev/null | head -n 1 || true)"

python3 - <<PY
import json, os, datetime

def classify_path(path):
    if not path:
        return ("missing", "missing")
    if "/processed/" in path:
        return ("success", "processed")
    if "/errors/" in path:
        return ("error", "errors")
    if "/archive/" in path:
        return ("success", "archive")
    if "/inbox/" in path:
        return ("success", "inbox")
    if "/outputs/" in path:
        return ("input_only", "outputs")
    return ("unknown", "other")

def file_meta(path):
    status, bucket = classify_path(path)
    if not path or not os.path.exists(path):
        return {
            "path": path or None,
            "exists": False,
            "mtime": None,
            "event_time": None,
            "file_name": os.path.basename(path) if path else None,
            "status": "missing",
            "source_bucket": "missing",
        }
    mtime = datetime.datetime.utcfromtimestamp(os.path.getmtime(path)).isoformat() + "Z"
    return {
        "path": path,
        "exists": True,
        "mtime": mtime,
        "event_time": mtime,
        "file_name": os.path.basename(path),
        "status": status,
        "source_bucket": bucket,
    }

def preview_text(path):
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            raw = f.read(4000)
        try:
            obj = json.loads(raw)
            return json.dumps(obj, indent=2)[:1600]
        except Exception:
            return raw[:1600]
    except Exception as e:
        return f"Unable to read error file: {e}"

def error_detail(path):
    if not path or not os.path.exists(path):
        return None
    return {
        "path": path,
        "file_name": os.path.basename(path),
        "mtime": datetime.datetime.utcfromtimestamp(os.path.getmtime(path)).isoformat() + "Z",
        "preview": preview_text(path),
    }

def lock_detail(name, label, stage, latest_path):
    lock_dir = os.path.join(os.path.expanduser("~"), "ri_db", "locks", f"ri_{name}.lock")
    pid_path = os.path.join(lock_dir, "pid")
    ts_path = os.path.join(lock_dir, "ts")
    lock_exists = os.path.isdir(lock_dir)
    pid = None
    ts_raw = None
    ts_iso = None

    if lock_exists:
        if os.path.exists(pid_path):
            try:
                pid = open(pid_path).read().strip() or None
            except Exception:
                pid = None
        if os.path.exists(ts_path):
            try:
                ts_raw = open(ts_path).read().strip() or None
                if ts_raw and ts_raw.isdigit():
                    ts_iso = datetime.datetime.utcfromtimestamp(int(ts_raw)).isoformat() + "Z"
            except Exception:
                ts_raw = None
                ts_iso = None

    latest = file_meta(latest_path)
    artifact_status = latest["status"]

    if lock_exists:
        runtime_state = "running"
    elif artifact_status == "error":
        runtime_state = "error"
    elif artifact_status in ("success", "input_only"):
        runtime_state = "idle"
    else:
        runtime_state = "idle"

    return {
        "id": name,
        "label": label,
        "stage": stage,
        "runtime_state": runtime_state,
        "lock_present": lock_exists,
        "lock_pid": pid,
        "lock_ts": ts_iso,
        "latest_artifact": latest,
    }

out = {
  "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
  "counts": {
    "creator_profiles": int("${creator_count}"),
    "competitors": int("${competitor_count}"),
    "wellnest_workflows": int("${workflow_count}"),
    "creator_intel": int("${creator_intel_count}"),
    "competitor_intel": int("${competitor_intel_count}")
  },
  "latest_files": {
    "atlas": "${latest_atlas}",
    "karen": "${latest_karen}"
  },
  "pipeline_events": [
    {"id": "scour", "label": "Scour", "stage": "Creator Discovery", **file_meta("${latest_scour}")},
    {"id": "hans", "label": "Hans", "stage": "Competitor Discovery", **file_meta("${latest_hans}")},
    {"id": "scout", "label": "Scout", "stage": "Workflow Extraction", **file_meta("${latest_scout}")},
    {"id": "franz", "label": "Franz", "stage": "Competitor Intelligence", **file_meta("${latest_franz}")},
    {"id": "atlas", "label": "Atlas", "stage": "Opportunity Ranking", **file_meta("${latest_atlas}")},
    {"id": "karen", "label": "Karen", "stage": "Feature Specification", **file_meta("${latest_karen}")},
  ],
  "agent_runtime": [
    lock_detail("scour", "Scour", "Creator Discovery", "${latest_scour}"),
    lock_detail("hans", "Hans", "Competitor Discovery", "${latest_hans}"),
    lock_detail("scout", "Scout", "Workflow Extraction", "${latest_scout}"),
    lock_detail("franz", "Franz", "Competitor Intelligence", "${latest_franz}"),
    lock_detail("atlas", "Atlas", "Opportunity Ranking", "${latest_atlas}"),
    lock_detail("karen", "Karen", "Feature Specification", "${latest_karen}")
  ],
  "error_details": {
    "atlas": error_detail("${latest_atlas_error}") if classify_path("${latest_atlas}")[0] == "error" else None,
    "karen": error_detail("${latest_karen_error}") if classify_path("${latest_karen}")[0] == "error" else None
  },
  "creators": json.loads("""${creators_json}"""),
  "competitors": json.loads("""${competitors_json}"""),
  "wellnest_workflows": json.loads("""${workflows_json}""")
}

for key, path in list(out["latest_files"].items()):
  if path and os.path.exists(path):
    try:
      with open(path) as f:
        out[key] = json.load(f)
    except Exception:
      out[key] = None
  else:
    out[key] = None

with open("${OUT}", "w") as f:
  json.dump(out, f, indent=2)

print("OK: wrote ${OUT}")
PY
