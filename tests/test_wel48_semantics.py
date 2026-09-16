import json
from pathlib import Path

from tests.test_wel48_corpus import _saved_replay


def test_semantic_rubric_reports_every_live_record_without_model_self_rating():
    records = json.loads(Path("eval/wel48/corpus/manifest.json").read_text())["records"]
    rubric = Path("eval/wel48/rubric.md").read_text().lower()
    assert len(records) == 6
    assert "model self-ratings are ignored" in rubric
    assert "fixtures" in rubric and "never contribute to a live count" in " ".join(rubric.split())


def test_missing_live_predicates_are_explicitly_fixture_only():
    f1 = json.loads(Path("eval/wel48/fixtures/materially-incomplete.json").read_text())
    f2 = json.loads(Path("eval/wel48/fixtures/ingredient-conflict.json").read_text())
    assert [(x["id"], x["label"], x["live_coverage"]) for x in (f1, f2)] == [
        ("F1", "fixture", False), ("F2", "fixture", False)]


def test_all_six_saved_response_semantic_inventories_are_reported():
    replay = _saved_replay()
    assert set(replay) == {"R1", "R2", "R3", "R4", "R5", "R6"}
    report = {record_id: {"completeness": completeness,
                          "unknown_reasons": [item["reason"] for item in unknowns],
                          "conflicts": len(conflicts)}
              for record_id, (_, completeness, unknowns, conflicts) in replay.items()}
    assert sum(row["completeness"] == "complete" for row in report.values()) == 4
    assert report["R3"]["conflicts"] == 0
    r5 = replay["R5"][0]["servings"]
    assert report["R5"]["conflicts"] == 0
    assert r5["value"] == {"min": 4, "max": 6}
    assert len(r5["source"]["readings"]) == 4
