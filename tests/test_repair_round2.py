"""Round 2 on PR #1 (b399d31): closed action registry, free text never pending, whole-number timing,
status-before-report finalization, legacy rows shown unvalidated."""
import json
import sqlite3

import pytest

from research import db as dbm
from research import worker
from research.candidates import FREE_TEXT_DEFER_REASON, build_candidate, human_review, timing_days_in_quote
from research.extract import extract
from research.model import ModelClient
from research.rules import RULES, match_rules, sentence_units
from tests.conftest import (AIR_FRYER_ARTICLE, ARTICLE, PROBLEM_SENTENCE, SUPPORT_SENTENCE, air_fryer_proposal, entry,
                            good_proposal, make_transport, write_allowlist)

U1 = "https://fixture.example/air-fryer/"
HTML = {"content-type": "text/html"}
RULE = RULES[0]


def _run(cfg, pages, model=None, **kw):
    t = make_transport(pages)
    return worker.run(cfg, transport=t, model=model or ModelClient("fixture", 10, fixture_fn=good_proposal),
                      content_kind="fixture", **kw), t


def _cand(prop_overrides, text=ARTICLE):
    ex = extract(text)
    prop = good_proposal(ex.text, {})
    prop.update(prop_overrides)
    return build_candidate({"id": 1, "injection_flags": "[]", "attribution": "Fixture Publisher"}, ex.text, prop, "fixture:-")


def _page(*paragraphs):
    return "<html><body><article>%s</article></body></html>" % "".join("<p>%s</p>" % p for p in paragraphs)


# ------------------------------------------------------------------ registry: positive
def test_registry_is_closed_and_every_action_is_reviewed():
    # Closed registry: adding an entry is a deliberate, reviewed change. WEL-42 added the second.
    assert [r.rule_id for r in RULES] == [
        "air_fryer_basket_after_each_use",
        "rinse_fresh_produce_under_running_water",
        "bean_rice_bowl_prep_guide",
    ]
    assert RULE.generator == "rule:air_fryer_basket_after_each_use@1"
    assert RULE.support_sentences == (SUPPORT_SENTENCE,) and RULE.problem_sentences == (PROBLEM_SENTENCE,)
    for rule in RULES:
        # No shopping language in any rule, and every rule records where its sentences were read.
        for word in ("$", "price", "stock", "buy", "order", "purchase"):
            assert word not in (rule.action + rule.relevance).lower()
        assert rule.support_sentences and rule.problem_sentences
        assert rule.review_note.strip(), "%s has no review note" % rule.rule_id


def test_fixed_rule_candidate_is_pending_with_exact_support_quote(cfg, tmp_path):
    write_allowlist(tmp_path, [entry(U1)])
    res, _ = _run(cfg, {U1: (200, U1, HTML, AIR_FRYER_ARTICLE)}, model=ModelClient("fixture", 10, fixture_fn=air_fryer_proposal))
    assert res.ok and res["candidates_new"] == 2  # one rule candidate, one deferred free-text proposal
    conn = dbm.connect(cfg.db_path)
    rows = conn.execute("SELECT * FROM candidates ORDER BY id").fetchall()
    rule = [c for c in rows if c["generator"] == RULE.generator][0]
    free = [c for c in rows if c["generator"] == "fixture:fixture"][0]
    assert rule["state"] == "pending" and rule["state_set_by"] == "worker" and rule["publishable"] == 0
    assert rule["proposed_action"] == "Remind the household to clean the air fryer basket after each use."
    assert rule["household_problem"] == PROBLEM_SENTENCE
    assert json.loads(rule["observations"]) == [SUPPORT_SENTENCE, PROBLEM_SENTENCE]
    assert json.loads(rule["relevance_conditions"]) == ["household owns an air fryer"]
    assert json.loads(rule["inferences"]) == [] and json.loads(rule["product_mentions"]) == []
    assert rule["lead_time_days"] is None and rule["lead_time_basis"] is None and rule["expires_at"] is None
    assert rule["proposed_destination"] is None and rule["stock_price_claims"] == "not_verified"
    v = json.loads(rule["validation"])
    assert v == {"kind": "rule", "rule_id": "air_fryer_basket_after_each_use", "rule_version": 1,
                 "support_quote": SUPPORT_SENTENCE, "problem_quote": PROBLEM_SENTENCE,
                 "model_inference": False, "review_note": RULE.review_note}
    # nothing from the model's free text reached the rule candidate; the free text is deferred on its own row
    assert free["state"] == "deferred" and free["state_reason"] == FREE_TEXT_DEFER_REASON
    assert free["proposed_action"] is None and free["household_problem"] is None
    assert json.loads(free["validation"])["raw_proposal"]["proposed_action"] == "Offer a nudge to wipe the basket after cooking."
    assert json.loads(free["observations"]) == ["Use a soft sponge and warm water so the nonstick finish is not scratched"]
    assert conn.execute("SELECT COUNT(*) FROM candidates WHERE publishable=1").fetchone()[0] == 0
    report = cfg.report_path.read_text()
    assert "Rule**: air_fryer_basket_after_each_use v1 (fixed action text; model inference: none)" in report
    assert "Support quote (whole sentence, verbatim)**: \"%s\"" % SUPPORT_SENTENCE in report
    for prose in ("Offer a nudge", "easy to forget", "easiest to act on"):
        assert prose not in report, "model prose is audit material, never rendered"
    assert "Dawn Platinum" not in report.split("## Candidates")[1], "no product output from either row"


def test_rerun_dedupes_rule_and_free_text_rows(cfg, tmp_path):
    write_allowlist(tmp_path, [entry(U1)])
    pages = {U1: (200, U1, HTML, AIR_FRYER_ARTICLE)}
    r1, _ = _run(cfg, pages)
    r2, _ = _run(cfg, pages)
    assert r1["candidates_new"] == 2 and r2["candidates_new"] == 0 and r2["candidates_existing"] == 2
    assert r2["inference_calls"] == 0
    conn = dbm.connect(cfg.db_path)
    assert conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0] == 2


def test_human_can_approve_rule_candidate_but_it_stays_unpublishable(cfg, tmp_path):
    write_allowlist(tmp_path, [entry(U1)])
    _run(cfg, {U1: (200, U1, HTML, AIR_FRYER_ARTICLE)})
    conn = dbm.connect(cfg.db_path)
    cid = conn.execute("SELECT id FROM candidates WHERE state='pending'").fetchone()[0]
    conn.execute("BEGIN"); human_review(conn, cid, "approved", "astra", "supported by whole sentence"); conn.execute("COMMIT")
    c = conn.execute("SELECT state, state_set_by, publishable FROM candidates WHERE id=?", (cid,)).fetchone()
    assert tuple(c) == ("approved", "human:astra", 0)


# ------------------------------------------------------------------ registry: negatives
@pytest.mark.parametrize("variant", [
    "Do not assume that " + SUPPORT_SENTENCE[0].lower() + SUPPORT_SENTENCE[1:],       # prefixed negation
    "It is a myth that " + SUPPORT_SENTENCE[0].lower() + SUPPORT_SENTENCE[1:],
    "Some say " + SUPPORT_SENTENCE[0].lower() + SUPPORT_SENTENCE[1:-1] + ", but they are wrong.",  # suffix
    SUPPORT_SENTENCE[:-1] + "?",                                                        # punctuation reverses tone
    SUPPORT_SENTENCE[:-1] + ", unless the manual says otherwise.",
    "Do not clean the air fryer basket after every use.",                              # exact object + cadence, negated
    "Air fryer baskets need to be cleaned after every use.",                            # tail alone is not the reviewed sentence
    "Clean the air fryer basket after every use with a soft sponge.",
])
def test_reworded_or_negated_sentences_do_not_match(variant):
    text = extract(_page("Intro paragraph about appliances.", variant, PROBLEM_SENTENCE)).text
    assert SUPPORT_SENTENCE.lower()[10:60] in text.lower() or "after every use" in text.lower()  # the words are there
    assert match_rules(text) == []


@pytest.mark.parametrize("variant", [
    SUPPORT_SENTENCE,
    SUPPORT_SENTENCE.upper(),                                  # case is not meaning
    SUPPORT_SENTENCE.replace(" ", "  ")[:-1],                  # whitespace and a missing final full stop are not meaning
    "Here is the key point. " + SUPPORT_SENTENCE + " Now the details.",
])
def test_whole_sentence_variants_that_keep_meaning_match(variant):
    text = extract(_page(variant, PROBLEM_SENTENCE)).text
    m = match_rules(text)
    assert len(m) == 1 and m[0].complete and m[0].rule is RULE
    assert m[0].support_quote.lower().rstrip(".") == SUPPORT_SENTENCE.lower().rstrip(".")


def test_support_sentence_without_problem_sentence_is_deferred_not_pending(cfg, tmp_path):
    write_allowlist(tmp_path, [entry(U1)])
    page = _page(SUPPORT_SENTENCE, "Cleaning is important for reasons described elsewhere on this page in detail.",
                 "A soft sponge and warm water protect the nonstick finish while you clean it, so use them.")
    _run(cfg, {U1: (200, U1, HTML, page)})
    conn = dbm.connect(cfg.db_path)
    rule = conn.execute("SELECT * FROM candidates WHERE generator=?", (RULE.generator,)).fetchone()
    assert rule["state"] == "deferred" and rule["state_reason"].startswith("rule_support_incomplete")
    assert rule["household_problem"] is None and json.loads(rule["validation"])["problem_quote"] is None
    assert conn.execute("SELECT COUNT(*) FROM candidates WHERE state='pending'").fetchone()[0] == 0
    assert "Household problem (whole sentence, verbatim)**: not found in this evidence" in cfg.report_path.read_text()


def test_evidence_without_registry_sentence_yields_no_pending_candidate(cfg, tmp_path):
    write_allowlist(tmp_path, [entry(U1)])
    _run(cfg, {U1: (200, U1, HTML, ARTICLE)})  # a real cleaning article, just not the reviewed sentence
    conn = dbm.connect(cfg.db_path)
    states = [r[0] for r in conn.execute("SELECT state FROM candidates").fetchall()]
    assert states == ["deferred"]


def test_sentence_units_do_not_cross_block_or_terminator_boundaries():
    units = [n for n, _ in sentence_units("One thing. Two things?\nThree things! Four")]
    assert units == ["one thing", "two things?", "three things!", "four"]


# ------------------------------------------------------ free text: never laundered into pending
@pytest.mark.parametrize("field,value", [
    ("proposed_action", "Use OxiClean for the weekly cleaning routine."),                   # single capitalised word
    ("proposed_action", "The sponge costs nineteen dollars and is ready to ship."),         # spelled-out price/stock
    ("inferences", ["It costs nineteen dollars and is ready to ship."]),
    ("household_problem", "Families pay nineteen dollars a month for sponges."),
    ("relevance_conditions", ["household has OxiClean at home"]),
])
def test_unblacklisted_shopping_prose_is_still_never_pending(cfg, tmp_path, field, value):
    c = _cand({field: value, "product_mentions": []})
    assert c["state"] == "deferred" and c["state_reason"] == FREE_TEXT_DEFER_REASON
    assert c["proposed_action"] is None and c["household_problem"] is None and c["inferences"] == []
    assert c["relevance_conditions"] == [] and c["product_mentions"] == []
    assert json.loads(json.dumps(c["validation"]))["raw_proposal"][field] == value  # kept for audit only

    def prop(text, meta):
        p = good_proposal(text, meta)
        p[field] = value
        p["product_mentions"] = []
        return p
    write_allowlist(tmp_path, [entry(U1)])
    _run(cfg, {U1: (200, U1, HTML, ARTICLE)}, model=ModelClient("fixture", 10, fixture_fn=prop))
    report = cfg.report_path.read_text()
    assert "OxiClean" not in report and "nineteen dollars" not in report
    assert "not shown — free-text model proposal" in report and "DEFERRED" in report


def test_original_dyson_example_keeps_its_specific_reason():
    c = _cand({"proposed_action": "Buy the Dyson V15 Detect for $19.99; it is in stock today", "product_mentions": []})
    assert c["state"] == "deferred"
    assert "unsupported_shopping_claim: price, purchase, stock" in c["state_reason"]
    assert "unsupported_product_identity: Dyson V15 Detect, V15" in c["state_reason"]


def test_model_free_text_on_matching_evidence_is_not_blessed_by_the_rule(cfg, tmp_path):
    """The rule candidate and the model's proposal live on separate rows; a matching sentence in the
    evidence does not turn the model's shopping prose into a pending action."""
    def prop(text, meta):
        return {"household_problem": "Air fryer baskets get greasy.",
                "proposed_action": "Order OxiClean and clean the air fryer basket after every use.",
                "observations": [SUPPORT_SENTENCE], "inferences": [], "relevance_conditions": ["household owns an air fryer"],
                "lead_time_days": None, "expiry_quote": None, "product_mentions": []}
    write_allowlist(tmp_path, [entry(U1)])
    _run(cfg, {U1: (200, U1, HTML, AIR_FRYER_ARTICLE)}, model=ModelClient("fixture", 10, fixture_fn=prop))
    conn = dbm.connect(cfg.db_path)
    rows = {r["generator"]: r for r in conn.execute("SELECT * FROM candidates").fetchall()}
    assert rows[RULE.generator]["state"] == "pending"
    free = rows["fixture:fixture"]
    assert free["state"] == "deferred" and "unsupported_shopping_claim: purchase" in free["state_reason"]
    assert free["proposed_action"] is None
    assert "OxiClean" not in cfg.report_path.read_text()


# ------------------------------------------------------------------ timing: whole numbers only
@pytest.mark.parametrize("quote,expected", [
    ("Allow 1.5 weeks for the preparation process.", []),
    ("Allow 1,5 weeks for the preparation process.", []),
    ("Allow 2-3 weeks for delivery.", []),
    ("Allow 2–3 weeks for delivery.", []),
    ("Takes half a week to dry.", []),
    ("Takes 1/2 week to dry.", []),
    ("Allow 5 weeks for the preparation process.", [35]),
    ("Replace every two weeks.", [14]),
    ("Wipe it down weekly and every 3 days in summer.", [3, 7]),
])
def test_timing_accepts_complete_whole_numbers_only(quote, expected):
    assert sorted(timing_days_in_quote(quote)) == sorted(expected)


def test_fractional_timing_quote_does_not_support_35_days():
    text = _page("Allow 1.5 weeks for the preparation process.", "Kitchen sponges should be replaced every week.",
                 "Wipe down the microwave weekly and deep clean the oven every three months to keep it fresh.")
    for days in (35, 5, 10):
        c = _cand({"lead_time_days": days, "lead_time_quote": "Allow 1.5 weeks for the preparation process."}, text=text)
        assert c["lead_time_days"] is None and c["lead_time_basis"] is None
        assert any("lead_time_days: %d not stated by quote" % days in u for u in c["unsupported_claims"])


# ------------------------------------------------------ finalization: status before report
def test_successful_run_report_shows_its_own_run_as_ok(cfg, tmp_path):
    write_allowlist(tmp_path, [entry(U1)])
    res, _ = _run(cfg, {U1: (200, U1, HTML, AIR_FRYER_ARTICLE)})
    assert res.ok and res["report_path"] == str(cfg.report_path)
    report = cfg.report_path.read_text()
    line = [l for l in report.splitlines() if l.startswith("| %s |" % res["run_id"])][0]
    assert "| ok |" in line and "running" not in report
    conn = dbm.connect(cfg.db_path)
    run = conn.execute("SELECT status, finished_at, summary FROM runs").fetchone()
    assert run["status"] == "ok" and run["finished_at"]
    assert json.loads(run["summary"])["candidates_new"] == 2


def test_report_write_failure_updates_durable_status_and_keeps_evidence(cfg, tmp_path):
    write_allowlist(tmp_path, [entry(U1)])
    cfg.report_path = tmp_path / "blocker" / "report.md"
    (tmp_path / "blocker").write_text("a file where the directory should be")
    res, _ = _run(cfg, {U1: (200, U1, HTML, AIR_FRYER_ARTICLE)})
    assert res["status"] == "failed" and res["report_path"] is None
    assert [f for f in res["failures"] if f.startswith("report write to")]
    conn = dbm.connect(cfg.db_path)
    run = conn.execute("SELECT status, summary FROM runs").fetchone()
    summary = json.loads(run["summary"])
    assert run["status"] == "failed" and summary["status"] == "failed" and summary["report_path"] is None
    assert "report write to" in summary["failures"][0]
    assert conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM candidates WHERE state='pending'").fetchone()[0] == 1


def test_status_write_failure_is_failed_and_writes_no_report(cfg, tmp_path):
    write_allowlist(tmp_path, [entry(U1)])

    class Conn:
        def __init__(self, real):
            self._real = real

        def execute(self, sql, *a):
            if sql.lstrip().upper().startswith("UPDATE RUNS SET FINISHED_AT"):
                raise sqlite3.OperationalError("disk I/O error (simulated)")
            return self._real.execute(sql, *a)

        def __getattr__(self, name):
            return getattr(self._real, name)

    res = worker.run(cfg, transport=make_transport({U1: (200, U1, HTML, AIR_FRYER_ARTICLE)}),
                     model=ModelClient("none", 10), content_kind="fixture", conn_factory=lambda p: Conn(dbm.connect(p)))
    assert res["status"] == "failed" and any(f.startswith("run status write") for f in res["failures"])
    assert not cfg.report_path.exists(), "a report here would have shown the finished run as running"
    conn = dbm.connect(cfg.db_path)
    assert conn.execute("SELECT status FROM runs").fetchone()[0] == "running"  # honest: the final write never landed
    assert conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0] == 2


# --------------------------------------------------------- legacy v2 rows: preserved, unvalidated
def _v2_database(path, html, url):
    """A populated schema-v2 store: evidence for `url` plus one human-approved free-prose candidate."""
    conn = dbm.connect(path)
    conn.executescript(dbm.MIGRATIONS[0][1])
    conn.executescript(dbm.MIGRATIONS[1][1])
    conn.execute("INSERT INTO schema_version(version, applied_at) VALUES (1, 'x'), (2, 'x')")
    ex = extract(html)
    conn.execute("""INSERT INTO evidence(url, final_url, content_kind, content_hash, version_no, fetched_at,
                    published_at_basis, attribution, source_type, access_basis, excerpt, text_chars, injection_flags)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                 (url, url, "fixture", ex.content_hash, 1, "2026-09-01T00:00:00Z", "unknown", "Fixture Publisher",
                  "publication", "fixture", ex.excerpt, len(ex.text), "[]"))
    conn.execute("INSERT INTO evidence_text(evidence_id, text) VALUES(1, ?)", (ex.text,))
    conn.execute("""INSERT INTO candidates(dedupe_key, evidence_id, generator, household_problem, proposed_action,
                    observations, inferences, unsupported_claims, relevance_conditions, product_mentions,
                    source_attribution, stock_price_claims, state, state_reason, state_set_by, publishable,
                    created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                 (worker.cands.dedupe_key(1, "ollama:qwen2.5:14b"), 1, "ollama:qwen2.5:14b",
                  "The basket gets greasy after use.", "Buy a spare Dawn Platinum bottle and clean the basket often.",
                  json.dumps([PROBLEM_SENTENCE]), json.dumps(["A spare bottle saves trips."]), "[]",
                  json.dumps(["household owns an air fryer"]), json.dumps([{"name": "Dawn Platinum", "grounded": True}]),
                  "Fixture Publisher", "not_verified", "approved", "grounded and useful", "human:astra", 0, "x", "x"))
    conn.close()


def test_legacy_v2_rows_survive_unchanged_and_are_reported_without_prose(cfg, tmp_path):
    _v2_database(cfg.db_path, AIR_FRYER_ARTICLE, U1)
    write_allowlist(tmp_path, [entry(U1)])
    r1, _ = _run(cfg, {U1: (200, U1, HTML, AIR_FRYER_ARTICLE)})
    assert r1.ok and r1["evidence_existing"] == 1 and r1["evidence_new"] == 0
    assert r1["candidates_new"] == 2  # rule row + this run's deferred fixture proposal; the legacy generator differs
    conn = dbm.connect(cfg.db_path)
    assert dbm.migrate(conn) == 5
    legacy = conn.execute("SELECT * FROM candidates WHERE generator='ollama:qwen2.5:14b'").fetchone()
    assert legacy["validation"] is None and legacy["state"] == "approved" and legacy["state_set_by"] == "human:astra"
    assert legacy["proposed_action"].startswith("Buy a spare"), "stored prose is untouched, only not rendered"
    assert legacy["publishable"] == 0
    assert conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0] == 3
    report = cfg.report_path.read_text()
    legacy_section = report.split("## Legacy candidates")[1]
    assert "| %d | %s | #1 | approved | human:astra | grounded and useful | ollama:qwen2.5:14b |" % (legacy["id"], U1) in legacy_section
    assert "Buy a spare" not in report and "A spare bottle" not in report and "Dawn Platinum" not in report
    assert "### Candidate %d" % legacy["id"] not in report, "no old-prose fallback rendering"
    # unchanged rerun on the new representation dedupes everything
    r2, _ = _run(cfg, {U1: (200, U1, HTML, AIR_FRYER_ARTICLE)})
    assert r2["candidates_new"] == 0 and r2["candidates_existing"] == 2 and r2["inference_calls"] == 0
    assert conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0] == 3
    assert conn.execute("SELECT state, state_set_by FROM candidates WHERE id=?", (legacy["id"],)).fetchone()[0] == "approved"


def test_legacy_pending_row_is_not_blessed_by_migration(cfg, tmp_path):
    _v2_database(cfg.db_path, ARTICLE, U1)
    conn = dbm.connect(cfg.db_path)
    conn.execute("UPDATE candidates SET state='pending', state_reason=NULL, state_set_by='worker'")
    conn.close()
    write_allowlist(tmp_path, [entry(U1)])
    _run(cfg, {U1: (200, U1, HTML, ARTICLE)})
    conn = dbm.connect(cfg.db_path)
    legacy = conn.execute("SELECT state, validation FROM candidates WHERE generator='ollama:qwen2.5:14b'").fetchone()
    assert legacy["state"] == "pending" and legacy["validation"] is None  # a human decision, not the worker's, changes it
    report = cfg.report_path.read_text()
    assert "PENDING" not in report.split("## Legacy candidates")[0], "no validated pending candidate is shown"
    assert "| pending | worker |" in report.split("## Legacy candidates")[1]
