# WEL-43 — measured source quality: yield reporting, bounded exploration, one comparison

Base: `83c6898b6830f4270088cd50cec2cd88be6b1c8a` (WEL-41 merged, schema v4). **No schema change.**
Nothing here activates a scheduler, edits a prompt, adopts a variant or touches a household record.

## What was built

| piece | file | what it does |
|---|---|---|
| source/topic yield report | `research/quality.py` | read-only aggregation over existing tables → Markdown with explicit denominators, one outcome class per candidate, and a "what remains unknown" section. No rates, no ranking. |
| bounded exploration | `research/schedule.py` (`eligible_rows`, `select_cycle_urls`), wired in `research/worker.py` | reserves `floor(limit/3)` cycle slots (min 1 when an unexplored eligible source exists) for never-attempted sources, **after** the permitted / not-stalled / due gates. |
| one adjustment, measured | `research/sentence_integrity.py` (challenger, not the default), `research/evaluate.py`, `eval/wel43/` | frozen manifest + rubric, labeled dev cases, held-out documents, predeclared verdict. |

## Commands

```
python3 -m research.quality  --db work/research.sqlite [--out work/quality.md]
python3 -m research.evaluate freeze  --out work/wel43_manifest.json
python3 -m research.evaluate dev     --manifest work/wel43_manifest.json
python3 -m research.evaluate holdout --manifest work/wel43_manifest.json --db PATH --md work/comparison.md
python3 docs/WEL-43-eval/rescore_recorded.py                          # reviewed verdict from recorded results
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests -q          # 144 passed (124 inherited + 20 new)
```

The holdout store is opened `mode=ro&immutable=1` and is never written.

## Exploration rule, exactly

1. Eligible = has a `source_hints` row with `fetch_permitted=1`, `stalled=0`, `next_check_at <= now`,
   ordered `(next_check_at, url)` — the incumbent order.
2. Reserved slots = `floor(limit/3)`, raised to 1 when an eligible never-attempted source exists,
   capped by the number of such sources and by `limit`.
3. Reserved slots go to eligible sources with `attempts = 0`, in incumbent order; remaining slots
   follow the incumbent order. The number of slots is unchanged; only membership changes.
4. Empty eligible pool or `limit = 0` selects nothing and creates no work. A source stops consuming
   the reserve as soon as it has one attempt, so the reserve rotates and no source is starved.

This is a fairness rule. Nothing in it scores source quality: the current sample cannot support that.

## Evaluation, in one paragraph

One adjustment was tested: sentence integrity — a line break in the middle of a sentence should not
end that sentence, and invisible characters (NBSP, zero-width, soft hyphen) should not break exact
comparison. Baseline (`research/rules.py`) stays the default. The manifest (`docs/WEL-43-eval/manifest.json`)
was frozen before the holdout was read; the rubric (`eval/wel43/rubric.md`) predeclared the verdict
rule. On 11 labeled dev cases the challenger agrees with ground truth 11/11 vs the baseline's 9/11,
with 0 new false matches and 0 lost matches. On the 8 held-out real documents the two variants are
**identical** (`docs/WEL-43-eval/comparison.md`). Under the corrected decision rule
(`eval/wel43/rubric-addendum-v2.md`) the reviewed verdict is **INCONCLUSIVE** — a fixture gain with
no held-out effect is not an improvement — and the dev-only reading (`adopt-with-review`) is reported
separately as fixture evidence. Recommendation: **hold**; the default stays `research/rules.py`.
See `docs/WEL-43-eval/verdict-reviewed.md`; the original run and its manifest are preserved unchanged
as history, re-scored by `docs/WEL-43-eval/rescore_recorded.py` without any new holdout read.

Claims are limited to sentence processing over already-extracted text. `evidence_text` is stored
extracted text, not HTML, so HTML extraction effects are **NOT TESTED**; no independent held-out HTML
corpus exists (fixtures authored while designing the adjustment cannot serve as one).

## Limits of the current data

One publisher, 8 documents, 9 fetch attempts all `ok`, 0 inference calls, 0 human review decisions.
No source can be compared to another, no rate is meaningful, and "no registered rule matched" (7 of 8
documents) is a gap in `research/rules.py`, not a source failure.
