# WEL-48 corpus — frozen records and exact reviewer inventories

**Frozen 2026-09-15.** Baseline `2b7602f42856ce34c6a18c810f7181bca418bd6f`.
Machine-readable twin: `corpus/manifest.json`. Immutable bytes: `corpus/raw/` (outside git).
**No design file was touched; v3 is under independent review.**

Retrieval used the repository's own boundary — `research.fetch.Fetcher` (scheme, private-host,
origin, login-path and robots gates; redirects surfaced and re-checked per hop, never auto-followed)
— and `research.extract.extract`. No naked urllib, no new dependency, no model call, no bypass.

**Budget: 10 of 10 page requests spent, 6 robots.txt requests. Cap reached; no further retrieval.**

---

## 1. The six records

| id | role | publisher | tier | ingredients | steps | text chars | content_hash |
|---|---|---|---|---|---|---|---|
| R1 | dev | budgetbytes.com | JSON-LD | 9 | 4 | 11,793 | `fcc262853a138ffe…` |
| R2 | **HELD OUT (complete #1)** | cookieandkate.com | JSON-LD | 13 | 11 | 22,808 | `aee1edae865e8d08…` |
| R3 | dev | loveandlemons.com | **non-JSON-LD** | 15 | 3 | 11,581 | `1fd0a4f155ae18d8…` |
| R4 | dev | cookieandkate.com | JSON-LD | 16 | 7 | 14,416 | `6423ef8cfeb417b7…` |
| R5 | dev | cookieandkate.com | JSON-LD | 19 | 5 | 14,800 | `679feb32bbfcd65f…` |
| R6 | **HELD OUT (complete #2)** | cookieandkate.com | JSON-LD | 13 | 4 | 8,128 | `409b13e3152e14b3…` |

**3 publishers, 6 records, 2 complete held-outs** — both retrieved today, neither previously used
for any tuning, and no generation code exists yet to tune. R1 is permanently ineligible as a
held-out: it was inspected in detail across three design rounds.

### Per-record detail

**R1 — `https://www.budgetbytes.com/poor-mans-burrito-bowls/`** (dev; pre-existing evidence, not
re-fetched)
Long-introduction case: first ingredient at char **2,870 of 11,793**. 9 ingredients, 4 steps,
correspondence **exact 9 / ambiguous 0 / unmatched 0**; all 4 steps exact.
Yield structured `['6']`, rendered `6`. Times `PT5M / PT20M / PT25M`.
Rendered time labels are `Prep` / `Cook` / `Total` — **not** `Prep Time` / `Cook Time` / `Total Time`.

**R2 — `https://cookieandkate.com/best-ratatouille-recipe/`** — **HELD OUT, complete**
13 ingredients, 11 steps, correspondence **exact 13 / ambiguous 0 / unmatched 0**; all 11 steps exact.
Yield structured `['4', '4 servings']`, rendered `4 servings` (**readings agree**).
Times `PT20M / PT40M / PT1H` vs rendered `20 minutes / 40 minutes / 1 hour` — **all three agree**.

**R3 — `https://www.loveandlemons.com/black-bean-soup/`** (dev) — **the non-JSON-LD case**
Zero JSON-LD `Recipe` nodes and zero `schema.org/Recipe` microdata (one unrelated `ld+json` blob;
45 WP-Recipe-Maker class attributes present but no consumable structured recipe). The recipe is
recoverable **only** from rendered headings — `Ingredients` at line 62, `Instructions` at line 79.
Reviewer-read: **15 ingredient lines, 3 instruction paragraphs**; servings stated as **`Serves 4`**;
rendered times `15 minutes / 45 minutes / 1 hour`.
Retrieval note: this URL **redirected** (2 hops) to `…/black-bean-soup-recipe/`; the Fetcher
re-evaluated the gates on the hop rather than following blindly.
There is **no structured reading to compare against**, so this record cannot exercise conflict
detection — only locator tier 3 and coverage.

**R4 — `https://cookieandkate.com/best-lentil-soup-recipe/`** (dev) — **the ambiguous-correspondence case**
16 ingredients, 7 steps; correspondence **exact 15 / ambiguous 1 / unmatched 0**. One structured
ingredient string matches **more than one** visible unit, which is the only instance of that branch
in the corpus. All 7 steps exact. Yield `['4', '4 servings']` / rendered `4 servings`. All three
times agree.

**R5 — `https://cookieandkate.com/vegetarian-chili-recipe/`** (dev) — **the genuine conflict case**
19 ingredients, 5 steps; correspondence **exact 19 / ambiguous 0 / unmatched 0**; all 5 steps exact.
All three times agree.
**`recipeYield` carries two non-equal readings — `'4'` and `'4 to 6 servings'` — and the rendered
card states `4 to 6 servings`.** A consumer taking `recipeYield[0]` would publish a precise `4`
where the source states a range. This is real, found in live content, and is the corpus's only
genuine disagreement.
It is a **yield** disagreement, **not** an ingredient-quantity disagreement — see gap G2.

**R6 — `https://cookieandkate.com/spicy-vegan-black-bean-soup/`** — **HELD OUT, complete**
13 ingredients, 4 steps, correspondence **exact 13 / ambiguous 0 / unmatched 0**; all 4 steps exact.
Yield structured `['6', '6 servings']`, rendered `6 servings` (**agree**).
Times `PT10M / PT45M / PT55M` vs rendered `10 mins / 45 mins / 55 minutes` — **all three agree**.

---

## 2. Recorded fetch outcomes — truthful, including failures

| url | outcome | http | robots | note |
|---|---|---|---|---|
| `cookieandkate.com/best-lentil-soup-recipe/` | ok | 200 | allowed | R4 |
| `www.allrecipes.com/recipe/223042/chicken-parmesan/` | **blocked** | 403 | allowed | robots permitted the path; the server refused our agent |
| `www.loveandlemons.com/black-bean-soup/` | ok | 200 | allowed | R3; 2 hops, redirect re-checked |
| `www.myplate.gov/myplate-kitchen/recipes` | **blocked** | 403 | allowed_no_robots | intended 3rd-publisher (government) source; refused |
| `cookieandkate.com/best-vegetarian-chili-recipe/` | **error** | 404 | allowed | guessed slug — wrong |
| `cookieandkate.com/easy-guacamole-recipe/` | **error** | 404 | allowed | guessed slug — wrong |
| `cookieandkate.com/vegetarian-chili-recipe/` | ok | 200 | allowed | R5 |
| `cookieandkate.com/best-ratatouille-recipe/` | ok | 200 | allowed | R2 |
| `cookieandkate.com/spicy-vegan-black-bean-soup/` | ok | 200 | allowed | R6 |

**9 URLs, 10 page requests** (R3 consumed two through its redirect hop), 6 robots requests.
Two requests were wasted on guessed slugs; after that I harvested real permalinks from a page I
already held, at **zero** request cost, using the repository's `discovery.extract_hints`.

---

## 3. Material finding: JSON-LD strings carry undecoded HTML entities

**This changes a number the design relies on, so it is reported rather than quietly fixed.**

First-pass correspondence looked alarming — R2 matched only 5 of 13 ingredients, R5's steps only
2 of 5 — which would have meant the "structured content appears verbatim in the rendered text"
property did not generalize beyond Budget Bytes.

It does generalize. The mismatch was an **encoding** difference, not absence. `research/extract.py`
parses the rendered body with `convert_charrefs=True` (`extract.py:19`), so body text holds real
characters (`¼`, `’`), while JSON-LD string values keep raw entities (`&frac14;`, `&#8217;`).
Comparing them directly compares two encodings of the same text.

Applying `html.unescape()` (plus inline-tag stripping) to structured strings before matching:

| record | before | after |
|---|---|---|
| R1 ingredients | 9 exact / 0 amb / 0 unmatched | **9 / 0 / 0** (unchanged) |
| R2 ingredients | 5 / 0 / 8 | **13 / 0 / 0** |
| R4 ingredients | 12 / 1 / 3 | **15 / 1 / 0** |
| R5 ingredients | 17 / 0 / 2 | **19 / 0 / 0** |
| R6 ingredients | 9 / 0 / 4 | **13 / 0 / 0** |
| R5 steps exact | 2 of 5 | **5 of 5** |
| R2 steps exact | 6 of 11 | **11 of 11** |

Unicode NFKC normalization recovers **none** of these — it is specifically HTML-entity decoding.
Budget Bytes happened not to use entities, which is why three design rounds never surfaced it.

**Consequence for the reviewers (design change NOT made here):** the v3 locator spec says
structured readings are retained and matched against `evidence_text`, but does not specify entity
decoding. Implemented literally, it would mark most real records `incomplete` via P13 and fail B4
coverage. The inventories above are frozen **with** decoding, since that is the true content.

---

## 4. Gaps — explicitly reported, not filled

| id | gap | status |
|---|---|---|
| **G1** | **No genuinely materially-incomplete record.** All six state ingredients, steps, servings and at least one time. R3 initially looked incomplete but states `Serves 4` under a `Serves` label. | **UNFILLED.** Not manufactured. A synthetic incomplete record would be a fixture, and inventing one to hit a quota would corrupt the corpus. |
| **G2** | **The conflict case (R5) is a yield disagreement, not an ingredient-quantity disagreement.** The design's per-ingredient conflict branch has no live coverage. | **PARTIALLY FILLED.** R5 genuinely exercises structured-vs-visible disagreement; per-ingredient conflict must be covered by a **clearly labelled fixture**, with this gap stated in the results. |
| **G3** | **Publisher concentration.** 4 of 6 records, and **both** held-outs, come from cookieandkate.com. | **UNFILLED.** allrecipes.com and myplate.gov both returned 403; the page budget is exhausted. A cross-publisher held-out needs additional budget. |
| **G4** | **Official terms / recipe-policy pages not retrieved.** `cookieandkate.com/terms-of-use/` and `/cookie-and-kates-photo-and-recipe-policy/` were discovered in-page but **not fetched** — the 10-page cap was already spent, and terms pages count against it. | **UNFILLED, explicit.** Publication rights for all three publishers are **UNKNOWN**. Nothing here asserts any. |
| **G5** | Two publishers (allrecipes, myplate) returned 403 despite robots permitting the path. | Recorded as real outcomes. Robots permission and server access are different things. |

---

## 5. Rights and access — unknowns stay unknown

- Robots status is recorded per record and was **allowed** for every retrieved URL
  (`allowed_no_robots` for myplate.gov, which then refused with 403).
- **Robots permission is not a licence.** These bytes were retrieved for **bounded review evidence**.
  No publication right, reuse right or republication right is claimed for any of them.
- **No publisher's official terms were read** (G4). Every publication-rights question for
  budgetbytes.com, cookieandkate.com and loveandlemons.com is **UNKNOWN** and must be resolved
  separately before anything derived from these records is published.
- Raw bytes are stored **outside the git worktree** at `/tmp/wel48-coordination/corpus/raw/`,
  with SHA-256 per file recorded in `manifest.json`, precisely because reuse rights are unresolved.
- `budgetbytes.com` is still **not** in `sources/allowlist.json`; reviewer-authored entries with
  `access_basis` and `usage_constraints` are required for all three publishers before any
  collection through the normal worker path.

---

## 6. What is frozen

For each record `manifest.json` carries: `source_url`, `final_url`, redirect hop count, publisher
host, retrieval outcome (`http_status`, `robots_status`, `fetched_at`), `sha256_raw_bytes` and byte
length of the immutable source, the `content_hash` from `research.extract.extract` at baseline,
title, publication/modification dates and basis, injection flags, locator tier, and the exact
expected inventory (ingredient/step counts, correspondence counts, yield readings structured and
rendered, and per-time structured-vs-rendered agreement).

Held-out records R2 and R6 have full inventories recorded here for reviewer inspection, as directed.
No generation code exists yet, so nothing has been tuned against them.

**No model call was made. No design file was modified. No product code was written.**
