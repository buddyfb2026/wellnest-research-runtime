from research import recipe_normalize as n


def test_generic_quantity_and_unit_grammar():
    assert n.quantity("1½ cups beans") == {"amount": 1.5, "amount_max": None, "unit": "cup", "item": "beans"}
    assert n.quantity("1 to 2 tablespoons oil") == {"amount": 1.0, "amount_max": 2.0, "unit": "tbsp", "item": "oil"}


def test_generic_duration_and_yield_grammar():
    assert n.duration_minutes("PT1H25M") == 85
    assert n.duration_minutes("1 hour 25 minutes") == 85
    assert n.servings("4 to 6 servings") == {"min": 4, "max": 6}


def test_unnormalizable_quantity():
    # Identity is retained and amount is explicitly unknown rather than invented.
    assert n.quantity("salt to taste") == {"amount": None, "amount_max": None, "unit": None,
                                           "item": "salt to taste"}


def test_subject_grammar_matches_binding_amendment_v5():
    accepted = ["Serves 4.", "Recipe serves 4.", "This recipe serves 4.",
                "The recipe serves 4."]
    rejected = ["This serves 4.", "The serves 4.",
                "This yields 4 generous or 6 more modest servings.", "A recipe serves 4.",
                "Recipe recipe serves 4.", "This the recipe serves 4."]
    assert [n.parse_servings_quote(value) for value in accepted] == [{"min": 4, "max": 4}] * 4
    assert [n.parse_servings_quote(value) for value in rejected] == [None] * 6


def test_scalar_grammar_rejects_narration_negation_and_unrelated_numbers():
    rejected_servings = [
        "Serves 4 calories or 300 calories.", "Yield: 4 cups or 6 ounces.",
        "This recipe never serves 4.", "Makes 4 servings", "I think it serves 4",
        "Serves 4 (not really)", "Serves 4, not 6", "6 oz.", "Serving: 1",
        "Yield: 4 cups", "Serves 4 people", "Serves 6 to 4", "Serves 0", "yield: 1000",
    ]
    assert [n.parse_servings_quote(value) for value in rejected_servings] == [None] * len(rejected_servings)
    assert n.parse_servings_quote("Recipe yields 4 generous or 6 more modest servings.") == {
        "min": 4, "max": 6}
    assert n.parse_time_quote("cook_time", "Do not cook 5 minutes.") is None
    assert n.parse_time_quote("cook_time", "Cook Time: 45 mins") == 45


def test_duration_domain_boundaries():
    cases = [("99 hours", 5940), ("100 hours", None), ("999 minutes", 999),
             ("1000 minutes", None), ("PT99H", 5940), ("PT100H", None),
             ("PT999M", 999), ("PT1000M", None), ("PT", None)]
    assert [n.parse_time_reading(value) for value, _ in cases] == [want for _, want in cases]


def test_typed_values_are_fail_closed():
    for value in (6.9, 6.0, True, "6", {"min": 4}, {"min": 4.0, "max": 6}):
        assert n.typed_value("servings", value) is None
