"""Source/topic yield report (WEL-43 AC1). No schema change, no network, no model call.

`collect` and `render` are read-only: they open no transaction and write nothing. Only the CLI
touches the store, and only to apply the existing migrations so it can be pointed at a fresh path.

What this module does: it counts what the store actually contains and names, for every document and
every candidate, exactly one outcome class. What it deliberately does NOT do:

  * it never ranks sources and never computes a rate or a score from a handful of documents;
  * it never treats "no registered rule matched" or "provider=none" as a source failure — those are
    coverage gaps of this repository, not evidence about the publisher;
  * it never treats a pending or human-approved candidate as a completed household outcome.

Denominators are distinct documents, i.e. distinct (url, content_hash) evidence rows. Repeated
collection of unchanged content produces a fetch attempt but no new document, so re-running the
worker cannot inflate the sample.

    python3 -m research.quality --db work/research.sqlite [--out work/quality.md]
"""
import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlsplit

from . import candidates as cands
from . import db as dbm
from . import schedule as sch

# A sample smaller than this is reported as counts only: no rates, no ranking, no "best source".
MIN_SAMPLE_FOR_RATES = 30
STALE_AFTER_DAYS = 730

CANDIDATE_CLASSES = {
    "human_approved": "a reviewer approved the prepared action. Approval is a review decision only — "
                      "it is not evidence that any household did anything.",
    "human_rejected": "a reviewer rejected the candidate.",
    "human_deferred": "a reviewer deferred the candidate.",
    "human_pending": "a reviewer put the candidate back to pending.",
    "rule_supported_unreviewed": "the closed action registry matched a reviewed sentence verbatim; "
                                 "no human has reviewed it yet. Not a quality verdict.",
    "no_inference_provider": "no model was configured (provider=none), so no proposal was produced. "
                             "This says nothing about the source.",
    "waiting_inference_budget": "the daily inference cap was reached; the candidate is a placeholder.",
    "model_proposal_unregistered": "a free-text model proposal was stored for audit and deferred or "
                                   "rejected because it is not a registered action.",
    "unknown": "the record does not fit any defined class; reported as unknown rather than success.",
}


def _host(url: str) -> str:
    return urlsplit(url).netloc or url


def _validation_kind(raw: Optional[str]) -> Optional[str]:
    try:
        v = json.loads(raw) if raw else None
    except Exception:
        return None
    return v.get("kind") if isinstance(v, dict) else None


def classify_candidate(row: sqlite3.Row) -> str:
    """Exactly one class per candidate row. Never guesses in the direction of success."""
    set_by = row["state_set_by"] or ""
    state = row["state"] or "unknown"
    if set_by.startswith("human:"):
        return "human_%s" % state if "human_%s" % state in CANDIDATE_CLASSES else "unknown"
    reason = row["state_reason"] or ""
    if reason.startswith(cands.BUDGET_PLACEHOLDER_PREFIX):
        return "waiting_inference_budget"
    if reason.startswith("inference_unavailable"):
        return "no_inference_provider"
    kind = _validation_kind(row["validation"])
    if kind == "rule" and state == "pending":
        return "rule_supported_unreviewed"
    if kind == "free_text" and state in ("deferred", "rejected"):
        return "model_proposal_unregistered"
    return "unknown"


def _freshness(published_at: Optional[str], basis: str, now: datetime) -> str:
    if not published_at or basis == "unknown":
        return "date_unknown"
    try:
        day = datetime.strptime(published_at[:10], "%Y-%m-%d")
    except Exception:
        return "date_unknown"
    age = (now.replace(tzinfo=None) - day).days
    if age < 0:
        return "date_unknown"
    return "older_than_%dd" % STALE_AFTER_DAYS if age > STALE_AFTER_DAYS else "within_%dd" % STALE_AFTER_DAYS


def collect(conn: sqlite3.Connection, now: Optional[datetime] = None) -> Dict[str, object]:
    """Pure aggregation over existing tables. Opens no transaction and writes nothing."""
    now = now or sch.utc_now()
    ev_rows = conn.execute(
        "SELECT id, url, content_hash, version_no, published_at, published_at_basis, content_kind, "
        "source_type, attribution FROM evidence ORDER BY url, version_no").fetchall()
    documents = {}          # (url, content_hash) -> row ; the honest sample unit
    for r in ev_rows:
        documents.setdefault((r["url"], r["content_hash"]), r)

    cand_rows = conn.execute("SELECT c.*, e.url AS url FROM candidates c JOIN evidence e ON e.id=c.evidence_id").fetchall()
    attempts = Counter(r["outcome"] for r in conn.execute("SELECT outcome FROM fetch_attempts").fetchall())
    unchanged_refetch = int(conn.execute(
        "SELECT COUNT(*) FROM fetch_attempts WHERE reason LIKE 'content unchanged%'").fetchone()[0])

    by_host: Dict[str, Dict[str, object]] = defaultdict(
        lambda: {"documents": 0, "urls": set(), "versions": 0, "classes": Counter(), "freshness": Counter(),
                 "evidence_ids": set(), "attempts": Counter()})
    for (url, _h), r in documents.items():
        b = by_host[_host(url)]
        b["documents"] += 1
        b["urls"].add(url)
        b["freshness"][_freshness(r["published_at"], r["published_at_basis"], now)] += 1
    for r in ev_rows:
        b = by_host[_host(r["url"])]
        b["versions"] += 1
        b["evidence_ids"].add(int(r["id"]))
    for r in conn.execute("SELECT url, outcome FROM fetch_attempts").fetchall():
        by_host[_host(r["url"])]["attempts"][r["outcome"]] += 1

    classes = Counter()
    ev_with_rule = set()
    ev_with_candidate = set()
    for c in cand_rows:
        cls = classify_candidate(c)
        classes[cls] += 1
        by_host[_host(c["url"])]["classes"][cls] += 1
        ev_with_candidate.add(int(c["evidence_id"]))
        if _validation_kind(c["validation"]) == "rule":
            ev_with_rule.add(int(c["evidence_id"]))

    all_ev_ids = {int(r["id"]) for r in ev_rows}
    hints = conn.execute("SELECT fetch_permitted, access_assessment, discovery_route FROM source_hints").fetchall()
    state_rows = conn.execute("SELECT url, attempts, last_outcome, stalled FROM source_state").fetchall()

    return {
        "now": sch.iso(now),
        "documents": len(documents),
        "evidence_rows": len(ev_rows),
        "distinct_urls": len({u for u, _ in documents}),
        # `hosts` also contains hosts that were only ever attempted (blocked or failed): they keep
        # their attempt counts, but a host with no document is not a source with evidence.
        "hosts": {h: v for h, v in by_host.items()},
        "hosts_with_evidence": sum(1 for v in by_host.values() if v["documents"]),
        "hosts_attempted_without_evidence": sorted(h for h, v in by_host.items() if not v["documents"]),
        "attempts": attempts,
        "attempts_total": sum(attempts.values()),
        "unchanged_refetch": unchanged_refetch,
        "candidates": len(cand_rows),
        "classes": classes,
        "evidence_without_candidate": sorted(all_ev_ids - ev_with_candidate),
        "evidence_without_rule_match": sorted(all_ev_ids - ev_with_rule),
        "human_reviewed": sum(n for c, n in classes.items() if c.startswith("human_")),
        "inference_calls": int(conn.execute("SELECT COUNT(*) FROM inference_calls").fetchone()[0]),
        "inference_by_status": Counter(
            (r["status"] or "legacy") for r in conn.execute("SELECT status FROM inference_calls").fetchall()),
        "hints_total": len(hints),
        "hints_permitted": sum(1 for h in hints if h["fetch_permitted"]),
        "hints_unassessed": sum(1 for h in hints if h["discovery_route"] and not h["access_assessment"]),
        "sources_scheduled": len(state_rows),
        "sources_never_attempted": sum(1 for r in state_rows if not r["attempts"]),
        "sources_stalled": sum(1 for r in state_rows if r["stalled"]),
    }


def render(conn: sqlite3.Connection, now: Optional[datetime] = None) -> str:
    d = collect(conn, now)
    hosts = d["hosts"]
    n_hosts = d["hosts_with_evidence"]        # hosts that produced at least one document
    n_attempted_only = len(d["hosts_attempted_without_evidence"])
    largest = max([v["documents"] for v in hosts.values()] or [0])
    out: List[str] = [
        "# WellNest source yield report (WEL-43)", "",
        "Generated %s from the research store only. Read-only: this report writes nothing and makes "
        "no network or model call." % d["now"], "",
        "## How to read this", "",
        "- The sample unit is a **distinct document** = one `(url, content_hash)` evidence row. "
        "Re-collecting unchanged content adds a fetch attempt, not a document, so repeated runs "
        "cannot inflate the sample.",
        "- **No rates and no ranking are shown.** The largest per-source sample here is %d document(s); "
        "the threshold for computing a rate is %d. Counts only." % (largest, MIN_SAMPLE_FOR_RATES),
        "- \"No registered rule matched\" and \"provider=none\" are **coverage gaps of this repository**, "
        "not source failures, and are reported in their own section.",
        "- A pending or approved candidate is a review state. It is **not** evidence that a household "
        "did anything.", "",
        "## Denominators", "",
        "| quantity | value |", "|---|---|",
        "| distinct documents (sample unit) | %d |" % d["documents"],
        "| evidence rows incl. superseded versions | %d |" % d["evidence_rows"],
        "| distinct urls with evidence | %d |" % d["distinct_urls"],
        "| distinct hosts (sources) with evidence | %d |" % n_hosts,
        "| hosts attempted but with no evidence (blocked/failed only) | %d |" % n_attempted_only,
        "| fetch attempts (all outcomes) | %d |" % d["attempts_total"],
        "| of which re-fetches of unchanged content | %d |" % d["unchanged_refetch"],
        "| candidates | %d |" % d["candidates"],
        "| candidates with a human review decision | %d |" % d["human_reviewed"],
        "| inference calls recorded | %d |" % d["inference_calls"],
        "| scheduled sources (permitted) | %d (never attempted %d, stalled %d) |" % (
            d["sources_scheduled"], d["sources_never_attempted"], d["sources_stalled"]),
        "| discovery hints | %d (permitted %d, discovered but unassessed %d) |" % (
            d["hints_total"], d["hints_permitted"], d["hints_unassessed"]),
        "",
        "## Topic yield", "",
        "Topic is **not recorded** by schema v4: there is no topic, tag or category column on evidence "
        "or candidates. No topic breakdown is shown, and none is inferred from urls or titles.", "",
        "## Per-source counts", "",
        "| source (host) | documents | evidence versions | fetch ok | blocked | error | freshness | candidate classes |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for host in sorted(hosts):
        v = hosts[host]
        fresh = ", ".join("%s=%d" % (k, n) for k, n in sorted(v["freshness"].items())) or "-"
        cls = ", ".join("%s=%d" % (k, n) for k, n in sorted(v["classes"].items())) or "none"
        out.append("| %s | %d | %d | %d | %d | %d | %s | %s |" % (
            host, v["documents"], v["versions"], v["attempts"].get("ok", 0), v["attempts"].get("blocked", 0),
            v["attempts"].get("error", 0), fresh, cls))
    if not hosts:
        out.append("| _no source attempted_ | 0 | 0 | 0 | 0 | 0 | - | none |")
    out += ["",
            "A row with 0 documents is a host that was attempted and produced no evidence (blocked or "
            "failed). Its attempts are shown here, and it is **not** counted as a source with evidence: "
            "%d of the %d host(s) in this table are in that position." % (n_attempted_only, len(hosts)),
            "",
            "Comparing sources against each other is **not possible from this table**: %s" % (
                "no source has evidence yet." if n_hosts == 0 else
                "there is only one source with evidence." if n_hosts == 1
                else "each per-source sample is far below %d documents." % MIN_SAMPLE_FOR_RATES),
            "",
            "## Candidate outcome classes", "",
            "Every candidate row falls in exactly one class (total %d = candidates %d)." % (
                sum(d["classes"].values()), d["candidates"]), "",
            "| class | count | meaning |", "|---|---|---|"]
    for cls, meaning in CANDIDATE_CLASSES.items():
        out.append("| %s | %d | %s |" % (cls, d["classes"].get(cls, 0), meaning))
    out += ["",
            "## Coverage gaps (NOT source failures)", "", "| gap | count | note |", "|---|---|---|",
            "| evidence with no registered rule match | %d | `research/rules.py` currently registers a small "
            "closed set of reviewed actions. An unmatched document means this repository has no rule for it. |"
            % len(d["evidence_without_rule_match"]),
            "| evidence with no candidate row at all | %d | no rule matched and no proposal was attempted. |"
            % len(d["evidence_without_candidate"]),
            "| candidates with no model available | %d | provider was `none`. |" % d["classes"].get("no_inference_provider", 0),
            "| candidates waiting for inference budget | %d | the daily cap stopped the work honestly. |"
            % d["classes"].get("waiting_inference_budget", 0),
            "",
            "## What remains unknown", "",
            "- Whether any collected guidance is **factually correct**: no reviewer has scored factual "
            "support (%d of %d candidates carry a human decision)." % (d["human_reviewed"], d["candidates"]),
            "- Whether any source is **better than another**: %d source(s) have evidence." % n_hosts,
            "- Whether any candidate **helped a household**: household outcomes are out of scope here (WEL-33).",
            "- Model-assisted extraction quality: %d inference call(s) are recorded (%s)." % (
                d["inference_calls"],
                ", ".join("%s=%d" % kv for kv in sorted(d["inference_by_status"].items())) or "none"),
            "- %d discovered hint(s) have no access assessment yet, so their yield is unmeasured." % d["hints_unassessed"],
            "",
            "## Not claimed", "",
            "This report does not claim any quality improvement, does not rank sources, does not treat "
            "popularity or link counts as quality, and does not use rejected or deferred rows as evidence "
            "that a source is bad. The sample above is too small to support any of those claims.", ""]
    return "\n".join(out)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="research.quality", description="read-only source yield report")
    ap.add_argument("--db", required=True)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    conn = dbm.connect(Path(a.db))
    dbm.migrate(conn)          # no-op on an existing store; keeps the CLI usable on a fresh one
    try:
        text = render(conn)
    finally:
        conn.close()
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
