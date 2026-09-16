"""Portable WEL-48 recipe document contract and dependency-free validation."""
import hashlib
from typing import Any, Dict, List

from .recipes import canonical_json

RECIPE_SCHEMA_VERSION = "wel48_recipe_v1"
SUPPORT_CLASSES = {"source_literal", "source_normalized", "unknown"}
PORTABLE_SHAPE = {
    "schema_version": RECIPE_SCHEMA_VERSION,
    "required": ["identity", "name", "servings", "times", "ingredients", "steps", "provenance",
                 "evidence", "completeness", "unknown_fields", "conflicts"],
    "support_classes": sorted(SUPPORT_CLASSES),
    "adaptations_allowed": False,
}
SCHEMA_HASH = hashlib.sha256(canonical_json(PORTABLE_SHAPE).encode("utf-8")).hexdigest()


def validate(document: Dict[str, Any]) -> List[str]:
    errors = []
    if not isinstance(document, dict):
        return ["document_not_object"]
    if document.get("schema_version") != RECIPE_SCHEMA_VERSION:
        errors.append("unknown_recipe_schema_version")
    if "adaptations" in document:
        errors.append("adaptations_not_portable")
    for key in PORTABLE_SHAPE["required"]:
        if key not in document:
            errors.append("missing_%s" % key)
    def walk(value):
        if isinstance(value, dict):
            if "support" in value and value["support"] not in SUPPORT_CLASSES:
                errors.append("invalid_support_class:%s" % value["support"])
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(document)
    if document.get("completeness") not in ("complete", "incomplete", "failed"):
        errors.append("invalid_completeness")
    return errors


def cooking_content_usable(document: Dict[str, Any]) -> bool:
    """Whether the source-backed name, ingredients, and steps are usable despite scalar unknowns."""
    name = document.get("name") or {}
    ingredients = document.get("ingredients")
    steps = document.get("steps")
    if name.get("support") != "source_literal" or not ingredients or not steps:
        return False
    if any(item.get("support") == "unknown" for item in ingredients + steps if isinstance(item, dict)):
        return False
    scalar_fields = {"servings", "prep_time", "cook_time", "total_time"}
    if any(item.get("field") not in scalar_fields
           and item.get("reason") != "ingredient_correspondence_ambiguous"
           for item in document.get("unknown_fields", [])):
        return False
    return not any(str(conflict.get("field", "")).startswith("ingredient")
                   for conflict in document.get("conflicts", []))
