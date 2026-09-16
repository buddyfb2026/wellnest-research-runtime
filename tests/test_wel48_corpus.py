import hashlib
import json
from pathlib import Path

from research.extract import extract
from research.recipe_extract import bind, proposal_for_located
from research.recipe_schema import cooking_content_usable

MANIFEST = Path("eval/wel48/corpus/manifest.json")
RAW = Path("/tmp/wel48-coordination/corpus/raw")
R1 = Path("/tmp/wel42-coordination/evidence-raw/burrito_bowls.html")
BAKEOFF = Path("/tmp/wel48-coordination/model-bakeoff")


def _records():
    return json.loads(MANIFEST.read_text())["records"]


def _path(record):
    return R1 if record["id"] == "R1" else RAW / Path(record["immutable_bytes"]["raw_file"]).name


def _result(record):
    raw = _path(record).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == record["immutable_bytes"]["sha256_raw_bytes"]
    ex = extract(raw.decode("utf-8", errors="replace"))
    assert ex.content_hash == record["extracted"]["content_hash"]
    located = ex.locators["recipes"][0]
    evidence = {"id": 1, "url": record["source_url"], "version_no": 1, "content_hash": ex.content_hash,
                "title": ex.title, "attribution": record["publisher_host"], "fetched_at": "frozen",
                "published_at": ex.published_at}
    manifest = {"id": 1, "locator_manifest_id": 1, "manifest_hash": "frozen", "revision_no": 1,
                "locator_version": ex.locators["locator_version"]}
    document, completeness, unknowns, conflicts = bind(
        evidence, ex.text, manifest, located, proposal_for_located(ex.text, located))
    return located, completeness, unknowns, conflicts


def _saved_replay():
    cases = {case["id"]: case for case in json.loads((BAKEOFF / "frozen-inputs.json").read_text())}
    results = {}
    for record_id, case in cases.items():
        proposal = json.loads((BAKEOFF / ("2-%s-result.json" % record_id)).read_text())["proposal"]
        evidence = {"id": 1, "url": "https://frozen.invalid/%s" % record_id, "version_no": 1,
                    "content_hash": hashlib.sha256(case["text"].encode()).hexdigest(),
                    "title": case["title"], "attribution": "frozen", "fetched_at": "frozen",
                    "published_at": None}
        manifest = {"id": 1, "locator_manifest_id": 1, "manifest_hash": "frozen",
                    "revision_no": 1, "locator_version": "wel48_locator_v1"}
        document, completeness, unknowns, conflicts = bind(
            evidence, case["text"], manifest, case["expected_locator"]["recipes"][0], proposal)
        results[record_id] = (document, completeness, unknowns, conflicts)
    return results


def test_frozen_live_corpus_counts_and_hashes():
    records = _records()
    assert len(records) == 6
    assert len({r["publisher_host"] for r in records}) == 3
    held = [r for r in records if r["role"] == "HELD OUT"]
    assert len(held) == 2
    assert {r["id"] for r in held} == {"R2", "R6"}
    assert sum(1 for r in records if _path(r).exists()) == 6


def test_complete_results_include_both_heldouts():
    results = {record["id"]: _result(record)[1] for record in _records()}
    assert sum(value == "complete" for value in results.values()) == 5
    assert results["R4"] == "incomplete"
    assert [results["R2"], results["R6"]] == ["complete", "complete"]


def test_all_six_live_results_are_reported_and_fixtures_excluded():
    results = [(record["id"],) + _result(record)[1:] for record in _records()]
    assert len(results) == 6 and {x[0] for x in results} == {"R1", "R2", "R3", "R4", "R5", "R6"}
    assert all(not row[0].startswith("F") for row in results)


def test_saved_model_replay_matches_binding_v5_exact_oracle():
    replay = _saved_replay(); results = {}
    for record_id, (document, completeness, _, conflicts) in replay.items():
        scalars = [document["servings"], *document["times"].values()]
        results[record_id] = {
            "complete": completeness == "complete",
            "usable": cooking_content_usable(document),
            "scalars": sum(item["support"] == "source_normalized" for item in scalars),
            "conflicts": len(conflicts),
            "servings_unknown": document["servings"]["support"] == "unknown",
        }
    assert sum(item["complete"] for item in results.values()) == 4
    assert sum(results[key]["complete"] for key in ("R2", "R6")) == 1
    assert sum(item["usable"] for item in results.values()) == 6
    assert sum(item["scalars"] for item in results.values()) == 22
    assert sum(item["conflicts"] for item in results.values()) == 0
    assert sum(item["servings_unknown"] for item in results.values()) == 2
