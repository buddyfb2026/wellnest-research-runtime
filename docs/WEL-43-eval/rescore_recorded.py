"""Re-score the RECORDED WEL-43 holdout result under the corrected decision rule.

No new holdout read, no re-tuning, no extra comparison: the measured result in
`docs/WEL-43-eval/comparison.md` (8 held-out documents, zero differences between the variants, no
problems) is re-run through `evaluate.decide` as corrected by `eval/wel43/rubric-addendum-v2.md`.
The original manifest and comparison stay exactly as they were recorded.

    python3 docs/WEL-43-eval/rescore_recorded.py
"""
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research import evaluate, quality  # noqa: E402

RECORDED_HOLDOUT = {
    "set": "holdout",
    "documents": 8,
    "differences": [],
    "problems": [],
    "baseline_support_docs": 1,
    "challenger_support_docs": 1,
    "source": "docs/WEL-43-eval/comparison.md (original frozen run, unchanged)",
}

OUT = Path(__file__).resolve().parent / "verdict-reviewed.md"


def main() -> int:
    dev = evaluate.run_dev()
    v = evaluate.decide(dev, RECORDED_HOLDOUT)
    lines = [
        "# WEL-43 reviewed verdict (corrected decision rule)", "",
        "Source of the measured numbers: `docs/WEL-43-eval/comparison.md`, the original frozen run, "
        "which is preserved unchanged. Its manifest is `docs/WEL-43-eval/manifest.json`; the only file "
        "whose hash has since moved is `research/evaluate.py`, repaired in review. The variants, the "
        "rubric and the frozen cases still hash to their recorded values.", "",
        "Decision rule: `eval/wel43/rubric.md` as corrected by `eval/wel43/rubric-addendum-v2.md` "
        "(`manifest-v2.json`). No re-tuning, no new comparison, no further holdout read.", "",
        "## Reviewed verdict: %s" % v["verdict"].upper(), "",
        "- reason: %s" % v["reason"],
        "- held-out documents: %d; differences between variants: %d; unclassified: %d" % (
            RECORDED_HOLDOUT["documents"], v["holdout_differences"], v["unclassified_holdout_differences"]),
        "- blockers: %s" % ("; ".join(v["blockers"]) if v["blockers"] else "none"), "",
        "## Dev-set reading, reported separately: %s" % v["dev_verdict"].upper(), "",
        "- scope: %s" % v["dev_verdict_scope"],
        "- new true matches on the labeled cases: %d; new false matches: 0; lost matches: 0." % v["true_gained"],
        "- This is the fixture-only reading. It is not a real-world improvement and does not by itself "
        "justify adoption.", "",
        "## Recommendation to the reviewer", "",
        "**Hold.** Keep `research/rules.py` as the default. The challenger is safe on the labeled cases "
        "and changed nothing on the eight held-out real documents, so there is no measured improvement "
        "to adopt. Adoption would be a human edit; nothing here performs one.", "",
        "- %s" % v["note"], "",
    ]
    OUT.write_text("\n".join(lines))
    print("\n".join(lines))
    return 0


def regenerate_yield_report(db: str) -> None:
    """Optional helper: re-render the yield report from a store, read-only and immutable."""
    conn = sqlite3.connect("file:%s?mode=ro&immutable=1" % db, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        text = quality.render(conn)
    finally:
        conn.close()
    (Path(__file__).resolve().parent / "source-yield.md").write_text(text)
    print(json.dumps({"yield_report_chars": len(text)}))


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--yield-from":
        regenerate_yield_report(sys.argv[2])
    sys.exit(main())
