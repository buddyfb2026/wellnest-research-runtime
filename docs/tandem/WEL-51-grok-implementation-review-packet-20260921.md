# WEL-51 — Grok implementation review packet (2026-09-21)

## FOCUS GATE

Named scope: WEL-51 retained, versioned cross-source research knowledge implementation.

Required output: an independent implementation-merits verdict against the binding design and Stan clarification, including any concrete violated invariant or failed oracle.

Explicitly out of scope: implementing fixes, editing any file, WEL-52 product work, WEL-53, external handoff execution, network access, live databases, publication, deployment, commit, push, merge, or adjacent refactoring.

Permitted issue changes: none.

Verification required: read both binding documents completely; inspect every changed and new file; perform the six review passes below; adversarially verify the test oracles; personally execute the focused and portable commands below.

Do not investigate or act on adjacent findings. Report them in one sentence as PARKED FINDING. Stop when the required output is complete.

## Immutable inputs

- Frozen repository baseline: `08eb06b4fc634c2bb7e9b5240a632fe84a6157f4`.
- Isolated implementation worktree: `/private/tmp/wel51-builder.t9zyYE`.
- Binding design: `/Users/buddystudio1/Projects/wellnest-research-runtime-wel51-53-design-20260921/docs/tandem/WEL-51-design-fable-v3.md`.
- Binding design SHA-256: `c9643a14a61581864bb0b96028c8581f01712ab37634523aead6201c09871279`.
- Binding clarification: `/Users/buddystudio1/Projects/wellnest-research-runtime-wel51-53-design-20260921/docs/tandem/WEL-51-backup-expected-count-STAN-CONFIRM-20260921.md`.
- Clarification SHA-256: `ce12057044237d6fe6c803693b2f330f7b727d291a91d6feccef1f764e844eb4`.
- Consensus state: binding Fable v3; fresh Astra verdict `NO OBJECTIONS` at 2026-09-21T19:37:53Z; Stan clarification resolves only the backup expected-count ambiguity.

The worktree has no commit. Review its working-tree state directly. Do not edit it.

## Changed paths

Tracked modifications:

- `research/db.py`
- `research/report.py`
- `tests/test_wel50_backup.py`
- `tests/wel52_helpers.py`

New paths:

- `research/knowledge.py`
- `eval/wel51/fixtures/syndicated-duplicate.json`
- `eval/wel51/corpus/manifest.json`
- `tests/wel51_helpers.py`
- `tests/test_wel51_knowledge.py`
- `tests/test_wel51_replay.py`

No other implementation path is changed. `git diff --check` passes, and the changed Python files compile.

## Review passes

1. **Brief and scope drift:** compare every changed path and behavior to the two immutable inputs; reject any mechanism or incumbent edit not authorized there.
2. **Migration and durability:** verify migration 8 verbatim, keys/FKs/checks/uniqueness, partial migration recovery, transaction boundaries, crash hooks, and exact backup counts.
3. **Evidence semantics:** verify current-recipe/current-evidence eligibility, literal-span checks, absence versus stated-total classification, provenance, immutable link history, digest/version behavior, and no invented inference.
4. **Rights and follow-up:** verify five target predicates, root independence, exact one-follow-up contract, stored-versus-current view separation, seven statuses, fail-closed stale/unreadable behavior, and that no follow-up is executed.
5. **Replay and oracles:** independently challenge idempotency, A→B→A versioning, deduplication, rejection/deferred review semantics, unknown-rule refusal, and each named test's ability to discriminate a broken implementation. Tests that merely record behavior are defects.
6. **Integration and degradation:** verify empty-store report byte identity, placement before inference usage, CLI locking/error behavior, default-off structure, no worker integration, and absence of fetch/model/publication/network/live-store behavior.

## Commands and builder evidence

Run from `/private/tmp/wel51-builder.t9zyYE` with the installed local dependencies.

Focused affected suite:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q -p no:cacheprovider \
  tests/test_wel51_knowledge.py tests/test_wel51_replay.py tests/test_wel50_backup.py
```

Builder result: `36 passed in 1.71s`.

Binding portable suite:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q -p no:cacheprovider \
  tests/test_wel51_knowledge.py tests/test_wel51_replay.py \
  tests/test_wel48_literal_corrections.py tests/test_wel48_semantics.py tests/test_wel48_migration.py \
  tests/test_wel48_manifest.py \
  --deselect tests/test_wel48_manifest.py::test_ambiguous_correspondence_is_incomplete \
  --deselect tests/test_wel48_semantics.py::test_all_six_saved_response_semantic_inventories_are_reported \
  tests/test_wel49.py tests/test_wel50_backup.py \
  tests/test_wel52_review.py tests/test_wel52_pack.py
```

Builder result: `179 passed, 2 failed, 2 deselected in 4.06s`.

The two failures are pre-existing frozen-baseline defects, not WEL-51 deltas:

- `tests/test_wel48_manifest.py::test_locator_bump_without_recollection_is_a_noop`
- `tests/test_wel48_manifest.py::test_locator_bump_applies_on_next_collection`

Both tests assume incumbent `LOCATOR_VERSION == "wel48_locator_v5"`, but frozen baseline `08eb06b` already contains `wel48_locator_v6`. The builder reproduced both failures unchanged in the untouched baseline worktree before this review packet. Excluding those two historical nodes in addition to the two binding historical-input deselections yields `179 passed, 4 deselected`.

## Evidence deliberately not claimed

- The six WEL-48 historical-input tests identified in binding design §6.2 are `NOT VERIFIED — BLOCKED`; their original frozen `/tmp` inputs are absent. They were not fabricated, regenerated, fetched, or stubbed.
- `tests/test_wel52_handoff.py::test_real_producer_consumer_two_then_three` is `NOT VERIFIED`. Its four external prerequisites remain H1 `WELLNEST_APP_DIR`, H2 `scripts/wel52-consume.mts`, H3 local `node_modules/tsx`, and H4 a Node executable. The consumer repository was not inspected or changed for WEL-51.
- No broad-suite, external-runtime, production-readiness, deployment, or live-data claim is made.

## Required verdict

Return exactly one of:

- `APPROVE — implementation conforms to the binding WEL-51 brief and clarification; test oracles are adversarially adequate.`
- `BLOCK — <numbered concrete defects, each naming the violated binding section/invariant and a discriminating test or required correction>.`

Do not approve, merge, commit, push, or modify the worktree. This is merits review only.
