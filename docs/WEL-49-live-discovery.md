# WEL-49: daily meal-index discovery continuation

Scope: configure the existing discovery worker; no runtime, schema, model, permission-gate or scheduler code changes. This is a bounded advance, not completion of all WEL-49 acceptance.

## Preparation

From repository root:

```sh
PYTHONPATH=. python3 scripts/prepare_meal_discovery.py --output /absolute/new/config-directory
```

The command validates the existing roster and emits a new configuration directory. It refuses an existing directory. It does not install, run, restart or publish anything. Generated collection scope is exactly the two existing meal pages plus `https://publicdomainrecipes.com/` as an explicit discovery route. The historical 25-seed registry and prior denials are preserved; they are not new collection grants. The new index has a daily cadence selected for this pilot, not an assertion of daily publishing. Discovered recipe pages retain the existing weekly refresh.

## Source evidence and limits

- Public Domain Recipes' [index](https://publicdomainrecipes.com/) states its recipes are public domain and its project is under the Unlicense; its newest-recipes links are directly present in HTML. The product Fetcher observed HTTP 200 and robots allowed on September 16, 2026. Text only; no images, logos or donation content. Preserve attribution and defer publication.
- Existing [FOSS recipe text licence](https://fossrecipes.com/license.html) remains CC0. Its index contains absolute `http://` recipe links despite being served over HTTPS. The existing same-origin check excludes those links. A direct HTTP-route assessment encountered an unavailable robots check (HTTP301); it was not bypassed. FOSS discovery is NOT enabled by this profile; its prior exact orzo entry is unchanged.
- Foodista remains denied/pending. No new request, alternate access route or grant.
- Only the first 20 eligible index links are considered by the incumbent mechanism. This is bounded newest-item monitoring, not exhaustive catalog enumeration. More than 20 arrivals between polls could be missed. Link order is not a family-quality ranking; desserts and incomplete recipes can be discovered.
- The model cannot expand source access. Each hint passes the existing origin/login/robots/registry gates before later collection. Discovery does not approve recipes or affiliate links.
- The incumbent canonical publisher report does not attribute new exact child URLs automatically. Their source URL, attribution and discovery-route lineage are retained, but they appear as unattributed surfaces in that count. No new publisher-count claim follows.

## Real source-to-store proof

Isolated proof directory: `/private/tmp/wel49-discovery-proof-20260916`. It began as a copy of the real pilot's post-shipment backup (44 inference rows, 32 recipe versions), not an empty ledger. The running pilot database/configuration were not changed. The actual Qwen27B digest and Ollama version were recorded; no synthetic model responses were used. Proof runner is an unshipped one-off in the coordination packet, not another service feature.

First cycle at 23:27:04UTC: one actual index fetch, 20 discovered links, 3 permitted assessments, zero model calls. Subsequent bounded cycles selected recipe URLs themselves; none of these four URLs was manually seeded in the new configuration:

| New evidence | New saved extraction | Result |
| --- | --- | --- |
| Baked Trout | version33 | Pending/incomplete: step-boundary coverage gap and unstated quantities/timing. |
| Casio in pastelletto | version34 | Pending/incomplete: total time unstated; not necessarily an appropriate family dinner. |
| Castagnole | version35 | Pending/incomplete: total time unstated; dessert, not a dinner recommendation. |
| Clam Chowder | version36 | Pending/incomplete: ingredient coverage and servings-expression gaps; total unstated. |

These are real new persisted research records, not approved app cards. The first/second-cycle run IDs are `run_20260916T232704Z_248e16` and `run_20260916T232705Z_33f4f5`. Raw evidence, model-call accounting, quoted fields, unknowns and route provenance remain inspectable in that isolated SQLite database. Original backup records remain available unchanged in the production pilot. No replay reset, fake model identity, source-policy bypass or publication occurred.

## Focused verification

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_wel49_meal_discovery.py tests/test_wel49.py tests/test_wel49_permissive_recipes.py tests/test_recurring.py -q
```

116 passed. The new tests use explicitly synthetic transport to exercise the real worker's index discovery, later recipe collection, no-duplicate replay, next-day new-item detection, 24-hour index cadence, preserved history/denials and protocol-boundary refusal. Those fixtures are separate from the real Qwen proof above. No unrelated broad suite was repeated.

## Remaining acceptance and delivery

Independent review, exact PR merge authority and exact live-profile installation remain outstanding. Running hourly registration alone will not install this profile.

WEL-49 remains open for broader useful coverage, three actual permitted recipe publishers and the intended refreshed ten-source working set. Two recipe publishers and one active discovery index do not satisfy those criteria. FOSS discovery needs a permitted compatible route; Foodista stays pending. Do not add government material or label an unverified source family-proven to fill the count.

The real sample exposes bounded downstream WEL-48 extraction gaps (trout step boundaries and chowder ingredient/servings handling), plus WEL-52's already-recorded unknown-total limitation. No correction is included here. These must not be hidden by loosening validation or calling pending candidates published meals.
