#!/usr/bin/env python3
import json
import os
import hashlib
from pathlib import Path
import subprocess
import sys

DB_URL = os.environ.get("DATABASE_URL", "postgresql:///research_intelligence")

def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def q(s):
    if s is None:
        return "NULL"
    return "'" + str(s).replace("'", "''") + "'"

def main():
    if len(sys.argv) != 2:
        print("usage: ri_sync_artifact_metadata.py <artifact_json_path>", file=sys.stderr)
        sys.exit(1)

    path = Path(sys.argv[1])
    data = json.loads(path.read_text())

    artifact_id = data.get("artifact_id") or path.stem
    artifact_type = data.get("artifact_type")
    artifact_version = data.get("artifact_version")
    content_hash = sha256_file(path)

    sql = """
    update artifacts
    set
      artifact_type = {artifact_type},
      artifact_version = {artifact_version},
      content_hash = {content_hash},
      validation_status = 'pass'
    where artifact_id = {artifact_id};
    """.format(
        artifact_type=q(artifact_type),
        artifact_version=q(artifact_version),
        content_hash=q(content_hash),
        artifact_id=q(artifact_id),
    )

    subprocess.run(
        ["/opt/homebrew/opt/postgresql@16/bin/psql", DB_URL, "-v", "ON_ERROR_STOP=1", "-c", sql],
        check=True,
    )

    print(artifact_id)

if __name__ == "__main__":
    main()
