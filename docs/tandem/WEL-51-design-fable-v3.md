# WEL-51 — Tandem Design v3 (Fable 5.1 author, portable-gate correction after Astra critique of v2)

**Reusable research knowledge and one bounded cross-source investigation.**

Frozen worktree `08eb06b4fc634c2bb7e9b5240a632fe84a6157f4`; repository claims cite `path:line` in that tree. Authoring only: nothing here is implemented or executed. Replaces `WEL-51-design-fable-v2.md` (preserved unmodified); self-contained. Changes from v1 are marked **[v2]**; the single correction from v2 (the §6.1 gate and the new §6.2a) is marked **[v3]**; dispositions are in `WEL-51-fable-v2-adopt-rebut.md` and `WEL-51-fable-v3-adopt-rebut.md`.

## 1. Problem and objective

The store links one statement to one page: `candidates.evidence_id` (`research/db.py:86`) and `recipe_versions.evidence_id` (`research/db.py:199`) are single-valued. Nothing can say "this finding rests on these documents, and that one qualifies it". `independent_publishers()` counts roots over *every* evidence URL (`research/source_registry.py:204-213`), so it cannot answer for one finding and cannot notice two surfaces carrying the same article.

**Objective (smallest slice).** One retained, versioned *finding* with many-to-many links to recipe/evidence versions (`supports`, `qualifies_or_contradicts`); per-finding independent-source accounting in which same content or same owner never counts twice; a contradiction/qualification that forces a visible pending decision; and exactly one recorded follow-up proposal per finding version that is **never executed** here. **[v2]** The recorded follow-up is a *historical proposal*; whether it may be acted on is a separate *current eligibility view* recomputed from the store at every read (§3.4). Output answers: what we know / why we believe it / what remains uncertain / what to investigate next.

**Named consumer of everything stored:** a `## Retained knowledge` section in `render()` (`research/report.py:112-213`), written by `python3 -m research.worker report` (`research/worker.py:501-509`).

**Non-objectives.** No graph platform, vector store, service, agent, scheduler, visualisation; no household data; no fetch, no model call, no publication (`recipe_publications` is written only by the human act in `research/recipe_review.py:121-139`); no worker-cycle integration (§3.0).

## 2. Repo facts and constraints

| # | Fact | Citation |
|---|---|---|
| F1 | Isolated SQLite store, never an app database | `research/db.py:1-3`, `research/config.py:7` |
| F2 | `MIGRATIONS` is ordered; highest version is 7 | `research/db.py:9`, `:163-166`, `:238-239`, `:255-283` |
| F3 | `migrate()` skips `version <= current`, applies statements one at a time, tolerates only `duplicate column`, then records the version | `research/db.py:297-320` |
| F4 | `connect()` uses explicit transactions and `PRAGMA foreign_keys = ON` | `research/db.py:291-293` |
| F5 | Two tracked tests pin schema version 7 and will fail once a migration 8 exists | `tests/wel52_helpers.py:19`, `tests/test_wel50_backup.py:157` |
| F6 | `evidence` is append-only, `UNIQUE(url, content_hash)`; changed content is version N+1 with `supersedes_id` | `research/db.py:43-65`, `research/evidence.py:43-72` |
| F7 | `content_hash` = sha256 of extracted text | `research/extract.py:156` |
| F8 | `recipe_versions`: FK to `evidence`, `UNIQUE(recipe_id, version_no)`, `content_fingerprint`, `unknown_fields`, `state`, `state_set_by` | `research/db.py:196-223` |
| F8a | **[v2]** `content_fingerprint` = sha256 of `canonical_json(content)`, and `content` embeds the store-local `evidence_id` (twice) and `checked_at` = `evidence.fetched_at`. It is therefore **not** a cross-store identity | `research/recipes.py:105-106`; `research/recipe_extract.py:238`, `:243`, `:246` |
| F9 | A worker budget-placeholder version can be rewritten in place while `state_set_by='worker'`; a version id alone is not content-stable | `research/recipes.py:94-96`, `:132-146` |
| F9a | `resolve_current(conn, recipe_id)` selects the version whose `manifest_hash` equals the evidence's `evidence_current_manifest` pointer; after manifests A→B→A it returns the original A version | `research/recipes.py:172-179`, `:47-53`; oracle `tests/test_wel48_manifest.py:62-78` |
| F9b | Work is rediscovered from the latest evidence version per URL plus that pointer | `research/recipes.py:149-158` |
| F10 | `canonical_json` is the incumbent hashing input; `ensure_recipe` is the identity-before-create pattern | `research/recipes.py:14-15`, `:76-87` |
| F11 | WEL-48 `bind` decides total-time absence: `total_time.value is None` with unknown `("total_time","not_stated_by_source")`; stated scalars carry a verbatim `source` literal and span | `research/recipe_extract.py:124-126`, `tests/test_wel48_literal_corrections.py:103-115` |
| F12 | `publishers(parent_publisher)` / `source_surfaces(url PK, publisher_id)`; `resolve()` walks to `root_publisher_id`, all-`None` for an unknown URL | `research/db.py:239-250`, `research/source_registry.py:189-201` |
| F13 | `effective_denied()`: a known surface not (`permitted` AND `retain`) is denied, returning a reason string; `project()` is a whole-file atomic upsert that never deletes omitted rows | `research/source_registry.py:181-186`, `:132-163` |
| F13a | **[v2]** Closed vocabularies: `roster_status ∈ {retain, replace, defer, candidate}`, `access_status ∈ {permitted, hint_only, denied, unknown}`; `working_set` only requires declared URLs, not permitted ones | `research/source_registry.py:76-79`, `:108-112` |
| F14 | Closed topic vocabulary includes `recipe_supply` | `research/source_registry.py:14-15` |
| F15 | One writer per store (non-blocking `flock`); worker and `recipe_review` lock then migrate on entry | `research/lock.py:19-40`, `research/worker.py:100-110`, `research/recipe_review.py:137-143` |
| F16 | Human authority convention: `by` must start with `human:` | `research/recipe_review.py:133-134` |
| F17 | The only request gate and the persisted caps already exist; this slice calls neither | `research/fetch.py:155-172`, `research/config.py:14-16` |
| F18 | `render(conn, run_id, now)` composes sections; the report file is a plain non-atomic `write_text` | `research/report.py:112-122`, `:209`, `research/worker.py:398-427` |
| F19 | Crash-injection pattern: `crash_hook(point)` + `SimulatedCrash` + exact count tuples | `tests/test_wel48_replay.py:44-52`, `:126-131`, `research/recipe_extract.py:361-362`, `:375-376` |
| F20 | Network refused in every test not marked `local_http` | `tests/conftest.py:102-114`, `pytest.ini:1-3` |
| F21 | **[v2]** Six tracked tests depend on historical inputs under `/tmp` with no skip guard — five directly, one transitively: the four tests of `tests/test_wel48_corpus.py` (paths `:10-12`, tests `:56`, `:66`, `:73`, `:79`) and `tests/test_wel48_manifest.py::test_ambiguous_correspondence_is_incomplete` (`:134`), which read the paths themselves; and `tests/test_wel48_semantics.py::test_all_six_saved_response_semantic_inventories_are_reported`, which imports `_saved_replay` from `tests.test_wel48_corpus` (`tests/test_wel48_semantics.py:4`) and calls it (`:22-23`), reading `BAKEOFF` and the raw corpus (`tests/test_wel48_corpus.py:39-43`). The other two semantics tests (`:7`, `:15`) read only in-repo files, and importing the corpus module reads nothing at import time (`:9-12` are path constants). On 2026-09-21 the directories `/tmp/wel48-coordination/corpus/raw`, `/tmp/wel48-coordination/model-bakeoff`, `/tmp/wel42-coordination/evidence-raw` exist and are empty. `tests/test_meal_export.py:358-365` also names a `/tmp` DB but skips when absent. A `/tmp` grep over `tests/*.py` hits only `test_wel48_corpus.py`, `test_wel48_manifest.py`, `test_meal_export.py`; a grep for importers of those modules' helpers (`test_wel48_corpus`, `_saved_replay`) hits only `test_wel48_semantics.py` | as cited |

**Corpus facts.**

| # | Artifact | Verified content | Citation |
|---|---|---|---|
| C1 | operating literal rec. 2 (casserole) | `publicdomainrecipes.com/easy-chicken-and-rice-casserole/`, hash `06ef9508…c447`; prep `5`, cook `40`, `total_minutes.value null` | `eval/wel48/fixtures/operating-recipe-literals.json:49-52`, `:76-87` |
| C2 | operating literal rec. 1 (orzo) | `fossrecipes.com/recipes/orzo-chicken`, hash `52366a25…52f1`; servings/prep/cook/total all `null` | same file `:3-6`, `:29-44` |
| C3 | Both texts hash to their recorded `content_hash`, and real `bind` on them yields the F11 unknown | `tests/test_wel48_literal_corrections.py:67-70`, `:90-108`, `:118-126` |
| C4 | The two publishers are distinct roots; both surfaces `retain` + `permitted`, topic `recipe_supply` | `sources/roster.json:142-158`, `:563-571`, `:580-588` |
| C5 | WEL-52 seed `f-a` states `Total Time: 20 minutes`, span-bound, on off-roster `fixture.example` | `tests/fixtures/wel52/f-a.json:6`, `tests/wel52_helpers.py:34-37`, `:64-65` |
| C6 | **[v2]** The tracked roster (25 surfaces, 17 publishers) has five `site_article` + `recipe_supply` surfaces; in `url` order: orzo (C2), casserole (C1), budgetbytes (`hint_only`), NHLBI `…/pita-pizzas`, NHLBI `…/wiki-fast-rice` (both `retain` + `permitted`, root `nhlbi`). NHLBI's "states no total time" is roster prose, not stored evidence | `sources/roster.json:171-179`; enumeration by reading the tracked file this session |
| C7 | Fixture-label contract `"label":"fixture"`, `"live_coverage":false` | `eval/wel48/fixtures/ingredient-conflict.json:4-5`, `tests/test_wel48_semantics.py:15-19` |
| C8 | **Gap:** no source-level duplicate exists in the tree | `eval/wel43/dev_cases.json:61-65` |
| C9 | WEL-48 six-record corpus reads raw bytes from `/tmp`; not portable, not used (F21) | `tests/test_wel48_corpus.py:9-12`, `:23-25` |

## 3. Approach and data model

### 3.0 Shape decisions (each removes mechanism)

| Decision | Reason |
|---|---|
| **3 tables, 0 extra indexes**; the follow-up is two `NOT NULL` columns on the version row | *exactly one* follow-up per version by construction; UNIQUE constraints already index the only lookups |
| **No worker or config change.** Own entry point `python3 -m research.knowledge`, shaped like `recipe_review` (F15) | synthesis needs no fetch, model or cycle state; default-off is structural |
| Absence is **`inferred`** by a named rule over WEL-48's own unknown (F11); only a stated total is `observed` | an absent literal has no span |
| Composite natural link key; publisher roots resolved at synthesis and snapshotted on the version, inside the digest | a later roster correction must invalidate the version. **[v2]** v1's "digest reproduces across stores" claim is withdrawn (F8a, S5) |
| **Connected components** over {same content hash, same root}; the mirror gets a *different* synthetic root | no tie-break; oracle proves the hash path: distinct roots `3`, independent `2` |
| Compare to the **latest** version's digest, not `UNIQUE(digest)` | A→B→A must append a new pending version, not resurrect A's approval |
| **[v2]** Follow-up decision inputs stay **out** of the support digest; eligibility is recomputed at read (§3.4) | putting roster permission into the digest would void human approvals of the *finding* for reasons unrelated to its support, and would still serve a stale follow-up until an operator re-ran synthesis. Read-time recomputation closes the gap with zero writes |

### 3.1 Rule (the only one) — `wel51_total_time_v1`

Finding: topic `recipe_supply` (F14), `claim_slug` `total-time-not-stated-by-source`, claim text fixed in code: *"A source-backed recipe may omit an explicit total time; where it is absent, no total is derived."*

**Current recipe version.** For each `recipes` row the only candidate is `resolve_current(conn, recipe_id)` (F9a). It is *eligible* iff not `None`, `state != 'rejected'`, not a budget placeholder (F9), `completeness != 'failed'`, and its `evidence_id` is the latest evidence version for its URL (F9b).

| Document condition (from `recipe_versions.content` / `unknown_fields`) | Link | Basis and `basis_detail` |
|---|---|---|
| `times.total_time.value is None` AND unknown `{field:"total_time", reason:"not_stated_by_source"}` | `supports` | `inferred`: `{rule, unknown:{field,reason}, stated:[{field, literal, span}…]}` — `stated` carries verbatim prep/cook literals, never summed |
| `times.total_time` carries a `source` literal + span | `qualifies_or_contradicts` | `observed`: `{field, literal, span}` |
| any other total-time unknown | none | L6 |

Every literal/span is re-checked `evidence_text[start:end] == literal` before insert; a mismatch writes no link and reports a failure. No value is computed, averaged or filled.

### 3.2 Hard part — identity, replay, version invalidation

- **S1 Finding identity.** `finding_key = sha256(topic + "|" + claim_slug)`, `UNIQUE`; `INSERT OR IGNORE` then select (F10).
- **S2 Link identity.** `UNIQUE(finding_id, recipe_version_id, content_fingerprint, rule)`, `INSERT OR IGNORE`. Links are never updated or deleted; a newly current recipe version yields a new link beside the old one; A→B→A re-livens the existing link.
- **S3 Live links.** Live iff its `recipe_version_id` is the eligible `resolve_current` row **and** the link's `content_fingerprint` equals that row's present one (F9). Computed at read time.
- **S4 Independent accounting** (pure function of live `supports` links + WEL-49 tables): (1) `root = resolve(evidence.url)["root_publisher_id"]`; `None` → `unattributed_supports`, excluded; (2) union links sharing `evidence_content_hash` **or** `root`; (3) `independent_publisher_count` = components; `components` = sorted lists of sorted roots; `distinct_roots` diagnostic. Order-independent, can only under-count.
- **S5 Support digest.** `sha256(canonical_json({rule, links: sorted([url, evidence_content_hash, content_fingerprint, relation, root_or_null] for live links)}))`. No rowids or timestamps are added by WEL-51. **[v2] Determinism scope:** because `content_fingerprint` already encodes store-local evidence ids and fetch time (F8a), the digest, `statement` and all §6 outputs are claimed deterministic **only for an identical frozen store snapshot and identical inputs** (same rows, same roster projection, same code). Two stores that collected the same pages independently are *not* claimed to produce equal digests; the repository offers no evidence for more.
- **S6 Version append.** No version, or latest `support_digest` differs ⇒ append `version_no = prior+1`, `supersedes_id`, `state='pending'`, `state_set_by='worker'`, with `statement` and follow-up. Equal digest ⇒ **zero writes** (unchanged; made safe by §3.4 S11).
- **S7 Approval is never inherited.** The synthesiser only INSERTs versions. The sole UPDATE is `knowledge.review`, requiring `by` starting `human:` (F16), on one version id.
- **S8 Contradiction.** Any live qualifier ⇒ `unresolved` non-empty ⇒ rendered with both literals. No vote; no worker-written state other than `pending`.
- **S9 Atomicity.** Per finding, one `BEGIN … COMMIT` covers finding row, new links, version row. Hooks: `before_knowledge_commit`, `after_knowledge_commit` (F19).
- **S10 Not protected.** Paraphrased syndication; editorial independence beyond WEL-49 roots; correctness of WEL-48's unknown; the report file (F18); cross-store equality (S5).

### 3.3 Schema — one additive migration (8), list form, three tables

```sql
CREATE TABLE IF NOT EXISTS findings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  finding_key TEXT NOT NULL UNIQUE,
  topic TEXT NOT NULL, claim_slug TEXT NOT NULL, created_at TEXT NOT NULL,
  UNIQUE(topic, claim_slug));

CREATE TABLE IF NOT EXISTS finding_links (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  finding_id INTEGER NOT NULL REFERENCES findings(id),
  relation TEXT NOT NULL CHECK (relation IN ('supports','qualifies_or_contradicts')),
  evidence_id INTEGER NOT NULL REFERENCES evidence(id),
  evidence_content_hash TEXT NOT NULL,
  recipe_version_id INTEGER NOT NULL REFERENCES recipe_versions(id),
  content_fingerprint TEXT NOT NULL,
  basis TEXT NOT NULL CHECK (basis IN ('observed','inferred')),
  basis_detail TEXT NOT NULL,
  rule TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  UNIQUE(finding_id, recipe_version_id, content_fingerprint, rule));

CREATE TABLE IF NOT EXISTS finding_versions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  finding_id INTEGER NOT NULL REFERENCES findings(id),
  version_no INTEGER NOT NULL,
  supersedes_id INTEGER REFERENCES finding_versions(id),
  support_digest TEXT NOT NULL,
  rule TEXT NOT NULL,
  statement TEXT NOT NULL,           -- canonical_json snapshot: claim, per-link url/hash/root/basis_detail, S4 result
  unresolved TEXT NOT NULL,          -- JSON list; S8
  followup_state TEXT NOT NULL CHECK (followup_state IN ('none','proposed','refused')),  -- HISTORICAL, as of created_at
  followup TEXT NOT NULL,            -- canonical_json, §3.4; HISTORICAL, never an instruction
  state TEXT NOT NULL,               -- pending | approved | rejected | deferred
  state_reason TEXT, state_set_by TEXT NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  UNIQUE(finding_id, version_no));
```

**[v2]** No column is added relative to v1; the change is the content contract of `followup` and who may read it (§3.4).

| Relationship | Stored as | Consumer (report heading) |
|---|---|---|
| publisher → surface | not duplicated: WEL-49 tables joined on `evidence.url` (F12) | "Why we believe it"; S4 |
| surface → evidence version → recipe version | incumbent `evidence.url`, `recipe_versions.evidence_id` | "Why" columns |
| version `supports` finding | `finding_links` | "Why we believe it" + independent count |
| version `qualifies_or_contradicts` finding | `finding_links` | "What remains uncertain" |
| finding version supersedes finding version | `supersedes_id` | history line |
| finding version → one follow-up | `followup_state`, `followup` | "What to investigate next", via `current_followup` only |

No FK to `source_surfaces`: an off-roster document (C5) must be storable and is simply unattributed.

### 3.4 The one follow-up — historical proposal + current eligibility view **[v2]**

**Target predicates** (one code function `target_ok(conn, url, topic, supporting_roots) -> list[str]` returning failure reasons; empty = passes):

| # | Predicate | Failure reason string |
|---|---|---|
| P1 | `source_surfaces` row exists with `surface_kind='site_article'` | `target surface absent or not site_article` |
| P2 | its `topics` contains the finding topic | `target topic no longer includes <topic>` |
| P3 | `effective_denied(conn, url) is None` (F13) | the `effective_denied` string verbatim |
| P4 | no `evidence` row has that `url` | `evidence now exists for target` |
| P5 | `resolve(url)["root_publisher_id"]` not in the finding's current supporting roots | `target root now among supporting roots` |

**Selection** `select_followup(conn, finding_id)`: `unresolved` empty ⇒ `none`. Otherwise all `source_surfaces` rows ordered by `url`; first with `target_ok == []` ⇒ `proposed`; none ⇒ `refused`, reason `no permitted uncollected surface for topic <topic>`. `bounds` is a code constant `{"max_depth":1,"max_pages":1,"max_model_calls":1,"deadline_at": created_at + 7d}`; the question is a code template. No model text enters any field.

**Durable fields (written once at S6, never updated).** `followup_state` and `followup` = `canonical_json` of exactly:

```
{"question": str, "target_surface_url": str|null, "bounds": {...}, "reason": str|null,
 "decision_inputs": {"topic": str, "supporting_roots": [str…],
                     "target": null | {"url","surface_kind","topics","roster_status","access_status",
                                        "root_publisher_id","evidence_rows": 0}}}
```

`decision_inputs` records what the decision saw, so the report can show *what changed*; it is explanation, never re-used as truth.

- **S11 Sole reader and current view.** `knowledge.current_followup(conn, version_row) -> dict` is the **only** function that reads `followup_state`/`followup`; `render_knowledge` calls it and never reads those columns itself. It is read-only and returns `{status, recorded, withdrawn_reasons, actionable_target_url}`:

| Order | Condition (evaluated now, on the current store) | `status` | `actionable_target_url` |
|---|---|---|---|
| 0 | stored `followup` does not parse to exactly the durable-field contract above (newer/older writer) | `unreadable` | `null` |
| 1 | recomputed S5 digest `!=` `version.support_digest` | `stale_version` | `null` |
| 2 | stored `none` | `none` | `null` |
| 3 | stored `proposed`, `target_ok(stored target) == []` | `eligible` | stored target |
| 4 | stored `proposed`, reasons non-empty | `withdrawn` (+ `withdrawn_reasons`) | `null` |
| 5 | stored `refused`, `select_followup` now yields a target | `newly_eligible` | that target |
| 6 | stored `refused`, still none | `refused` | `null` |

  `actionable_target_url` is non-null **only** for `eligible`/`newly_eligible`; it is the single value any reader may treat as a candidate, and it is derived, never stored. A withdrawn proposal is not silently replaced by the next surface: replacement happens only when the support changes and S6 appends a version. This keeps *exactly one* follow-up per version.
- **Rendering.** "What to investigate next" prints three lines: `Recorded proposal (historical, v<N>, <created_at>): <question> → <url>`; `Current eligibility (computed <now>): <status>[: reasons]`; `Actionable target: <url|none> — not executed`.
- **Never executed.** `research/knowledge.py` imports neither `fetch` nor `model`; nothing schedules from any of this. The only way a follow-up is answered is the incumbent human-timed WEL-49 cycle under F17. *Not protected:* a future executor must call `current_followup` immediately before acting, under the store lock, and re-argue the bounds (L4, L9).

### 3.5 Entry points

`python3 -m research.knowledge synthesize --db PATH` and `… review VERSION_ID {approved,rejected,deferred} --by human:NAME --reason TEXT --db PATH`. Both: `StoreLock` → `db.migrate` → work (F15); busy lock exits non-zero having written nothing. Reading is `render_knowledge(conn, now)` called from `render()` immediately before `## Inference usage` (`research/report.py:209`); it renders the latest version's stored `statement`, the history line and the S11 view, and returns `[]` when `findings` is empty, so an unsynthesised store yields a byte-identical incumbent report.

## 4. Files in and out

| In | Change |
|---|---|
| `research/db.py` | append `(8, [three CREATE TABLE statements])` after `:283` |
| `research/knowledge.py` | **new**: rule, S1–S11, `independent_support()`, `target_ok()`, `select_followup()`, `current_followup()`, `synthesize()`, `review()`, `main()` |
| `research/report.py` | `render_knowledge()` + one call before `:209` |
| `tests/wel52_helpers.py:19`, `tests/test_wel50_backup.py:157` | schema pin `7` → `8` (F5); no other incumbent test edit |
| `eval/wel51/fixtures/syndicated-duplicate.json` | **new synthetic fixture** (E3): `label`, `live_coverage:false`, mirror URL, one publisher + one surface row (§6.4.1), *hash reference* to C1 |
| `eval/wel51/corpus/manifest.json` | **new**: edge ids, source file + content hash per edge, expected §6.4 values |
| `tests/wel51_helpers.py`, `tests/test_wel51_knowledge.py`, `tests/test_wel51_replay.py` | **new** (§6) |

| Out | Reason |
|---|---|
| `research/worker.py`, `research/config.py` | no cycle integration, no flag |
| Any incumbent table/column; `research/recipes.py`, `recipe_extract.py`, `source_registry.py` | upstream contracts are read, not changed |
| `research/fetch.py`, `discovery.py`, `model.py`, `inference_calls` | no collection, no inference |
| `research/recipe_review.py`, `recipe_pack.py`, `recipe_publications` | WEL-52 boundary untouched |
| `sources/roster.json`, `sources/allowlist.json` | fixture rows and permission flips exist only in test-projected in-memory rosters |
| launchd/cron/scheduler artifacts; graph/vector/service components | no activation; no platform |
| `/tmp` WEL-48/WEL-42 historical inputs; `tests/test_wel48_corpus.py`, `tests/test_wel48_manifest.py`, `tests/test_wel48_semantics.py` | absent (F21); not regenerated, not edited, not skipped-by-edit |

## 5. Failure design

**There is no remote write in this slice**: no HTTP request, remote store, message or external service. Durable boundaries are the local SQLite store and the local report file only.

### 5(a) Crash-boundary oracle — 4 boundaries

Subject: `knowledge.synthesize(db_path, crash_hook=…)` on the §6.4 store. Tuple `T = (findings, finding_links, finding_versions)`.

| # | Boundary | Tuple | Report file | Rerun |
|---|---|---|---|---|
| M1 | **test-simulated** interruption of migration 8: the test executes only statement 1 on a store at 7, no `schema_version` row. No production hook in `db.migrate` | WEL-51 tables `== 1`, `MAX(version) == 7` | n/a | `db.migrate(conn) == 8`; tables `== 3`; version-8 rows `== 1` |
| K1 | `before_knowledge_commit` | `(0, 0, 0)` | unchanged | `(1, 4, 1)` |
| K2 | `after_knowledge_commit` | `(1, 4, 1)` | unchanged/stale | zero inserts |
| R1 | store committed, report absent or torn (F18) | `(1, 4, 1)` | absent | `worker report` rewrites it; eligibility is recomputed at that render |

`review` is a single-row UPDATE; `current_followup` writes nothing, so it adds no boundary.

### 5(b) Death-to-disposition map

| Failure | Disposition | Named test |
|---|---|---|
| Migration interrupted (simulated) | re-runnable list form (F3) | `test_m1_migration_8_rerunnable` |
| Fixture roster rows malformed | real `validate` raises inside `project`; rollback | `test_fixture_roster_passes_real_validate` |
| Crash before COMMIT | nothing durable | `test_k1_crash_before_commit` |
| Crash after COMMIT / replay | zero writes | `test_k2_replay_inserts_nothing` |
| Report missing or torn | regenerate from store | `test_r1_report_regenerates` |
| Store lock held elsewhere | refuse, write nothing | `test_locked_store_writes_nothing` |
| Same article under a second surface and owner | one component | `test_duplicate_adds_zero_independent` |
| Off-roster `supports` document | listed, never counted | `test_unattributed_support_not_counted` |
| Qualifier present | pending + both literals, no vote | `test_qualifier_forces_unresolved` |
| Support changes after approval | new pending version | `test_changed_support_does_not_inherit_approval` |
| Roster records mirror as child of original | new pending version | `test_roster_change_invalidates_version` |
| Manifest A→B→A | appended pending version | `test_digest_return_appends_pending` |
| Literal/span mismatch | no link, failure reported | `test_span_mismatch_writes_no_link` |
| Non-human reviewer | refused, row unchanged | `test_review_requires_human` |
| No permitted uncollected target | `refused` with reason | `test_followup_refused_without_target` |
| Closed vocabulary violated | `sqlite3.IntegrityError` | `test_relation_vocabulary_is_closed` |
| Latest version has unknown `rule` | read-only; synthesis refuses | `test_unknown_rule_is_read_only` |
| **[v2]** Target permission withdrawn, support unchanged | stored proposal kept as history; view `withdrawn`; nothing actionable | `test_followup_permitted_to_withdrawn_no_support_change` |
| **[v2]** Target permission granted after a `refused`, support unchanged | stored `refused` kept; view `newly_eligible` | `test_followup_withdrawn_to_permitted_no_support_change` |
| **[v2]** Evidence appears for the target without any new recipe version | view `withdrawn` | `test_followup_evidence_availability_withdraws` |
| **[v2]** Support changed but synthesis not re-run | view `stale_version`; nothing actionable | `test_followup_stale_version_not_actionable` |

### 5(c) Accepted-limitations register

| # | Limitation | Why accepted |
|---|---|---|
| L1 | Paraphrased syndication counts as independent | needs similarity; out of slice; report says so |
| L2 | "Independent" = distinct WEL-49 root | WEL-49 owns identity; S4 under-counts |
| L3 | Synthesis is operator-invoked | keeps `worker.run` untouched |
| L4 | The follow-up is never executed by WEL-51; `bounds.deadline_at` binds only a future executor and is not part of the eligibility view | proposal only |
| L5 | Report replaced non-atomically | incumbent (F18) |
| L6 | One rule, one finding | one named consumer |
| L7 | Duplicate and qualifier are synthetic fixtures | tree has none (C8); labelled |
| L8 | Finding inherits any WEL-48 binding error | upstream contract |
| L9 | **[v2]** The eligibility view is true at render time only; a report *file* is a snapshot stamped `computed <now>` and can age. The "one reader" rule is a code contract with tests on its outputs, not a DB-enforced guard | no executor exists in this slice; a store trigger or lease would be new infrastructure |
| L10 | **[v2]** Determinism is per identical frozen store snapshot; cross-store digest/fingerprint equality is not claimed (F8a) | would require changing WEL-48's `content` shape, out of scope |

## 6. Runnable acceptance suites

None of the commands below was run in this session.

### 6.1 Portable local verification **[v2]** — the WEL-51 gate

Named files with two command-line deselects; no selected test depends on F21 inputs, by source reading (the `/tmp` grep and importer grep of F21). **[v3]** `tests/test_wel52_handoff.py` is not selected: it requires a second repository (§6.2a), so it is not self-contained.

```
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q -p no:cacheprovider \
  tests/test_wel51_knowledge.py tests/test_wel51_replay.py \
  tests/test_wel48_literal_corrections.py tests/test_wel48_semantics.py tests/test_wel48_migration.py \
  tests/test_wel48_manifest.py --deselect tests/test_wel48_manifest.py::test_ambiguous_correspondence_is_incomplete \
  --deselect tests/test_wel48_semantics.py::test_all_six_saved_response_semantic_inventories_are_reported \
  tests/test_wel49.py tests/test_wel50_backup.py \
  tests/test_wel52_review.py tests/test_wel52_pack.py
```

Why each incumbent file: binding used for seeding (C3); fixture-label contract (C7); migration pattern; the F9a A→B→A oracle; the WEL-49 registry; the two F5 pins (`test_wel50_backup.py` directly, the two WEL-52 files `tests/test_wel52_review.py` and `tests/test_wel52_pack.py` via `tests/wel52_helpers.py:19`). The first two files do not exist yet (proposed). Expected incumbent delta: only the two pin values change. `tests/test_wel48_semantics.py` stays selected for its two portable tests, in particular `test_missing_live_predicates_are_explicitly_fixture_only` (the C7 contract); only its saved-replay test is deselected. Both `--deselect`s are on the command line; no tracked test is edited, skipped or marked.

### 6.2 Historical replay **[v2]** — BLOCKED / NOT VERIFIED

```
python3 -m pytest -q tests/test_wel48_corpus.py \
  tests/test_wel48_manifest.py::test_ambiguous_correspondence_is_incomplete \
  tests/test_wel48_semantics.py::test_all_six_saved_response_semantic_inventories_are_reported
```

Six tests (F21): 4 + 1 + 1. The §6.1 deselects and this list are the same two node ids plus the whole corpus file, so the two commands are disjoint. Status: **NOT VERIFIED — BLOCKED**, because the WEL-48/WEL-42 raw bytes and bake-off results they read are absent. They are not fabricated, regenerated, re-fetched or stubbed by this design. Consequently the broad command `python3 -m pytest tests -q` (`docs/WEL-48-49-integration.md:20`) is **not** a WEL-51 gate and no clean broad-suite result is claimed, before or after WEL-51. Unblocking requires the original frozen inputs to be restored by their owner; that is outside WEL-51.

### 6.2a WEL-52 cross-repository handoff **[v3]** — NOT VERIFIED

```
WELLNEST_APP_DIR=<path to a consumer checkout> python3 -m pytest -q tests/test_wel52_handoff.py
```

One test, `tests/test_wel52_handoff.py::test_real_producer_consumer_two_then_three` (`:55`); the file contains no other test. It is disjoint from §6.1 (the file is not listed there) and from §6.2. By its own docstring it "deliberately fails (never skips)" without the consumer (`:3-4`). Prerequisites, read from the source this session:

| # | Prerequisite | Citation |
|---|---|---|
| H1 | Environment variable `WELLNEST_APP_DIR` set, naming a checkout of the consumer application (a separate repository, not this tree) | `tests/test_wel52_handoff.py:56-58` |
| H2 | That checkout contains the WEL-52 consumer CLI `scripts/wel52-consume.mts` | `:59` |
| H3 | That checkout has its dependencies installed, specifically `node_modules/tsx` present | `:60` |
| H4 | A `node` executable on `PATH`, since the consumer is invoked as `node --import tsx scripts/wel52-consume.mts …` with `cwd` = the consumer checkout | `:47-51` |

Relation to WEL-51: the test builds its store with `make_store` and `seed_version` from `tests/wel52_helpers` (`:15`, `:63-64`), so the F5 pin edit at `tests/wel52_helpers.py:19` is on its path; that effect is covered portably in §6.1 only through `tests/test_wel52_review.py` and `tests/test_wel52_pack.py`. Status: **NOT VERIFIED**. It was not run; no consumer checkout was located, inspected or assumed; no consumer revision or baseline is known to this design and none is named; no result, passing or failing, is claimed before or after WEL-51. WEL-51 changes no consumer code and provisions no consumer environment. Verifying it requires an operator who holds H1–H4; that is outside the portable WEL-51 gate.

### 6.3 Exact oracles

Real subject: `research.knowledge` and `research.report.render` on an on-disk store from `db.connect` + `db.migrate`. Seeding (`tests/wel51_helpers.py`) uses real `locate` + real `bind` on the saved proposals, as `tests/test_wel48_literal_corrections.py:67-87` does, then `save_version`; E4 reuses `seed_version` (`tests/wel52_helpers.py:32`). The roster is tracked `sources/roster.json` loaded in memory plus the fixture rows (§6.4.1), through real `registry.validate` + `registry.project`; the tracked file is never modified. No mocks of the subject; network refused (F20). `T` as §5(a); `A = knowledge.independent_support(conn, finding_id)`; `V = knowledge.current_followup(conn, latest_version)`; `PITA`/`RICE` = the two NHLBI URLs of C6; `F = (followup_state, followup)` bytes of the latest version.

| Test | Oracle |
|---|---|
| `test_m1_migration_8_rerunnable` | store migrated with `MIGRATIONS` filtered `<= 7` (pattern `tests/test_wel48_migration.py:8-9`); after statement 1 only: WEL-51 tables `== 1`, `MAX(version) == 7`; then `db.migrate(conn) == 8`; tables `== 3`; version-8 rows `== 1`; second `db.migrate(conn) == 8` |
| `test_fixture_roster_passes_real_validate` | `registry.validate(roster) is None`; `project(...)["surface_count"] == 26`; `resolve(conn, mirror_url)["root_publisher_id"] == "fixture_mirror"`; `effective_denied(conn, mirror_url) is None` |
| `test_bounded_investigation_counts` | `T == (1, 4, 1)`; `(supports, qualifiers) == (3, 1)`; bases of E1–E4 `== ("inferred","inferred","inferred","observed")` |
| `test_independent_support_is_two` | `A["independent_publisher_count"] == 2`; `A["components"] == [["fixture_mirror","public_domain_recipes"],["foss_family_recipes"]]` |
| `test_duplicate_adds_zero_independent` | `A["distinct_roots"] == 3`; count with E3 `== 2`; seeded without E3 `== 2` |
| `test_unattributed_support_not_counted` | `A["unattributed_supports"] == ["https://offroster.example/x"]`; count `== 2` |
| `test_qualifier_forces_unresolved` | `(state, len(unresolved)) == ("pending", 1)`; `A["unattributed_qualifiers"] == ["https://fixture.example/f-a"]`; report contains `"Total Time: 20 minutes"` and `"⏲️ Prep time: 5 min"` |
| `test_no_total_is_ever_derived` | E1 `stated` fields `== ["prep_time","cook_time"]`; literals `== ["⏲️ Prep time: 5 min","🍳 Cook time: 40 min"]`; every `text[start:end] == literal`; no numeric total field in `statement` |
| `test_fixture_links_are_labelled` | `A["fixture_links"] == 2` |
| `test_followup_is_exactly_one_and_unexecuted` | `followup_state == "proposed"`; `target_surface_url == PITA`; `decision_inputs["target"]["access_status"] == "permitted"` and `["evidence_rows"] == 0`; `decision_inputs["supporting_roots"] == ["fixture_mirror","foss_family_recipes","public_domain_recipes"]`; `(max_depth, max_pages, max_model_calls) == (1,1,1)`; `(V["status"], V["actionable_target_url"]) == ("eligible", PITA)`; `fetch_attempts` and `inference_calls` counts before `==` after |
| `test_followup_refused_without_target` | `(followup_state, reason) == ("refused", "no permitted uncollected surface for topic recipe_supply")`; `V["status"] == "refused"`; `V["actionable_target_url"] is None` |
| `test_single_source_needs_no_corroboration` | seed C1 only: `(count, followup_state, state, V["status"]) == (1, "none", "pending", "none")` |
| **`test_followup_permitted_to_withdrawn_no_support_change`** | §6.4 store synthesised ⇒ `F0`, `T0 == (1,4,1)`, `V["status"] == "eligible"`. Re-project the in-memory roster with only `PITA.access_status = "denied"` (valid per F13a). No evidence/recipe row touched. Then: `synthesize` again ⇒ `T == T0` and `F == F0` (zero writes, digest equal); `V["status"] == "withdrawn"`; `V["withdrawn_reasons"] == [registry.effective_denied(conn, PITA)]` and that string starts `"registry: effective-denied (retain/denied)"`; `V["actionable_target_url"] is None` (not `RICE`); `V["recorded"]["target_surface_url"] == PITA`; report contains `"Recorded proposal (historical"` and `"Current eligibility"` and `"withdrawn"`, and does not contain `"Actionable target: " + PITA`. Re-project `PITA` back to `permitted`: `(V["status"], V["actionable_target_url"]) == ("eligible", PITA)`; `T == T0`; `F == F0` |
| **`test_followup_withdrawn_to_permitted_no_support_change`** | same seed, but roster first projected with `PITA` and `RICE` both `access_status = "denied"`; synthesise ⇒ `F0[0] == "refused"`, `T0 == (1,4,1)`, `V["status"] == "refused"`. Re-project only `PITA = "permitted"`. Then: `synthesize` ⇒ `T == T0`, `F == F0` (stored state still `"refused"`); `(V["status"], V["actionable_target_url"]) == ("newly_eligible", PITA)`; `V["recorded"]["target_surface_url"] is None`; report contains `"newly_eligible"`. Re-project `PITA = "denied"`: `(V["status"], V["actionable_target_url"]) == ("refused", None)` |
| **`test_followup_evidence_availability_withdraws`** | §6.4 store synthesised; insert one `evidence` row for `PITA` via the incumbent store function (`research/evidence.py:43-72`) with labelled fixture text and **no** recipe version. `synthesize` ⇒ `T == T0`, `F == F0`; `V["status"] == "withdrawn"`; `V["withdrawn_reasons"] == ["evidence now exists for target"]`; `V["actionable_target_url"] is None` |
| **`test_followup_stale_version_not_actionable`** | §6.4 store synthesised; E2's human state set `rejected` (support changes); **without** re-running synthesis: `(V["status"], V["actionable_target_url"]) == ("stale_version", None)`; `T == (1,4,1)`. After `synthesize`: versions `== 2`; `(V["status"], V["actionable_target_url"]) == ("eligible", PITA)` |
| `test_k1_crash_before_commit` | `T == (0,0,0)`; rerun `T == (1,4,1)` |
| `test_k2_replay_inserts_nothing` | crash at `after_knowledge_commit`, rerun twice: `T == (1,4,1)` each |
| `test_r1_report_regenerates` | `worker.main(["report","--db",db,"--report",out]) == 0`; two renders with the same `now` are `==`; section has the four headings |
| `test_changed_support_does_not_inherit_approval` | `[(version_no, state)] == [(1,"approved"),(2,"pending")]`; links `== 5`; v1 `state_set_by == "human:reviewer"` |
| `test_roster_change_invalidates_version` | after `fixture_mirror.parent_publisher="public_domain_recipes"`: versions `== 2`; `A["distinct_roots"] == 2`; count `== 2` |
| `test_digest_return_appends_pending` | E2 manifest A→B→A via `attach_manifest` with a saved B version, **within one store**: `resolve_current` id after step 3 `==` after step 1; links `== 5`; versions `== 3`; `v3.support_digest == v1.support_digest`; `v3.state == "pending"` |
| `test_span_mismatch_writes_no_link` | links for that version `== 0`; failures `== 1` |
| `test_review_requires_human` | `by="worker"` raises; row `(state, state_set_by) == ("pending","worker")` |
| `test_locked_store_writes_nothing` | exit code `!= 0`; `T == (0,0,0)` |
| `test_relation_vocabulary_is_closed` | `pytest.raises(sqlite3.IntegrityError)` on `relation='related_to'` |
| `test_unknown_rule_is_read_only` | versions before `==` after; stored statement rendered |
| `test_empty_store_report_is_unchanged` | `"Retained knowledge" not in render(conn)` |
| `test_wel51_writes_no_publication` | `COUNT(*) FROM recipe_publications == 0` |

### 6.4 Frozen bounded investigation corpus

| Edge | Source | Kind | Relation / basis | Root | Proves |
|---|---|---|---|---|---|
| E1 | C1 casserole, `06ef9508…` | saved source-derived (`live`) | `supports` / `inferred` | `public_domain_recipes` | total absent although prep `5` and cook `40` are stated — the derivation trap, not taken |
| E2 | C2 orzo, `52366a25…` | saved source-derived (`live`) | `supports` / `inferred` | `foss_family_recipes` | a genuinely independent second publisher (C4) |
| E3 | new `syndicated-duplicate.json`: C1's text by hash reference under `https://mirror.example/easy-chicken-and-rice-casserole/` | **synthetic fixture** | `supports` / `inferred` | `fixture_mirror` (test-only) | same content, different owner adds `0`: `distinct_roots 3` → count `2` |
| E4 | WEL-52 `f-a`, `https://fixture.example/f-a` | **synthetic fixture** | `qualifies_or_contradicts` / `observed` | none (off-roster) | some recipes do state a total; visible, unresolved, never counted |

Expected: `T == (1,4,1)`; supports 3; qualifiers 1; `distinct_roots` 3; independent 2; `unattributed_supports` 0; `unattributed_qualifiers` 1; `fixture_links` 2; version `pending`; follow-up `proposed` → `PITA`; view `eligible`. Follow-up target order follows C6: orzo, casserole and the mirror fail P4 (evidence exists) and P5; budgetbytes fails P3; `PITA` is the first passing row, `RICE` the second.

#### 6.4.1 Fixture roster-row contract (must pass the real `source_registry.validate`, `research/source_registry.py:50-113`)

- **Publisher row** (`PUBLISHER_FIELDS`, `:17-18`): `publisher_id:"fixture_mirror"`, `canonical_name:"WEL-51 synthetic mirror (fixture)"`, `official_url:null`, `parent_publisher:null`, `identity_basis:"synthetic fixture; no real publisher; never fetched"`, `assessed_at:"2026-09-21T00:00:00Z"`, `assessed_by:"agent:wel51-fixture"` (`:35-38`), `notes:"label=fixture"`.
- **Surface row** (`SURFACE_FIELDS`, `:19-20`): `url` = mirror URL, `publisher_id:"fixture_mirror"`, `surface_kind:"site_article"`, `topics:["recipe_supply"]`, `roster_status:"retain"`, `roster_reason:"synthetic duplicate of C1 for WEL-51 tests; not a real source"`, `access_status:"permitted"`, `access_basis:"fixture only; never requested"`, `assessed_at`/`assessed_by` as above, `cadence_seconds:null`, `cadence_reason:null`, `equivalent_urls:[]`.
- Rows are appended to `publishers`/`surfaces` only; `version`, `historical_seeds`, `working_set` stay as tracked. **[v2]** Permission flips in the transition tests change only `access_status` of existing NHLBI rows in the in-memory copy; `working_set` membership does not require `permitted` (F13a). Whether each assembled roster validates is decided by the real `validate` inside `project` in the test, not claimed here.

The independent count of 2 rests on E1 and E2 alone, both real saved records; neither fixture can raise it. The NHLBI page has no evidence in this repository and roster prose is not evidence, so the follow-up stays unanswered. No household or private data is involved.

## 7. Rollout and degradation

**Default off, structurally.** No incumbent path calls synthesis. Until an operator runs `python3 -m research.knowledge synthesize`, the three tables are empty and every report is byte-identical to the frozen tree's. No activation, deployment, release or box change is part of this design.

**Migration loader.** `(8, [...])` appended after `research/db.py:283`; a store at 7 applies only 8; a fresh store applies 1→8 (F3). List form + `CREATE TABLE IF NOT EXISTS` makes a partial apply re-runnable (M1, test simulation only). The two F5 pins move to 8 in the same change.

**Old-store history.** First synthesis on an upgraded store reads only rows already present; it re-fetches nothing, modifies no incumbent row, and its first version is `pending`.

| Skew | Behaviour |
|---|---|
| New code, old store (≤7) | every entry point migrates before reading (F15, `research/worker.py:502-503`) |
| Old code, new store (8) | old `migrate()` applies nothing (F3); old code never names the three tables |
| New code, newer WEL-51 store | unknown `rule` ⇒ render stored statement, refuse synthesis; **[v2]** `followup` lacking `decision_inputs` or carrying unknown keys ⇒ view `unreadable` (S11 row 0), `actionable_target_url` null |

| Degradation | Behaviour (fail closed) |
|---|---|
| Roster absent/invalid | last valid projection stays (`research/source_registry.py:171-178`); unresolvable surface ⇒ unattributed |
| Roster permission or evidence availability changes with support unchanged **[v2]** | zero writes; stored proposal shown as historical; view recomputed (`withdrawn` / `newly_eligible`); nothing actionable unless the view says so |
| Support changed, synthesis not re-run **[v2]** | view `stale_version`; nothing actionable |
| No eligible follow-up target | `refused` with reason |
| Span/literal mismatch | no link; failure reported |
| Synthesis raises | transaction rolls back (S9) |
| Store locked or unavailable | non-zero exit, zero writes |
| Report write fails | incumbent handling (F18); store intact |
| Historical WEL-48/WEL-42 inputs absent **[v2]** | §6.2 stays BLOCKED / NOT VERIFIED; §6.1 is the gate |

## Self-lint

- Exactly seven numbered sections (1–7); three failure tables (5a/5b/5c); **no remote write** stated in §5.
- Re-verified against the frozen tree this session: `research/source_registry.py:66-113`, `:132-213`; `research/recipes.py:99-113` and the `:14-176` symbol map; `research/recipe_extract.py:230-250`; `tests/test_wel48_corpus.py:1-30`, `:56-79`; `tests/test_wel48_manifest.py:125-140`; `tests/test_wel48_semantics.py:1-30` (whole file) and `tests/test_wel48_corpus.py:39-43`; `tests/test_meal_export.py:350-375`; `research/report.py:63`, `:112`; `sources/roster.json:171-179` plus a full-file enumeration (25 surfaces, 17 publishers, C6 order); emptiness of the three `/tmp` directories. All other citations are carried from v1, which recorded re-reading them at the same SHA; they were not re-opened in this revision. **[v3]** The preceding list is carried from v2 and was not re-opened; the v3 revision read only `tests/test_wel52_handoff.py:1-82` (whole file) for §6.2a.
- Recount: 1 migration; 3 tables; 0 extra indexes; 0 new columns vs v1; 2 relation types; 1 rule; 5 target predicates; 7 view rows = 7 statuses, 2 of them actionable; 6 consumer rows; 4 crash boundaries; 21 death rows (17 + 4); 10 limitations (8 + 2); 29 oracle rows (25 + 4 new; 3 existing rows extended with `V`); 4 corpus edges = 3 supports + 1 qualifier; distinct roots 3 → independent 2; 6 blocked historical tests (4 corpus + 1 manifest + 1 semantics); 2 command-line deselects in §6.1; 2 pinned-test edits; 0 remote writes, fetches, inference calls, publications. **[v3]** 10 files in the §6.1 command (2 proposed + 8 incumbent, of which 2 WEL-52); 1 cross-repository handoff test recorded NOT VERIFIED in §6.2a with 4 prerequisites.
- Both transition tests assert unchanged support on both sides: `T == T0` and `F == F0` after re-synthesis.
- §6.1 portable and §6.2 blocked are separate; **[v3]** §6.2a is separate from both and `tests/test_wel52_handoff.py` appears in neither; no broad-suite result is claimed; nothing was run.
- No consensus, completion, implementation or test execution is claimed.

**PARKED FINDING —** six tracked tests (`tests/test_wel48_corpus.py`, one in `tests/test_wel48_manifest.py`, one in `tests/test_wel48_semantics.py`) hard-fail rather than skip when their `/tmp` inputs are absent; not investigated or changed.
