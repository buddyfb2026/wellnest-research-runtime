from research.recipe_locate import locate
from research.recipe_extract import bind
from research.recipes import recipe_key
from tests.test_wel48_bind import _inputs


def test_unresolvable_slot_creates_no_identity():
    manifest = locate("<html><body><h2>Ingredients</h2><p>1 cup beans</p><h2>Instructions</h2>"
                      "<p>Stir beans.</p></body></html>", "Ingredients\n1 cup beans\nInstructions\nStir beans.")
    assert manifest["recipes"][0]["slot"] is None


def test_duplicate_name_disambiguates_and_records_it():
    node = ('{"@type":"Recipe","name":"Soup","recipeIngredient":["1 cup beans"],'
            '"recipeInstructions":[{"text":"Stir beans."}]}')
    html = "<script type='application/ld+json'>[%s,%s]</script>" % (node, node)
    text = "Soup\n1 cup beans\nStir beans."
    recipes = locate(html, text)["recipes"]
    assert recipes[0]["slot"].startswith("name:")
    assert recipes[1]["slot"].endswith("#2") and recipes[1]["slot_disambiguated"] == 1
    assert recipe_key("https://x/", recipes[0]["slot"]) != recipe_key("https://x/", recipes[1]["slot"])


def test_model_name_must_match_primary_recipe():
    ex, loc, evidence, manifest, proposal = _inputs()
    proposal["name"] = "Completely Different Dish"
    document, completeness, unknowns, _ = bind(evidence, ex.text, manifest, loc, proposal)
    assert completeness == "incomplete" and document["name"]["support"] == "unknown"
    assert any(item == {"field": "name", "reason": "name_not_primary_recipe"}
               for item in unknowns)
