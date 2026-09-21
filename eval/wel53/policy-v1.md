# WEL-53 recipe eligibility policy v1

This is an offline, shadow-only policy. A `shadow_eligible` decision is a report finding and grants no publication, export, or consumer right.

The evaluator applies every gate in `research.shadow_eligibility` to a `wel48_recipe_v1` document. Eligibility requires a complete document with no unknowns or conflicts; source-backed name, servings, prep time, cook time, total time, every ingredient, and every step; byte-reproducing evidence spans; no unsupported claim keys or instruction-like evidence; current content and manifest identity; a retained/permitted surface whose URL exactly equals `document.evidence.source_url`; and a non-empty rights basis recorded by a named `human:` reviewer. An optional approval must also name a human and bind the same content fingerprint.

The only dispositions are `shadow_eligible` (no reasons) and `shadow_hold` (one or more reasons). Synthetic cases are labeled `fixture` with `live_coverage: false`; they never contribute to a live count. Rights review is a recorded human basis for one exact URL, not proof of republishability.

Material error classes are: `materially_incomplete`, `unresolved_contradiction`, `unsupported_claim`, `stale_version`, `access_or_reuse_gap`, `forged_approval`, and `adversarial_injection`.
