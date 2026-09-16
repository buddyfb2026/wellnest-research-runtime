import hashlib
import json
from pathlib import Path

from research import db
from research.recipes import (EXTRACTOR_VERSION, PROMPT_SCHEMA_VERSION, attach_manifest,
                              canonical_json, ensure_recipe, extraction_key, recipe_key,
                              save_version)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "wel52"


def load_spec(name):
    return json.loads((FIXTURE_DIR / (name + ".json")).read_text())


def make_store(path):
    conn = db.connect(path)
    assert db.migrate(conn) == 7
    return conn


def _bound(text, literal, support="source_literal"):
    start = text.index(literal)
    if support == "source_literal":
        return {"value": literal, "support": support, "span": {"start": start, "end": start + len(literal)}}
    return {"value": literal, "support": "source_normalized",
            "source": {"value": literal, "support": "source_literal",
                       "span": {"start": start, "end": start + len(literal)}}}


def seed_version(conn, fixture_name="f-a", *, content_kind="fixture", source_url=None):
    spec = load_spec(fixture_name)
    source_url = source_url or "https://fixture.example/%s" % fixture_name
    ingredients = ["%s ingredient %02d" % (fixture_name, i + 1) for i in range(spec["ingredient_count"])]
    steps = ["%s step %02d uses a skillet." % (fixture_name, i + 1) for i in range(spec["step_count"])]
    lines = [spec["name"], "Servings: 4", "Total Time: %d minutes" % spec["total_time"]] + ingredients + steps
    text = "\n".join(lines)
    digest = hashlib.sha256(text.encode()).hexdigest()
    cur = conn.execute(
        """INSERT INTO evidence(url,final_url,content_kind,content_hash,version_no,fetched_at,
             published_at,published_at_basis,modified_at,title,attribution,source_type,access_basis,
             usage_constraints,excerpt,text_chars,injection_flags)
             VALUES(?,?,?,?,1,'2026-09-15T00:00:00Z',NULL,'unknown',NULL,?,'Fixture Publisher',
                    'publication','fixture','fixture only',?,?, '[]')""",
        (source_url, source_url, content_kind, digest, spec["name"], text[:100], len(text)))
    evidence_id = int(cur.lastrowid)
    conn.execute("INSERT INTO evidence_text(evidence_id,text) VALUES(?,?)", (evidence_id, text))
    manifest = {"locator_version": "wel48_locator_v1", "recipes": [{"slot": "name:%s" % fixture_name}]}
    manifest_id, _ = attach_manifest(conn, evidence_id, manifest, "2026-09-15T00:00:00Z")
    slot = manifest["recipes"][0]["slot"]
    recipe_id = ensure_recipe(conn, source_url, slot, evidence_id, created_at="2026-09-15T00:00:00Z")
    key = recipe_key(source_url, slot)
    servings = ({"support": "unknown"} if spec["unknown_servings"]
                else {**_bound(text, "Servings: 4", "source_normalized"), "value": {"min": 4, "max": 4}})
    unknowns = ([{"field": "servings", "reason": "not_stated_by_source"}]
                if spec["unknown_servings"] else [])
    document = {
        "schema_version": "wel48_recipe_v1",
        "identity": {"recipe_key": key, "recipe_slot": slot, "slot_disambiguated": False},
        "name": _bound(text, spec["name"]),
        "servings": servings,
        "times": {"prep_time": {"support": "unknown"}, "cook_time": {"support": "unknown"},
                  "total_time": {**_bound(text, "Total Time: %d minutes" % spec["total_time"],
                                                   "source_normalized"), "value": spec["total_time"]}},
        "ingredients": [_bound(text, value) for value in ingredients],
        "steps": [_bound(text, value) for value in steps],
        "provenance": {"evidence_id": str(evidence_id), "revision": 1, "content_hash": digest,
                       "manifest_hash": "", "manifest_revision_no": 1,
                       "locator_version": "wel48_locator_v1", "is_current_observation": True},
        "evidence": {"evidence_id": str(evidence_id), "title": spec["name"], "revision": 1,
                     "content_hash": digest, "source_url": source_url,
                     "attribution": "Fixture Publisher", "checked_at": "2026-09-15T00:00:00Z",
                     "published_at": None},
        "completeness": "incomplete" if unknowns else "complete",
        "unknown_fields": unknowns, "conflicts": [],
    }
    manifest_hash = conn.execute("SELECT manifest_hash FROM locator_manifests WHERE id=?", (manifest_id,)).fetchone()[0]
    document["provenance"]["manifest_hash"] = manifest_hash
    ek = extraction_key(evidence_id, manifest_hash, slot, "fixture")
    version_id = save_version(conn, recipe_id, evidence_id, manifest_id, manifest_hash, ek, "fixture",
                              document, None, document["completeness"], unknowns, [], "pending", None,
                              None, "2026-09-15T00:00:00Z")
    return {"version_id": version_id, "recipe_id": recipe_id, "recipe_key": key,
            "document": document, "spec": spec, "ingredients": ingredients, "steps": steps,
            "evidence_id": evidence_id, "manifest": manifest}


def publish_args(seed, intent="fixture-publish"):
    return dict(intent_id=intent, version_id=seed["version_id"], by="human:Fixture Reviewer",
                authority="fixture-review", rights_basis="fixture-only test data",
                template_name=seed["spec"]["template"], required=[seed["fixture_token"]]
                if "fixture_token" in seed else [seed["recipe_key"][:8]], introduced=[],
                ingredient_map=[{"index": i, "tokens": [seed.get("fixture_token", seed["recipe_key"][:8])]}
                                for i in range(len(seed["ingredients"]))],
                equipment_needs=[{"text": "Skillet", "anchor": "skillet"}], equipment_reviewed=True)
