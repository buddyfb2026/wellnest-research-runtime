import json
import sqlite3
from pathlib import Path

import pytest

from research.library import (filter_recipes, open_readonly, read_snapshot, render_detail,
                              render_index, safe_external_url, serve)


def _db(tmp_path: Path, *, hostile: bool = False) -> Path:
    path = tmp_path / "research.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE recipes(id INTEGER PRIMARY KEY, source_url TEXT, recipe_key TEXT, recipe_slot TEXT,
          slot_disambiguated INTEGER, first_seen_evidence_id INTEGER, created_at TEXT);
        CREATE TABLE recipe_versions(id INTEGER PRIMARY KEY, recipe_id INTEGER, version_no INTEGER,
          content TEXT, completeness TEXT, state TEXT, created_at TEXT);
        CREATE TABLE runs(run_id TEXT PRIMARY KEY, started_at TEXT, finished_at TEXT, status TEXT, summary TEXT);
    """)
    title = '<script>alert("x")</script>' if hostile else "Forest Soup"
    url = "javascript:alert(1)" if hostile else "https://example.test/forest-soup"
    content = {
        "name": {"support": "source_literal", "value": title},
        "evidence": {"attribution": "Test Kitchen"},
        "servings": {"support": "source_normalized", "value": {"min": 4, "max": 4}},
        "times": {"total_time": {"support": "source_normalized", "value": 35}},
        "ingredients": [{"support": "source_normalized", "source": {"value": "2 cups beans"}}],
        "steps": [{"support": "source_literal", "value": "Simmer gently."}],
        "unknown_fields": [],
    }
    conn.execute("INSERT INTO recipes VALUES(1,?,?,?,?,?,?)", (url, "key", "slot", 0, 1, "2026-09-20T10:00:00Z"))
    conn.execute("INSERT INTO recipe_versions VALUES(1,1,1,?,?,?,?)",
                 (json.dumps(content), "complete", "pending", "2026-09-20T10:00:00Z"))
    # Older version must never replace the current record in the library.
    conn.execute("INSERT INTO recipe_versions VALUES(2,1,0,?,?,?,?)",
                 (json.dumps({**content, "name": {"value": "Old name"}}), "incomplete", "pending", "2026-09-19T10:00:00Z"))
    conn.execute("INSERT INTO runs VALUES(?,?,?,?,?)", ("run-1", "2026-09-20T10:00:00Z", "2026-09-20T10:01:00Z", "ok",
                                                        json.dumps({"recipe_versions_new": 1, "fetched_ok": 2})))
    conn.commit()
    conn.close()
    return path


def test_connection_is_uri_read_only_and_cannot_mutate(tmp_path):
    path = _db(tmp_path)
    conn = open_readonly(path)
    assert conn.execute("PRAGMA query_only").fetchone()[0] == 1
    with pytest.raises(sqlite3.OperationalError, match="readonly|read-only|not authorized"):
        conn.execute("UPDATE recipe_versions SET state='approved'")
    conn.close()
    assert sqlite3.connect(path).execute("SELECT state FROM recipe_versions WHERE id=1").fetchone()[0] == "pending"


def test_current_version_and_truthful_status_mapping(tmp_path):
    snapshot = read_snapshot(_db(tmp_path))
    assert snapshot.all_count == 1
    card = snapshot.recipes[0]
    assert card.title == "Forest Soup"
    assert card.status == "Ready for review"
    assert card.summary == "The source includes 1 source-backed ingredient, 1 instruction, 35 min total."
    assert snapshot.last_run_findings == "1 recipe added · 2 sources checked"


def test_incomplete_and_persisted_approved_states_map_without_inference(tmp_path):
    path = _db(tmp_path)
    conn = sqlite3.connect(path)
    conn.execute("UPDATE recipe_versions SET completeness='incomplete' WHERE id=1")
    conn.commit(); conn.close()
    assert read_snapshot(path).recipes[0].status == "Missing information"
    conn = sqlite3.connect(path)
    conn.execute("UPDATE recipe_versions SET state='approved' WHERE id=1")
    conn.commit(); conn.close()
    assert read_snapshot(path).recipes[0].status == "Approved"


def test_filtering_searches_actual_fields(tmp_path):
    recipes = read_snapshot(_db(tmp_path)).recipes
    assert len(filter_recipes(recipes, query="beans")) == 1
    assert len(filter_recipes(recipes, query="chicken")) == 0
    assert len(filter_recipes(recipes, source="Test Kitchen")) == 1
    assert len(filter_recipes(recipes, status="Approved")) == 0


def test_html_escapes_content_and_rejects_unsafe_source_links(tmp_path):
    snapshot = read_snapshot(_db(tmp_path, hostile=True))
    card = snapshot.recipes[0]
    assert card.source_url is None
    page = render_index(snapshot, {"q": '<img src=x onerror="bad">'})
    detail = render_detail(card)
    assert "<script>alert" not in page + detail
    assert "&lt;script&gt;alert" in page + detail
    assert "javascript:" not in detail
    assert "&lt;img src=x onerror=&quot;bad&quot;&gt;" in page


@pytest.mark.parametrize("value", ["file:///tmp/x", "javascript:alert(1)", "https://user:pass@example.test/x", "//example.test/x", "not a url"])
def test_only_safe_http_links(value):
    assert safe_external_url(value) is None


def test_missing_store_does_not_create_a_database(tmp_path):
    missing = tmp_path / "missing.sqlite"
    with pytest.raises(Exception):
        open_readonly(missing)
    assert not missing.exists()


def test_server_rejects_non_loopback_binding(tmp_path):
    with pytest.raises(ValueError, match="loopback"):
        serve(_db(tmp_path), host="0.0.0.0", port=0)
