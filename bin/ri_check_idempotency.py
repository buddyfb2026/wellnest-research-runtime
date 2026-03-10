#!/usr/bin/env python3
import json
import os
import sys
import subprocess

def run_sql(sql: str) -> str:
    result = subprocess.run(
        ["psql", os.environ["DATABASE_URL"], "-X", "-q", "-A", "-t", "-c", sql],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()

def main():
    if len(sys.argv) != 2:
        print("usage: ri_check_idempotency.py <idempotency_key>", file=sys.stderr)
        sys.exit(2)

    key = sys.argv[1].replace("'", "''")

    sql = f"""
    SELECT artifact_id, file_path, status
    FROM artifacts
    WHERE idempotency_key = '{key}'
    ORDER BY created_at DESC
    LIMIT 1;
    """

    out = run_sql(sql)
    if not out:
        print(json.dumps({"exists": False}))
        return

    artifact_id, file_path, status = out.split("|")
    print(json.dumps({
        "exists": True,
        "artifact_id": artifact_id,
        "file_path": file_path,
        "status": status
    }))

if __name__ == "__main__":
    main()
