# WellNest source yield report (WEL-43)

Generated 2026-09-15T17:40:54Z from the research store only. Read-only: this report writes nothing and makes no network or model call.

## How to read this

- The sample unit is a **distinct document** = one `(url, content_hash)` evidence row. Re-collecting unchanged content adds a fetch attempt, not a document, so repeated runs cannot inflate the sample.
- **No rates and no ranking are shown.** The largest per-source sample here is 8 document(s); the threshold for computing a rate is 30. Counts only.
- "No registered rule matched" and "provider=none" are **coverage gaps of this repository**, not source failures, and are reported in their own section.
- A pending or approved candidate is a review state. It is **not** evidence that a household did anything.

## Denominators

| quantity | value |
|---|---|
| distinct documents (sample unit) | 8 |
| evidence rows incl. superseded versions | 8 |
| distinct urls with evidence | 8 |
| distinct hosts (sources) with evidence | 1 |
| hosts attempted but with no evidence (blocked/failed only) | 0 |
| fetch attempts (all outcomes) | 9 |
| of which re-fetches of unchanged content | 0 |
| candidates | 9 |
| candidates with a human review decision | 0 |
| inference calls recorded | 0 |
| scheduled sources (permitted) | 12 (never attempted 3, stalled 0) |
| discovery hints | 22 (permitted 12, discovered but unassessed 10) |

## Topic yield

Topic is **not recorded** by schema v4: there is no topic, tag or category column on evidence or candidates. No topic breakdown is shown, and none is inferred from urls or titles.

## Per-source counts

| source (host) | documents | evidence versions | fetch ok | blocked | error | freshness | candidate classes |
|---|---|---|---|---|---|---|---|
| www.goodhousekeeping.com | 8 | 8 | 9 | 0 | 0 | older_than_730d=1, within_730d=7 | no_inference_provider=8, rule_supported_unreviewed=1 |

A row with 0 documents is a host that was attempted and produced no evidence (blocked or failed). Its attempts are shown here, and it is **not** counted as a source with evidence: 0 of the 1 host(s) in this table are in that position.

Comparing sources against each other is **not possible from this table**: there is only one source with evidence.

## Candidate outcome classes

Every candidate row falls in exactly one class (total 9 = candidates 9).

| class | count | meaning |
|---|---|---|
| human_approved | 0 | a reviewer approved the prepared action. Approval is a review decision only — it is not evidence that any household did anything. |
| human_rejected | 0 | a reviewer rejected the candidate. |
| human_deferred | 0 | a reviewer deferred the candidate. |
| human_pending | 0 | a reviewer put the candidate back to pending. |
| rule_supported_unreviewed | 1 | the closed action registry matched a reviewed sentence verbatim; no human has reviewed it yet. Not a quality verdict. |
| no_inference_provider | 8 | no model was configured (provider=none), so no proposal was produced. This says nothing about the source. |
| waiting_inference_budget | 0 | the daily inference cap was reached; the candidate is a placeholder. |
| model_proposal_unregistered | 0 | a free-text model proposal was stored for audit and deferred or rejected because it is not a registered action. |
| unknown | 0 | the record does not fit any defined class; reported as unknown rather than success. |

## Coverage gaps (NOT source failures)

| gap | count | note |
|---|---|---|
| evidence with no registered rule match | 7 | `research/rules.py` currently registers a small closed set of reviewed actions. An unmatched document means this repository has no rule for it. |
| evidence with no candidate row at all | 0 | no rule matched and no proposal was attempted. |
| candidates with no model available | 8 | provider was `none`. |
| candidates waiting for inference budget | 0 | the daily cap stopped the work honestly. |

## What remains unknown

- Whether any collected guidance is **factually correct**: no reviewer has scored factual support (0 of 9 candidates carry a human decision).
- Whether any source is **better than another**: 1 source(s) have evidence.
- Whether any candidate **helped a household**: household outcomes are out of scope here (WEL-33).
- Model-assisted extraction quality: 0 inference call(s) are recorded (none).
- 10 discovered hint(s) have no access assessment yet, so their yield is unmeasured.

## Not claimed

This report does not claim any quality improvement, does not rank sources, does not treat popularity or link counts as quality, and does not use rejected or deferred rows as evidence that a source is bad. The sample above is too small to support any of those claims.
