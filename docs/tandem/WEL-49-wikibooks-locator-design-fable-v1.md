# WEL-49 — retained Wikibooks recipe locator support (Tandem design, Fable v1)

Author: Claude Fable (design only). Baseline: `37a8179a9f80598f31dc6d31bd0b4b7281730426`.
Status: proposal for a fresh critic. Nothing here is implemented, agreed, or live.

**Smallest-mechanism answer.** The pages yield zero recipes because `_heading_recipe` finds no
step heading (`Procedure` ∉ {`instructions`,`directions`}) and returns `None`; adding that one
literal is what *finds* the recipe, and the only further necessity is that the found recipe be
*correct*: without three more line rules the same pages would emit `[edit | edit source]` as a
unit, run steps through Notes/`Retrieved from`/Categories/Search chrome, and name the recipe
with the `<title>` chrome line.

## 1 Problem/objective

Three retained real Wikibooks Cookbook pages produce 3 evidence rows and 0 located recipes under
`wel48_locator_v6`. Objective: a narrow extension of the existing `research.recipe_locate`
heading tier so the same retained bytes locate exactly one recipe each with exact inventories
4/7, 7/7, 5/4, a grounded visible name, and no chrome units. No new tier, pipeline, schema,
scalar grammar, prompt, binding, or source change. Not a claim of complete recipes, scalar
support, live improvement, or Wikibooks breadth.

## 2 Repo/receipt facts

Reproduced locally at the frozen HEAD (read-only; `extract(body.decode())` on each `.body`):

| Page (`https://en.wikibooks.org/wiki/Cookbook:…`) | body sha256 (`receipts.json`) | bytes | text sha256 = `content_hash` | v6 `recipes` |
|---|---|---|---|---|
| `Kid-Friendly_Pasta` | `cbd1ec4a…3af81d` | 59239 | `0c8555af…212b35` | `[]` |
| `Chicken_Fajitas` | `09d538dc…` | 61263 | `ac2e37dd…d5c78b` | `[]` |
| `Tuna_Casserole` | `565b1f22…` | 60927 | `c7ec0e55…22876a` | `[]` |

- `extract(...).text` is byte-identical to the retained `.txt` for all three (the `.txt` has no
  trailing newline); `.body` file names are `sha256(url)`; each body hashes to its receipt value.
- All three: HTTP 200, robots allowed, one hop, 2026-09-21T19:38:54–55Z.
  `work/wikibooks-baseline/yield.json`: `recipe_count 0`, `usable 0`, `complete 0`,
  `publications 0`, `model null`, `inference_calls 0`.
- Markup: no JSON-LD, no microdata (`ld+json` 0, `itemprop` 0) → tiers 1–2 produce no nodes.
  Headings are `<h1>Cookbook:<name>`, `<h2>Ingredients`, `<h2>Procedure`, plus Tuna's
  `<h2>Notes, tips, and variations`. One `<ol>` per page, under `Procedure`.
- Cause of 0: `recipe_locate.py:251` accepts only `instructions`/`directions`; `step_i is None`
  → `return None` (`:252-253`). `_Markup.handle_endtag` (`:167`) has the same two literals.
- Retained text: each section-heading line is followed by the exact line `[edit | edit source]`
  (2, 2, 3 occurrences; `_normalize` already folds whitespace, so exact equality suffices — no
  case/whitespace normalization is evidenced or proposed). Steps are followed by
  `Retrieved from "https://en.wikibooks.org/w/index.php?title=…&oldid=…"`, then `Categories:`,
  category lines, `Search`, `Cookbook:<name>`, `Add languages`, `Add topic`.
- Title: `extract.title` = `Cookbook:<name> - Wikibooks, open books for an open world`, which is
  also text line 0 (`<title>` is not skipped). Today `_first_span(text, title, anchor)` would
  ground the name on that chrome line. The plain `<name>` is a whole line exactly once (line 3);
  `Cookbook:<name>` near the footer is a different line.
- Scalars are fused (`Servings4 children`, `Servings6`, `Time45 minutes`); `_role_span` requires
  `:` or whitespace after the label, so `roles == {}` today and must stay `{}`.
- Manifest semantics: `locator_version` is inside the manifest, so it feeds `manifest_hash`,
  which feeds `extraction_key`; `attach_manifest` runs only from `research/evidence.py` on
  collection (`:52`, `:71`).
- Baseline is already red independent of this work: 10 failures in the suites of §6 —
  4 stale `wel48_locator_v5` pins, 1 bump test that uses `v6` as its "new" version, 5 absent
  `/tmp/wel42-…`/`/tmp/wel48-…` inputs. See §6/§7.

## 3 Minimal design/contract

All changes are in `research/recipe_locate.py`, heading tier only. Four rules, one constant each.

1. **Step heading.** `STEP_HEADINGS = ("instructions", "directions", "procedure")`, used at both
   existing sites (`_heading_recipe` whole-line casefold match; `_Markup.handle_endtag`, so the
   ordered-list `Tip:` rule behaves identically under `Procedure`). Match stays whole-line.
2. **Edit control.** `EDIT_CONTROL_LINE = "[edit | edit source]"`. A stripped line exactly equal
   to it is never an ingredient or step unit. Exact, case-sensitive, whole-line.
3. **Boundaries** (step loop, checked where `_is_section_end` is checked today; first hit ends
   collection):
   a. *MediaWiki next heading*: a line whose immediately following line equals
      `EDIT_CONTROL_LINE`. This is the evidenced structural marker for every Wikibooks section
      heading, so Tuna's `Notes, tips, and variations` ends steps without adding that page's
      literal to `SECTION_ENDS` (which stays unchanged).
   b. *MediaWiki footer*: a stripped line that fully matches
      `Retrieved from "https?://[^"\s]+"`. Everything after it (categories, search, language
      chrome) is therefore unreachable.
   The ingredient range is already bounded by `ing_i+1:step_i`; rule 2 is its only change.
4. **Title candidate.** If `title` fully matches
   `Cookbook:(.+) - Wikibooks, open books for an open world`, the candidate is group 1 and the
   name span is the *unique whole retained-text line* exactly equal to it. Zero or multiple such
   lines → name ungrounded (`start=-1`), hence `slot=None` and no work item (fail closed; never
   fall back to the chrome line). `name.structured_raw` stays `None`; `structured_decoded` is the
   candidate. Any other title form → incumbent `_first_span(text, title, anchor)` unchanged.
   No URL, meal name, ingredient, or step literal appears in code.

**Version: bump to `wel48_locator_v7`.** A v6 manifest and a v7 manifest for these pages differ
in content anyway, but the bump is still required: `locator_version` is the only persisted
statement of which layout semantics produced a manifest, prior semantic changes bumped (v4→v5
`note`/`contributor(s)`, v5→v6 Related), and the bump makes `manifest_hash`/`extraction_key`
distinct for *every* heading-tier page collected afterwards, so no v7 reading can be mistaken for
or deduplicated against a v6 one. It rides existing behavior: a new manifest revision is appended
and `evidence_current_manifest` repointed only on next collection.

Unchanged: `extract.py` (text, title, `content_hash`), JSON-LD/microdata tiers, structured-
disagreement carry-over, `Tip:` rule, `SECTION_ENDS`, `ROLE_LABELS`/`_role_span`, slot hashing,
bounds computation, binding, schema, worker, prompts.

Known limit (accepted, not fixed): `_Markup` does not reset on a MediaWiki next heading, so a
later `<ol>` would join `heading_ordered_steps`; that list only feeds the `Tip:` rule and none
of the three pages has a second `<ol>`.

## 4 Files in/out

In (implementation pass, not this pass):
- `research/recipe_locate.py` — the four rules and the version constant (~25 lines).
- `tests/test_wel49_wikibooks_locator.py` — new (§6).
- `tests/fixtures/wel49_wikibooks/` — new: three `<sha256(url)>.body` copied byte-for-byte
  (181,429 bytes total), three `.txt` byte-for-byte (4,386 bytes), and `PROVENANCE.json` with,
  per page: url, final_url, status 200, robots `allowed`, hop count 1, captured_at, body sha256,
  text sha256, `oldid` revision URL, licence note (Wikibooks text, CC BY-SA 4.0), and the sha256
  of the source `receipts.json`. The full body is kept because trimming chrome would break the
  body hash and the HTML→extract→`content_hash` proof; 181 KB is the smallest representation
  that still exercises the real subject. `receipts.json` itself is **not** committed (its
  headers carry `set-cookie` and `x-client-ip`); the robots body is not needed.
- `docs/WEL-49-wikibooks-locator.md` — short change note, as prior locator bumps have.

Out: `research/library.py`, `scripts/prepare_wikibooks_profile.py`, `scripts/qualify_wikibooks.py`,
`scripts/eval_wikibooks_retained.py`, `tests/test_wel49_wikibooks_profile.py` (builder-owned);
`research/extract.py`, `research/recipes.py`, `research/recipe_extract.py`, `research/db.py`,
worker, allowlist/roster/profile, any existing test file, anything under `work/`.

## 5 Failure and preservation design

- `locate` stays pure: no I/O, no state; the new rules are string comparisons and one
  `fullmatch`. A crash story beyond "exception → existing `try/except` in `extract`/`locate`
  callers" does not exist and none is added. No queue, retry, backfill, or recovery machinery.
- Locator support alone does **not** mutate any existing store and does **not** reprocess
  historical evidence: stored v6 manifests (including `recipes: []` rows) stay current until the
  URL is next collected, exactly as `test_locator_bump_without_recollection_is_a_noop` encodes.
- Degradation is fail-closed per rule: no unique name line → `slot=None`; no ingredient or step
  units → `None` as today; unsupported fused scalars → `roles={}` → unknown under existing bind.
- Negative controls (synthetic, in the new test file; each asserts exact unit literals):
  1. Instructions page with the step `Follow the same procedure for the second batch.` and a
     whole-line step `Procedure` absent → step kept; `procedure` inside prose is never a heading.
  2. A page whose first whole-line match is `Instructions` and that also contains a later line
     `Procedure` → `step_i` is still the first match; incumbent precedence unchanged.
  3. Steps `Press [edit | edit source] to change the label.` and `[Edit | Edit Source]` → both
     kept as steps (not exact); and the line before them is *not* treated as a heading.
  4. Step `Retrieved from the oven, rest the casserole for 5 minutes.` and step
     `Categories: choose mild or hot salsa.` → kept; only the full quoted-URL form ends steps.
  5. Title `Cookbook:X - Wikibooks, open books for an open world` with `X` as a whole line
     twice → name `start=-1`, `slot=None`; with `X` only inside a longer line → same.
  6. Non-Wikibooks title containing `Cookbook:` (e.g. `Cookbook: Soup | Fixture`) → incumbent
     `_first_span` result, byte-identical to v6 apart from `locator_version`.
- Preservation is proven by the incumbent suites in §6 producing the same manifests modulo the
  version string.

## 6 Acceptance suites/oracles

New `tests/test_wel49_wikibooks_locator.py` (reads only `tests/fixtures/wel49_wikibooks/`):

- **Fixture integrity**: each `.body` sha256 == `PROVENANCE.json` == file-name rule
  `sha256(url)`; each `.txt` sha256 as in §2.
- **Text invariance**: `extract(body.decode("utf-8")).text.encode() == txt_bytes` and
  `content_hash ==` the §2 text sha256 for all three (unchanged from v6).
- **v6 baseline oracle**: `locate(html, text, title)` with both `STEP_HEADINGS` sites
  monkeypatched to the v6 pair returns `recipes == []` for all three (0/0/0) — pins the cause.
- **Corrected oracle** (`locator_version == "wel48_locator_v7"`, exactly one recipe, `tier ==
  "heading"`): ingredient/step counts 4/7, 7/7, 5/4; full ordered literal lists equal the
  retained `.txt` lines between the headings (first/last: `1 lb whole-wheat spaghetti`…`Serve.`;
  `1 Tbsp olive oil`…`Serve with tortilla shells … guacamole.`; `3 cans of tuna in water`…`Let
  cool for 5 minutes and serve.`).
- **Exclusions**: no unit literal equals `[edit | edit source]`; none starts with `Retrieved
  from`, `Categories:`, `Search`, `Add `, or `Cookbook:`; Tuna has no unit from `Notes, tips,
  and variations` or its two note lines; `bounds.end ==` last step end.
- **Name/slot**: `text[name.start:name.end]` is exactly `Kid-Friendly Pasta` / `Chicken
  Fajitas` / `Tuna Casserole`, starts a line, is not at offset 0; `slot == "name:" +
  sha256(casefold(literal))[:16]`; `slot_disambiguated == 0`.
- **Spans**: for every unit and name, `0 <= start < end <= len(text)` and the slice equals the
  expected literal with no leading/trailing whitespace.
- **Scalars**: `roles == {}` for all three; no servings/time claim is asserted anywhere.
- **Negative controls** 1–6 of §5.

Smallest affected incumbent suite (must show no *new* failure against the recorded baseline):
`tests/test_wel48_locate.py`, `test_wel48_extract.py`, `test_wel48_related_boundary.py`,
`test_wel49_heading_boundaries.py`, `test_wel49_permissive_recipes.py`, `test_wel48_bind.py`,
`test_wel48_manifest.py`, `test_wel48_replay.py`, `test_wel48_identity.py`,
`test_wel48_no_hardcoding.py`, `test_wel48_wel49_integration.py`.
Recorded baseline at `37a8179` for this list plus `test_wel48_corpus.py`: 73 passed, 10 failed
(§2). Expected after the change: the 4 `v5`-pin failures remain (they now read `v7 != v5`);
`test_locator_bump_applies_on_next_collection` flips to pass only because `v6` is again a
different version — report it as incidental, not as a fix.

Retained replay oracle (builder-owned `scripts/eval_wikibooks_retained.py`, no `--model`, new
isolated DB, offline): 3 evidence rows; 3 current manifests at v7 with one located recipe each;
`inference_calls 0`; `publications 0`; `complete_recipe_count 0`; `usable_recipe_count 0`. Any
`recipe_versions` rows are whatever existing provider-`none` semantics write
(`inference_unavailable`, non-publishable) and are recorded, not tuned.

NOT VERIFIED and not fabricated: `tests/test_wel48_corpus.py` and
`test_wel48_manifest.py::test_ambiguous_correspondence_is_incomplete` depend on absent `/tmp`
inputs; they stay reported as NOT VERIFIED.

## 7 Rollout/degradation

1. Implement §3 + fixtures + new test on a branch off `37a8179`; run the new file, then the §6
   incumbent list; record pass/fail against the baseline set verbatim.
2. Run the retained replay once into a new output directory; record the §6 replay numbers.
3. Fresh critic review; on PASS, stop. Merge follows the opposite-engine rule; no cut, deploy,
   live DB, service restart, collection, or network request is part of this work.

Effect after merge: none on existing stores until a Wikibooks Cookbook URL is next collected
under whatever source profile is separately approved; then one new v7 manifest revision per
evidence row via normal `attach_manifest`. Rollback is reverting the commit; v7 manifests
already written remain valid, versioned history. If a future Wikibooks page lacks a unique name
line or uses another step heading, it degrades to `slot=None` or `recipes=[]` — today's behavior.

Done = new real-receipt regressions green, no new incumbent failure, replay numbers recorded,
critic PASS.

## Self-lint

- Seven numbered sections; design only; no code, test, or builder-owned file touched.
- Every number in §2 was reproduced locally from the retained receipts at the frozen HEAD; the
  §3 rules were dry-run in memory against the three bodies (4/7, 7/7, 5/4, names exact,
  `roles {}`) without writing any file. Boundary 3a was reasoned from the retained text, and an
  earlier dry-run used a literal `SECTION_ENDS` entry instead; 3a itself awaits the
  implementation test.
- No claim of implementation, consensus, live improvement, complete recipes, scalar support, or
  source breadth.
