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
        try:
            conn.executescript(sql)
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e):
                raise
        conn.execute(
            "INSERT INTO schema_version(version, applied_at) VALUES (?, strftime('%Y-%m-%dT%H:%M:%SZ','now'))",
            (version,),
        )
        current = version
    return current
