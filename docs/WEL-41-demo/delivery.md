# WEL-41 delivery — bounded recurring collection and discovery (Claude, 2026-09-15, repair round 1)

**State: review-ready, uncommitted** in `/private/tmp/wellnest-wel41` (branch `wel-41/recurring-collection`, base `6a9ee4c11d63125566611761ecff226025746e83`). Nothing committed, pushed, installed or activated. Git commands were denied by the session sandbox, so the file list below is from my edit record, not `git status`; Astra should confirm with `git status` before review.

## Repair round 1 (review verdict F1, F2)

| finding | fix | regression test | result |
|---|---|---|---|
| F1 recovery re-dispatched after a durable reservation | `worker._prior_attempt` consults `inference_calls` for the evidence/provider/model before any dispatch. A `reserved` row (worker died after dispatch) is settled to `ambiguous` with reason `interrupted…`; an `ok`/`error`/`ambiguous` row whose candidate save failed yields `prior_attempt_<status>`. Either way a deferred candidate is written with zero external dispatch; rule recovery and budget-placeholder redo are unchanged. | `test_interruption_after_dispatch_recovers_deferred_state_without_a_second_dispatch` (KeyboardInterrupt inside `http_post`: 1 dispatch, `reserved` persists; restart +1h: 0 requests, 0 dispatches, `attempts_settled` 1, row → `ambiguous`, rule pending + ollama deferred; +1 day: still 0 dispatches). `test_save_failure_after_successful_call_is_settled_not_replayed` (1 fixture call total, reason `prior_attempt_ok`). | both pass |
| F2 day/time frozen at run start | reservation `day`/`called_at` are read from the injected clock immediately before each `propose`; `inference_used_today`/`day` in the result refer to the clock at run end. | `test_reservations_in_one_long_run_are_charged_to_the_day_of_each_dispatch` (worker starts 23:00 Sep 15, second call at 00:00 Sep 16 with cap 1 → days `[09-15, 09-16]`, `called_at` `[23:00, 00:00]`; a Sep 16 02:00 worker gets 0 calls and 1 budget deferral). | pass |

Docs updated (`docs/WEL-41.md`): the earlier "redo spends a second call" limitation is withdrawn; a dispatched attempt is never replayed automatically. Live demo evidence below is unchanged: it ran with provider none, which reserves nothing, so neither fix alters its semantics.

## Test evidence

```
python3 -m pytest tests -q      → 124 passed (99 WEL-40 baseline + 25 new in tests/test_recurring.py)
focused: -k "interruption or save_failure_after or long_run or rollback_after_reservation or ambiguous or placeholder or crash_after" → 8 passed
```

Baseline change: the schema-version literal `3 → 4` in three existing assertions (`test_worker.py`, `test_repair_round1.py`, `test_repair_round2.py`). No other WEL-40 test text changed.

| AC | proof (tests, counts) |
|---|---|
| AC1/2 two cycles + restart | cycle 1: requests 1 (+1 robots), evidence 1, candidates 1, inference rows 1, next check +7d. cycle 2 (fresh connection + fresh model client, +1h): requests 0, `not_due` 1, rows unchanged, `inference_used_today` 1 visible after restart. cycle 3 (+7d, unchanged content): request 1, evidence 1, candidates 1, inference 0. |
| AC2 overlap, whole processes | real subprocess holds the flock mid-fetch; in-process `cycle` returns `status=locked`, 0 requests, 0 calls, no run row. Holder SIGKILLed → OS releases lock → next cycle collects; evidence 1, candidates 1; killed run stays `running` in `runs`. |
| AC2 crash at persisted boundary | process dies right after the evidence COMMIT (BaseException from a conn wrapper): evidence 1, source_state ok, candidates 0, lock released. Restart at +1h (not due): 0 requests, `candidates_recovered` 1, rule candidate pending + free-text deferred created, inference 1. Third entrance recovers 0. |
| AC1/5 daily budget | cap 1, two sources: run 1 spends 1 (`reserved→ok`), second evidence gets placeholder `inference_budget_exhausted: daily…`. Restart same day: 0 calls. +1 day (00:00 UTC): placeholder replaced, inference rows 2 with days 09-15/09-16. Human-changed placeholder is never overwritten. Ambiguous timeout (provider ollama, injected `http_post` raising): row `status=ambiguous`, candidate deferred `ambiguous_response`, no replay next hour or next day. Candidate-insert failure after a reservation: run `failed`, candidates 0, reservation stays `ok`, `used_today` 1. Provider none: 0 reservations. Reservation inside an open transaction is refused. |
| AC3/5 backoff + preserved evidence | timeout series produces next checks +1h, +4h, +24h, +72h, +7d, +7d with a request-free probe 1s before each; 6 attempt rows, 0 evidence. Failed refresh at +7d after a human approval: evidence 1 with original `fetched_at`/`published_at`, approval intact, `last_success_at` = t0, report row `failed`, "7d ago", `http 500`. Blocked ×3 (t0, +7d, +37d) → `stalled`; at +400d 0 requests; `reset-source` → collected; 4 attempt rows total. |
| AC2/5 changed content | v2 `supersedes` v1, fetched_at differs, v1 rule candidate stays `approved` by human, v2 rule candidate `pending` by worker; 4 candidate rows. |
| AC3 health report | one render distinguishes `not_due`, `failed`, `stalled`, `due` (after manual reset), lists stalled/failing sources, budget by status, "Budget stopped: N". Report-write failure in cycle mode: run `failed`, evidence kept. |
| AC4 discovery | fixture route page: 2 hints stored (off-origin, login, other-section, self and query-string links dropped), 1 permitted, 1 robots-denied; assessment made 0 content requests; permitted hint collected next cycle; denied never requested; article links and injected URLs produce 0 hints; bounds 20 hints/route and 3 assessments/cycle enforced; route without `fetch=true` rejected. |

## Live demo (provider=none, zero model calls, temporary store)

`/tmp/wel41-coordination/demo/` — `run_demo.py`, `allowlist.json` (declared GH route + the two GH seeds only), `research.sqlite`, `cycle{1,2,3}.json`, `report_cycle{1,2,3}.md`, `query_demo.py`.

| cycle | requests (robots) | fetched ok | routes | hints new | assessed permitted | not_due | evidence new | candidates new | inference |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 3 (1) | 2 | 1 | 19 | 3 | 0 | 2 | 3 | 0 |
| 2 | 3 (1) | 3 | 0 | 0 | 3 | 3 | 3 | 3 | 0 |
| 3 | 3 (1) | 3 | 0 | 0 | 3 | 6 | 3 | 3 | 0 |

Store after cycle 3 (schema 4): evidence 8 (all `live`), candidates 9 (1 rule pending: air fryer; 8 `none:-` deferred), inference_calls 0, fetch attempts 9 all `ok`, runs 3 `ok`, hints 19 (9 assessed permitted, 10 unassessed), source_state 12 (9 ok, 3 never attempted, due).

**Genuine beyond-seed discovery (AC4)**: route `https://www.goodhousekeeping.com/home/cleaning/` (declared in `sources/allowlist.json` with `role: discovery_route`; publisher already permitted for the two seeds; robots checked). First discovered and collected URL: `https://www.goodhousekeeping.com/home/cleaning/a71604725/why-robot-vacuum-missing-spots/`, discovered 2026-09-15T16:17:55Z, assessment `permitted: same origin as declared route; robots allows` (robots_status `allowed`), collected cycle 2, published 2026-08-18, 5227 text chars. Five more household-cleaning articles were discovered and collected the same way (too-much-detergent, cold-water washing, wash-before-using, unshrinking trick, white sneakers). None is in the seed list.

Actual live retrieval this session: two aborted demo attempts (a path-formatting bug in my script after cycle 1 had already run) plus the recorded run: 15 content requests and 5 robots.txt requests to goodhousekeeping.com in total. No model calls of any kind.

## Changed files

New: `research/lock.py`, `research/schedule.py`, `research/discovery.py`, `tests/test_recurring.py`, `docs/WEL-41.md`, `docs/WEL-41-scheduler.launchd.example.plist` (Disabled=true, not installed).
Modified: `research/db.py` (migration 4, per-statement apply), `research/worker.py` (lock, `cycle`, schedule, durable candidate recovery, discovery, `reset-source`, `--max-inference-per-day`), `research/model.py` (reservation before request, ambiguous status), `research/report.py` (health section), `research/candidates.py` (placeholder helpers), `research/config.py` (daily cap, discovery limits), `research/fetch.py` (clock, `permit`), `sources/allowlist.json` (route entry), three WEL-40 test files (version literal).

## Limitations and honest gaps

- The `locked` entrance writes no run row, by design, so overlap is visible only in the caller's exit code (3) and JSON; not in the report.
- After a candidate-save failure or interruption following a dispatch, the evidence gets a deferred candidate from that attempt and is not dispatched again automatically; obtaining a real proposal for it is a human decision.
- Route hint extraction is generic (same origin, route path prefix); on the live GH index this yields articles only because the section index links articles. A route that links galleries could produce `no usable text` errors that back off normally.
- Recorded live day rollover was simulated with the injected clock; no real midnight was observed.
- Sources are fetched sequentially; no concurrency knob beyond `--max-urls`.
- Ollama path is exercised only with an injected `http_post` (offline); no live model was called.

## Adversarial self-review

- Could overlap overspend? No: the store lock precedes any request, and the reservation is `BEGIN IMMEDIATE` on the same SQLite file, so even a bypassing caller cannot double-count.
- Could a rollback refund? No: the reservation commits before the request in a separate transaction; `test_candidate_save_rollback_after_reservation_does_not_refund`.
- Could a dispatched call be replayed? No: any prior reservation for the evidence/provider/model is settled, never re-sent; interruption and save-failure tests above.
- Could midnight be mis-charged? No: day and time are read per call; long-run test above.
- Could embedded text authorize a fetch or change budget? No: hints come only from `role=discovery_route` allowlist pages; evidence text never reaches `extract_hints`; budgets are config/CLI ceilings only.
- Could a not-due source be requested? No: selection is by `next_check_at` in `cycle`; probed at due−1s across six backoff steps.
- Could a placeholder suppress work forever? No: it is the one explicitly redone state; human-changed rows are excluded.

PARKED FINDING: `research/evidence.py` `upsert_source_hint` still stamps `first_seen_at`/`last_seen_at` with the wall clock rather than the injected clock, so hint timestamps in clock-driven tests are real-time; harmless here, not touched.
