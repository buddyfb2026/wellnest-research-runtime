# WEL-50: empty generic-model response correction

Scope: repair `candidate_proposal` response generation, not redesign the research engine.
Base: research main `af702cce547a175d7cbdd642a6e56e298ece5e50`.

## Proven failure and smallest correction

The operating ledger's ten failed generic calls (23–32) all retained zero response
characters. The JSON parser correctly rejected empty input. The generic request
omitted `think` and `num_ctx`; recipe extraction already explicitly requested
`think=false`, context 16,384 and a 4,096 output-token limit.

The generic adapter now defaults to `think=false` and sends its existing recorded
8,192-token context explicitly. Its 900-token output limit, temperature, seed,
prompt, evidence limit and strict JSON-object parsing are unchanged. Explicit
recipe overrides remain unchanged. No response repair, reasoning-field fallback,
extra inference retries, budget increase or candidate promotion was introduced.

## Actual local-model comparison — September 16, 2026

Host: existing M3 Ultra Studio. Provider: existing Ollama 0.32.14, local
`qwen3.8:27b`, Q4_K_M; verified digest:
`22130167c4c20e20c7b71454612966ca8e8171e9b3cc8ab6ce8aa6cbfec79643`.

Four bounded calls used already-retained public evidence and an in-memory copy of
the ledger. The source database was opened read-only. No source requests, permanent
database writes, service changes or publications. Model reasoning was neither
inspected nor retained.

| Request | Source | Final answer | Provider completion | Duration |
| --- | --- | --- | --- | --- |
| Old defaults | FOSS chicken/orzo | Empty; JSON parsing error | `stop`, 393 output tokens | 20,812 ms |
| Change only `think=false` | Same exact evidence | Valid JSON, 1,041 characters | `stop`, 263 tokens | 13,968 ms |
| Patched production defaults, including explicit context | Same exact evidence | Valid JSON, 1,041 characters | `stop`, 263 tokens | 18,451 ms |
| Patched production defaults | Public Domain Recipes chicken/rice | Valid JSON, 1,594 characters | `stop`, 450 tokens | 23,647 ms |

This isolates the observed empty-answer behavior to the default thinking setting.
It does **not** establish token-budget exhaustion: the old call reported `stop`,
not `length`. The explicit context also corrects the mismatch between requested
settings and the context already recorded in the ledger.

Source evidence identities:

- <https://fossrecipes.com/recipes/orzo-chicken>, evidence 9, content hash
  `52366a25e87258f02801efe4c4f169fdc41e6dec06450faa5b9ff0ac7e1f52f1`.
- <https://publicdomainrecipes.com/easy-chicken-and-rice-casserole/>, evidence 10,
  content hash `06ef950818360bc16a5e250870a2014da73c051150c4703fb22fc0a5c6d3c447`.

Both parsed outputs also went through the existing production candidate validator.
Orzo retained three grounded observations and remained deferred as free text.
Casserole remained deferred under the existing shopping-claim rule; its short
`Servings: 4` quote did not pass the existing generic quote-length check. These
are generic audit proposals, **not approved recipe versions or usable app cards**.
Recipe-specific literal correction is separate research PR11.

## Verification

- Before the code correction: two request-contract tests failed; four rejection
  cases passed. After: all six passed within the affected suite.
- 191 affected tests passed, covering the actual worker, generic and recipe
  transport, reservation/restart behavior, throughput, backup configuration and
  recipe replay.
- Full repository: **550 passed in 10.51 seconds**, including the real app consumer
  at `94a00e3b6ebd58dc76cf6be99ce6d4347b9c15eb`:

  ```sh
  WELLNEST_APP_DIR=/private/tmp/wellnest-wel19-sep16.BASm13 PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /usr/bin/python3 -m pytest -q -p no:cacheprovider
  ```

- Final test-fixture metadata was aligned with the actual `stop`/393 receipt;
  all five new tests were rerun and passed. No production change after full tests.
- Empty, malformed, non-object and truncated final answers remain failures even
  when another provider field contains valid JSON. Failed attempts remain spent
  and are not automatically repeated. Successful parsing does not publish content.

## Deployment and remaining boundaries

Not deployed. Exact-head independent Grok review and Spencer's exact merge/live
authorization remain required. No scheduler, model installation, roster, database
schema or app change is part of this patch.

The correction applies to future eligible calls. Existing failed candidate rows
and reservations remain untouched and will **not automatically retry on deployment**.
Controlled recovery of those attempts is separate; do not delete history, reset a
ledger or fake a new model identity to force replay. The hourly pilot still has
two static permitted pages on weekly refresh, not continuous source discovery.
WEL-50 remains open for operational acceptance; this patch proves the response
boundary on two saved sources, not all-source reliability or useful card delivery.
