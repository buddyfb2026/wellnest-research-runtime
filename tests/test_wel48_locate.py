import hashlib
import json
from pathlib import Path

from research.extract import extract
from research.recipe_extract import bind, proposal_for_located
from research.recipe_schema import cooking_content_usable
from tests.wel48_helpers import recipe_html

CORPUS = Path("/tmp/wel48-coordination/corpus/raw")


def test_entity_decoding_matches_corpus_counts():
    expected = {
        "cookieandkate_com_best_ratatouille_recipe.html": (13, 0, 0, 11),
        "cookieandkate_com_best_lentil_soup_recipe.html": (15, 1, 0, 7),
        "cookieandkate_com_vegetarian_chili_recipe.html": (19, 0, 0, 5),
        "cookieandkate_com_spicy_vegan_black_bean_soup.html": (13, 0, 0, 4),
    }
    for name, counts in expected.items():
        recipe = extract((CORPUS / name).read_text(errors="replace")).locators["recipes"][0]
        got = tuple(sum(u["correspondence"] == kind for u in recipe["ingredient_units"])
                    for kind in ("exact", "ambiguous", "unmatched")) + (len(recipe["step_units"]),)
        assert got == counts
        assert all("structured_raw" in u and "structured_decoded" in u for u in recipe["ingredient_units"])


def test_heading_tier_on_live_record():
    ex = extract((CORPUS / "www_loveandlemons_com_black_bean_soup.html").read_text(errors="replace"))
    recipe = ex.locators["recipes"][0]
    assert recipe["tier"] == "heading"
    assert (len(recipe["ingredient_units"]), len(recipe["step_units"])) == (15, 3)


def test_non_recipe_page_fails_closed():
    ex = extract("<html><head><title>Essay</title></head><body><p>" + "words " * 80 + "</p></body></html>")
    assert ex.locators["recipes"] == []


def test_extract_text_and_hash_are_unchanged_by_structured_entity_decoding():
    html = recipe_html(ingredient="&frac12; cup beans")
    ex = extract(html)
    assert ex.content_hash == hashlib.sha256(ex.text.encode()).hexdigest()
    unit = ex.locators["recipes"][0]["ingredient_units"][0]
    assert unit["structured_raw"] == "&frac12; cup beans" and unit["structured_decoded"] == "½ cup beans"


def test_evidence_without_ref_is_skipped(tmp_path):
    from research import db, recipes
    conn = db.connect(tmp_path / "db.sqlite"); db.migrate(conn)
    assert list(recipes.work_items(conn, "fixture:fixture")) == []


def _heading_card(*, ingredients, steps, after_steps):
    return ("<html><head><title>Portable Supper</title></head><body><article>"
            "<h1>Portable Supper</h1><h2>Ingredients</h2><ul>%s</ul>"
            "<h2>Directions</h2><ol>%s</ol>%s</article></body></html>" %
            ("".join("<li>%s</li>" % item for item in ingredients),
             "".join("<li>%s</li>" % item for item in steps), after_steps))


def test_heading_card_stops_before_tip_video_and_metadata_and_binds_yields():
    ingredients = ["1 cup beans", "2 tsp oil"]
    steps = ["Warm the beans.", "Fold in the oil."]
    html = _heading_card(
        ingredients=ingredients,
        steps=steps,
        after_steps=("<p><strong>Tip:</strong> Save a portion for lunch.</p>"
                     "<h2>Recipe Video</h2><table>"
                     "<tr><th>Prep Time</th><td><div>10 minutes</div></td></tr>"
                     "<tr><th>Cook Time</th><td><div>8 minutes</div></td></tr>"
                     "<tr><th>Yields</th><td><div>4 servings</div></td></tr>"
                     "</table><h2>Nutritional Facts</h2><p>Calories</p><p>275</p>"))
    ex = extract(html)
    recipe = ex.locators["recipes"][0]

    assert [ex.text[u["start"]:u["end"]] for u in recipe["ingredient_units"]] == ingredients
    assert [ex.text[u["start"]:u["end"]] for u in recipe["step_units"]] == steps
    assert ex.text[recipe["roles"]["servings"]["start"]:
                   recipe["roles"]["servings"]["end"]] == "4 servings"
    assert ex.text[recipe["roles"]["prep_time"]["start"]:
                   recipe["roles"]["prep_time"]["end"]] == "10 minutes"
    assert ex.text[recipe["roles"]["cook_time"]["start"]:
                   recipe["roles"]["cook_time"]["end"]] == "8 minutes"
    assert "total_time" not in recipe["roles"]

    evidence = {"id": 1, "url": "https://fixture.invalid/portable-supper", "version_no": 1,
                "content_hash": ex.content_hash, "title": ex.title, "attribution": "fixture",
                "fetched_at": "frozen", "published_at": None}
    manifest = {"id": 1, "locator_manifest_id": 1, "manifest_hash": "fixture",
                "revision_no": 1, "locator_version": ex.locators["locator_version"]}
    document, _, unknowns, _ = bind(
        evidence, ex.text, manifest, recipe, proposal_for_located(ex.text, recipe))
    assert document["servings"]["value"] == {"min": 4, "max": 4}
    assert document["times"]["total_time"]["support"] == "unknown"
    assert any(item["field"] == "total_time" and item["reason"] == "not_stated_by_source"
               for item in unknowns)


def test_heading_boundaries_do_not_match_words_inside_normal_steps():
    steps = ["Tip the pan toward you while stirring.",
             "Check nutrition preferences before seasoning.", "Cook"]
    ex = extract(_heading_card(
        ingredients=["1 cup beans"], steps=steps,
        after_steps="<h2>Notes</h2><p>Optional garnish.</p>"))
    recipe = ex.locators["recipes"][0]
    assert [ex.text[u["start"]:u["end"]] for u in recipe["step_units"]] == steps


def test_heading_card_stops_at_video_or_role_metadata_units():
    for after_steps in (
            "<h2>Recipe Video</h2><p>Transcript text.</p>",
            "<h2>Prep Time</h2><div>10 minutes</div><h2>Nutritional Facts</h2>"):
        ex = extract(_heading_card(
            ingredients=["1 cup beans"], steps=["Warm the beans."], after_steps=after_steps))
        recipe = ex.locators["recipes"][0]
        assert [ex.text[u["start"]:u["end"]] for u in recipe["step_units"]] == ["Warm the beans."]


def test_unknown_heading_boundary_is_not_silently_discarded():
    ex = extract(_heading_card(
        ingredients=["1 cup beans"], steps=["Warm the beans."],
        after_steps=("<h2>Chef Guidance</h2><p>Keep stirring.</p>"
                     "<h2>Notes</h2><p>Optional garnish.</p>")))
    recipe = ex.locators["recipes"][0]
    assert [ex.text[u["start"]:u["end"]] for u in recipe["step_units"]] == [
        "Warm the beans.", "Chef Guidance", "Keep stirring."]


def _bind_with_steps(ex, recipe, steps):
    evidence = {"id": 1, "url": "https://fixture.invalid/portable-supper", "version_no": 1,
                "content_hash": ex.content_hash, "title": ex.title, "attribution": "fixture",
                "fetched_at": "frozen", "published_at": None}
    manifest = {"id": 1, "locator_manifest_id": 1, "manifest_hash": "fixture",
                "revision_no": 1, "locator_version": ex.locators["locator_version"]}
    proposal = proposal_for_located(ex.text, recipe)
    proposal["steps"] = steps
    return bind(evidence, ex.text, manifest, recipe, proposal)


def test_ordered_interleaved_tip_cannot_hide_a_later_mandatory_step():
    source_steps = ["Warm the beans.", "Tip: Use a heavy pan.",
                    "Add the oil and fry for 5 minutes."]
    ex = extract(_heading_card(
        ingredients=["1 cup beans"], steps=source_steps,
        after_steps="<h2>Recipe Video</h2><h2>Nutritional Facts</h2>"))
    recipe = ex.locators["recipes"][0]
    assert [ex.text[u["start"]:u["end"]] for u in recipe["step_units"]] == source_steps

    document, completeness, unknowns, _ = _bind_with_steps(ex, recipe, [source_steps[0]])
    assert completeness == "incomplete" and cooking_content_usable(document) is False
    assert any(item["field"] == "steps" and item["reason"] == "located_units_not_fully_covered"
               for item in unknowns)


def test_terminal_ordered_tip_instruction_is_not_an_outside_annotation():
    source_steps = ["Warm the beans.", "Tip: Pour the hot beans into the serving bowl."]
    ex = extract(_heading_card(
        ingredients=["1 cup beans"], steps=source_steps,
        after_steps="<h2>Recipe Video</h2><h2>Nutritional Facts</h2>"))
    recipe = ex.locators["recipes"][0]
    assert [ex.text[u["start"]:u["end"]] for u in recipe["step_units"]] == source_steps

    document, completeness, unknowns, _ = _bind_with_steps(ex, recipe, [source_steps[0]])
    assert completeness == "incomplete" and cooking_content_usable(document) is False
    assert any(item["field"] == "steps" and item["reason"] == "located_units_not_fully_covered"
               for item in unknowns)


def test_tip_without_ordered_list_proof_is_retained_fail_closed():
    html = ("<html><head><title>Portable Supper</title></head><body><article>"
            "<h1>Portable Supper</h1><h2>Ingredients</h2><p>1 cup beans</p>"
            "<h2>Directions</h2><p>Warm the beans.</p>"
            "<p><strong>Tip:</strong> Keep stirring until glossy.</p>"
            "<h2>Recipe Video</h2></article></body></html>")
    ex = extract(html); recipe = ex.locators["recipes"][0]
    assert [ex.text[u["start"]:u["end"]] for u in recipe["step_units"]] == [
        "Warm the beans.", "Tip: Keep stirring until glossy."]
