import copy
import hashlib
import json
from pathlib import Path

from research import db, recipes
from research.recipe_extract import bind
from research.recipe_locate import locate
from research import source_registry as registry
from tests.wel52_helpers import seed_version

ROOT = Path(__file__).parent.parent
LITERALS_PATH = ROOT / "eval/wel48/fixtures/operating-recipe-literals.json"
MIRROR_PATH = ROOT / "eval/wel51/fixtures/syndicated-duplicate.json"
ROSTER_PATH = ROOT / "sources/roster.json"
LITERALS = json.loads(LITERALS_PATH.read_text())
MIRROR = json.loads(MIRROR_PATH.read_text())
PITA = "https://www.nhlbi.nih.gov/health/heart-healthy-living/healthy-foods/healthy-eating-recipes/pita-pizzas"
RICE = "https://www.nhlbi.nih.gov/health/heart-healthy-living/healthy-foods/healthy-eating-recipes/wiki-fast-rice"


def roster(*, mirror=True, access=None, mirror_parent=None):
    value = json.loads(ROSTER_PATH.read_text())
    if mirror:
        publisher = copy.deepcopy(MIRROR["publisher"])
        publisher["parent_publisher"] = mirror_parent
        value["publishers"].append(publisher)
        value["surfaces"].append(copy.deepcopy(MIRROR["surface"]))
    for surface in value["surfaces"]:
        if access and surface["url"] in access:
            surface["access_status"] = access[surface["url"]]
    return value


def make_store(path, *, project_roster=True, roster_value=None):
    conn = db.connect(path)
    assert db.migrate(conn) == 8
    if project_roster:
        registry.project(conn, roster_value or roster())
    return conn


def _insert_evidence(conn, fixture, url, content_kind):
    text = fixture["text"]
    digest = hashlib.sha256(text.encode()).hexdigest()
    previous = conn.execute("SELECT id,version_no FROM evidence WHERE url=? ORDER BY version_no DESC LIMIT 1", (url,)).fetchone()
    cur = conn.execute(
        """INSERT INTO evidence(url,final_url,content_kind,content_hash,version_no,supersedes_id,fetched_at,
           published_at,published_at_basis,modified_at,title,attribution,source_type,access_basis,
           usage_constraints,excerpt,text_chars,injection_flags)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (url, url, content_kind, digest, int(previous["version_no"]) + 1 if previous else 1,
         int(previous["id"]) if previous else None, "2026-09-21T00:00:00Z", None, "unknown", None,
         fixture["proposal"]["name"], fixture["attribution"], "publication", fixture["access_basis"],
         "fixture/saved evidence", text[:100], len(text), "[]"),
    )
    evidence_id = int(cur.lastrowid)
    conn.execute("INSERT INTO evidence_text(evidence_id,text) VALUES(?,?)", (evidence_id, text))
    manifest = locate("", text, fixture["proposal"]["name"])
    manifest_id, _ = recipes.attach_manifest(conn, evidence_id, manifest, "2026-09-21T00:00:00Z")
    return evidence_id, manifest_id, manifest, text, digest


def seed_literal(conn, index, *, url=None, content_kind="live", proposal=None):
    fixture = copy.deepcopy(LITERALS[index])
    url = url or fixture["url"]
    evidence_id, manifest_id, manifest, text, digest = _insert_evidence(conn, fixture, url, content_kind)
    located = manifest["recipes"][0]
    recipe_id = recipes.ensure_recipe(conn, url, located["slot"], evidence_id, created_at="2026-09-21T00:00:00Z")
    evidence = {"id": evidence_id, "url": url, "version_no": 1, "content_hash": digest,
                "title": fixture["proposal"]["name"], "attribution": fixture["attribution"],
                "fetched_at": "2026-09-21T00:00:00Z", "published_at": None}
    row = {"id": manifest_id, "locator_manifest_id": manifest_id,
           "manifest_hash": recipes.manifest_hash(manifest), "revision_no": 1,
           "locator_version": manifest["locator_version"]}
    document, completeness, unknowns, conflicts = bind(
        evidence, text, row, located, proposal or copy.deepcopy(fixture["proposal"])
    )
    extraction = recipes.extraction_key(evidence_id, row["manifest_hash"], located["slot"], "fixture")
    version_id = recipes.save_version(
        conn, recipe_id, evidence_id, manifest_id, row["manifest_hash"], extraction, "fixture",
        document, None, completeness, unknowns, conflicts, "pending", None, None,
        "2026-09-21T00:00:00Z",
    )
    return {"recipe_id": recipe_id, "version_id": version_id, "evidence_id": evidence_id,
            "manifest_id": manifest_id, "manifest": manifest, "document": document, "text": text,
            "content_hash": digest, "slot": located["slot"], "url": url}


def seed_corpus(path, *, mirror=True, orzo=True, qualifier=True, roster_value=None):
    conn = make_store(path, roster_value=roster_value)
    rows = {"E1": seed_literal(conn, 1)}
    if orzo:
        rows["E2"] = seed_literal(conn, 0)
    if mirror:
        rows["E3"] = seed_literal(conn, 1, url=MIRROR["url"], content_kind="fixture")
    if qualifier:
        rows["E4"] = seed_version(conn, "f-a", content_kind="fixture")
    conn.commit()
    return conn, rows


def counts(conn):
    return tuple(conn.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]
                 for table in ("findings", "finding_links", "finding_versions"))


def latest(conn):
    return conn.execute("SELECT * FROM finding_versions ORDER BY id DESC LIMIT 1").fetchone()
