# WEL-48: related-content boundary

ROUTE: DIRECT — bounded correction using the established exact section-heading stop mechanism; no schema, scalar grammar or publication change.

Fresh real evidence 11, recipe version 33, collected 2026-09-21T16:40:51Z from https://publicdomainrecipes.com/baked-trout/, source content hash `16d52c909d41eadb5f82d9e98dbed3d897e1d54f7a5538db8563c4d036024e43`. Attribution: Public Domain Recipes; individual contributor credit remains in original source evidence. Text collection follows the already-approved public-domain source route; no imagery included.

The retained normalized text is copied verbatim to `eval/wel48/fixtures/baked-trout-20260921.txt`. Its six cooking steps were correctly present in normalized Qwen output, but the locator additionally counted six footer/navigation lines beginning with `Related`. This falsely reported steps 6–11 missing. The focused regression failed before the correction (12 located steps versus 6 expected).

The fix adds exact case-insensitive `Related` to the existing section terminators and increments the locator version for traceable new manifests. It does not discard instructions merely containing that word. Tests reconstruct a source-literal proposal; they do not claim to replay raw model output, which was not retained.

Remaining limits: cook-time narration is intentionally outside the existing closed scalar grammar; source-total time, quantities and servings remain unknown where unsupported. No scalar weakening or full-candidate completion claim. Existing saved records are not rewritten. Recollection/re-extraction and live deployment are separate authorized actions. Chowder has not yet been reproduced in the fresh retained evidence.

## Missing historical corpus disposition

The two old locator tests depended on `/tmp/wel48-coordination/corpus/raw`. Targeted searches of known WellNest coordination directories, worktrees and project documents found no retained raw corpus. No restricted creator pages were recollected or repackaged.

Their non-reproducible historical expectations are retained here for audit, not claimed as passing evidence: Cookie and Kate ratatouille `(13 exact, 0 ambiguous, 0 unmatched, 11 steps)`; lentil soup `(15, 1, 0, 7)`; vegetarian chili `(19, 0, 0, 5)`; spicy vegan black bean soup `(13, 0, 0, 4)`. Love and Lemons black bean soup: heading tier, 15 ingredients and 3 steps. Those specific five pages remain **NOT REVERIFIED**; a green suite does not recover their lost proof.

The two tests now use explicitly authored self-contained HTML to test the actual extraction path: exact versus ambiguous decoded-entity correspondence with exact counts, raw/decoded literals and offsets, ordered decoded steps, and heading-only ingredient/step extraction with exact arrays and termination. No assertion was skipped or made optional; the historical page-count claims are replaced by narrower, reproducible behavioral claims. The real trout evidence fixture remains separately identified. No production code changes accompany this test repair.

Verification: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_wel48_related_boundary.py tests/test_wel48_locate.py tests/test_wel48_extract.py tests/test_wel48_literal_corrections.py -q` — **49 passed**.
