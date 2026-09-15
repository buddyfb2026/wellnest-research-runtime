# WEL-41 — Bounded recurring research collection and discovery

Linear: https://linear.app/bizina/issue/WEL-41/run-bounded-recurring-research-collection-and-discover-new-sources

Extends the WEL-40 worker into a restart-safe, bounded collector. No daemon, no loop, no queue
service, no app change. A scheduler may call `cycle`; none is installed or activated here
(`docs/WEL-41-scheduler.launchd.example.plist` is a disabled example only).

## Commands

```bash
python3 -m pytest tests -q                                     # 124 tests, network refused
python3 -m research.worker run   --provider none               # manual: every permitted source (WEL-40 behaviour)
python3 -m research.worker cycle --provider none               # recurring entrance: DUE sources only, capped
python3 -m research.worker cycle --provider none --max-urls 5 --max-inference-per-day 3
python3 -m research.worker report
python3 -m research.worker reset-source URL --by NAME --reason TEXT   # revive a stalled/backed-off source
```

Exit codes: 0 ok, 1 failed (some write or report failed; see `failures`), 3 locked (another
worker holds the store; nothing was requested or called).

## Mechanism (schema version 4, additive)

| piece | where | behaviour |
|---|---|---|
| store lock | `research/lock.py` | advisory `flock` on `<db>.lock` beside the resolved SQLite file, held for the process lifetime, released by the OS on exit or kill. Both `run` and `cycle` take it. Overlap: `status=locked`, zero requests, zero calls, no run row. |
| schedule | `source_state`, `research/schedule.py` | per permitted source: `next_check_at`, attempts, consecutive failures, last outcome/reason, last success, last evidence id, `stalled`. Newly permitted sources are due immediately. `cycle` selects `next_check_at <= clock`, `stalled=0`, ordered by due time, at most `--max-urls`. Not-due sources: no request, no attempt row, counted as `not_due`. |
| backoff | `schedule.record_outcome` | success → +7d. error (timeout, 5xx, 404, unusable text) → 1h, 4h, 24h, 72h, 7d, 7d… blocked (robots, login, 401/403) → 7d, 30d, then `stalled` until `reset-source`. Failures never modify prior evidence, its age, or candidate states. |
| clock | `run(..., clock=)` | injectable UTC clock used for run ids, schedule, budget day, fetch timestamps and report ages. Default: wall clock. |
| daily budget | `inference_calls.day/status`, `ModelClient._reserve` | ceilings: 10 per process (`--max-inference`) and 10 per UTC day (`--max-inference-per-day`), both may only be lowered. Before any model request a `reserved` row is committed in its own `BEGIN IMMEDIATE` transaction (refused if a transaction is open). The reservation's `day` and `called_at` are read from the clock immediately before that call, so a worker running across midnight charges each call to the day it was dispatched. Every row for the day counts, whatever its later status (`ok`, `error`, `ambiguous`); rows are never deleted, so restart, overlap, timeout or a later candidate rollback cannot refund a call that may have executed. Day resets at 00:00 UTC. `provider=none` reserves nothing. `inference_used_today` in the run result refers to the day at the end of the run. |
| ambiguous calls | `ModelClient.propose` | an exception from the HTTP request (timeout, dropped connection) is recorded as `status=ambiguous`, the candidate is deferred with `ambiguous_response: …`, and it is never replayed automatically. No retries anywhere. |
| recoverable work | `worker._missing_work`, `worker._prior_attempt` | candidate work comes from durable state, not memory: every URL's latest evidence version that lacks a rule candidate for a matching rule or a free-text row for the current generator is (re)done. A crash after the evidence commit is finished on the next entrance without any request. Before any model dispatch the worker consults `inference_calls` for that evidence/provider/model: if a reservation already exists (process died after dispatch → still `reserved`; or the candidate save failed after `ok`/`error`/`ambiguous`), it is settled into a deferred candidate with no external dispatch, and a `reserved` row becomes `ambiguous`. The only worker-written row that is redone is a budget placeholder (`inference_budget_exhausted: …`, which has no reservation); a human-changed row is never touched. |
| discovery | `research/discovery.py`, `source_hints.discovered_at/discovery_route/access_assessment` | only an allowlist entry with `"role": "discovery_route"` (a declared public index page, fetch permitted, robots checked) yields hints: same-origin links under the route's path, at most 20 per route page, no query strings, no login paths. Each cycle assesses at most 3 unassessed hints with the fetcher's request gate (http(s), not private, same origin as the route, not login, robots allows) making no content request. Permitted hints inherit the route's access basis, become scheduled sources due now, and are collected by a later cycle under the same caps. Denied hints stay hints with zero requests. Links inside article evidence, model output or embedded instructions are never hints. |
| health report | `report.render_health` | per source: `not_due`, `due`, `failed`, `blocked`, `stalled`, `never_attempted`, with last attempt, reason, last success age, evidence fetched/published age, attempts, consecutive failures, next check; lists stalled and failing sources; today's budget by status; "budget stopped" count; discovered hints with route, assessment and collect flag. |

## Limits recorded before build-ready

- one worker process per store; sources are fetched sequentially (concurrency 1); at most
  `--max-urls` (≤10) source requests per entrance; at most 3 discovery assessments per cycle;
  at most 20 hints stored per route page; robots.txt requested at most once per origin per process.
- daily cap counts reservations, not successes. A candidate-save failure or an interruption after
  dispatch leaves the reservation spent; the next entrance records a deferred candidate from that
  attempt (`prior_attempt_<status>` / `ambiguous_response: interrupted`) and does not call again.
  Getting a real proposal for that evidence needs a human decision, not an automatic replay.
- a `locked` entrance writes nothing (not even a run row) so it never waits on the holder's SQLite
  work; a holder killed mid-run leaves its `runs` row as `running`, which the report shows.
- schedule and budget timestamps are UTC strings; the day boundary is 00:00 UTC.

## Tests (tests/test_recurring.py)

| acceptance | test |
|---|---|
| AC1/2 due, two cycles, restart | `test_two_cycles_and_restart_add_nothing_and_spend_nothing_when_not_due`, `test_manual_run_still_attempts_every_permitted_source_and_updates_schedule` |
| AC1/2 overlap across processes, kill | `test_two_processes_one_processing_attempt_and_os_releases_a_killed_holder` (real subprocess holds the lock mid-fetch; SIGKILL) |
| AC2 crash at persisted boundary | `test_crash_after_evidence_commit_then_restart_finishes_rule_and_free_text_candidates` |
| AC1/5 budget | `test_last_reservation_survives_restart_and_placeholder_is_redone_after_day_rollover`, `test_human_reviewed_placeholder_is_not_overwritten`, `test_ambiguous_model_timeout_consumes_its_reservation_and_is_never_replayed`, `test_interruption_after_dispatch_recovers_deferred_state_without_a_second_dispatch`, `test_save_failure_after_successful_call_is_settled_not_replayed`, `test_reservations_in_one_long_run_are_charged_to_the_day_of_each_dispatch`, `test_candidate_save_rollback_after_reservation_does_not_refund`, `test_provider_none_cycle_makes_zero_reservations`, `test_reservation_refuses_to_run_inside_a_transaction` |
| AC3/5 backoff, freshness, preserved evidence | `test_error_backoff_is_finite_and_no_request_occurs_before_next_check`, `test_failed_refresh_keeps_prior_evidence_age_and_approval`, `test_blocked_backoff_stalls_after_three_and_only_manual_reset_revives`, `test_blocked_source_is_never_reported_as_fresh_success` |
| AC2/5 changed content | `test_changed_content_appends_version_and_does_not_inherit_approval` |
| AC3 report | `test_health_report_distinguishes_states_without_a_service`, `test_report_write_failure_in_cycle_leaves_no_durable_success` |
| AC4 discovery | `test_route_hints_are_assessed_then_collected_next_cycle_and_denied_hints_are_never_requested`, `test_article_links_and_embedded_instructions_never_become_hints`, `test_discovery_bounds_hints_per_route_and_assessments_per_cycle`, `test_route_must_declare_permitted_access` |
| CLI | `test_cli_cycle_and_reset_source` |

WEL-40 tests are unchanged except the schema version literal (3 → 4) in three assertions.
