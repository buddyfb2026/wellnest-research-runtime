"""Portable regressions for source whitespace and explicitly located time values."""
import json
from functools import partial

import pytest

from research import db, recipes, worker
from research.config import Config
from research.extract import extract
from research.model import ModelClient
from research.recipe_extract import _bind_units, bind
from research.recipe_schema import cooking_content_usable
from tests.conftest import entry, good_proposal, make_transport, write_allowlist
from tests.test_wel48_bind import _inputs
from tests.test_wel48_replay import _run, _setup


def units_for(lines):
    text = "\n".join(lines)
    units, start = [], 0
    for line in lines:
        units.append({"start": start, "end": start + len(line)})
        start += len(line) + 1
    return text, units


@pytest.mark.parametrize("space", [" ", "\t", "\n", "\u00a0", "\u2003", "\u202f"])
def test_spacing_only_binds_original_source_span(space):
    original = "1 cup\u00a0cooked beans"
    text, units = units_for([original])
    unknowns = []
    result = _bind_units(text, "ingredient", units,
                         [space + space.join(original.split()) + space], unknowns)
    assert unknowns == [] and len(result) == 1
    source = result[0]["source"]
    assert source["value"] == original
    assert text[source["span"]["start"]:source["span"]["end"]] == original


@pytest.mark.parametrize("returned", [
    "2 cup cooked beans", "1 cup raw beans", "1 cup beans", "1 Cup cooked beans",
    "1 cup cooked beans!", "1cup cooked beans", "1 cup cooked be ans",
    "1 cup\u200bcooked beans", "cup cooked beans", "1 cup cooked beans 2 tsp oil",
    None, 1, "", "   ",
])
def test_spacing_does_not_accept_changed_or_partial_content(returned):
    text, units = units_for(["1 cup\u00a0cooked beans"])
    unknowns = []
    assert _bind_units(text, "ingredient", units, [returned], unknowns) == []
    assert any(x["reason"] == "located_units_not_fully_covered" for x in unknowns)


def test_spacing_preserves_ambiguity_duplicates_order_and_conflicts():
    text, units = units_for(["1 cup\u00a0beans", "1 cup  beans"])
    unknowns = []
    assert _bind_units(text, "ingredient", units, ["1 cup beans"], unknowns) == []
    # Identical repeated source units retain the incumbent ordered consumption rule.
    text, units = units_for(["1 cup\u00a0beans", "1 cup\u00a0beans"])
    unknowns = []
    result = _bind_units(text, "ingredient", units, ["1 cup beans"] * 2, unknowns)
    assert len(result) == 2 and unknowns == []
    assert [x["source"]["span"]["start"] for x in result] == [0, len("1 cup\u00a0beans") + 1]
    unknowns = []
    result = _bind_units(text, "ingredient", units[:1], ["1 cup beans"] * 2, unknowns)
    assert len(result) == 1 and unknowns
    text, units = units_for(["First\u00a0stir.", "Then\u00a0serve."])
    unknowns = []
    _bind_units(text, "step", units, ["Then serve.", "First stir."], unknowns)
    assert any(x["reason"] == "step_order_not_source_derivable" for x in unknowns)
    unknowns = []
    result = _bind_units(text, "step", units, ["First stir.", "Then serve."], unknowns,
                         {0: "conflicting_source_values"})
    assert result[0] == {"value": None, "support": "unknown", "reason": "conflicting_source_values"}


@pytest.mark.parametrize(("role", "key", "minutes"), [
    ("prep_time", "prep_minutes", 5), ("cook_time", "cook_minutes", 10),
    ("total_time", "total_minutes", 15),
])
def test_bare_time_requires_exact_located_role_value(role, key, minutes):
    ex, loc, evidence, manifest, proposal = _inputs()
    proposal[key] = {"value": minutes, "quote": "%s minutes" % minutes}
    doc, _, unknowns, _ = bind(evidence, ex.text, manifest, loc, proposal)
    field = doc["times"][role]
    assert field["value"] == minutes
    assert field["source"]["span"] == {k: loc["roles"][role][k] for k in ("start", "end")}
    assert not any(x["field"] == role for x in unknowns)
    loc["roles"].pop(role)
    doc, _, unknowns, _ = bind(evidence, ex.text, manifest, loc, proposal)
    assert doc["times"][role]["support"] == "unknown"


def test_bare_time_cannot_borrow_another_role_or_override_source_conflict():
    ex, loc, evidence, manifest, proposal = _inputs()
    proposal["prep_minutes"] = {"value": 10, "quote": "10 minutes"}
    doc, _, _, _ = bind(evidence, ex.text, manifest, loc, proposal)
    assert doc["times"]["prep_time"]["support"] == "unknown"
    proposal["prep_minutes"] = {"value": 5, "quote": "5 minutes"}
    loc["roles"]["prep_time"]["structured_decoded"] = ["PT6M"]
    doc, _, _, conflicts = bind(evidence, ex.text, manifest, loc, proposal)
    assert doc["times"]["prep_time"]["support"] == "unknown"
    assert any(x["field"] == "prep_time" for x in conflicts)


@pytest.mark.parametrize("space", ["\u00a0", " "])
def test_real_adapter_keeps_recipe_content_and_stated_times_then_replays(tmp_path, space):
    url = "https://fixture.example/meal/"
    ingredient = "1 cup" + space + "cooked beans"
    html = ("<html><head><title>Bean Supper</title></head><body><article>"
            "<h1>Bean Supper</h1><p>" + "context " * 40 + "</p>"
            "<h2>Ingredients</h2><p>" + ingredient + "</p>"
            "<h2>Directions</h2><ol><li>Warm the beans.</li><li>Serve immediately.</li></ol>"
            "<h2>Prep Time</h2><p>10 minutes</p><h2>Cook Time</h2><p>8 minutes</p>"
            "<h2>Yields</h2><p>4 servings</p></article></body></html>")
    ex = extract(html)
    # Hand-authored ordinary response: deliberately not built by the locator fixture helper.
    response = {"name": "Bean Supper", "ingredients": ["1 cup cooked beans"],
                "steps": ["Warm the beans.", "Serve immediately."],
                "servings": {"value": 4, "quote": "4 servings"},
                "prep_minutes": {"value": 10, "quote": "10 minutes"},
                "cook_minutes": {"value": 8, "quote": "8 minutes"},
                "total_minutes": {"value": None, "quote": None}, "unknowns": []}
    posts = []
    def post(url, payload, timeout):
        posts.append(payload)
        meta = json.loads(payload["prompt"].split("\n\n", 1)[0].split(": ", 1)[1])
        answer = response if "recipe_extraction" in meta else good_proposal(ex.text, meta)
        return {"response": json.dumps(answer)}
    cfg = Config(db_path=tmp_path / "test.sqlite",
                 allowlist_path=write_allowlist(tmp_path, [entry(url)]),
                 report_path=tmp_path / "report.md", provider="ollama", recipe_extraction_enabled=True)
    transport = make_transport({url: (200, url, {"content-type": "text/html"}, html)})
    assert worker.run(cfg, transport=transport,
                      model=ModelClient("ollama", 10, model="stub", http_post=post),
                      content_kind="fixture").ok
    conn = db.connect(cfg.db_path)
    row = dict(conn.execute("SELECT * FROM recipe_versions").fetchone())
    doc = json.loads(row["content"])
    assert cooking_content_usable(doc)
    assert len(doc["ingredients"]) == 1 and len(doc["steps"]) == 2
    assert doc["ingredients"][0]["source"]["value"] == ingredient
    assert doc["times"]["prep_time"]["value"] == 10
    assert doc["times"]["cook_time"]["value"] == 8
    assert [(x["field"], x["reason"]) for x in doc["unknown_fields"]] == [
        ("total_time", "not_stated_by_source")]
    assert row["completeness"] == "incomplete" and row["publishable"] == 0 and row["state"] == "pending"
    conn.close()
    assert worker.run(cfg, transport=transport,
                      model=ModelClient("ollama", 10, model="stub", http_post=post),
                      content_kind="fixture").ok
    conn = db.connect(cfg.db_path)
    assert [dict(x) for x in conn.execute("SELECT * FROM recipe_versions")] == [row]
    assert len(posts) == conn.execute("SELECT COUNT(*) FROM inference_calls").fetchone()[0] == 2
    conn.close()


@pytest.mark.parametrize("old_version", ["wel48_extractor_v2", "wel48_extractor_v3"])
def test_extractor_upgrade_preserves_old_version_and_spent_call(tmp_path, monkeypatch, old_version):
    cfg, pages, model, fixture = _setup(tmp_path)
    current_key = recipes.extraction_key
    with monkeypatch.context() as old:
        old.setattr(recipes, "EXTRACTOR_VERSION", old_version)
        old.setattr(recipes, "extraction_key", partial(current_key, extractor_version=old_version))
        assert _run(cfg, pages, model).ok
    conn = db.connect(cfg.db_path)
    previous = dict(conn.execute("SELECT * FROM recipe_versions").fetchone())
    conn.close()
    assert recipes.EXTRACTOR_VERSION == "wel48_extractor_v4"
    assert _run(cfg, pages, ModelClient("fixture", 10, fixture_fn=fixture)).ok
    conn = db.connect(cfg.db_path)
    rows = [dict(x) for x in conn.execute("SELECT * FROM recipe_versions ORDER BY id")]
    assert len(rows) == 2 and rows[0] == previous
    assert rows[1]["extractor_version"] == "wel48_extractor_v4"
    assert conn.execute("SELECT COUNT(*) FROM inference_calls WHERE purpose='recipe_extraction'").fetchone()[0] == 2
    conn.close()
