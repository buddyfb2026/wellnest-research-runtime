# WEL-48 — source-supported recipe extraction

WEL-48 adds a default-off recipe extraction path without changing the existing candidate, meal
guide, or export paths. Set `WN_RESEARCH_RECIPE_EXTRACTION=1` to enable it for an otherwise normal
worker run. The default remains off.

At collection time a deterministic locator records a closed, content-addressed manifest of recipe
bounds, roles, ingredient units, and step units. JSON-LD is preferred when all structured units can
be represented in retained evidence text; microdata and a generic Ingredients/Instructions heading
tier are fallbacks. Structured strings are HTML-entity-decoded only for matching. Their raw and
decoded forms are retained; rendered text and its existing content hash are unchanged.

Distinct manifests are immutable first-observation revisions. `evidence_current_manifest` is the
single mutable pointer to what was most recently observed. Selection follows that pointer, never a
maximum revision, so A→B→A resolves to the original A version. A locator-version change cannot run
against old evidence because raw HTML is not stored; it takes effect on the next ordinary
collection and spends no inference call before then.

The model receives the full retained evidence text as untrusted source data, with trusted metadata
naming the primary recipe. It returns strings and scalar `{value, quote}` objects, not offsets and
not the locator's answers. Deterministic code resolves each literal back to exact evidence offsets,
requires whole located ingredient and step units, enforces coverage and source order, and accepts a
scalar when its entire quote matches the closed affirmative servings/time grammar, or a bare time
quote exactly equals the whole value of that already-located, explicitly labeled time role. Structured,
visible, and model-quote readings must agree under the field-specific range rules. Model prose and
rejected quotes remain only in the non-portable `adaptations` audit column.

Ingredient and instruction matching keeps exact whole-unit matching first. A whitespace-only
fallback uses the existing whitespace fold, rejects candidates with distinct raw source texts,
and always stores the original source substring and offsets. It does not fold case, punctuation,
digits, unit tokens, or fractions, join units, or relax coverage/order/conflict checks. Identical
repeated source units retain ordered consumption. The extractor version is now
`wel48_extractor_v3`; existing versions and spent calls remain unchanged.

The scalar grammar deliberately withholds narrated, hedged, negated, out-of-domain, or unsupported
forms. It accepts only label-plus-quantity forms and the bounded `(this|the)? recipe` subject form.
Counts inside one explicit servings range are compatible and bind to that source range; two unequal
ranges or disjoint counts remain conflicts. Portable scalar audit readings live only at
`<field>.source.readings`; conflict rows retain the legacy structured/visible keys.

Ambiguous or unmatched structured-to-visible ingredient correspondence remains a P13
classification unknown even when the raw-source model returns the exact whole visible unit. The
literal unit stays bound, so cooking content can remain usable, but the record is `incomplete` for
review; this is the accepted AL-8 safe false-incomplete behavior measured by R4. Cooking content is
not usable when any actual name, ingredient, or step binding fails—including omission, truncation,
reordering, fabrication, or stale evidence identity.

Recipe rows created by the worker always have `publishable=0` and `state_set_by=worker`.
`completeness=complete` is not approval. WEL-48 has no promotion, publication, scheduler activation,
or auto-approval path.

## Offline evidence boundary

`eval/wel48/corpus/manifest.json` and `expected-inventory.md` describe six frozen live records from
three publishers, including two complete held-outs. Publisher HTML remains outside git; access to
the historical internal corpus grants no publication right. F1 materially-incomplete and F2
per-ingredient-conflict are explicitly labelled fixtures and are never counted as live proof.

Offline replay of six saved `qwen3.8:27b` responses under the binding grammar yields exactly four
complete records, one complete held-out, six with usable cooking content, 22 of 24 bound scalars,
zero scalar conflicts, and two unknown servings values (R4 and R6). That meets the governing
offline AC4 floor of at least three complete records including at least one held-out; it does not
claim both held-outs are perfect. A separate two-recipe NHLBI test has run through the real local
adapter and persistence path; it is not the full six-record proof. Its initial results exposed the
spacing and labeled-time cases covered by `tests/test_wel48_meal_binding.py`. Missing source total
time stays unknown, so a recipe may have usable cooking content while remaining `incomplete`.
No source-data promotion or publication follows from that distinction. No network or inference
call is needed to run the offline WEL-48 tests.
