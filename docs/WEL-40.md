# WEL-40 — Real-source evidence storage and reviewable household research candidates

Linear: https://linear.app/bizina/issue/WEL-40/build-real-source-evidence-storage-and-reviewable-household-research

This is the first bounded, manually invoked slice of the WellNest research layer:
**permitted source → durable evidence → reviewable candidate**. No scheduler, no app change,
no publication, no purchases. The old `bin/` runtime is untouched reference material.

## Reproducible setup

Requirements: Python 3.9+ (stdlib only; no third-party packages), `pytest` for tests, and
optionally a local Ollama server for inference.

```bash
# from the repository root
python3 -m pytest tests -q                              # fixtures only; network is refused (one loopback-server test)
python3 -m research.worker run --provider none          # retrieval + storage only; candidates deferred
python3 -m research.worker run --provider ollama        # local inference (default model qwen2.5:14b)
python3 -m research.worker report                       # re-render work/report.md from the database
python3 -m research.worker review 2 approved --by astra --reason "grounded and useful"
```

Defaults: database `work/research.sqlite`, allowlist `sources/allowlist.json`, report
`work/report.md` (all under the git-ignored `work/`). Override with `--db`, `--allowlist`,
`--report`, or env `WN_RESEARCH_DB`, `WN_RESEARCH_MODEL_PROVIDER`, `WN_RESEARCH_OLLAMA_MODEL`,
`WN_RESEARCH_OLLAMA_URL`. The worker never opens `ri_db` or any application database.

Hard caps: at most 10 source URLs and 10 inference calls per run (`--max-urls`, `--max-inference`
can lower them, never raise them). One model call per evidence row, no automatic retries.

## What is stored (`research/db.py`, schema version 3)

| table | meaning |
|---|---|
| `source_hints` | where we may look: type, attribution, **access basis**, fetch permission, usage constraints, discovery origin. Hints are not evidence. |
| `fetch_attempts` | every attempt, including `blocked`, `error`, and `skipped_policy` (no permitted access → never requested). |
| `evidence` | append-only retrieved content: `content_kind` (`live` or `fixture`), sha-256 `content_hash`, `version_no` + `supersedes_id`, `fetched_at`, `published_at` + `published_at_basis` (or `unknown`), `modified_at`, excerpt, `injection_flags`. |
| `evidence_text` | full extracted text per evidence row (for grounding checks). |
| `inference_calls` | provider, model, prompt hash, ok/error — the audit trail for the call budget. |
| `candidates` | household problem, proposed prepared action, **observations** (verbatim quotes proven present in the evidence text), **inferences**, dropped unsupported claims, relevance conditions, lead time (+ `lead_time_basis` quote) / expiry (+ basis), product mentions with a grounded flag, source attribution, `proposed_destination` (always NULL here), `stock_price_claims` (`not_verified`), `state` pending/approved/rejected/deferred, `state_reason`, `state_set_by`, `publishable` (never set by the worker), `validation` (v3: JSON `{"kind":"rule",...}` with rule id/version and the exact support and problem quotes, or `{"kind":"free_text","raw_proposal":...}` holding the model's raw output for audit only; NULL on rows created before v3). |
| `runs` | run status; a run with any failed write is `failed`. |

## Which candidates can be pending (`research/rules.py`)

Only one thing produces a `pending` candidate: a **closed registry of supported prepared actions**.
Each rule fixes the action text, the relevance condition and the human-reviewed source sentences
that support it. A rule fires when a reviewed support sentence occurs in the evidence as a
**complete sentence** (same words, same order, both boundaries; case, whitespace and one final
full stop are ignored). A prefix such as "Do not assume that …", a suffix, a question mark, the
tail of the sentence on its own, or any rewording does not match and produces nothing. If the
support sentence is present but the reviewed problem sentence is not, the rule candidate is
`deferred` with reason `rule_support_incomplete`.

The registry currently holds one action, chosen because the demo evidence supports it:

| rule | action | relevance | lead time |
|---|---|---|---|
| `air_fryer_basket_after_each_use` v1 | Remind the household to clean the air fryer basket after each use. | household owns an air fryer | none ("after every use" is a cadence, not an advance notice) |

Support sentence and problem sentence are the two Good Housekeeping sentences in `rules.py`, read
by a reviewer from the evidence of the demo run. This is a curated evidence-to-action mapping,
not language understanding: automatically validated action coverage is deliberately this narrow,
while evidence retrieval and reporting still cover every allowlisted source. Rule candidates carry
`generator = rule:<id>@<version>` and no model inference; the report says so on each one.

**Free-text model proposals never become pending.** They are still validated so the reason is
specific (grounded quotes, invented identities, shopping language, timing), then `deferred` with
`unvalidated_free_text` or `rejected`. Their household problem, action, inferences, relevance
conditions and product names are stored only in `validation.raw_proposal` and are not rendered;
the report shows the source, the reason, the grounded quotes and the dropped claims. A matching
registry sentence in the same evidence does not change this: the rule candidate and the model's
proposal are separate rows. The regex blacklists for price/stock/purchase and brand-like names
are diagnostics, not the safety boundary; the closed registry is.

Rows created before schema v3 (`validation IS NULL`) keep their state and reviewer and are
listed in the report under "Legacy candidates" by id, source, state, reviewer and reason, with no
prose. Migration does not re-validate or re-bless them.

## Rules enforced in code

* Only allowlisted URLs with `fetch: true` are requested. The transport never follows redirects;
  the fetcher checks every hop before requesting it: same origin as the allowlisted URL, not a
  loopback/private host, not a login path, and allowed by that origin's robots.txt. A robots.txt
  that is unavailable (5xx, timeout) blocks the fetch; an absent one (404) is unrestricted. At
  most 3 hops. URLs found inside retrieved content are never followed. There is no CLI robots
  bypass; the programmatic one is refused for live content.
* Login walls, 401/403, redirects to login, paywall shells and 404s are recorded as honest
  failures with a reason. Nothing is fabricated for them.
* Identical content for a URL is not re-inserted (hash match). Changed content becomes version
  N+1 pointing at the row it supersedes; prior rows are never edited.
* A failed write rolls back that unit, is listed under `failures`, and the run is `failed`
  (exit code 1).
* Publication dates come only from page metadata (`article:published_time`, `datePublished`,
  `dc.date`, JSON-LD). Absent metadata → `published_at_basis = unknown`. Fetch time is separate.
* Source text is untrusted data. It is wrapped as data in the model prompt; the model has no
  tools. Instruction-like text is flagged on the evidence row and any derived candidate is
  deferred for human review. The worker's own behaviour (what it fetches, what it calls) does
  not change.
* The whole free-text proposal is validated into a small typed representation before anything is
  saved. Wrong field types → `rejected`. Every observation quote is re-checked as a verbatim
  substring of the evidence text; others are demoted to `unsupported_claims`. No grounded
  observation → `rejected`. Price, stock, discount or purchase language in any prose field, or a
  brand/model-like identity not present in the text (in any field, not only `product_mentions`) →
  `deferred` with the reason. Anything that passes all of that is still `deferred` as
  `unvalidated_free_text`. Model confidence/approval fields are ignored.
* `lead_time_days` is kept only when a grounded `lead_time_quote` literally states that value as a
  complete whole number (e.g. "every two weeks" → 14). Decimal, fractional or ranged quantities
  ("1.5 weeks", "half a week", "2-3 weeks") support nothing; the dropped value is listed under
  `unsupported_claims`. Negative, non-finite, boolean or string values are dropped the same way.
* Finalization writes the durable run result first, then renders the report from it, so no report
  shows a finished run as `running`. These are two separate writes (a SQLite row, then a file)
  with no atomicity between them. A report-write failure returns `failed`, updates the `runs` row
  to `failed` with the reason, and keeps the evidence and candidates already committed. If the
  status write itself fails, no report is written and the run returns `failed`. Re-rendering with
  `report` never changes run history.
* `approved` is only set through `review` with a named reviewer and reason. Approval does not
  set `publishable`; publishability is a separate later decision.
* Creator attribution is stored with the candidate; no shopping destination is proposed, no
  affiliate tags are touched, no stock or price claim is made.

## Source access basis in this slice

See `sources/allowlist.json`. Website (robots-checked public pages), Instagram (login-gated,
discovery-only, not requested) and YouTube (no transcript access, discovery-only, not requested)
are deliberately different bases. The Buy Guide entries are seeds from
`seeds/scour_discovery_playbook.json`, not permission to reuse material.

## Known gaps

* No video or newsletter access route exists; those hints stay discovery-only.
* Publication dates are trusted from page metadata as-is (no cross-checking with other channels).
* Automatically validated actions are limited to the registry in `research/rules.py` (one rule).
  Every other proposal, however good, is deferred for a human. Growing coverage means a human
  reading real evidence and adding a rule with the sentences they read; nothing here understands
  language. Reject/defer is a valid outcome.
* The model's role is currently audit-only: its proposals are validated and stored raw, and a
  reviewer can read them in the database, but they do not drive any displayed action text.
* Registry sentences were read from the demo run's evidence; if the live page is rewritten, the
  rule stops matching and the report shows no pending candidate rather than a stale one.
* Full-text storage in `evidence_text` is for grounding and review only; usage constraints per
  source govern any reuse.
