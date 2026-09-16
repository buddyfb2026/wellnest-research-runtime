"""WEL-43: honest source yield reporting, bounded exploration and one frozen comparison.

Every test is offline and deterministic; the autouse `_no_network` fixture in conftest fails any
test that touches the network, and no test here creates a model client other than the existing
fixture provider.
"""
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from research import db as dbm
from research import evaluate, quality, rules
from research import schedule as sch
from research import sentence_integrity as challenger
from research import worker
from research.candidates import human_review
from research.model import ModelClient
from tests.conftest import (AIR_FRYER_ARTICLE, ARTICLE, air_fryer_proposal, entry, good_proposal,
                            make_transport, write_allowlist)

T0 = datetime(2026, 9, 15, 0, 0, tzinfo=timezone.utc)
H, D = timedelta(hours=1), timedelta(days=1)
HTML = {"content-type": "text/html"}
U_RULE = "https://fixture.example/air-fryer/"
U_PLAIN = "https://fixture.example/how-often-clean/"


class Clock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t

    def at(self, t):
        self.t = t
        return self


def proposals(text, meta):
    return air_fryer_proposal(text, meta) if "air fryer" in text.lower() else good_proposal(text, meta)


def cycle(cfg, pages, clock, model=None, due_only=True):
    t = make_transport(pages)
    res = worker.run(cfg, transport=t, model=model or ModelClient("fixture", 10, fixture_fn=proposals, daily_cap=10),
                     content_kind="fixture", clock=clock, due_only=due_only)
    return res, t


def two_source_store(cfg, tmp_path, clock, model=None):
    write_allowlist(tmp_path, [entry(U_RULE), entry(U_PLAIN)])
    pages = {U_RULE: (200, U_RULE, HTML, AIR_FRYER_ARTICLE), U_PLAIN: (200, U_PLAIN, HTML, ARTICLE)}
    res, _ = cycle(cfg, pages, clock, model=model)
    assert res.ok, res["failures"]
    return pages


def open_store(cfg):
    conn = dbm.connect(cfg.db_path)
    dbm.migrate(conn)
    return conn


# ---- AC1: honest yield, explicit denominators, unknown is not success -------------------------

def test_quality_report_denominators_mark_unknown_not_success(cfg, tmp_path):
    clock = Clock()
    two_source_store(cfg, tmp_path, clock)
    conn = open_store(cfg)
    d = quality.collect(conn, now=T0)

    assert d["documents"] == 2 and d["distinct_urls"] == 2 and d["evidence_rows"] == 2
    assert sum(d["classes"].values()) == d["candidates"], "every candidate lands in exactly one class"
    assert d["human_reviewed"] == 0
    assert d["classes"]["rule_supported_unreviewed"] == 1
    assert d["classes"]["model_proposal_unregistered"] == 2
    assert d["classes"]["unknown"] == 0

    text = quality.render(conn, now=T0)
    assert "No rates and no ranking are shown" in text
    assert "The sample unit is a **distinct document**" in text
    assert "## What remains unknown" in text
    assert "no reviewer has scored factual support (0 of 3 candidates carry a human decision)" in text
    assert "1 source(s) have evidence" in text
    assert "%" not in text.replace("100%", ""), "no rate is printed anywhere"

    # A human decision is a review state, never a household outcome.
    cid = conn.execute("SELECT id FROM candidates WHERE state='pending'").fetchone()[0]
    conn.execute("BEGIN")
    human_review(conn, cid, "approved", "astra", "reviewed the quote")
    conn.execute("COMMIT")
    text2 = quality.render(conn, now=T0)
    assert quality.collect(conn, now=T0)["classes"]["human_approved"] == 1
    assert "not evidence that any household did anything" in text2
    assert "Whether any candidate **helped a household**" in text2
    conn.close()


def test_rule_coverage_gap_is_not_scored_as_source_failure(cfg, tmp_path):
    clock = Clock()
    two_source_store(cfg, tmp_path, clock)
    conn = open_store(cfg)
    d = quality.collect(conn, now=T0)

    plain_id = conn.execute("SELECT id FROM evidence WHERE url=?", (U_PLAIN,)).fetchone()[0]
    assert plain_id in d["evidence_without_rule_match"]
    # The document collected fine; nothing about it is recorded as a failed or bad source.
    host = d["hosts"]["fixture.example"]
    assert host["attempts"]["ok"] == 2 and host["attempts"].get("blocked", 0) == 0 and host["attempts"].get("error", 0) == 0
    assert host["classes"].get("human_rejected", 0) == 0

    text = quality.render(conn, now=T0)
    assert "## Coverage gaps (NOT source failures)" in text
    assert "evidence with no registered rule match | 1" in text
    assert "not a source failure" in text or "not source failures" in text
    conn.close()


def test_provider_none_is_a_coverage_gap_not_a_rejected_candidate(cfg, tmp_path):
    clock = Clock()
    two_source_store(cfg, tmp_path, clock, model=ModelClient("none", 10, daily_cap=10))
    conn = open_store(cfg)
    d = quality.collect(conn, now=T0)
    assert d["classes"]["no_inference_provider"] == 2
    assert d["classes"]["human_rejected"] == 0 and d["classes"]["unknown"] == 0
    text = quality.render(conn, now=T0)
    assert "candidates with no model available | 2" in text
    conn.close()


def test_refetch_same_hash_does_not_inflate_sample(cfg, tmp_path):
    clock = Clock()
    pages = two_source_store(cfg, tmp_path, clock)
    conn = open_store(cfg)
    before = quality.collect(conn, now=T0)
    conn.close()

    res, _ = cycle(cfg, pages, clock.at(T0 + 7 * D))          # unchanged content, both due again
    assert res.ok and res["evidence_existing"] == 2 and res["evidence_new"] == 0

    conn = open_store(cfg)
    after = quality.collect(conn, now=T0 + 7 * D)
    assert after["documents"] == before["documents"] == 2, "a re-fetch is an attempt, not a new document"
    assert after["attempts_total"] == before["attempts_total"] + 2
    assert after["unchanged_refetch"] == 2
    assert after["candidates"] == before["candidates"]
    assert "| distinct documents (sample unit) | 2 |" in quality.render(conn, now=T0 + 7 * D)
    conn.close()


# ---- AC2: bounded exploration after the permitted / not-stalled / due gates --------------------

def make_state(tmp_path, rows, name="explore.sqlite"):
    """rows: (url, attempts, next_check_at, stalled, permitted, with_hint)"""
    conn = dbm.connect(tmp_path / name)
    dbm.migrate(conn)
    for url, attempts, next_at, stalled, permitted, with_hint in rows:
        if with_hint:
            conn.execute("INSERT INTO source_hints(url, source_type, access_basis, fetch_permitted, "
                         "first_seen_at, last_seen_at) VALUES(?,?,?,?,?,?)",
                         (url, "publication", "fixture", permitted, sch.iso(T0), sch.iso(T0)))
        conn.execute("INSERT INTO source_state(url, next_check_at, attempts, stalled, updated_at) "
                     "VALUES(?,?,?,?,?)", (url, sch.iso(next_at), attempts, stalled, sch.iso(T0)))
    return conn


def test_exploration_reserve_small_batch_rounding_and_empty_pool(tmp_path):
    winner_a, winner_b, winner_c, fresh_1, fresh_2 = ("https://s.example/a/", "https://s.example/b/",
                                                      "https://s.example/c/", "https://s.example/new1/",
                                                      "https://s.example/new2/")
    conn = make_state(tmp_path, [
        (winner_a, 9, T0 - 3 * H, 0, 1, True),
        (winner_b, 7, T0 - 2 * H, 0, 1, True),
        (winner_c, 5, T0 - 1 * H, 0, 1, True),
        (fresh_1, 0, T0, 0, 1, True),
        (fresh_2, 0, T0, 0, 1, True),
    ])
    now = T0

    s1 = sch.select_cycle_urls(conn, now, 1)          # floor(1/3)=0 -> minimum one reserved slot
    assert s1["reserved_slots"] == 1 and s1["exploration"] == [fresh_1] and s1["selected"] == [fresh_1]

    s3 = sch.select_cycle_urls(conn, now, 3)          # floor(3/3)=1 reserved, 2 incumbent
    assert s3["reserved_slots"] == 1 and s3["exploration"] == [fresh_1]
    assert s3["exploitation"] == [winner_a, winner_b]
    assert s3["selected"] == [winner_a, winner_b, fresh_1], "request order stays the incumbent order"

    s6 = sch.select_cycle_urls(conn, now, 6)          # limit above the pool: everything, no duplicates
    assert len(s6["selected"]) == 5 == len(set(s6["selected"]))

    assert sch.select_cycle_urls(conn, now, 0)["selected"] == []                       # no slots, no work
    assert sch.select_cycle_urls(conn, T0 - 5 * H, 3)["selected"] == []                # nothing due yet
    assert sch.select_cycle_urls(conn, T0 - 5 * H, 3)["reserved_slots"] == 0

    # No unexplored source: the reserve is not invented, incumbent order is kept exactly.
    conn.execute("UPDATE source_state SET attempts=4 WHERE url IN (?,?)", (fresh_1, fresh_2))
    s = sch.select_cycle_urls(conn, now, 3)
    assert s["reserved_slots"] == 0 and s["exploration"] == []
    assert s["selected"] == [winner_a, winner_b, winner_c] == sch.due_urls(conn, now, 3)
    conn.close()


def test_exploration_cannot_select_stalled_or_unpermitted(tmp_path):
    blocked, denied, orphan, ok = ("https://s.example/stalled/", "https://s.example/denied/",
                                   "https://s.example/orphan/", "https://s.example/ok/")
    conn = make_state(tmp_path, [
        (blocked, 0, T0 - H, 1, 1, True),      # never attempted, but stalled
        (denied, 0, T0 - H, 0, 0, True),       # never attempted, but no permitted access basis
        (orphan, 0, T0 - H, 0, 1, False),      # scheduling row with no source hint at all
        (ok, 3, T0 - H, 0, 1, True),
    ])
    s = sch.select_cycle_urls(conn, T0, 3)
    assert s["selected"] == [ok] and s["exploration"] == [] and s["reserved_slots"] == 0
    for url in (blocked, denied, orphan):
        assert url not in s["selected"]
    conn.close()


def test_exploration_does_not_starve_new_sources_or_hold_the_reserve_forever(cfg, tmp_path):
    """Three due sources, one slot per cycle: the incumbent cannot own every cycle, and an explored
    source stops consuming the reserve."""
    u1, u2, u3 = "https://fixture.example/a/", "https://fixture.example/b/", "https://fixture.example/c/"
    write_allowlist(tmp_path, [entry(u1), entry(u2), entry(u3)])
    pages = {u: (200, u, HTML, ARTICLE) for u in (u1, u2, u3)}
    cfg.max_urls = 1
    clock = Clock()

    r1, _ = cycle(cfg, pages, clock)
    assert r1["exploration_selected"] == 1 and r1["fetched_ok"] == 1
    r2, _ = cycle(cfg, pages, clock.at(T0 + H))
    assert r2["exploration_selected"] == 1 and r2["fetched_ok"] == 1

    conn = open_store(cfg)
    attempted = {r["url"] for r in conn.execute("SELECT url FROM source_state WHERE attempts>0").fetchall()}
    remaining = {u1, u2, u3} - attempted
    assert len(attempted) == 2 and len(remaining) == 1
    conn.close()

    # u1 is due again now and sorts first; the single slot still goes to the never-attempted source.
    r3, t3 = cycle(cfg, pages, clock.at(T0 + 7 * D + 2 * H))
    assert r3["exploration_selected"] == 1 and [c for c in t3.calls if not c.endswith("robots.txt")] == list(remaining)

    # Everything has been attempted: the reserve disappears and the incumbent order returns.
    r4, t4 = cycle(cfg, pages, clock.at(T0 + 7 * D + 3 * H))
    assert r4["exploration_selected"] == 0 and r4["exploitation_selected"] == 1
    assert [c for c in t4.calls if not c.endswith("robots.txt")] == [u1]


def test_exploration_keeps_slot_count_and_cannot_exceed_the_url_cap(cfg, tmp_path):
    urls = ["https://fixture.example/%d/" % i for i in range(5)]
    write_allowlist(tmp_path, [entry(u) for u in urls])
    pages = {u: (200, u, HTML, ARTICLE) for u in urls}
    cfg.max_urls = 2
    res, t = cycle(cfg, pages, Clock())
    assert res["fetched_ok"] == 2 and len([c for c in t.calls if not c.endswith("robots.txt")]) == 2
    assert res["exploration_selected"] + res["exploitation_selected"] == 2
    assert res["not_due"] == 3 and res["stalled"] == 0


# ---- AC3: frozen comparison, held-out documents, review-gated adoption -------------------------

def test_evaluation_manifest_hash_and_unchanged_variant_reproduces(tmp_path):
    out = tmp_path / "manifest.json"
    assert evaluate.main(["freeze", "--out", str(out)]) == 0
    man = json.loads(out.read_text())
    assert man["budget"] == {"model_calls": 0, "network_requests": 0}
    assert set(man["files"]) >= {"research/rules.py", "research/sentence_integrity.py", "eval/wel43/rubric.md",
                                 "eval/wel43/dev_cases.json"}
    assert evaluate.check_manifest(out) == [], "nothing drifted right after freezing"

    text = json.loads(evaluate.DEV_CASES.read_text())["cases"][0]["text"]
    assert evaluate.score_text(text, "challenger") == evaluate.score_text(text, "challenger")
    assert evaluate.score_text(text, "baseline")["deterministic"]
    assert evaluate.run_dev() == evaluate.run_dev(), "the whole dev run reproduces exactly"

    tampered = dict(man)
    tampered["files"] = dict(man["files"], **{"research/sentence_integrity.py": "0" * 64})
    p = tmp_path / "tampered.json"
    p.write_text(json.dumps(tampered))
    assert evaluate.check_manifest(p) == ["research/sentence_integrity.py"]
    # A changed challenger cannot be scored against a stale manifest: the runner refuses.
    assert evaluate.main(["dev", "--manifest", str(p)]) == 2


def test_adoption_requires_review_no_default_change(cfg, tmp_path):
    root = Path(worker.__file__).resolve().parent
    for module in ("worker.py", "rules.py", "candidates.py", "report.py", "schedule.py"):
        assert "sentence_integrity" not in (root / module).read_text(), \
            "%s must keep the incumbent segmentation" % module

    before = {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in ("rules.py", "worker.py")}
    clock = Clock()
    pages = two_source_store(cfg, tmp_path, clock)
    store_hash = hashlib.sha256(Path(cfg.db_path).read_bytes()).hexdigest()

    dev = evaluate.run_dev()
    holdout = evaluate.run_holdout(cfg.db_path)
    verdict = evaluate.decide(dev, holdout)

    assert verdict["verdict"] in ("adopt-with-review", "do-not-adopt", "inconclusive")
    assert "recommendation to a human reviewer" in verdict["note"]
    assert {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in before} == before, \
        "evaluation never edits production code"
    assert hashlib.sha256(Path(cfg.db_path).read_bytes()).hexdigest() == store_hash, \
        "evaluation never writes to the research store"

    # Collection behaviour after the evaluation is byte-identical to before it.
    res, _ = cycle(cfg, pages, clock.at(T0 + 7 * D))
    assert res.ok and res["evidence_new"] == 0 and res["candidates_new"] == 0
    assert rules.match_rules is not challenger.match_rules


def test_holdout_store_is_opened_read_only_and_never_mutated(cfg, tmp_path, monkeypatch):
    clock = Clock()
    two_source_store(cfg, tmp_path, clock)
    before = Path(cfg.db_path).read_bytes()

    uris = []
    real_connect = sqlite3.connect

    def spy(target, *a, **k):
        uris.append(target)
        return real_connect(target, *a, **k)

    monkeypatch.setattr(sqlite3, "connect", spy)
    docs = evaluate.read_holdout(cfg.db_path)
    monkeypatch.undo()

    assert docs and all("text" in d for d in docs)
    assert uris and "mode=ro" in uris[0] and "immutable=1" in uris[0]
    assert Path(cfg.db_path).read_bytes() == before


def test_challenger_rejoins_split_sentence_without_new_false_match():
    cases = {c["name"]: c for c in evaluate.load_dev_cases()}
    split = cases["split_by_block_break"]["text"]
    assert rules.match_rules(split) == [], "incumbent loses a sentence broken by a block tag"
    m = challenger.match_rules(split)
    assert len(m) == 1 and m[0].rule.rule_id == "air_fryer_basket_after_each_use"
    assert m[0].support_quote.endswith("need to be cleaned after every use.")

    for name in ("fragment_only", "negated_prefix", "question_form", "unrelated_document", "false_join_bait"):
        text = cases[name]["text"]
        assert rules.match_rules(text) == [], "%s must not match the incumbent" % name
        assert challenger.match_rules(text) == [], "%s must not become a false support match" % name


def test_challenger_does_not_change_injection_detection_or_stored_text():
    for case in evaluate.load_dev_cases():
        b = evaluate.score_text(case["text"], "baseline")
        c = evaluate.score_text(case["text"], "challenger")
        assert b["injection_flags"] == c["injection_flags"]
        assert b["deterministic"] and c["deterministic"]
    injected = [c for c in evaluate.load_dev_cases() if c["name"] == "injected_instructions"][0]
    assert evaluate.score_text(injected["text"], "challenger")["injection_flags"], "injection stays detected"


def test_hosts_without_evidence_are_not_counted_as_sources_with_evidence(cfg, tmp_path):
    """Review finding 1: a host that was only ever blocked or failed has no evidence and must not
    appear in the evidence denominator, while its attempts stay visible."""
    blocked = "https://blocked.example/secret/"
    clock = Clock()

    # Zero evidence anywhere: one host, one blocked attempt.
    write_allowlist(tmp_path, [entry(blocked)])
    pages = {blocked: (403, blocked, HTML, "denied"), blocked + "robots.txt": (200, blocked, {}, "User-agent: *\n")}
    res, _ = cycle(cfg, pages, clock)
    assert res.ok and res["blocked"] + res["errors"] == 1
    conn = open_store(cfg)
    d = quality.collect(conn, now=T0)
    assert d["documents"] == 0 and d["hosts_with_evidence"] == 0
    assert d["hosts_attempted_without_evidence"] == ["blocked.example"]
    text = quality.render(conn, now=T0)
    assert "| distinct hosts (sources) with evidence | 0 |" in text
    assert "| hosts attempted but with no evidence (blocked/failed only) | 1 |" in text
    assert "no source has evidence yet" in text
    assert "0 source(s) have evidence" in text
    assert "blocked.example" in text, "the failed host keeps its attempts row"
    conn.close()

    # Mixed: one host with evidence plus the blocked-only host is still one source with evidence.
    write_allowlist(tmp_path, [entry(blocked), entry(U_RULE), entry(U_PLAIN)])
    pages.update({U_RULE: (200, U_RULE, HTML, AIR_FRYER_ARTICLE), U_PLAIN: (200, U_PLAIN, HTML, ARTICLE)})
    res2, _ = cycle(cfg, pages, clock.at(T0 + 8 * D))
    assert res2.ok and res2["fetched_ok"] == 2
    conn = open_store(cfg)
    d2 = quality.collect(conn, now=T0 + 8 * D)
    assert d2["documents"] == 2 and d2["hosts_with_evidence"] == 1
    assert d2["hosts_attempted_without_evidence"] == ["blocked.example"]
    assert len(d2["hosts"]) == 2, "both hosts remain in the attempts table"
    text2 = quality.render(conn, now=T0 + 8 * D)
    assert "| distinct hosts (sources) with evidence | 1 |" in text2
    assert "| hosts attempted but with no evidence (blocked/failed only) | 1 |" in text2
    assert "1 source(s) have evidence" in text2
    assert "there is only one source with evidence" in text2
    conn.close()


def test_decide_requires_holdout_review_for_unclassified_differences():
    """Review finding 2: an unexamined held-out difference cannot ride on a dev-set gain."""
    dev = evaluate.run_dev()
    unclassified = {"differences": [{"evidence_id": 1, "baseline": [], "challenger": ["unsupported"]}],
                    "problems": []}
    v = evaluate.decide(dev, unclassified)
    assert v["verdict"] == "inconclusive" and v["unclassified_holdout_differences"] == 1
    assert "no human classification" in v["reason"]
    assert v["dev_verdict"] == "adopt-with-review", "the fixture-only reading is reported separately"
    assert "not evidence of a real-world improvement" in v["dev_verdict_scope"]

    labelled = {"differences": [dict(unclassified["differences"][0], review="true_gain")], "problems": []}
    assert evaluate.decide(dev, labelled)["verdict"] == "adopt-with-review"
    for bad in ("false_gain", "lost"):
        v_bad = evaluate.decide(dev, {"differences": [dict(unclassified["differences"][0], review=bad)],
                                      "problems": []})
        assert v_bad["verdict"] == "do-not-adopt", bad
    neutral = {"differences": [dict(unclassified["differences"][0], review="neutral")], "problems": []}
    assert evaluate.decide(dev, neutral)["verdict"] == "inconclusive"

    bogus = {"differences": [dict(unclassified["differences"][0], review="looks fine to me")], "problems": []}
    assert evaluate.decide(dev, bogus)["verdict"] == "inconclusive", "only the defined labels count"


def test_decide_is_inconclusive_when_the_holdout_shows_no_difference():
    """The recorded real holdout: 8 documents, zero differences. A dev gain alone is not improvement."""
    dev = evaluate.run_dev()
    v = evaluate.decide(dev, {"differences": [], "problems": []})
    assert v["verdict"] == "inconclusive" and v["holdout_differences"] == 0
    assert "no real-world effect was measured" in v["reason"]
    assert v["dev_verdict"] == "adopt-with-review"
    assert evaluate.decide(dev)["verdict"] == "adopt-with-review", "dev-only call keeps the v1 reading"
    assert evaluate.decide(dev)["reason"].startswith("no held-out evidence")


def test_recorded_comparison_and_manifest_are_preserved_as_history():
    """The review repair touched the evaluator, not the measured artefacts."""
    historical = Path(evaluate.REPO_ROOT) / "docs" / "WEL-43-eval" / "manifest.json"
    recorded = json.loads(historical.read_text())
    drift = evaluate.check_manifest(historical)
    assert set(drift) == {"research/evaluate.py", "research/rules.py"}, \
        "WEL-43 repair changed the evaluator and WEL-42 later added a rule; historical inputs stay frozen"
    for name in ("research/sentence_integrity.py", "eval/wel43/rubric.md",
                 "eval/wel43/dev_cases.json"):
        assert evaluate.sha256_file(evaluate.REPO_ROOT / name) == recorded["files"][name]
    comparison = (Path(evaluate.REPO_ROOT) / "docs" / "WEL-43-eval" / "comparison.md").read_text()
    assert "Documents where the two variants differ: 0." in comparison
    assert (Path(evaluate.REPO_ROOT) / "eval" / "wel43" / "rubric-addendum-v2.md").exists()


def test_dev_verdict_follows_the_predeclared_rule_only():
    dev = evaluate.run_dev()
    assert dev["counts"]["false_support_gained"] == 0 and dev["counts"]["support_lost"] == 0
    assert evaluate.decide(dev)["verdict"] == "adopt-with-review"

    poisoned = json.loads(json.dumps(dev))
    poisoned["counts"]["false_support_gained"] = 1
    assert evaluate.decide(poisoned)["verdict"] == "do-not-adopt"

    flat = json.loads(json.dumps(dev))
    flat["counts"] = {k: 0 for k in flat["counts"]}
    assert evaluate.decide(flat)["verdict"] == "inconclusive"

    noisy = json.loads(json.dumps(dev))
    noisy["problems"] = ["case x: injection flags differ"]
    assert evaluate.decide(noisy)["verdict"] == "do-not-adopt"


# ---- AC4: the inherited daily cap, demonstrated without any new inference machinery ------------

def test_inherited_daily_cap_demonstrated_with_fixture_provider(cfg, tmp_path):
    clock = Clock()
    write_allowlist(tmp_path, [entry(U_RULE), entry(U_PLAIN)])
    pages = {U_RULE: (200, U_RULE, HTML, AIR_FRYER_ARTICLE), U_PLAIN: (200, U_PLAIN, HTML, ARTICLE)}
    capped = lambda: ModelClient("fixture", 10, fixture_fn=proposals, daily_cap=1)

    r1, _ = cycle(cfg, pages, clock, model=capped())
    assert r1["inference_calls"] == 1 and r1["budget_deferred"] == 1
    r2, _ = cycle(cfg, pages, clock.at(T0 + 2 * H), model=capped())      # restart cannot reset the day
    assert r2["inference_calls"] == 0 and r2["inference_used_today"] == 1

    conn = open_store(cfg)
    d = quality.collect(conn, now=T0 + 2 * H)
    assert d["inference_calls"] == 1 and d["inference_by_status"]["ok"] == 1
    assert d["classes"]["waiting_inference_budget"] == 1
    text = quality.render(conn, now=T0 + 2 * H)
    assert "| inference calls recorded | 1 |" in text
    assert "candidates waiting for inference budget | 1" in text
    conn.close()


def test_quality_and_evaluation_make_no_model_call(cfg, tmp_path, monkeypatch):
    clock = Clock()
    two_source_store(cfg, tmp_path, clock)
    monkeypatch.setattr(ModelClient, "propose",
                        lambda *a, **k: pytest.fail("reporting must never call a model"))
    conn = open_store(cfg)
    quality.render(conn, now=T0)
    conn.close()
    evaluate.run_dev()
    evaluate.run_holdout(cfg.db_path)
