"""Build the WEL-42 approved meal-research snapshot the app bundles.

Reads a research database, runs the deterministic rule registry over its evidence, saves any new
rule candidates, and writes the versioned export produced by research/meal_export.py.

The source database is opened read-only and duplicated into a separate WORKING COPY via sqlite3's
online backup API; all writes land on that copy. The source is never modified. Before anything is
written or removed, the source, working copy and output paths are checked for being the same file —
directly, via symlink, or via hard link — and the run is refused if any two coincide.

It never sets a review state: candidates are saved by the worker as 'pending' and only a named
human can approve them, so a freshly built snapshot contains zero details until that happens.

Usage:
  python3 scripts/wel42_build_snapshot.py <source.sqlite> <out-snapshot.json> [--work <path>]

The working copy is where any approval must be applied — see the approval packet.
"""
import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research.candidates import build_rule_candidate, human_review, save_candidate  # noqa: E402
from research.meal_export import MEAL_APPLICABILITY, export_meal_details  # noqa: E402
from research.rules import RULES, match_rules  # noqa: E402


PREVIEW_REVIEWER = "PREVIEW-NOT-A-REAL-APPROVAL"


class UnsafePaths(ValueError):
    """Raised before anything is written when two of the paths could be the same file."""


def _aliases(a: Path, b: Path) -> bool:
    """True when a and b are, or would be, the same file — including via symlink or hard link."""
    try:
        if a.exists() and b.exists() and os.path.samefile(a, b):
            return True
    except OSError:
        pass
    # Covers the not-yet-created case, where samefile cannot help.
    return a.resolve() == b.resolve()


def check_paths(source: Path, out: Path, work: Path) -> None:
    """Every destructive precondition, checked before a single byte is written or unlinked."""
    if not source.exists():
        raise UnsafePaths("source database does not exist: %s" % source)
    for label, other in (("working copy", work), ("output snapshot", out)):
        if _aliases(source, other):
            raise UnsafePaths(
                "refusing to run: the %s (%s) is the same file as the source database (%s). "
                "The source must never be overwritten." % (label, other, source))
    if _aliases(work, out):
        raise UnsafePaths("refusing to run: working copy and output snapshot are the same file")


def build(source: Path, out: Path, work: Path, preview_approve=()) -> dict:
    # Nothing below this line may run until the paths are proven distinct.
    check_paths(source, out, work)

    # sqlite3's online backup, not a file copy: it reads through the connection, so content
    # committed to a -wal sidecar is included. Copying the .sqlite file alone would silently lose it.
    src = sqlite3.connect("file:%s?mode=ro" % source, uri=True)
    try:
        if work.exists():
            work.unlink()
        work.parent.mkdir(parents=True, exist_ok=True)
        dst = sqlite3.connect(work)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()

    conn = sqlite3.connect(work)
    conn.row_factory = sqlite3.Row

    # Only rules that have a registered meal applicability are worth materialising here.
    meal_rules = tuple(r for r in RULES if r.rule_id in MEAL_APPLICABILITY)

    saved = []
    for ev in conn.execute("SELECT * FROM evidence ORDER BY id"):
        row = conn.execute("SELECT text FROM evidence_text WHERE evidence_id=?", (ev["id"],)).fetchone()
        if row is None:
            continue
        for match in match_rules(row["text"], meal_rules):
            cand = build_rule_candidate(ev, match)
            cid = save_candidate(conn, cand)
            if cid is not None:
                saved.append((cid, ev["id"], match.rule.rule_id, cand["state"]))
    conn.commit()

    if preview_approve:
        # PREVIEW ONLY, on the throwaway working copy. This shows what the export WOULD produce once
        # a real human approves; the reviewer name is deliberately not a person's name so a preview
        # artifact can never be mistaken for a real approval. The source database is untouched.
        for cid in preview_approve:
            human_review(conn, cid, "approved", PREVIEW_REVIEWER,
                         "PREVIEW ONLY: not a real human approval")
            conn.execute("UPDATE candidates SET publishable=1 WHERE id=?", (cid,))
        conn.commit()

    snapshot = export_meal_details(conn, generated_at=None)
    if preview_approve:
        snapshot = {
            "_preview_warning": (
                "PREVIEW ONLY — NOT APPROVED RESEARCH. Approval was simulated on a throwaway copy to "
                "show what this export produces once a named human approves candidate(s) %s. The "
                "source text, attribution, hash and checked time ARE real. Never bundle this file in "
                "the app." % ", ".join(str(c) for c in preview_approve)
            ),
            **snapshot,
        }
    conn.close()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snapshot, indent=2, sort_keys=False) + "\n")
    return {"saved": saved, "snapshot": snapshot, "work": work}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("source", type=Path)
    p.add_argument("out", type=Path)
    p.add_argument("--work", type=Path, default=Path("/tmp/wel42-snapshot-work.sqlite"))
    p.add_argument("--preview-approve", type=int, nargs="*", default=[],
                   help="PREVIEW ONLY: simulate approval of these candidate ids on the working copy")
    a = p.parse_args()

    try:
        result = build(a.source, a.out, a.work, tuple(a.preview_approve))
    except UnsafePaths as e:
        print("ABORTED, nothing written: %s" % e, file=sys.stderr)
        return 2
    print("source (unmodified): %s" % a.source)
    print("working copy (all writes land here): %s" % result["work"])
    for cid, eid, rule_id, state in result["saved"]:
        print("saved candidate id=%s evidence=%s rule=%s state=%s" % (cid, eid, rule_id, state))
    if not result["saved"]:
        print("no new rule candidates (already present or no support sentence matched)")
    snap = result["snapshot"]
    print("snapshot: %d detail(s), %d omitted -> %s" % (len(snap["details"]), len(snap["omitted"]), a.out))
    for o in snap["omitted"]:
        print("  omitted candidate %s: %s" % (o["candidate_id"], "; ".join(o["reasons"])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
