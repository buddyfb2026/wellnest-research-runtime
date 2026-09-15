# WEL-43 reviewed verdict (corrected decision rule)

Source of the measured numbers: `docs/WEL-43-eval/comparison.md`, the original frozen run, which is preserved unchanged. Its manifest is `docs/WEL-43-eval/manifest.json`; the only file whose hash has since moved is `research/evaluate.py`, repaired in review. The variants, the rubric and the frozen cases still hash to their recorded values.

Decision rule: `eval/wel43/rubric.md` as corrected by `eval/wel43/rubric-addendum-v2.md` (`manifest-v2.json`). No re-tuning, no new comparison, no further holdout read.

## Reviewed verdict: INCONCLUSIVE

- reason: the variants did not differ on any held-out document, so no real-world effect was measured; the dev-set gain is fixture evidence only
- held-out documents: 8; differences between variants: 0; unclassified: 0
- blockers: none

## Dev-set reading, reported separately: ADOPT-WITH-REVIEW

- scope: labeled fixtures authored while designing the adjustment; not evidence of a real-world improvement
- new true matches on the labeled cases: 4; new false matches: 0; lost matches: 0.
- This is the fixture-only reading. It is not a real-world improvement and does not by itself justify adoption.

## Recommendation to the reviewer

**Hold.** Keep `research/rules.py` as the default. The challenger is safe on the labeled cases and changed nothing on the eight held-out real documents, so there is no measured improvement to adopt. Adoption would be a human edit; nothing here performs one.

- A verdict is a recommendation to a human reviewer. The default stays research/rules.py in every case; nothing is adopted or activated automatically.
