# WEL-49 — source registry and cadence mechanics

**Combined WEL-48/49 candidate:** see `WEL-48-49-integration.md` for current combined evidence and configuration. This tree retains one no-fetch integration hold for Cookie and Kate and two WEL-48 historical no-fetch recipe entries: 18 unique allowlist URLs, 13 collection flags, 10 declared working-set URLs but only 9 with an active collection flag across 6 roots. The standalone counts and pending-migration notes below describe the earlier WEL-49 delivery, not the combined candidate. Neither document authorizes collection, inference, publication or service activation.

Binding brief: `design-v3.md` and `hardest-contract.md` v3 in the WEL-49 coordination packet, grounded on `2b7602f42856ce34c6a18c810f7181bca418bd6f`. This is builder evidence, not independent review or merge authorization.

## What changed

- Three additive tables retain assessed publishers, exact source surfaces, and explicitly declared equivalent URL spellings. The roster projects in one transaction, validates the merged parent graph, and preserves previous rows after missing/invalid files or interrupted projection. Historical seed mapping and working-set order remain in the reviewed file.
- A registry entry can deny collection but cannot grant it. Only `retain` plus `permitted` stops denying; the ordinary allowlist/access gates still apply. Exact aliases share denial only. Evidence URLs, hashes and version identity remain unchanged.
- Denial is checked before cycle slot selection, at the final worker request boundary, before discovery assessment, and at every redirect hop before robots. Removing denied sources from the pool leaves the incumbent exploration reserve unchanged.
- Successful collection uses an assessed surface's cadence (3 hours–30 days for indexes, 6 hours–30 days for other surfaces); absent/unattributed sources keep 7 days. The three-hour minimum supports bounded pilot checks of an eligible discovery index, not faster refresh of discovered recipe pages. Errors and blocked-source backoff remain unchanged. A response's Retry-After is a floor measured from receipt. Both delta seconds and HTTP dates work; 60-day deadlines are not capped. Unrepresentable deadlines stall for explicit review.
- Reports show canonical publisher counts over stored evidence, unattributed URLs, registry policy and last evidence version, plus one reasoned disposition per source for the latest cycle.

## Configuration and operation

The roster is `roster.json` beside the selected allowlist. Default: `sources/roster.json`. The existing `run` and `cycle` commands load it under the store lock; no new command, daemon or scheduler is introduced.

Edit a surface's `roster_status` to `replace`/`defer`, or its `access_status` to `hint_only`/`unknown`/`denied`, to withdraw it. Re-run the worker to project the change. Restore `retain` **and** `permitted` to stop denying; that does not itself grant access. A publisher withdrawal requires editing each surface. `reset-source` cannot override the registry. Deleting the file retains the last valid configuration; a corrupt file records a failed run while other already-permitted, non-denied sources continue.

The closed topic vocabulary is `recipe_supply`, `weekend_methods`, `weekend_activities`, `seasonal_ideas`, `household_systems`, `product_discovery`, `parenting`, `family_operations`. Assessors must explicitly identify themselves with `agent:<name>` or `human:<name>`; nothing defaults to human provenance. Fixture identities and assessments are explicitly synthetic.

## Acceptance evidence

| Criterion | Builder result | Evidence / remaining work |
|---|---|---|
| Reviewed 25-seed roster and ordered working set | Roster projects; breadth criterion INCOMPLETE | Reviewed coverage amendment records 25 seed dispositions; with the NHLBI amendment the roster has 14 publishers and 22 surfaces. The ordered working set has 10 URLs across 7 root publishers, but the ten count is reached with two articles from one federal publisher, so breadth is not claimed complete. |
| Canonical identity, provenance, effective denial | PASS, offline | Exact surface/alias lookup, nullable attribution, parent-root counting, atomic whole-file validation and all four zero-request denial boundaries. |
| Per-source cadence and Retry-After | PASS, offline | Config bounds, unchanged backoff/stall, response-receipt clock, HTTP-date/delta floors, uncapped 60-day floor, overflow stall. |
| Collection from at least three permitted publishers | PASS fixture mechanics; live NOT TESTED | The allowlist/roster now make 6 working-set publishers collectable, and three synthetic publishers persist separate evidence/schedules. Real collection evidence still requires the controlled worker run. |
| Hints/model text do not create source authority | PASS, offline | No registry grant writes; model/hint content does not add roster rows. Assessment refusal precedes any robots request. |
| Persistence, replay, explanation | PASS, offline | Real subprocess deaths before projection commit preserve the complete prior graph/denial. Invalid merged cycles roll back all upserts. Missing/corrupt roster retains denial and cadence. Source decisions have exact checked/skipped/not-due/stalled accounting. |

Binding commands (network refused by existing test fixtures):

```text
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_wel49.py -q
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests -q
```

Exact output is retained in the delivery packet. The baseline has one known WEL-43 manifest-history assertion failure because WEL-42 changed `research/rules.py`; this work does not rewrite/refreeze historical artifacts. Existing migration-version assertions now compare with the latest declared migration rather than hard-coded schema 4.

## Integration gate and limitations

**Migration 6 belongs to WEL-49 and must integrate after WEL-48's migration 5.** This isolated branch contains 1–4 and 6 solely for offline development. Do not apply it to any durable/shared store before integration: the unchanged loader uses the maximum version and would skip a subsequently added 5. No migration 5 is fabricated and the loader is unchanged. Recreate temporary test stores after integrating in list order 1–6.

No live service, schedule, collection, model call, deployment or merge occurred. `sources/roster.json` contains the reviewed coverage amendment and `sources/allowlist.json` adds its four collection grants, plus the two NHLBI recipe grants described below. The working set now has ten surfaces across seven root publishers, two of them articles from one federal publisher. Breadth across distinct publishers and real three-publisher collection evidence remain incomplete.

Opposite-engine review 1 identified two bounded corrections, now implemented: program publishers may have a null official URL (Playing Preschool is identified under Busy Toddler); source topics are remapped to the existing closed vocabulary. The focused suite now passes **85 tests**, including the real corrected roster, nullable-program integration and the NHLBI recipe amendment below.

### Access assessment follow-up

The completed coverage follow-up distinguishes collection from republication. Busy Toddler, Days With Grey, Cookie and Kate, and Love and Lemons are collectable on the recorded public-web/robots basis, while their reuse restrictions travel in each allowlist entry. Budget Bytes remains `hint_only` because its terms prohibit scrape/crawl/spider. Mothercould is `denied`/`defer` because its terms prohibit scraping, indexing, surveying, or data mining. The Lazy Genius remains `unknown`. Identity and robots/HTTP success alone do not confer permission; no republication grant is inferred.

The binding design-v3 and opposite-engine review2 PASS remain unchanged. Coverage evidence and the applied proposal are retained in the WEL-49 coordination delivery. Migration-5 integration still precedes final PR readiness.

### NHLBI recipe surfaces (2026-09-16 configuration amendment)

One publisher (`nhlbi`, National Heart, Lung, and Blood Institute) and exactly two `site_article` recipe surfaces were added to `sources/roster.json` and `sources/allowlist.json` from the recorded proof in the WEL-49 coordination packet (`nhlbi-proof.md`, `nhlbi-proof/`), which captured both pages once through the product Fetcher on 2026-09-16 (robots allowed, http 200, no redirect, no login wall). Nothing was refetched to configure them, and no source was substituted. The two recipes are first in the surfaces list, the ordered `working_set`, and the allowlist; every pre-existing publisher, surface, alias, no-crawl denial, historical seed disposition and its order is unchanged after them. The mechanism, schema and migrations are unchanged: `source_type` is free-form `TEXT NOT NULL`, and `government` follows the incumbent CDC entry.

Projected into a temporary store the roster now has 14 publishers, 22 surfaces and 25 historical seeds; the working set has 10 URLs across 7 distinct root publishers; the allowlist has 16 entries, 14 with `fetch=true`. A manual run attempts grants in allowlist order under the ten-URL hard cap, so the two recipes sit inside the first ten grants; cycle selection still orders by next-check time and URL and is unchanged.

Source-use basis, as recorded on each row: collection on the recorded robots/transport observation; internal text retention and local inference on NHLBI's content policy, which states site information is generally public domain except identified third-party material and requires attribution, no endorsement or advertising implication, unaltered formatted publications and no logo use. Photos, the recipe video, logos, PDFs and third-party material are excluded. Any reuse must carry `Source: National Heart, Lung, and Blood Institute; National Institutes of Health; U.S. Department of Health and Human Services.` That internal basis is distinct from editorial approval, which remains absent; no human approval is claimed, and the rows say so.

Corrections applied to the proof's proposal: `cadence_seconds` is null, which means the existing seven-day fallback applies if collection is later scheduled, not a one-time-only collection; the HTTP `Last-Modified` header is a transport header with unknown editorial semantics, and one observation does not establish a posting cadence; page publication and modification dates are unknown. Both recipes require already-prepared ingredients (grilled chicken and cooked broccoli; cooked brown rice and cooked mixed vegetables), and neither states a total time, so none is derived from prep plus cook.

What this amendment is not: it is one federal meal publisher, so the three-permitted-publisher collection criterion and the social/creator coverage remain as recorded above; ten working-set URLs by count does not by itself complete the coverage criterion, since it is reached with two articles from a single publisher. It is an unmerged configuration, not a live grant, schedule activation, content approval, model result or deployment; no durable store was touched.

Accepted design limitations: identity is not legal permission; a process death between receipt and schedule commit can lose Retry-After (the incumbent request caps remain); cadence is operator-declared, not adaptive; publisher withdrawal is per surface; undeclared equivalent URL spellings are not implicitly denied. No fuzzy host/path matching or evidence merging is introduced.
