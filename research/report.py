"""Plain Markdown report of sources, evidence, candidates, rejections and collection health."""
import json
import sqlite3
from datetime import datetime
from typing import List, Optional

from . import candidates as cands
from . import schedule as sch
from . import source_registry as registry


def _j(s: Optional[str]):
    try:
        return json.loads(s) if s else []
    except Exception:
        return []


def _jobj(s: Optional[str]):
    try:
        v = json.loads(s) if s else None
    except Exception:
        return None
    return v if isinstance(v, dict) else None


def _age(ts: Optional[str], now: datetime) -> str:
    if not ts:
        return "never"
    try:
        delta = now - sch.parse(ts)
    except Exception:
        return "unknown"
    secs = int(delta.total_seconds())
    if secs < 0:
        return "in %s" % _span(-secs)
    return "%s ago" % _span(secs)


def _span(secs: int) -> str:
    if secs < 3600:
        return "%dm" % (secs // 60)
    if secs < 86400:
        return "%dh" % (secs // 3600)
    return "%dd" % (secs // 86400)


def health_state(row: sqlite3.Row, now: datetime) -> str:
    """One word a reader can act on. Never 'ok' for a failed or blocked refresh."""
    if row["stalled"]:
        return "stalled"
    if row["last_outcome"] is None:
        return "never_attempted"
    due = sch.parse(row["next_check_at"]) <= now
    if row["consecutive_failures"] > 0:   # a manual reset clears the counter but keeps the history
        if row["last_outcome"] == "blocked":
            return "blocked"
        if row["last_outcome"] == "error":
            return "failed"
    return "due" if due else "not_due"


def render_health(conn: sqlite3.Connection, now: datetime) -> List[str]:
    out = ["## Collection health (as of %s)" % sch.iso(now), "",
           "State: `not_due` last refresh succeeded and the next check is in the future; `due` will be tried by the "
           "next cycle; `failed`/`blocked` last attempt did not succeed and the source is in backoff (prior evidence "
           "is kept with its original age); `stalled` blocked repeatedly, needs `reset-source`; "
           "`never_attempted` registered, not yet tried.", "",
           "| source | state | last attempt | outcome | reason | last success | evidence age | attempts | consecutive failures | next check |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    rows = conn.execute("SELECT * FROM source_state ORDER BY stalled DESC, last_outcome, url").fetchall()
    if not rows:
        out += ["_No scheduled sources yet._", ""]
        return out
    for r in rows:
        ev_age = "-"
        if r["last_evidence_id"]:
            e = conn.execute("SELECT fetched_at, published_at FROM evidence WHERE id=?", (r["last_evidence_id"],)).fetchone()
            if e:
                ev_age = "fetched %s; published %s" % (_age(e["fetched_at"], now), e["published_at"] or "unknown")
        out.append("| %s | %s | %s | %s | %s | %s | %s | %d | %d | %s (%s) |" % (
            r["url"], health_state(r, now), r["last_attempt_at"] or "-", r["last_outcome"] or "-",
            (r["last_reason"] or "-").replace("|", "/")[:80], _age(r["last_success_at"], now), ev_age,
            r["attempts"], r["consecutive_failures"], r["next_check_at"], _age(r["next_check_at"], now)))
    out.append("")
    stalled = [r["url"] for r in rows if r["stalled"]]
    failing = [r["url"] for r in rows if not r["stalled"] and r["last_outcome"] in ("error", "blocked")]
    out += ["- **Stalled (manual reset required)**: %s" % (", ".join(stalled) or "none"),
            "- **Failing / blocked (in backoff)**: %s" % (", ".join(failing) or "none")]

    day = sch.day_of(now)
    used = conn.execute("SELECT status, COUNT(*) AS n FROM inference_calls WHERE day=? GROUP BY status", (day,)).fetchall()
    waiting = conn.execute("SELECT COUNT(*) FROM candidates WHERE state_set_by='worker' AND state_reason LIKE ?",
                           (cands.BUDGET_PLACEHOLDER_PREFIX + "%",)).fetchone()[0]
    out += ["- **Inference budget %s (UTC)**: %s" % (day, ", ".join("%s=%d" % (u["status"] or "legacy", u["n"]) for u in used) or "no calls"),
            "- **Budget stopped**: %d candidate(s) waiting for inference budget (redone when budget exists)" % waiting]
    hints = conn.execute("SELECT url, discovered_at, discovery_route, access_assessment, fetch_permitted FROM source_hints "
                         "WHERE discovery_route IS NOT NULL ORDER BY discovered_at, url").fetchall()
    if hints:
        out += ["", "### Discovered hints (route → assessment → collection)", "",
                "| url | discovered | route | assessment | collect? |", "|---|---|---|---|---|"]
        for h in hints:
            a = _jobj(h["access_assessment"])
            out.append("| %s | %s | %s | %s | %s |" % (
                h["url"], h["discovered_at"], h["discovery_route"],
                ("%s: %s" % (a["status"], a.get("reason", ""))) if a else "not yet assessed",
                "yes" if h["fetch_permitted"] else "no"))
    out.append("")
    return out


def render(conn: sqlite3.Connection, run_id: Optional[str] = None, now: Optional[datetime] = None) -> str:
    now = now or sch.utc_now()
    out = ["# WellNest research report", ""]
    runs = conn.execute("SELECT * FROM runs ORDER BY started_at DESC LIMIT 5").fetchall()
    if runs:
        out += ["## Recent runs", "", "| run | started | status | summary |", "|---|---|---|---|"]
        for r in runs:
            out.append("| %s | %s | %s | %s |" % (r["run_id"], r["started_at"], r["status"], (r["summary"] or "").replace("|", "/")))
        out.append("")

    out += registry.render_health(conn)
    if runs:
        summary = _jobj(runs[0]["summary"]) or {}
        if summary.get("roster"):
            out += ["Roster: %s" % summary["roster"]["reason"], ""]
        if summary.get("source_decisions"):
            out += ["### Latest cycle decisions", "", "| source | disposition | reason |", "|---|---|---|"]
            for d in summary["source_decisions"]:
                out.append("| %s | %s | %s |" % (d["url"], d["decision"], d["reason"].replace("|", "/")))
            out.append("")

    out += ["## Sources (hints are not evidence)", "",
            "| url | type | access basis | fetch? | last attempt | outcome | reason |", "|---|---|---|---|---|---|---|"]
    for h in conn.execute("SELECT * FROM source_hints ORDER BY source_type, url").fetchall():
        a = conn.execute("SELECT * FROM fetch_attempts WHERE url=? ORDER BY id DESC LIMIT 1", (h["url"],)).fetchone()
        out.append("| %s | %s | %s | %s | %s | %s | %s |" % (
            h["url"], h["source_type"], h["access_basis"], "yes" if h["fetch_permitted"] else "no",
            a["attempted_at"] if a else "-", a["outcome"] if a else "-", (a["reason"] or "") if a else ""))
    out.append("")

    out += render_health(conn, now)

    out += ["## Evidence (append-only, versioned)", "",
            "| id | v | kind | url | fetched | published (basis) | modified | hash | title | flags |",
            "|---|---|---|---|---|---|---|---|---|---|"]
    for e in conn.execute("SELECT * FROM evidence ORDER BY url, version_no").fetchall():
        out.append("| %d | %d%s | %s | %s | %s | %s (%s) | %s | %s | %s | %s |" % (
            e["id"], e["version_no"], (" supersedes %d" % e["supersedes_id"]) if e["supersedes_id"] else "",
            e["content_kind"], e["url"], e["fetched_at"], e["published_at"] or "unknown", e["published_at_basis"],
            e["modified_at"] or "-", e["content_hash"][:12], (e["title"] or "").replace("|", "/")[:60],
            ", ".join(_j(e["injection_flags"])) or "-"))
    out.append("")

    out += ["## Candidates", "",
            "Only candidates from the closed action registry (`research/rules.py`) can be pending. Free-text "
            "model proposals are deferred or rejected with a reason; their prose is kept for audit and not shown.", ""]
    cands = conn.execute("SELECT c.*, e.url AS url, e.content_kind AS kind FROM candidates c JOIN evidence e ON e.id=c.evidence_id ORDER BY c.state, c.id").fetchall()
    legacy = []
    shown = 0
    for c in cands:
        val = _jobj(c["validation"])
        if val is None:
            legacy.append(c)
            continue
        shown += 1
        is_rule = val.get("kind") == "rule"
        out += ["### Candidate %d — %s" % (c["id"], c["state"].upper()),
                "- **Source**: %s (%s evidence #%d)" % (c["url"], c["kind"], c["evidence_id"]),
                "- **Attribution**: %s" % (c["source_attribution"] or "unknown"),
                "- **State set by**: %s — %s" % (c["state_set_by"], c["state_reason"] or "-")]
        if is_rule:
            out += ["- **Rule**: %s v%s (fixed action text; model inference: none)" % (val.get("rule_id"), val.get("rule_version")),
                    "- **Proposed prepared action**: %s" % (c["proposed_action"] or "-"),
                    "- **Support quote (whole sentence, verbatim)**: \"%s\"" % (val.get("support_quote") or "-"),
                    "- **Household problem (whole sentence, verbatim)**: %s" % (
                        ("\"%s\"" % val["problem_quote"]) if val.get("problem_quote") else "not found in this evidence")]
        else:
            out += ["- **Proposed prepared action**: not shown — free-text model proposal, not a registered action "
                    "(raw model output retained for audit)",
                    "- **Household problem**: not shown (free-text model proposal)"]
        out += ["- **Observations (verbatim, grounded)**:"] + (["  - \"%s\"" % q for q in _j(c["observations"])] or ["  - none"])
        out += ["- **Inferences (not stated by source)**:"] + (["  - %s" % q for q in _j(c["inferences"])] or ["  - none"])
        unsupported = _j(c["unsupported_claims"])
        if unsupported:
            out += ["- **Dropped as unsupported (model text, not evidence)**:"] + ["  - %s" % q for q in unsupported]
        out += ["- **Relevance conditions**: %s" % ("; ".join(_j(c["relevance_conditions"])) or "-"),
                "- **Lead time / expiry**: %s%s / %s%s" % (
                    ("%d days" % c["lead_time_days"]) if c["lead_time_days"] is not None else "none (unsupported)",
                    (" (basis: \"%s\")" % c["lead_time_basis"]) if c["lead_time_basis"] else "",
                    c["expires_at"] or "none set",
                    (" (basis: \"%s\")" % c["expiry_basis"]) if c["expiry_basis"] else ""),
                "- **Products named**: %s" % (", ".join("%s%s" % (p["name"], "" if p.get("grounded") else " [NOT IN TEXT]") for p in _j(c["product_mentions"])) or "none"),
                "- **Shopping destination**: %s (separate decision; creator attribution preserved)" % (c["proposed_destination"] or "none proposed"),
                "- **Stock/price claims**: %s" % c["stock_price_claims"],
                "- **Publishable**: %s" % ("yes" if c["publishable"] else "no"),
                "- **Generator**: %s" % c["generator"], ""]
    if not shown:
        out += ["_No candidates._", ""]
    if legacy:
        out += ["## Legacy candidates (created before schema v3; prose never validated, not shown)", "",
                "| id | source | evidence | state | set by | reason | generator |", "|---|---|---|---|---|---|---|"]
        for c in legacy:
            out.append("| %d | %s | #%d | %s | %s | %s | %s |" % (
                c["id"], c["url"], c["evidence_id"], c["state"], c["state_set_by"],
                (c["state_reason"] or "-").replace("|", "/"), c["generator"]))
        out.append("")

    out += ["## Inference usage", "", "| run | provider | model | evidence | ok | error |", "|---|---|---|---|---|---|"]
    for i in conn.execute("SELECT * FROM inference_calls ORDER BY id").fetchall():
        out.append("| %s | %s | %s | %s | %s | %s |" % (i["run_id"], i["provider"], i["model"] or "-", i["evidence_id"], i["ok"], (i["error"] or "-").replace("|", "/")[:120]))
    out.append("")
    return "\n".join(out)
