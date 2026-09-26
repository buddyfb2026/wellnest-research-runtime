"""Retained, versioned cross-source research knowledge (WEL-51).

This module is operator-invoked and local-store only.  It does not fetch, call a
model, publish recipes, or participate in the worker cycle.
"""
import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, Union

from . import db, recipes
from . import source_registry as registry
from .lock import StoreLock

RULE = "wel51_total_time_v1"
TOPIC = "recipe_supply"
CLAIM_SLUG = "total-time-not-stated-by-source"
CLAIM = "A source-backed recipe may omit an explicit total time; where it is absent, no total is derived."
VALID_STATES = ("approved", "rejected", "deferred")
FOLLOWUP_KEYS = {"question", "target_surface_url", "bounds", "reason", "decision_inputs"}
BOUNDS_KEYS = {"max_depth", "max_pages", "max_model_calls", "deadline_at"}
INPUT_KEYS = {"topic", "supporting_roots", "target"}
TARGET_KEYS = {"url", "surface_kind", "topics", "roster_status", "access_status",
               "root_publisher_id", "evidence_rows"}


class KnowledgeRefused(ValueError):
    pass


class SimulatedCrash(RuntimeError):
    pass


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _parse(value: Any, fallback: Any = None) -> Any:
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _latest_version(conn: sqlite3.Connection, finding_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM finding_versions WHERE finding_id=? ORDER BY version_no DESC LIMIT 1",
        (finding_id,),
    ).fetchone()


def _eligible_current(conn: sqlite3.Connection, recipe_id: int) -> Optional[sqlite3.Row]:
    row = recipes.resolve_current(conn, recipe_id)
    if row is None or row["state"] == "rejected" or recipes.is_budget_placeholder(row) or row["completeness"] == "failed":
        return None
    evidence = conn.execute("SELECT url,version_no FROM evidence WHERE id=?", (row["evidence_id"],)).fetchone()
    if evidence is None:
        return None
    latest = conn.execute("SELECT id FROM evidence WHERE url=? ORDER BY version_no DESC LIMIT 1", (evidence["url"],)).fetchone()
    return row if latest and int(latest["id"]) == int(row["evidence_id"]) else None


def _literal(slot: Any) -> Optional[Tuple[str, int, int]]:
    if not isinstance(slot, dict):
        return None
    source = slot.get("source") if slot.get("support") == "source_normalized" else slot
    if not isinstance(source, dict) or source.get("support") != "source_literal":
        return None
    literal, span = source.get("value"), source.get("span")
    if not isinstance(literal, str) or not literal or not isinstance(span, dict):
        return None
    start, end = span.get("start"), span.get("end")
    if type(start) is not int or type(end) is not int or start < 0 or end <= start:
        return None
    return literal, start, end


def _classify(document: Dict[str, Any], unknown_fields: Any, evidence_text: str) -> Tuple[Optional[str], Optional[str], Optional[Dict[str, Any]]]:
    times = document.get("times") if isinstance(document.get("times"), dict) else {}
    total = times.get("total_time")
    unknowns = unknown_fields if isinstance(unknown_fields, list) else []
    absent = (isinstance(total, dict) and total.get("value") is None
              and any(isinstance(u, dict) and u.get("field") == "total_time"
                      and u.get("reason") == "not_stated_by_source" for u in unknowns))
    if absent:
        stated = []
        for field in ("prep_time", "cook_time"):
            bound = _literal(times.get(field))
            if bound is not None:
                literal, start, end = bound
                if end > len(evidence_text) or evidence_text[start:end] != literal:
                    return None, None, None
                stated.append({"field": field, "literal": literal,
                                "span": {"start": start, "end": end}})
        return "supports", "inferred", {
            "rule": RULE,
            "unknown": {"field": "total_time", "reason": "not_stated_by_source"},
            "stated": stated,
        }
    bound = _literal(total)
    if bound is None:
        return None, None, None
    literal, start, end = bound
    if end > len(evidence_text) or evidence_text[start:end] != literal:
        return None, None, None
    return "qualifies_or_contradicts", "observed", {
        "field": "total_time", "literal": literal, "span": {"start": start, "end": end},
    }


def _live_links(conn: sqlite3.Connection, finding_id: int) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    rows = conn.execute(
        """SELECT fl.*,rv.recipe_id,e.url,e.content_kind,e.fetched_at
           FROM finding_links fl JOIN recipe_versions rv ON rv.id=fl.recipe_version_id
           JOIN evidence e ON e.id=fl.evidence_id WHERE fl.finding_id=? ORDER BY fl.id""",
        (finding_id,),
    ).fetchall()
    for row in rows:
        current = _eligible_current(conn, int(row["recipe_id"]))
        if current is None or int(current["id"]) != int(row["recipe_version_id"]):
            continue
        if current["content_fingerprint"] != row["content_fingerprint"]:
            continue
        value = dict(row)
        value["root_publisher_id"] = registry.resolve(conn, row["url"])["root_publisher_id"]
        value["basis_detail"] = _parse(row["basis_detail"], {})
        result.append(value)
    return result


def independent_support(conn: sqlite3.Connection, finding_id: int) -> Dict[str, Any]:
    links = _live_links(conn, finding_id)
    supports = [row for row in links if row["relation"] == "supports"]
    qualifiers = [row for row in links if row["relation"] == "qualifies_or_contradicts"]
    attributed = [row for row in supports if row["root_publisher_id"] is not None]
    parent = list(range(len(attributed)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        a, b = find(left), find(right)
        if a != b:
            parent[b] = a

    for left in range(len(attributed)):
        for right in range(left + 1, len(attributed)):
            if (attributed[left]["evidence_content_hash"] == attributed[right]["evidence_content_hash"]
                    or attributed[left]["root_publisher_id"] == attributed[right]["root_publisher_id"]):
                union(left, right)
    grouped: Dict[int, set] = {}
    for index, row in enumerate(attributed):
        grouped.setdefault(find(index), set()).add(row["root_publisher_id"])
    components = sorted([sorted(values) for values in grouped.values()])
    return {
        "independent_publisher_count": len(components),
        "components": components,
        "distinct_roots": len({row["root_publisher_id"] for row in attributed}),
        "unattributed_supports": sorted({row["url"] for row in supports if row["root_publisher_id"] is None}),
        "unattributed_qualifiers": sorted({row["url"] for row in qualifiers if row["root_publisher_id"] is None}),
        "fixture_links": sum(row["content_kind"] == "fixture" for row in links),
        "supporting_roots": sorted({row["root_publisher_id"] for row in attributed}),
    }


def _digest(conn: sqlite3.Connection, finding_id: int) -> str:
    links = sorted([
        [row["url"], row["evidence_content_hash"], row["content_fingerprint"],
         row["relation"], row["root_publisher_id"]]
        for row in _live_links(conn, finding_id)
    ], key=lambda value: recipes.canonical_json(value))
    return _sha(recipes.canonical_json({"rule": RULE, "links": links}))


def target_ok(conn: sqlite3.Connection, url: str, topic: str, supporting_roots: Iterable[str]) -> List[str]:
    row = conn.execute("SELECT * FROM source_surfaces WHERE url=?", (url,)).fetchone()
    if row is None or row["surface_kind"] != "site_article":
        return ["target surface absent or not site_article"]
    reasons = []
    topics = _parse(row["topics"], [])
    if topic not in topics:
        reasons.append("target topic no longer includes %s" % topic)
    denied = registry.effective_denied(conn, url)
    if denied is not None:
        reasons.append(denied)
    if conn.execute("SELECT COUNT(*) FROM evidence WHERE url=?", (url,)).fetchone()[0]:
        reasons.append("evidence now exists for target")
    root = registry.resolve(conn, url)["root_publisher_id"]
    if root in set(supporting_roots):
        reasons.append("target root now among supporting roots")
    return reasons


def _target_snapshot(conn: sqlite3.Connection, url: str) -> Dict[str, Any]:
    row = conn.execute("SELECT * FROM source_surfaces WHERE url=?", (url,)).fetchone()
    return {
        "url": url, "surface_kind": row["surface_kind"], "topics": _parse(row["topics"], []),
        "roster_status": row["roster_status"], "access_status": row["access_status"],
        "root_publisher_id": registry.resolve(conn, url)["root_publisher_id"],
        "evidence_rows": conn.execute("SELECT COUNT(*) FROM evidence WHERE url=?", (url,)).fetchone()[0],
    }


def _select_target(conn: sqlite3.Connection, topic: str, supporting_roots: Iterable[str]) -> Optional[str]:
    for row in conn.execute("SELECT url FROM source_surfaces ORDER BY url"):
        if target_ok(conn, row["url"], topic, supporting_roots) == []:
            return row["url"]
    return None


def select_followup(conn: sqlite3.Connection, finding_id: int,
                    unresolved: Optional[List[Any]] = None) -> Dict[str, Any]:
    latest = _latest_version(conn, finding_id)
    if unresolved is None:
        unresolved = _parse(latest["unresolved"], []) if latest else []
    accounting = independent_support(conn, finding_id)
    roots = accounting["supporting_roots"]
    if not unresolved:
        return {"state": "none", "target": None, "reason": None, "supporting_roots": roots}
    target = _select_target(conn, TOPIC, roots)
    if target is None:
        return {"state": "refused", "target": None,
                "reason": "no permitted uncollected surface for topic %s" % TOPIC,
                "supporting_roots": roots}
    return {"state": "proposed", "target": target, "reason": None, "supporting_roots": roots}


def _followup(conn: sqlite3.Connection, finding_id: int, unresolved: List[Any], created_at: str) -> Tuple[str, str]:
    selected = select_followup(conn, finding_id, unresolved)
    target = selected["target"]
    deadline = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) + timedelta(days=7)
    value = {
        "question": ("Does %s independently confirm or qualify whether a source-backed recipe may omit an explicit total time?" % target
                     if target else "Is there a permitted uncollected source that can confirm or qualify this finding?"),
        "target_surface_url": target,
        "bounds": {"max_depth": 1, "max_pages": 1, "max_model_calls": 1,
                   "deadline_at": deadline.strftime("%Y-%m-%dT%H:%M:%SZ")},
        "reason": selected["reason"],
        "decision_inputs": {"topic": TOPIC, "supporting_roots": selected["supporting_roots"],
                            "target": _target_snapshot(conn, target) if target else None},
    }
    return selected["state"], recipes.canonical_json(value)


def _valid_followup(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != FOLLOWUP_KEYS:
        return False
    bounds, inputs = value.get("bounds"), value.get("decision_inputs")
    if not isinstance(bounds, dict) or set(bounds) != BOUNDS_KEYS or not isinstance(inputs, dict) or set(inputs) != INPUT_KEYS:
        return False
    target = inputs.get("target")
    return target is None or (isinstance(target, dict) and set(target) == TARGET_KEYS)


def current_followup(conn: sqlite3.Connection, version_row: sqlite3.Row) -> Dict[str, Any]:
    recorded = _parse(version_row["followup"])
    base = {"status": "unreadable", "recorded": recorded, "withdrawn_reasons": [],
            "actionable_target_url": None}
    if not _valid_followup(recorded):
        return base
    if version_row["rule"] != RULE or _digest(conn, int(version_row["finding_id"])) != version_row["support_digest"]:
        return dict(base, status="stale_version")
    state = version_row["followup_state"]
    if state == "none":
        return dict(base, status="none")
    if state == "proposed":
        target = recorded["target_surface_url"]
        reasons = target_ok(conn, target, TOPIC, independent_support(conn, int(version_row["finding_id"]))["supporting_roots"])
        if reasons:
            return dict(base, status="withdrawn", withdrawn_reasons=reasons)
        return dict(base, status="eligible", actionable_target_url=target)
    if state == "refused":
        selected = select_followup(conn, int(version_row["finding_id"]))
        if selected["target"]:
            return dict(base, status="newly_eligible", actionable_target_url=selected["target"])
        return dict(base, status="refused")
    return base


def _statement(conn: sqlite3.Connection, finding_id: int) -> Dict[str, Any]:
    links = []
    for row in _live_links(conn, finding_id):
        links.append({"url": row["url"], "evidence_content_hash": row["evidence_content_hash"],
                      "content_fingerprint": row["content_fingerprint"], "relation": row["relation"],
                      "root_publisher_id": row["root_publisher_id"], "basis": row["basis"],
                      "basis_detail": row["basis_detail"], "content_kind": row["content_kind"]})
    return {"claim": CLAIM, "rule": RULE,
            "links": sorted(links, key=lambda row: (row["relation"], row["url"])),
            "independent_support": independent_support(conn, finding_id)}


def _synthesize_conn(conn: sqlite3.Connection, crash_hook: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    finding_key = _sha(TOPIC + "|" + CLAIM_SLUG)
    prior_finding = conn.execute("SELECT id FROM findings WHERE finding_key=?", (finding_key,)).fetchone()
    if prior_finding:
        latest = _latest_version(conn, int(prior_finding["id"]))
        if latest is not None and latest["rule"] != RULE:
            raise KnowledgeRefused("unknown knowledge rule")
    now = _iso_now()
    failures = []
    conn.execute("BEGIN")
    try:
        conn.execute("INSERT OR IGNORE INTO findings(finding_key,topic,claim_slug,created_at) VALUES(?,?,?,?)",
                     (finding_key, TOPIC, CLAIM_SLUG, now))
        finding_id = int(conn.execute("SELECT id FROM findings WHERE finding_key=?", (finding_key,)).fetchone()["id"])
        for recipe in conn.execute("SELECT id FROM recipes ORDER BY id").fetchall():
            version = _eligible_current(conn, int(recipe["id"]))
            if version is None:
                continue
            document = _parse(version["content"], {})
            unknown_fields = _parse(version["unknown_fields"], [])
            evidence = conn.execute("SELECT e.*,t.text FROM evidence e JOIN evidence_text t ON t.evidence_id=e.id WHERE e.id=?",
                                    (version["evidence_id"],)).fetchone()
            relation, basis, detail = _classify(document, unknown_fields, evidence["text"])
            if relation is None:
                total = document.get("times", {}).get("total_time") if isinstance(document, dict) else None
                if _literal(total) is not None or any(isinstance(u, dict) and u.get("field") == "total_time"
                                                      and u.get("reason") == "not_stated_by_source" for u in unknown_fields):
                    failures.append({"recipe_version_id": int(version["id"]), "reason": "literal_span_mismatch"})
                continue
            conn.execute(
                """INSERT OR IGNORE INTO finding_links(finding_id,relation,evidence_id,evidence_content_hash,
                   recipe_version_id,content_fingerprint,basis,basis_detail,rule,observed_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (finding_id, relation, version["evidence_id"], evidence["content_hash"], version["id"],
                 version["content_fingerprint"], basis, recipes.canonical_json(detail), RULE, now),
            )
        digest = _digest(conn, finding_id)
        latest = _latest_version(conn, finding_id)
        inserted = 0
        if latest is None or latest["support_digest"] != digest:
            statement = _statement(conn, finding_id)
            unresolved = [row for row in statement["links"] if row["relation"] == "qualifies_or_contradicts"]
            followup_state, followup = _followup(conn, finding_id, unresolved, now)
            version_no = int(latest["version_no"]) + 1 if latest else 1
            cur = conn.execute(
                """INSERT INTO finding_versions(finding_id,version_no,supersedes_id,support_digest,rule,statement,
                   unresolved,followup_state,followup,state,state_reason,state_set_by,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,'pending',NULL,'worker',?,?)""",
                (finding_id, version_no, int(latest["id"]) if latest else None, digest, RULE,
                 recipes.canonical_json(statement), recipes.canonical_json(unresolved), followup_state, followup, now, now),
            )
            inserted = int(cur.lastrowid)
        if crash_hook:
            crash_hook("before_knowledge_commit")
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    if crash_hook:
        crash_hook("after_knowledge_commit")
    return {"finding_id": finding_id, "version_id": inserted, "failures": failures,
            "counts": tuple(conn.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]
                            for table in ("findings", "finding_links", "finding_versions"))}


def synthesize(db_path: Union[str, Path], crash_hook: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    lock = StoreLock(db_path)
    if not lock.acquire():
        raise KnowledgeRefused("research store is busy")
    conn = None
    try:
        conn = db.connect(db_path)
        db.migrate(conn)
        return _synthesize_conn(conn, crash_hook)
    finally:
        if conn is not None:
            conn.close()
        lock.release()


def review(db_path: Union[str, Path], version_id: int, state: str, by: str, reason: str) -> None:
    if state not in VALID_STATES:
        raise KnowledgeRefused("state must be approved, rejected, or deferred")
    if not isinstance(by, str) or not by.startswith("human:") or not by[6:].strip():
        raise KnowledgeRefused("reviewer must use human:<name>")
    if not isinstance(reason, str) or not reason.strip():
        raise KnowledgeRefused("reason is required")
    lock = StoreLock(db_path)
    if not lock.acquire():
        raise KnowledgeRefused("research store is busy")
    conn = None
    try:
        conn = db.connect(db_path); db.migrate(conn); conn.execute("BEGIN")
        cur = conn.execute("UPDATE finding_versions SET state=?,state_reason=?,state_set_by=?,updated_at=? WHERE id=?",
                           (state, reason, by, _iso_now(), version_id))
        if cur.rowcount != 1:
            raise KnowledgeRefused("finding version does not exist")
        conn.execute("COMMIT")
    except BaseException:
        if conn is not None and conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        if conn is not None: conn.close()
        lock.release()


def render_knowledge(conn: sqlite3.Connection, now: datetime) -> List[str]:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='findings'").fetchone():
        return []
    findings = conn.execute("SELECT * FROM findings ORDER BY topic,claim_slug").fetchall()
    if not findings:
        return []
    out = ["## Retained knowledge", ""]
    for finding in findings:
        version = _latest_version(conn, int(finding["id"]))
        if version is None:
            continue
        statement = _parse(version["statement"], {})
        out += ["### What we know", "", statement.get("claim", "Stored finding unavailable."), "",
                "### Why we believe it", ""]
        for link in statement.get("links", []):
            detail = link.get("basis_detail", {})
            literals = [item.get("literal") for item in detail.get("stated", []) if isinstance(item, dict)]
            if detail.get("literal"):
                literals.append(detail["literal"])
            out.append("- %s — %s / %s%s" % (link.get("url"), link.get("relation"), link.get("basis"),
                                              (": " + "; ".join(literals)) if literals else ""))
        accounting = statement.get("independent_support", {})
        out += ["", "Independent supporting publishers: %s. Components: %s." % (
            accounting.get("independent_publisher_count", 0), accounting.get("components", [])), "",
            "### What remains uncertain", ""]
        unresolved = _parse(version["unresolved"], [])
        if unresolved:
            for item in unresolved:
                detail = item.get("basis_detail", {})
                out.append("- %s: %s" % (item.get("url"), detail.get("literal", "qualification recorded")))
        else:
            out.append("- No recorded qualification or contradiction.")
        view = current_followup(conn, version)
        recorded = view.get("recorded") if isinstance(view.get("recorded"), dict) else {}
        reasons = ": " + "; ".join(view["withdrawn_reasons"]) if view["withdrawn_reasons"] else ""
        out += ["", "### What to investigate next", "",
                "- Recorded proposal (historical, v%d, %s): %s → %s" % (
                    version["version_no"], version["created_at"], recorded.get("question", "unreadable"),
                    recorded.get("target_surface_url") or "none"),
                "- Current eligibility (computed %s): %s%s" % (
                    now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), view["status"], reasons),
                "- Actionable target: %s — not executed" % (view["actionable_target_url"] or "none"),
                "- History: version %d, state %s, set by %s%s" % (
                    version["version_no"], version["state"], version["state_set_by"],
                    (", supersedes %d" % version["supersedes_id"]) if version["supersedes_id"] else ""), ""]
    return out


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="research.knowledge")
    subs = parser.add_subparsers(dest="command", required=True)
    synth = subs.add_parser("synthesize"); synth.add_argument("--db", required=True)
    rev = subs.add_parser("review"); rev.add_argument("version_id", type=int)
    rev.add_argument("state", choices=list(VALID_STATES)); rev.add_argument("--by", required=True)
    rev.add_argument("--reason", required=True); rev.add_argument("--db", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "synthesize":
            print(json.dumps(synthesize(args.db), indent=2))
        else:
            review(args.db, args.version_id, args.state, args.by, args.reason)
            print("finding version %d -> %s by %s" % (args.version_id, args.state, args.by))
        return 0
    except (KnowledgeRefused, OSError, sqlite3.Error) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
