# WEL-42 meal-detail payload (producer side)

Version 1. Produced by `research/meal_export.py`, consumed by `src/core/mealResearch.ts` in
`buddyfb2026/wellnest-v1`. Both sides are pinned to one shared fixture
(`src/fixtures/meal-research.synthetic.v1.json` in the app), asserted by
`tests/test_meal_export.py::test_export_matches_the_shared_consumer_fixture`.

## Envelope

```json
{ "payload_version": 1, "capability": "weekly_meal_plan", "details": [...], "omitted": [...] }
```

The consumer refuses the whole payload on an unknown `payload_version` or any `capability` other
than `weekly_meal_plan`, and leaves existing plans untouched.

## One detail

| Field | Meaning |
|---|---|
| `detail_id` | Candidate dedupe key. Stable across runs. |
| `candidate.state` / `state_set_by` / `publishable` | Must be `approved` / `human:<name>` / `1`. All three, independently. |
| `candidate.rule_id` / `rule_version` | Must still be registered in `rules.py` at that exact version. |
| `applicability.template_name` | Exact meal name. Not a substring or keyword. |
| `applicability.required_ingredients` | All must be present exactly in that meal's ingredients. |
| `guidance.text` | Fixed reviewer-authored rule text. Never model prose. |
| `guidance.supporting_passage` | A whole sentence quoted from the evidence. Absent ⇒ the detail is omitted. |
| `evidence.*` | identity, revision, content hash, source URL, attribution, checked time, publication time (nullable). |

## Why applicability is a separate registry

`MEAL_APPLICABILITY` maps a rule to exactly one meal template. A rule with no entry can never attach
to any meal. This keeps guidance from drifting onto a recipe it was not reviewed against, and it
cannot cause a meal to be selected, reordered or substituted — enrichment runs *after* the app has
already chosen the week's meals under household constraints.

## The registered meal rule

`rinse_fresh_produce_under_running_water@1` → template `Sheet-pan chicken and vegetables`,
requiring ingredients `broccoli` **and** `carrots`.

Its support sentence was read in real evidence already collected by WEL-40:

| | |
|---|---|
| Evidence | id 6, `content_kind='live'`, revision 1 |
| URL | <https://www.cdc.gov/food-safety/prevention/index.html> |
| Attribution | U.S. Centers for Disease Control and Prevention |
| Content hash | `b2574db36c04e96958bae89bb4ec9f9e52d2d1ec1dcc01698e8d08af81aeb418` |
| Fetched | 2026-09-15T15:33:48Z |
| Support sentence | "Rinse fresh fruits and vegetables under running water." |
| Problem sentence | "Unwashed fruits and vegetables" |

`tests/test_meal_export.py` re-reads that database read-only, re-hashes the stored text against the
recorded hash, and asserts the rule matches the sentence as a whole sentence.

The action text restates the support sentence and scopes it to the meal. It adds no temperature,
time or safety claim the source does not make.

## Building the snapshot

```bash
python3 scripts/wel42_build_snapshot.py <research.sqlite> <app>/src/research/meal-research.approved.v1.json
```

The script copies the database first and never writes to the one it is pointed at. It saves rule
candidates as `pending` (the worker cannot approve) and exports whatever is currently approved,
publishable and human-set — today, nothing.

`--preview-approve <id>` simulates approval **on the throwaway copy only**, for demos and tests. It
stamps `human:PREVIEW-NOT-A-REAL-APPROVAL` and adds a `_preview_warning`, so a preview artifact can
never be mistaken for approved research or bundled by accident.

## Current state: one real candidate, pending

The CDC candidate is `pending` / `state_set_by='worker'` / `publishable=0`, so the export produces
**zero** details and the app renders no detail. Only a named human can approve it; see
`/tmp/wel42-coordination/approval-packet.md`.
