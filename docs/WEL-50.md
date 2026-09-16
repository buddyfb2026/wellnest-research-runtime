# WEL-50 — Continuous runtime preparation (PREPARED / NOT ACTIVATED)

Preparation input: WEL-50 candidate `af152a2a6461bc05d3b13fee93867bfc80f64a6e` with new `main`
`2010943a974b70778aa67f74d6a20e19e6c246c7` merged locally without a commit. Nothing here is installed, loaded,
bootstrapped, started or stopped. No external source request, local/hosted model call, or service command was made
while preparing this. Activation is a separate step that needs Spencer's explicit authorization
naming the exact action and the exact host, service account and plist (see the last section).
Review, merge or PR approval is not activation authority. Nothing starts a service automatically.

## What is prepared

One OS supervisor (launchd) starts **one** bounded worker process on a fixed interval. The worker
runs the reviewed WEL-41/43 `cycle` once and exits; launchd sleeps until the next interval. There is
no long-running agent loop, no queue service, no KeepAlive. Overlap, backoff and inference budgets
are the existing reviewed mechanisms in the worker, not supervisor features:

| concern | mechanism (unchanged) | supervisor's part |
|---|---|---|
| two cycles overlapping | `research/lock.py`: advisory `flock` beside the store; second entrance exits 3 `locked`, zero requests, zero calls, no run row | none; a skipped launch costs nothing |
| a source failing / blocked | `research/schedule.py`: 1h → 4h → 24h → 72h → 7d backoff; blocked 7d → 30d → `stalled` until `reset-source` | none; not-due sources are never requested |
| model spend | `research/model.py`: per-process and per-UTC-day caps, reservation committed before dispatch, never refunded, never replayed | none; caps are flags in the plist and can only be lowered |
| sleeping between cycles | launchd `StartInterval` | this is the only thing the supervisor adds |

Files:

| file | role |
|---|---|
| `docs/WEL-50-supervisor.launchd.example.plist` | uninstalled, `Disabled=true` supervisor definition; `plutil -lint` clean; every host-specific value is a `__FILL_*__` manifest token |
| `scripts/wel50_store_backup.py` | offline `backup` of the isolated SQLite store and `restore` into a fresh path only; takes the same store lock as the worker, exits 3 if a cycle is running; SQLite backup API + `integrity_check`; never overwrites an existing backup or store, and restore removes no files |
| `tests/test_wel50_backup.py` | 7 tests on pytest scratch paths: schema-6 representative-row round trip, refusal of existing / same-file / companion destinations without mutation, lock refusal, corrupt backup never restored, exact disabled-plist configuration parsing, adjacent allowlist/roster pairing, and stubbed recipe-adapter payload settings |
| this file | procedure, status semantics, manifest, gaps |

`bin/ri_run_research_cycle_launchd.sh` is an old script for a different runtime (`/Users/buddystudio1/ri_db`,
PostgreSQL). It is not used, not repaired and must not be installed. The only entrance is
`python3 -m research.worker cycle` on an isolated SQLite file.

## Prepared runtime command shape (disabled example; not executed)

```bash
WN_RESEARCH_OLLAMA_MODEL=qwen3.8:27b \
WN_RESEARCH_OLLAMA_URL=http://127.0.0.1:11434 \
WN_RESEARCH_RECIPE_EXTRACTION=true \
__FILL_PYTHON3__ -m research.worker cycle \
  --provider ollama --max-urls 10 --max-inference 10 --max-inference-per-day 10 \
  --allowlist __FILL_CHECKOUT__/sources/allowlist.json \
  --db __FILL_STATE_DIR__/research.sqlite \
  --report __FILL_STATE_DIR__/report.md
```

Paths are explicit flags, not `WN_RESEARCH_*` environment variables, so the supervised worker can
never silently resolve to another store. The adjacent `sources/roster.json` is loaded automatically
from the allowlist's directory; the focused test projects that real pair and verifies every current
`fetch=true` grant has a retained/permitted roster surface. Exit codes: 0 ok, 1 failed (`failures`
lists why), 3 locked.

These are existing runtime controls, not invented flags. `Config.from_env` reads model, URL and the
recipe switch; the reviewed recipe adapter supplies `num_ctx=16384`, `num_predict=4096` and
`think=false`. The candidate is the already-tested installed `qwen3.8:27b`, Ollama 0.32.14,
Q4_K_M, digest `22130167c4c20e20c7b71454612966ca8e8171e9b3cc8ab6ce8aa6cbfec79643` on the proposed
96 GB M3 Ultra. This records preparation evidence and a recommendation only: it does not prove the
future host has that digest, pin or download a model, authorize a rebenchmark, or activate Ollama.

Provider-none is only a zero-model diagnostic, not the continuous recipe outcome. Run it, if needed,
with recipe extraction explicitly off so it does not create failed recipe placeholders:

```bash
WN_RESEARCH_RECIPE_EXTRACTION=false __FILL_PYTHON3__ -m research.worker cycle \
  --provider none --max-urls 10 --max-inference 10 --max-inference-per-day 10 \
  --allowlist __FILL_CHECKOUT__/sources/allowlist.json \
  --db __FILL_SCRATCH_STATE_DIR__/research.sqlite --report __FILL_SCRATCH_STATE_DIR__/report.md
```

## Manifest (fill from verified, authorized deployment evidence; never invent)

| token | meaning | filled by |
|---|---|---|
| `__FILL_PYTHON3__` | absolute interpreter path on the deployment host (prepared and tested here with Python 3.9.6) | host evidence |
| `__FILL_CHECKOUT__` | checkout of the reviewed commit (the combined branch once WEL-48/49 are merged and reviewed) | deployment record |
| `__FILL_STATE_DIR__` | writable directory owned by the service account for `research.sqlite`, `research.sqlite.lock`, `report.md`, `cycle.log`, `cycle.err`; outside any customer or `ri_db` path | deployment record |
| host | isolated office Mac (current candidate host is a 96 GB M3 Ultra; a 24 GB mini only if actual model quality/headroom proves fit) | hardware decision |
| account | dedicated service account; no reuse of an existing mixed-use HOME/USER | deployment record |
| interval | `StartInterval` seconds (example 3600) | operator decision |
| provider / model | prepared candidate: Ollama + `qwen3.8:27b`; activation must verify exact installed digest/runtime on the target | model + host evidence |
| allowlist / roster | paired `sources/allowlist.json` and adjacent `sources/roster.json` from the exact reviewed checkout | deployment record |

## Start / stop procedure (documented only; NOT executed in WEL-50; each live step needs Spencer's exact authorization)

Prerequisite for every step: manifest complete, plist copied under the service account, `Disabled`
changed to `false` in the copy only, `plutil -lint` on the copy, and Spencer's explicit authorization
naming the action (bootstrap, kickstart, bootout) and the exact host, account/domain and plist label.

| action | command (run as the service account) | effect |
|---|---|---|
| install (load, no immediate run) | `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.wellnest.research-cycle.plist` | job registered; first cycle after one `StartInterval` (`RunAtLoad=false`) |
| run one cycle now | `launchctl kickstart gui/$(id -u)/com.wellnest.research-cycle` | one bounded cycle; if a cycle is already running the new process exits 3 |
| is it registered / alive | `launchctl print gui/$(id -u)/com.wellnest.research-cycle` | shows state, pid while a cycle runs, last exit status |
| stop (uninstall) | `launchctl bootout gui/$(id -u)/com.wellnest.research-cycle` | job removed; an in-flight cycle receives SIGTERM |

Stopping is the normal, label-scoped `bootout` above and nothing else. No process-level kill recipe
is prepared: the lock file's contents are informational only (`research/lock.py`), not a verified
process target. If a force-stop is ever needed it is a separately authorized action verified during
that exact activation work.

What a stop leaves behind is the reviewed WEL-41 behaviour: committed evidence, schedule
and candidates stay; the interrupted `runs` row stays `running` (visible in the report); a model
reservation dispatched before the stop is settled as `ambiguous` on the next entrance and never
replayed. No new crash semantics are introduced here.

## Backup / restore procedure (offline; fresh-path restore only; helper tested on scratch paths)

```bash
# backup: refuses (exit 3) while a cycle holds the store; never overwrites an existing backup
python3 scripts/wel50_store_backup.py backup  --db __FILL_STATE_DIR__/research.sqlite --out __FILL_BACKUP_DIR__/research-$(date -u +%Y%m%dT%H%M%SZ).sqlite

# restore: into a NEW path only. The destination must not exist, must not be the backup file, and
# must have no -journal/-wal/-shm companion; otherwise the command refuses before opening anything.
python3 scripts/wel50_store_backup.py restore --db __FILL_RESTORE_DIR__/research-candidate.sqlite --from __FILL_BACKUP_DIR__/research-....sqlite
python3 -m research.worker report --db __FILL_RESTORE_DIR__/research-candidate.sqlite --report __FILL_RESTORE_DIR__/report.md   # inspect the candidate
```

The helper never replaces the active store, never deletes a journal/WAL/SHM file and never
touches the backup. Making a configured service use a restored candidate file (a `--db` change
in the installed plist, after `bootout`, followed by `bootstrap`) is a later operation on an
exact target that needs its own Spencer authorization; WEL-50 does not prepare an in-place swap.

The store is the only durable runtime state. `report.md` is derived and regenerable; the allowlist and roster live in
the git checkout; `cycle.log` holds one JSON result per cycle and is not needed for recovery. A
backup is a consistent SQLite copy (backup API) verified with `PRAGMA integrity_check`; a newly
created invalid backup may be removed, but an existing backup/store is never overwritten; a file that
fails the check is never restored. What was exercised: whole-store copy of a synthetic scratch store
holding one run, one hint, one fetch attempt, one evidence version with text, one rule candidate, one
inference row, one schedule row, one WEL-48 manifest/recipe/version identity, and one WEL-49
publisher/surface identity, with values and cross-table relationships asserted equal after restore at
schema 6. Recovery of a real collected store remains untested.

## Status: four separate questions, four separate sources of truth

"Alive" never implies "useful". Read them in this order:

| question | where the answer is | what counts |
|---|---|---|
| 1. is the process alive / did it run | `launchctl print …` (pid, last exit status); last JSON line in `cycle.log`; `runs` table (`status` ok / failed / running) | exit 0 or 1 leaves a `runs` row; exit 3 (overlap) is visible only in `cycle.log` and the exit status and writes no run row. A `running` row with no live pid means an interrupted cycle. |
| 2. did a fetch succeed | `runs.summary.fetched_ok`, `source_requests`, `errors`, `blocked`; `fetch_attempts` rows; health table state `not_due` with a recent "last success" | `fetched_ok > 0` in some cycle; `not_due` with `source_requests = 0` is normal when nothing is due |
| 3. did model inference happen | `inference_calls` by `purpose` and `status` (`reserved` / `ok` / `error` / `ambiguous`), `inference_used_today`, "Inference budget" in the report | recipe extraction and candidate proposal consume the same persisted caps; `ambiguous` needs human review and is never automatically replayed |
| 4. was durable output useful | run summary `recipe_versions_new`, `recipe_versions_existing`, `recipe_failures`, `publisher_evidence`, `evidence_new`, `candidates_new`, `candidates_recovered`; `recipe_versions` completeness/state/publishable and report registry counts | source-backed recipe versions plus independent-publisher evidence; recipe `pending` still has `publishable=0`, and counts do not establish editorial approval or app delivery |

A cycle that exits 0 with all counters 0 proves only question 1. A provider-none diagnostic cannot
prove question 3 or the recipe part of question 4.

Operating limits of the existing worker: generic candidate proposals run before recipe extraction
and share the persisted 10-call daily budget. A first cycle with 10 fetched pages can spend that
budget before any recipe extraction; deferred recipe placeholders can resume on a later cycle/day.
Do not reset the ledger or raise its hard cap to make a run appear successful. Also,
`recipe_versions_new` counts deferred/failed placeholders, not only usable recipes: inspect the
stored content, completeness and failure reasons before reporting useful output.

## Verification performed here (offline, scratch paths, no network, no model, no service)

| check | command | result |
|---|---|---|
| plist lint | `plutil -lint docs/WEL-50-supervisor.launchd.example.plist docs/WEL-41-scheduler.launchd.example.plist` | both `OK` |
| focused preparation | `PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q -p no:cacheprovider tests/test_wel50_backup.py` | 7 passed: schema-6 recipe/source identity round trip, refusal/lock/corruption rules, exact disabled invocation parsing, actual adjacent allowlist/roster projection, and stubbed adapter proof of 16384/4096/false |
| merged-boundary smoke | `PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q -p no:cacheprovider tests/test_wel50_backup.py tests/test_wel48_wel49_integration.py` | 12 passed; offline only; verifies merged CLI/config, recipe adapter settings, roster coexistence, schema 6 and backup fidelity |
| no live assertion | no external source, local/hosted model, process, service, or existing-store command was run; tests use only synthetic in-memory transport and a stubbed model boundary | these checks establish configuration and scratch-store behavior only |

## NOT TESTED (stays NOT TESTED until an authorized activation runs it)

- launchd actually launching the job, honouring `StartInterval`, coalescing after sleep, and its
  behaviour when a previous instance is still running (the store lock covers correctness either way).
- Any 24-hour or multi-day criterion: real midnight UTC budget rollover under launchd, log growth,
  disk use, wake-from-sleep timing.
- Hardware and account: M3 Ultra vs 24 GB mini headroom, dedicated service account, file ownership
  and permissions on `__FILL_STATE_DIR__`.
- Live source requests or any local-model request under the supervisor, including the prepared Ollama recipe path.
- Exact target model digest/runtime availability, model process ownership, local endpoint health and model quality on the eventual deployment host.
- `launchctl bootstrap / kickstart / bootout / print` commands above: documented from launchd's
  interface, not executed.

## WEL-48 / WEL-49 preparation boundary

The new main commit is locally integrated into this uncommitted preparation tree. The disabled
supervisor now uses the merged configuration surface; backup/restore covers schema 6 recipe and
publisher identities; status semantics include recipe and publisher counters. The real allowlist has
18 entries, 13 `fetch=true`; the roster has 22 surfaces, and the 10-URL working set currently has 9
collection flags across 6 root publishers. That is configured coverage, not live collection proof.
Cookie and Kate remains on the combined integration hold (`fetch=false`) even though its roster row is
retained/permitted. No access was expanded here.

## Activation prerequisites (separate step, separate authorization)

1. Independent review of this WEL-50-on-new-main preparation delta, then an exact reviewed commit/checkout selected for deployment. The current local merge has no commit by design.
2. Manifest above filled from verified host/account/checkout evidence; no `__FILL_*__` left.
3. Dedicated service account on the isolated host; no shared HOME/USER and no other launchd job
   (for example an existing Ollama service) sharing the store, the port or the account.
4. On the exact target, verify Ollama 0.32.14 and the installed `qwen3.8:27b` digest, then confirm the
   installed copy's existing environment controls. The disabled example records the proposed values;
   it neither installs nor pins them. Provider `none` is diagnostic only and cannot satisfy the outcome.
   Specifically confirm `WN_RESEARCH_OLLAMA_MODEL` survived the copy: omitting it uses the existing
   `qwen2.5:14b` default, not the reviewed Qwen 27B candidate.
5. `Disabled` flipped to `false` only in the installed copy; the example in `docs/` stays disabled.
6. First backup taken before the first supervised cycle; backup location and cadence decided.
7. Spencer's explicit authorization naming the exact action (`launchctl bootstrap`), the exact host,
   the service account / launchd domain and the plist label. Coordinator go, review, merge or PR
   approval do not count. The same applies to every later `kickstart`, `bootout`, provider change or
   switch of `--db` to a restored file.
