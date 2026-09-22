import copy
import json
import sqlite3
from datetime import datetime, timezone

import pytest

from research import db, knowledge, report, source_registry as registry
from research.extract import Extracted
from research.fetch import FetchResult
from research import evidence as evidence_store
from research.lock import StoreLock
from tests.wel51_helpers import (PITA, RICE, counts, latest, make_store, roster, seed_corpus,
                                 seed_literal)


def _synth(path):
    return knowledge.synthesize(path)


def _finding_id(conn):
    return int(conn.execute("SELECT id FROM findings").fetchone()[0])


def _render(conn):
    return report.render(conn, now=datetime(2026, 9, 21, 20, 0, tzinfo=timezone.utc))


def test_m1_migration_8_rerunnable(tmp_path, monkeypatch):
    original = list(db.MIGRATIONS)
    monkeypatch.setattr(db, "MIGRATIONS", [item for item in original if item[0] <= 7])
    conn = db.connect(tmp_path / "db.sqlite")
    assert db.migrate(conn) == 7
    conn.executescript(original[-1][1][0])
    assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN ('findings','finding_links','finding_versions')").fetchone()[0] == 1
    assert conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == 7
    monkeypatch.setattr(db, "MIGRATIONS", original)
    assert db.migrate(conn) == 8
    assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN ('findings','finding_links','finding_versions')").fetchone()[0] == 3
    assert conn.execute("SELECT COUNT(*) FROM schema_version WHERE version=8").fetchone()[0] == 1
    assert db.migrate(conn) == 8


def test_fixture_roster_passes_real_validate(tmp_path):
    value = roster()
    assert registry.validate(value) is None
    conn = make_store(tmp_path / "db.sqlite", project_roster=False)
    result = registry.project(conn, value)
    assert result["surface_count"] == 26
    assert registry.resolve(conn, "https://mirror.example/easy-chicken-and-rice-casserole/")["root_publisher_id"] == "fixture_mirror"
    assert registry.effective_denied(conn, "https://mirror.example/easy-chicken-and-rice-casserole/") is None


def test_bounded_investigation_counts(tmp_path):
    path = tmp_path / "db.sqlite"; conn, _ = seed_corpus(path); conn.close(); result = _synth(path)
    conn = db.connect(path)
    assert result["counts"] == counts(conn) == (1, 4, 1)
    assert tuple(conn.execute("SELECT relation,COUNT(*) FROM finding_links GROUP BY relation ORDER BY relation").fetchall()[i][1] for i in range(2)) == (1, 3)
    assert tuple(r[0] for r in conn.execute("SELECT basis FROM finding_links ORDER BY id")) == ("inferred", "inferred", "inferred", "observed")


def test_independent_support_is_two(tmp_path):
    path = tmp_path / "db.sqlite"; conn, _ = seed_corpus(path); conn.close(); _synth(path); conn = db.connect(path)
    value = knowledge.independent_support(conn, _finding_id(conn))
    assert value["independent_publisher_count"] == 2
    assert value["components"] == [["fixture_mirror", "public_domain_recipes"], ["foss_family_recipes"]]


def test_duplicate_adds_zero_independent(tmp_path):
    full = tmp_path / "full.sqlite"; conn, _ = seed_corpus(full); conn.close(); _synth(full); conn = db.connect(full)
    value = knowledge.independent_support(conn, _finding_id(conn))
    assert value["distinct_roots"] == 3 and value["independent_publisher_count"] == 2
    plain = tmp_path / "plain.sqlite"; conn, _ = seed_corpus(plain, mirror=False); conn.close(); _synth(plain); conn = db.connect(plain)
    assert knowledge.independent_support(conn, _finding_id(conn))["independent_publisher_count"] == 2


def test_unattributed_support_not_counted(tmp_path):
    path = tmp_path / "db.sqlite"; conn, _ = seed_corpus(path)
    seed_literal(conn, 1, url="https://offroster.example/x", content_kind="fixture"); conn.close(); _synth(path); conn = db.connect(path)
    value = knowledge.independent_support(conn, _finding_id(conn))
    assert value["unattributed_supports"] == ["https://offroster.example/x"]
    assert value["independent_publisher_count"] == 2


def test_qualifier_forces_unresolved(tmp_path):
    path = tmp_path / "db.sqlite"; conn, _ = seed_corpus(path); conn.close(); _synth(path); conn = db.connect(path)
    version = latest(conn); accounting = knowledge.independent_support(conn, _finding_id(conn)); text = _render(conn)
    assert (version["state"], len(json.loads(version["unresolved"]))) == ("pending", 1)
    assert accounting["unattributed_qualifiers"] == ["https://fixture.example/f-a"]
    assert "Total Time: 20 minutes" in text and "⏲️ Prep time: 5 min" in text


def test_no_total_is_ever_derived(tmp_path):
    path = tmp_path / "db.sqlite"; conn, _ = seed_corpus(path); conn.close(); _synth(path); conn = db.connect(path)
    row = conn.execute("SELECT basis_detail FROM finding_links fl JOIN evidence e ON e.id=fl.evidence_id WHERE e.url LIKE 'https://publicdomainrecipes.com/%'").fetchone()
    detail = json.loads(row[0]); stated = detail["stated"]
    assert [x["field"] for x in stated] == ["prep_time", "cook_time"]
    assert [x["literal"] for x in stated] == ["⏲️ Prep time: 5 min", "🍳 Cook time: 40 min"]
    evidence = conn.execute("SELECT t.text FROM evidence e JOIN evidence_text t ON t.evidence_id=e.id WHERE e.url LIKE 'https://publicdomainrecipes.com/%'").fetchone()[0]
    assert all(evidence[x["span"]["start"]:x["span"]["end"]] == x["literal"] for x in stated)
    assert "total_minutes" not in latest(conn)["statement"]


def test_fixture_links_are_labelled(tmp_path):
    path = tmp_path / "db.sqlite"; conn, _ = seed_corpus(path); conn.close(); _synth(path); conn = db.connect(path)
    assert knowledge.independent_support(conn, _finding_id(conn))["fixture_links"] == 2


def test_followup_is_exactly_one_and_unexecuted(tmp_path):
    path = tmp_path / "db.sqlite"; conn, _ = seed_corpus(path)
    before = tuple(conn.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0] for table in ("fetch_attempts", "inference_calls")); conn.close()
    _synth(path); conn = db.connect(path); version = latest(conn); followup = json.loads(version["followup"]); view = knowledge.current_followup(conn, version)
    assert version["followup_state"] == "proposed" and followup["target_surface_url"] == PITA
    assert followup["decision_inputs"]["target"]["access_status"] == "permitted" and followup["decision_inputs"]["target"]["evidence_rows"] == 0
    assert followup["decision_inputs"]["supporting_roots"] == ["fixture_mirror", "foss_family_recipes", "public_domain_recipes"]
    assert tuple(followup["bounds"][k] for k in ("max_depth", "max_pages", "max_model_calls")) == (1, 1, 1)
    assert (view["status"], view["actionable_target_url"]) == ("eligible", PITA)
    after = tuple(conn.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0] for table in ("fetch_attempts", "inference_calls"))
    assert before == after


def test_followup_refused_without_target(tmp_path):
    denied = roster(access={PITA: "denied", RICE: "denied"})
    path = tmp_path / "db.sqlite"; conn, _ = seed_corpus(path, roster_value=denied); conn.close(); _synth(path); conn = db.connect(path)
    version = latest(conn); followup = json.loads(version["followup"]); view = knowledge.current_followup(conn, version)
    assert (version["followup_state"], followup["reason"]) == ("refused", "no permitted uncollected surface for topic recipe_supply")
    assert view["status"] == "refused" and view["actionable_target_url"] is None


def test_single_source_needs_no_corroboration(tmp_path):
    path = tmp_path / "db.sqlite"; conn, _ = seed_corpus(path, mirror=False, orzo=False, qualifier=False); conn.close(); _synth(path); conn = db.connect(path)
    version = latest(conn); view = knowledge.current_followup(conn, version)
    assert (knowledge.independent_support(conn, _finding_id(conn))["independent_publisher_count"], version["followup_state"], version["state"], view["status"]) == (1, "none", "pending", "none")


def test_followup_permitted_to_withdrawn_no_support_change(tmp_path):
    path = tmp_path / "db.sqlite"; initial = roster(); conn, _ = seed_corpus(path, roster_value=initial); conn.close(); _synth(path); conn = db.connect(path)
    v = latest(conn); f0 = (v["followup_state"], v["followup"]); t0 = counts(conn); assert knowledge.current_followup(conn, v)["status"] == "eligible"
    registry.project(conn, roster(access={PITA: "denied"})); conn.close(); _synth(path); conn = db.connect(path); v = latest(conn); view = knowledge.current_followup(conn, v)
    assert counts(conn) == t0 == (1, 4, 1) and (v["followup_state"], v["followup"]) == f0
    assert view["status"] == "withdrawn" and view["withdrawn_reasons"] == [registry.effective_denied(conn, PITA)]
    assert view["withdrawn_reasons"][0].startswith("registry: effective-denied (retain/denied)") and view["actionable_target_url"] is None
    text = _render(conn); assert "Recorded proposal (historical" in text and "Current eligibility" in text and "withdrawn" in text
    assert "Actionable target: " + PITA not in text
    registry.project(conn, initial); v = latest(conn); assert (knowledge.current_followup(conn, v)["status"], knowledge.current_followup(conn, v)["actionable_target_url"]) == ("eligible", PITA)
    assert counts(conn) == t0 and (v["followup_state"], v["followup"]) == f0


def test_followup_withdrawn_to_permitted_no_support_change(tmp_path):
    denied = roster(access={PITA: "denied", RICE: "denied"})
    path = tmp_path / "db.sqlite"; conn, _ = seed_corpus(path, roster_value=denied); conn.close(); _synth(path); conn = db.connect(path)
    v = latest(conn); f0 = (v["followup_state"], v["followup"]); t0 = counts(conn); assert f0[0] == "refused"
    registry.project(conn, roster(access={RICE: "denied"})); conn.close(); _synth(path); conn = db.connect(path); v = latest(conn); view = knowledge.current_followup(conn, v)
    assert counts(conn) == t0 == (1, 4, 1) and (v["followup_state"], v["followup"]) == f0
    assert (view["status"], view["actionable_target_url"]) == ("newly_eligible", PITA) and view["recorded"]["target_surface_url"] is None
    assert "newly_eligible" in _render(conn)
    registry.project(conn, denied); view = knowledge.current_followup(conn, latest(conn)); assert (view["status"], view["actionable_target_url"]) == ("refused", None)


def test_followup_evidence_availability_withdraws(tmp_path):
    path = tmp_path / "db.sqlite"; conn, _ = seed_corpus(path); conn.close(); _synth(path); conn = db.connect(path)
    f0 = (latest(conn)["followup_state"], latest(conn)["followup"]); t0 = counts(conn)
    text = "fixture target evidence"
    ex = Extracted("Fixture", text, text, __import__("hashlib").sha256(text.encode()).hexdigest(), None, "unknown", None, [], {"locator_version": "wel48_locator_v5", "recipes": []})
    fetched = FetchResult(PITA, "ok", "2026-09-21T00:00:00Z", 200, PITA, "allowed", html="fixture")
    evidence_store.store_evidence(conn, {"url": PITA, "source_type": "publication", "access_basis": "fixture", "attribution": "Fixture"}, fetched, ex, "fixture")
    conn.close(); _synth(path); conn = db.connect(path); v = latest(conn); view = knowledge.current_followup(conn, v)
    assert counts(conn) == t0 and (v["followup_state"], v["followup"]) == f0
    assert view["status"] == "withdrawn" and view["withdrawn_reasons"] == ["evidence now exists for target"] and view["actionable_target_url"] is None


def test_followup_stale_version_not_actionable(tmp_path):
    path = tmp_path / "db.sqlite"; conn, rows = seed_corpus(path); conn.close(); _synth(path); conn = db.connect(path)
    conn.execute("UPDATE recipe_versions SET state='rejected',state_set_by='human:reviewer' WHERE id=?", (rows["E2"]["version_id"],))
    view = knowledge.current_followup(conn, latest(conn)); assert (view["status"], view["actionable_target_url"]) == ("stale_version", None) and counts(conn) == (1, 4, 1)
    conn.close(); _synth(path); conn = db.connect(path); assert counts(conn)[2] == 2
    view = knowledge.current_followup(conn, latest(conn)); assert (view["status"], view["actionable_target_url"]) == ("eligible", PITA)


def test_r1_report_regenerates(tmp_path):
    from research import worker
    path = tmp_path / "db.sqlite"; conn, _ = seed_corpus(path); conn.close(); _synth(path)
    out = tmp_path / "report.md"; assert worker.main(["report", "--db", str(path), "--report", str(out)]) == 0
    conn = db.connect(path); now = datetime(2026, 9, 21, 20, 0, tzinfo=timezone.utc)
    assert report.render(conn, now=now) == report.render(conn, now=now)
    text = out.read_text(); assert all(heading in text for heading in ("What we know", "Why we believe it", "What remains uncertain", "What to investigate next"))


def test_span_mismatch_writes_no_link(tmp_path):
    path = tmp_path / "db.sqlite"; conn = make_store(path); row = seed_literal(conn, 1)
    conn.execute("UPDATE evidence_text SET text='mismatch' WHERE evidence_id=?", (row["evidence_id"],)); conn.close()
    result = _synth(path); conn = db.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM finding_links WHERE recipe_version_id=?", (row["version_id"],)).fetchone()[0] == 0
    assert len(result["failures"]) == 1


def test_review_requires_human(tmp_path):
    path = tmp_path / "db.sqlite"; conn, _ = seed_corpus(path); conn.close(); _synth(path); conn = db.connect(path); version = latest(conn); conn.close()
    with pytest.raises(knowledge.KnowledgeRefused): knowledge.review(path, version["id"], "approved", "worker", "no")
    conn = db.connect(path); assert tuple(conn.execute("SELECT state,state_set_by FROM finding_versions").fetchone()) == ("pending", "worker")


def test_locked_store_writes_nothing(tmp_path):
    path = tmp_path / "db.sqlite"; conn, _ = seed_corpus(path); conn.close(); lock = StoreLock(path); assert lock.acquire()
    try: assert knowledge.main(["synthesize", "--db", str(path)]) != 0
    finally: lock.release()
    conn = db.connect(path); assert counts(conn) == (0, 0, 0)


def test_relation_vocabulary_is_closed(tmp_path):
    conn = make_store(tmp_path / "db.sqlite")
    conn.execute("INSERT INTO findings(finding_key,topic,claim_slug,created_at) VALUES('k','recipe_supply','x','t')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO finding_links(finding_id,relation,evidence_id,evidence_content_hash,recipe_version_id,content_fingerprint,basis,basis_detail,rule,observed_at) VALUES(1,'related_to',1,'h',1,'f','inferred','{}','r','t')")


def test_unknown_rule_is_read_only(tmp_path):
    path = tmp_path / "db.sqlite"; conn, _ = seed_corpus(path); conn.close(); _synth(path); conn = db.connect(path)
    conn.execute("UPDATE finding_versions SET rule='wel51_future_rule',statement=?", (json.dumps({"claim": "future stored statement", "links": [], "independent_support": {}}),)); before = counts(conn); conn.close()
    with pytest.raises(knowledge.KnowledgeRefused): _synth(path)
    conn = db.connect(path); assert counts(conn) == before and "future stored statement" in _render(conn)


def test_empty_store_report_is_unchanged(tmp_path):
    conn = make_store(tmp_path / "db.sqlite")
    assert "Retained knowledge" not in _render(conn)


def test_wel51_writes_no_publication(tmp_path):
    path = tmp_path / "db.sqlite"; conn, _ = seed_corpus(path); conn.close(); _synth(path); conn = db.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM recipe_publications").fetchone()[0] == 0
