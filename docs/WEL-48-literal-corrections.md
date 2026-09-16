# WEL-48 recipe-literal correction — September 16, 2026

## Bounded change

The first live PDR casserole extraction retained correct source strings but normalized
`1/2 cup` as amount 1 and item `/2 cup...`, and `2/3 cup` as amount 2.
Its exact quoted prep/cook/serving labels included decorative icons and failed the
otherwise-correct closed scalar grammar.

The correction matches complete ASCII fractions before integer prefixes, uses the
same token at both ends of a range, and preserves unknown amounts for malformed
or zero-denominator input. Mixed and Unicode fractions, ordinary numbers, decimals,
existing units and literal source spans remain supported. Invalid fractional pieces
are not silently treated as zero.

Only a single leading timer, frying-pan or place-setting icon (optionally followed
by the emoji variation selector, then horizontal whitespace) is allowed before the
existing full-match label grammar. No general Unicode/punctuation stripping, word
deletion, negation removal or free numeric extraction. Bare readings, role matching,
recipe-region validation and source conflicts retain their existing checks.
Quotes and offsets remain the exact original source strings.

## Actual-source fixture proof

`eval/wel48/fixtures/operating-recipe-literals.json` contains the already-retained
permitted recipe text, original SHA-256 and attribution/access receipt, and a fixed
model-shaped proposal. No new web request or model call produced these tests.
Production heading location and binding process the exact text directly; tests
do not invent HTML/schema.org values or replace the subject with a mock.

- Casserole: 9 ingredients / 3 steps; onion and celery 0.5 cup, rice 2/3 cup,
  hot water 1.75 cups, cooked-chicken prerequisite retained. Servings 4, prep 5,
  cook 40 accepted with exact icon-prefixed quotes. Total remains UNKNOWN.
- Orzo: 11 ingredients / 4 steps preserved; all unstated time/serving values remain
  UNKNOWN. Cooking-step durations do not become a made-up recipe total.
- These are still incomplete, unapproved candidates. No family card is published.

## Verification

Before product edits, the new targeted file produced 18 failures / 8 passes,
including the exact fraction and scalar defects. After correction:

- Literal and existing normalizer files: 33 passed.
- Affected WEL-48/49/50/52/54 tests: 386 passed.
- Full repository: 572 passed in 12.12 seconds.
- `git diff --check`: clean.

The first affected-suite attempt had 383 passes and two failures: the pre-existing
upgrade oracle pinned current extractor v3, and the consumer path was not supplied.
The version oracle now explicitly tests both v2→v4 and v3→v4 with unchanged old
rows/spent calls. The consumer test runs against the real isolated app checkout
at `94a00e3b6ebd58dc76cf6be99ce6d4347b9c15eb`; it neither edits nor deploys that app.

Final command:
```sh
WELLNEST_APP_DIR=/private/tmp/wellnest-wel19-sep16.BASm13 PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /usr/bin/python3 -m pytest -q -p no:cacheprovider
```

The app path may be replaced by an installed consumer checkout; record its exact
commit. Missing consumer/dependencies remain a test failure, not a skip.

## Existing-data application and limitations

Extractor identity becomes `wel48_extractor_v4`; schema and model prompt versions
do not change. Existing worker `recipes.work_items` recognizes a new extraction
key, preserves old recipe versions and spent calls, and schedules new extraction
under the current provider. This is a NEW versioned extraction attempt, not replay
of the prior ambiguous call. Its ordinary budget/lock/pending-review rules remain.

There is no supported CLI that simply rebinds a successfully retained model response
without inference; successful rows do not retain the complete response as a reusable
proposal. Do not patch live rows, clear the ledger, impersonate a model response, or
claim this patch automatically corrected the running database.

After separate deployment authorization, the existing `python3 -m research.worker
cycle` entry point under the installed recipe-enabled configuration can process
already-retained evidence with the new extractor identity, even when source pages
are not due. This can schedule work for ALL eligible retained recipes, not just the
casserole, and entails new model calls within existing per-run limits. No such
deployment or run was performed for this correction. Live source-to-database proof,
editorial approval and the app's missing-total-time policy remain outstanding.

Other icons, unsupported quantity syntaxes and genuine conflicting/ambiguous source
claims remain outside this bounded grammar. The general-proposal JSON failures,
source expansion, automatic promotion and app redesign are explicitly out of scope.

Independent Grok review pending. No merge, deployment, live database edit or content
publication is authorized by these author tests.
