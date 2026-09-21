# WEL-59 — local read-only Research Library

The Research Library is a dependency-free, server-rendered browser for the current recipe versions already present in the WellNest research SQLite store. It does not import the worker, run migrations, call a model, or expose a write route.

Run it only on loopback:

```bash
python3 -m research.library \
  --db "/Users/buddystudio1/Library/Application Support/WellNestResearch/state/research.sqlite" \
  --host 127.0.0.1 \
  --port 8765
```

Open `http://127.0.0.1:8765/` in the local Studio browser. Stop the foreground process with `Ctrl-C`.

The **Approved & Autopilot** view at `/approved` runs the existing recipe-pack eligibility evaluator on the read-only connection; it never allocates or exports a pack. The UI labels a recipe Approved only when the persisted approval also passes that global feed contract. Inconsistent approval records are shown as internal Needs correction, not as approved recipes; unavailable evaluation is labeled Eligibility not evaluated. Global approval means eligible for household matching, while suitability for a particular household remains a separate downstream decision. Missing information is grouped into details the source does not specify and extraction that needs correction. Optional source omissions do not by themselves mean a recipe is unusable.

Safety properties:

- SQLite is opened with `mode=ro` and `PRAGMA query_only=ON`.
- The file must already exist; the library never creates or migrates a database.
- The server binds only to `127.0.0.1`, rejects unexpected Host headers, and has no mutation endpoint.
- Recipe text is HTML-escaped and only credential-free HTTP(S) source URLs become links.
- Technical identifiers and stored JSON are not included in the default UI.
- Statuses are projections only: persisted `approved` → Approved; human `rejected` → Withdrawn; `deferred` → On hold; `failed` → Extraction failed; and only `pending` uses completeness to distinguish Ready for review from Missing information. Held, withdrawn, failed, or unknown-state recipe bodies are not rendered.
- The viewer does not equate approval with feed readiness, change app matching/export rules, publish recipes, or offer approval controls.

Focused verification:

```bash
python3 -m pytest -q tests/test_library.py
```
