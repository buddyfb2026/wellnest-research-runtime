# WEL-49 Wikibooks locator — Stan design correction (2026-09-21)

Audience: Astra (critique) → existing builder (implement). Design only. No merge/deploy/publication.

Baseline brief: `docs/tandem/WEL-49-wikibooks-locator-design-fable-v1.md` (Fable v1).
Frozen main noted in that brief. Do not widen scope beyond `research/recipe_locate.py` heading tier + focused tests/fixtures.

## Corrections (binding)

### 1) Separate URL-hash from body-hash (do not conflate)

Fable v1 correctly stores facts but the wording invites mix-ups. Lock these as **distinct**:

| Symbol | Definition | Used for |
|---|---|---|
| `url_hash` | `sha256(canonical_url)` | **Filename / retention key** for `.body` (and pairing) only |
| `body_hash` | `sha256(raw_body_bytes)` | **Integrity** of the retained HTML bytes; must match receipt |
| `text_hash` / `content_hash` | `sha256(extracted_text)` | Evidence/text identity after `extract`; not interchangeable with `body_hash` |

Rules:
- Never name a file with `body_hash` and then treat that name as the URL key (or the reverse).
- Fixtures/`PROVENANCE.json` must record **all three** where HTML is retained: `url`, `url_hash`, `body_hash`, `text_hash`.
- Tests that open `sha256(url).body` must assert `sha256(file_bytes) == body_hash` from the receipt — proving the map, not assuming it.
- Locator design must not say “body file names are sha256(url); each body hashes to its receipt value” without naming the second value `body_hash`. Rewrite any prose that uses one word “hash” for both.

### 2) Narrow heading detection (reject overly broad “next line is edit-control”)

Fable rule 3a (“any line whose next line equals `[edit | edit source]` is a MediaWiki heading / step boundary”) is **too broad**: any prose line accidentally followed by that chrome would terminate or reclassify sections.

Replace 3a with a **closed heading recognizer**:

A line L is a MediaWiki section heading for boundary purposes only if **all** hold:
1. L stripped is non-empty and is **not** exactly `EDIT_CONTROL_LINE`.
2. The immediately following line is exactly `EDIT_CONTROL_LINE`.
3. L casefold-matches one of the **closed** heading labels already in play for this change:
   - ingredient side: existing ingredient headings only (no expansion in this ticket unless already in v6),
   - step side: `instructions` | `directions` | `procedure` (the sole step-heading addition),
   - optional documented end labels already evidenced on the three pages (e.g. Tuna’s notes heading) **listed as exact casefold literals** — not “any line before edit-control”.

Do **not** treat arbitrary capitalized lines + edit-control as headings. Do **not** add open-ended heuristics (title-case, short line, etc.).

Footer rule 3b (`Retrieved from "…"`) stays as an exact footer terminator for the step loop.

### 3) Unchanged (confirm)

- Single constant add for step heading: `procedure` alongside `instructions`/`directions`.
- Exact whole-line `EDIT_CONTROL_LINE` never becomes an ingredient/step unit.
- Title chrome stripping only for the Wikibooks title pattern; fail closed if name line not unique.
- Version bump to `wel48_locator_v7`; no recollection/backfill; no schema; no live fetch in this ticket.
- Scalars stay unparsed when fused; do not invent totals.

## Acceptance delta for critic/builder

1. Document + tests use `url_hash` / `body_hash` / `text_hash` distinctly; one regression fails if filename key is asserted equal to body content hash.
2. Synthetic negative: a non-heading prose line immediately before `[edit | edit source]` does **not** end steps / does **not** count as a heading.
3. Three retained Wikibooks pages still meet the exact inventory targets in Fable §6 once implemented — without broader heading invention.

## Out of scope

New sources, roster changes, model calls, publication, schema migrations, worker schedule changes.
