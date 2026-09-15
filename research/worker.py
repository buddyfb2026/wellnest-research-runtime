"""Research worker (WEL-40 manual run, WEL-41 bounded recurring cycle). No daemon, no loop.

    python3 -m research.worker run    [--allowlist F] [--db F] [--report F] [--provider none|ollama|fixture]
                                      [--max-urls N] [--max-inference N] [--max-inference-per-day N]
    python3 -m research.worker cycle  (same options)   one bounded pass over sources that are DUE
    python3 -m research.worker report [--db F] [--report F]
    python3 -m research.worker review CANDIDATE_ID approved|rejected|deferred|pending --by NAME --reason TEXT
    python3 -m research.worker reset-source URL --by NAME --reason TEXT

`run` attempts every permitted source (manual, as in WEL-40); `cycle` attempts only sources whose
persisted next-check time has passed. Both take the store lock, both update the schedule, both
spend from the same persisted daily inference budget. A scheduler (launchd, cron) would call
`cycle`; none is installed or activated by this repository.
"""
import argparse
import json
import sqlite3
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import candidates as cands
from . import config as cfgm
from . import db as dbm
from . import discovery
from . import evidence as ev
from . import report as rpt
from . import rules
from . import schedule as sch
from .config import Config
from .extract import extract
from .fetch import Fetcher, FetchResult, urllib_transport
from .lock import StoreLock
from .model import BudgetExhausted, ModelClient


class RunResult(dict):
    @property
    def ok(self) -> bool:
        return self.get("status") == "ok"


def load_allowlist(path: Path) -> List[Dict[str, Any]]:
    data = json.loads(Path(path).read_text())
    srcs = data["sources"] if isinstance(data, dict) else data
    for s in srcs:
        for k in ("url", "source_type", "access_basis"):
            if not s.get(k):
                raise ValueError("allowlist entry missing %s: %s" % (k, s))
        if s.get("role") == "discovery_route" and not s.get("fetch"):
            raise ValueError("discovery route must declare a permitted access basis (fetch=true): %s" % s["url"])
    return srcs


def _latest_evidence_ids(conn: sqlite3.Connection) -> List[int]:
    """Durable work set: the newest version of every URL's evidence."""
    rows = conn.execute(
        "SELECT e.id FROM evidence e WHERE e.version_no=(SELECT MAX(version_no) FROM evidence WHERE url=e.url) ORDER BY e.id"
    ).fetchall()
    return [int(r["id"]) for r in rows]


def _missing_work(conn: sqlite3.Connection, eid: int, generator: str) -> bool:
    text = ev.load_evidence_text(conn, eid)
    for m in rules.match_rules(text):
        if not conn.execute("SELECT 1 FROM candidates WHERE dedupe_key=?", (cands.dedupe_key(eid, m.rule.generator),)).fetchone():
            return True
    row = conn.execute("SELECT state_reason, state_set_by FROM candidates WHERE dedupe_key=?",
                       (cands.dedupe_key(eid, generator),)).fetchone()
    return row is None or cands.is_budget_placeholder(row)


def run(cfg: Config, transport=urllib_transport, model: Optional[ModelClient] = None,
        content_kind: str = "live", check_robots: bool = True,
        conn_factory: Callable[[Path], sqlite3.Connection] = dbm.connect,
        clock: Optional[Callable[[], datetime]] = None, due_only: bool = False) -> RunResult:
    clock = clock or sch.utc_now
    now = clock()
    now_s = sch.iso(now)
    day = sch.day_of(now)
    run_id = "run_%s_%s" % (now_s.replace(":", "").replace("-", ""), uuid.uuid4().hex[:6])
    result = RunResult(run_id=run_id, status="running", mode="cycle" if due_only else "manual", day=day,
                       fetched_ok=0, blocked=0, errors=0, skipped_policy=0, not_due=0, stalled=0,
                       evidence_new=0, evidence_existing=0, candidates_new=0, candidates_existing=0,
                       candidates_recovered=0, attempts_settled=0, inference_calls=0, inference_used_today=0,
                       budget_deferred=0,
                       routes_fetched=0, discovered_hints=0, assessed_permitted=0, assessed_denied=0,
                       source_requests=0, robots_requests=0, failures=[])

    if not check_robots and content_kind != "fixture":
        raise ValueError("robots bypass is only allowed for fixture content, never for live collection")

    lock = StoreLock(cfg.db_path) if str(cfg.db_path) != ":memory:" else None
    conn: Optional[sqlite3.Connection] = None
    try:
        try:
            if lock and not lock.acquire():
                result["status"] = "locked"
                result["failures"].append("store %s is held by another worker process (lock %s); nothing requested"
                                          % (cfg.db_path, lock.path))
                return result
            conn = conn_factory(cfg.db_path)
            dbm.migrate(conn)
            conn.execute("INSERT INTO runs(run_id, started_at, status) VALUES(?,?,?)", (run_id, now_s, "running"))
        except Exception as e:
            result["status"] = "failed"
            result["failures"].append("database unavailable: %s: %s" % (type(e).__name__, e))
            return result
        return _run_locked(cfg, conn, transport, model, content_kind, check_robots, clock, due_only, result, run_id)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        if lock:
            lock.release()


def _run_locked(cfg: Config, conn: sqlite3.Connection, transport, model: Optional[ModelClient], content_kind: str,
                check_robots: bool, clock: Callable[[], datetime], due_only: bool, result: RunResult,
                run_id: str) -> RunResult:
    now = clock()
    now_s = sch.iso(now)
    day = result["day"]
    allow = load_allowlist(cfg.allowlist_path)
    allow_urls = {s["url"] for s in allow}
    sources = allow + [d for d in discovery.permitted_discovered(conn) if d["url"] not in allow_urls]
    fetcher = Fetcher(transport, cfg.user_agent, cfg.fetch_timeout_s, cfg.max_body_bytes, check_robots, clock=clock)
    model = model or ModelClient(cfg.provider, cfg.max_inference, cfg.ollama_model, cfg.ollama_url,
                                 daily_cap=cfg.max_inference_per_day)

    # 1. Register hints and scheduling state (allowlist rows are re-asserted; discovered rows are DB-owned).
    for hint in sources:
        try:
            conn.execute("BEGIN")
            if not hint.get("discovered"):
                ev.upsert_source_hint(conn, hint)
            if hint.get("fetch", False):
                sch.ensure_state(conn, hint["url"], now)
            conn.execute("COMMIT")
        except Exception as e:
            _rollback(conn)
            result["failures"].append("register %s: %s: %s" % (hint["url"], type(e).__name__, e))

    # 2. Select: manual = every permitted source (WEL-40 behaviour); cycle = due sources only, capped.
    if due_only:
        # WEL-43: same gates and same number of slots as before; a fixed share of the slots is
        # reserved for never-attempted sources so an incumbent cannot occupy every cycle.
        selection = sch.select_cycle_urls(conn, now, cfg.max_urls)
        due = selection["selected"]
        result["exploration_selected"] = len(selection["exploration"])
        result["exploitation_selected"] = len(selection["exploitation"])
        by_url = {s["url"]: s for s in sources if s.get("fetch", False)}
        selected = [by_url[u] for u in due if u in by_url]
        permitted = [s for s in sources if s.get("fetch", False)]
        stalled = {r["url"] for r in conn.execute("SELECT url FROM source_state WHERE stalled=1").fetchall()}
        result["stalled"] = sum(1 for s in permitted if s["url"] in stalled)
        result["not_due"] = len(permitted) - len(selected) - result["stalled"]
        result["skipped_policy"] = sum(1 for s in sources if not s.get("fetch", False))   # never requested, no row
    else:
        selected = sources

    attempted = 0
    touched: List[int] = []
    for hint in selected:
        url = hint["url"]
        try:
            conn.execute("BEGIN")
            if not hint.get("fetch", False):
                ev.record_fetch_attempt(conn, run_id, url, "skipped_policy", now_s,
                                        reason="no permitted access basis: %s" % hint["access_basis"])
                result["skipped_policy"] += 1
                conn.execute("COMMIT")
                continue
            if attempted >= cfg.max_urls:
                ev.record_fetch_attempt(conn, run_id, url, "skipped_policy", now_s, reason="url cap %d reached" % cfg.max_urls)
                result["skipped_policy"] += 1
                conn.execute("COMMIT")
                continue
            attempted += 1
            fr: FetchResult = fetcher.fetch(url)
            at = sch.parse(fr.attempted_at)
            if fr.outcome != "ok":
                ev.record_fetch_attempt(conn, run_id, fr.url, fr.outcome, fr.attempted_at, fr.http_status,
                                        fr.final_url, fr.robots_status, fr.reason)
                sch.record_outcome(conn, url, fr.outcome, fr.reason, fr.attempted_at, at)
                result["blocked" if fr.outcome == "blocked" else "errors"] += 1
                conn.execute("COMMIT")
                continue
            if hint.get("role") == "discovery_route":
                links = discovery.extract_hints(url, fr.html or "", cfgm.MAX_DISCOVERY_HINTS_PER_ROUTE)
                new = sum(1 for link in links if discovery.record_hint(conn, link, hint, fr.attempted_at))
                ev.record_fetch_attempt(conn, run_id, fr.url, "ok", fr.attempted_at, fr.http_status, fr.final_url,
                                        fr.robots_status, "discovery route: %d same-origin links, %d new hints" % (len(links), new))
                sch.record_outcome(conn, url, "ok", None, fr.attempted_at, at)
                result["routes_fetched"] += 1
                result["discovered_hints"] += new
                conn.execute("COMMIT")
                continue
            ex = extract(fr.html or "")
            if len(ex.text) < 200:
                reason = "no usable text extracted"
                ev.record_fetch_attempt(conn, run_id, fr.url, "error", fr.attempted_at, fr.http_status,
                                        fr.final_url, fr.robots_status, reason)
                sch.record_outcome(conn, url, "error", reason, fr.attempted_at, at)
                result["errors"] += 1
                conn.execute("COMMIT")
                continue
            eid, is_new = ev.store_evidence(conn, hint, fr, ex, content_kind)
            ev.record_fetch_attempt(conn, run_id, fr.url, "ok", fr.attempted_at, fr.http_status, fr.final_url,
                                    fr.robots_status, None if is_new else "content unchanged (hash match)", eid)
            sch.record_outcome(conn, url, "ok", None, fr.attempted_at, at, eid)
            result["fetched_ok"] += 1
            result["evidence_new" if is_new else "evidence_existing"] += 1
            touched.append(eid)
            conn.execute("COMMIT")   # evidence + schedule are durable here; candidate work below is recoverable
        except Exception as e:
            _rollback(conn)
            result["failures"].append("persist %s: %s: %s" % (url, type(e).__name__, e))

    # 3. Access assessment of discovered hints: bounded, robots-only, no content request.
    for h in discovery.unassessed_hints(conn, cfgm.MAX_DISCOVERY_ASSESSMENTS_PER_CYCLE):
        try:
            conn.execute("BEGIN")
            ok, _ = discovery.assess(conn, fetcher, h, now_s)
            if ok:
                sch.ensure_state(conn, h["url"], now)   # due now; collected by a later cycle under the same caps
            result["assessed_permitted" if ok else "assessed_denied"] += 1
            conn.execute("COMMIT")
        except Exception as e:
            _rollback(conn)
            result["failures"].append("assess %s: %s: %s" % (h["url"], type(e).__name__, e))

    # 4. Candidate work from durable state: evidence touched now plus any latest evidence still
    #    missing output (a crash after the evidence commit, or a budget placeholder).
    work = list(touched)
    for eid in _latest_evidence_ids(conn):
        if eid not in work and _missing_work(conn, eid, model.generator_name):
            work.append(eid)
            result["candidates_recovered"] += 1
    for eid in work:
        row = conn.execute("SELECT * FROM evidence WHERE id=?", (eid,)).fetchone()
        text = ev.load_evidence_text(conn, eid)

        # 4a. Closed action registry: deterministic, no model. The only source of 'pending' candidates.
        for match in rules.match_rules(text):
            if conn.execute("SELECT 1 FROM candidates WHERE dedupe_key=?",
                            (cands.dedupe_key(eid, match.rule.generator),)).fetchone():
                result["candidates_existing"] += 1
                continue
            try:
                conn.execute("BEGIN")
                cid = cands.save_candidate(conn, cands.build_rule_candidate(row, match))
                conn.execute("COMMIT")
                result["candidates_new" if cid else "candidates_existing"] += 1
            except Exception as e:
                _rollback(conn)
                result["failures"].append("rule candidate for evidence %d: %s: %s" % (eid, type(e).__name__, e))

        # 4b. Free-text model proposal: validated, stored for audit, never pending.
        key = cands.dedupe_key(eid, model.generator_name)
        existing = conn.execute("SELECT id, state_reason, state_set_by FROM candidates WHERE dedupe_key=?", (key,)).fetchone()
        placeholder = existing["id"] if cands.is_budget_placeholder(existing) else None
        if existing and placeholder is None:
            result["candidates_existing"] += 1
            continue
        meta = {"url": row["url"], "title": row["title"], "attribution": row["attribution"],
                "source_type": row["source_type"], "published_at": row["published_at"] or "unknown"}
        proposal, failure = None, None
        prior = _prior_attempt(conn, eid, model)
        try:
            if prior is not None:
                # F1: a durable reservation already exists for this evidence/provider/model, so the
                # request was dispatched once (process died, or the candidate save failed). Recover
                # an honest deferred row; never dispatch again automatically.
                failure = _settle_prior_attempt(conn, prior)
                result["attempts_settled"] += 1
            else:
                # Reservation (if any) is committed inside propose, before the request and outside the
                # candidate transaction below: a later rollback or crash cannot refund it. F2: the
                # reservation day/time is read from the clock right now, not at run start.
                t = clock()
                proposal = model.propose(conn, run_id, eid, text, meta, day=sch.day_of(t), called_at=sch.iso(t))
                failure = model.last_error
        except BudgetExhausted as e:
            failure = "%s: %s" % (cands.BUDGET_PLACEHOLDER_PREFIX, e)
            result["budget_deferred"] += 1
            if placeholder is not None:
                result["candidates_existing"] += 1
                result["inference_calls"] = model.calls_used
                continue   # still waiting; the placeholder already says so
        result["inference_calls"] = model.calls_used
        cand = cands.build_candidate(row, text, proposal, model.generator_name, failure)
        try:
            conn.execute("BEGIN")
            if placeholder is not None:
                cands.replace_placeholder(conn, placeholder, cand)
                cid = placeholder
            else:
                cid = cands.save_candidate(conn, cand)
            conn.execute("COMMIT")
            result["candidates_new" if cid else "candidates_existing"] += 1
        except Exception as e:
            _rollback(conn)
            result["failures"].append("candidate for evidence %d: %s: %s" % (eid, type(e).__name__, e))

    end = clock()
    result["day"] = sch.day_of(end)                      # the day the usage figure refers to
    result["inference_used_today"] = ModelClient.used_today(conn, result["day"])
    result["status"] = "failed" if result["failures"] else "ok"
    result["robots_requests"] = fetcher.robots_requests
    result["source_requests"] = fetcher.requests_made
    result["report_path"] = str(cfg.report_path)

    # Finalization order: durable run result first, then the report that renders it. These are two
    # separate writes (SQLite row, then a file); there is no atomicity between them. If the report
    # write fails, the run row is updated again to 'failed' with the reason; committed evidence and
    # candidates are untouched either way.
    def persist_status() -> None:
        summary = {k: v for k, v in result.items() if k != "failures"}
        summary["failures"] = list(result["failures"])
        conn.execute("UPDATE runs SET finished_at=?, status=?, summary=? WHERE run_id=?",
                     (sch.iso(clock()), result["status"], json.dumps(summary), run_id))

    try:
        persist_status()
    except Exception as e:
        result["status"] = "failed"
        result["report_path"] = None
        result["failures"].append("run status write: %s: %s (report not written: it would show this run as running)"
                                  % (type(e).__name__, e))
        return result
    try:
        cfg.report_path.parent.mkdir(parents=True, exist_ok=True)
        cfg.report_path.write_text(rpt.render(conn, now=clock()))
    except Exception as e:
        result["status"] = "failed"
        result["report_path"] = None
        result["failures"].append("report write to %s: %s: %s" % (cfg.report_path, type(e).__name__, e))
        try:
            persist_status()
        except Exception as e2:
            result["failures"].append("run status write after report failure: %s: %s" % (type(e2).__name__, e2))
    return result


def _prior_attempt(conn: sqlite3.Connection, eid: int, model: ModelClient) -> Optional[sqlite3.Row]:
    """The most recent durable reservation for this evidence with the current provider/model."""
    if model.provider == "none":
        return None
    return conn.execute(
        "SELECT id, status, error FROM inference_calls WHERE evidence_id=? AND provider=? AND COALESCE(model,'')=? "
        "ORDER BY id DESC LIMIT 1", (eid, model.provider, model.model or "")).fetchone()


def _settle_prior_attempt(conn: sqlite3.Connection, prior: sqlite3.Row) -> str:
    """Turn a dangling attempt into an honest reason without any external dispatch. A row still
    `reserved` means the process died after dispatch: it becomes `ambiguous` (the call may have run)."""
    if prior["status"] == "reserved":
        conn.execute("UPDATE inference_calls SET status='ambiguous', error=? WHERE id=? AND status='reserved'",
                     ("interrupted: worker died after dispatch; result unknown, not replayed", prior["id"]))
        return "ambiguous_response: interrupted after dispatch (reservation %d); not replayed" % prior["id"]
    return "prior_attempt_%s: reservation %d already dispatched (%s); not replayed" % (
        prior["status"], prior["id"], (prior["error"] or "result not persisted")[:120])


def _rollback(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("ROLLBACK")
    except Exception:
        pass


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="research.worker")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "cycle"):
        r = sub.add_parser(name)
        r.add_argument("--allowlist"); r.add_argument("--db"); r.add_argument("--report")
        r.add_argument("--provider", choices=["none", "ollama", "fixture"])
        r.add_argument("--max-urls", type=int); r.add_argument("--max-inference", type=int)
        r.add_argument("--max-inference-per-day", type=int)
    p = sub.add_parser("report"); p.add_argument("--db"); p.add_argument("--report")
    v = sub.add_parser("review"); v.add_argument("candidate_id", type=int)
    v.add_argument("state", choices=list(cands.VALID_HUMAN_STATES)); v.add_argument("--by", required=True)
    v.add_argument("--reason", required=True); v.add_argument("--db")
    rs = sub.add_parser("reset-source"); rs.add_argument("url"); rs.add_argument("--by", required=True)
    rs.add_argument("--reason", required=True); rs.add_argument("--db")
    a = ap.parse_args(argv)

    if a.cmd in ("run", "cycle"):
        cfg = Config.from_env(db_path=Path(a.db) if a.db else None, allowlist_path=Path(a.allowlist) if a.allowlist else None,
                              report_path=Path(a.report) if a.report else None, provider=a.provider,
                              max_urls=a.max_urls, max_inference=a.max_inference,
                              max_inference_per_day=a.max_inference_per_day)
        if cfg.provider == "fixture":
            print("provider=fixture is only available programmatically (tests)", file=sys.stderr)
            return 2
        res = run(cfg, transport=urllib_transport, due_only=(a.cmd == "cycle"))
        print(json.dumps(res, indent=2))
        if res["status"] == "locked":
            return 3
        return 0 if res.ok else 1
    cfg = Config.from_env(db_path=Path(a.db) if a.db else None, report_path=Path(getattr(a, "report", None)) if getattr(a, "report", None) else None)
    conn = dbm.connect(cfg.db_path)
    dbm.migrate(conn)
    if a.cmd == "report":
        text = rpt.render(conn)
        cfg.report_path.parent.mkdir(parents=True, exist_ok=True)
        cfg.report_path.write_text(text)
        print(text)
        return 0
    if a.cmd == "review":
        conn.execute("BEGIN")
        cands.human_review(conn, a.candidate_id, a.state, a.by, a.reason)
        conn.execute("COMMIT")
        print("candidate %d -> %s by %s" % (a.candidate_id, a.state, a.by))
        return 0
    if a.cmd == "reset-source":
        conn.execute("BEGIN")
        sch.reset_source(conn, a.url, a.by, a.reason, sch.utc_now())
        conn.execute("COMMIT")
        print("source %s reset: due now" % a.url)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
