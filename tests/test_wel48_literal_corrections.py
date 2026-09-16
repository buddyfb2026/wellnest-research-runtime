"""Offline regressions from the retained, permitted September 16 recipe text.

No fetch or model call. The exact text/hash and fixed model-shaped proposal are
fixtures; production locate/bind/normalization are the subjects, not mocks.
"""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from research import recipe_normalize as n, recipes
from research.recipe_extract import bind
from research.recipe_locate import locate

FIXTURES = json.loads((Path(__file__).parent.parent / "eval/wel48/fixtures/operating-recipe-literals.json").read_text())


@pytest.mark.parametrize("literal,amount,maximum,unit,item", [
    ("1/2 cup Onion, chopped", 0.5, None, "cup", "Onion, chopped"),
    ("1/2 cup Celery, chopped", 0.5, None, "cup", "Celery, chopped"),
    ("2/3 cup Long Grain White Rice", 2/3, None, "cup", "Long Grain White Rice"),
    ("1 3/4 cups Hot water", 1.75, None, "cup", "Hot water"),
    ("1½ cups beans", 1.5, None, "cup", "beans"),
    ("½ cup beans", 0.5, None, "cup", "beans"),
    ("1 ½ cups beans", 1.5, None, "cup", "beans"),
    ("14.5 oz crushed tomatoes", 14.5, None, "oz", "crushed tomatoes"),
    ("2 chicken breasts", 2, None, None, "chicken breasts"),
    ("1 to 2 tablespoons oil", 1, 2, "tbsp", "oil"),
    ("1/2–3/4 cup rice", 0.5, 0.75, "cup", "rice"),
    ("1 1/2 to 1 3/4 cups rice", 1.5, 1.75, "cup", "rice"),
    ("½-¾ cup rice", 0.5, 0.75, "cup", "rice"),
])
def test_quantity_token_is_complete(literal, amount, maximum, unit, item):
    got = n.quantity(literal)
    assert got == {"amount": amount, "amount_max": maximum, "unit": unit, "item": item}


@pytest.mark.parametrize("literal", [
    "1/0 cup rice", "1 1/0 cups rice", "1/2/3 cup rice", "1//2 cup rice",
    "1/ cup rice", "1 1/ cups rice", "1-1/0 cups rice", "1/2-3/0 cup rice",
])
def test_malformed_quantity_is_not_a_whole_number_prefix(literal):
    assert n.quantity(literal) == {
        "amount": None, "amount_max": None, "unit": None, "item": literal,
    }


def test_icon_labels_preserve_the_closed_scalar_grammar():
    assert n.parse_time_quote("prep_time", "⏲️ Prep time: 5 min") == 5
    assert n.parse_time_quote("cook_time", "🍳 Cook time: 40 min") == 40
    assert n.parse_servings_quote("🍽️ Servings: 4") == {"min": 4, "max": 4}
    assert n.parse_time_quote("prep_time", "⏲ Prep time: 5 min") == 5
    for quote in ("🚫 Cook time: 40 min", "❌ Cook time: 40 min",
                  "🍳 Do not cook 40 min", "🍳 Cook time: not 40 min",
                  "🍳 Cook time: 40 min, not 30", "Cook 🍳 time: 40 min",
                  "🍳\nCook time: 40 min", "🍳🍳 Cook time: 40 min",
                  "🍳 40 min", "🍳 Nutrition: 40 min"):
        assert n.parse_time_quote("cook_time", quote) is None, quote
    assert n.parse_time_quote("total_time", "⏲️ Prep time: 5 min") is None
    for quote in ("🚫 Servings: 4", "🍽️ Not 4 servings", "🍽️ Servings: 4 calories",
                  "🍽️ I think it serves 4", "🍽️\nServings: 4", "🍽️ 4"):
        assert n.parse_servings_quote(quote) is None, quote


def inputs(index):
    fixture = FIXTURES[index]
    text = fixture["text"]
    assert hashlib.sha256(text.encode()).hexdigest() == fixture["content_hash"]
    # The captured text itself supplies heading-tier units; no fabricated HTML or
    # structured recipe values supply information that the page did not contain.
    manifest = locate("", text, fixture["proposal"]["name"])
    assert len(manifest["recipes"]) == 1
    loc = manifest["recipes"][0]
    evidence = {"id": index + 1, "url": fixture["url"], "version_no": 1,
                "content_hash": fixture["content_hash"], "title": fixture["proposal"]["name"],
                "attribution": fixture["attribution"], "fetched_at": "2026-09-16T19:49:48Z",
                "published_at": None}
    row = {"id": 1, "locator_manifest_id": 1, "manifest_hash": recipes.manifest_hash(manifest),
           "revision_no": 1, "locator_version": manifest["locator_version"]}
    return fixture, text, loc, evidence, row


def bound(index, proposal=None):
    fixture, text, loc, evidence, row = inputs(index)
    return bind(evidence, text, row, loc, proposal or copy.deepcopy(fixture["proposal"]))


def test_real_casserole_complete_text_and_stated_scalars_but_no_invented_total():
    document, completeness, unknowns, conflicts = bound(1)
    assert len(document["ingredients"]) == 9
    assert len(document["steps"]) == 3
    assert document["ingredients"][0]["value"] == {
        "amount": 0.5, "amount_max": None, "unit": "cup", "item": "Onion, chopped",
    }
    assert document["ingredients"][1]["value"]["amount"] == 0.5
    assert document["ingredients"][4]["value"]["amount"] == 1.75
    assert document["ingredients"][5]["value"]["amount"] == 2/3
    assert document["ingredients"][5]["value"]["item"] == "Long Grain White Rice"
    assert document["ingredients"][3]["source"]["value"] == "2 cups Chicken, cooked and chopped"
    assert document["servings"]["value"] == {"min": 4, "max": 4}
    assert document["times"]["prep_time"]["value"] == 5
    assert document["times"]["cook_time"]["value"] == 40
    assert document["times"]["total_time"]["value"] is None
    assert [(u["field"], u["reason"]) for u in unknowns] == [
        ("total_time", "not_stated_by_source")]
    assert completeness == "incomplete" and conflicts == []
    text = FIXTURES[1]["text"]
    for value in [x["source"] for x in document["ingredients"]] + document["steps"] + [
        document["servings"]["source"], document["times"]["prep_time"]["source"],
        document["times"]["cook_time"]["source"],
    ]:
        assert text[value["span"]["start"]:value["span"]["end"]] == value["value"]
    assert document["times"]["prep_time"]["source"]["value"] == "⏲️ Prep time: 5 min"


def test_real_orzo_preserves_complete_text_and_all_unstated_scalars():
    document, completeness, unknowns, conflicts = bound(0)
    assert len(document["ingredients"]) == 11
    assert len(document["steps"]) == 4
    assert document["servings"]["value"] is None
    assert all(t["value"] is None for t in document["times"].values())
    assert {u["field"] for u in unknowns} == {"servings", "prep_time", "cook_time", "total_time"}
    assert all(u["reason"] == "not_stated_by_source" for u in unknowns)
    assert completeness == "incomplete" and conflicts == []


def test_decorated_quotes_do_not_bypass_wrong_role_or_fabricated_value():
    proposal = copy.deepcopy(FIXTURES[1]["proposal"])
    proposal["total_minutes"] = proposal["prep_minutes"]
    document, _, unknowns, _ = bound(1, proposal)
    assert document["times"]["total_time"]["value"] is None
    assert any(u["field"] == "total_time" and u["reason"] == "scalar_expression_unrecognized" for u in unknowns)
    proposal = copy.deepcopy(FIXTURES[1]["proposal"])
    proposal["servings"]["value"] = 6
    document, _, unknowns, _ = bound(1, proposal)
    assert document["servings"]["value"] is None
    assert any(u["field"] == "servings" and u["reason"] == "value_not_supported_by_quote" for u in unknowns)


def test_normalization_revision_changes_work_identity_without_changing_recipe_identity():
    args = (10, "manifest", "slot", "ollama:test")
    assert recipes.extraction_key(*args) != recipes.extraction_key(*args, extractor_version="wel48_extractor_v3")
    assert recipes.extraction_key(*args) == recipes.extraction_key(*args)
