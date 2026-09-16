from research.recipe_extract import bind, proposal_for_located
from tests.test_wel48_bind import _inputs
from tests.wel48_helpers import located, recipe_html


def test_intra_structured_yield_disagreement_fixture():
    ex, loc, evidence, manifest, proposal = _inputs()
    loc["roles"]["servings"]["structured_decoded"] = ["2", "4 servings"]
    _, completeness, unknowns, conflicts = bind(evidence, ex.text, manifest, loc, proposal)
    assert completeness == "incomplete"
    assert conflicts[0]["reason"] == "conflicting_source_values"


def test_ingredient_conflict_FIXTURE(capsys):
    html = recipe_html(ingredient="3 cups water").replace(
        '"recipeIngredient": ["3 cups water"]', '"recipeIngredient": ["2 cups water"]')
    ex, loc = located(html)
    evidence = {"id": 1, "url": "https://fixture.example/conflict/", "version_no": 1,
                "content_hash": ex.content_hash, "title": ex.title, "attribution": "Fixture",
                "fetched_at": "t", "published_at": None}
    manifest = {"id": 1, "locator_manifest_id": 1, "manifest_hash": "f" * 64,
                "revision_no": 1, "locator_version": "wel48_locator_v1"}
    document, completeness, unknowns, conflicts = bind(
        evidence, ex.text, manifest, loc, proposal_for_located(ex.text, loc))
    print("fixture F2: per-ingredient conflict through locator and binder")
    assert loc["ingredient_units"][0]["structured_decoded"] == "2 cups water"
    assert loc["ingredient_units"][0]["correspondence"] == "unmatched"
    assert completeness == "incomplete" and conflicts[0]["field"] == "ingredient[0]"
    assert conflicts[0]["reason"] == "conflicting_source_values"
    assert any(x["reason"] == "conflicting_source_values" for x in unknowns)
    assert document["ingredients"][0]["support"] == "unknown"
    assert "fixture" in capsys.readouterr().out


def test_punctuation_only_difference_is_not_a_conflict():
    ex, loc, evidence, manifest, proposal = _inputs()
    loc["ingredient_units"][0]["structured_decoded"] = "1 cup beans!"
    document, completeness, unknowns, conflicts = bind(evidence, ex.text, manifest, loc, proposal)
    assert completeness == "complete" and unknowns == []
    assert not any(item["field"].startswith("ingredient") for item in conflicts)
    assert document["ingredients"][0]["support"] == "source_normalized"


def test_structured_only_never_becomes_a_value():
    ex, loc, evidence, manifest, proposal = _inputs()
    loc["roles"]["prep_time"]["start"] = loc["roles"]["prep_time"]["end"] = -1
    proposal["prep_minutes"] = {"value": None, "quote": None}
    doc, completeness, unknowns, _ = bind(evidence, ex.text, manifest, loc, proposal)
    assert completeness == "incomplete" and doc["times"]["prep_time"]["support"] == "unknown"
    assert any(x["reason"] == "not_stated_by_model" for x in unknowns)


def test_count_within_explicit_range_is_compatible():
    ex, loc = located(recipe_html(recipe_yield="2 to 4 servings"))
    evidence = {"id": 1, "url": "https://fixture.example/recipe/", "version_no": 1,
                "content_hash": ex.content_hash, "title": ex.title, "attribution": "Fixture",
                "fetched_at": "t", "published_at": None}
    manifest = {"id": 1, "locator_manifest_id": 1, "manifest_hash": "a" * 64,
                "revision_no": 1, "locator_version": "wel48_locator_v1"}
    proposal = proposal_for_located(ex.text, loc)
    loc["roles"]["servings"]["structured_decoded"] = ["2", "2 to 4 servings"]
    proposal["servings"] = {"value": {"min": 2, "max": 4}, "quote": "Yield: 2 to 4 servings"}
    document, _, _, conflicts = bind(evidence, ex.text, manifest, loc, proposal)
    assert document["servings"]["value"] == {"min": 2, "max": 4}
    assert len(document["servings"]["source"]["readings"]) == 4
    assert conflicts == []


def test_disjoint_servings_readings_conflict():
    cases = [
        ("4 servings", "Serves 6", 6),
        ("4 servings", "Serves 6 to 8", {"min": 6, "max": 8}),
        ("4 to 6 servings", "Serves 5 to 7", {"min": 5, "max": 7}),
    ]
    for source_yield, quote, value in cases:
        ex, loc = located(recipe_html(recipe_yield=source_yield, extra=quote))
        evidence = {"id": 1, "url": "https://fixture.example/conflict/", "version_no": 1,
                    "content_hash": ex.content_hash, "title": ex.title, "attribution": "Fixture",
                    "fetched_at": "t", "published_at": None}
        manifest = {"id": 1, "locator_manifest_id": 1, "manifest_hash": "f" * 64,
                    "revision_no": 1, "locator_version": "wel48_locator_v1"}
        loc["bounds"]["end"] = len(ex.text)
        proposal = proposal_for_located(ex.text, loc)
        proposal["servings"] = {"value": value, "quote": quote}
        document, completeness, _, conflicts = bind(evidence, ex.text, manifest, loc, proposal)
        assert completeness == "incomplete" and document["servings"]["support"] == "unknown"
        conflict = next(item for item in conflicts if item["field"] == "servings")
        assert set(conflict) == {"field", "reason", "structured", "visible", "model_quote",
                                 "model_quote_span", "readings"}
        assert len(conflict["readings"]) == 3


def test_time_readings_must_agree():
    ex, loc, evidence, manifest, proposal = _inputs()
    loc["roles"]["prep_time"]["structured_decoded"] = ["PT20M"]
    document, completeness, _, conflicts = bind(evidence, ex.text, manifest, loc, proposal)
    assert completeness == "incomplete" and document["times"]["prep_time"]["support"] == "unknown"
    assert any(item["field"] == "prep_time" for item in conflicts)
