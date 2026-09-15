import json
import sqlite3

import pytest

from research import db as dbm
from research import worker
from research.candidates import human_review
from research.model import ModelClient
from tests.conftest import (ARTICLE, ARTICLE_CHANGED, ARTICLE_NO_DATE, INJECTED, LOGIN_WALL, entry, good_proposal,
                            make_transport, write_allowlist)

U1 = "https://fixture.example/how-often-clean/"
U2 = "https://fixture.example/second/"
HTML = {"content-type": "text/html"}


def fixture_model(fn=good_proposal, budget=10):
    return ModelClient("fixture", budget, fixture_fn=fn)


def _run(cfg, pages, model=None, content_kind="fixture"):
    t = make_transport(pages)
    res = worker.run(cfg, transport=t, model=model or fixture_model(), content_kind=content_kind)
    return res, t


def test_migrate_is_idempotent_and_state_survives_reopen(cfg, tmp_path):
    write_allowlist(tmp_path, [entry(U1)])
    res, _ = _run(cfg, {U1: (200, U1, HTML, ARTICLE)})
    assert res.ok, res
    conn = dbm.connect(cfg.db_path)
    assert dbm.migrate(conn) == 2
    assert dbm.migrate(conn) == 2
    conn.close()
    conn = dbm.connect(cfg.db_path)  # simulated restart
    assert conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0] == 1
    assert conn.execute("SELECT status FROM runs").fetchone()[0] == "ok"


def test_duplicate_input_does_not_duplicate_and_changed_content_versions(cfg, tmp_path):
    write_allowlist(tmp_path, [entry(U1)])
    pages = {U1: (200, U1, HTML, ARTICLE)}
    r1, _ = _run(cfg, pages)
    r2, _ = _run(cfg, pages)
    assert r1["evidence_new"] == 1 and r1["candidates_new"] == 1
    assert r2["evidence_new"] == 0 and r2["evidence_existing"] == 1
    assert r2["candidates_new"] == 0 and r2["candidates_existing"] == 1
    assert r2["inference_calls"] == 0, "no inference spent on unchanged evidence"
    conn = dbm.connect(cfg.db_path)
    assert conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM fetch_attempts WHERE outcome='ok'").fetchone()[0] == 2
    old_hash = conn.execute("SELECT content_hash FROM evidence").fetchone()[0]

    r3, _ = _run(cfg, {U1: (200, U1, HTML, ARTICLE_CHANGED)})
    assert r3["evidence_new"] == 1
    rows = conn.execute("SELECT id, version_no, supersedes_id, content_hash FROM evidence ORDER BY version_no").fetchall()
    assert [r["version_no"] for r in rows] == [1, 2]
    assert rows[1]["supersedes_id"] == rows[0]["id"]
    assert rows[0]["content_hash"] == old_hash, "prior evidence untouched"
    assert conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0] == 2


def test_blocked_login_source_is_recorded_not_fabricated(cfg, tmp_path):
    write_allowlist(tmp_path, [entry(U1), entry(U2)])
    res, _ = _run(cfg, {U1: (200, "https://fixture.example/accounts/login/?next=x", HTML, LOGIN_WALL),
                        U2: (403, U2, HTML, "<html>forbidden</html>")})
    assert res.ok and res["blocked"] == 2 and res["fetched_ok"] == 0
    conn = dbm.connect(cfg.db_path)
    reasons = [r[0] for r in conn.execute("SELECT reason FROM fetch_attempts WHERE outcome='blocked'").fetchall()]
    assert any("login" in r for r in reasons) and any("403" in r for r in reasons)
    assert conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0] == 0


def test_policy_blocked_source_is_never_requested(cfg, tmp_path):
    ig = "https://fixture.example/instagram/"
    write_allowlist(tmp_path, [entry(ig, fetch=False, source_type="creator_social", basis="none: login-gated")])
    res, t = _run(cfg, {})
    assert res.ok and res["skipped_policy"] == 1
    assert t.calls == [], "discovery-only hint must not produce any request"
    conn = dbm.connect(cfg.db_path)
    assert conn.execute("SELECT outcome FROM fetch_attempts").fetchone()[0] == "skipped_policy"


def test_robots_disallow_blocks_fetch(cfg, tmp_path):
    write_allowlist(tmp_path, [entry(U1)])
    pages = {U1: (200, U1, HTML, ARTICLE),
             "https://fixture.example/robots.txt": (200, "", {}, "User-agent: *\nDisallow: /how-often-clean/\n")}
    res, t = _run(cfg, pages)
    assert res["blocked"] == 1 and U1 not in t.calls
    conn = dbm.connect(cfg.db_path)
    assert conn.execute("SELECT robots_status FROM fetch_attempts").fetchone()[0] == "disallowed"


def test_unknown_date_is_recorded_as_unknown_not_invented(cfg, tmp_path):
    write_allowlist(tmp_path, [entry(U1)])
    res, _ = _run(cfg, {U1: (200, U1, HTML, ARTICLE_NO_DATE)})
    assert res.ok
    conn = dbm.connect(cfg.db_path)
    e = conn.execute("SELECT published_at, published_at_basis, modified_at, fetched_at FROM evidence").fetchone()
    assert e["published_at"] is None and e["published_at_basis"] == "unknown"
    assert e["fetched_at"]  # fetch time is always known and separate from publication time
    c = conn.execute("SELECT lead_time_days, expires_at FROM candidates").fetchone()
    assert c["lead_time_days"] is None and c["expires_at"] is None
    assert "unknown" in cfg.report_path.read_text()


def test_dates_come_from_page_metadata_and_fixture_is_labelled(cfg, tmp_path):
    write_allowlist(tmp_path, [entry(U1)])
    _run(cfg, {U1: (200, U1, HTML, ARTICLE)})
    conn = dbm.connect(cfg.db_path)
    e = conn.execute("SELECT * FROM evidence").fetchone()
    assert e["published_at"] == "2024-03-01T12:00:00Z" and e["published_at_basis"] == "meta:article:published_time"
    assert e["modified_at"] == "2024-06-01T12:00:00Z"
    assert e["content_kind"] == "fixture"
    assert e["title"] == "How Often You Should Clean Everything"
    assert "Menu Login" not in e["excerpt"], "nav chrome stripped"


def test_unsupported_product_identity_defers_candidate(cfg, tmp_path):
    def prop(text, meta):
        p = good_proposal(text, meta)
        p["product_mentions"] = ["Scrub Daddy sponge", "Dyson V15 Detect"]
        return p
    write_allowlist(tmp_path, [entry(U1)])
    _run(cfg, {U1: (200, U1, HTML, ARTICLE)}, model=fixture_model(prop))
    conn = dbm.connect(cfg.db_path)
    c = conn.execute("SELECT * FROM candidates").fetchone()
    assert c["state"] == "deferred" and "unsupported_product_identity: Dyson V15 Detect" in c["state_reason"]
    pm = json.loads(c["product_mentions"])
    assert {p["name"]: p["grounded"] for p in pm} == {"Scrub Daddy sponge": True, "Dyson V15 Detect": False}
    assert c["proposed_destination"] is None and c["stock_price_claims"] == "not_verified"
    assert c["source_attribution"] == "Fixture Publisher"


def test_ungrounded_quotes_are_dropped_and_candidate_rejected_when_none_remain(cfg, tmp_path):
    def prop(text, meta):
        p = good_proposal(text, meta)
        p["observations"] = ["Sponges must be boiled daily", "Towels should be burned"]
        p["expiry_quote"] = "valid until next spring"
        return p
    write_allowlist(tmp_path, [entry(U1)])
    _run(cfg, {U1: (200, U1, HTML, ARTICLE)}, model=fixture_model(prop))
    conn = dbm.connect(cfg.db_path)
    c = conn.execute("SELECT * FROM candidates").fetchone()
    assert c["state"] == "rejected" and c["state_reason"].startswith("no_grounded_observation")
    assert json.loads(c["observations"]) == []
    assert len(json.loads(c["unsupported_claims"])) == 3 and c["expiry_basis"] is None


def test_no_automatic_approval_and_human_review_path(cfg, tmp_path):
    write_allowlist(tmp_path, [entry(U1)])
    _run(cfg, {U1: (200, U1, HTML, ARTICLE)})  # good_proposal claims approved=True, confidence=0.99
    conn = dbm.connect(cfg.db_path)
    c = conn.execute("SELECT * FROM candidates").fetchone()
    assert c["state"] == "pending" and c["state_set_by"] == "worker" and c["publishable"] == 0
    conn.execute("BEGIN")
    human_review(conn, c["id"], "approved", "astra", "grounded, useful")
    conn.execute("COMMIT")
    c = conn.execute("SELECT * FROM candidates").fetchone()
    assert c["state"] == "approved" and c["state_set_by"] == "human:astra" and c["publishable"] == 0
    with pytest.raises(ValueError):
        human_review(conn, c["id"], "approved", "", "")


def test_save_failure_does_not_report_success(cfg, tmp_path):
    write_allowlist(tmp_path, [entry(U1)])

    class FailingConn:
        def __init__(self, real):
            self._real = real

        def execute(self, sql, *a):
            if sql.lstrip().upper().startswith("INSERT INTO EVIDENCE("):
                raise sqlite3.OperationalError("disk I/O error (simulated)")
            return self._real.execute(sql, *a)

        def __getattr__(self, name):
            return getattr(self._real, name)

    res = worker.run(cfg, transport=make_transport({U1: (200, U1, HTML, ARTICLE)}), model=fixture_model(),
                     content_kind="fixture", conn_factory=lambda p: FailingConn(dbm.connect(p)))
    assert not res.ok and res["status"] == "failed"
    assert any("disk I/O error" in f for f in res["failures"])
    conn = dbm.connect(cfg.db_path)
    assert conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0] == 0
    assert conn.execute("SELECT status FROM runs").fetchone()[0] == "failed"


def test_cli_run_uses_injected_transport_only(cfg, tmp_path, monkeypatch, capsys):
    write_allowlist(tmp_path, [entry(U1)])
    t = make_transport({U1: (200, U1, HTML, ARTICLE)})
    monkeypatch.setattr(worker, "urllib_transport", t)
    rc = worker.main(["run", "--db", str(cfg.db_path), "--allowlist", str(cfg.allowlist_path),
                      "--report", str(cfg.report_path), "--provider", "none"])
    assert rc == 0 and t.calls == ["https://fixture.example/robots.txt", U1]
    assert json.loads(capsys.readouterr().out)["status"] == "ok"


def test_database_unavailable_is_a_failure(cfg, tmp_path):
    write_allowlist(tmp_path, [entry(U1)])
    cfg.db_path = tmp_path / "missing_dir" / "x" / "db.sqlite"
    (tmp_path / "missing_dir").write_text("not a directory")  # makes mkdir fail
    res = worker.run(cfg, transport=make_transport({}), model=fixture_model())
    assert res["status"] == "failed" and "database unavailable" in res["failures"][0]


def test_source_embedded_instructions_never_redirect_tools(cfg, tmp_path):
    seen_prompts = []

    def prop(text, meta):
        seen_prompts.append(text)
        return good_proposal(text, meta)

    write_allowlist(tmp_path, [entry(U1)])
    res, t = _run(cfg, {U1: (200, U1, HTML, INJECTED)}, model=fixture_model(prop))
    assert res.ok
    assert all("evil.example" not in u for u in t.calls), "URL inside content was never requested"
    assert t.calls == ["https://fixture.example/robots.txt", U1]
    conn = dbm.connect(cfg.db_path)
    flags = json.loads(conn.execute("SELECT injection_flags FROM evidence").fetchone()[0])
    assert flags, "instruction-like content is flagged"
    c = conn.execute("SELECT state, state_reason FROM candidates").fetchone()
    assert c["state"] == "deferred" and c["state_reason"].startswith("source_embedded_instructions_flagged")
    # the model saw the text only as data; the worker did nothing else with it
    assert "ignore previous instructions" in seen_prompts[0].lower()
    assert res["inference_calls"] == 1 and res["source_requests"] == 1


def test_inference_budget_is_hard_and_errors_are_not_retried(cfg, tmp_path):
    calls = {"n": 0}

    def prop(text, meta):
        calls["n"] += 1
        raise RuntimeError("model exploded")

    urls = ["https://fixture.example/p%d/" % i for i in range(3)]
    write_allowlist(tmp_path, [entry(u) for u in urls])
    pages = {u: (200, u, HTML, ARTICLE.replace("every week", "every %d days" % i)) for i, u in enumerate(urls)}
    res, _ = _run(cfg, pages, model=fixture_model(prop, budget=2))
    assert res.ok and calls["n"] == 2, "budget of 2 respected, no retry after error"
    conn = dbm.connect(cfg.db_path)
    reasons = sorted(r[0] for r in conn.execute("SELECT state_reason FROM candidates").fetchall())
    assert sum("model exploded" in r for r in reasons) == 2
    assert sum(r.startswith("inference_budget_exhausted") for r in reasons) == 1
    assert conn.execute("SELECT COUNT(*) FROM inference_calls WHERE ok=0").fetchone()[0] == 2


def test_url_cap_is_enforced(cfg, tmp_path):
    urls = ["https://fixture.example/u%d/" % i for i in range(4)]
    write_allowlist(tmp_path, [entry(u) for u in urls])
    cfg.max_urls = 2
    res, t = _run(cfg, {u: (200, u, HTML, ARTICLE) for u in urls})
    assert res["source_requests"] == 2 and res["skipped_policy"] == 2


def test_provider_none_defers_honestly(cfg, tmp_path):
    write_allowlist(tmp_path, [entry(U1)])
    res, _ = _run(cfg, {U1: (200, U1, HTML, ARTICLE)}, model=ModelClient("none", 10))
    assert res.ok and res["inference_calls"] == 0
    conn = dbm.connect(cfg.db_path)
    c = conn.execute("SELECT state, state_reason FROM candidates").fetchone()
    assert c["state"] == "deferred" and c["state_reason"].startswith("inference_unavailable")


def test_report_is_readable_and_has_no_household_fields(cfg, tmp_path):
    write_allowlist(tmp_path, [entry(U1), entry("https://fixture.example/ig/", fetch=False, source_type="creator_social", basis="none")])
    _run(cfg, {U1: (200, U1, HTML, ARTICLE)})
    text = cfg.report_path.read_text()
    for needle in ("## Sources", "## Evidence", "## Candidates", "PENDING", "Observations (verbatim, grounded)",
                   "Inferences (not stated by source)", "skipped_policy", "Shopping destination**: none proposed"):
        assert needle in text, needle
    conn = dbm.connect(cfg.db_path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(candidates)").fetchall()}
    assert not cols & {"household_id", "family_name", "email", "phone", "address"}
