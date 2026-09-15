"""WEL-42 producer export gates.

Every rule/candidate used here is an EXPLICITLY SYNTHETIC fixture. `SYNTHETIC_MEAL_RULE` is not in
research/rules.py and its "evidence" is invented test text. These tests prove the export gates
behave correctly; they prove nothing about any real-world food-safety fact.
"""
import hashlib
import json
import re
from pathlib import Path

import pytest

from research.candidates import build_rule_candidate, save_candidate
from research.db import connect, migrate
from research.rules import match_rules
from research.meal_export import (
    MEAL_APPLICABILITY,
    MEAL_EXPORT_CAPABILITY,
    MEAL_EXPORT_PAYLOAD_VERSION,
    MealApplicability,
    export_meal_details,
)
from research.rules import RULES as REAL_RULES, SupportRule

# ---- explicitly synthetic fixtures -------------------------------------------------------------

SYNTHETIC_SUPPORT = "Synthetic fixture sentence: cook the sheet-pan chicken until it is done through."

SYNTHETIC_MEAL_RULE = SupportRule(
    rule_id="synthetic_meal_guidance_fixture",
    version=1,
    action="SYNTHETIC FIXTURE: fixed reviewer-authored guidance text for the test template.",
    relevance="synthetic fixture relevance",
    support_sentences=(SYNTHETIC_SUPPORT,),
    problem_sentences=("Synthetic fixture problem sentence.",),
    review_note="SYNTHETIC: invented for tests, never read from a real source.",
)

SYNTHETIC_RULES = (SYNTHETIC_MEAL_RULE,)

SYNTHETIC_APPLICABILITY = {
    "synthetic_meal_guidance_fixture": MealApplicability(
        template_name="Sheet-pan chicken and vegetables",
        required_ingredients=("chicken",),
    )
}


def rule_validation(**overrides):
    v = {
        "kind": "rule",
        "rule_id": "synthetic_meal_guidance_fixture",
        "rule_version": 1,
        "support_quote": SYNTHETIC_SUPPORT,
        "problem_quote": "Synthetic fixture problem sentence.",
        "model_inference": False,
        "review_note": "SYNTHETIC",
    }
    v.update(overrides)
    return v


SYNTHETIC_TEXT = SYNTHETIC_SUPPORT + "\nSynthetic fixture problem sentence."
SYNTHETIC_HASH = hashlib.sha256(SYNTHETIC_TEXT.encode("utf-8")).hexdigest()


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "db.sqlite")
    migrate(c)
    c.execute(
        """INSERT INTO evidence(id, url, content_kind, content_hash, version_no, fetched_at, published_at,
                published_at_basis, title, attribution, source_type, access_basis, excerpt, text_chars,
                injection_flags)
           VALUES(1, 'https://fixture.example/synthetic', 'fixture', ?, 2,
                  '2026-09-15T00:00:00Z', '2026-01-02T00:00:00Z', 'meta:datePublished',
                  'Synthetic Fixture', 'Synthetic Fixture Publisher', 'publication', 'fixture',
                  'excerpt', 120, '[]')""",
        (SYNTHETIC_HASH,),
    )
    c.execute("INSERT INTO evidence_text(evidence_id, text) VALUES(1, ?)", (SYNTHETIC_TEXT,))
    c.commit()
    return c


def add_candidate(conn, *, cid=1, state="approved", set_by="human:Spencer", publishable=1,
                  validation=None, evidence_id=1, dedupe="key-1"):
    conn.execute(
        """INSERT INTO candidates(id, dedupe_key, evidence_id, generator, observations, inferences,
                unsupported_claims, relevance_conditions, product_mentions, source_attribution,
                stock_price_claims, state, state_reason, state_set_by, publishable, validation,
                created_at, updated_at)
           VALUES(?,?,?,?,'[]','[]','[]','[]','[]','Synthetic Fixture Publisher','not_verified',
                  ?,?,?,?,?, '2026-09-15T00:00:00Z','2026-09-15T00:00:00Z')""",
        (cid, dedupe, evidence_id, "rule:synthetic_meal_guidance_fixture@1", state, "test", set_by,
         publishable, json.dumps(validation if validation is not None else rule_validation())),
    )
    conn.commit()
    return cid


def run(conn):
    """Synthetic evidence is content_kind='fixture', so these tests must opt in explicitly.
    Production callers never pass this flag; see test_fixture_evidence_is_refused_by_default."""
    return export_meal_details(conn, SYNTHETIC_APPLICABILITY, SYNTHETIC_RULES,
                               allow_fixture_evidence=True)


def only_reason_contains(payload, fragment):
    assert payload["details"] == []
    reasons = " ".join(r for o in payload["omitted"] for r in o["reasons"])
    assert fragment in reasons, reasons


# ---- the registry ships with no real meal rule yet ----------------------------------------------

def test_registered_applicability_rules_all_exist_in_the_rule_registry():
    """Applicability may only reference rules whose support sentences were read in real evidence."""
    registered = {r.rule_id for r in REAL_RULES}
    for rule_id in MEAL_APPLICABILITY:
        assert rule_id in registered, "%s has applicability but no SupportRule" % rule_id


# ---- the happy path ----------------------------------------------------------------------------

def test_approved_publishable_rule_candidate_exports_full_detail(conn):
    add_candidate(conn)
    payload = run(conn)

    assert payload["payload_version"] == MEAL_EXPORT_PAYLOAD_VERSION
    assert payload["capability"] == MEAL_EXPORT_CAPABILITY
    assert len(payload["details"]) == 1
    d = payload["details"][0]

    assert d["candidate"]["state"] == "approved"
    assert d["candidate"]["state_set_by"] == "human:Spencer"
    assert d["candidate"]["rule_id"] == "synthetic_meal_guidance_fixture"
    assert d["candidate"]["rule_version"] == 1

    assert d["applicability"] == {
        "kind": "meal_template",
        "template_name": "Sheet-pan chicken and vegetables",
        "required_ingredients": ["chicken"],
    }

    # Displayed guidance is fixed rule text; the passage is the whole evidence sentence.
    assert d["guidance"]["text"] == SYNTHETIC_MEAL_RULE.action
    assert d["guidance"]["supporting_passage"] == SYNTHETIC_SUPPORT

    assert d["evidence"]["revision"] == 2
    assert d["evidence"]["content_hash"] == SYNTHETIC_HASH
    assert d["evidence"]["source_url"] == "https://fixture.example/synthetic"
    assert d["evidence"]["attribution"] == "Synthetic Fixture Publisher"
    assert d["evidence"]["checked_at"] == "2026-09-15T00:00:00Z"


def test_export_contains_no_household_fields(conn):
    add_candidate(conn)
    blob = json.dumps(run(conn)).lower()
    for token in ("household", "kid", "sanchez", "spencer@", "prefs", "rejectedingredients"):
        if token == "household":
            # 'household' must not appear as data; the only human name is the approver attribution.
            assert "household_id" not in blob and "household_problem" not in blob
            continue
        assert token not in blob


# ---- review-state gates (AC1) ------------------------------------------------------------------

@pytest.mark.parametrize("state", ["pending", "rejected", "deferred", "weird_unknown_state"])
def test_non_approved_states_never_export(conn, state):
    add_candidate(conn, state=state)
    only_reason_contains(run(conn), "state_not_approved")


def test_publishable_zero_never_exports_even_when_approved(conn):
    add_candidate(conn, publishable=0)
    only_reason_contains(run(conn), "not_publishable")


def test_worker_set_approval_is_not_human_approval(conn):
    """A forged 'approved' written by the worker must not publish."""
    add_candidate(conn, set_by="worker")
    only_reason_contains(run(conn), "not_human_approved")


# ---- generator / schema gates ------------------------------------------------------------------

def test_free_text_model_candidate_never_exports(conn):
    add_candidate(conn, validation={"kind": "free_text", "raw_proposal": {"proposed_action": "do a thing"},
                                    "model_inference": True})
    only_reason_contains(run(conn), "not_a_rule_candidate")


def test_legacy_unvalidated_candidate_never_exports(conn):
    add_candidate(conn, validation=None)
    conn.execute("UPDATE candidates SET validation=NULL WHERE id=1")
    conn.commit()
    only_reason_contains(run(conn), "unvalidated_legacy_candidate")


def test_malformed_validation_json_is_rejected(conn):
    add_candidate(conn)
    conn.execute("UPDATE candidates SET validation='{not json' WHERE id=1")
    conn.commit()
    only_reason_contains(run(conn), "malformed_validation")


def test_unknown_rule_id_has_no_applicability(conn):
    add_candidate(conn, validation=rule_validation(rule_id="some_unregistered_rule"))
    reasons = " ".join(r for o in run(conn)["omitted"] for r in o["reasons"])
    assert "rule_not_registered_at_version" in reasons
    assert "no_registered_meal_applicability" in reasons


def test_rule_version_drift_stops_export(conn):
    """The reviewer approved v1; if the registry has moved on, v1 wording must stop publishing."""
    add_candidate(conn, validation=rule_validation(rule_version=2))
    only_reason_contains(run(conn), "rule_not_registered_at_version")


def test_missing_support_quote_is_rejected(conn):
    add_candidate(conn, validation=rule_validation(support_quote="   "))
    only_reason_contains(run(conn), "missing_support_quote")


def test_injection_flagged_evidence_never_exports(conn):
    add_candidate(conn)
    conn.execute("UPDATE evidence SET injection_flags='[\"ignore previous instructions\"]' WHERE id=1")
    conn.commit()
    only_reason_contains(run(conn), "source_embedded_instructions_flagged")


def test_missing_evidence_attribution_is_rejected(conn):
    add_candidate(conn)
    conn.execute("UPDATE evidence SET attribution='' WHERE id=1")
    conn.commit()
    only_reason_contains(run(conn), "missing_evidence_field: attribution")


# ---- determinism ------------------------------------------------------------------------------

# ---- support must be re-derived from the actual stored evidence (review finding 2) ---------------

def test_REPRO_registered_rule_with_an_invented_quote_on_unrelated_evidence_is_refused(conn):
    """An approved candidate claiming a registered rule, but whose support sentence is not in the
    evidence it points at, must not export however well-formed the row looks."""
    conn.execute("UPDATE evidence_text SET text=? WHERE evidence_id=1",
                 ("Air fryer baskets need to be cleaned after every use.\nUnrelated article body.",))
    conn.execute("UPDATE evidence SET content_hash=? WHERE id=1",
                 (hashlib.sha256(
                     "Air fryer baskets need to be cleaned after every use.\nUnrelated article body."
                     .encode()).hexdigest(),))
    conn.commit()
    add_candidate(conn)
    only_reason_contains(run(conn), "support_not_present_in_evidence")


def test_support_quote_that_differs_from_the_evidence_sentence_is_refused(conn):
    add_candidate(conn, validation=rule_validation(support_quote="Some other wording entirely."))
    only_reason_contains(run(conn), "support_quote_does_not_match_evidence")


def test_tampered_evidence_text_fails_the_hash_check(conn):
    conn.execute("UPDATE evidence_text SET text=? WHERE evidence_id=1",
                 (SYNTHETIC_TEXT + "\nSmuggled extra sentence.",))
    conn.commit()
    add_candidate(conn)
    only_reason_contains(run(conn), "evidence_text_hash_mismatch")


def test_missing_evidence_text_cannot_be_verified(conn):
    conn.execute("DELETE FROM evidence_text WHERE evidence_id=1")
    conn.commit()
    add_candidate(conn)
    only_reason_contains(run(conn), "missing_evidence_text")


# ---- fixture evidence must not publish on the production path ------------------------------------

def test_fixture_evidence_is_refused_by_default(conn):
    """The production call signature has no flag set; content_kind='fixture' must not publish."""
    add_candidate(conn)
    payload = export_meal_details(conn, SYNTHETIC_APPLICABILITY, SYNTHETIC_RULES)
    assert payload["details"] == []
    reasons = " ".join(r for o in payload["omitted"] for r in o["reasons"])
    assert "non_live_evidence" in reasons
    assert "_test_only_fixture_evidence" not in payload


def test_fixture_enabled_export_is_self_identifying(conn):
    """A snapshot built with the escape hatch is marked, so the consumer can refuse it outright."""
    add_candidate(conn)
    payload = run(conn)
    assert payload["_test_only_fixture_evidence"] is True
    assert len(payload["details"]) == 1


def test_live_evidence_needs_no_flag(conn):
    conn.execute("UPDATE evidence SET content_kind='live' WHERE id=1")
    conn.commit()
    add_candidate(conn)
    payload = export_meal_details(conn, SYNTHETIC_APPLICABILITY, SYNTHETIC_RULES)
    assert len(payload["details"]) == 1
    assert "_test_only_fixture_evidence" not in payload


# ---- producer and consumer registries must not drift ---------------------------------------------

CONSUMER_REGISTRY = Path("/tmp/wellnest-wel42-app/src/core/mealResearch.ts")


def test_consumer_registry_matches_the_producer_registries():
    """The app mirrors rule text and applicability so a payload cannot supply either. That mirror is
    only safe if the two sides agree, so compare them field by field."""
    if not CONSUMER_REGISTRY.exists():
        pytest.skip("app checkout not available")
    src = CONSUMER_REGISTRY.read_text()
    block = src.split("export const MEAL_DETAIL_RULES", 1)[1].split("];", 1)[0]

    entries = re.findall(
        r"ruleId:\s*'([^']+)',\s*"
        r"ruleVersion:\s*(\d+),\s*"
        r"text:\s*'((?:[^'\\]|\\.)*)',\s*"
        r"supportingPassages:\s*\[([^\]]*)\],\s*"
        r"templateName:\s*'((?:[^'\\]|\\.)*)',\s*"
        r"requiredIngredients:\s*\[([^\]]*)\],",
        block,
    )
    assert entries, "could not parse the consumer registry"

    exportable = {r.rule_id: r for r in REAL_RULES if r.rule_id in MEAL_APPLICABILITY}
    assert {e[0] for e in entries} == set(exportable), \
        "consumer registry and exportable producer rules do not cover the same rule ids"

    for rule_id, version, text, passages, template, ingredients in entries:
        rule = exportable[rule_id]
        applies = MEAL_APPLICABILITY[rule_id]
        strings = lambda s: [m for m in re.findall(r"'((?:[^'\\]|\\.)*)'", s)]  # noqa: E731

        assert int(version) == rule.version, "%s: version drift" % rule_id
        assert text == rule.action, "%s: guidance text drift" % rule_id
        assert strings(passages) == list(rule.support_sentences), "%s: support sentence drift" % rule_id
        assert template == applies.template_name, "%s: template drift" % rule_id
        assert strings(ingredients) == list(applies.required_ingredients), \
            "%s: required ingredient drift" % rule_id


# ---- the real, source-backed rule ---------------------------------------------------------------

LIVE_DB = Path("/tmp/wel40-coordination/live-demo/research.sqlite")


def test_real_produce_rule_matches_the_real_stored_cdc_evidence():
    """The registered support sentence must occur as a whole sentence in real retrieved evidence,
    and the stored text must still hash to the recorded content hash."""
    if not LIVE_DB.exists():
        pytest.skip("live research database not available")
    import hashlib
    import sqlite3 as sq

    c = sq.connect("file:%s?mode=ro" % LIVE_DB, uri=True)
    c.row_factory = sq.Row
    ev = c.execute("SELECT * FROM evidence WHERE id=6").fetchone()
    text = c.execute("SELECT text FROM evidence_text WHERE evidence_id=6").fetchone()["text"]

    assert ev["url"] == "https://www.cdc.gov/food-safety/prevention/index.html"
    assert ev["content_kind"] == "live"
    assert hashlib.sha256(text.encode()).hexdigest() == ev["content_hash"], "evidence text was altered"

    rule = next(r for r in REAL_RULES if r.rule_id == "rinse_fresh_produce_under_running_water")
    matches = match_rules(text, (rule,))
    assert len(matches) == 1
    assert matches[0].support_quote == "Rinse fresh fruits and vegetables under running water."
    assert matches[0].complete, "a reviewed problem sentence must also be present"

    # The worker can only ever produce a pending candidate; it cannot approve or publish.
    cand = build_rule_candidate(ev, matches[0])
    assert cand["state"] == "pending"
    assert cand["state_set_by"] == "worker"
    assert cand["publishable"] == 0
    assert cand["proposed_action"] == rule.action
    assert cand["source_attribution"] == "U.S. Centers for Disease Control and Prevention"


def test_the_real_pending_candidate_exports_nothing(conn):
    """End to end on the real shape: pending means zero details, whatever else is asserted."""
    if not LIVE_DB.exists():
        pytest.skip("live research database not available")
    import sqlite3 as sq

    c = sq.connect("file:%s?mode=ro" % LIVE_DB, uri=True)
    c.row_factory = sq.Row
    ev = c.execute("SELECT * FROM evidence WHERE id=6").fetchone()
    text = c.execute("SELECT text FROM evidence_text WHERE evidence_id=6").fetchone()["text"]
    rule = next(r for r in REAL_RULES if r.rule_id == "rinse_fresh_produce_under_running_water")

    # Replay the real evidence into a scratch database and export with the REAL registries.
    conn.execute("DELETE FROM evidence")
    cols = ("id, url, content_kind, content_hash, version_no, fetched_at, published_at, "
            "published_at_basis, title, attribution, source_type, access_basis, excerpt, "
            "text_chars, injection_flags")
    conn.execute(
        "INSERT INTO evidence(%s) VALUES(%s)" % (cols, ",".join("?" * 15)),
        tuple(ev[k.strip()] for k in cols.split(",")),
    )
    conn.commit()
    cand = build_rule_candidate(ev, match_rules(text, (rule,))[0])
    save_candidate(conn, cand)

    payload = export_meal_details(conn, MEAL_APPLICABILITY, REAL_RULES)
    assert payload["details"] == []
    assert any("state_not_approved: pending" in r for o in payload["omitted"] for r in o["reasons"])


def test_export_is_deterministic_and_ordered_by_candidate_id(conn):
    add_candidate(conn, cid=2, dedupe="key-2")
    add_candidate(conn, cid=1, dedupe="key-1")
    first = run(conn)
    assert [d["candidate"]["candidate_id"] for d in first["details"]] == [1, 2]
    assert json.dumps(first) == json.dumps(run(conn))
