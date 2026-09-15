"""Regressions for the four blocking findings on PR #1 (Astra review of fdf2056)."""
import json

import pytest

from research import db as dbm
from research import worker
from research.candidates import build_candidate, validate_proposal
from research.fetch import Fetcher
from research.model import ModelClient
from tests.conftest import ARTICLE, STALE_ARTICLE, entry, good_proposal, make_transport, write_allowlist

U1 = "https://fixture.example/how-often-clean/"
ROBOTS = "https://fixture.example/robots.txt"
HTML = {"content-type": "text/html"}


def _run(cfg, pages, model=None, **kw):
    t = make_transport(pages)
    res = worker.run(cfg, transport=t, model=model or ModelClient("fixture", 10, fixture_fn=good_proposal),
                     content_kind="fixture", **kw)
    return res, t


# ---------------------------------------------------------------- F1: request boundary
@pytest.mark.parametrize("target", [
    "https://evil.example/steal",                       # foreign origin
    "http://127.0.0.1:8080/admin",                      # loopback
    "http://169.254.169.254/latest/meta-data/",         # link-local metadata
    "https://fixture.example/accounts/login/?next=/x",  # login page on same origin
    "https://fixture.example/private/report",           # robots-disallowed path on same origin
    "file:///etc/passwd",                               # non-http
])
def test_redirect_destination_is_gated_before_request(cfg, tmp_path, target):
    write_allowlist(tmp_path, [entry(U1)])
    pages = {U1: (302, U1, {"location": target}, ""), target: (200, target, HTML, ARTICLE)}
    res, t = _run(cfg, pages)
    assert target not in t.calls, "forbidden destination must never be requested"
    assert t.calls == [ROBOTS, U1]
    assert res["blocked"] == 1 and res["fetched_ok"] == 0
    conn = dbm.connect(cfg.db_path)
    assert conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 0
    a = conn.execute("SELECT outcome, reason FROM fetch_attempts").fetchone()
    assert a["outcome"] == "blocked" and a["reason"]


def test_same_origin_permitted_redirect_is_followed_with_hop_accounting(cfg, tmp_path):
    write_allowlist(tmp_path, [entry(U1)])
    final = "https://fixture.example/how-often-clean-v2/"
    res, t = _run(cfg, {U1: (301, U1, {"location": "/how-often-clean-v2/"}, ""), final: (200, final, HTML, ARTICLE)})
    assert t.calls == [ROBOTS, U1, final] and res["fetched_ok"] == 1 and res["source_requests"] == 2
    conn = dbm.connect(cfg.db_path)
    assert conn.execute("SELECT final_url FROM evidence").fetchone()[0] == final


def test_redirect_loop_is_capped(cfg, tmp_path):
    write_allowlist(tmp_path, [entry(U1)])
    res, t = _run(cfg, {U1: (302, U1, {"location": U1}, "")})
    assert res["blocked"] == 1 and t.calls.count(U1) == 4  # MAX_REDIRECTS + 1


@pytest.mark.parametrize("robots_response", ["503", "timeout"])
def test_unavailable_robots_is_not_permission(cfg, tmp_path, robots_response):
    write_allowlist(tmp_path, [entry(U1)])
    pages = {U1: (200, U1, HTML, ARTICLE)}
    if robots_response == "503":
        pages[ROBOTS] = (503, ROBOTS, {}, "busy")
    t = make_transport(pages)
    if robots_response == "timeout":
        inner = t

        def t2(url, *a):
            if url == ROBOTS:
                raise TimeoutError("robots timeout")
            return inner(url, *a)
        t2.calls = inner.calls
        t = t2
    res = worker.run(cfg, transport=t, model=ModelClient("none", 10), content_kind="fixture")
    assert U1 not in t.calls, "page must not be requested when the access check is unavailable"
    assert res["blocked"] == 1 and res["fetched_ok"] == 0
    conn = dbm.connect(cfg.db_path)
    a = conn.execute("SELECT robots_status, reason FROM fetch_attempts").fetchone()
    assert a["robots_status"].startswith("unavailable") and "access check unavailable" in a["reason"]


def test_absent_robots_404_is_unrestricted(cfg, tmp_path):
    write_allowlist(tmp_path, [entry(U1)])
    res, t = _run(cfg, {U1: (200, U1, HTML, ARTICLE), ROBOTS: (404, ROBOTS, {}, "")})
    assert res["fetched_ok"] == 1
    conn = dbm.connect(cfg.db_path)
    assert conn.execute("SELECT robots_status FROM fetch_attempts").fetchone()[0] == "allowed_no_robots"


def test_robots_bypass_cannot_enable_live_collection(cfg, tmp_path):
    write_allowlist(tmp_path, [entry(U1)])
    with pytest.raises(ValueError):
        worker.run(cfg, transport=make_transport({}), model=ModelClient("none", 10), content_kind="live", check_robots=False)
    with pytest.raises(SystemExit):
        worker.main(["run", "--no-robots", "--db", str(cfg.db_path)])  # flag no longer exists


@pytest.mark.local_http
def test_real_transport_surfaces_redirects_instead_of_following_them():
    """Real urllib transport against a loopback server: a 302 comes back as 302 + Location,
    and the redirect target is never requested by the transport itself."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from research.fetch import urllib_transport

    hits = []

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            if self.path == "/start":
                self.send_response(302); self.send_header("Location", "/target"); self.end_headers()
            else:
                self.send_response(200); self.send_header("Content-Type", "text/html"); self.end_headers()
                self.wfile.write(b"<html>target</html>")

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    th = threading.Thread(target=srv.serve_forever, daemon=True); th.start()
    try:
        base = "http://127.0.0.1:%d" % srv.server_address[1]
        status, final, headers, body = urllib_transport(base + "/start", "t", 5, 10_000)
    finally:
        srv.shutdown()
    assert status == 302 and headers.get("location") == "/target" and body == b""
    assert hits == ["/start"], "transport must not have followed the redirect"
    # and the Fetcher gate refuses loopback destinations outright, even for an allowlisted loopback URL
    f = Fetcher(transport=urllib_transport, check_robots=False)
    r = f.fetch(base + "/start")
    assert r.outcome == "blocked" and "loopback" in r.reason and hits == ["/start"]


def test_purchase_pattern_ignores_ordinary_prose():
    from research.candidates import shopping_claims
    assert shopping_claims("Wipe it down in order to prevent buildup; The Buy Guide team shares a workshop tip.") == []
    assert shopping_claims("Order the sponge now") == ["purchase"]


# ------------------------------------------------------ F2: whole-proposal validation
def _cand(prop_overrides, text=ARTICLE):
    from research.extract import extract
    ex = extract(text)
    row = {"id": 1, "injection_flags": "[]", "attribution": "Fixture Publisher"}
    prop = good_proposal(ex.text, {})
    prop.update(prop_overrides)
    return build_candidate(row, ex.text, prop, "fixture:-")


def test_shopping_claim_in_action_with_empty_product_list_is_not_pending():
    c = _cand({"proposed_action": "Buy the Dyson V15 Detect for $19.99; it is in stock today", "product_mentions": []})
    assert c["state"] == "deferred"
    assert "unsupported_shopping_claim: price, purchase, stock" in c["state_reason"]
    assert "unsupported_product_identity: Dyson V15 Detect, V15" in c["state_reason"]


@pytest.mark.parametrize("field,value,expect", [
    ("inferences", ["It is 20% off and sold out elsewhere."], "unsupported_shopping_claim: discount, stock"),
    ("household_problem", "Families overpay $40 for sponges.", "unsupported_shopping_claim: price"),
    ("relevance_conditions", ["household owns a Dyson V15 Detect"], "unsupported_product_identity: Dyson V15 Detect, V15"),
    ("proposed_action", "Order replacement sponges weekly.", "unsupported_shopping_claim: purchase"),
])
def test_claims_in_any_prose_field_defer(field, value, expect):
    c = _cand({field: value})
    assert c["state"] == "deferred" and expect in c["state_reason"]


def test_identity_present_in_text_is_fine():
    c = _cand({"proposed_action": "Remind households to swap the Scrub Daddy sponge weekly."})
    assert c["state"] == "pending"


@pytest.mark.parametrize("bad", [
    {"observations": {"quote": "x"}}, {"proposed_action": ["a", "b"]}, {"inferences": 42}, {"lead_time_quote": 7},
])
def test_wrong_field_types_are_rejected_not_saved_pending(bad):
    c = _cand(bad)
    assert c["state"] == "rejected" and c["state_reason"].startswith("invalid_proposal_types")


def test_non_object_proposal_is_rejected():
    row = {"id": 1, "injection_flags": "[]", "attribution": "x"}
    assert build_candidate(row, "text", ["not", "an", "object"], "fixture:-")["state"] == "rejected"


# ------------------------------------------------------------ F3: lead time grounding
@pytest.mark.parametrize("days,quote,expect_days,expect_note", [
    (999, None, None, "no grounded timing quote"),
    (999, "Kitchen sponges should be replaced every week", None, "not stated by quote"),
    (7, "Kitchen sponges should be replaced every week", 7, None),
    (14, "Kitchen sponges should be replaced every week", None, "not stated by quote"),
    (14, "Wash bath towels after three uses", None, "not stated by quote"),
    (-3, "deep clean the oven every three months", None, "invalid value"),
    (float("nan"), "deep clean the oven every three months", None, "invalid value"),
    (True, "deep clean the oven every three months", None, "invalid value"),
    ("90", "deep clean the oven every three months", None, "invalid value"),
    (90, "deep clean the oven every three months", 90, None),
    (90, "the oven every three months is invented text", None, "no grounded timing quote"),
])
def test_lead_time_requires_evidence_for_that_value(days, quote, expect_days, expect_note):
    c = _cand({"lead_time_days": days, "lead_time_quote": quote})
    assert c["lead_time_days"] == expect_days
    notes = [u for u in c["unsupported_claims"] if u.startswith("lead_time_days")]
    if expect_note:
        assert notes and expect_note in notes[0]
        assert c["state"] == "pending", "an unsupported timing is dropped, the rest of the candidate survives review"
    else:
        assert not notes and c["lead_time_basis"] == quote


def test_migration_v2_applies_to_v1_database(tmp_path):
    import sqlite3
    path = tmp_path / "old.sqlite"
    conn = dbm.connect(path)
    conn.executescript(dbm.MIGRATIONS[0][1])
    conn.execute("INSERT INTO schema_version(version, applied_at) VALUES (1, 'x')")
    assert dbm.migrate(conn) == 2
    assert "lead_time_basis" in {r[1] for r in conn.execute("PRAGMA table_info(candidates)")}
    assert dbm.migrate(conn) == 2


# ---------------------------------------------------- F4: honest persisted run status
def test_report_write_failure_persists_failed_status_and_keeps_evidence(cfg, tmp_path):
    write_allowlist(tmp_path, [entry(U1)])
    cfg.report_path = tmp_path / "blocker" / "report.md"
    (tmp_path / "blocker").write_text("a file where the directory should be")
    res, _ = _run(cfg, {U1: (200, U1, HTML, ARTICLE)})
    assert res["status"] == "failed" and any(f.startswith("report write to") for f in res["failures"])
    conn = dbm.connect(cfg.db_path)
    run = conn.execute("SELECT status, summary FROM runs").fetchone()
    assert run["status"] == "failed"
    assert "report write to" in json.loads(run["summary"])["failures"][0]
    assert conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0] == 1
    # re-rendering later does not rewrite history
    cfg.report_path = tmp_path / "later.md"
    assert worker.main(["report", "--db", str(cfg.db_path), "--report", str(cfg.report_path)]) == 0
    assert conn.execute("SELECT status FROM runs").fetchone()[0] == "failed"
    assert "failed" in cfg.report_path.read_text()


def test_cli_exit_code_reflects_report_failure(cfg, tmp_path, monkeypatch):
    write_allowlist(tmp_path, [entry(U1)])
    monkeypatch.setattr(worker, "urllib_transport", make_transport({U1: (200, U1, HTML, ARTICLE)}))
    (tmp_path / "blocker").write_text("x")
    rc = worker.main(["run", "--db", str(cfg.db_path), "--allowlist", str(cfg.allowlist_path),
                      "--report", str(tmp_path / "blocker" / "r.md"), "--provider", "none"])
    assert rc == 1


# ------------------------------------------------------------ AC5: stale-date fixture
def test_stale_dated_source_keeps_its_age_and_asserts_no_current_offer(cfg, tmp_path):
    def prop(text, meta):
        return {
            "household_problem": "Holiday gift wrapping is left to the last minute.",
            "proposed_action": "Buy the Cozy Fleece Blanket for $19.99 while it is in stock and wrap gifts early.",
            "observations": ["Wrap gifts a week before the holiday to avoid the last-minute rush."],
            "inferences": ["Early wrapping reduces holiday stress."],
            "relevance_conditions": ["household celebrates a gift-giving holiday"],
            "lead_time_days": 7,
            "lead_time_quote": "Wrap gifts a week before the holiday",
            "expiry_quote": "Our holiday sale ends this Friday",
            "product_mentions": ["Cozy Fleece Blanket"],
        }
    write_allowlist(tmp_path, [entry(U1)])
    _run(cfg, {U1: (200, U1, HTML, STALE_ARTICLE)}, model=ModelClient("fixture", 10, fixture_fn=prop))
    conn = dbm.connect(cfg.db_path)
    e = conn.execute("SELECT published_at, published_at_basis, fetched_at FROM evidence").fetchone()
    assert e["published_at"] == "2016-11-20T09:00:00Z" and e["published_at_basis"] == "meta:article:published_time"
    assert e["fetched_at"] > "2026"
    c = conn.execute("SELECT * FROM candidates").fetchone()
    assert c["state"] == "deferred" and "unsupported_shopping_claim: price, purchase, stock" in c["state_reason"]
    assert c["expires_at"] is None, "a 2016 'ends Friday' never becomes a current expiry date"
    assert c["expiry_basis"] == "Our holiday sale ends this Friday"
    assert c["lead_time_days"] == 7 and c["lead_time_basis"] == "Wrap gifts a week before the holiday"
    assert "7 days (basis: \"Wrap gifts a week before the holiday\")" in cfg.report_path.read_text()
    report = cfg.report_path.read_text()
    assert "2016-11-20T09:00:00Z (meta:article:published_time)" in report and "DEFERRED" in report
