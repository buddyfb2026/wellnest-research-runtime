import copy
import json

import pytest

from research import db, knowledge, recipes, source_registry as registry
from tests.wel51_helpers import counts, latest, roster, seed_corpus


class Crash(BaseException):
    pass


def _raise(point):
    def hook(actual):
        if actual == point:
            raise Crash(actual)
    return hook


def _add_b_version(conn, row):
    changed = copy.deepcopy(row["manifest"])
    changed["wel51_fixture_revision"] = "B"
    manifest_id, _ = recipes.attach_manifest(conn, row["evidence_id"], changed, "2026-09-22T00:00:00Z")
    manifest_hash = conn.execute("SELECT manifest_hash FROM locator_manifests WHERE id=?", (manifest_id,)).fetchone()[0]
    document = copy.deepcopy(row["document"]); document["provenance"]["manifest_hash"] = manifest_hash
    key = recipes.extraction_key(row["evidence_id"], manifest_hash, row["slot"], "fixture")
    return recipes.save_version(conn, row["recipe_id"], row["evidence_id"], manifest_id, manifest_hash, key,
                                "fixture", document, None, document["completeness"], document["unknown_fields"],
                                document["conflicts"], "pending", None, None, "2026-09-22T00:00:00Z")


def test_k1_crash_before_commit(tmp_path):
    path = tmp_path / "db.sqlite"; conn, _ = seed_corpus(path); conn.close()
    with pytest.raises(Crash): knowledge.synthesize(path, _raise("before_knowledge_commit"))
    conn = db.connect(path); assert counts(conn) == (0, 0, 0); conn.close()
    knowledge.synthesize(path); conn = db.connect(path); assert counts(conn) == (1, 4, 1)


def test_k2_replay_inserts_nothing(tmp_path):
    path = tmp_path / "db.sqlite"; conn, _ = seed_corpus(path); conn.close()
    with pytest.raises(Crash): knowledge.synthesize(path, _raise("after_knowledge_commit"))
    conn = db.connect(path); assert counts(conn) == (1, 4, 1); conn.close()
    knowledge.synthesize(path); knowledge.synthesize(path); conn = db.connect(path); assert counts(conn) == (1, 4, 1)


def test_changed_support_does_not_inherit_approval(tmp_path):
    path = tmp_path / "db.sqlite"; conn, rows = seed_corpus(path); conn.close(); knowledge.synthesize(path)
    conn = db.connect(path); first = latest(conn); conn.close(); knowledge.review(path, first["id"], "approved", "human:reviewer", "reviewed")
    conn = db.connect(path); _add_b_version(conn, rows["E2"]); conn.close(); knowledge.synthesize(path); conn = db.connect(path)
    assert [tuple(r) for r in conn.execute("SELECT version_no,state FROM finding_versions ORDER BY version_no")] == [(1, "approved"), (2, "pending")]
    assert conn.execute("SELECT COUNT(*) FROM finding_links").fetchone()[0] == 5
    assert conn.execute("SELECT state_set_by FROM finding_versions WHERE version_no=1").fetchone()[0] == "human:reviewer"


def test_roster_change_invalidates_version(tmp_path):
    path = tmp_path / "db.sqlite"; conn, _ = seed_corpus(path); conn.close(); knowledge.synthesize(path); conn = db.connect(path)
    registry.project(conn, roster(mirror_parent="public_domain_recipes")); conn.close(); knowledge.synthesize(path); conn = db.connect(path)
    value = knowledge.independent_support(conn, 1)
    assert counts(conn)[2] == 2 and value["distinct_roots"] == 2 and value["independent_publisher_count"] == 2


def test_digest_return_appends_pending(tmp_path):
    path = tmp_path / "db.sqlite"; conn, rows = seed_corpus(path); conn.close(); knowledge.synthesize(path); conn = db.connect(path)
    v1_digest = latest(conn)["support_digest"]; a_id = recipes.resolve_current(conn, rows["E2"]["recipe_id"])["id"]
    _add_b_version(conn, rows["E2"]); conn.close(); knowledge.synthesize(path); conn = db.connect(path)
    recipes.attach_manifest(conn, rows["E2"]["evidence_id"], rows["E2"]["manifest"], "2026-09-23T00:00:00Z")
    assert recipes.resolve_current(conn, rows["E2"]["recipe_id"])["id"] == a_id
    conn.close(); knowledge.synthesize(path); conn = db.connect(path)
    assert counts(conn) == (1, 5, 3)
    assert latest(conn)["support_digest"] == v1_digest and latest(conn)["state"] == "pending"
