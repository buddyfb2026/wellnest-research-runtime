"""Small, publisher-neutral normalizers for verified recipe literals."""
import re
import unicodedata
from fractions import Fraction
from typing import Any, Dict, Iterable, Optional, Tuple

_FRACTIONS = {"¼": Fraction(1, 4), "½": Fraction(1, 2), "¾": Fraction(3, 4),
              "⅓": Fraction(1, 3), "⅔": Fraction(2, 3), "⅛": Fraction(1, 8),
              "⅜": Fraction(3, 8), "⅝": Fraction(5, 8), "⅞": Fraction(7, 8)}
_UNITS = {
    "teaspoon": "tsp", "teaspoons": "tsp", "tsp": "tsp",
    "tablespoon": "tbsp", "tablespoons": "tbsp", "tbsp": "tbsp",
    "cup": "cup", "cups": "cup", "ounce": "oz", "ounces": "oz", "oz": "oz",
    "pound": "lb", "pounds": "lb", "lb": "lb", "lbs": "lb",
    "gram": "g", "grams": "g", "g": "g", "kilogram": "kg", "kilograms": "kg", "kg": "kg",
    "milliliter": "ml", "milliliters": "ml", "ml": "ml", "liter": "l", "liters": "l", "l": "l",
    "clove": "clove", "cloves": "clove", "can": "can", "cans": "can",
}


def _number(token: str) -> Optional[float]:
    token = token.strip()
    if token in _FRACTIONS:
        return float(_FRACTIONS[token])
    if token and token[-1:] in _FRACTIONS:
        whole = float(token[:-1] or 0)
        return whole + float(_FRACTIONS[token[-1]])
    try:
        return float(Fraction(token))
    except (ValueError, ZeroDivisionError):
        try:
            return float(token)
        except ValueError:
            return None


def quantity(literal: str) -> Optional[Dict[str, Any]]:
    clean = literal.strip().lstrip("▢☐ ")
    m = re.match(r"^(\d*[¼½¾⅓⅔⅛⅜⅝⅞]|\d+(?:\.\d+)?(?:\s+\d+/\d+)?|\d+/\d+)(?:\s*(?:-|–|to)\s*(\d*[¼½¾⅓⅔⅛⅜⅝⅞]|\d+(?:\.\d+)?|\d+/\d+))?\s*(?:\([^)]*\)\s*)?(\w+)?\b\s*(.*)$", clean, re.I)
    if not m:
        # A source may state an ingredient without a quantity; preserve identity but make amount unknown.
        return {"amount": None, "amount_max": None, "unit": None, "item": clean}
    low = _number(m.group(1).replace(" ", "+")) if " " not in m.group(1).strip() else sum(
        (_number(p) or 0) for p in m.group(1).split())
    high = _number(m.group(2)) if m.group(2) else None
    unit_token = (m.group(3) or "").casefold()
    unit = _UNITS.get(unit_token)
    item = m.group(4).strip() if unit else " ".join(x for x in (m.group(3), m.group(4)) if x).strip()
    return {"amount": low, "amount_max": high, "unit": unit, "item": item}


def duration_minutes(literal: str) -> Optional[int]:
    value = literal.strip()
    iso = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?", value, re.I)
    if iso:
        return int(iso.group(1) or 0) * 60 + int(iso.group(2) or 0)
    hours = re.search(r"(\d+)\s*(?:hours?|hrs?)", value, re.I)
    minutes = re.search(r"(\d+)\s*(?:minutes?|mins?)", value, re.I)
    if not hours and not minutes:
        return None
    return int(hours.group(1) if hours else 0) * 60 + int(minutes.group(1) if minutes else 0)


def servings(literal: str) -> Optional[Dict[str, int]]:
    nums = [int(x) for x in re.findall(r"\d+", literal)]
    if not nums:
        return None
    return {"min": nums[0], "max": nums[1] if len(nums) > 1 else nums[0]}


def semantic(role: str, literal: str) -> Any:
    if role in ("prep_time", "cook_time", "total_time"):
        return duration_minutes(literal)
    if role == "servings":
        return servings(literal)
    return re.sub(r"\s+", " ", literal).strip().casefold()


def canonical(literal: str) -> str:
    """Canonical identity used for names and structured/visible ingredient comparison."""
    return " ".join(re.sub(r"[^\w\s/.-]", " ", unicodedata.normalize("NFKC", literal).casefold()).split())


# Closed scalar grammar from the WEL-48 v4 amendment. These recognizers intentionally full-match:
# accepting less source prose is preferable to turning narration, negation, or nutrition into facts.
_N = r"\d{1,3}"
_MOD = r"(?:generous|large|big|hearty|ample|modest|small|smaller|moderate|more)"
_SUBJECT = r"(?:(?:(?:this|the)\s+)?recipe\s+)?"
_LABEL = r"(?:yields?|serves|servings)"
_TRAIL = r"\s+servings?\b"
_SEP = r"\s*:?\s*"
_END = r"\s*[.)!;,]?\s*$"


def _range(tag: str) -> str:
    return rf"(?P<n{tag}>{_N})(?:\s*(?:to|-|–|—)\s*(?P<m{tag}>{_N}))?"


def _narrative(tag: str) -> str:
    return (rf"(?P<n{tag}>{_N})(?:\s+{_MOD}){{0,2}}\s+or\s+"
            rf"(?P<m{tag}>{_N})(?:\s+{_MOD}){{0,2}}{_TRAIL}")


SERV_FORMS = (
    re.compile(rf"^{_SUBJECT}{_LABEL}{_SEP}{_range('a')}(?:{_TRAIL})?{_END}", re.I),
    re.compile(rf"^{_SUBJECT}{_LABEL}{_SEP}{_narrative('a')}{_END}", re.I),
    re.compile(rf"^\(?{_range('a')}{_TRAIL}{_END}", re.I),
)
SERV_BARE = re.compile(rf"^\s*{_range('a')}(?:{_TRAIL})?\s*$", re.I)
_HOURS = r"(?:hours?|hrs?)"
_MINUTES = r"(?:minutes?|mins?)"
_H = rf"(?P<h>\d{{1,2}})\s*{_HOURS}\b(?:\s+{_HOURS}\b)?"
_M = rf"(?P<mi>\d{{1,3}})\s*{_MINUTES}\b(?:\s+{_MINUTES}\b)?"
_M2 = _M.replace("?P<mi>", "?P<mi2>")
DURATION = rf"(?:{_H}(?:\s*{_M})?|{_M2}|PT(?:(?P<ih>\d{{1,2}})H)?(?:(?P<im>\d{{1,3}})M)?)"
TIME_LABELS = {"prep_time": "prep", "cook_time": "cook", "total_time": "total"}
TIME_FORMS = {
    role: re.compile(rf"^{label}(?:\s+time)?{_SEP}{DURATION}{_END}", re.I)
    for role, label in TIME_LABELS.items()
}
TIME_BARE = re.compile(rf"^\s*{DURATION}\s*$", re.I)


def _count_value(match: re.Match) -> Optional[Dict[str, int]]:
    low = int(match.group("na"))
    high = int(match.group("ma")) if match.group("ma") else low
    return {"min": low, "max": high} if 1 <= low <= high else None


def parse_servings_quote(literal: Any) -> Optional[Dict[str, int]]:
    if not isinstance(literal, str) or "\n" in literal:
        return None
    for form in SERV_FORMS:
        match = form.fullmatch(literal)
        if match:
            return _count_value(match)
    return None


def parse_servings_reading(literal: Any) -> Optional[Dict[str, int]]:
    if not isinstance(literal, str):
        return None
    match = SERV_BARE.fullmatch(literal)
    return _count_value(match) if match else None


def _duration_value(match: re.Match) -> Optional[int]:
    if match.group("ih") is not None or match.group("im") is not None:
        return int(match.group("ih") or 0) * 60 + int(match.group("im") or 0)
    minutes = match.group("mi") or match.group("mi2")
    if match.group("h") is None and minutes is None:
        return None
    return int(match.group("h") or 0) * 60 + int(minutes or 0)


def parse_time_quote(role: str, literal: Any) -> Optional[int]:
    if role not in TIME_FORMS or not isinstance(literal, str) or "\n" in literal:
        return None
    match = TIME_FORMS[role].fullmatch(literal)
    return _duration_value(match) if match else None


def parse_time_reading(literal: Any) -> Optional[int]:
    if not isinstance(literal, str):
        return None
    match = TIME_BARE.fullmatch(literal)
    return _duration_value(match) if match else None


def typed_value(role: str, value: Any) -> Any:
    def is_int(item: Any) -> bool:
        return isinstance(item, int) and not isinstance(item, bool)

    if role == "servings":
        if is_int(value):
            return {"min": value, "max": value}
        if (isinstance(value, dict) and set(value) == {"min", "max"}
                and is_int(value["min"]) and is_int(value["max"])):
            return {"min": value["min"], "max": value["max"]}
        return None
    return value if is_int(value) else None


def servings_compatible(values: Iterable[Dict[str, int]]) -> Tuple[bool, Optional[Dict[str, int]]]:
    values = list(values)
    if not values:
        return False, None
    ranges = [value for value in values if value["min"] != value["max"]]
    counts = [value for value in values if value["min"] == value["max"]]
    if len({(value["min"], value["max"]) for value in ranges}) > 1:
        return False, None
    if ranges:
        selected = ranges[0]
        return (all(selected["min"] <= count["min"] <= selected["max"] for count in counts),
                selected)
    return all(count == counts[0] for count in counts[1:]), counts[0]
