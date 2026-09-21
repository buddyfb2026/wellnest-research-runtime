# WEL-48: related-content boundary

ROUTE: DIRECT — bounded correction using the established exact section-heading stop mechanism; no schema, scalar grammar or publication change.

Fresh real evidence 11, recipe version 33, collected 2026-09-21T16:40:51Z from https://publicdomainrecipes.com/baked-trout/, source content hash `16d52c909d41eadb5f82d9e98dbed3d897e1d54f7a5538db8563c4d036024e43`. Attribution: Public Domain Recipes; individual contributor credit remains in original source evidence. Text collection follows the already-approved public-domain source route; no imagery included.

The retained normalized text is copied verbatim to `eval/wel48/fixtures/baked-trout-20260921.txt`. Its six cooking steps were correctly present in normalized Qwen output, but the locator additionally counted six footer/navigation lines beginning with `Related`. This falsely reported steps 6–11 missing. The focused regression failed before the correction (12 located steps versus 6 expected).

The fix adds exact case-insensitive `Related` to the existing section terminators and increments the locator version for traceable new manifests. It does not discard instructions merely containing that word. Tests reconstruct a source-literal proposal; they do not claim to replay raw model output, which was not retained.

Remaining limits: cook-time narration is intentionally outside the existing closed scalar grammar; source-total time, quantities and servings remain unknown where unsupported. No scalar weakening or full-candidate completion claim. Existing saved records are not rewritten. Recollection/re-extraction and live deployment are separate authorized actions. Chowder has not yet been reproduced in the fresh retained evidence.
