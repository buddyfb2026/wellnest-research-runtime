# WEL-49 — permissive recipe sources (configuration amendment, 2026-09-16)

Spencer approved three permissive recipe sources: Public Domain Recipes, FOSS Family Recipes and Foodista. This amendment adds them to the existing registry. The engine, schema, migrations (1–7) and normalizer are unchanged; the locator gets only the bounded v5 section-end correction described below. It is an unmerged configuration. It is not a live grant, schedule activation, model result, editorial approval or publication.

## What changed

- `sources/roster.json`: three publishers appended last (`public_domain_recipes`, `foss_family_recipes`, `foodista`) plus three surfaces appended last:
  - `https://fossrecipes.com/recipes/orzo-chicken` — `site_article`, `retain`/`permitted`, CC0 recipe text.
  - `https://publicdomainrecipes.com/easy-chicken-and-rice-casserole/` — `site_article`, `retain`/`permitted`, public domain / Unlicense recipe text.
  - `https://www.foodista.com/` — `site_index`, `candidate`/`unknown`, which is **effective-denied**. The Foodista content licence is CC BY 4.0 (not CC0), but automated access is unverified: the coordinator's robots.txt request returned a non-retryable safe-open error. Foodista is not operationally qualified, and no other route may be tried.
- `sources/allowlist.json`: two `fetch=true` entries for the two named recipe pages, appended last. The existing 18 entries, and therefore the manual run's first ten grants, keep their order. There is no Foodista entry.
- Every pre-existing publisher, surface, alias, denial, historical-seed disposition and the 10-URL working set is unchanged. The new pages are not in the working set.
- Only the two exact recipe URLs are qualified. Site roots, sibling recipes and based.cooking (the same project lineage as Public Domain Recipes, not an independent publisher) are not registered or granted.

After the amendment, the projected roster has 17 publishers, 25 surfaces and 25 historical seeds. The allowlist has 20 unique URLs, 15 of them with `fetch=true`.

## Source-use basis (text only)

| Source | Basis | Credit | Exclusions |
|---|---|---|---|
| FOSS Family Recipes | `fossrecipes.com/license.html`: recipes are public domain under CC0; attribution appreciated, not required | Keep "FOSS Family Recipes (fossrecipes.com)" | Images; site design (separately CC BY 3.0, HTML5 UP) |
| Public Domain Recipes | The site states all recipes are public domain; the project is under the Unlicense | Keep "Public Domain Recipes; contributor <name>" | Images, logos, contributor donation addresses |
| Foodista | CC BY 4.0 (terms effective 2026-01-23) | Required, with licence link and indication of changes | Pending access verification; photos |

A registry `retain`/`permitted` row only stops denying. Collection still needs the allowlist grant and the Fetcher's robots, origin, login and redirect checks. Source clearance is not editorial approval, and every resulting recipe record stays unapproved and unpublishable.

## Tests

`tests/test_wel49_permissive_recipes.py` uses the committed files and synthetic, labelled fixture pages; no network or model calls are made. It checks that:

- every pre-existing surface keeps its denial and identity result;
- the 8 previously denied surfaces stay denied;
- the working set, seeds and first-ten manual grants are unchanged;
- the new surfaces have exact identity and agent provenance;
- Foodista is denied even if an allowlist entry reasserts it, and no request reaches it;
- unlisted sibling pages are never requested;
- evidence and attribution are recorded, heading-tier manifests are produced, and a no-model run records only failed/unpublishable placeholders;
- a replay adds no duplicates.

`tests/test_wel49.py` changes only its pinned totals (14→17 publishers, 22→25 surfaces, 18→20 allowlist entries, 13→15 fetch grants).

## Heading boundary: locator v4 finding and v5 correction

**Finding under `wel48_locator_v4`** (historical; recorded in the roster reasons at 2026-09-16T15:51:05Z). The heading tier took non-step lines as step units:

- Public Domain Recipes: the page footer ("Contributor(s)", contributor name, cryptocurrency donation addresses, "Related", tags, Previous/Next).
- FOSS: a trailing "Note" heading and its note.

The effect: a faithful extraction (true steps only) was `incomplete` with `steps: located_units_not_fully_covered`, so `cooking_content_usable` was false.

**Correction in `wel48_locator_v5`.** `research/recipe_locate.py` adds the exact whole-line section ends `note` and `contributor(s)` beside the incumbent `notes`, and bumps `LOCATOR_VERSION`.

- On the retained real pages, v5 locates exactly 4 (orzo) and 3 (casserole) step units.
- Faithful extractions have no step-coverage unknown.
- Proposals that re-add the old v4 lines are refused (`not_a_whole_located_unit`) and are not usable.
- The roster reasons still describe the v4 manifests as they were at assessment time; this section is the current correction.

**What does not change:**

- Unknown headings are still kept as steps (fail closed; for example "Chef Guidance").
- No same-rank-heading cut and no site-specific logic are added. A future site's different footer heading can still contaminate steps and would need its own bounded alias.
- Existing v4 manifests and recipe versions remain as history. Raw HTML is not stored, so v5 applies only at the next ordinary collection, as a new manifest revision; each affected record then needs a new inference call.

**Scalars (unchanged).** Public Domain Recipes prefixes its scalar lines with emoji (`⏲️ Prep time: 5 min`), so no scalar role is located. A model quote such as `Prep time: 5 min` still falls inside the recipe bounds and parses under the existing grammar. Neither source states a total time, and none is derived.
