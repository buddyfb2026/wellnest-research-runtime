import copy
import json

from research import db, recipes
from research.recipe_extract import bind, proposal_for_located
from research.recipe_schema import cooking_content_usable
from tests.wel48_helpers import located


def _store(conn, ex, url="https://fixture.example/recipe/"):
    conn.execute("""INSERT INTO evidence(url,content_kind,content_hash,version_no,fetched_at,published_at_basis,
                  source_type,access_basis,excerpt,text_chars,injection_flags) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                 (url, "fixture", ex.content_hash, 1, "2026-09-15T00:00:00Z", "unknown", "publication",
                  "fixture", ex.excerpt, len(ex.text), "[]"))
    eid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute("INSERT INTO evidence_text VALUES(?,?)", (eid, ex.text))
    return eid


def test_repeat_observation_inserts_nothing(tmp_path):
    conn = db.connect(tmp_path / "d.sqlite"); db.migrate(conn); ex, _ = located(); eid = _store(conn, ex)
    one = recipes.attach_manifest(conn, eid, ex.locators, "t1")
    two = recipes.attach_manifest(conn, eid, ex.locators, "t2")
    assert one[1] is True and two[1] is False
    assert conn.execute("SELECT COUNT(*) FROM locator_manifests").fetchone()[0] == 1


def test_structured_change_makes_new_revision(tmp_path):
    conn = db.connect(tmp_path / "d.sqlite"); db.migrate(conn); ex, _ = located(); eid = _store(conn, ex)
    recipes.attach_manifest(conn, eid, ex.locators, "t1")
    changed = copy.deepcopy(ex.locators); changed["recipes"][0]["roles"]["servings"]["structured_raw"] = ["3"]
    recipes.attach_manifest(conn, eid, changed, "t2")
    assert [r[0] for r in conn.execute("SELECT revision_no FROM locator_manifests ORDER BY id")] == [1, 2]


def test_aba_resolves_to_a_without_duplicate_inference(tmp_path):
    from research.model import ModelClient
    from tests.conftest import make_transport
    from tests.test_wel48_extract import HTML_HEADERS, URL
    from tests.test_wel48_replay import _counters, _run, _setup

    cfg, pages, model, fixture = _setup(tmp_path)
    assert _run(cfg, pages, model).ok
    original = pages[URL][3]
    changed_html = original.replace('"recipeYield": "2 servings"',
                                    '"recipeYield": "3 servings"', 1)
    changed_pages = {URL: (200, URL, HTML_HEADERS, changed_html)}
    assert _run(cfg, changed_pages, ModelClient("fixture", 10, fixture_fn=fixture)).ok
    conn = db.connect(cfg.db_path)
    assert _counters(conn) == (1, 2, 1, 3, 2)
    recipe_calls_before = conn.execute(
        "SELECT COUNT(*) FROM inference_calls WHERE purpose='recipe_extraction'").fetchone()[0]
    assert _run(cfg, pages, ModelClient("fixture", 10, fixture_fn=fixture)).ok
    conn = db.connect(cfg.db_path)
    assert _counters(conn) == (1, 2, 1, 3, 2)
    assert conn.execute("SELECT locator_manifest_id FROM evidence_current_manifest").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM inference_calls WHERE purpose='recipe_extraction'").fetchone()[0] == recipe_calls_before == 2
    recipe_id = conn.execute("SELECT id FROM recipes").fetchone()[0]
    assert recipes.resolve_current(conn, recipe_id)["version_no"] == 1


def test_aba_current_recipe_resolution_returns_original_immutable_version(tmp_path):
    conn = db.connect(tmp_path / "d.sqlite"); db.migrate(conn); ex, loc = located(); eid = _store(conn, ex)
    a_id, _ = recipes.attach_manifest(conn, eid, ex.locators, "t1")
    a_hash = conn.execute("SELECT manifest_hash FROM locator_manifests WHERE id=?", (a_id,)).fetchone()[0]
    rid = recipes.ensure_recipe(conn, "https://fixture.example/recipe/", loc["slot"], eid)
    a_key = recipes.extraction_key(eid, a_hash, loc["slot"], "fixture:fixture")
    v1 = recipes.save_version(conn, rid, eid, a_id, a_hash, a_key, "fixture:fixture", {"v": "A"}, None,
                              "complete", [], [], "pending", None, 1)
    changed = copy.deepcopy(ex.locators); changed["recipes"][0]["roles"]["servings"]["structured_raw"] = ["3"]
    b_id, _ = recipes.attach_manifest(conn, eid, changed, "t2")
    b_hash = conn.execute("SELECT manifest_hash FROM locator_manifests WHERE id=?", (b_id,)).fetchone()[0]
    b_key = recipes.extraction_key(eid, b_hash, loc["slot"], "fixture:fixture")
    recipes.save_version(conn, rid, eid, b_id, b_hash, b_key, "fixture:fixture", {"v": "B"}, None,
                         "complete", [], [], "pending", None, 2)
    recipes.attach_manifest(conn, eid, ex.locators, "t3")
    assert recipes.resolve_current(conn, rid)["id"] == v1
    assert [r[0] for r in conn.execute("SELECT content FROM recipe_versions ORDER BY id")] == ['{"v":"A"}', '{"v":"B"}']


def test_locator_bump_without_recollection_is_a_noop(tmp_path, monkeypatch):
    from research.model import ModelClient
    from tests.conftest import entry, write_allowlist
    from tests.test_wel48_extract import URL
    from tests.test_wel48_replay import _run, _setup

    cfg, pages, model, fixture = _setup(tmp_path)
    first = _run(cfg, pages, model)
    assert first.ok and first["recipe_versions_new"] == 1
    conn = db.connect(cfg.db_path)
    before = tuple(conn.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                   for table in ("locator_manifests", "recipe_versions", "inference_calls"))
    assert before == (1, 1, 2)

    monkeypatch.setattr("research.recipe_locate.LOCATOR_VERSION", "wel48_locator_v5")
    write_allowlist(tmp_path, [entry(URL, fetch=False)])
    second = _run(cfg, {}, ModelClient("fixture", 10, fixture_fn=fixture))
    conn = db.connect(cfg.db_path)
    after = tuple(conn.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                  for table in ("locator_manifests", "recipe_versions", "inference_calls"))
    assert second.ok and second["source_requests"] == 0 and second["recipe_versions_new"] == 0
    assert after == before
    assert conn.execute("SELECT locator_version FROM locator_manifests").fetchone()[0] == "wel48_locator_v4"


def test_locator_bump_applies_on_next_collection(tmp_path, monkeypatch):
    from research.model import ModelClient
    from research import recipe_locate
    from tests.test_wel48_replay import _counters, _run, _setup

    cfg, pages, model, fixture = _setup(tmp_path)
    assert _run(cfg, pages, model).ok
    original_locate = recipe_locate.locate
    monkeypatch.setattr(recipe_locate, "locate",
                        lambda html, text, title=None: original_locate(
                            html, text, title, locator_version="wel48_locator_v5"))
    assert _run(cfg, pages, ModelClient("fixture", 10, fixture_fn=fixture)).ok
    conn = db.connect(cfg.db_path)
    assert _counters(conn) == (1, 2, 1, 3, 2)
    assert conn.execute("SELECT locator_version FROM locator_manifests ORDER BY id DESC").fetchone()[0] == "wel48_locator_v5"


def test_first_manifest_attaches_without_new_evidence_row(tmp_path):
    conn = db.connect(tmp_path / "d.sqlite"); db.migrate(conn); ex, _ = located(); eid = _store(conn, ex)
    recipes.attach_manifest(conn, eid, ex.locators, "t1")
    assert conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM evidence_current_manifest").fetchone()[0] == 1


def test_ambiguous_correspondence_is_incomplete():
    # R4 is the frozen live oracle for the safe false-incomplete limitation AL-8.
    from pathlib import Path
    from research.extract import extract
    ex = extract(Path("/tmp/wel48-coordination/corpus/raw/cookieandkate_com_best_lentil_soup_recipe.html").read_text(errors="replace"))
    r = ex.locators["recipes"][0]
    assert sum(x["correspondence"] == "ambiguous" for x in r["ingredient_units"]) == 1
    evidence = {"id": 1, "url": "https://cookieandkate.com/best-lentil-soup-recipe/",
                "version_no": 1, "content_hash": ex.content_hash, "title": ex.title,
                "attribution": "frozen", "fetched_at": "frozen", "published_at": ex.published_at}
    manifest = {"id": 1, "locator_manifest_id": 1, "manifest_hash": "frozen",
                "revision_no": 1, "locator_version": ex.locators["locator_version"]}
    document, completeness, unknowns, _ = bind(
        evidence, ex.text, manifest, r, proposal_for_located(ex.text, r))
    assert completeness == "incomplete"
    assert sum(item["reason"] == "ingredient_correspondence_ambiguous" for item in unknowns) == 1
    assert len(document["ingredients"]) == 16 and cooking_content_usable(document) is True


def test_locator_manifests_are_never_updated(tmp_path):
    conn = db.connect(tmp_path / "d.sqlite"); db.migrate(conn); ex, _ = located(); eid = _store(conn, ex)
    statements = []
    conn.set_trace_callback(statements.append)
    recipes.attach_manifest(conn, eid, ex.locators, "t1")
    changed = copy.deepcopy(ex.locators); changed["recipes"][0]["roles"]["servings"]["structured_raw"] = ["3"]
    recipes.attach_manifest(conn, eid, changed, "t2")
    recipes.attach_manifest(conn, eid, ex.locators, "t3")
    writes = [statement.upper() for statement in statements if "LOCATOR_MANIFESTS" in statement.upper()]
    assert sum(statement.startswith("UPDATE LOCATOR_MANIFESTS") for statement in writes) == 0
    assert sum(statement.startswith("DELETE FROM LOCATOR_MANIFESTS") for statement in writes) == 0
    assert sum(statement.startswith("INSERT INTO LOCATOR_MANIFESTS") for statement in writes) == 2
