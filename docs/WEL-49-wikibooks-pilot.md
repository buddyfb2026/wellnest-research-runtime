# WEL-49 — bounded Wikibooks dinner pilot

Owner: Codex. Baseline: `37a8179a9f80598f31dc6d31bd0b4b7281730426`.
Status: isolated implementation and measurement; no installation, live configuration,
publication, service restart or merge. These three pages are one publisher.

## First-party qualification

The normal `research.fetch.Fetcher`, with the existing identified contact-bearing
user agent, fetched exactly three pages plus one shared robots file on
2026-09-21T19:38:54Z–19:38:55Z. All pages returned HTTP 200, `robots_status=allowed`,
one hop and no access refusal. No images or extra recipe links were fetched.

| Page | Grounded ingredient/step inventory | Observed revision | Retained-text SHA-256 |
| --- | --- | --- | --- |
| [Kid-Friendly Pasta](https://en.wikibooks.org/wiki/Cookbook:Kid-Friendly_Pasta) | 4 / 7 | 4499839 | `0c8555afc154dded7c8961a97b5e7daf90c4f321e5d38b741ddc7c1221212b35` |
| [Chicken Fajitas](https://en.wikibooks.org/wiki/Cookbook:Chicken_Fajitas) | 7 / 7 | 4513985 | `ac2e37dd784b312b814bac683a98822da9736dde080ed2d3b654b9f319d5c78b` |
| [Tuna Casserole](https://en.wikibooks.org/wiki/Cookbook:Tuna_Casserole) | 5 / 4 | 4525567 | `c7ec0e5550480968ada54b138a6df4ba463d2077d08325925134b5804922876a` |

The first two pages appear in the publisher's kid-friendly classification; the latter
two appear in its [Easy Dinners index](https://en.wikibooks.org/wiki/Cookbook:Easy_Dinners).
This supports selection as dinner-shaped inputs, not popularity, parent testing,
nutrition or editorial suitability. Chicken Fajitas mentions seasonings absent from
the ingredient list and has no numeric safe internal temperature. Tuna Casserole
does not specify package sizes. These source limitations must not be invented away.

Each current recipe footer identifies the Creative Commons Attribution-ShareAlike
license. [Wikimedia Terms of Use §7](https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use#7._Licensing_of_Content)
permits attributed text reuse: the source article URL provides contributor-history
attribution; retain license and modification notices and license adapted text under
CC BY-SA 4.0 or later. The selected profile uses exactly
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/), never a public-domain
or CC0 label. No special imported-content notice was visible in the three recipe
bodies. Page discussion/history were not independently retrieved in this pilot;
the browser could not access discussion pages, and the product robots policy does
not permit generic `/w/` history requests. This is disclosed, not bypassed. Future
page-level extra attribution notices require review before reuse.

Access receipts: [robots.txt](https://en.wikibooks.org/robots.txt) and
[Wikimedia API usage guidelines](https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_API_Usage_Guidelines).
The pilot uses ordinary `/wiki/Cookbook:…` HTML, not a disallowed API/history route.
Per-file media rights were not qualified, so all images are excluded.

## Smallest implemented support

`scripts/prepare_wikibooks_profile.py` follows the incumbent meal-profile preparation
pattern. It produces an allowlist with just the three named pages and extends a copy
of the full existing roster by one publisher and three surfaces. Existing denials,
history and working-set ordering are retained. Output requires a new directory;
the default source files and running service are untouched.

The existing `attribution` string carries contributor credit, source URL, license
URL, change notice and the adapted-text license declaration. Existing persistence
and recipe binding preserve it unchanged. A concrete display omission was fixed:
the Research Library formerly displayed only the text before the first semicolon.
The detail page now additionally displays the full escaped credit/license notice.
No schema, approval policy, publication path or recipe-pack contract changed.

## Measured baseline and corrected result

The unmodified v6 locator produces **zero recipes on all three real pages**. Its
heading path recognizes `Instructions`/`Directions`, whereas Wikibooks uses
`Procedure`; its edit controls and trailing page sections also require explicit
boundaries. This was the first broken link. The bounded locator correction is now
implemented against the independently accepted Fable brief plus Stan correction.
It adds a closed `Procedure` heading, exact edit-control exclusion, closed MediaWiki
section/footer boundaries, unique visible-name grounding and locator version v7.
The retained text, scalar parser, inference prompt and approval path are unchanged.

Offline replay of the captured real responses through the incumbent worker into
`work/wikibooks-baseline/research.sqlite` produced exactly 3 evidence rows, 0 recipe
versions, 0 usable recipes, 0 inference calls and 0 publications. The worker's three
generic unavailable-inference audit candidates are **not** recipe yield. Its request
counters describe the replayed transport, not new internet requests. Baseline elapsed
time was 0.061 seconds.

The corrected retained run used the real installed `qwen3.8:27b`, exactly three local
recipe-extraction calls, and no source network. In **56.115 seconds** it produced:

| Recipe | Located ingredients / steps | Schema-valid | Cooking content usable | State |
| --- | --- | --- | --- | --- |
| Kid-Friendly Pasta | 4 / 7 | yes | yes | pending, incomplete |
| Chicken Fajitas | 7 / 7 | yes | yes | pending, incomplete |
| Tuna Casserole | 5 / 4 | yes | yes | pending, incomplete |

**3/3 usable cooking candidates, 0 fully complete recipes, 0 publications.** All
three are `publishable=0`. Pasta's fused servings and Tuna's fused total-time text
remain unresolved by the incumbent scalar grammar; missing times remain unknown.
The model did not turn missing facts into approved data. Usable cooking content is
the repository's deterministic name/ingredient/step validation result, not a claim of
editorial, food-safety or household readiness. A second no-model replay into its own
fresh database yielded 3 manifests, 3 unavailable-inference failed versions, 0 calls,
0 usable recipes and 0 publications, as the existing worker contract specifies.

Local raw receipt bodies, response hashes, exact text and outcome metadata are in
`work/wikibooks-receipts/`; the baseline report is
`work/wikibooks-baseline/yield.json`. Corrected results are
`work/wikibooks-v7-no-model/yield.json` and `work/wikibooks-v7-qwen/yield.json`; each
directory has its own isolated database. Sanitized source bodies/text and provenance
are also included as regression fixtures under `tests/fixtures/wel49_wikibooks/`.
HTTP headers containing cookie/client-IP fields are excluded from committed fixtures.

## Reproduction and checks

```sh
PYTHONPATH=. python3 scripts/prepare_wikibooks_profile.py --output work/wikibooks-profile
PYTHONPATH=. python3 scripts/eval_wikibooks_retained.py --receipts work/wikibooks-receipts --output work/wikibooks-baseline
python3 -m pytest -q tests/test_wel49_wikibooks_profile.py tests/test_library.py tests/test_wel49_permissive_recipes.py
```

The last command initially passed **37 tests**. The new integration test uses explicitly
synthetic supported HTML and fixture inference to verify full attribution survives
source configuration → evidence → recipe document → escaped library detail. It
asserts three pending, non-publishable recipe versions and zero publications; it is
not evidence that the real Wikibooks locator or model succeeded. Subsequent combined
binding verification passed **131 tests** with **9 pre-existing failures**: four stale
v5 assertions and five historical `/tmp` fixture dependencies. No incumbent failure
was added; the baseline design recorded 10 failures, and one version-bump test now
passes incidentally because v6 differs from v7. No existing test was edited to hide
those failures. Details and exact command are in `WEL-49-wikibooks-locator.md`.

`scripts/qualify_wikibooks.py --output NEW_DIRECTORY` is a separate explicit live
qualification action; it uses the real Fetcher, records bodies and stops on a block
or rate-limit response. Do not rerun it merely to repeat the already captured proof.
The completed retained evaluation used explicit `--model qwen3.8:27b` for exactly
three local inference calls in a new isolated database. The installed model was
confirmed via loopback `/api/tags`; no model was downloaded and no service was started
or configured for this pilot.

Deployment remains a later exact decision: review the final diff and real-model
yield first, then choose whether/where to install the prepared source profile and
corrected code. Nothing in this document grants publication or live-change authority.
