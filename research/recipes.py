"""Durable recipe manifests, identities, versions, replay and current-observation selection."""
import hashlib
import json
import sqlite3
from typing import Any, Dict, Iterable, Optional, Tuple

from .fetch import now_iso

EXTRACTOR_VERSION = "wel48_extractor_v3"
PROMPT_SCHEMA_VERSION = "wel48_recipe_literals_v3"
BUDGET_PLACEHOLDER_PREFIX = "inference_budget_exhausted"


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def manifest_hash(manifest: Dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(manifest).encode("utf-8")).hexdigest()


def attach_manifest(conn: sqlite3.Connection, evidence_id: int, manifest: Dict[str, Any],
                    observed_at: Optional[str] = None) -> Tuple[int, bool]:
    """Append distinct manifest content and point the mutable observation ref at what was seen."""
    observed_at = observed_at or now_iso()
    encoded, digest = canonical_json(manifest), manifest_hash(manifest)
    row = conn.execute(
        "SELECT id FROM locator_manifests WHERE evidence_id=? AND manifest_hash=?",
        (evidence_id, digest),
    ).fetchone()
    inserted = row is None
    if row is None:
        prior = conn.execute(
            "SELECT id, revision_no FROM locator_manifests WHERE evidence_id=? ORDER BY revision_no DESC LIMIT 1",
            (evidence_id,),
        ).fetchone()
        revision = int(prior["revision_no"]) + 1 if prior else 1
        cur = conn.execute(
            """INSERT INTO locator_manifests(evidence_id, manifest_hash, locator_version, revision_no,
                   supersedes_id, manifest, first_observed_at) VALUES(?,?,?,?,?,?,?)""",
            (evidence_id, digest, manifest["locator_version"], revision,
             int(prior["id"]) if prior else None, encoded, observed_at),
        )
        manifest_id = int(cur.lastrowid)
    else:
        manifest_id = int(row["id"])
    conn.execute(
        """INSERT INTO evidence_current_manifest(evidence_id, locator_manifest_id, manifest_hash, observed_at)
           VALUES(?,?,?,?) ON CONFLICT(evidence_id) DO UPDATE SET
           locator_manifest_id=excluded.locator_manifest_id,
           manifest_hash=excluded.manifest_hash, observed_at=excluded.observed_at""",
        (evidence_id, manifest_id, digest, observed_at),
    )
    return manifest_id, inserted


def current_manifest(conn: sqlite3.Connection, evidence_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        """SELECT lm.*, ecm.observed_at FROM evidence_current_manifest ecm
           JOIN locator_manifests lm ON lm.id=ecm.locator_manifest_id
           WHERE ecm.evidence_id=? AND ecm.manifest_hash=lm.manifest_hash""", (evidence_id,)
    ).fetchone()


def recipe_key(source_url: str, slot: str) -> str:
    return hashlib.sha256((source_url + "|" + slot).encode("utf-8")).hexdigest()


def extraction_key(evidence_id: int, digest: str, slot: str, generator: str,
                   extractor_version: str = EXTRACTOR_VERSION,
                   prompt_schema_version: str = PROMPT_SCHEMA_VERSION) -> str:
    raw = "|".join((str(evidence_id), digest, slot, extractor_version, prompt_schema_version, generator))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def ensure_recipe(conn: sqlite3.Connection, source_url: str, slot: Optional[str], evidence_id: int,
                  disambiguated: int = 0, created_at: Optional[str] = None) -> Optional[int]:
    if not slot:
        return None
    key, created_at = recipe_key(source_url, slot), created_at or now_iso()
    conn.execute(
        """INSERT OR IGNORE INTO recipes(recipe_key, source_url, recipe_slot, slot_disambiguated,
               first_seen_evidence_id, created_at) VALUES(?,?,?,?,?,?)""",
        (key, source_url, slot, int(bool(disambiguated)), evidence_id, created_at),
    )
    row = conn.execute("SELECT id FROM recipes WHERE recipe_key=?", (key,)).fetchone()
    return int(row["id"])


def existing_version(conn: sqlite3.Connection, key: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM recipe_versions WHERE extraction_key=?", (key,)).fetchone()


def is_budget_placeholder(row: Optional[sqlite3.Row]) -> bool:
    return bool(row and row["state_set_by"] == "worker" and
                (row["state_reason"] or "").startswith(BUDGET_PLACEHOLDER_PREFIX))


def save_version(conn: sqlite3.Connection, recipe_id: int, evidence_id: int,
                 locator_manifest_id: int, digest: str, key: str, generator: str,
                 content: Dict[str, Any], adaptations: Any, completeness: str,
                 unknown_fields: Any, conflicts: Any, state: str, state_reason: Optional[str],
                 inference_call_id: Optional[int], created_at: Optional[str] = None) -> int:
    created_at = created_at or now_iso()
    encoded = canonical_json(content)
    fingerprint = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    prior = conn.execute(
        "SELECT id, version_no FROM recipe_versions WHERE recipe_id=? ORDER BY version_no DESC LIMIT 1",
        (recipe_id,),
    ).fetchone()
    unchanged = conn.execute(
        "SELECT id FROM recipe_versions WHERE recipe_id=? AND content_fingerprint=? ORDER BY id LIMIT 1",
        (recipe_id, fingerprint),
    ).fetchone()
    cur = conn.execute(
        """INSERT INTO recipe_versions(recipe_id,evidence_id,locator_manifest_id,manifest_hash,
               version_no,supersedes_id,extraction_key,content_fingerprint,content_unchanged_from,
               extractor_version,prompt_schema_version,generator,content,adaptations,completeness,
               unknown_fields,conflicts,state,state_reason,state_set_by,publishable,inference_call_id,
               created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?,?)""",
        (recipe_id, evidence_id, locator_manifest_id, digest,
         int(prior["version_no"]) + 1 if prior else 1, int(prior["id"]) if prior else None,
         key, fingerprint, int(unchanged["id"]) if unchanged else None, EXTRACTOR_VERSION,
         PROMPT_SCHEMA_VERSION, generator, encoded,
         canonical_json(adaptations) if adaptations is not None else None, completeness,
         canonical_json(unknown_fields), canonical_json(conflicts), state, state_reason, "worker",
         inference_call_id, created_at, created_at),
    )
    return int(cur.lastrowid)


def replace_placeholder(conn: sqlite3.Connection, row_id: int, content: Dict[str, Any], adaptations: Any,
                        completeness: str, unknown_fields: Any, conflicts: Any, state: str,
                        state_reason: Optional[str], inference_call_id: Optional[int]) -> None:
    encoded = canonical_json(content)
    fingerprint = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    cur = conn.execute(
        """UPDATE recipe_versions SET content_fingerprint=?, content=?, adaptations=?, completeness=?,
               unknown_fields=?, conflicts=?, state=?, state_reason=?, inference_call_id=?, updated_at=?
           WHERE id=? AND state_set_by='worker'""",
        (fingerprint, encoded, canonical_json(adaptations) if adaptations is not None else None,
         completeness, canonical_json(unknown_fields), canonical_json(conflicts), state, state_reason,
         inference_call_id, now_iso(), row_id),
    )
    if cur.rowcount != 1:
        raise sqlite3.IntegrityError("recipe placeholder changed by a human; replacement refused")


def work_items(conn: sqlite3.Connection, generator: str) -> Iterable[Dict[str, Any]]:
    """Latest evidence only, but always the manifest named by its latest-observation ref."""
    rows = conn.execute(
        """SELECT e.*, lm.id AS locator_manifest_id, lm.manifest_hash, lm.manifest
           FROM evidence e
           JOIN evidence_current_manifest ecm ON ecm.evidence_id=e.id
           JOIN locator_manifests lm ON lm.id=ecm.locator_manifest_id
           WHERE e.version_no=(SELECT MAX(e2.version_no) FROM evidence e2 WHERE e2.url=e.url)
           ORDER BY e.id"""
    ).fetchall()
    for evidence in rows:
        manifest = json.loads(evidence["manifest"])
        for located in manifest.get("recipes", []):
            slot = located.get("slot")
            if not slot:
                continue
            key = extraction_key(int(evidence["id"]), evidence["manifest_hash"], slot, generator)
            existing = existing_version(conn, key)
            if existing is None or is_budget_placeholder(existing):
                yield {"evidence": evidence, "manifest": manifest, "located": located,
                       "extraction_key": key, "existing": existing}


def resolve_current(conn: sqlite3.Connection, recipe_id: int) -> Optional[sqlite3.Row]:
    """Resolve by the observed manifest pointer; audit-order maxima are deliberately irrelevant."""
    return conn.execute(
        """SELECT rv.* FROM recipe_versions rv
           JOIN evidence_current_manifest ecm ON ecm.evidence_id=rv.evidence_id
           WHERE rv.recipe_id=? AND rv.manifest_hash=ecm.manifest_hash
           ORDER BY rv.id DESC LIMIT 1""", (recipe_id,)
    ).fetchone()
