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

Safety properties:

- SQLite is opened with `mode=ro` and `PRAGMA query_only=ON`.
- The file must already exist; the library never creates or migrates a database.
- The server binds only to `127.0.0.1`, rejects unexpected Host headers, and has no mutation endpoint.
- Recipe text is HTML-escaped and only credential-free HTTP(S) source URLs become links.
- Technical identifiers and stored JSON are not included in the default UI.
- Statuses are projections only: persisted `approved` → Approved; human `rejected` → Withdrawn; `deferred` → On hold; `failed` → Extraction failed; and only `pending` uses completeness to distinguish Ready for review from Missing information. Held, withdrawn, failed, or unknown-state recipe bodies are not rendered.

Focused verification:

```bash
python3 -m pytest -q tests/test_library.py
```
