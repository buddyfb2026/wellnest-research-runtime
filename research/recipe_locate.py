"""Publisher-neutral recipe section location.

The locator runs while markup is available. It retains only the closed manifest contract; raw
markup is deliberately not persisted. Structured strings are HTML-decoded for matching while both
their raw and decoded readings remain in the manifest.
"""
import hashlib
import html as html_lib
import json
import re
from html.parser import HTMLParser
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .recipe_normalize import canonical

LOCATOR_VERSION = "wel48_locator_v7"
STEP_HEADINGS = ("instructions", "directions", "procedure")
EDIT_CONTROL_LINE = "[edit | edit source]"
MEDIAWIKI_END_HEADINGS = ("ingredients", *STEP_HEADINGS, "notes, tips, and variations")
MEDIAWIKI_FOOTER = re.compile(r'Retrieved from "https?://[^"\s]+"')
WIKIBOOKS_TITLE = re.compile(r"Cookbook:(.+) - Wikibooks, open books for an open world")
ROLE_LABELS = {
    "servings": ("yield", "yields", "servings", "serves"),
    "prep_time": ("prep time", "prep"),
    "cook_time": ("cook time", "cook"),
    "total_time": ("total time", "total"),
}
SECTION_ENDS = {
    "notes", "note", "contributor(s)", "nutrition", "nutrition facts", "nutritional facts", "recipe video",
    "prep time", "cook time", "total time", "yield", "yields", "servings", "serving size",
    "did you make this recipe?", "comments", "related",
}


def _is_section_end(literal: str) -> bool:
    return literal.casefold() in SECTION_ENDS


def _fold_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _plain_structured(value: Any) -> str:
    value = "" if value is None else str(value)
    return _fold_whitespace(re.sub(r"<[^>]+>", " ", html_lib.unescape(value)))


def _readings(value: Any) -> List[Tuple[str, str]]:
    values = value if isinstance(value, list) else ([] if value is None else [value])
    return [(str(v), _plain_structured(v)) for v in values if isinstance(v, (str, int, float))]


def _all_spans(text: str, needle: str) -> List[Dict[str, int]]:
    needle = re.sub(r"\s+", " ", needle).strip()
    if not needle:
        return []
    out: List[Dict[str, int]] = []
    start = 0
    folded, target = text.casefold(), needle.casefold()
    while True:
        at = folded.find(target, start)
        if at < 0:
            return out
        out.append({"start": at, "end": at + len(needle)})
        start = at + 1


def _first_span(text: str, needle: str, before: Optional[int] = None) -> Optional[Dict[str, int]]:
    spans = _all_spans(text, needle)
    if not spans:
        return None
    if before is None:
        return spans[0]
    candidates = [s for s in spans if s["start"] <= before]
    return candidates[-1] if candidates else spans[0]


def _walk_recipe_nodes(value: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(value, dict):
        kind = value.get("@type")
        if kind == "Recipe" or (isinstance(kind, list) and "Recipe" in kind):
            yield value
        for child in value.values():
            yield from _walk_recipe_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_recipe_nodes(child)


def _step_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        if isinstance(value.get("text"), str):
            yield value["text"]
        elif "itemListElement" in value:
            yield from _step_strings(value["itemListElement"])
    elif isinstance(value, list):
        for child in value:
            yield from _step_strings(child)


class _Markup(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.jsonld: List[str] = []
        self.microdata: Dict[str, List[str]] = {}
        self._json = False
        self._blob: List[str] = []
        self._itemprop: Optional[str] = None
        self._itemtext: List[str] = []
        self._depth = 0
        self._recipe_depth: Optional[int] = None
        self.heading_ordered_steps: Optional[List[str]] = None
        self._heading_tag: Optional[str] = None
        self._heading_text: List[str] = []
        self._directions_heading = False
        self._direction_ol_depth: Optional[int] = None
        self._direction_li_depth: Optional[int] = None
        self._direction_li_text: List[str] = []

    def handle_starttag(self, tag, attrs):
        self._depth += 1
        a = dict(attrs)
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._heading_tag, self._heading_text = tag, []
        if tag == "ol" and self._directions_heading and self._direction_ol_depth is None:
            self._direction_ol_depth = self._depth
            if self.heading_ordered_steps is None:
                self.heading_ordered_steps = []
        if tag == "li" and self._direction_ol_depth is not None:
            self._direction_li_depth, self._direction_li_text = self._depth, []
        if tag == "script" and (a.get("type") or "").lower() == "application/ld+json":
            self._json, self._blob = True, []
            return
        if "itemscope" in a and "schema.org/Recipe" in (a.get("itemtype") or ""):
            self._recipe_depth = self._depth
        prop = a.get("itemprop")
        if prop and self._recipe_depth is not None:
            self._itemprop, self._itemtext = prop, []
            value = a.get("content") or a.get("datetime")
            if value:
                self.microdata.setdefault(prop, []).append(value)

    def handle_data(self, data):
        if self._json:
            self._blob.append(data)
        elif self._itemprop:
            self._itemtext.append(data)
        if self._heading_tag is not None:
            self._heading_text.append(data)
        if self._direction_li_depth is not None:
            self._direction_li_text.append(data)

    def handle_entityref(self, name):
        value = html_lib.unescape("&%s;" % name)
        if self._heading_tag is not None:
            self._heading_text.append(value)
        if self._direction_li_depth is not None:
            self._direction_li_text.append(value)

    def handle_charref(self, name):
        value = html_lib.unescape("&#%s;" % name)
        if self._heading_tag is not None:
            self._heading_text.append(value)
        if self._direction_li_depth is not None:
            self._direction_li_text.append(value)

    def handle_endtag(self, tag):
        if tag == self._heading_tag:
            heading = _plain_structured("".join(self._heading_text)).casefold()
            if heading in STEP_HEADINGS:
                self._directions_heading = True
            elif heading == "ingredients" or heading in SECTION_ENDS:
                self._directions_heading = False
            self._heading_tag, self._heading_text = None, []
        if tag == "li" and self._direction_li_depth == self._depth:
            literal = _plain_structured("".join(self._direction_li_text))
            if literal:
                self.heading_ordered_steps.append(literal)  # type: ignore[union-attr]
            self._direction_li_depth, self._direction_li_text = None, []
        if tag == "ol" and self._direction_ol_depth == self._depth:
            self._direction_ol_depth = None
        if tag == "script" and self._json:
            self.jsonld.append("".join(self._blob))
            self._json = False
        if self._itemprop and self._itemtext:
            value = "".join(self._itemtext).strip()
            if value:
                self.microdata.setdefault(self._itemprop, []).append(value)
            self._itemprop, self._itemtext = None, []
        if self._recipe_depth == self._depth:
            self._recipe_depth = None
        self._depth = max(0, self._depth - 1)


def _role_span(text: str, labels: Tuple[str, ...], anchor: int) -> Optional[Dict[str, int]]:
    choices = []
    for label in labels:
        pattern = re.compile(r"(?im)^\s*" + re.escape(label) +
                             r"(?:\s*:\s*|\s+)(\d[^\n]{0,59})$")
        for match in pattern.finditer(text):
            value = match.group(1).strip()
            if value:
                start = match.start(1) + (len(match.group(1)) - len(match.group(1).lstrip()))
                choices.append((abs(match.start() - anchor), {"start": start, "end": start + len(value)}))
    return min(choices, key=lambda x: x[0])[1] if choices else None


def _manifest_recipe(node: Dict[str, Any], text: str, tier: str) -> Dict[str, Any]:
    ingredients = [x for x in (node.get("recipeIngredient") or []) if isinstance(x, str)]
    steps = list(_step_strings(node.get("recipeInstructions") or []))
    ingredient_units = []
    for raw in ingredients:
        decoded = _plain_structured(raw)
        matches = _all_spans(text, decoded)
        span = matches[0] if matches else {"start": -1, "end": -1}
        ingredient_units.append({**span, "structured_raw": raw, "structured_decoded": decoded,
                                 "correspondence": "exact" if len(matches) == 1 else
                                 ("ambiguous" if len(matches) > 1 else "unmatched")})
    step_units = []
    for raw in steps:
        decoded = _plain_structured(raw)
        matches = _all_spans(text, decoded)
        if len(matches) == 1:
            step_units.append({**matches[0], "structured_raw": raw, "structured_decoded": decoded})

    located = [u for u in ingredient_units + step_units if u["start"] >= 0]
    anchor = min((u["start"] for u in located), default=0)
    name_readings = _readings(node.get("name"))
    name_text = name_readings[0][1] if name_readings else ""
    name_span = _first_span(text, name_text, anchor)
    roles: Dict[str, Dict[str, Any]] = {}
    for role, source_key in (("servings", "recipeYield"), ("prep_time", "prepTime"),
                             ("cook_time", "cookTime"), ("total_time", "totalTime")):
        readings = _readings(node.get(source_key))
        span = _role_span(text, ROLE_LABELS[role], anchor)
        if readings or span:
            roles[role] = dict(span or {"start": -1, "end": -1},
                               structured_raw=[r for r, _ in readings],
                               structured_decoded=[d for _, d in readings])
    all_spans = located + ([name_span] if name_span else []) + [r for r in roles.values() if r["start"] >= 0]
    start = min((s["start"] for s in all_spans), default=0)
    end = max((s["end"] for s in all_spans), default=0)
    name = dict(name_span or {"start": -1, "end": -1})
    name.update({"structured_raw": name_readings[0][0] if name_readings else None,
                 "structured_decoded": name_text or None})
    return {"tier": tier, "bounds": {"start": start, "end": end}, "name": name, "roles": roles,
            "ingredient_units": ingredient_units, "step_units": step_units}


def _heading_recipe(text: str, title: Optional[str],
                    ordered_steps: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
    lines = list(re.finditer(r"(?m)^.*$", text))
    ing_i = next((i for i, m in enumerate(lines) if m.group().strip().casefold() == "ingredients"), None)
    step_i = next((i for i, m in enumerate(lines) if m.group().strip().casefold() in STEP_HEADINGS), None)
    if ing_i is None or step_i is None or step_i <= ing_i:
        return None
    ingredient_units = []
    for m in lines[ing_i + 1:step_i]:
        literal = m.group().strip().lstrip("▢☐ ").strip()
        if literal and literal != EDIT_CONTROL_LINE and not literal.casefold().startswith("cook mode"):
            at = m.start() + m.group().find(literal)
            ingredient_units.append({"start": at, "end": at + len(literal),
                                     "structured_raw": None, "structured_decoded": None,
                                     "correspondence": "exact"})
    step_units = []
    for line_i, m in enumerate(lines[step_i + 1:], start=step_i + 1):
        literal = m.group().strip()
        next_is_edit = (line_i + 1 < len(lines) and lines[line_i + 1].group().strip() == EDIT_CONTROL_LINE)
        if (_is_section_end(literal) or MEDIAWIKI_FOOTER.fullmatch(literal)
                or (next_is_edit and literal.casefold() in MEDIAWIKI_END_HEADINGS)):
            break
        if literal.casefold().startswith("tip:") and ordered_steps is not None:
            next_literal = next((line.group().strip() for line in lines[line_i + 1:]
                                 if line.group().strip()), None)
            if (_fold_whitespace(literal) not in ordered_steps
                    and next_literal and _is_section_end(next_literal)):
                break
        if literal and literal != EDIT_CONTROL_LINE:
            at = m.start() + m.group().find(literal)
            step_units.append({"start": at, "end": at + len(literal)})
    if not ingredient_units or not step_units:
        return None
    anchor = ingredient_units[0]["start"]
    name_text = title or ""
    wikibooks = WIKIBOOKS_TITLE.fullmatch(name_text)
    if wikibooks:
        name_text = wikibooks.group(1)
        matches = [m for m in lines if m.group() == name_text]
        name_span = {"start": matches[0].start(), "end": matches[0].end()} if len(matches) == 1 else None
    else:
        name_span = _first_span(text, name_text, anchor)
    roles = {}
    for role, labels in ROLE_LABELS.items():
        span = _role_span(text, labels, anchor)
        if span:
            roles[role] = {**span, "structured_raw": [], "structured_decoded": []}
    start = min([ingredient_units[0]["start"], step_units[0]["start"]] +
                [r["start"] for r in roles.values()] + ([name_span["start"]] if name_span else []))
    end = max([step_units[-1]["end"]] + [r["end"] for r in roles.values()])
    return {"tier": "heading", "bounds": {"start": start, "end": end},
            "name": {**(name_span or {"start": -1, "end": -1}), "structured_raw": None,
                     "structured_decoded": name_text or None}, "roles": roles,
            "ingredient_units": ingredient_units, "step_units": step_units}


def locate(html: str, text: str, title: Optional[str] = None,
           locator_version: str = LOCATOR_VERSION) -> Dict[str, Any]:
    parser = _Markup()
    try:
        parser.feed(html)
    except Exception:
        pass
    nodes = []
    for blob in parser.jsonld:
        try:
            nodes.extend(_walk_recipe_nodes(json.loads(blob)))
        except Exception:
            continue
    tier = "jsonld"
    if not nodes and parser.microdata.get("recipeIngredient"):
        tier = "microdata"
        nodes = [{"name": (parser.microdata.get("name") or [title])[0],
                  "recipeIngredient": parser.microdata.get("recipeIngredient", []),
                  "recipeInstructions": parser.microdata.get("recipeInstructions", []),
                  "recipeYield": parser.microdata.get("recipeYield"),
                  "prepTime": (parser.microdata.get("prepTime") or [None])[0],
                  "cookTime": (parser.microdata.get("cookTime") or [None])[0],
                  "totalTime": (parser.microdata.get("totalTime") or [None])[0]}]
    recipes = []
    rejected_structured = []
    for node in nodes:
        candidate = _manifest_recipe(node, text, tier)
        # A structured node is consumable only when all of its ingredient and step units can be
        # represented in the retained text. Otherwise continue down the tier chain; keeping a
        # half-locatable structured recipe would make deterministic coverage impossible.
        structured_steps = list(_step_strings(node.get("recipeInstructions") or []))
        if (all(u["correspondence"] != "unmatched" for u in candidate["ingredient_units"])
                and len(candidate["step_units"]) == len(structured_steps)):
            recipes.append(candidate)
        else:
            rejected_structured.append(candidate)
    if not recipes:
        heading = _heading_recipe(text, title, parser.heading_ordered_steps)
        # A heading fallback must not erase structured disagreement. When one structured recipe and
        # one visible recipe inventory have the same cardinality, carry each raw/decoded reading and
        # its correspondence onto the visible unit. P13 can then fail closed after restart while the
        # established heading-tier behavior remains available for the rendered recipe.
        if (heading and len(rejected_structured) == 1 and
                len(heading["ingredient_units"]) == len(rejected_structured[0]["ingredient_units"])):
            rejected = rejected_structured[0]
            for visible, structured in zip(heading["ingredient_units"], rejected["ingredient_units"]):
                visible["structured_raw"] = structured["structured_raw"]
                visible["structured_decoded"] = structured["structured_decoded"]
                visible_literal = text[visible["start"]:visible["end"]]
                visible["correspondence"] = ("exact" if structured["structured_decoded"]
                                              and canonical(structured["structured_decoded"])
                                              == canonical(visible_literal)
                                              else structured["correspondence"])
            for role, structured in rejected.get("roles", {}).items():
                if role in heading["roles"]:
                    heading["roles"][role]["structured_raw"] = structured["structured_raw"]
                    heading["roles"][role]["structured_decoded"] = structured["structured_decoded"]
        recipes = [heading] if heading else []
    # Slots are based only on the grounded name reading; duplicate names are ordinal-disambiguated.
    seen: Dict[str, int] = {}
    for recipe in recipes:
        n = recipe["name"]
        literal = text[n["start"]:n["end"]] if n["start"] >= 0 else ""
        base = "name:" + hashlib.sha256(re.sub(r"\s+", " ", literal).strip().casefold().encode()).hexdigest()[:16]
        ordinal = seen.get(base, 0)
        seen[base] = ordinal + 1
        recipe["slot"] = base + ("#%d" % (ordinal + 1) if ordinal else "") if literal else None
        recipe["slot_disambiguated"] = 1 if ordinal else 0
    return {"locator_version": locator_version, "recipes": recipes}
