import json

from research.extract import extract


def recipe_html(name="Test Soup", ingredient="1 cup beans", step="Stir the beans well.",
                recipe_yield="2 servings", extra=""):
    steps = step if isinstance(step, list) else [step]
    node = {"@context": "https://schema.org", "@type": "Recipe", "name": name,
            "recipeYield": recipe_yield, "prepTime": "PT5M", "cookTime": "PT10M",
            "totalTime": "PT15M", "recipeIngredient": [ingredient],
            "recipeInstructions": [{"@type": "HowToStep", "text": value} for value in steps]}
    return ("<html><head><title>%s</title><script type='application/ld+json'>%s</script></head>"
            "<body><article><h1>%s</h1><p>Prep Time: 5 minutes</p><p>Cook Time: 10 minutes</p>"
            "<p>Total Time: 15 minutes</p><p>Yield: %s</p><h2>Ingredients</h2><p>%s</p>"
            "<h2>Instructions</h2>%s<p>%s</p></article></body></html>" %
            (name, json.dumps(node), name, recipe_yield, ingredient,
             "".join("<p>%s</p>" % value for value in steps), extra or "context " * 40))


def located(html=None):
    html = html or recipe_html()
    ex = extract(html)
    return ex, ex.locators["recipes"][0]
