# WEL-43 rubric addendum v2 — holdout differences must be reviewed (2026-09-15)

`eval/wel43/rubric.md` is unchanged and remains the rubric the original run was scored under. This
addendum corrects one defect found in review: the v1 decision rule keyed off the development set
only, so a gain on authored fixtures could produce `adopt-with-review` while the held-out documents
were either unexamined or differed in ways nobody had classified.

The adjustment under test, the variants, the frozen cases and the measured results are **unchanged**.
Only the decision step changes.

## Corrected decision rule

Let *dev* be the labeled development result and *holdout* the held-out document result.

1. The **dev-only verdict** keeps the v1 rule and is reported separately, labeled as fixture evidence.
   It is never presented as a real-world improvement.
2. A verdict that takes the holdout into account requires every holdout difference to carry an
   explicit human classification `review` of `true_gain`, `false_gain`, `lost` or `neutral`.
   - any unclassified difference → **inconclusive** (a reviewer must classify it first);
   - any `false_gain` or `lost` → **do-not-adopt**;
   - **no differences at all** → **inconclusive**: the adjustment had no measurable effect on real
     documents, and fixture gains alone do not establish an improvement;
   - at least one `true_gain`, none of the above → **adopt-with-review**.
3. Any blocker from the v1 rubric (new false support on dev, lost true match, injection-detection
   change, non-determinism) still forces **do-not-adopt**, whatever the holdout shows.

No re-tuning, no new comparison and no further holdout read is permitted under this addendum: it
re-scores the results already recorded in `docs/WEL-43-eval/comparison.md`.
