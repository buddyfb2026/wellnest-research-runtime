import sqlite3

import pytest

from research.lock import StoreLock
from research.recipe_review import ReviewLockBusy, ReviewRefused, publish, withdraw
from tests.wel52_helpers import make_store, publish_args, seed_version


def count(conn, table):
    return conn.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]


def test_publish_and_withdraw_are_explicit_human_acts(tmp_path):
    path = tmp_path / "research.sqlite"
    conn = make_store(path); seed = seed_version(conn); conn.close()
    result = publish(path, **publish_args(seed))
    conn = sqlite3.connect(path)
    assert result["replayed"] is False
    assert count(conn, "recipe_publications") == 1
    assert conn.execute("SELECT state,state_set_by,publishable FROM recipe_versions WHERE id=?",
                        (seed["version_id"],)).fetchone() == ("approved", "human:Fixture Reviewer", 1)
    withdrawn = withdraw(path, intent_id="fixture-withdraw", version_id=seed["version_id"],
                         by="human:Fixture Reviewer", authority="fixture-review", reason="test")
    assert withdrawn["replayed"] is False
    assert count(conn, "recipe_publications") == 2
    conn.close()


def test_replay_with_same_intent_is_a_noop(tmp_path):
    path = tmp_path / "research.sqlite"
    conn = make_store(path); seed = seed_version(conn); conn.close()
    first = publish(path, **publish_args(seed))
    second = publish(path, **publish_args(seed))
    conn = sqlite3.connect(path)
    assert second["replayed"] is True
    assert second["publication_id"] == first["publication_id"]
    assert count(conn, "recipe_publications") == 1
    conn.close()


def test_intent_reuse_with_different_args_is_refused(tmp_path):
    path = tmp_path / "research.sqlite"
    conn = make_store(path); seed = seed_version(conn); conn.close()
    publish(path, **publish_args(seed))
    changed = publish_args(seed); changed["authority"] = "different"
    with pytest.raises(ReviewRefused, match="intent_id_reused"):
        publish(path, **changed)
    conn = sqlite3.connect(path)
    assert count(conn, "recipe_publications") == 1
    conn.close()


def test_worker_cannot_publish(tmp_path):
    path = tmp_path / "research.sqlite"
    conn = make_store(path); seed = seed_version(conn); conn.close()
    args = publish_args(seed); args["by"] = "worker"
    with pytest.raises(ReviewRefused):
        publish(path, **args)
    conn = sqlite3.connect(path)
    assert count(conn, "recipe_publications") == 0
    assert conn.execute("SELECT publishable FROM recipe_versions WHERE id=?", (seed["version_id"],)).fetchone()[0] == 0
    conn.close()


def test_crash_before_commit_leaves_no_row(tmp_path):
    path = tmp_path / "research.sqlite"
    conn = make_store(path); seed = seed_version(conn); conn.close()
    def crash(stage):
        assert stage == "before_commit"
        raise RuntimeError("crash")
    args = publish_args(seed); args["crash_hook"] = crash
    with pytest.raises(RuntimeError, match="crash"):
        publish(path, **args)
    conn = sqlite3.connect(path)
    assert count(conn, "recipe_publications") == 0
    assert conn.execute("SELECT state,publishable FROM recipe_versions WHERE id=?", (seed["version_id"],)).fetchone() == ("pending", 0)
    conn.close()


def test_crash_after_commit_replays_identical_publication(tmp_path):
    path = tmp_path / "research.sqlite"
    conn = make_store(path); seed = seed_version(conn); conn.close()
    def crash(stage):
        if stage == "after_commit":
            raise RuntimeError("lost ack")
    args = publish_args(seed); args["crash_hook"] = crash
    with pytest.raises(RuntimeError, match="lost ack"):
        publish(path, **args)
    replay = publish(path, **publish_args(seed))
    conn = sqlite3.connect(path)
    assert replay["replayed"] is True
    assert count(conn, "recipe_publications") == 1
    conn.close()


def test_review_act_holds_store_lock(tmp_path):
    path = tmp_path / "research.sqlite"
    conn = make_store(path); seed = seed_version(conn); conn.close()
    held = StoreLock(path); assert held.acquire() is True
    try:
        with pytest.raises(ReviewLockBusy):
            publish(path, **publish_args(seed))
    finally:
        held.release()
    conn = sqlite3.connect(path)
    assert count(conn, "recipe_publications") == 0
    conn.close()


@pytest.mark.parametrize("mutation", ["map", "tokens", "equipment", "attestation", "rights"])
def test_publish_requires_complete_applicability_and_attestation(tmp_path, mutation):
    path = tmp_path / (mutation + ".sqlite")
    conn = make_store(path); seed = seed_version(conn); conn.close()
    args = publish_args(seed)
    if mutation == "map": args["ingredient_map"] = args["ingredient_map"][:-1]
    if mutation == "tokens": args["ingredient_map"][0]["tokens"] = ["unlisted"]
    if mutation == "equipment": args["equipment_needs"] = [{"text": "Oven", "anchor": "not present"}]
    if mutation == "attestation": args["equipment_reviewed"] = False
    if mutation == "rights": args["rights_basis"] = ""
    with pytest.raises(ReviewRefused):
        publish(path, **args)
    conn = sqlite3.connect(path)
    assert count(conn, "recipe_publications") == 0
    conn.close()
