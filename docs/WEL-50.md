# WEL-50 — Continuous runtime preparation (PREPARED / NOT ACTIVATED)

Base: remote `main` `2b7602f42856ce34c6a18c810f7181bca418bd6f`. Nothing here is installed, loaded,
bootstrapped, started or stopped. No model call, no source request, no service command was made
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
| `tests/test_wel50_backup.py` | 4 tests on pytest scratch paths: representative-row round trip, refusal of existing / same-file / companion destinations without mutation, lock refusal, corrupt backup never restored |
| this file | procedure, status semantics, manifest, gaps |

`bin/ri_run_research_cycle_launchd.sh` is an old script for a different runtime (`/Users/buddystudio1/ri_db`,
PostgreSQL). It is not used, not repaired and must not be installed. The only entrance is
`python3 -m research.worker cycle` on an isolated SQLite file.

## Command shape (current flags only)

```bash
__FILL_PYTHON3__ -m research.worker cycle \
  --provider none --max-urls 10 --max-inference 10 --max-inference-per-day 10 \
  --allowlist __FILL_CHECKOUT__/sources/allowlist.json \
  --db __FILL_STATE_DIR__/research.sqlite \
  --report __FILL_STATE_DIR__/report.md
```

Paths are explicit flags, not `WN_RESEARCH_*` environment variables, so the supervised worker can
never silently resolve to another store. Exit codes: 0 ok, 1 failed (`failures` lists why), 3 locked.
`--provider none` makes zero model calls; WEL-50 pins no model (Qwen/Gemma runs are experiments,
not configuration). Switching to `--provider ollama` is an activation decision recorded in the manifest.

## Manifest (fill from verified, authorized deployment evidence; never invent)

| token | meaning | filled by |
|---|---|---|
| `__FILL_PYTHON3__` | absolute interpreter path on the deployment host (prepared and tested here with Python 3.9.6) | host evidence |
| `__FILL_CHECKOUT__` | checkout of the reviewed commit (the combined branch once WEL-48/49 are merged and reviewed) | deployment record |
| `__FILL_STATE_DIR__` | writable directory owned by the service account for `research.sqlite`, `research.sqlite.lock`, `report.md`, `cycle.log`, `cycle.err`; outside any customer or `ri_db` path | deployment record |
| host | isolated office Mac (current candidate host is a 96 GB M3 Ultra; a 24 GB mini only if actual model quality/headroom proves fit) | hardware decision |
| account | dedicated service account; no reuse of an existing mixed-use HOME/USER | deployment record |
| interval | `StartInterval` seconds (example 3600) | operator decision |
| provider / model | `none` until a model is chosen by evidence | model decision |
| allowlist roster | `sources/allowlist.json` at the reviewed commit | review |

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

The store is the only durable state. `report.md` is derived and regenerable; the allowlist lives in
the git checkout; `cycle.log` holds one JSON result per cycle and is not needed for recovery. A
backup is a consistent SQLite copy (backup API) verified with `PRAGMA integrity_check`; a file that
fails the check is never restored. What was exercised: whole-store copy of a synthetic scratch store
holding one run, one hint, one fetch attempt, one evidence version with text, one rule candidate, one
inference row and one schedule row, with values and the evidence↔candidate↔schedule relationships
asserted equal after restore. Recovery of a real collected store, and any WEL-48/49 state, is untested.

## Status: four separate questions, four separate sources of truth

"Alive" never implies "useful". Read them in this order:

| question | where the answer is | what counts |
|---|---|---|
| 1. is the process alive / did it run | `launchctl print …` (pid, last exit status); last JSON line in `cycle.log`; `runs` table (`status` ok / failed / running) | exit 0 or 1 leaves a `runs` row; exit 3 (overlap) is visible only in `cycle.log` and the exit status and writes no run row. A `running` row with no live pid means an interrupted cycle. |
| 2. did a fetch succeed | `runs.summary.fetched_ok`, `source_requests`, `errors`, `blocked`; `fetch_attempts` rows; health table state `not_due` with a recent "last success" | `fetched_ok > 0` in some cycle; `not_due` with `source_requests = 0` is normal when nothing is due |
| 3. did model inference happen | `inference_calls` rows by `status` (`reserved` / `ok` / `error` / `ambiguous`), `inference_used_today`, "Inference budget" line in the report | with `--provider none` this is always 0 by design; `ambiguous` rows need a human decision |
| 4. was durable output useful | `evidence_new`, `candidates_new`, `candidates_recovered`; `candidates` rows `pending` (rule registry) or `deferred` (free text) | evidence versions and pending rule candidates; "Budget stopped" counts placeholders waiting |

A cycle that exits 0 with all counters 0 (as in the verification below) proves only question 1.

## Verification performed here (offline, scratch paths, no network, no model, no service)

| check | command | result |
|---|---|---|
| plist lint | `plutil -lint docs/WEL-50-supervisor.launchd.example.plist docs/WEL-41-scheduler.launchd.example.plist` | both `OK` |
| worker entrance | `python3 -m research.worker cycle --provider none --allowlist <scratch>/allowlist.json` (`{"sources": []}`) `--db <scratch>/work/research.sqlite --report …` | exit 0, `status ok`, `source_requests 0`, `robots_requests 0`, `inference_calls 0`, one `runs` row `ok`, `report.md` written |
| overlap | same command while another process holds `research.sqlite.lock` | exit 3, `status locked`, `source_requests 0`, failure text "held by another worker process … nothing requested" |
| report | `python3 -m research.worker report --db … --report …` | exit 0, renders the run row |
| backup / restore (first pass) | `scripts/wel50_store_backup.py backup …` then `restore …` into a fresh path on a run-only scratch store | exit 0 both; `integrity ok`; identical table counts (schema_version 4); proves copy of that fixture only |
| focused tests (repair one) | `python3 -m pytest tests/test_wel50_backup.py -q` | 4 passed: representative rows (evidence, text, candidate, hint, attempt, inference, schedule) equal after fresh-path restore; existing / same-file (direct, relative alias, symlink) / companion destinations refused with no mutation and no lock file; lock refusal exit 3; corrupt backup refused |
| full suite (first pass only, not repeated) | `python3 -m pytest tests -q` | 188 passed, 1 failed (`test_wel43.py::test_recorded_comparison_and_manifest_are_preserved_as_history`, pre-existing on `main`; unrelated, not touched) |
| not installed | `ls ~/Library/LaunchAgents \| grep -i wellnest.research` | no match; `launchctl` was never invoked |

## NOT TESTED (stays NOT TESTED until an authorized activation runs it)

- launchd actually launching the job, honouring `StartInterval`, coalescing after sleep, and its
  behaviour when a previous instance is still running (the store lock covers correctness either way).
- Any 24-hour or multi-day criterion: real midnight UTC budget rollover under launchd, log growth,
  disk use, wake-from-sleep timing.
- Hardware and account: M3 Ultra vs 24 GB mini headroom, dedicated service account, file ownership
  and permissions on `__FILL_STATE_DIR__`.
- Live source requests under the supervisor and any model provider other than `none`.
- `launchctl bootstrap / kickstart / bootout / print` commands above: documented from launchd's
  interface, not executed.

## Unmet WEL-48 / WEL-49 contracts (explicit)

WEL-48 and WEL-49 are uncommitted in separate worktrees and are not part of base `2b7602f`. This
preparation used **current flags only** and did not read, copy or integrate their code. Therefore:

- any CLI flag, environment variable or provider option they add is absent from the plist and untested;
- any durable state they add (tables, files beside the store, identity or recovery records) is
  outside the backup/restore procedure above until re-verified;
- any status or health output they add is not part of the four-question table above;
- the "combined reviewed branch" does not exist yet, so the command shape must be re-linted and the
  scratch verification re-run on it before the manifest is filled.

Integration of WEL-48/49-specific behaviour is NOT TESTED by definition here.

## Activation prerequisites (separate step, separate authorization)

1. Reviewed combined branch containing WEL-48/49 merged into `main`, suite green on that commit.
2. Manifest above filled from verified host/account/checkout evidence; no `__FILL_*__` left.
3. Dedicated service account on the isolated host; no shared HOME/USER and no other launchd job
   (for example an existing Ollama service) sharing the store, the port or the account.
4. Tested local-model decision recorded, with its model name and URL supplied as explicit
   flags/variables in the installed copy, never in this example. Provider `none` is valid only for
   preparation/diagnostic runs; it cannot satisfy the continuous local-model research outcome.
5. `Disabled` flipped to `false` only in the installed copy; the example in `docs/` stays disabled.
6. First backup taken before the first supervised cycle; backup location and cadence decided.
7. Spencer's explicit authorization naming the exact action (`launchctl bootstrap`), the exact host,
   the service account / launchd domain and the plist label. Coordinator go, review, merge or PR
   approval do not count. The same applies to every later `kickstart`, `bootout`, provider change or
   switch of `--db` to a restored file.
