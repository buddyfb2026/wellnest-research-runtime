"""Real retained text regression; reconstructed proposals are NOT saved model output."""
from pathlib import Path

from research.recipe_locate import locate
from research.recipe_extract import _bind_units


def test_real_trout_footer_is_not_missing_cooking_steps():
    text = (Path(__file__).parents[1] / "eval/wel48/fixtures/baked-trout-20260921.txt").read_text()
    recipe = locate("", text, "Baked Trout")["recipes"][0]
    # These six source literals are also present in saved Qwen version 33.
    steps = text.split("Directions\n", 1)[1].split("\nRelated\n", 1)[0].splitlines()
    unknowns = []
    bound = _bind_units(text, "step", recipe["step_units"], steps, unknowns)
    assert len(recipe["step_units"]) == 6
    assert [s["value"] for s in bound] == steps
    assert unknowns == []


def test_related_word_inside_instruction_does_not_end_steps():
    text = "Soup\nIngredients\n1 cup water\nDirections\nRelated ingredients go in next.\nBoil.\nRelated\nOther soup\n"
    recipe = locate("", text, "Soup")["recipes"][0]
    assert [text[u["start"]:u["end"]] for u in recipe["step_units"]] == [
        "Related ingredients go in next.", "Boil."]
