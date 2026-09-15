"""Frozen baseline/challenger comparison for one adjustment (WEL-43 AC3). Offline, zero calls.

    python3 -m research.evaluate freeze  --out work/wel43_manifest.json
    python3 -m research.evaluate dev     --manifest work/wel43_manifest.json
    python3 -m research.evaluate holdout --manifest work/wel43_manifest.json --db PATH [--md OUT]

`freeze` records the sha256 of both variants' source, the rubric and the labeled development cases.
`dev` scores the labeled cases. `holdout` scores unseen documents (stored `evidence_text`) and must
be run only after the manifest exists; it re-checks the manifest hashes and refuses to run if the
challenger source changed, which is what stops a "tune until it wins" loop.

Neither command opens a transaction, writes to the research store, makes a network request or calls
a model. The holdout store is opened read-only and immutable.
"""
import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import rules as baseline
from . import sentence_integrity as challenger
from .config import REPO_ROOT
from .extract import scan_for_instructions

EVAL_DIR = REPO_ROOT / "eval" / "wel43"
DEV_CASES = EVAL_DIR / "dev_cases.json"
RUBRIC = EVAL_DIR / "rubric.md"
RUBRIC_ADDENDUM = EVAL_DIR / "rubric-addendum-v2.md"
FROZEN_FILES = [
    REPO_ROOT / "research" / "rules.py",
    REPO_ROOT / "research" / "sentence_integrity.py",
    REPO_ROOT / "research" / "evaluate.py",
    RUBRIC,
    RUBRIC_ADDENDUM,
    DEV_CASES,
]

# A holdout difference counts as examined only when a human recorded one of these on it.
HOLDOUT_REVIEW_LABELS = ("true_gain", "false_gain", "lost", "neutral")

VARIANTS = {
    "baseline": {"version": "rules_incumbent", "match": baseline.match_rules},
    "challenger": {"version": challenger.VERSION, "match": challenger.match_rules},
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def manifest() -> Dict[str, Any]:
    return {
        "adjustment": "sentence integrity over already-extracted text",
        "baseline_version": VARIANTS["baseline"]["version"],
        "challenger_version": VARIANTS["challenger"]["version"],
        "files": {str(p.relative_to(REPO_ROOT)): sha256_file(p) for p in FROZEN_FILES},
        "dev_case_count": len(load_dev_cases()),
        "rubric": str(RUBRIC.relative_to(REPO_ROOT)),
        "budget": {"model_calls": 0, "network_requests": 0},
    }


def check_manifest(path: Path) -> List[str]:
    """Files that changed since the manifest was frozen. Empty list means the comparison is valid."""
    m = json.loads(Path(path).read_text())
    drift = []
    for rel, digest in m["files"].items():
        p = REPO_ROOT / rel
        if not p.exists() or sha256_file(p) != digest:
            drift.append(rel)
    return drift


def load_dev_cases() -> List[Dict[str, Any]]:
    return json.loads(DEV_CASES.read_text())["cases"]


def score_text(text: str, variant: str) -> Dict[str, Any]:
    """One variant's result on one text. Run twice to expose any non-determinism."""
    fn = VARIANTS[variant]["match"]
    first = [(m.rule.rule_id, m.support_quote, m.problem_quote) for m in fn(text)]
    second = [(m.rule.rule_id, m.support_quote, m.problem_quote) for m in fn(text)]
    return {
        "variant": variant,
        "version": VARIANTS[variant]["version"],
        "matches": len(first),
        "rule_ids": sorted(r for r, _s, _p in first),
        "support": bool(first),
        "problem": any(p is not None for _r, _s, p in first),
        "support_quotes": [s for _r, s, _p in first],
        "deterministic": first == second,
        "injection_flags": sorted(scan_for_instructions(text)),
    }


def run_dev() -> Dict[str, Any]:
    counts = {k: 0 for k in ("true_support_gained", "false_support_gained", "support_lost",
                             "true_problem_gained", "false_problem_gained", "problem_lost")}
    rows, problems = [], []
    for case in load_dev_cases():
        b = score_text(case["text"], "baseline")
        c = score_text(case["text"], "challenger")
        truth_s, truth_p = bool(case["support"]), bool(case["problem"])
        if c["support"] and not b["support"]:
            counts["true_support_gained" if truth_s else "false_support_gained"] += 1
        if b["support"] and not c["support"]:
            counts["support_lost"] += 1
        if c["problem"] and not b["problem"]:
            counts["true_problem_gained" if truth_p else "false_problem_gained"] += 1
        if b["problem"] and not c["problem"]:
            counts["problem_lost"] += 1
        if b["injection_flags"] != c["injection_flags"]:
            problems.append("%s: injection flags differ" % case["name"])
        if not b["deterministic"] or not c["deterministic"]:
            problems.append("%s: non-deterministic result" % case["name"])
        rows.append({"case": case["name"], "truth_support": truth_s, "truth_problem": truth_p,
                     "baseline_support": b["support"], "challenger_support": c["support"],
                     "baseline_problem": b["problem"], "challenger_problem": c["problem"],
                     "baseline_matches": b["matches"], "challenger_matches": c["matches"],
                     "injection_flags": len(b["injection_flags"]), "why": case["why"]})
    # Baseline/challenger agreement with the ground truth, reported as plain counts.
    for row in rows:
        row["baseline_correct"] = row["baseline_support"] == row["truth_support"]
        row["challenger_correct"] = row["challenger_support"] == row["truth_support"]
    return {"set": "dev", "cases": len(rows), "rows": rows, "counts": counts, "problems": problems,
            "baseline_correct": sum(1 for r in rows if r["baseline_correct"]),
            "challenger_correct": sum(1 for r in rows if r["challenger_correct"])}


def read_holdout(db_path: Path) -> List[Dict[str, Any]]:
    """Unseen documents: stored extracted text, opened read-only and immutable. Never written."""
    uri = "file:%s?mode=ro&immutable=1" % Path(db_path).resolve()
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT e.id AS id, e.url AS url, e.content_hash AS content_hash, t.text AS text "
            "FROM evidence e JOIN evidence_text t ON t.evidence_id = e.id ORDER BY e.id").fetchall()
        return [{"id": int(r["id"]), "url": r["url"], "content_hash": r["content_hash"], "text": r["text"]}
                for r in rows]
    finally:
        conn.close()


def run_holdout(db_path: Path) -> Dict[str, Any]:
    rows, problems, diffs = [], [], []
    for doc in read_holdout(db_path):
        b = score_text(doc["text"], "baseline")
        c = score_text(doc["text"], "challenger")
        if b["injection_flags"] != c["injection_flags"]:
            problems.append("evidence %d: injection flags differ" % doc["id"])
        if not b["deterministic"] or not c["deterministic"]:
            problems.append("evidence %d: non-deterministic result" % doc["id"])
        if (b["support"], b["problem"], b["support_quotes"]) != (c["support"], c["problem"], c["support_quotes"]):
            diffs.append({"evidence_id": doc["id"], "url": doc["url"],
                          "baseline": b["support_quotes"], "challenger": c["support_quotes"]})
        rows.append({"evidence_id": doc["id"], "url": doc["url"], "chars": len(doc["text"]),
                     "baseline_matches": b["matches"], "challenger_matches": c["matches"],
                     "baseline_support": b["support"], "challenger_support": c["support"],
                     "baseline_problem": b["problem"], "challenger_problem": c["problem"],
                     "injection_flags": len(b["injection_flags"])})
    return {"set": "holdout", "documents": len(rows), "rows": rows, "differences": diffs, "problems": problems,
            "baseline_support_docs": sum(1 for r in rows if r["baseline_support"]),
            "challenger_support_docs": sum(1 for r in rows if r["challenger_support"])}


def decide(dev: Dict[str, Any], holdout: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The decision rule of eval/wel43/rubric.md as corrected by rubric-addendum-v2.md.

    `dev_verdict` is the fixture-only reading and is never presented as a real improvement. `verdict`
    is the reviewed reading: it needs held-out evidence, and every held-out difference must carry a
    human `review` label from HOLDOUT_REVIEW_LABELS before it can support adoption.
    """
    c = dev["counts"]
    blockers = []
    if c["false_support_gained"] or c["false_problem_gained"]:
        blockers.append("challenger produced %d new false support/problem match(es) on the dev set"
                        % (c["false_support_gained"] + c["false_problem_gained"]))
    if c["support_lost"] or c["problem_lost"]:
        blockers.append("challenger lost %d true match(es) on the dev set" % (c["support_lost"] + c["problem_lost"]))
    blockers += list(dev["problems"]) + list(holdout.get("problems", []) if holdout else [])
    gained = c["true_support_gained"] + c["true_problem_gained"]

    dev_verdict = "do-not-adopt" if blockers else ("adopt-with-review" if gained > 0 else "inconclusive")
    result = {"dev_verdict": dev_verdict, "dev_verdict_scope": "labeled fixtures authored while "
              "designing the adjustment; not evidence of a real-world improvement",
              "true_gained": gained, "blockers": blockers,
              "note": "A verdict is a recommendation to a human reviewer. The default stays "
                      "research/rules.py in every case; nothing is adopted or activated automatically."}

    if holdout is None:
        result.update({"verdict": dev_verdict, "holdout_differences": None,
                       "unclassified_holdout_differences": None,
                       "reason": "no held-out evidence was supplied; this is the fixture-only reading"})
        return result

    diffs = list(holdout.get("differences", []))
    unclassified = [d for d in diffs if d.get("review") not in HOLDOUT_REVIEW_LABELS]
    reviewed = [d for d in diffs if d.get("review") in HOLDOUT_REVIEW_LABELS]
    bad = [d for d in reviewed if d["review"] in ("false_gain", "lost")]
    true_gains = [d for d in reviewed if d["review"] == "true_gain"]

    if bad:
        blockers.append("%d held-out difference(s) reviewed as false_gain/lost" % len(bad))
    if blockers:
        verdict, reason = "do-not-adopt", "a blocker forbids adoption regardless of the holdout"
    elif unclassified:
        verdict = "inconclusive"
        reason = ("%d held-out difference(s) carry no human classification; a reviewer must label each "
                  "as true_gain/false_gain/lost/neutral before adoption can be considered" % len(unclassified))
    elif not diffs:
        verdict = "inconclusive"
        reason = ("the variants did not differ on any held-out document, so no real-world effect was "
                  "measured; the dev-set gain is fixture evidence only")
    elif true_gains:
        verdict, reason = "adopt-with-review", "%d held-out difference(s) reviewed as true_gain, none adverse" % len(true_gains)
    else:
        verdict = "inconclusive"
        reason = "held-out differences were all reviewed as neutral; no improvement was measured"

    result.update({"verdict": verdict, "reason": reason, "holdout_differences": len(diffs),
                   "unclassified_holdout_differences": len(unclassified)})
    return result


def render_markdown(man: Dict[str, Any], dev: Dict[str, Any], holdout: Optional[Dict[str, Any]],
                    verdict: Dict[str, Any]) -> str:
    out = ["# WEL-43 baseline vs challenger — one adjustment", "",
           "Adjustment: **%s**. Baseline `%s` (unchanged default) vs challenger `%s`." % (
               man["adjustment"], man["baseline_version"], man["challenger_version"]), "",
           "Budget consumed: **%d model calls, %d network requests**." % (
               man["budget"]["model_calls"], man["budget"]["network_requests"]), "",
           "## Frozen manifest", "", "| file | sha256 |", "|---|---|"]
    out += ["| %s | `%s` |" % (f, h) for f, h in sorted(man["files"].items())]
    out += ["", "## Development cases (labeled, used to design the adjustment)", "",
            "| case | truth: sentence present | baseline | challenger | note |", "|---|---|---|---|---|"]
    for r in dev["rows"]:
        out.append("| %s | %s | %s | %s | %s |" % (
            r["case"], "yes" if r["truth_support"] else "no",
            "match" if r["baseline_support"] else "no match",
            "match" if r["challenger_support"] else "no match", r["why"]))
    out += ["", "Agreement with ground truth: baseline %d/%d, challenger %d/%d. New true matches %d, "
            "new false matches %d, lost matches %d." % (
                dev["baseline_correct"], dev["cases"], dev["challenger_correct"], dev["cases"],
                dev["counts"]["true_support_gained"] + dev["counts"]["true_problem_gained"],
                dev["counts"]["false_support_gained"] + dev["counts"]["false_problem_gained"],
                dev["counts"]["support_lost"] + dev["counts"]["problem_lost"]), ""]
    if holdout:
        out += ["## Holdout (unseen documents, read after the manifest was frozen)", "",
                "Corpus: %d stored documents of already-extracted text. Claims are limited to sentence "
                "processing; HTML extraction is NOT TESTED here." % holdout["documents"], "",
                "| evidence | url | chars | baseline match | challenger match |", "|---|---|---|---|---|"]
        for r in holdout["rows"]:
            out.append("| %d | %s | %d | %s | %s |" % (
                r["evidence_id"], r["url"], r["chars"],
                "yes" if r["baseline_support"] else "no", "yes" if r["challenger_support"] else "no"))
        out += ["", "Documents with a registry match: baseline %d, challenger %d. Documents where the "
                "two variants differ: %d." % (holdout["baseline_support_docs"],
                                              holdout["challenger_support_docs"], len(holdout["differences"])), ""]
        for diff in holdout["differences"]:
            out.append("- evidence %d (%s): baseline %s, challenger %s" % (
                diff["evidence_id"], diff["url"], diff["baseline"] or "none", diff["challenger"] or "none"))
        out.append("")
    out += ["## Verdict: %s" % verdict["verdict"].upper(), "",
            "- reason: %s" % verdict.get("reason", "-"),
            "- dev-set (fixture-only) reading: **%s** — %s" % (
                verdict["dev_verdict"], verdict["dev_verdict_scope"]),
            "- held-out differences: %s (unclassified: %s)" % (
                verdict.get("holdout_differences"), verdict.get("unclassified_holdout_differences")),
            "- blockers: %s" % ("; ".join(verdict["blockers"]) if verdict["blockers"] else "none"),
            "- %s" % verdict["note"], ""]
    return "\n".join(out)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="research.evaluate")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("freeze"); f.add_argument("--out", required=True)
    d = sub.add_parser("dev"); d.add_argument("--manifest")
    h = sub.add_parser("holdout"); h.add_argument("--manifest", required=True); h.add_argument("--db", required=True)
    h.add_argument("--md")
    a = ap.parse_args(argv)

    if a.cmd == "freeze":
        m = manifest()
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(m, indent=2, sort_keys=True) + "\n")
        print(json.dumps(m, indent=2, sort_keys=True))
        return 0

    if a.manifest:
        drift = check_manifest(Path(a.manifest))
        if drift:
            print("manifest drift, comparison refused (re-freeze and re-run the holdout): %s" % ", ".join(drift),
                  file=sys.stderr)
            return 2
    dev = run_dev()
    if a.cmd == "dev":
        print(json.dumps({"dev": dev, "verdict": decide(dev)}, indent=2))
        return 0
    holdout = run_holdout(Path(a.db))
    verdict = decide(dev, holdout)
    man = json.loads(Path(a.manifest).read_text())
    text = render_markdown(man, dev, holdout, verdict)
    if a.md:
        Path(a.md).parent.mkdir(parents=True, exist_ok=True)
        Path(a.md).write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
