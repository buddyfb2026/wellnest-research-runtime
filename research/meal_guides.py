"""WEL-42 reviewed preparation guides.

One registry, one shape. A guide is the unit a human approves: a whole coherent recipe a household
can actually execute for ONE existing meal template — not a pile of individually-approved tips.

Every displayed line is a reviewer-written concise paraphrase (`text`) bound to an `anchor` — a
sentence or complete ingredient-list line that must occur, verbatim and whole, in the stored evidence named by `source_url`. The
exporter re-checks every anchor against the hashed evidence text, so a guide whose source changed
or whose wording was never in the source simply stops exporting.

Nothing here republishes article prose: `text` is a short paraphrase of a factual instruction
(quantities, times and temperatures are facts), and the `anchor` is the short attributed quote that
supports it. Anchors are retained for review; the app does not render them.
"""
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

BURRITO_BOWL_URL = "https://www.budgetbytes.com/poor-mans-burrito-bowls/"


@dataclass(frozen=True)
class GuideItem:
    text: str          # reviewed paraphrase — what the household reads
    anchor: str        # verbatim sentence from the evidence that supports it
    source_url: str    # which evidence record must contain the anchor


@dataclass(frozen=True)
class MealGuide:
    """A whole reviewed guide. `template_name` + `required_ingredients` are the exact applicability;
    they can only narrow where the guide attaches and never influence meal selection.

    `introduced_ingredients` lists every ingredient the guide asks for that is NOT part of the meal
    template. The app refuses to attach a guide when a household rejects any of them, so exclusions
    cannot be satisfied by checking the template's own ingredients alone.
    """
    rule_id: str
    version: int
    template_name: str
    required_ingredients: Tuple[str, ...]
    introduced_ingredients: Tuple[str, ...]
    title: str
    summary: str
    equipment: Tuple[GuideItem, ...]
    extra_ingredients: Tuple[GuideItem, ...]
    steps: Tuple[GuideItem, ...]
    cautions: Tuple[GuideItem, ...]
    # Only set when a source actually states it. Left None rather than estimated.
    servings: Optional[str] = None
    total_time_minutes: Optional[int] = None

    @property
    def items(self) -> Tuple[GuideItem, ...]:
        return self.equipment + self.extra_ingredients + self.steps + self.cautions

    @property
    def source_urls(self) -> Tuple[str, ...]:
        seen = []
        for item in self.items:
            if item.source_url not in seen:
                seen.append(item.source_url)
        return tuple(seen)


_U = BURRITO_BOWL_URL

BEAN_RICE_BOWL_GUIDE = MealGuide(
    rule_id="bean_rice_bowl_prep_guide",
    version=2,
    template_name="Bean and rice bowls",
    required_ingredients=("rice", "beans"),
    # Everything the recipe needs beyond the template's own rice and beans.
    introduced_ingredients=(
        "salt", "cumin", "garlic powder", "salsa", "cheese", "green onions", "jalapeño",
    ),
    title="Cook it: rice and black bean bowls",
    summary="Start the rice first — everything else is finished before it is.",
    servings="6 bowls",
    total_time_minutes=25,
    equipment=(
        GuideItem("A medium sauce pot with a lid, for the rice",
                  "Place a lid on top and turn the heat on to high.", _U),
        GuideItem("A small sauce pot, for the beans",
                  "Add both cans of black beans (undrained) to a small sauce pot, along with the "
                  "cumin, and garlic powder.", _U),
    ),
    extra_ingredients=(
        GuideItem("Salt — ½ tsp",
                  "Add 2 cups long grain white rice, 1/2 tsp salt, and 3 cups water to a sauce pot.", _U),
        GuideItem("Ground cumin (½ tsp) and garlic powder (¼ tsp)",
                  "cans of black beans (undrained) to a sauce pot along with 1/2 tsp cumin and 1/4 "
                  "tsp garlic powder.", _U),
        GuideItem("Salsa — one 16-ounce jar; about ⅓ cup per bowl",
                  "▢ 1 16oz. jar salsa ($2.37)", _U),
        GuideItem("Shredded cheese — about ¼ cup per bowl; use one that melts",
                  "*Use your favorite type of meltable shredded cheese.", _U),
        GuideItem("Green onions, and a jalapeño if you want heat (optional)",
                  "Slice a bunch of green onions and one jalapeño (optional).", _U),
    ),
    steps=(
        GuideItem("Start the rice first — everything else will be done by the time it is.",
                  "Begin the rice first because everything else will be finished by the time the "
                  "rice is done cooking.", _U),
        GuideItem("Put 2 cups long-grain white rice, ½ tsp salt and 3 cups water in the medium pot.",
                  "Add 2 cups long grain white rice, 1/2 tsp salt, and 3 cups water to a sauce pot.", _U),
        GuideItem("Lid on, heat on high.",
                  "Place a lid on top and turn the heat on to high.", _U),
        GuideItem("Once it reaches a full boil, turn the heat to low and simmer 15 minutes.",
                  "Once it reaches a full boil, turn the heat down to low and let it simmer for 15 "
                  "minutes.", _U),
        GuideItem("Turn the heat off and let it sit, still covered, 5 more minutes.",
                  "After 15 minutes, turn the heat off and let it rest, with the lid in place, for "
                  "an additional five minutes.", _U),
        GuideItem("Fluff with a fork.", "Finally, fluff with a fork.", _U),
        GuideItem("While the rice cooks, heat two 15-ounce cans of black beans, undrained, in the small pot "
                  "with ½ tsp cumin and ¼ tsp garlic powder.",
                  "▢ 2 15oz. cans black beans ($0.98)", _U),
        GuideItem("Heat over medium, stirring often, until heated through.",
                  "Heat over medium, stirring often, until heated through.", _U),
        GuideItem("Slice the green onions, and the jalapeño if you're using it.",
                  "Slice a bunch of green onions and one jalapeño (optional).", _U),
        GuideItem("Build each bowl: about 1 cup rice, ½ cup beans, ⅓ cup salsa.",
                  "Add one cup cooked rice, 1/2 cup warm black beans, 1/3 cup salsa, and 1 oz.", _U),
        GuideItem("Top with about ¼ cup shredded cheese, sliced green onion and jalapeño.",
                  "(1/4 cup) shredded cheese, sliced green onion, and sliced jalapeño (if desired).", _U),
    ),
    cautions=(
        GuideItem("Don't drain the beans — they heat in their own liquid.",
                  "Add both cans of black beans (undrained) to a small sauce pot, along with the "
                  "cumin, and garlic powder.", _U),
        GuideItem("Keep the lid on while the rice rests off the heat.",
                  "After 15 minutes, turn the heat off and let it rest, with the lid in place, for "
                  "an additional five minutes.", _U),
        GuideItem("Use a cheese that melts.",
                  "*Use your favorite type of meltable shredded cheese.", _U),
    ),
)


# rule_id -> guide. A rule with no guide here can never reach a meal card.
MEAL_GUIDES: Dict[str, MealGuide] = {
    BEAN_RICE_BOWL_GUIDE.rule_id: BEAN_RICE_BOWL_GUIDE,
}
