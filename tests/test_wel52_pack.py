import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from research import db
from research.lock import StoreLock
from research.recipe_pack import (ExportLockBusy, ExportRefused, OMITTED_REASONS, export_recipe_pack,
                                  served_state)
from research.recipe_review import publish, withdraw
from research.recipes import attach_manifest, canonical_json
from tests.wel52_helpers import make_store, publish_args, seed_version


def _publish(path, seed, intent):
    args = publish_args(seed, intent)
    publish(path, **args)


def _export(path, out, hook=None):
    return export_recipe_pack(path, out, allow_fixture_evidence=True, crash_hook=hook)


def test_export_two_recipes_with_exact_identity_and_hash(tmp_path):
    path, out = tmp_path / "research.sqlite", tmp_path / "recipe-pack.v1.json"
    conn = make_store(path)
    a = seed_version(conn, "f-a"); b = seed_version(conn, "f-b")
    conn.close(); _publish(path, a, "pub-a"); _publish(path, b, "pub-b")
    pack = _export(path, out)
    assert len(pack["recipes"]) == 2
    assert pack["generation"] == 1
    assert [r["publication"]["recipe_key"] for r in pack["recipes"]] == sorted([a["recipe_key"], b["recipe_key"]])
    expected = hashlib.sha256(canonical_json(served_state(pack)).encode()).hexdigest()
    assert pack["pack_id"] == expected
    assert pack["_fixture"].startswith("wel52 fixture")
    assert json.loads(out.read_text())["pack_id"] == expected


def test_unchanged_state_reuses_generation(tmp_path, monkeypatch):
    path, out = tmp_path / "research.sqlite", tmp_path / "pack.json"
    conn = make_store(path); seed = seed_version(conn); conn.close(); _publish(path, seed, "pub")
    first = _export(path, out); first_bytes = out.read_bytes()
    second = _export(path, out); second_bytes = out.read_bytes()
    assert second["generation"] == first["generation"] == 1
    assert second["pack_id"] == first["pack_id"]
    left, right = json.loads(first_bytes), json.loads(second_bytes)
    left.pop("generated_at"); right.pop("generated_at")
    assert left == right


def test_generation_advances_on_source_current_drift(tmp_path):
    path, out = tmp_path / "research.sqlite", tmp_path / "pack.json"
    conn = make_store(path); seed = seed_version(conn); conn.close(); _publish(path, seed, "pub")
    p1 = _export(path, out)
    conn = db.connect(path)
    attach_manifest(conn, seed["evidence_id"], {"locator_version": "wel48_locator_v1",
                    "recipes": [{"slot": "name:other"}]}, "2026-09-15T01:00:00Z")
    conn.close()
    p2 = _export(path, out)
    conn = db.connect(path)
    attach_manifest(conn, seed["evidence_id"], seed["manifest"], "2026-09-15T02:00:00Z")
    conn.close()
    p3 = _export(path, out)
    assert [p1["generation"], p2["generation"], p3["generation"]] == [1, 2, 3]
    assert [len(p1["recipes"]), len(p2["recipes"]), len(p3["recipes"])] == [1, 0, 1]
    assert p1["pack_id"] == p3["pack_id"] != p2["pack_id"]


def test_withdrawal_exports_tombstone(tmp_path):
    path, out = tmp_path / "research.sqlite", tmp_path / "pack.json"
    conn = make_store(path); seed = seed_version(conn); conn.close(); _publish(path, seed, "pub")
    first = _export(path, out)
    withdraw(path, intent_id="withdraw", version_id=seed["version_id"], by="human:Fixture Reviewer",
             authority="fixture-review", reason="retired")
    second = _export(path, out)
    assert len(second["recipes"]) == 0
    assert len(second["withdrawn"]) == 1
    assert second["withdrawn"][0]["recipe_version_id"] == seed["version_id"]
    assert second["generation"] == first["generation"] + 1


def test_slot_collision_omits_both(tmp_path):
    path, out = tmp_path / "research.sqlite", tmp_path / "pack.json"
    conn = make_store(path); a = seed_version(conn, "f-a"); b = seed_version(conn, "f-b"); conn.close()
    args_a, args_b = publish_args(a, "pub-a"), publish_args(b, "pub-b")
    args_b["template_name"] = args_a["template_name"]
    token = args_a["required"][0]; args_b["required"] = [token]
    args_b["ingredient_map"] = [{"index": i, "tokens": [token]} for i in range(len(b["ingredients"]))]
    publish(path, **args_a); publish(path, **args_b)
    pack = _export(path, out)
    assert len(pack["recipes"]) == 0
    assert [item["reason"] for item in pack["omitted"]] == ["applicability_slot_collision"] * 2


def test_exporter_crash_rows(tmp_path):
    for stage in ("before_state_commit", "after_state_commit", "after_temp_write", "after_rename"):
        case = tmp_path / stage; case.mkdir()
        path, out = case / "research.sqlite", case / "pack.json"
        conn = make_store(path); seed = seed_version(conn); conn.close(); _publish(path, seed, "pub")
        old = b'{"old":true}\n'; out.write_bytes(old)
        def crash(actual, wanted=stage):
            if actual == wanted:
                raise RuntimeError(wanted)
        with pytest.raises(RuntimeError, match=stage):
            _export(path, out, crash)
        conn = sqlite3.connect(path)
        state_rows = conn.execute("SELECT COUNT(*) FROM pack_state").fetchone()[0]
        conn.close()
        if stage == "before_state_commit":
            assert state_rows == 0 and out.read_bytes() == old
        elif stage in ("after_state_commit", "after_temp_write"):
            assert state_rows == 1 and out.read_bytes() == old
        else:
            assert state_rows == 1 and json.loads(out.read_text())["generation"] == 1
        retry = _export(path, out)
        assert retry["generation"] == 1
        assert json.loads(out.read_text())["pack_id"] == retry["pack_id"]


def test_export_requires_store_lock(tmp_path):
    path, out = tmp_path / "research.sqlite", tmp_path / "pack.json"
    conn = make_store(path); seed = seed_version(conn); conn.close(); _publish(path, seed, "pub")
    old = b"old"; out.write_bytes(old)
    held = StoreLock(path); assert held.acquire() is True
    try:
        with pytest.raises(ExportLockBusy):
            _export(path, out)
    finally:
        held.release()
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM pack_state").fetchone()[0] == 0
    conn.close(); assert out.read_bytes() == old


def test_export_refuses_database_output_alias_before_write(tmp_path):
    path = tmp_path / "research.sqlite"
    conn = make_store(path); seed_version(conn); conn.close()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ExportRefused, match="must not alias"):
        _export(path, path)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_omitted_reasons_exact_count(tmp_path):
    path, out = tmp_path / "research.sqlite", tmp_path / "pack.json"
    conn = make_store(path)
    published = [seed_version(conn, "f-a", source_url="https://fixture.example/pub-a"),
                 seed_version(conn, "f-b", source_url="https://fixture.example/pub-b")]
    retired = seed_version(conn, "f-c", source_url="https://fixture.example/retired")
    for i in range(10):
        seed_version(conn, "f-a", source_url="https://fixture.example/omitted-%02d" % i)
    conn.close()
    for i, seed in enumerate(published): _publish(path, seed, "pub-%d" % i)
    _publish(path, retired, "pub-retired")
    withdraw(path, intent_id="withdraw-retired", version_id=retired["version_id"],
             by="human:Fixture Reviewer", authority="fixture-review", reason="retired")
    pack = _export(path, out)
    assert len(pack["recipes"]) == 2
    assert len(pack["omitted"]) == 11
    assert len(pack["withdrawn"]) == 1
    assert set(item["reason"] for item in pack["omitted"]) <= set(OMITTED_REASONS)


def test_producer_contains_no_fixture_recipe_hardcoding():
    root = Path(__file__).resolve().parent.parent
    patterns = ["Fixture Harvest Bowl", "Fixture Garden Pasta", "Fixture Skillet Supper",
                "fixture harvest bowl", "fixture garden pasta", "fixture skillet supper"]
    for directory in (root / "research", root / "scripts"):
        for path in directory.rglob("*.py"):
            text = path.read_text()
            assert sum(text.count(pattern) for pattern in patterns) == 0
