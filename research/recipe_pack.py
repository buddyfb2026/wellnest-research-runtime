"""WEL-52 recipe-pack producer.

Exports only human-published, current, evidence-bound WEL-48 documents. Generation is
allocated in the authoritative store while the existing store lock is held; the file is
then replaced atomically before the lock is released.
"""
import hashlib
import json
import os
import sqlite3
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

from . import db, recipe_schema
from .fetch import now_iso
from .lock import StoreLock
from .recipes import canonical_json, resolve_current

PACK_VERSION = 1
PACK_CAPABILITY = "weekly_meal_plan_recipes"
PACK_KIND = "recipe_pack"
FIXTURE_MARKER = "wel52 fixture — not corpus content, no publication right claimed"
SCALAR_FIELDS = {"servings", "prep_time", "cook_time", "total_time"}
UNKNOWN_REASONS = {
    "source_reading_unrecognized", "not_stated_by_model", "not_stated_by_source",
    "value_type_unsupported", "span_not_in_evidence", "quote_outside_recipe_region",
    "scalar_expression_unrecognized", "value_not_supported_by_quote",
    "conflicting_source_values",
}
OMITTED_REASONS = (
    "no_publication", "withdrawn", "not_human_published", "row_state_disagrees_with_log",
    "fingerprint_drift", "not_current_observation", "schema_invalid", "content_not_usable",
    "unknown_reason_out_of_contract", "has_conflicts", "support_not_in_evidence",
    "non_live_evidence", "source_embedded_instructions_flagged", "malformed_applicability",
    "missing_rights_basis", "ingredient_map_incomplete", "equipment_not_reviewed",
    "applicability_slot_collision",
)


class ExportRefused(ValueError):
    pass


class ExportLockBusy(RuntimeError):
    pass


def _decode(value: Any, fallback: Any = None) -> Any:
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _literal(item: Any) -> Optional[Tuple[str, Dict[str, Any]]]:
    if not isinstance(item, dict):
        return None
    if item.get("support") == "source_literal" and isinstance(item.get("value"), str):
        return item["value"], item.get("span") or {}
    source = item.get("source")
    if (item.get("support") == "source_normalized" and isinstance(source, dict)
            and source.get("support") == "source_literal" and isinstance(source.get("value"), str)):
        return source["value"], source.get("span") or {}
    return None


def _span_matches(text: str, bound: Tuple[str, Dict[str, Any]]) -> bool:
    literal, span = bound
    start, end = span.get("start"), span.get("end")
    return (isinstance(start, int) and isinstance(end, int) and 0 <= start <= end <= len(text)
            and text[start:end] == literal)


def _unknowns_valid(document: Dict[str, Any]) -> bool:
    ingredients = document.get("ingredients") if isinstance(document.get("ingredients"), list) else []
    for item in document.get("unknown_fields", []):
        if not isinstance(item, dict):
            return False
        field, reason = item.get("field"), item.get("reason")
        if field in SCALAR_FIELDS and reason in UNKNOWN_REASONS:
            continue
        if reason == "ingredient_correspondence_ambiguous" and isinstance(field, str):
            if not (field.startswith("ingredient[") and field.endswith("]")):
                return False
            try:
                index = int(field[len("ingredient["):-1])
            except ValueError:
                return False
            if index < 0 or index >= len(ingredients) or _literal(ingredients[index]) is None:
                return False
            continue
        return False
    return True


def _evidence_supported(row: sqlite3.Row, document: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    evidence = row["evidence_text"]
    if not isinstance(evidence, str) or hashlib.sha256(evidence.encode("utf-8")).hexdigest() != row["evidence_hash"]:
        return False, "support_not_in_evidence"
    bound: List[Tuple[str, Dict[str, Any]]] = []
    for item in [document.get("name")]:
        value = _literal(item)
        if value:
            bound.append(value)
    for key in ("ingredients", "steps"):
        for item in document.get(key, []):
            value = _literal(item)
            if value:
                bound.append(value)
    servings = document.get("servings")
    value = _literal(servings)
    if value:
        bound.append(value)
    times = document.get("times") if isinstance(document.get("times"), dict) else {}
    for item in times.values():
        value = _literal(item)
        if value:
            bound.append(value)
    if not bound or any(not _span_matches(evidence, item) for item in bound):
        return False, "support_not_in_evidence"
    if row["content_kind"] != "live":
        return False, "non_live_evidence"
    flags = _decode(row["injection_flags"], None)
    if flags is None or not isinstance(flags, list) or flags:
        return False, "source_embedded_instructions_flagged"
    return True, None


def _applicability(publication: sqlite3.Row, document: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    required = _decode(publication["required_ingredients"])
    introduced = _decode(publication["introduced_ingredients"])
    mapping = _decode(publication["ingredient_map"])
    equipment = _decode(publication["equipment_needs"])
    if (not isinstance(publication["template_name"], str) or not publication["template_name"].strip()
            or not isinstance(required, list) or not required
            or not isinstance(introduced, list) or not isinstance(mapping, list)
            or not all(isinstance(v, str) and v and v == v.lower() for v in required + introduced)):
        return None, "malformed_applicability"
    ingredients = document.get("ingredients") if isinstance(document.get("ingredients"), list) else []
    seen: Dict[int, List[str]] = {}
    for item in mapping:
        if (not isinstance(item, dict) or not isinstance(item.get("index"), int)
                or item["index"] in seen or not isinstance(item.get("tokens"), list)
                or not item["tokens"] or not all(isinstance(v, str) and v and v == v.lower()
                                                  for v in item["tokens"])):
            return None, "ingredient_map_incomplete"
        seen[item["index"]] = item["tokens"]
    if set(seen) != set(range(len(ingredients))):
        return None, "ingredient_map_incomplete"
    if {v for values in seen.values() for v in values} != set(required) | set(introduced):
        return None, "ingredient_map_incomplete"
    if int(publication["equipment_reviewed"] or 0) != 1 or not isinstance(equipment, list):
        return None, "equipment_not_reviewed"
    literals = [value[0] for value in (_literal(item) for item in ingredients + document.get("steps", [])) if value]
    for item in equipment:
        if (not isinstance(item, dict) or not isinstance(item.get("text"), str) or not item["text"]
                or not isinstance(item.get("anchor"), str)
                or not any(item["anchor"] in literal for literal in literals)):
            return None, "equipment_not_reviewed"
    return {"kind": "meal_template", "template_name": publication["template_name"],
            "required_ingredients": required, "introduced_ingredients": introduced,
            "ingredient_map": mapping, "equipment_needs": equipment,
            "equipment_reviewed": True}, None


def _coverage(document: Dict[str, Any]) -> Dict[str, Any]:
    return {"completeness": document.get("completeness"),
            "unknown_scalars": [item for item in document.get("unknown_fields", [])
                                if item.get("field") in SCALAR_FIELDS]}


def _recipe_payload(row: sqlite3.Row, publication: sqlite3.Row, document: Dict[str, Any],
                    applicability: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "publication": {
            "publication_id": int(publication["id"]), "intent_id": publication["intent_id"],
            "recipe_version_id": int(row["id"]), "recipe_key": row["recipe_key"],
            "content_fingerprint": row["content_fingerprint"],
            "published_by": publication["acted_by"], "published_at": publication["acted_at"],
            "authority": publication["authority"], "rights_basis": publication["rights_basis"],
            "extractor_version": row["extractor_version"],
            "prompt_schema_version": row["prompt_schema_version"],
        },
        "applicability": applicability,
        "coverage": _coverage(document),
        "document": document,
    }


def _source_rows(conn: sqlite3.Connection) -> Sequence[sqlite3.Row]:
    return conn.execute(
        """SELECT rv.*, r.recipe_key, e.content_kind, e.content_hash AS evidence_hash,
                  e.injection_flags, et.text AS evidence_text
             FROM recipe_versions rv JOIN recipes r ON r.id=rv.recipe_id
             JOIN evidence e ON e.id=rv.evidence_id
             LEFT JOIN evidence_text et ON et.evidence_id=e.id
            ORDER BY rv.id"""
    ).fetchall()


def build_served_state(conn: sqlite3.Connection, allow_fixture_evidence: bool = False) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    candidates: List[Tuple[sqlite3.Row, sqlite3.Row, Dict[str, Any], Dict[str, Any]]] = []
    withdrawn: List[Dict[str, Any]] = []
    omitted: List[Dict[str, Any]] = []
    for row in _source_rows(conn):
        publication = conn.execute(
            "SELECT * FROM recipe_publications WHERE recipe_version_id=? ORDER BY id DESC LIMIT 1",
            (row["id"],),
        ).fetchone()
        reason: Optional[str] = None
        if publication is None:
            reason = "no_publication"
        elif publication["action"] == "withdraw":
            withdrawn.append({"recipe_version_id": int(row["id"]), "recipe_key": row["recipe_key"],
                              "content_fingerprint": row["content_fingerprint"],
                              "withdrawn_by": publication["acted_by"],
                              "withdrawn_at": publication["acted_at"], "reason": publication["reason"]})
            reason = "withdrawn"
        elif not publication["acted_by"].startswith("human:"):
            reason = "not_human_published"
        elif row["state"] != "approved" or row["state_set_by"] != publication["acted_by"] or int(row["publishable"] or 0) != 1:
            reason = "row_state_disagrees_with_log"
        try:
            document = json.loads(row["content"])
        except (TypeError, ValueError):
            document = None
        if reason is None and (document is None or hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest() != row["content_fingerprint"]):
            reason = "fingerprint_drift"
        current = resolve_current(conn, int(row["recipe_id"])) if reason is None else None
        if reason is None and (current is None or int(current["id"]) != int(row["id"])):
            reason = "not_current_observation"
        if reason is None and recipe_schema.validate(document):
            reason = "schema_invalid"
        if reason is None and not recipe_schema.cooking_content_usable(document):
            reason = "content_not_usable"
        if reason is None and not _unknowns_valid(document):
            reason = "unknown_reason_out_of_contract"
        if reason is None and document.get("conflicts"):
            reason = "has_conflicts"
        if reason is None:
            supported, support_reason = _evidence_supported(row, document)
            if not supported and not (allow_fixture_evidence and support_reason == "non_live_evidence"):
                reason = support_reason
        if reason is None:
            try:
                flags = _decode(row["injection_flags"], None)
                if flags:
                    reason = "source_embedded_instructions_flagged"
            except (TypeError, ValueError):
                reason = "source_embedded_instructions_flagged"
        applicability = None
        if reason is None:
            applicability, reason = _applicability(publication, document)
        if reason is None and not publication["rights_basis"]:
            reason = "missing_rights_basis"
        if reason is None:
            candidates.append((row, publication, document, applicability))
        else:
            omitted.append({"recipe_version_id": int(row["id"]), "recipe_key": row["recipe_key"],
                            "reason": reason})
    slots: Dict[Tuple[str, Tuple[str, ...]], List[int]] = {}
    for index, (_, _, _, applicability) in enumerate(candidates):
        slot = (applicability["template_name"], tuple(sorted(applicability["required_ingredients"])))
        slots.setdefault(slot, []).append(index)
    collisions = {index for indexes in slots.values() if len(indexes) > 1 for index in indexes}
    recipes = []
    for index, (row, publication, document, applicability) in enumerate(candidates):
        if index in collisions:
            omitted.append({"recipe_version_id": int(row["id"]), "recipe_key": row["recipe_key"],
                            "reason": "applicability_slot_collision"})
        else:
            recipes.append(_recipe_payload(row, publication, document, applicability))
    recipes.sort(key=lambda value: value["publication"]["recipe_key"])
    withdrawn.sort(key=lambda value: value["recipe_version_id"])
    omitted.sort(key=lambda value: (value["recipe_version_id"], value["reason"]))
    return {"recipes": recipes, "withdrawn": withdrawn}, omitted


def served_state(pack: Dict[str, Any]) -> Dict[str, Any]:
    return {"recipes": pack["recipes"], "withdrawn": pack["withdrawn"]}


def state_hash(state: Dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(state).encode("utf-8")).hexdigest()


def _aliases(a: Path, b: Path) -> bool:
    try:
        if a.exists() and b.exists() and os.path.samefile(a, b):
            return True
    except OSError:
        pass
    return a.resolve() == b.resolve()


def check_paths(db_path: Path, out: Path) -> None:
    temp = Path(str(out) + ".tmp")
    if _aliases(db_path, out) or _aliases(db_path, temp) or _aliases(out, temp):
        raise ExportRefused("database, output, and output temp paths must not alias")


def _producer_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parent.parent,
            text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def export_recipe_pack(db_path: Union[str, Path], out: Union[str, Path], *,
                       allow_fixture_evidence: bool = False,
                       crash_hook: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    db_path, out = Path(db_path), Path(out)
    check_paths(db_path, out)
    lock = StoreLock(db_path)
    if not lock.acquire():
        raise ExportLockBusy("research store is busy")
    conn: Optional[sqlite3.Connection] = None
    try:
        conn = db.connect(db_path)
        db.migrate(conn)
        conn.execute("BEGIN IMMEDIATE")
        state, omitted = build_served_state(conn, allow_fixture_evidence=allow_fixture_evidence)
        digest = state_hash(state)
        prior = conn.execute("SELECT * FROM pack_state WHERE kind=?", (PACK_KIND,)).fetchone()
        if prior is not None and prior["state_hash"] == digest:
            generation = int(prior["generation"])
        else:
            generation = (int(prior["generation"]) if prior else 0) + 1
            conn.execute(
                """INSERT INTO pack_state(kind,generation,state_hash,allocated_at) VALUES(?,?,?,?)
                   ON CONFLICT(kind) DO UPDATE SET generation=excluded.generation,
                   state_hash=excluded.state_hash, allocated_at=excluded.allocated_at""",
                (PACK_KIND, generation, digest, now_iso()),
            )
        if crash_hook:
            crash_hook("before_state_commit")
        conn.commit()
        if crash_hook:
            crash_hook("after_state_commit")
        pack: Dict[str, Any] = {
            "pack_version": PACK_VERSION, "capability": PACK_CAPABILITY,
            "pack_id": digest, "generation": generation, "generated_at": now_iso(),
            "producer": {"repo": "wellnest-research-runtime", "commit": _producer_commit(),
                         "recipe_schema_version": recipe_schema.RECIPE_SCHEMA_VERSION,
                         "recipe_schema_hash": recipe_schema.SCHEMA_HASH},
            "recipes": state["recipes"], "withdrawn": state["withdrawn"], "omitted": omitted,
        }
        if allow_fixture_evidence:
            pack["_fixture"] = FIXTURE_MARKER
        encoded = (json.dumps(pack, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        out.parent.mkdir(parents=True, exist_ok=True)
        temp = Path(str(out) + ".tmp")
        with open(temp, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        if crash_hook:
            crash_hook("after_temp_write")
        os.replace(temp, out)
        if crash_hook:
            crash_hook("after_rename")
        return pack
    except BaseException:
        if conn is not None and conn.in_transaction:
            conn.rollback()
        raise
    finally:
        if conn is not None:
            conn.close()
        lock.release()
