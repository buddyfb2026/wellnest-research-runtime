"""Locator v5 heading boundaries for the two WEL-49 source layouts.

Fixtures are minimal reconstructions, not retained live pages. Recipe text is copied from
https://fossrecipes.com/recipes/orzo-chicken (recipes CC0 per https://fossrecipes.com/license.html)
and https://publicdomainrecipes.com/easy-chicken-and-rice-casserole/ (site states all recipes are
public domain; project under the Unlicense). Markup keeps only the relevant structure; the note text
and every footer identifier (contributor, donation codes, tags, navigation) are synthetic.
"""
from research.extract import extract
from research.recipe_extract import bind, proposal_for_located
from research.recipe_locate import LOCATOR_VERSION
from research.recipe_schema import cooking_content_usable

ORZO_INGREDIENTS = [
    "2 chicken breasts cut into bite-sized pieces", "1-2 tablespoons finely chopped fresh basil",
    "1 tsp onion powder", "1 medium zucchini, quartered (about 1 cup)", "1 red bell pepper, chopped",
    "1 cup uncooked orzo", "2 garlic cloves, minced", "14.5 oz crushed tomatoes (canned)",
    "3 tsp chicken bouillon powder", "1 tbsp vegetable oil", "2 cups water"]
ORZO_STEPS = [
    "Heat oil in a large pan (or pot) until shimmering",
    "Mix the chicken bouillon powder with water until dissolved.",
    "Toss chicken with basil and add to pot with onion powder and zucchini. Saute for about 4 minutes, "
    "then add bell pepper, garlic, and orzo and cook an additional 4 minutes.",
    "Add crushed tomato, bouillon powder and water mixture to pot and mix. Reduce heat to a simmer and "
    "cook, covered, for 10-15 minutes, stirring often so the orzo doesn’t burn, making sure to cover "
    "the pot after each stir. Add additional seasonings to taste, if desired."]
ORZO_OLD_EXTRA = ["Note", "Fixture note: this synthetic sentence follows the directions."]
ORZO_HTML = (
    "<html><head><title>One-pot Chicken and Orzo</title></head><body><div id='main'><section>"
    "<header class='main'><h1>One-pot Chicken and Orzo</h1></header>"
    "<h2 id='ingredients'>Ingredients</h2><ul>%s</ul>"
    "<h2 id='directions'>Directions</h2><ol>%s</ol>"
    "<h2 id='note'>Note</h2><p>%s</p></section></div>"
    "<div id='sidebar'><nav id='menu'><ul><li><a href='/'>Home</a></li></ul></nav></div></body></html>"
    % ("".join("<li>%s</li>" % i for i in ORZO_INGREDIENTS),
       "".join("<li><p>%s</p></li>" % s for s in ORZO_STEPS), ORZO_OLD_EXTRA[1]))

CASSEROLE_INGREDIENTS = [
    "1/2 cup Onion, chopped", "1/2 cup Celery, chopped", "2 Tbsp Butter or margarine",
    "2 cups Chicken, cooked and chopped", "1 3/4 cups Hot water", "2/3 cup Long Grain White Rice",
    "1 can (10 oz) Mushrooms with liquid", "1 cup Frozen Peas and Carrots", "1 tsp Dried Thyme and Rosemary"]
CASSEROLE_STEPS = [
    "In large fry pan, cook onion and celery in butter until soft.",
    "Stir in remaining ingredients.",
    "Bake in covered 8 cup baking dish in preheated (350F) oven for about 30 minutes or until rice is cooked."]
CASSEROLE_OLD_EXTRA = ["Contributor(s)", "Fixture Contributor", "Monero: FIXTURE-XMR-0000",
                       "Bitcoin: FIXTURE-BTC-0000", "Related", "FixtureTagOneFixtureTagTwo",
                       "Previous:", "Fixture Previous Recipe", "Next:", "Fixture Next Recipe"]
CASSEROLE_HTML = (
    "<html><head><title>Easy Chicken and Rice Casserole</title></head><body><main>"
    "<header><a href='/'>Fixture site header</a></header>"
    "<h1 id='tag_Easy Chicken and Rice Casserole'>Easy Chicken and Rice Casserole</h1><article>"
    "<ul><li>⏲️ Prep time: 5 min</li><li>\U0001f373 Cook time: 40 min</li>"
    "<li>\U0001f37d️ Servings: 4</li></ul>"
    "<h2 id='ingredients'>Ingredients</h2><ul>%s</ul>"
    "<h2 id='directions'>Directions</h2><ol>%s</ol>"
    "<h2>Contributor(s)</h2><ul><li><a href='#'>Fixture Contributor</a><ul id='donation'>"
    "<li>Monero: <code>FIXTURE-XMR-0000</code></li><li>Bitcoin: <code>FIXTURE-BTC-0000</code></li></ul></li></ul>"
    "<h2>Related</h2><p class='taglist'><span><a href='#'>FixtureTagOne</a></span>"
    "<span><a href='#'>FixtureTagTwo</a></span></p>"
    "<div id='nextprev'><div><a href='#'>Previous:<br>Fixture Previous Recipe</a></div>"
    "<div><a href='#'>Next:<br>Fixture Next Recipe</a></div></div>"
    "</article></main><footer><a href='/'>Fixture footer</a></footer></body></html>"
    % ("".join("<li>%s</li>" % i for i in CASSEROLE_INGREDIENTS),
       "".join("<li>%s</li>" % s for s in CASSEROLE_STEPS)))


def _bind(ex, recipe, steps, scalars=None):
    evidence = {"id": 1, "url": "https://fixture.invalid/wel49", "version_no": 1,
                "content_hash": ex.content_hash, "title": ex.title, "attribution": "fixture",
                "fetched_at": "frozen", "published_at": None}
    manifest = {"id": 1, "locator_manifest_id": 1, "manifest_hash": "fixture",
                "revision_no": 1, "locator_version": ex.locators["locator_version"]}
    proposal = proposal_for_located(ex.text, recipe)
    proposal.update(steps=steps, **(scalars or {}))
    return bind(evidence, ex.text, manifest, recipe, proposal)


def _located(html):
    ex = extract(html)
    assert ex.locators["locator_version"] == LOCATOR_VERSION == "wel48_locator_v5"
    [recipe] = ex.locators["recipes"]
    assert recipe["tier"] == "heading"
    units = lambda key: [ex.text[u["start"]:u["end"]] for u in recipe[key]]
    return ex, recipe, units("ingredient_units"), units("step_units")


def test_note_heading_ends_foss_directions():
    ex, recipe, ingredients, steps = _located(ORZO_HTML)
    assert ingredients == ORZO_INGREDIENTS and steps == ORZO_STEPS
    # v4 behavior on this layout: the two note lines followed the real steps as step units.
    assert all(extra in ex.text for extra in ORZO_OLD_EXTRA)
    doc, completeness, unknowns, conflicts = _bind(ex, recipe, ORZO_STEPS)
    assert [s["value"] for s in doc["steps"]] == ORZO_STEPS and cooking_content_usable(doc)
    assert not conflicts and not any(u["field"] in ("steps", "ingredients") for u in unknowns)
    # The source states no servings or times; they stay unknown and nothing is derived.
    assert sorted((u["field"], u["reason"]) for u in unknowns) == sorted(
        (f, "not_stated_by_source") for f in ("servings", "prep_time", "cook_time", "total_time"))
    assert completeness == "incomplete"


def test_contributor_heading_ends_pdr_directions_and_scalars_bind_as_stated():
    ex, recipe, ingredients, steps = _located(CASSEROLE_HTML)
    assert ingredients == CASSEROLE_INGREDIENTS and steps == CASSEROLE_STEPS
    joined = "\n".join(steps)
    assert not any(marker in joined for marker in ("Contributor", "Monero", "Bitcoin", "FIXTURE", "Previous", "Next:"))
    scalars = {"prep_minutes": {"value": 5, "quote": "Prep time: 5 min"},
               "cook_minutes": {"value": 40, "quote": "Cook time: 40 min"},
               "servings": {"value": 4, "quote": "Servings: 4"}}
    doc, completeness, unknowns, conflicts = _bind(ex, recipe, CASSEROLE_STEPS, scalars)
    assert [s["value"] for s in doc["steps"]] == CASSEROLE_STEPS and cooking_content_usable(doc)
    assert not conflicts
    assert [(u["field"], u["reason"]) for u in unknowns] == [("total_time", "not_stated_by_source")]
    assert (doc["times"]["prep_time"]["value"], doc["times"]["cook_time"]["value"]) == (5, 40)
    assert doc["servings"]["value"] == {"min": 4, "max": 4} and doc["times"]["total_time"]["value"] is None
    assert completeness == "incomplete"


def test_old_footer_and_note_units_are_not_accepted_as_steps():
    for html, real, extra in ((ORZO_HTML, ORZO_STEPS, ORZO_OLD_EXTRA),
                              (CASSEROLE_HTML, CASSEROLE_STEPS, CASSEROLE_OLD_EXTRA)):
        ex, recipe, ingredients, _ = _located(html)
        doc, completeness, unknowns, _ = _bind(ex, recipe, real + extra)
        # Real steps still bind in order; every old v4 extra is refused, none becomes a step.
        assert [s["value"] for s in doc["steps"]] == real
        refused = [(u["field"], u["reason"]) for u in unknowns if u["field"].startswith("step_returned")]
        assert refused == [("step_returned[%d]" % (len(real) + i), "not_a_whole_located_unit")
                           for i in range(len(extra))]
        assert completeness == "incomplete" and cooking_content_usable(doc) is False
        # Ingredient coverage and claims are unaffected by the step refusal.
        assert [i["source"]["value"] for i in doc["ingredients"]] == ingredients
        assert not any(u["field"].startswith("ingredient") for u in unknowns)
