import json
import sqlite3

import pytest

from research import db, worker
from research.model import ModelClient
from research.recipe_extract import proposal_for_located
from research import recipes
from tests.conftest import entry, good_proposal, make_transport, write_allowlist
from tests.test_wel48_extract import HTML_HEADERS, URL
from tests.wel48_helpers import recipe_html


def _setup(tmp_path, enabled=True, budget=10, post=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    html = recipe_html(); from research.extract import extract
    ex = extract(html)
    def fixture(text, meta):
        return (proposal_for_located(ex.text, ex.locators["recipes"][0])
                if "recipe_extraction" in meta else good_proposal(text, meta))
    allowlist = write_allowlist(tmp_path, [entry(URL)])
    from research.config import Config
    cfg = Config(db_path=tmp_path / "db.sqlite", allowlist_path=allowlist, report_path=tmp_path / "r.md",
                 provider="fixture", recipe_extraction_enabled=enabled)
    model = ModelClient("fixture", budget, fixture_fn=fixture) if post is None else ModelClient(
        "ollama", budget, model="fixture-model", http_post=post)
    pages = {URL: (200, URL, HTML_HEADERS, html)}
    return cfg, pages, model, fixture


def _run(cfg, pages, model):
    return worker.run(cfg, transport=make_transport(pages), model=model, content_kind="fixture")


def _counters(conn):
    return tuple(conn.execute(
        "SELECT (SELECT COUNT(*) FROM evidence),(SELECT COUNT(*) FROM locator_manifests),"
        "(SELECT COUNT(*) FROM evidence_current_manifest),(SELECT COUNT(*) FROM inference_calls),"
        "(SELECT COUNT(*) FROM recipe_versions)"
    ).fetchone())


class SimulatedCrash(BaseException):
    pass


def _raise_at(target):
    def hook(point):
        if point == target:
            raise SimulatedCrash(point)
    return hook


def test_identical_replay_inserts_nothing(tmp_path):
    cfg, pages, model, fixture = _setup(tmp_path)
    assert _run(cfg, pages, model).ok
    before = db.connect(cfg.db_path).execute("SELECT COUNT(*) FROM recipe_versions").fetchone()[0]
    result = _run(cfg, pages, ModelClient("fixture", 10, fixture_fn=fixture))
    conn = db.connect(cfg.db_path)
    assert result.ok and conn.execute("SELECT COUNT(*) FROM recipe_versions").fetchone()[0] == before == 1
    assert conn.execute("SELECT COUNT(*) FROM inference_calls WHERE purpose='recipe_extraction'").fetchone()[0] == 1


def test_legacy_attempt_cannot_shadow_recipe_recovery(tmp_path):
    cfg, pages, model, fixture = _setup(tmp_path, enabled=False)
    _run(cfg, pages, model)
    cfg.recipe_extraction_enabled = True
    result = _run(cfg, pages, ModelClient("fixture", 10, fixture_fn=fixture))
    conn = db.connect(cfg.db_path)
    assert result.ok and conn.execute("SELECT COUNT(*) FROM recipe_versions").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM inference_calls WHERE purpose='recipe_extraction'").fetchone()[0] == 1


def test_restart_with_no_new_evidence_finds_recipe_work(tmp_path):
    cfg, pages, model, fixture = _setup(tmp_path, enabled=False)
    first = _run(cfg, pages, model); cfg.recipe_extraction_enabled = True
    second = _run(cfg, pages, ModelClient("fixture", 10, fixture_fn=fixture))
    assert first["evidence_new"] == 1 and second["evidence_existing"] == 1
    assert second["recipe_versions_new"] == 1


def test_ambiguous_is_not_replayed(tmp_path):
    def dropped(*args):
        raise TimeoutError("dropped")
    cfg, pages, model, _ = _setup(tmp_path, post=dropped)
    first = _run(cfg, pages, model)
    count = db.connect(cfg.db_path).execute("SELECT COUNT(*) FROM inference_calls WHERE purpose='recipe_extraction'").fetchone()[0]
    second = _run(cfg, pages, ModelClient("ollama", 10, model="fixture-model", http_post=dropped))
    conn = db.connect(cfg.db_path)
    assert first.ok and second.ok and count == 1
    assert conn.execute("SELECT COUNT(*) FROM inference_calls WHERE purpose='recipe_extraction'").fetchone()[0] == 1


def test_placeholder_is_replaced_in_place_not_duplicated(tmp_path):
    cfg, pages, model, fixture = _setup(tmp_path, budget=1)
    first = _run(cfg, pages, model); conn = db.connect(cfg.db_path)
    row = conn.execute("SELECT id,state_reason FROM recipe_versions").fetchone()
    assert first.ok and row["state_reason"].startswith("inference_budget_exhausted")
    second = _run(cfg, pages, ModelClient("fixture", 10, fixture_fn=fixture)); conn = db.connect(cfg.db_path)
    replaced = conn.execute("SELECT id,state_reason FROM recipe_versions").fetchone()
    assert second.ok and replaced["id"] == row["id"] and replaced["state_reason"] is None
    assert conn.execute("SELECT COUNT(*) FROM recipe_versions").fetchone()[0] == 1


def test_human_decision_beats_placeholder_replacement(tmp_path):
    cfg, pages, model, fixture = _setup(tmp_path, budget=1); _run(cfg, pages, model)
    conn = db.connect(cfg.db_path); row = conn.execute("SELECT id FROM recipe_versions").fetchone()
    conn.execute("UPDATE recipe_versions SET state_set_by='human:reviewer',state='deferred' WHERE id=?", (row["id"],))
    second = _run(cfg, pages, ModelClient("fixture", 10, fixture_fn=fixture))
    current = db.connect(cfg.db_path).execute("SELECT id,state_set_by FROM recipe_versions").fetchone()
    assert second.ok and tuple(current) == (row["id"], "human:reviewer")


def test_concurrent_version_insert_fails_closed(tmp_path):
    cfg, pages, model, _ = _setup(tmp_path); _run(cfg, pages, model)
    conn = db.connect(cfg.db_path); row = conn.execute("SELECT * FROM recipe_versions").fetchone()
    columns = [item[1] for item in conn.execute("PRAGMA table_info(recipe_versions)") if item[1] != "id"]
    values = [row[column] for column in columns]
    values[columns.index("extraction_key")] = "concurrent-distinct-key"
    with pytest.raises(sqlite3.IntegrityError, match=r"recipe_versions\.recipe_id, recipe_versions\.version_no"):
        conn.execute("INSERT INTO recipe_versions(%s) VALUES(%s)" %
                     (",".join(columns), ",".join("?" for _ in columns)), values)


def test_crash_c2_after_evidence_commit_recovers_without_duplicate(tmp_path):
    cfg, pages, model, fixture = _setup(tmp_path / "c2")
    with pytest.raises(SimulatedCrash):
        worker.run(cfg, transport=make_transport(pages), model=model, content_kind="fixture",
                   crash_hook=_raise_at("after_evidence_manifest_commit"))
    conn = db.connect(cfg.db_path)
    assert _counters(conn) == (1, 1, 1, 0, 0)
    assert _run(cfg, pages, ModelClient("fixture", 10, fixture_fn=fixture)).ok
    conn = db.connect(cfg.db_path)
    assert _counters(conn) == (1, 1, 1, 2, 1)


def test_crash_c3_reserved_attempt_settles_ambiguous_without_replay(tmp_path):
    cfg, pages, _, fixture = _setup(tmp_path / "c3")
    model = ModelClient("fixture", 10, fixture_fn=fixture,
                        crash_hook=_raise_at("after_reservation_before_send:recipe_extraction"))
    with pytest.raises(SimulatedCrash):
        _run(cfg, pages, model)
    conn = db.connect(cfg.db_path)
    assert _counters(conn) == (1, 1, 1, 2, 0)
    assert tuple(conn.execute("SELECT status FROM inference_calls WHERE purpose='recipe_extraction'").fetchone()) == ("reserved",)
    assert conn.execute("SELECT COUNT(*) FROM recipe_versions").fetchone()[0] == 0
    assert _run(cfg, pages, ModelClient("fixture", 10, fixture_fn=fixture)).ok
    conn = db.connect(cfg.db_path)
    assert conn.execute("SELECT status FROM inference_calls WHERE purpose='recipe_extraction'").fetchone()[0] == "ambiguous"
    assert conn.execute("SELECT COUNT(*) FROM inference_calls WHERE purpose='recipe_extraction'").fetchone()[0] == 1
    assert _counters(conn) == (1, 1, 1, 2, 1)


def test_crash_c5_ok_attempt_becomes_failed_version_without_second_call(tmp_path):
    cfg, pages, model, fixture = _setup(tmp_path / "c5")
    with pytest.raises(SimulatedCrash):
        worker.run(cfg, transport=make_transport(pages), model=model, content_kind="fixture",
                   crash_hook=_raise_at("after_response_before_version"))
    conn = db.connect(cfg.db_path)
    assert _counters(conn) == (1, 1, 1, 2, 0)
    assert conn.execute("SELECT status FROM inference_calls WHERE purpose='recipe_extraction'").fetchone()[0] == "ok"
    assert _run(cfg, pages, ModelClient("fixture", 10, fixture_fn=fixture)).ok
    conn = db.connect(cfg.db_path)
    assert conn.execute("SELECT COUNT(*) FROM inference_calls WHERE purpose='recipe_extraction'").fetchone()[0] == 1
    assert conn.execute("SELECT completeness FROM recipe_versions").fetchone()[0] == "failed"
    assert _counters(conn) == (1, 1, 1, 2, 1)


def test_crash_c6_after_version_commit_replay_is_noop(tmp_path):
    cfg, pages, model, fixture = _setup(tmp_path / "c6")
    with pytest.raises(SimulatedCrash):
        worker.run(cfg, transport=make_transport(pages), model=model, content_kind="fixture",
                   crash_hook=_raise_at("after_version_commit"))
    conn = db.connect(cfg.db_path)
    assert _counters(conn) == (1, 1, 1, 2, 1)
    assert _run(cfg, pages, ModelClient("fixture", 10, fixture_fn=fixture)).ok
    assert _counters(db.connect(cfg.db_path)) == (1, 1, 1, 2, 1)


def test_crash_c7_placeholder_recovery_keeps_same_row(tmp_path):
    cfg, pages, model, fixture = _setup(tmp_path / "c7", budget=1); _run(cfg, pages, model)
    conn = db.connect(cfg.db_path); placeholder = conn.execute("SELECT id FROM recipe_versions").fetchone()[0]
    crashing = ModelClient("fixture", 10, fixture_fn=fixture)
    with pytest.raises(SimulatedCrash):
        worker.run(cfg, transport=make_transport(pages), model=crashing, content_kind="fixture",
                   crash_hook=_raise_at("after_response_before_version"))
    assert _counters(db.connect(cfg.db_path)) == (1, 1, 1, 2, 1)
    assert _run(cfg, pages, ModelClient("fixture", 10, fixture_fn=fixture)).ok
    conn = db.connect(cfg.db_path)
    assert conn.execute("SELECT id FROM recipe_versions").fetchone()[0] == placeholder
    assert conn.execute("SELECT COUNT(*) FROM recipe_versions").fetchone()[0] == 1
    assert _counters(conn) == (1, 1, 1, 2, 1)


def test_crash_c4_after_send_before_response_settles_without_replay(tmp_path):
    sent = []
    def crash_after_send(url, payload, timeout):
        sent.append(payload)
        if len(sent) == 1:
            return {"response": json.dumps(good_proposal("", {}))}
        raise SimulatedCrash("after HTTP send before response")
    cfg, pages, _, _ = _setup(tmp_path / "c4", post=crash_after_send)
    with pytest.raises(SimulatedCrash):
        _run(cfg, pages, ModelClient("ollama", 10, model="fixture-model", http_post=crash_after_send))
    conn = db.connect(cfg.db_path)
    assert len(sent) == 2 and _counters(conn) == (1, 1, 1, 2, 0)
    def must_not_send(*args):
        raise AssertionError("reserved C4 attempt must not be replayed")
    assert _run(cfg, pages, ModelClient("ollama", 10, model="fixture-model", http_post=must_not_send)).ok
    conn = db.connect(cfg.db_path)
    assert _counters(conn) == (1, 1, 1, 2, 1)
    assert conn.execute("SELECT status FROM inference_calls WHERE purpose='recipe_extraction'").fetchone()[0] == "ambiguous"


def test_crash_c8_structured_revision_recovers_without_refetch_or_duplicate(tmp_path):
    cfg, pages, model, fixture = _setup(tmp_path / "c8")
    assert _run(cfg, pages, model).ok
    original = pages[URL][3]
    changed_html = original.replace('"recipeYield": "2 servings"',
                                    '"recipeYield": "3 servings"', 1)
    changed_pages = {URL: (200, URL, HTML_HEADERS, changed_html)}
    with pytest.raises(SimulatedCrash):
        worker.run(cfg, transport=make_transport(changed_pages),
                   model=ModelClient("fixture", 10, fixture_fn=fixture), content_kind="fixture",
                   crash_hook=_raise_at("after_evidence_manifest_commit"))
    conn = db.connect(cfg.db_path)
    assert _counters(conn) == (1, 2, 1, 2, 1)
    assert conn.execute("SELECT locator_manifest_id FROM evidence_current_manifest").fetchone()[0] == 2
    write_allowlist(tmp_path / "c8", [entry(URL, fetch=False)])
    recovered = _run(cfg, {}, ModelClient("fixture", 10, fixture_fn=fixture))
    assert recovered.ok and recovered["source_requests"] == 0
    assert _counters(db.connect(cfg.db_path)) == (1, 2, 1, 3, 2)


def test_crash_c9_revert_ref_resolves_original_without_call(tmp_path):
    cfg, pages, model, fixture = _setup(tmp_path / "c9")
    assert _run(cfg, pages, model).ok
    original = pages[URL][3]
    changed_html = original.replace('"recipeYield": "2 servings"',
                                    '"recipeYield": "3 servings"', 1)
    changed_pages = {URL: (200, URL, HTML_HEADERS, changed_html)}
    assert _run(cfg, changed_pages, ModelClient("fixture", 10, fixture_fn=fixture)).ok
    assert _counters(db.connect(cfg.db_path)) == (1, 2, 1, 3, 2)
    with pytest.raises(SimulatedCrash):
        worker.run(cfg, transport=make_transport(pages),
                   model=ModelClient("fixture", 10, fixture_fn=fixture), content_kind="fixture",
                   crash_hook=_raise_at("after_evidence_manifest_commit"))
    conn = db.connect(cfg.db_path)
    assert _counters(conn) == (1, 2, 1, 3, 2)
    assert conn.execute("SELECT locator_manifest_id FROM evidence_current_manifest").fetchone()[0] == 1
    write_allowlist(tmp_path / "c9", [entry(URL, fetch=False)])
    recovered = _run(cfg, {}, ModelClient("fixture", 10, fixture_fn=fixture))
    assert recovered.ok and recovered["source_requests"] == 0
    conn = db.connect(cfg.db_path)
    assert _counters(conn) == (1, 2, 1, 3, 2)
    recipe_id = conn.execute("SELECT id FROM recipes").fetchone()[0]
    assert recipes.resolve_current(conn, recipe_id)["version_no"] == 1


def test_prompt_schema_bump_does_not_rewrite_history(tmp_path):
    cfg, pages, model, fixture = _setup(tmp_path / "schema-bump")
    assert _run(cfg, pages, model).ok
    conn = db.connect(cfg.db_path)
    old = conn.execute("SELECT id,content,state,publishable FROM recipe_versions").fetchone()
    conn.execute("""UPDATE recipe_versions SET extraction_key=?, extractor_version=?,
                    prompt_schema_version=? WHERE id=?""",
                 ("legacy-key", "wel48_extractor_v1", "wel48_recipe_spans_v2", old["id"]))
    assert _run(cfg, pages, ModelClient("fixture", 10, fixture_fn=fixture)).ok
    conn = db.connect(cfg.db_path)
    rows = conn.execute("SELECT * FROM recipe_versions ORDER BY id").fetchall()
    assert len(rows) == 2
    assert (rows[0]["id"], rows[0]["content"], rows[0]["state"], rows[0]["publishable"]) == tuple(old)
    assert rows[0]["prompt_schema_version"] == "wel48_recipe_spans_v2"
    assert rows[1]["prompt_schema_version"] == recipes.PROMPT_SCHEMA_VERSION
