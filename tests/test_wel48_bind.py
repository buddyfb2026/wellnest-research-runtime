import copy
import json
from pathlib import Path

from research.recipe_extract import bind, proposal_for_located
from tests.wel48_helpers import located, recipe_html


def _inputs():
    ex, loc = located()
    evidence = {"id": 1, "url": "https://fixture.example/recipe/", "version_no": 1,
                "content_hash": ex.content_hash, "title": ex.title, "attribution": "Fixture",
                "fetched_at": "t", "published_at": None}
    manifest = {"id": 1, "locator_manifest_id": 1, "manifest_hash": "a" * 64,
                "revision_no": 1, "locator_version": "wel48_locator_v1"}
    return ex, loc, evidence, manifest, proposal_for_located(ex.text, loc)


def _inputs_for_html(html):
    ex, loc = located(html)
    evidence = {"id": 1, "url": "https://fixture.example/recipe/", "version_no": 1,
                "content_hash": ex.content_hash, "title": ex.title, "attribution": "Fixture",
                "fetched_at": "t", "published_at": None}
    manifest = {"id": 1, "locator_manifest_id": 1, "manifest_hash": "a" * 64,
                "revision_no": 1, "locator_version": "wel48_locator_v1"}
    return ex, loc, evidence, manifest, proposal_for_located(ex.text, loc)


def test_complete_binding_uses_only_verified_support():
    ex, loc, evidence, manifest, proposal = _inputs()
    document, completeness, unknowns, conflicts = bind(evidence, ex.text, manifest, loc, proposal)
    assert completeness == "complete" and unknowns == conflicts == []
    assert document["ingredients"][0]["support"] == "source_normalized"


def test_fabricated_span_is_demoted():
    ex, loc, evidence, manifest, proposal = _inputs()
    proposal["servings"] = {"value": 2, "quote": "never in source"}
    document, completeness, unknowns, _ = bind(evidence, ex.text, manifest, loc, proposal)
    assert completeness == "incomplete" and any(x["reason"] == "span_not_in_evidence" for x in unknowns)


def test_literal_outside_unit_is_not_a_whole_unit():
    ex, loc, evidence, manifest, proposal = _inputs()
    proposal["ingredients"][0] = proposal["ingredients"][0][:-6]
    _, completeness, unknowns, _ = bind(evidence, ex.text, manifest, loc, proposal)
    assert completeness == "incomplete" and any(x["reason"] == "not_a_whole_located_unit" for x in unknowns)


def test_span_outside_bounds_is_demoted():
    ex, loc = located(recipe_html(extra="Serves 2."))
    evidence = {"id": 1, "url": "https://fixture.example/recipe/", "version_no": 1,
                "content_hash": ex.content_hash, "title": ex.title, "attribution": "Fixture",
                "fetched_at": "t", "published_at": None}
    manifest = {"id": 1, "locator_manifest_id": 1, "manifest_hash": "a" * 64,
                "revision_no": 1, "locator_version": "wel48_locator_v1"}
    proposal = proposal_for_located(ex.text, loc)
    proposal["servings"] = {"value": 2, "quote": "Serves 2."}
    _, completeness, unknowns, _ = bind(evidence, ex.text, manifest, loc, proposal)
    assert completeness == "incomplete" and any(x["reason"] == "quote_outside_recipe_region" for x in unknowns)


def test_role_mismatch_rejects_bare_number():
    ex, loc, evidence, manifest, proposal = _inputs()
    proposal["servings"] = {"value": 1, "quote": "1 cup beans"}
    _, _, unknowns, _ = bind(evidence, ex.text, manifest, loc, proposal)
    assert any(x["reason"] == "scalar_expression_unrecognized" for x in unknowns)


def test_partial_unit_is_rejected():
    ex, loc, evidence, manifest, proposal = _inputs()
    proposal["ingredients"][0] = proposal["ingredients"][0][:-6]
    _, _, unknowns, _ = bind(evidence, ex.text, manifest, loc, proposal)
    assert any(x["reason"] == "not_a_whole_located_unit" for x in unknowns)


def test_omission_cannot_be_complete():
    ex, loc, evidence, manifest, proposal = _inputs(); proposal["ingredients"] = []
    _, completeness, unknowns, _ = bind(evidence, ex.text, manifest, loc, proposal)
    assert completeness == "incomplete" and any(x["reason"] == "located_units_not_fully_covered" for x in unknowns)


def test_step_order_must_be_source_derived():
    ex, loc = located(recipe_html(step=["First stir the beans.", "Then simmer the beans."]))
    evidence = {"id": 1, "url": "https://fixture.example/recipe/", "version_no": 1,
                "content_hash": ex.content_hash, "title": ex.title, "attribution": "Fixture",
                "fetched_at": "t", "published_at": None}
    manifest = {"id": 1, "locator_manifest_id": 1, "manifest_hash": "a" * 64,
                "revision_no": 1, "locator_version": "wel48_locator_v1"}
    loc["step_units"] = list(reversed(loc["step_units"]))
    proposal = proposal_for_located(ex.text, loc)
    _, completeness, unknowns, _ = bind(evidence, ex.text, manifest, loc, proposal)
    assert completeness == "incomplete" and any(x["reason"] == "step_order_not_source_derivable" for x in unknowns)


def test_incomplete_recipe_FIXTURE(capsys):
    fixture = json.loads(Path("eval/wel48/fixtures/materially-incomplete.json").read_text())
    html = recipe_html().replace('"recipeYield": "2 servings", ', '').replace(
        '<p>Yield: 2 servings</p>', '')
    ex, loc, evidence, manifest, proposal = _inputs_for_html(html)
    assert fixture["missing_role"] not in loc["roles"]
    document, completeness, unknowns, _ = bind(evidence, ex.text, manifest, loc, proposal)
    print("fixture F1: materially incomplete")
    assert completeness == "incomplete" and document["servings"]["support"] == "unknown"
    assert any(item["reason"] == "not_stated_by_source" for item in unknowns)
    assert "fixture" in capsys.readouterr().out


def test_manifest_mismatch_yields_unknown_not_containment():
    ex, loc, evidence, manifest, proposal = _inputs(); evidence["content_hash"] = "stale"
    _, completeness, unknowns, _ = bind(evidence, ex.text, manifest, loc, proposal)
    assert completeness == "incomplete"
    assert any(x["reason"] == "evidence_content_hash_mismatch" for x in unknowns)


def test_narrative_alternative_requires_bounded_modifiers():
    cases = [
        ("Serves 4 calories or 300 calories.", {"min": 4, "max": 300}),
        ("Yield: 4 cups or 6 ounces.", {"min": 4, "max": 6}),
        ("Serves 4 bowls or 6 cups servings", {"min": 4, "max": 6}),
        ("Yields 4 generous or 6 more modest", {"min": 4, "max": 6}),
        ("Serves 4 or 6", {"min": 4, "max": 6}),
    ]
    for quote, value in cases:
        for card_present in (True, False):
            ex, loc, evidence, manifest, proposal = _inputs_for_html(recipe_html(extra=quote))
            loc["bounds"]["end"] = len(ex.text)
            if not card_present:
                loc["roles"].pop("servings")
            proposal["servings"] = {"value": value, "quote": quote}
            _, completeness, unknowns, _ = bind(evidence, ex.text, manifest, loc, proposal)
            assert completeness == "incomplete"
            assert any(item["reason"] == "scalar_expression_unrecognized" for item in unknowns)


def test_scalar_quote_has_no_free_prefix_or_suffix():
    servings = [
        ("This recipe never serves 4.", 4), ("Not 4 servings", 4),
        ("The recipe yields quite a bit of soup (6 to 8 servings)", {"min": 6, "max": 8}),
        ("Makes 4 servings", 4), ("I think it serves 4", 4),
        ("Serves 4 (not really)", 4), ("Serves 4, not 6", {"min": 4, "max": 6}),
    ]
    for quote, value in servings:
        ex, loc, evidence, manifest, proposal = _inputs_for_html(recipe_html(extra=quote))
        loc["bounds"]["end"] = len(ex.text); loc["roles"].pop("servings")
        proposal["servings"] = {"value": value, "quote": quote}
        _, _, unknowns, _ = bind(evidence, ex.text, manifest, loc, proposal)
        assert any(item["reason"] == "scalar_expression_unrecognized" for item in unknowns)
    for role, model_key, quote, value in (
        ("cook_time", "cook_minutes", "Do not cook 5 minutes.", 5),
        ("prep_time", "prep_minutes", "Never prep 12 minutes.", 12),
        ("total_time", "total_minutes", "This does not total 15 minutes.", 15),
    ):
        ex, loc, evidence, manifest, proposal = _inputs_for_html(recipe_html(extra=quote))
        loc["bounds"]["end"] = len(ex.text); loc["roles"].pop(role)
        proposal[model_key] = {"value": value, "quote": quote}
        _, _, unknowns, _ = bind(evidence, ex.text, manifest, loc, proposal)
        assert any(item["field"] == role and item["reason"] == "scalar_expression_unrecognized"
                   for item in unknowns)


def test_fractional_or_boolean_model_value_is_rejected():
    for value in (2.0, 2.5, True, "2"):
        ex, loc, evidence, manifest, proposal = _inputs()
        proposal["servings"] = {"value": value, "quote": "Yield: 2 servings"}
        _, _, unknowns, _ = bind(evidence, ex.text, manifest, loc, proposal)
        assert any(item["reason"] == "value_type_unsupported" for item in unknowns)


def test_label_prefixed_role_quote_is_admitted():
    ex, loc, evidence, manifest, proposal = _inputs()
    role = loc["roles"]["prep_time"]
    loc["bounds"]["start"] = role["start"]
    proposal["prep_minutes"] = {"value": 5, "quote": "Prep Time: 5 minutes"}
    document, _, unknowns, _ = bind(evidence, ex.text, manifest, loc, proposal)
    assert document["times"]["prep_time"]["value"] == 5
    assert not any(item["field"] == "prep_time" for item in unknowns)


def test_wrong_role_quote_equal_number_is_unknown():
    ex, loc, evidence, manifest, proposal = _inputs_for_html(recipe_html(ingredient="6 oz. cheese"))
    proposal["servings"] = {"value": 6, "quote": "6 oz. cheese"}
    document, _, unknowns, _ = bind(evidence, ex.text, manifest, loc, proposal)
    assert document["servings"]["support"] == "unknown"
    assert any(item["reason"] == "scalar_expression_unrecognized" for item in unknowns)


def test_absent_located_role_requires_role_cue():
    cases = [
        ("servings", "servings", "Prep Time: 5 minutes", 5),
        ("servings", "servings", "1 cup beans", 1),
        ("total_time", "total_minutes", "15 minutes", 15),
    ]
    for role, model_key, quote, value in cases:
        ex, loc, evidence, manifest, proposal = _inputs_for_html(
            recipe_html(step="Stir the beans well. 15 minutes"))
        loc["roles"].pop(role)
        proposal[model_key] = {"value": value, "quote": quote}
        document, _, unknowns, _ = bind(evidence, ex.text, manifest, loc, proposal)
        target = document["servings"] if role == "servings" else document["times"][role]
        assert target["support"] == "unknown"
        assert any(item["field"] == role and item["reason"] == "scalar_expression_unrecognized"
                   for item in unknowns)
    ex, loc, evidence, manifest, proposal = _inputs()
    loc["roles"].pop("servings")
    proposal["servings"] = {"value": 2, "quote": "Yield: 2 servings"}
    document, _, _, _ = bind(evidence, ex.text, manifest, loc, proposal)
    assert document["servings"]["value"] == {"min": 2, "max": 2}
