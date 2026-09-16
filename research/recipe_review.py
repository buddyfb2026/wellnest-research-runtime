"""Human publication boundary for WEL-52 recipe versions.

The worker never calls this module.  A publication is an explicit, idempotent
operator act recorded before a version can become exportable.
"""
import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

from . import db
from .fetch import now_iso
from .lock import StoreLock
from .recipes import canonical_json


class ReviewRefused(ValueError):
    pass


class ReviewLockBusy(RuntimeError):
    pass


def _json(value: Any) -> str:
    return canonical_json(value)


def _literal(item: Any) -> Optional[str]:
    if not isinstance(item, dict):
        return None
    if item.get("support") == "source_literal" and isinstance(item.get("value"), str):
        return item["value"]
    source = item.get("source")
    if (item.get("support") == "source_normalized" and isinstance(source, dict)
            and source.get("support") == "source_literal" and isinstance(source.get("value"), str)):
        return source["value"]
    return None


def _strings(values: Sequence[str], name: str, required: bool = False) -> List[str]:
    if not isinstance(values, (list, tuple)):
        raise ReviewRefused("%s must be a list" % name)
    result: List[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ReviewRefused("%s contains an empty or non-string value" % name)
        token = value.strip().lower()
        if token in result:
            raise ReviewRefused("%s contains a duplicate token" % name)
        result.append(token)
    if required and not result:
        raise ReviewRefused("%s must be non-empty" % name)
    return result


def _validate_publish(document: Dict[str, Any], by: str, authority: str, rights_basis: str,
                      template_name: str, required: Sequence[str], introduced: Sequence[str],
                      ingredient_map: Sequence[Dict[str, Any]],
                      equipment_needs: Sequence[Dict[str, Any]], equipment_reviewed: bool) -> Dict[str, Any]:
    if not by.startswith("human:") or not by[len("human:"):].strip():
        raise ReviewRefused("acted_by must name a human with the human: prefix")
    if not authority.strip():
        raise ReviewRefused("authority is required")
    if not rights_basis.strip():
        raise ReviewRefused("rights_basis is required")
    if not template_name.strip():
        raise ReviewRefused("template_name is required")
    if equipment_reviewed is not True:
        raise ReviewRefused("equipment_reviewed must be attested")
    required_values = _strings(required, "required_ingredients", required=True)
    introduced_values = _strings(introduced, "introduced_ingredients")
    if set(required_values) & set(introduced_values):
        raise ReviewRefused("required and introduced ingredients overlap")
    ingredients = document.get("ingredients")
    steps = document.get("steps")
    if not isinstance(ingredients, list) or not isinstance(steps, list):
        raise ReviewRefused("recipe document has no ingredient/step inventory")
    if not isinstance(ingredient_map, (list, tuple)):
        raise ReviewRefused("ingredient_map must be a list")
    seen: Dict[int, List[str]] = {}
    clean_map = []
    for item in ingredient_map:
        if not isinstance(item, dict) or not isinstance(item.get("index"), int):
            raise ReviewRefused("ingredient_map entry is malformed")
        index = item["index"]
        if index in seen:
            raise ReviewRefused("ingredient_map index is duplicated")
        tokens = _strings(item.get("tokens"), "ingredient_map tokens", required=True)
        seen[index] = tokens
        clean_map.append({"index": index, "tokens": tokens})
    if set(seen) != set(range(len(ingredients))):
        raise ReviewRefused("ingredient_map must cover every ingredient exactly once")
    mapped = {token for tokens in seen.values() for token in tokens}
    if mapped != set(required_values) | set(introduced_values):
        raise ReviewRefused("ingredient_map tokens must equal required plus introduced ingredients")
    literals = [literal for literal in
                [_literal(item) for item in ingredients + steps] if literal]
    if not isinstance(equipment_needs, (list, tuple)):
        raise ReviewRefused("equipment_needs must be a list")
    clean_equipment = []
    for item in equipment_needs:
        if not isinstance(item, dict):
            raise ReviewRefused("equipment need is malformed")
        text, anchor = item.get("text"), item.get("anchor")
        if not isinstance(text, str) or not text.strip() or not isinstance(anchor, str) or not anchor:
            raise ReviewRefused("equipment need requires text and anchor")
        if not any(anchor in literal for literal in literals):
            raise ReviewRefused("equipment anchor is not in a bound recipe literal")
        clean_equipment.append({"text": text.strip(), "anchor": anchor})
    return {"template_name": template_name.strip(), "required_ingredients": required_values,
            "introduced_ingredients": introduced_values, "ingredient_map": clean_map,
            "equipment_needs": clean_equipment}


def _existing_matches(row: sqlite3.Row, expected: Dict[str, Any]) -> bool:
    return all(row[key] == value for key, value in expected.items())


def review(db_path: Union[str, Path], *, action: str, intent_id: str, version_id: int,
           by: str, authority: str, rights_basis: Optional[str] = None,
           reason: Optional[str] = None, template_name: Optional[str] = None,
           required: Sequence[str] = (), introduced: Sequence[str] = (),
           ingredient_map: Sequence[Dict[str, Any]] = (),
           equipment_needs: Sequence[Dict[str, Any]] = (), equipment_reviewed: bool = False,
           crash_hook: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Record one publish/withdraw act. Same-intent replay is a read-only success."""
    if action not in ("publish", "withdraw"):
        raise ReviewRefused("action must be publish or withdraw")
    if not intent_id.strip():
        raise ReviewRefused("intent_id is required")
    if not by.startswith("human:") or not by[len("human:"):].strip():
        raise ReviewRefused("acted_by must name a human with the human: prefix")
    if not authority.strip():
        raise ReviewRefused("authority is required")
    lock = StoreLock(db_path)
    if not lock.acquire():
        raise ReviewLockBusy("research store is busy")
    conn: Optional[sqlite3.Connection] = None
    try:
        conn = db.connect(db_path)
        db.migrate(conn)
        version = conn.execute(
            """SELECT rv.*, r.recipe_key FROM recipe_versions rv
               JOIN recipes r ON r.id=rv.recipe_id WHERE rv.id=?""", (version_id,)
        ).fetchone()
        if version is None:
            raise ReviewRefused("recipe version does not exist")
        app = {"template_name": None, "required_ingredients": [], "introduced_ingredients": [],
               "ingredient_map": None, "equipment_needs": None}
        if action == "publish":
            try:
                document = json.loads(version["content"])
            except (TypeError, ValueError):
                raise ReviewRefused("recipe document is not valid JSON")
            app = _validate_publish(document, by, authority, rights_basis or "", template_name or "",
                                    required, introduced, ingredient_map, equipment_needs,
                                    equipment_reviewed)
        expected = {
            "recipe_version_id": int(version_id), "recipe_key": version["recipe_key"],
            "content_fingerprint": version["content_fingerprint"], "action": action,
            "acted_by": by, "authority": authority, "rights_basis": rights_basis if action == "publish" else None,
            "reason": reason, "template_name": app["template_name"],
            "required_ingredients": _json(app["required_ingredients"]) if action == "publish" else None,
            "introduced_ingredients": _json(app["introduced_ingredients"]),
            "ingredient_map": _json(app["ingredient_map"]) if action == "publish" else None,
            "equipment_needs": _json(app["equipment_needs"]) if action == "publish" else None,
            "equipment_reviewed": int(equipment_reviewed if action == "publish" else False),
        }
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute("SELECT * FROM recipe_publications WHERE intent_id=?", (intent_id,)).fetchone()
        if existing is not None:
            conn.rollback()
            if not _existing_matches(existing, expected):
                raise ReviewRefused("intent_id_reused")
            result = dict(existing); result["publication_id"] = int(existing["id"]); result["replayed"] = True
            return result
        acted_at = now_iso()
        columns = ["intent_id"] + list(expected) + ["acted_at"]
        values = [intent_id] + [expected[key] for key in expected] + [acted_at]
        cur = conn.execute("INSERT INTO recipe_publications(%s) VALUES(%s)" %
                           (",".join(columns), ",".join("?" for _ in columns)), values)
        state, publishable = (("approved", 1) if action == "publish" else ("rejected", 0))
        changed = conn.execute(
            """UPDATE recipe_versions SET state=?, state_reason=?, state_set_by=?, publishable=?, updated_at=?
               WHERE id=?""", (state, reason, by, publishable, acted_at, version_id))
        if changed.rowcount != 1:
            raise ReviewRefused("recipe version disappeared")
        if crash_hook:
            crash_hook("before_commit")
        conn.commit()
        result = dict(conn.execute("SELECT * FROM recipe_publications WHERE id=?", (cur.lastrowid,)).fetchone())
        result["publication_id"] = int(result["id"]); result["replayed"] = False
        if crash_hook:
            crash_hook("after_commit")
        return result
    except BaseException:
        if conn is not None and conn.in_transaction:
            conn.rollback()
        raise
    finally:
        if conn is not None:
            conn.close()
        lock.release()


def publish(db_path: Union[str, Path], **kwargs: Any) -> Dict[str, Any]:
    return review(db_path, action="publish", **kwargs)


def withdraw(db_path: Union[str, Path], **kwargs: Any) -> Dict[str, Any]:
    return review(db_path, action="withdraw", **kwargs)


def _csv(value: str) -> List[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _maps(value: str) -> List[Dict[str, Any]]:
    result = []
    for entry in value.split(";") if value else []:
        index, tokens = entry.split(":", 1)
        result.append({"index": int(index), "tokens": _csv(tokens)})
    return result


def _equipment(value: str) -> List[Dict[str, str]]:
    result = []
    for entry in value.split(";") if value else []:
        text, anchor = entry.split("|", 1)
        result.append({"text": text.strip(), "anchor": anchor})
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("publish", "withdraw"))
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--intent", required=True)
    parser.add_argument("--version", type=int, required=True)
    parser.add_argument("--by", required=True)
    parser.add_argument("--authority", required=True)
    parser.add_argument("--rights-basis")
    parser.add_argument("--reason")
    parser.add_argument("--template")
    parser.add_argument("--requires", default="")
    parser.add_argument("--introduces", default="")
    parser.add_argument("--map", dest="ingredient_map", default="")
    parser.add_argument("--equipment", default="")
    parser.add_argument("--equipment-reviewed", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = review(args.db, action=args.action, intent_id=args.intent, version_id=args.version,
                        by=args.by, authority=args.authority, rights_basis=args.rights_basis,
                        reason=args.reason, template_name=args.template, required=_csv(args.requires),
                        introduced=_csv(args.introduces), ingredient_map=_maps(args.ingredient_map),
                        equipment_needs=_equipment(args.equipment),
                        equipment_reviewed=args.equipment_reviewed)
    except (ReviewRefused, ReviewLockBusy, OSError, sqlite3.Error) as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
