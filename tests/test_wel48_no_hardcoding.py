import re
from pathlib import Path


def test_no_publisher_recipe_or_title_hardcoding_in_extraction_modules():
    modules = ["recipe_locate.py", "recipe_normalize.py", "recipe_schema.py", "recipes.py", "recipe_extract.py"]
    forbidden = re.compile(r"budgetbytes|cookieandkate|loveandlemons|ratatouille|black.bean.soup|vegetarian.chili", re.I)
    hits = [(name, forbidden.findall((Path("research") / name).read_text())) for name in modules]
    assert [(name, found) for name, found in hits if found] == []
