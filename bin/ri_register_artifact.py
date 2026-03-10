#!/usr/bin/env python3
import json
import os
import sys
import subprocess
from pathlib import Path

def run_sql(sql: str) -> str:
    result = subprocess.run(
        ["psql", os.environ["DATABASE_URL"], "-X", "-q", "-A", "-t", "-c", sql],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()

def esc(s: str) -> str:
    return s.replace("'", "''")

def main():
    if len(sys.argv) != 9:
        print("usage: ri_register_artifact.py <artifact_id> <artifact_type> <artifact_version> <agent> <lane> <job_id> <session_id> <file_path>", file=sys.stderr)
        sys.exit(2)

    artifact_id, artifact_type, artifact_version, agent, lane, job_id, session_id, file_path = sys.argv[1:]
    p = Path(file_path)

    if not p.exists():
        print(f"artifact file not found: {file_path}", file=sys.stderr)
        sys.exit(1)

    artifact = json.loads(p.read_text())
    content_hash = artifact.get("content_hash", "")
    idempotency_key = artifact.get("idempotency_key", "")
    validation_status = artifact.get("validation_status", "pass")

    sql = f"""
    INSERT INTO artifacts (
      artifact_id, artifact_type, artifact_version, agent, lane, job_id, session_id,
      status, file_path, content_hash, idempotency_key, validation_status
    )
    VALUES (
      '{esc(artifact_id)}',
      '{esc(artifact_type)}',
      '{esc(artifact_version)}',
      '{esc(agent)}',
      '{esc(lane)}',
      '{esc(job_id)}'::uuid,
      '{esc(session_id)}',
      'ready',
      '{esc(str(p))}',
      '{esc(content_hash)}',
      '{esc(idempotency_key)}',
      '{esc(validation_status)}'
    )
    ON CONFLICT (artifact_id) DO NOTHING;
    """

    run_sql(sql)
    print(json.dumps({
        "ok": True,
        "artifact_id": artifact_id,
        "file_path": str(p)
    }))

if __name__ == "__main__":
    main()
