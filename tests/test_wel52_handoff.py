"""Executable WEL-52 producer-to-GrokBot handoff contract.

This test deliberately fails (never skips) when the consumer checkout or its WEL-52 CLI is
absent. That makes a producer-only run honest: A9 is not green until the real consumer exists.
"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.wel52_helpers import make_store, seed_version

ROOT = Path(__file__).resolve().parent.parent


def _tree_hashes(paths):
    result = {}
    for base in paths:
        if not base.exists():
            continue
        for path in sorted(p for p in base.rglob("*") if p.is_file()):
            result[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _publish_cli(db_path, seed, intent):
    token = seed["recipe_key"][:8]
    mapping = ";".join("%d:%s" % (i, token) for i in range(len(seed["ingredients"])))
    command = [sys.executable, "-m", "research.recipe_review", "publish", "--db", str(db_path),
               "--intent", intent, "--version", str(seed["version_id"]),
               "--by", "human:Fixture Reviewer", "--authority", "fixture-review",
               "--rights-basis", "fixture-only test data", "--template", seed["spec"]["template"],
               "--requires", token, "--map", mapping, "--equipment", "Skillet|skillet",
               "--equipment-reviewed"]
    subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)


def _export_cli(db_path, pack_path):
    subprocess.run([sys.executable, "scripts/wel52_build_pack.py", str(db_path), str(pack_path),
                    "--allow-fixture-evidence"], cwd=ROOT, check=True, capture_output=True, text=True)


def _consume(app, pack_path):
    completed = subprocess.run(
        ["node", "--import", "tsx", "scripts/wel52-consume.mts", str(pack_path),
         "--strip-fixture-marker", "--household", "eligible"],
        cwd=app, check=True, capture_output=True, text=True)
    return json.loads(completed.stdout)


def test_real_producer_consumer_two_then_three(tmp_path):
    app_value = os.environ.get("WELLNEST_APP_DIR")
    assert app_value, "A9 requires WELLNEST_APP_DIR; absent consumer is a failure, never a skip"
    app = Path(app_value).resolve()
    assert (app / "scripts/wel52-consume.mts").is_file(), "A9 blocked: GrokBot WEL-52 consumer CLI is absent"
    assert (app / "node_modules/tsx").exists(), "A9 blocked: GrokBot dependencies are not installed"

    db_path, pack_path = tmp_path / "research.sqlite", tmp_path / "recipe-pack.v1.json"
    conn = make_store(db_path)
    a, b, c = seed_version(conn, "f-a"), seed_version(conn, "f-b"), seed_version(conn, "f-c")
    conn.close()
    protected = [ROOT / "research", ROOT / "scripts", app / "src", app / "api"]
    before = _tree_hashes(protected)

    _publish_cli(db_path, a, "handoff-a"); _publish_cli(db_path, b, "handoff-b")
    _export_cli(db_path, pack_path)
    first_pack = json.loads(pack_path.read_text()); first = _consume(app, pack_path)
    assert first_pack["generation"] == 1 and len(first_pack["recipes"]) == 2
    assert first["accepted"] == 2 and first["attached"] == 2
    assert first["inventories"] == [[9, 4], [13, 11]]
    assert _tree_hashes(protected) == before

    _publish_cli(db_path, c, "handoff-c"); _export_cli(db_path, pack_path)
    second_pack = json.loads(pack_path.read_text()); second = _consume(app, pack_path)
    assert second_pack["generation"] == 2 and len(second_pack["recipes"]) == 3
    assert second["accepted"] == 3 and second["attached"] == 3
    assert second["inventories"] == [[9, 4], [13, 11], [15, 3]]
    assert _tree_hashes(protected) == before
