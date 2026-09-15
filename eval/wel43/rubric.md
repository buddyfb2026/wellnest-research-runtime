# WEL-43 evaluation rubric (predeclared, frozen before the holdout was read)

One adjustment is under test: **sentence integrity** (`research/sentence_integrity.py`, version
`sentence_integrity_v1`) against the incumbent `research/rules.py` segmentation.

- **Baseline**: `rules.match_rules` / `rules.sentence_units`, unchanged, and it stays the default
  regardless of the outcome of this evaluation.
- **Challenger**: `sentence_integrity.match_rules`, imported by nothing in the collection path.

## Scope of any claim

The challenger changes sentence processing over **already-extracted text**. The holdout corpus is
`evidence_text`, which is stored extracted text, not raw HTML. Therefore:

- Claims may be made about sentence segmentation and whole-sentence matching.
- **No claim may be made about HTML extraction.** No independent held-out HTML corpus exists — any
  HTML fixture here was authored by the builder while designing the adjustment, so it cannot serve
  as a holdout. HTML-level effects are NOT TESTED.

## Dimensions, scored separately (never summed into one score)

1. `true_support_gained` — challenger matches a reviewed support sentence where the ground truth says
   it is present and the baseline missed it.
2. `false_support_gained` — challenger matches where the ground truth says the reviewed sentence is
   **not** present (fragment, negated prefix, question form, fused unrelated lines).
3. `support_lost` — baseline matched a true case and the challenger does not.
4. `problem_quote` — same three measures for the reviewed problem sentence.
5. `injection_detection` — `extract.scan_for_instructions` output on the identical text must be
   identical for both variants.
6. `determinism` — same input + same variant version run twice must produce identical results.
7. `stored_text_integrity` — neither variant may alter evidence text, `content_hash` or version rows.
   Both run at match time on a copy; stored hashes are untouched. A *hash difference caused by an
   intentional normalisation of the input* is not what this dimension forbids; it forbids a variant
   writing to the store or producing a different result for the same input and version.

## Decision rule (predeclared)

- **adopt-with-review** only if `true_support_gained > 0` **and** `false_support_gained == 0` **and**
  `support_lost == 0` **and** injection detection identical **and** deterministic.
- **do-not-adopt** if any false support is gained, any true support is lost, injection detection
  changes, or a variant is non-deterministic.
- **inconclusive** if the variants do not differ on the frozen cases, or if the only differences are
  on cases whose ground truth the rubric cannot settle.

An adopt result is a recommendation to a human reviewer. It changes no default, edits no prompt or
code automatically, and activates nothing. No tuning is permitted after the holdout is read: a
changed challenger requires a new frozen manifest and a new holdout run.

## Budget

Zero model calls and zero network requests. Both variants are deterministic local code.
