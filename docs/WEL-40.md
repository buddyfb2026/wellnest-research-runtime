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
python3 -m pytest tests -q                              # focused fixtures, no network
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

## What is stored (`research/db.py`, schema version 1)

| table | meaning |
|---|---|
| `source_hints` | where we may look: type, attribution, **access basis**, fetch permission, usage constraints, discovery origin. Hints are not evidence. |
| `fetch_attempts` | every attempt, including `blocked`, `error`, and `skipped_policy` (no permitted access → never requested). |
| `evidence` | append-only retrieved content: `content_kind` (`live` or `fixture`), sha-256 `content_hash`, `version_no` + `supersedes_id`, `fetched_at`, `published_at` + `published_at_basis` (or `unknown`), `modified_at`, excerpt, `injection_flags`. |
| `evidence_text` | full extracted text per evidence row (for grounding checks). |
| `inference_calls` | provider, model, prompt hash, ok/error — the audit trail for the call budget. |
| `candidates` | household problem, proposed prepared action, **observations** (verbatim quotes proven present in the evidence text), **inferences**, dropped unsupported claims, relevance conditions, lead time / expiry (+ basis), product mentions with a grounded flag, source attribution, `proposed_destination` (always NULL here), `stock_price_claims` (`not_verified`), `state` pending/approved/rejected/deferred, `state_reason`, `state_set_by`, `publishable` (never set by the worker). |
| `runs` | run status; a run with any failed write is `failed`. |

## Rules enforced in code

* Only allowlisted URLs with `fetch: true` are requested; robots.txt is checked per origin and a
  disallow blocks the fetch. URLs found inside retrieved content are never followed.
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
* Every observation quote is re-checked as a verbatim substring of the evidence text; others are
  demoted to `unsupported_claims`. No grounded observation → `rejected`. Product names not in
  the text → `deferred: unsupported_product_identity`. Model confidence/approval fields are ignored.
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
* Candidate quality depends on the local model; the grounding check protects against invented
  quotes and products but not against dull proposals. Reject/defer is a valid outcome.
* Full-text storage in `evidence_text` is for grounding and review only; usage constraints per
  source govern any reuse.
