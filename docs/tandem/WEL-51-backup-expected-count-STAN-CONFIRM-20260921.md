# WEL-51 — backup-test expected-count correction (Stan confirm, 2026-09-21)

## Confirm (binding)

When **migration 8** lands (WEL-51 graph tables), update the incumbent backup pin as follows — nothing softer:

1. `tests/test_wel50_backup.py`
   - `EXPECTED_COUNTS["schema_version"]`: **7 → 8**
   - Add these **new empty tables** created by migration 8, each with count **0**:
     - `findings`: **0**
     - `finding_links`: **0**
     - `finding_versions`: **0**
   - Keep every other exact table count assertion unchanged.
   - Keep exact equality asserts: `res["tables"] == EXPECTED_COUNTS` (do **not** weaken to subset/superset).
   - Keep `MAX(version) FROM schema_version == 8` wherever the file currently pins `== 7`.

2. `tests/wel52_helpers.py` schema pin **7 → 8** (same change set).

## Preserve

- Exact assertion style (full dict equality).
- No redesign of backup/restore behavior.
- No change to WEL-53 (already Claude-reviewed; Astra packaging) — WEL-53 adds **no** migration 8.

## Not authorized here

Implementing migration 8 itself. This note only confirms the **necessary expected-count correction**.
