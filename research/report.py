"""Plain Markdown report of sources, evidence, candidates and rejections."""
import json
import sqlite3
from typing import Optional


def _j(s: Optional[str]):
    try:
        return json.loads(s) if s else []
    except Exception:
        return []


def render(conn: sqlite3.Connection, run_id: Optional[str] = None) -> str:
    out = ["# WellNest research report", ""]
    runs = conn.execute("SELECT * FROM runs ORDER BY started_at DESC LIMIT 5").fetchall()
    if runs:
        out += ["## Recent runs", "", "| run | started | status | summary |", "|---|---|---|---|"]
        for r in runs:
            out.append("| %s | %s | %s | %s |" % (r["run_id"], r["started_at"], r["status"], (r["summary"] or "").replace("|", "/")))
        out.append("")

    out += ["## Sources (hints are not evidence)", "",
            "| url | type | access basis | fetch? | last attempt | outcome | reason |", "|---|---|---|---|---|---|---|"]
    for h in conn.execute("SELECT * FROM source_hints ORDER BY source_type, url").fetchall():
        a = conn.execute("SELECT * FROM fetch_attempts WHERE url=? ORDER BY id DESC LIMIT 1", (h["url"],)).fetchone()
        out.append("| %s | %s | %s | %s | %s | %s | %s |" % (
            h["url"], h["source_type"], h["access_basis"], "yes" if h["fetch_permitted"] else "no",
            a["attempted_at"] if a else "-", a["outcome"] if a else "-", (a["reason"] or "") if a else ""))
    out.append("")

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

    out += ["## Candidates", ""]
    cands = conn.execute("SELECT c.*, e.url AS url, e.content_kind AS kind FROM candidates c JOIN evidence e ON e.id=c.evidence_id ORDER BY c.state, c.id").fetchall()
    if not cands:
        out.append("_No candidates._")
    for c in cands:
        out += ["### Candidate %d — %s" % (c["id"], c["state"].upper()),
                "- **Source**: %s (%s evidence #%d)" % (c["url"], c["kind"], c["evidence_id"]),
                "- **Attribution**: %s" % (c["source_attribution"] or "unknown"),
                "- **State set by**: %s — %s" % (c["state_set_by"], c["state_reason"] or "-"),
                "- **Household problem**: %s" % (c["household_problem"] or "-"),
                "- **Proposed prepared action**: %s" % (c["proposed_action"] or "-"),
                "- **Observations (verbatim, grounded)**:"] + (["  - \"%s\"" % q for q in _j(c["observations"])] or ["  - none"])
        out += ["- **Inferences (not stated by source)**:"] + (["  - %s" % q for q in _j(c["inferences"])] or ["  - none"])
        unsupported = _j(c["unsupported_claims"])
        if unsupported:
            out += ["- **Dropped as unsupported**:"] + ["  - %s" % q for q in unsupported]
        out += ["- **Relevance conditions**: %s" % ("; ".join(_j(c["relevance_conditions"])) or "-"),
                "- **Lead time / expiry**: %s / %s%s" % (
                    c["lead_time_days"] if c["lead_time_days"] is not None else "unsupported",
                    c["expires_at"] or "none set",
                    (" (basis: \"%s\")" % c["expiry_basis"]) if c["expiry_basis"] else ""),
                "- **Products named**: %s" % (", ".join("%s%s" % (p["name"], "" if p.get("grounded") else " [NOT IN TEXT]") for p in _j(c["product_mentions"])) or "none"),
                "- **Shopping destination**: %s (separate decision; creator attribution preserved)" % (c["proposed_destination"] or "none proposed"),
                "- **Stock/price claims**: %s" % c["stock_price_claims"],
                "- **Publishable**: %s" % ("yes" if c["publishable"] else "no"),
                "- **Generator**: %s" % c["generator"], ""]

    out += ["## Inference usage", "", "| run | provider | model | evidence | ok | error |", "|---|---|---|---|---|---|"]
    for i in conn.execute("SELECT * FROM inference_calls ORDER BY id").fetchall():
        out.append("| %s | %s | %s | %s | %s | %s |" % (i["run_id"], i["provider"], i["model"] or "-", i["evidence_id"], i["ok"], (i["error"] or "-").replace("|", "/")[:120]))
    out.append("")
    return "\n".join(out)
