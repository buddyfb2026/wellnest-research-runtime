"""Manually invoked research worker (WEL-40). No scheduler, no daemon.

    python3 -m research.worker run   [--allowlist F] [--db F] [--report F] [--provider none|ollama|fixture]
                                     [--max-urls N] [--max-inference N] [--no-robots]
    python3 -m research.worker report [--db F] [--report F]
    python3 -m research.worker review CANDIDATE_ID approved|rejected|deferred|pending --by NAME --reason TEXT
"""
import argparse
import json
import sqlite3
import sys
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import candidates as cands
from . import db as dbm
from . import evidence as ev
from . import report as rpt
from .config import Config
from .extract import extract
from .fetch import Fetcher, FetchResult, now_iso, urllib_transport
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
    return srcs


def run(cfg: Config, transport=urllib_transport, model: Optional[ModelClient] = None,
        content_kind: str = "live", check_robots: bool = True,
        conn_factory: Callable[[Path], sqlite3.Connection] = dbm.connect) -> RunResult:
    run_id = "run_%s_%s" % (now_iso().replace(":", "").replace("-", ""), uuid.uuid4().hex[:6])
    result = RunResult(run_id=run_id, status="running", fetched_ok=0, blocked=0, errors=0, skipped_policy=0,
                       evidence_new=0, evidence_existing=0, candidates_new=0, candidates_existing=0,
                       inference_calls=0, failures=[])
    try:
        conn = conn_factory(cfg.db_path)
        dbm.migrate(conn)
        conn.execute("INSERT INTO runs(run_id, started_at, status) VALUES(?,?,?)", (run_id, now_iso(), "running"))
    except Exception as e:
        result["status"] = "failed"
        result["failures"].append("database unavailable: %s: %s" % (type(e).__name__, e))
        return result

    sources = load_allowlist(cfg.allowlist_path)
    fetcher = Fetcher(transport, cfg.user_agent, cfg.fetch_timeout_s, cfg.max_body_bytes, check_robots)
    model = model or ModelClient(cfg.provider, cfg.max_inference, cfg.ollama_model, cfg.ollama_url)
    attempted = 0
    evidence_ids: List[int] = []

    for hint in sources:
        try:
            conn.execute("BEGIN")
            ev.upsert_source_hint(conn, hint)
            if not hint.get("fetch", False):
                ev.record_fetch_attempt(conn, run_id, hint["url"], "skipped_policy", now_iso(),
                                        reason="no permitted access basis: %s" % hint["access_basis"])
                result["skipped_policy"] += 1
                conn.execute("COMMIT")
                continue
            if attempted >= cfg.max_urls:
                ev.record_fetch_attempt(conn, run_id, hint["url"], "skipped_policy", now_iso(),
                                        reason="url cap %d reached" % cfg.max_urls)
                result["skipped_policy"] += 1
                conn.execute("COMMIT")
                continue
            attempted += 1
            fr: FetchResult = fetcher.fetch(hint["url"])
            if fr.outcome != "ok":
                ev.record_fetch_attempt(conn, run_id, fr.url, fr.outcome, fr.attempted_at, fr.http_status,
                                        fr.final_url, fr.robots_status, fr.reason)
                result["blocked" if fr.outcome == "blocked" else "errors"] += 1
                conn.execute("COMMIT")
                continue
            ex = extract(fr.html or "")
            if len(ex.text) < 200:
                ev.record_fetch_attempt(conn, run_id, fr.url, "error", fr.attempted_at, fr.http_status,
                                        fr.final_url, fr.robots_status, "no usable text extracted")
                result["errors"] += 1
                conn.execute("COMMIT")
                continue
            eid, is_new = ev.store_evidence(conn, hint, fr, ex, content_kind)
            ev.record_fetch_attempt(conn, run_id, fr.url, "ok", fr.attempted_at, fr.http_status, fr.final_url,
                                    fr.robots_status, None if is_new else "content unchanged (hash match)", eid)
            result["fetched_ok"] += 1
            result["evidence_new" if is_new else "evidence_existing"] += 1
            evidence_ids.append(eid)
            conn.execute("COMMIT")
        except Exception as e:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            result["failures"].append("persist %s: %s: %s" % (hint["url"], type(e).__name__, e))

    for eid in evidence_ids:
        row = conn.execute("SELECT * FROM evidence WHERE id=?", (eid,)).fetchone()
        key = cands.dedupe_key(eid, model.generator_name)
        if conn.execute("SELECT 1 FROM candidates WHERE dedupe_key=?", (key,)).fetchone():
            result["candidates_existing"] += 1
            continue
        text = ev.load_evidence_text(conn, eid)
        meta = {"url": row["url"], "title": row["title"], "attribution": row["attribution"],
                "source_type": row["source_type"], "published_at": row["published_at"] or "unknown"}
        proposal, failure = None, None
        try:
            conn.execute("BEGIN")
            try:
                proposal = model.propose(conn, run_id, eid, text, meta)
                failure = model.last_error
            except BudgetExhausted as e:
                failure = "inference_budget_exhausted: %s" % e
            result["inference_calls"] = model.calls_used
            cand = cands.build_candidate(row, text, proposal, model.generator_name, failure)
            cid = cands.save_candidate(conn, cand)
            conn.execute("COMMIT")
            result["candidates_new" if cid else "candidates_existing"] += 1
        except Exception as e:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            result["failures"].append("candidate for evidence %d: %s: %s" % (eid, type(e).__name__, e))

    result["status"] = "failed" if result["failures"] else "ok"
    result["robots_requests"] = fetcher.robots_requests
    result["source_requests"] = fetcher.requests_made
    try:
        summary = {k: v for k, v in result.items() if k != "failures"}
        summary["failures"] = len(result["failures"])
        conn.execute("UPDATE runs SET finished_at=?, status=?, summary=? WHERE run_id=?",
                     (now_iso(), result["status"], json.dumps(summary), run_id))
        cfg.report_path.parent.mkdir(parents=True, exist_ok=True)
        cfg.report_path.write_text(rpt.render(conn))
        result["report_path"] = str(cfg.report_path)
    except Exception as e:
        result["status"] = "failed"
        result["failures"].append("finalize: %s: %s" % (type(e).__name__, e))
    return result


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="research.worker")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--allowlist"); r.add_argument("--db"); r.add_argument("--report")
    r.add_argument("--provider", choices=["none", "ollama", "fixture"])
    r.add_argument("--max-urls", type=int); r.add_argument("--max-inference", type=int)
    r.add_argument("--no-robots", action="store_true", help="tests/fixtures only")
    p = sub.add_parser("report"); p.add_argument("--db"); p.add_argument("--report")
    v = sub.add_parser("review"); v.add_argument("candidate_id", type=int)
    v.add_argument("state", choices=list(cands.VALID_HUMAN_STATES)); v.add_argument("--by", required=True)
    v.add_argument("--reason", required=True); v.add_argument("--db")
    a = ap.parse_args(argv)

    if a.cmd == "run":
        cfg = Config.from_env(db_path=Path(a.db) if a.db else None, allowlist_path=Path(a.allowlist) if a.allowlist else None,
                              report_path=Path(a.report) if a.report else None, provider=a.provider,
                              max_urls=a.max_urls, max_inference=a.max_inference)
        if cfg.provider == "fixture":
            print("provider=fixture is only available programmatically (tests)", file=sys.stderr)
            return 2
        res = run(cfg, check_robots=not a.no_robots)
        print(json.dumps(res, indent=2))
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
    return 2


if __name__ == "__main__":
    sys.exit(main())
