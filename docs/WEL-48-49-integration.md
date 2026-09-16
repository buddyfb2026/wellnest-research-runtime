# WEL-48 / WEL-49 combined candidate

This is an isolated offline integration of the two reviewed implementations, not deployment or issue completion. Original WEL-48 and WEL-49 worktrees are unchanged. Both inputs are based on `2b7602f42856ce34c6a18c810f7181bca418bd6f`.

## Integration choices

- Retain migration 5 exactly, then migration 6 exactly. The migration loader is unchanged.
- Retain the recipe work block and the source-registry/reporting block in the worker, including both sets of counters, request guards, crash hooks, and prior-attempt separation. No new processing mechanism.
- Preserve the source registry file byte-for-byte. It is still a denial/reporting registry, not a collection grant.
- Combine allowlist entries by exact URL, retaining both distinct historical no-fetch recipe URLs from WEL-48. Cookie and Kate's exact root URL had conflicting `fetch` settings; retain **one entry with fetch=false**, mark an integration hold, and preserve both prior policies as audit context. No source access was expanded. This hold is not a legal judgment or permanent rejection of that publisher.
- Current allowlist: **18 unique URLs, 13 fetch=true**. The declared roster working set still has 10 URLs; 9 have collection flags, across 6 roots. Declared priority is not proof of collectability or full-recipe reuse permission. NHLBI Pita and Rice remain first and retain their recorded text-only use constraints.
- Keep migration-5-specific tests genuinely scoped to historical versions 1–5; separately test the real 1–6 list from fresh, version-4 and version-5 stores. No skipped-migration workaround.

## Builder evidence

```
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_wel48_wel49_integration.py tests/test_wel48_migration.py tests/test_wel49.py tests/test_wel48_meal_binding.py -q -p no:cacheprovider
120 passed

PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests -q -p no:cacheprovider
398 passed

git diff --check
clean
```

Five new integration cases cover fresh/4→6/5→6 migrations preserving historical evidence; manual and scheduled worker paths with both recipe extraction enabled and a denied source present; real temporary SQLite; an injected ordinary model HTTP response rather than a locator-generated recipe answer; ingredient source-span retention; stated times; publisher identity; no denied-source requests; pending/unpublished recipe state; and reopen/replay with no duplicate versions or model calls.

These tests use synthetic sources and a stubbed model boundary, with network disabled. The separate genuine Qwen Pita/Rice results are prior WEL-48 evidence, not a claim of new inference through the combined runtime. No model calls, source fetches or canonical-ledger migrations occurred during integration.

## Remaining boundaries

Independent review of the integration delta is required before claiming this candidate reviewed. Broader real family-recipe publisher coverage, controlled activation, continuous-run observation, editorial approval and app-side delivery are still separate work. Cookie and Kate's integration hold must be explicitly reconciled against the intended use before any future activation of that entry. Source metadata does not itself grant inference or app reuse rights. No automatic publication or production readiness is claimed.
