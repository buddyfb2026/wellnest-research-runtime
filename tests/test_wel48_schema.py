import copy

from research import recipe_schema
from research.recipe_extract import bind, proposal_for_located
from tests.test_wel48_bind import _inputs
from tests.wel48_helpers import located, recipe_html


def test_portable_schema_hash_and_support_classes_are_frozen():
    assert recipe_schema.SCHEMA_HASH == "f4815575f716dcaaa6b040283253cb574aeee4a21920cf57867c65a0eb477aeb"
    assert recipe_schema.SUPPORT_CLASSES == {"source_literal", "source_normalized", "unknown"}


def test_portable_document_excludes_adaptations_and_validates():
    ex, loc, evidence, manifest, proposal = _inputs()
    document, _, _, _ = bind(evidence, ex.text, manifest, loc, proposal)
    assert "adaptations" not in document
    assert recipe_schema.validate(document) == []


def test_portable_worker_rows_are_unpublished(tmp_path):
    from research import db
    from tests.test_wel48_extract import run_recipe
    cfg, result = run_recipe(tmp_path)
    assert result.ok
    conn = db.connect(cfg.db_path)
    assert conn.execute("SELECT COUNT(*) FROM recipe_versions WHERE publishable != 0 OR state_set_by != 'worker'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM recipe_versions WHERE completeness='complete' AND state='approved'").fetchone()[0] == 0


def test_scalar_readings_path_and_conflict_keys_frozen():
    ex, loc, evidence, manifest, proposal = _inputs()
    document, _, _, _ = bind(evidence, ex.text, manifest, loc, proposal)
    assert "readings" not in document["servings"]
    assert set(document["servings"]["source"]) == {"value", "support", "span", "readings"}


def test_cooking_content_usable_rejects_unbound_or_stale_content():
    mutations = []
    for mutate in (
        lambda proposal, evidence: proposal["ingredients"].pop(0),
        lambda proposal, evidence: proposal["steps"].pop(0),
        lambda proposal, evidence: proposal["ingredients"].__setitem__(0, proposal["ingredients"][0][:-2]),
        lambda proposal, evidence: proposal["ingredients"].append("fabricated ingredient"),
        lambda proposal, evidence: evidence.__setitem__("content_hash", "stale"),
    ):
        ex, loc, evidence, manifest, proposal = _inputs()
        mutate(proposal, evidence)
        document, completeness, _, _ = bind(evidence, ex.text, manifest, loc, proposal)
        mutations.append((completeness, recipe_schema.cooking_content_usable(document)))
    ex, loc = located(recipe_html(step=["First stir the beans.", "Then simmer the beans."]))
    evidence = {"id": 1, "url": "https://fixture.example/recipe/", "version_no": 1,
                "content_hash": ex.content_hash, "title": ex.title, "attribution": "Fixture",
                "fetched_at": "t", "published_at": None}
    manifest = {"id": 1, "locator_manifest_id": 1, "manifest_hash": "a" * 64,
                "revision_no": 1, "locator_version": "wel48_locator_v1"}
    proposal = proposal_for_located(ex.text, loc); proposal["steps"].reverse()
    document, completeness, _, _ = bind(evidence, ex.text, manifest, loc, proposal)
    mutations.append((completeness, recipe_schema.cooking_content_usable(document)))
    assert mutations == [("incomplete", False)] * 6
