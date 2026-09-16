"""Isolated SQLite research store with versioned, additive migrations.

Never points at ri_db or any app database. Path comes from Config.db_path.
"""
import sqlite3
from pathlib import Path
from typing import Union

MIGRATIONS = [
    (
        1,
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        );
        -- Discovery hints: where we *might* look. Not evidence.
        CREATE TABLE IF NOT EXISTS source_hints (
            url TEXT PRIMARY KEY,
            source_type TEXT NOT NULL,
            attribution TEXT,
            access_basis TEXT NOT NULL,
            fetch_permitted INTEGER NOT NULL DEFAULT 0,
            usage_constraints TEXT,
            discovery_origin TEXT,
            notes TEXT,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL
        );
        -- Every retrieval attempt, including blocked and failed ones.
        CREATE TABLE IF NOT EXISTS fetch_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            url TEXT NOT NULL,
            attempted_at TEXT NOT NULL,
            outcome TEXT NOT NULL,           -- ok | blocked | error | skipped_policy
            http_status INTEGER,
            final_url TEXT,
            robots_status TEXT,              -- allowed | disallowed | unreachable | not_checked
            reason TEXT,
            evidence_id INTEGER
        );
        -- Retrieved evidence. Append-only; a changed page gets a new version row.
        CREATE TABLE IF NOT EXISTS evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL,
            final_url TEXT,
            content_kind TEXT NOT NULL,      -- live | fixture
            content_hash TEXT NOT NULL,
            version_no INTEGER NOT NULL,
            supersedes_id INTEGER,
            fetched_at TEXT NOT NULL,
            published_at TEXT,
            published_at_basis TEXT NOT NULL, -- meta:article:published_time | meta:datePublished | unknown
            modified_at TEXT,
            title TEXT,
            attribution TEXT,
            source_type TEXT NOT NULL,
            access_basis TEXT NOT NULL,
            usage_constraints TEXT,
            excerpt TEXT NOT NULL,
            text_chars INTEGER NOT NULL,
            injection_flags TEXT,            -- JSON list of matched instruction-like patterns
            UNIQUE(url, content_hash)
        );
        CREATE TABLE IF NOT EXISTS evidence_text (
            evidence_id INTEGER PRIMARY KEY,
            text TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS inference_calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            model TEXT,
            purpose TEXT NOT NULL,
            evidence_id INTEGER,
            prompt_hash TEXT NOT NULL,
            called_at TEXT NOT NULL,
            ok INTEGER NOT NULL,
            error TEXT,
            response_chars INTEGER
        );
        CREATE TABLE IF NOT EXISTS candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dedupe_key TEXT NOT NULL UNIQUE,
            evidence_id INTEGER NOT NULL,
            generator TEXT NOT NULL,         -- provider:model or fixture
            household_problem TEXT,
            proposed_action TEXT,
            observations TEXT NOT NULL,      -- JSON list of grounded quotes
            inferences TEXT NOT NULL,        -- JSON list of model/heuristic inferences
            unsupported_claims TEXT,         -- JSON list dropped for lack of grounding
            relevance_conditions TEXT,       -- JSON list
            lead_time_days INTEGER,
            expires_at TEXT,
            expiry_basis TEXT,
            product_mentions TEXT,           -- JSON list [{name, grounded}]
            source_attribution TEXT,
            proposed_destination TEXT,       -- always NULL in WEL-40; separate decision
            stock_price_claims TEXT NOT NULL DEFAULT 'not_verified',
            state TEXT NOT NULL,             -- pending | approved | rejected | deferred
            state_reason TEXT,
            state_set_by TEXT NOT NULL,      -- worker | human:<name>
            publishable INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL,            -- running | ok | failed
            summary TEXT
        );
        """,
    ),
    (
        2,
        """
        ALTER TABLE candidates ADD COLUMN lead_time_basis TEXT;  -- grounded quote that states lead_time_days
        """,
    ),
    (
        3,
        """
        -- JSON: how the row was produced and what was checked. {"kind":"rule",...} for the closed
        -- action registry, {"kind":"free_text","raw_proposal":...} for audit-only model prose.
        -- NULL = row created before v3: its prose was never validated and is not rendered.
        ALTER TABLE candidates ADD COLUMN validation TEXT;
        """,
    ),
    (
        4,
        # WEL-41: recurring collection. A list is applied statement by statement so a partially
        # applied migration can be re-run (each ALTER tolerates "duplicate column").
        [
            # Per-source scheduling and backoff state. One row per permitted source; hints without a
            # permitted access basis never get a row and are therefore never due.
            """CREATE TABLE IF NOT EXISTS source_state (
                url TEXT PRIMARY KEY,
                next_check_at TEXT NOT NULL,
                consecutive_failures INTEGER NOT NULL DEFAULT 0,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_attempt_at TEXT,
                last_outcome TEXT,               -- ok | blocked | error
                last_reason TEXT,
                last_success_at TEXT,
                last_evidence_id INTEGER,
                stalled INTEGER NOT NULL DEFAULT 0,   -- 1 after repeated blocks; only a manual reset clears it
                updated_at TEXT NOT NULL
            )""",
            # Persistent daily budget: a row is inserted (status=reserved) and committed BEFORE the
            # external request. Every row for a UTC day counts toward that day's cap; rows are never
            # deleted, so a crash, timeout or rollback cannot refund a call that may have executed.
            "ALTER TABLE inference_calls ADD COLUMN day TEXT",
            "ALTER TABLE inference_calls ADD COLUMN status TEXT",   # reserved | ok | error | ambiguous
            # Discovery provenance and the recorded access assessment for hints found via a route.
            "ALTER TABLE source_hints ADD COLUMN discovered_at TEXT",
            "ALTER TABLE source_hints ADD COLUMN discovery_route TEXT",   # the declared route URL
            "ALTER TABLE source_hints ADD COLUMN access_assessment TEXT",  # JSON {status, reason, robots_status, checked_at}
        ],
    ),
    (
        5,
        # WEL-48: source-supported recipe extraction. All changes are additive and every CREATE
        # is restart-safe because the migration runner applies statements one at a time.
        [
            """CREATE TABLE IF NOT EXISTS locator_manifests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                evidence_id INTEGER NOT NULL REFERENCES evidence(id),
                manifest_hash TEXT NOT NULL,
                locator_version TEXT NOT NULL,
                revision_no INTEGER NOT NULL,
                supersedes_id INTEGER REFERENCES locator_manifests(id),
                manifest TEXT NOT NULL,
                first_observed_at TEXT NOT NULL,
                UNIQUE(evidence_id, manifest_hash),
                UNIQUE(evidence_id, revision_no)
            )""",
            """CREATE TABLE IF NOT EXISTS evidence_current_manifest (
                evidence_id INTEGER PRIMARY KEY REFERENCES evidence(id),
                locator_manifest_id INTEGER NOT NULL REFERENCES locator_manifests(id),
                manifest_hash TEXT NOT NULL,
                observed_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS recipes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recipe_key TEXT NOT NULL UNIQUE,
                source_url TEXT NOT NULL,
                recipe_slot TEXT NOT NULL,
                slot_disambiguated INTEGER NOT NULL DEFAULT 0,
                first_seen_evidence_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(source_url, recipe_slot)
            )""",
            """CREATE TABLE IF NOT EXISTS recipe_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recipe_id INTEGER NOT NULL REFERENCES recipes(id),
                evidence_id INTEGER NOT NULL REFERENCES evidence(id),
                locator_manifest_id INTEGER NOT NULL REFERENCES locator_manifests(id),
                manifest_hash TEXT NOT NULL,
                version_no INTEGER NOT NULL,
                supersedes_id INTEGER REFERENCES recipe_versions(id),
                extraction_key TEXT NOT NULL UNIQUE,
                content_fingerprint TEXT NOT NULL,
                content_unchanged_from INTEGER REFERENCES recipe_versions(id),
                extractor_version TEXT NOT NULL,
                prompt_schema_version TEXT,
                generator TEXT NOT NULL,
                content TEXT NOT NULL,
                adaptations TEXT,
                completeness TEXT NOT NULL,
                unknown_fields TEXT NOT NULL,
                conflicts TEXT NOT NULL,
                state TEXT NOT NULL,
                state_reason TEXT,
                state_set_by TEXT NOT NULL,
                publishable INTEGER NOT NULL DEFAULT 0,
                inference_call_id INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(recipe_id, version_no)
            )""",
            "CREATE INDEX IF NOT EXISTS idx_recipe_versions_recipe ON recipe_versions(recipe_id, version_no)",
            "CREATE INDEX IF NOT EXISTS idx_recipe_versions_manifest ON recipe_versions(evidence_id, manifest_hash)",
            "CREATE INDEX IF NOT EXISTS idx_locator_manifests_evidence ON locator_manifests(evidence_id, revision_no)",
            "ALTER TABLE inference_calls ADD COLUMN attempt_key TEXT",
            "ALTER TABLE inference_calls ADD COLUMN prompt_schema_version TEXT",
            "ALTER TABLE inference_calls ADD COLUMN machine_class TEXT",
            "ALTER TABLE inference_calls ADD COLUMN model_digest TEXT",
            "ALTER TABLE inference_calls ADD COLUMN quantization TEXT",
            "ALTER TABLE inference_calls ADD COLUMN runtime_version TEXT",
            "ALTER TABLE inference_calls ADD COLUMN context_tokens INTEGER",
            "ALTER TABLE inference_calls ADD COLUMN latency_ms INTEGER",
            "ALTER TABLE inference_calls ADD COLUMN peak_bytes INTEGER",
        ],
    ),
    # WEL-49 owns migration 6; integration must place WEL-48's migration 5 before this.
    (6, """
        CREATE TABLE IF NOT EXISTS publishers (
            publisher_id TEXT PRIMARY KEY, canonical_name TEXT NOT NULL, official_url TEXT,
            parent_publisher TEXT REFERENCES publishers(publisher_id), identity_basis TEXT NOT NULL,
            assessed_at TEXT NOT NULL, assessed_by TEXT NOT NULL, notes TEXT
        );
        CREATE TABLE IF NOT EXISTS source_surfaces (
            url TEXT PRIMARY KEY, publisher_id TEXT REFERENCES publishers(publisher_id),
            surface_kind TEXT NOT NULL, topics TEXT NOT NULL, roster_status TEXT NOT NULL,
            roster_reason TEXT NOT NULL, access_status TEXT NOT NULL, access_basis TEXT,
            assessed_at TEXT NOT NULL, assessed_by TEXT NOT NULL, cadence_seconds INTEGER, cadence_reason TEXT
        );
        CREATE TABLE IF NOT EXISTS surface_aliases (
            alias_url TEXT PRIMARY KEY, url TEXT NOT NULL REFERENCES source_surfaces(url), alias_reason TEXT NOT NULL
        );
    """),
]


def connect(path: Union[str, Path]) -> sqlite3.Connection:
    path = Path(path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), isolation_level=None)  # explicit transactions
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending migrations. Idempotent; returns current schema version."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    row = conn.execute("SELECT COALESCE(MAX(version), 0) AS v FROM schema_version").fetchone()
    current = int(row["v"])
    for version, sql in MIGRATIONS:
        if version <= current:
            continue
        # executescript autocommits statement by statement; v1 statements are CREATE IF NOT
        # EXISTS and later ones are single additive ALTERs, so a partial apply is safe to re-run.
        for stmt in ([sql] if isinstance(sql, str) else sql):
            try:
                conn.executescript(stmt)
            except sqlite3.OperationalError as e:
                if "duplicate column" not in str(e):
                    raise
        conn.execute(
            "INSERT INTO schema_version(version, applied_at) VALUES (?, strftime('%Y-%m-%dT%H:%M:%SZ','now'))",
            (version,),
        )
        current = version
    return current
