import sqlite3

from research import db


def test_migration_5_is_rerunnable(tmp_path):
    conn = db.connect(tmp_path / "db.sqlite")
    assert db.migrate(conn) == 5
    conn.execute("DELETE FROM schema_version WHERE version=5")
    assert db.migrate(conn) == 5
    assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN "
                        "('locator_manifests','evidence_current_manifest','recipes','recipe_versions')").fetchone()[0] == 4
    columns = {r[1] for r in conn.execute("PRAGMA table_info(inference_calls)")}
    assert {"attempt_key", "prompt_schema_version", "machine_class", "model_digest", "quantization",
            "runtime_version", "context_tokens", "latency_ms", "peak_bytes"} <= columns


def test_migration_5_is_additive_and_keeps_wel49_separate(tmp_path):
    conn = db.connect(tmp_path / "db.sqlite")
    db.migrate(conn)
    assert conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == 5
    assert "publisher" not in {r[1] for r in conn.execute("PRAGMA table_info(recipes)")}
    assert {r[1] for r in conn.execute("PRAGMA table_info(source_state)")} == {
        "url", "next_check_at", "consecutive_failures", "attempts", "last_attempt_at", "last_outcome",
        "last_reason", "last_success_at", "last_evidence_id", "stalled", "updated_at"}
