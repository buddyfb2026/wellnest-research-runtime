# WEL-49 — independent Grok implementation review

Review the concrete bounded Wikibooks source-expansion change in
`/Users/buddystudio1/Projects/wellnest-research-runtime-wel49-wikibooks-20260921`.
Base HEAD: `37a8179a9f80598f31dc6d31bd0b4b7281730426`. Changes are uncommitted.
Read-only review; do not fetch sources, run models, mutate any live store, publish,
change services, commit or merge. Offline tests may use temporary databases.

## Mission and binding inputs

Produce real research candidates from three legally qualified practical dinner pages
using the existing pipeline. Source breadth is one new publisher, not three. No
popularity/parent-endorsement claim, no historical cookbook expansion, no social
scraping, no new pipeline or rights schema.

Read these documents in order:

1. `docs/tandem/WEL-49-wikibooks-locator-design-fable-v1.md`
   SHA-256 `65b4868e7a54fc44f7335a6c70bdbb44d1cd8644764524d18795e7bbb39e8e24`.
2. `docs/tandem/WEL-49-wikibooks-locator-STAN-CORRECTION-20260921.md`
   SHA-256 `07b74ab47192b9f0bb20a556a1458dfb79fbdabef92f9741242bfe39c07bc6d4`.
   This supersedes Fable's broad next-line boundary and conflated hash oracle.
   Independent Astra NO OBJECTIONS was supplied before build.
3. `docs/WEL-49-wikibooks-pilot.md` and `docs/WEL-49-wikibooks-locator.md` for
   receipts, actual result, exact test command, limitations and one necessary
   oracle correction (`Add …` cooking steps cannot be banned).

## Changed artifacts and review targets

- `research/recipe_locate.py`: shared `Procedure` literal, exact edit-control exclusion,
  closed section-label boundary, quoted-URL footer, unique whole-line Wikibooks name,
  v7 version. Verify ordinary prose before edit-control cannot terminate directions.
- `tests/test_wel49_wikibooks_locator.py` and `tests/fixtures/wel49_wikibooks/`:
  actual unchanged retained HTML/text, distinct URL/body/text hashes, exact 4/7,
  7/7, 5/4 inventories, all spans and scalar-unknown boundaries, negative controls.
  Raw HTTP headers/cookies are not committed.
- `scripts/prepare_wikibooks_profile.py`: existing profile pattern, exactly three URL
  grants, one publisher; preserve existing roster/denials and default configuration.
  License/source/change notices must survive in the existing attribution field.
- `research/library.py`: full escaped attribution rendered on detail pages in addition
  to the existing short source name. No user/source markup execution or approval change.
- `tests/test_wel49_wikibooks_profile.py`: source config → evidence → bound recipe →
  rendered full notice, non-publishable state and zero-publication assertions.
- `scripts/qualify_wikibooks.py` and `scripts/eval_wikibooks_retained.py`: explicit
  bounded tools requiring fresh output directories. Review only; do not rerun live
  qualification or inference. Replay has no source network fallback.

Do not treat a partial candidate as household readiness. Recipe documents and packs
retain attribution; downstream household consumers outside this repository are not
verified. Current results remain pending and not publishable.

## Evidence to verify

The exact combined command in the locator note returned **131 passed / 9 failed**.
The nine failures are four existing stale v5 pins and five absent historical `/tmp`
fixtures. No existing test was changed; no new failure. Fable baseline was 73 passed /
10 failed for its incumbent list. One existing version-bump test incidentally passes
because its hardcoded v6 is again different from the new version. Missing corpus
tests remain NOT VERIFIED, not waived green.

New tests + profile tests contain 25 passing cases; library and incumbent checks are
included in the combined 140-case result. Direct baseline comparator verified four
full incumbent manifests identical modulo locator_version.

Inspect the isolated existing database `work/wikibooks-v7-qwen/research.sqlite`
read-only and `work/wikibooks-v7-qwen/yield.json`:

- 3 original source evidence rows, 3 v7 current manifests.
- Exactly 3 actual `qwen3.8:27b` recipe-extraction calls, all recorded `ok`.
- 3 schema-valid cooking-content-usable recipes, all pending / publishable 0.
- 0 fully complete recipes (scalar gaps preserved), 0 publications.
- 56.115 seconds; no fresh source requests during replay.
- Actual Library details retain full source URL/license/change notice. Pasta and Tuna
  show `Extraction needs correction`; Fajitas shows `Source doesn’t specify`.

The zero-model control is `work/wikibooks-v7-no-model/yield.json`: 3 manifests,
3 failed unavailable-inference versions, 0 calls and 0 publications. Baseline v6
replay is `work/wikibooks-baseline/yield.json`: 3 evidence, 0 recipe versions.

## Frozen implementation hashes

| File | SHA-256 |
| --- | --- |
| `research/recipe_locate.py` | `2c039dd6aa3462f6349a3f3ca89c21c7332857e43a39633ef7973b006d6df22c` |
| `research/library.py` | `f8cc837ff53031dd9e676b581569b0d0b77b4c3418993586b278dc790f68b925` |
| `scripts/prepare_wikibooks_profile.py` | `65ec43c576d57c6511eb2a1c4273e0f76c9d7332940c45bf0467c792e5f53a66` |
| `scripts/qualify_wikibooks.py` | `7576a03c22e59903536db92fcf0cf733517ac865f794b1626a8f033c726d112b` |
| `scripts/eval_wikibooks_retained.py` | `c2aa96d2f4d67047090c75b2908577145fe40dfb2871246ee68713f201cb77db` |
| `tests/test_wel49_wikibooks_locator.py` | `f3ee97da995ff069cd7338f5e623725a8ae46d4652d47f06154c3b979cb99cb4` |
| `tests/test_wel49_wikibooks_profile.py` | `bc75331d39a1d0629d26630ec9bf1a97d8a5e0e3ed173892a91d4545d1128077` |
| `tests/fixtures/wel49_wikibooks/PROVENANCE.json` | `70437d7f587753c33a02dc63ce299e75869c6a6d9020e1fbaed11b9d45a3b44a` |

Return PASS or numbered material defects with file/line, concrete failure, and smallest
correction. Review is not merge/deployment/publication authority. Do not redesign the
workflow or expand into unresolved scalar parsing; those limitations are explicitly
preserved by the binding scope.
