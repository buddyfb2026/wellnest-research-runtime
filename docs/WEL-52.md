# WEL-52 producer contract

This repository implements only the research producer side of the binding WEL-52 design v5.
The app remains the GrokBot-owned consumer. No source acquisition, human publication decision,
content placement, activation, deployment, or app change is performed here.

## Publication boundary

Migration 7 adds the append-only `recipe_publications` log and the content-free `pack_state`
generation row. A publish act requires an operator-supplied intent, a named `human:` actor,
authority and rights-basis strings, complete ingredient mapping, and explicit equipment review.
Those strings are audit evidence, not proof of rights. Replaying the same intent and arguments is
a read-only success; reusing an intent with different arguments is refused. Withdrawal is another
explicit human act. The worker has no publication path.

Example shape (do not treat this as an approval):

```text
python3 -m research.recipe_review publish --db <research.sqlite> \
  --intent <operator-id> --version <recipe-version-id> --by "human:<name>" \
  --authority <reference> --rights-basis <recorded-basis> --template <meal-template> \
  --requires <tokens> --introduces <tokens> --map "0:token;1:token" \
  --equipment "display text|literal anchor" --equipment-reviewed
```

## Export boundary

`python3 scripts/wel52_build_pack.py <research.sqlite> <recipe-pack.v1.json>` acquires the existing
non-blocking store lock, evaluates the 18 closed omission gates, allocates or reuses generation in
the same SQLite transaction as the served-state observation, and replaces the output using a
fixed temporary path. `pack_id` is the SHA-256 of canonical JSON containing only `recipes` and
`withdrawn`; generation advances whenever that served state changes, including drift and revert.
Fixture evidence is refused unless the test-only flag is supplied, which stamps `_fixture` so a
production consumer must reject the artifact.

The exporter contains no household or customer-private input and no recipe-specific rules. A
recipe with unknown total time can remain a shared exported candidate; the consumer timing gate
must refuse attachment rather than estimating or summing a value. Equipment is attested display
data only and does not claim ownership or household fit.

## Verification boundary

Focused producer suites:

```text
python3 -m pytest -q tests/test_wel52_review.py
python3 -m pytest -q tests/test_wel52_pack.py
```

The handoff test is intentionally non-skipping:

```text
WELLNEST_APP_DIR=<GrokBot checkout with dependencies> \
  python3 -m pytest -q tests/test_wel52_handoff.py
```

It fails when the consumer CLI or dependencies are absent. A9 therefore cannot be reported green
from a producer-only checkout. Fixture handoff evidence is also not real-source, human-review,
device, publication, release, or deployment evidence.
