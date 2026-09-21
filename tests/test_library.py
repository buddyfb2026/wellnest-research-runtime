from contextlib import contextmanager
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
import sqlite3
from threading import Thread
from pathlib import Path

import pytest

from research.library import (filter_recipes, make_handler, open_readonly, read_snapshot,
                              render_approved, render_detail, render_index, safe_external_url, serve)
from research.recipe_review import publish
from tests.wel52_helpers import make_store, publish_args, seed_version


def _db(tmp_path: Path, *, hostile: bool = False) -> Path:
    path = tmp_path / "research.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE recipes(id INTEGER PRIMARY KEY, source_url TEXT, recipe_key TEXT, recipe_slot TEXT,
          slot_disambiguated INTEGER, first_seen_evidence_id INTEGER, created_at TEXT);
        CREATE TABLE recipe_versions(id INTEGER PRIMARY KEY, recipe_id INTEGER, version_no INTEGER,
          content TEXT, completeness TEXT, state TEXT, state_reason TEXT, state_set_by TEXT, created_at TEXT);
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
    conn.execute("INSERT INTO recipe_versions VALUES(1,1,1,?,?,?,?,?,?)",
                 (json.dumps(content), "complete", "pending", None, "worker", "2026-09-20T10:00:00Z"))
    # Older version must never replace the current record in the library.
    conn.execute("INSERT INTO recipe_versions VALUES(2,1,0,?,?,?,?,?,?)",
                 (json.dumps({**content, "name": {"value": "Old name"}}), "incomplete", "pending", None,
                  "worker", "2026-09-19T10:00:00Z"))
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
    assert read_snapshot(path).recipes[0].status == "Extraction needs correction"
    conn = sqlite3.connect(path)
    conn.execute("UPDATE recipe_versions SET state='approved' WHERE id=1")
    conn.commit(); conn.close()
    assert read_snapshot(path).recipes[0].status == "Eligibility not evaluated"


@pytest.mark.parametrize(("state", "completeness", "reason", "set_by", "status", "note", "hidden"), [
    ("pending", "complete", None, "worker", "Ready for review", "awaiting review", False),
    ("pending", "incomplete", None, "worker", "Extraction needs correction", "needs correction", False),
    ("approved", "complete", None, "human:reviewer", "Eligibility not evaluated",
     "could not evaluate", True),
    ("rejected", "complete", '<script>unsafe reviewer text</script>', "human:reviewer", "Withdrawn",
     "Withdrawn by a reviewer", True),
    ("deferred", "complete", "source_embedded_instructions_flagged", "worker", "On hold",
     "instruction-like text", True),
    ("deferred", "failed", "inference_budget_exhausted: 10/10", "worker", "On hold",
     "processing budget", True),
    ("failed", "failed", "invalid_model_output", "worker", "Extraction failed", "usable recipe", True),
])
def test_every_persisted_recipe_state_has_truthful_bounded_projection(
        tmp_path, state, completeness, reason, set_by, status, note, hidden):
    path = _db(tmp_path)
    conn = sqlite3.connect(path)
    conn.execute("UPDATE recipe_versions SET state=?, completeness=?, state_reason=?, state_set_by=? WHERE id=1",
                 (state, completeness, reason, set_by))
    conn.commit(); conn.close()
    card = read_snapshot(path).recipes[0]
    assert (card.status, card.details_hidden) == (status, hidden)
    assert note in card.status_note
    rendered = render_detail(card)
    assert '<script>unsafe reviewer text</script>' not in rendered
    assert '<script>unsafe reviewer text</script>' not in render_index(read_snapshot(path), {})
    if hidden:
        assert "Recipe details withheld" in rendered
        assert "2 cups beans" not in rendered
        assert "Simmer gently" not in rendered
        assert not filter_recipes((card,), query="beans")


def test_unknown_state_fails_closed(tmp_path):
    path = _db(tmp_path)
    conn = sqlite3.connect(path)
    conn.execute("UPDATE recipe_versions SET state='new_future_state' WHERE id=1")
    conn.commit(); conn.close()
    card = read_snapshot(path).recipes[0]
    assert (card.status, card.details_hidden) == ("Status unavailable", True)


def test_missing_information_separates_source_omissions_from_extraction_corrections(tmp_path):
    path = _db(tmp_path)
    conn = sqlite3.connect(path)
    document = json.loads(conn.execute("SELECT content FROM recipe_versions WHERE id=1").fetchone()[0])
    document["unknown_fields"] = [
        {"field": "prep_time", "reason": "not_stated_by_source"},
        {"field": "ingredient[0]", "reason": "ingredient_correspondence_ambiguous"},
    ]
    conn.execute("UPDATE recipe_versions SET content=?, completeness='incomplete' WHERE id=1",
                 (json.dumps(document),))
    conn.commit(); conn.close()
    card = read_snapshot(path).recipes[0]
    assert card.status == "Extraction needs correction"
    assert card.source_missing == ("Prep time not confirmed by the source",)
    assert card.extraction_issues == ("One ingredient needs clarification",)
    assert len(filter_recipes((card,), status="Extraction needs correction")) == 1
    detail = render_detail(card)
    assert "Source doesn’t specify" in detail
    assert "does not by itself make the recipe unusable" in detail
    assert "Extraction needs correction" in detail


def test_source_only_omissions_use_secondary_status_consistently(tmp_path):
    path = _db(tmp_path)
    conn = sqlite3.connect(path)
    document = json.loads(conn.execute("SELECT content FROM recipe_versions WHERE id=1").fetchone()[0])
    document["unknown_fields"] = [
        {"field": "prep_time", "reason": "not_stated_by_source"},
    ]
    conn.execute("UPDATE recipe_versions SET content=?, completeness='incomplete' WHERE id=1",
                 (json.dumps(document),))
    conn.commit(); conn.close()

    snapshot = read_snapshot(path)
    card = snapshot.recipes[0]
    assert card.status == "Source doesn’t specify"
    assert snapshot.status_counts["Source doesn’t specify"] == 1
    assert snapshot.status_counts["Extraction needs correction"] == 0
    assert card.source_missing == ("Prep time not confirmed by the source",)
    assert card.extraction_issues == ()
    assert len(filter_recipes(snapshot.recipes, status="Source doesn’t specify")) == 1
    assert len(filter_recipes(snapshot.recipes, status="Extraction needs correction")) == 0

    index = render_index(snapshot, {})
    detail = render_detail(card)
    assert "Source doesn’t specify" in index
    assert "Extraction corrections" in index
    assert "Source doesn’t specify" in detail
    assert "Extraction needs correction" not in detail


def test_approved_view_reuses_existing_pack_eligibility_without_equating_optional_unknowns_to_unusable(tmp_path):
    path = tmp_path / "full.sqlite"
    conn = make_store(path)
    ready = seed_version(conn, "f-a", content_kind="live", source_url="https://fixture.example/ready")
    optional_unknown = seed_version(conn, "f-b", content_kind="live",
                                    source_url="https://fixture.example/optional-unknown")
    blocked = seed_version(conn, "f-c", content_kind="live", source_url="https://fixture.example/blocked")
    conn.execute("UPDATE recipe_versions SET state='approved', state_set_by='human:Fixture Reviewer' WHERE id=?",
                 (blocked["version_id"],))
    conn.close()
    publish(path, **publish_args(ready, "publish-ready"))
    publish(path, **publish_args(optional_unknown, "publish-optional"))

    snapshot = read_snapshot(path)
    by_version = {card.recipe_version_id: card for card in snapshot.recipes}
    assert by_version[ready["version_id"]].autopilot_status == "ready"
    optional_card = by_version[optional_unknown["version_id"]]
    assert optional_card.autopilot_status == "ready"
    assert optional_card.source_missing == ("Servings not confirmed by the source",)
    blocked_card = by_version[blocked["version_id"]]
    assert blocked_card.autopilot_status == "needs_correction"
    assert blocked_card.status == "Needs correction"
    assert blocked_card.details_hidden is True
    assert "approval record" in blocked_card.autopilot_note
    assert snapshot.autopilot_counts == {"ready": 2, "needs_correction": 1, "not_evaluated": 0}

    page = render_approved(snapshot)
    assert "What’s ready for family Autopilot" in page
    assert "Ready for family Autopilot" in page
    assert "Internal records needing correction" in page
    assert "Approved · Not ready for Autopilot" not in page
    assert "Eligibility not evaluated" in page
    assert "Ready for family Autopilot" in render_detail(optional_card)


def test_approved_view_labels_eligibility_not_evaluated_when_pack_contract_is_unavailable(tmp_path):
    path = _db(tmp_path)
    conn = sqlite3.connect(path)
    conn.execute("UPDATE recipe_versions SET state='approved', state_set_by='human:reviewer' WHERE id=1")
    conn.commit(); conn.close()
    snapshot = read_snapshot(path)
    card = snapshot.recipes[0]
    assert card.status == "Eligibility not evaluated"
    assert card.details_hidden is True
    assert card.autopilot_status == "not_evaluated"
    assert card.autopilot_label == "Eligibility not evaluated"
    assert "could not evaluate" in card.autopilot_note


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


def test_valid_non_object_run_summary_is_treated_as_no_counts(tmp_path):
    path = _db(tmp_path)
    conn = sqlite3.connect(path)
    conn.execute("UPDATE runs SET summary='[]'")
    conn.commit(); conn.close()
    assert read_snapshot(path).last_run_findings == "0 recipes added · 0 sources checked"


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


@contextmanager
def _fixture_server(db_path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(db_path))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _request(port, method="GET", target="/", host=None):
    conn = HTTPConnection("127.0.0.1", port, timeout=2)
    conn.request(method, target, headers={"Host": host or "127.0.0.1:%d" % port})
    response = conn.getresponse()
    body = response.read().decode("utf-8")
    result = response.status, response.getheader("Content-Type"), body
    conn.close()
    return result


def test_http_handler_post_is_read_only_and_asset_routes_are_whitelisted(tmp_path):
    with _fixture_server(_db(tmp_path)) as port:
        assert _request(port, method="POST")[0] == 405
        status, content_type, _ = _request(port, target="/assets/library.css")
        assert status == 200 and content_type.startswith("text/css")
        assert _request(port, target="/assets/../library.py")[0] == 404
        assert _request(port, target="/assets/not-bundled.css")[0] == 404


def test_http_handler_serves_separate_approved_view(tmp_path):
    path = _db(tmp_path)
    conn = sqlite3.connect(path)
    conn.execute("UPDATE recipe_versions SET state='approved', state_set_by='human:reviewer' WHERE id=1")
    conn.commit(); conn.close()
    with _fixture_server(path) as port:
        status, _, body = _request(port, target="/approved")
        assert status == 200
        assert "Approved &amp; Autopilot" in body
        assert "Eligibility not evaluated" in body


@pytest.mark.parametrize("host", ["evil.example", "127.0.0.1.evil.example", "127.0.0.1:1", "[::1]"])
def test_http_handler_rejects_unexpected_host_headers(tmp_path, host):
    with _fixture_server(_db(tmp_path)) as port:
        status, _, body = _request(port, host=host)
        assert status == 421
        assert "loopback requests" in body
        assert "Forest Soup" not in body


def test_http_handler_returns_generic_503_when_store_is_unavailable(tmp_path):
    with _fixture_server(tmp_path / "missing.sqlite") as port:
        status, _, body = _request(port)
        assert status == 503
        assert "could not be read safely" in body
        assert "missing.sqlite" not in body
