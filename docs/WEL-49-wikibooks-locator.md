# WEL-49 Wikibooks locator v7 — implementation evidence

Baseline `37a8179a9f80598f31dc6d31bd0b4b7281730426`.
Binding design: `tandem/WEL-49-wikibooks-locator-design-fable-v1.md` plus
`tandem/WEL-49-wikibooks-locator-STAN-CORRECTION-20260921.md` (SHA-256
`07b74ab47192b9f0bb20a556a1458dfb79fbdabef92f9741242bfe39c07bc6d4`),
independent Astra NO OBJECTIONS supplied by coordinator.

Implemented only the existing heading tier: `Procedure` joins the shared step-heading
constant; the exact edit-control line is excluded; a section boundary requires an
immediately following edit control AND a closed label (`ingredients`, `instructions`,
`directions`, `procedure`, `notes, tips, and variations`); the full quoted HTTP(S)
`Retrieved from` line terminates the footer. There is no arbitrary-capitalization or
next-line heuristic. Wikibooks title chrome is removed only for the exact title
pattern and its name must occur as exactly one whole retained-text line.

Locator version is v7. Existing text hashes, scalars, structured tiers, binding,
prompts and durable machinery are unchanged. Old stores are not backfilled. The
version bump affects future collection manifest hashes under incumbent semantics;
this work does not install code or collect against a live store.

Fixtures preserve original HTML and exact extracted text for three first-party
pages. `PROVENANCE.json` records distinct URL-hash retention keys, body hashes and
text hashes, original revision URLs, access outcomes and CC BY-SA license. Original
HTTP headers and cookies are excluded. Tests assert exact inventories 4/7, 7/7, 5/4,
every literal/span, unique grounded names, unchanged text, empty locator scalar roles,
and ordinary prose immediately before edit-control remaining a step.

One literal test-oracle correction was necessary: Fable's prohibition on any step
starting `Add ` contradicts Pasta's actual `Add spaghetti…`, `Add green beans…` and
`Add a pinch…` steps. The implementation excludes only exact `Add languages` and
`Add topic` chrome in that assertion and retains the independent full literal-list
oracle. Runtime boundary behavior follows the accepted design unchanged.

## Verification

```sh
python3 -m pytest -q tests/test_wel49_wikibooks_locator.py tests/test_wel49_wikibooks_profile.py tests/test_library.py tests/test_wel48_locate.py tests/test_wel48_extract.py tests/test_wel48_related_boundary.py tests/test_wel49_heading_boundaries.py tests/test_wel49_permissive_recipes.py tests/test_wel48_bind.py tests/test_wel48_manifest.py tests/test_wel48_replay.py tests/test_wel48_identity.py tests/test_wel48_no_hardcoding.py tests/test_wel48_wel49_integration.py tests/test_wel48_corpus.py
```

Result: **131 passed, 9 failed** (5.40 seconds). All nine belong to the recorded
baseline failure set, not new failures:

- `test_wel49_heading_boundaries.py`: `test_note_heading_ends_foss_directions`,
  `test_contributor_heading_ends_pdr_directions_and_scalars_bind_as_stated`,
  `test_old_footer_and_note_units_are_not_accepted_as_steps` — stale v5 assertions.
- `test_wel48_manifest.py::test_locator_bump_without_recollection_is_a_noop` — stale v5 assertion.
- `test_wel48_manifest.py::test_ambiguous_correspondence_is_incomplete` — absent historical HTML.
- `test_wel48_corpus.py`: `test_frozen_live_corpus_counts_and_hashes`,
  `test_complete_results_include_both_heldouts`,
  `test_all_six_live_results_are_reported_and_fixtures_excluded`,
  `test_saved_model_replay_matches_binding_v5_exact_oracle` — absent historical `/tmp` inputs.

The absent corpus checks remain **not verified**. The stale tests were not edited.
An additional direct comparator against `git show 37a8179:research/recipe_locate.py`
confirmed four full incumbent manifests (Orzo, Casserole, structured standard,
structured ambiguous entity) are identical modulo locator_version.

```sh
PYTHONPATH=. python3 scripts/eval_wikibooks_retained.py --receipts work/wikibooks-receipts --output work/wikibooks-v7-no-model
PYTHONPATH=. python3 scripts/eval_wikibooks_retained.py --receipts work/wikibooks-receipts --output work/wikibooks-v7-qwen --model qwen3.8:27b
```

Both completed once. No-model: 3 evidence rows, 3 v7 manifests, 3 failed unavailable
inference versions, 0 calls, 0 publications. Real local Qwen: exactly 3 calls, 3
schema-valid/cooking-usable pending candidates, 0 fully complete recipes, 0 publications,
56.115 seconds. Source transport replayed the retained actual responses without
network fallback. Full yield report: `work/wikibooks-v7-qwen/yield.json`.

The earlier single unretained qualification check plus the captured three-page check
made four live page requests total during source qualification; the corrected proof
made none. No inference retry, live DB write, publication, restart, deployment, commit
or merge occurred.
