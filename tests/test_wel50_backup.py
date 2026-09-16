"""WEL-50: offline backup / fresh-path restore of the isolated store honours the established store lock.

Scratch paths only (pytest tmp_path); synthetic fixture rows only; no network, no model, no service,
no existing store. Proves whole-store copy of representative rows, not source collection or inference.
"""
import json
import plistlib
import sqlite3
import subprocess
import sys
from pathlib import Path

from research import db as dbm
from research import source_registry
from research import worker
from research.lock import StoreLock
from tests.test_wel48_replay import _run as run_recipe_fixture
from tests.test_wel48_replay import _setup as setup_recipe_fixture

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "wel50_store_backup.py"

URL = "https://fixture.example/articles/sponges"
TEXT = ("Kitchen sponges should be replaced every week because they harbor bacteria. " * 4).strip()


def _seed(path: Path) -> None:
    """One run, one permitted hint, one fetch attempt, one evidence version with text, one rule
    candidate on that evidence, one settled inference row, and schedule state pointing at the evidence."""
    conn = dbm.connect(path)
    dbm.migrate(conn)
    conn.execute("BEGIN")
    conn.execute("INSERT INTO runs(run_id, started_at, finished_at, status, summary) VALUES(?,?,?,?,?)",
                 ("run_seed", "2026-09-15T00:00:00Z", "2026-09-15T00:00:05Z", "ok", json.dumps({"fetched_ok": 1})))
    conn.execute("INSERT INTO source_hints(url, source_type, attribution, access_basis, fetch_permitted, "
                 "first_seen_at, last_seen_at) VALUES(?,?,?,?,1,?,?)",
                 (URL, "publication", "Fixture Publisher", "fixture", "2026-09-15T00:00:00Z", "2026-09-15T00:00:00Z"))
    conn.execute("INSERT INTO evidence(id, url, final_url, content_kind, content_hash, version_no, fetched_at, "
                 "published_at, published_at_basis, title, attribution, source_type, access_basis, excerpt, text_chars) "
                 "VALUES(7,?,?,'fixture','hash-v1',1,?,?,?,?,?,?,?,?,?)",
                 (URL, URL, "2026-09-15T00:00:01Z", "2024-03-01T12:00:00Z", "meta:article:published_time",
                  "Sponge fixture", "Fixture Publisher", "publication", "fixture", TEXT[:80], len(TEXT)))
    conn.execute("INSERT INTO evidence_text(evidence_id, text) VALUES(7,?)", (TEXT,))
    conn.execute("INSERT INTO fetch_attempts(run_id, url, attempted_at, outcome, http_status, final_url, robots_status, "
                 "evidence_id) VALUES('run_seed',?, '2026-09-15T00:00:01Z','ok',200,?,'allowed',7)", (URL, URL))
    conn.execute("INSERT INTO candidates(id, dedupe_key, evidence_id, generator, household_problem, proposed_action, "
                 "observations, inferences, state, state_reason, state_set_by, created_at, updated_at, validation) "
                 "VALUES(3,'7:rule:sponge_swap',7,'rule:sponge_swap','Sponges harbor bacteria.','Weekly sponge swap reminder.',"
                 "?, '[]', 'pending', 'closed action registry match', 'worker', '2026-09-15T00:00:02Z', "
                 "'2026-09-15T00:00:02Z', ?)",
                 (json.dumps(["Kitchen sponges should be replaced every week"]), json.dumps({"kind": "rule"})))
    conn.execute("INSERT INTO inference_calls(run_id, provider, model, purpose, evidence_id, prompt_hash, called_at, ok, "
                 "day, status) VALUES('run_seed','ollama','fixture-model','propose',7,'p1','2026-09-15T00:00:03Z',1,"
                 "'2026-09-15','ok')")
    conn.execute("INSERT INTO source_state(url, next_check_at, attempts, last_attempt_at, last_outcome, last_success_at, "
                 "last_evidence_id, updated_at) VALUES(?, '2026-09-22T00:00:01Z', 1, '2026-09-15T00:00:01Z', 'ok', "
                 "'2026-09-15T00:00:01Z', 7, '2026-09-15T00:00:01Z')", (URL,))
    conn.execute("INSERT INTO publishers(publisher_id, canonical_name, official_url, parent_publisher, identity_basis, "
                 "assessed_at, assessed_by, notes) VALUES('fixture_pub','Fixture Publisher','https://fixture.example/',"
                 "NULL,'synthetic test identity','2026-09-15T00:00:00Z','agent:wel50-test','scratch only')")
    conn.execute("INSERT INTO source_surfaces(url,publisher_id,surface_kind,topics,roster_status,roster_reason,"
                 "access_status,access_basis,assessed_at,assessed_by,cadence_seconds,cadence_reason) "
                 "VALUES(?,'fixture_pub','site_article','[\"recipe_supply\"]','retain','synthetic fixture',"
                 "'permitted','fixture only','2026-09-15T00:00:00Z','agent:wel50-test',604800,'fixture cadence')", (URL,))
    manifest = json.dumps({"locator_version": "wel48_locator_v3", "recipes": [{"slot": "fixture-slot"}]},
                          sort_keys=True, separators=(",", ":"))
    conn.execute("INSERT INTO locator_manifests(id,evidence_id,manifest_hash,locator_version,revision_no,supersedes_id,"
                 "manifest,first_observed_at) VALUES(11,7,'manifest-hash','wel48_locator_v3',1,NULL,?,"
                 "'2026-09-15T00:00:02Z')", (manifest,))
    conn.execute("INSERT INTO evidence_current_manifest(evidence_id,locator_manifest_id,manifest_hash,observed_at) "
                 "VALUES(7,11,'manifest-hash','2026-09-15T00:00:02Z')")
    conn.execute("INSERT INTO recipes(id,recipe_key,source_url,recipe_slot,slot_disambiguated,first_seen_evidence_id,created_at) "
                 "VALUES(13,'fixture-recipe-key',?,'fixture-slot',0,7,'2026-09-15T00:00:02Z')", (URL,))
    recipe = json.dumps({"schema_version": "wel48_recipe_v1", "identity": {"recipe_key": "fixture-recipe-key", "recipe_slot": "fixture-slot"},
                         "name": {"value": "Fixture Soup", "support": "source"}}, sort_keys=True, separators=(",", ":"))
    conn.execute("INSERT INTO recipe_versions(id,recipe_id,evidence_id,locator_manifest_id,manifest_hash,version_no,"
                 "supersedes_id,extraction_key,content_fingerprint,content_unchanged_from,extractor_version,"
                 "prompt_schema_version,generator,content,adaptations,completeness,unknown_fields,conflicts,state,"
                 "state_reason,state_set_by,publishable,inference_call_id,created_at,updated_at) "
                 "VALUES(17,13,7,11,'manifest-hash',1,NULL,'fixture-extraction-key','fixture-fingerprint',NULL,"
                 "'wel48_extractor_v3','wel48_recipe_literals_v3','ollama:fixture-model',?,NULL,'complete','[]','[]',"
                 "'pending',NULL,'worker',0,NULL,'2026-09-15T00:00:03Z','2026-09-15T00:00:03Z')", (recipe,))
    conn.execute("COMMIT")
    conn.close()


EXPECTED_COUNTS = {"candidates": 1, "evidence": 1, "evidence_current_manifest": 1, "evidence_text": 1,
                   "fetch_attempts": 1, "inference_calls": 1, "locator_manifests": 1, "publishers": 1,
                   "recipe_versions": 1, "recipes": 1, "runs": 1, "schema_version": 6, "source_hints": 1,
                   "source_state": 1, "source_surfaces": 1, "surface_aliases": 0}


def _run(*args, timeout=20):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, cwd=str(REPO),
                          timeout=timeout)


def _snapshot(path: Path) -> dict:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        ev = dict(conn.execute("SELECT * FROM evidence WHERE id=7").fetchone())
        return {
            "evidence": ev,
            "text": conn.execute("SELECT text FROM evidence_text WHERE evidence_id=7").fetchone()[0],
            "candidate": dict(conn.execute("SELECT * FROM candidates WHERE id=3").fetchone()),
            "state": dict(conn.execute("SELECT * FROM source_state WHERE url=?", (URL,)).fetchone()),
            "attempt": dict(conn.execute("SELECT url, outcome, evidence_id FROM fetch_attempts").fetchone()),
            "inference": dict(conn.execute("SELECT evidence_id, day, status FROM inference_calls").fetchone()),
            "join": conn.execute("SELECT c.id FROM candidates c JOIN evidence e ON e.id=c.evidence_id "
                                 "JOIN source_state s ON s.last_evidence_id=e.id WHERE s.url=?", (URL,)).fetchone()[0],
            "recipe": dict(conn.execute("SELECT * FROM recipe_versions WHERE id=17").fetchone()),
            "recipe_identity": tuple(conn.execute(
                "SELECT r.recipe_key,r.source_url,r.recipe_slot,rv.manifest_hash,rv.version_no,rv.state,rv.publishable "
                "FROM recipes r JOIN recipe_versions rv ON rv.recipe_id=r.id WHERE rv.id=17").fetchone()),
            "publisher_identity": tuple(conn.execute(
                "SELECT p.publisher_id,p.canonical_name,s.url FROM publishers p JOIN source_surfaces s "
                "ON s.publisher_id=p.publisher_id WHERE s.url=?", (URL,)).fetchone()),
            "current_recipe": conn.execute(
                "SELECT rv.id FROM recipe_versions rv JOIN evidence_current_manifest ecm "
                "ON ecm.evidence_id=rv.evidence_id AND ecm.locator_manifest_id=rv.locator_manifest_id "
                "WHERE rv.id=17").fetchone()[0],
        }
    finally:
        conn.close()


def test_backup_and_fresh_path_restore_round_trip_representative_rows(tmp_path):
    db = tmp_path / "work" / "research.sqlite"
    _seed(db)
    before = _snapshot(db)
    out = tmp_path / "backups" / "research.sqlite"
    p = _run("backup", "--db", str(db), "--out", str(out))
    assert p.returncode == 0, p.stderr
    res = json.loads(p.stdout)
    assert res["integrity"] == "ok" and res["tables"] == EXPECTED_COUNTS
    probe = StoreLock(db)
    assert probe.acquire(), "lock released after backup"
    probe.release()

    # a second backup to the same name is refused (never silently overwrite a backup)
    p2 = _run("backup", "--db", str(db), "--out", str(out))
    assert p2.returncode == 1 and "already exists" in p2.stderr

    # restore only into a brand-new path; content and relationships survive
    fresh = tmp_path / "restored" / "research-candidate.sqlite"
    p3 = _run("restore", "--db", str(fresh), "--from", str(out))
    assert p3.returncode == 0, p3.stderr
    assert json.loads(p3.stdout)["tables"] == EXPECTED_COUNTS
    after = _snapshot(fresh)
    assert after == before
    assert after["text"] == TEXT and after["candidate"]["evidence_id"] == 7 and after["candidate"]["state"] == "pending"
    assert after["state"]["last_evidence_id"] == 7 and after["join"] == 3
    assert json.loads(after["candidate"]["observations"]) == ["Kitchen sponges should be replaced every week"]
    conn = sqlite3.connect(str(fresh))
    assert conn.execute("SELECT COALESCE(MAX(version),0) FROM schema_version").fetchone()[0] == 6
    conn.close()
    # the backup and the original store are untouched by the restore
    assert _snapshot(db) == before and _snapshot(out) == before


def test_restore_refuses_existing_destination_same_file_and_companions_without_mutation(tmp_path):
    db = tmp_path / "work" / "research.sqlite"
    _seed(db)
    before = _snapshot(db)
    out = tmp_path / "backups" / "research.sqlite"
    assert _run("backup", "--db", str(db), "--out", str(out)).returncode == 0

    # existing destination (the active store) is refused
    p = _run("restore", "--db", str(db), "--from", str(out))
    assert p.returncode == 1 and "already exists" in p.stderr
    # same file, direct and via a relative alias and a symlink, is refused and terminates
    p = _run("restore", "--db", str(out), "--from", str(out), timeout=10)
    assert p.returncode == 1 and "backup file itself" in p.stderr
    alias = out.parent / "." / out.name
    p = _run("restore", "--db", str(alias), "--from", str(out), timeout=10)
    assert p.returncode == 1 and "backup file itself" in p.stderr
    link = tmp_path / "link.sqlite"
    link.symlink_to(out)
    p = _run("restore", "--db", str(link), "--from", str(out), timeout=10)
    assert p.returncode == 1 and "backup file itself" in p.stderr
    # a leftover companion beside a nonexistent destination is refused and is never deleted
    dst = tmp_path / "restored" / "research.sqlite"
    dst.parent.mkdir()
    journal = dst.with_name(dst.name + "-journal")
    journal.write_bytes(b"leftover")
    p = _run("restore", "--db", str(dst), "--from", str(out))
    assert p.returncode == 1 and "companion" in p.stderr
    assert journal.read_bytes() == b"leftover" and not dst.exists()
    assert not StoreLock(dst).path.exists(), "refused before any lock file was created"
    # nothing changed
    assert _snapshot(db) == before and _snapshot(out) == before


def test_backup_and_restore_refuse_while_a_worker_holds_the_store_lock(tmp_path):
    db = tmp_path / "work" / "research.sqlite"
    _seed(db)
    out = tmp_path / "backups" / "research.sqlite"
    holder = StoreLock(db)
    assert holder.acquire()
    try:
        p = _run("backup", "--db", str(db), "--out", str(out))
        assert p.returncode == 3 and "held by a worker" in p.stderr and not out.exists()
    finally:
        holder.release()
    p = _run("backup", "--db", str(db), "--out", str(out))
    assert p.returncode == 0 and out.exists()
    fresh = tmp_path / "restored" / "research.sqlite"
    holder = StoreLock(fresh)
    assert holder.acquire()
    try:
        p = _run("restore", "--db", str(fresh), "--from", str(out))
        assert p.returncode == 3 and not fresh.exists()
    finally:
        holder.release()


def test_corrupt_backup_is_never_restored(tmp_path):
    db = tmp_path / "work" / "research.sqlite"
    _seed(db)
    bad = tmp_path / "bad.sqlite"
    bad.write_bytes(b"not a database")
    fresh = tmp_path / "restored" / "research.sqlite"
    p = _run("restore", "--db", str(fresh), "--from", str(bad))
    assert p.returncode == 1 and "not restored" in p.stderr and not fresh.exists()
    assert _snapshot(db)["candidate"]["id"] == 3, "original store untouched"


def test_disabled_plist_parses_as_the_actual_recipe_runtime_configuration(tmp_path, monkeypatch, capsys):
    plist_path = REPO / "docs" / "WEL-50-supervisor.launchd.example.plist"
    with plist_path.open("rb") as f:
        plist = plistlib.load(f)
    assert plist["Disabled"] is True and plist["RunAtLoad"] is False and "KeepAlive" not in plist
    env = plist["EnvironmentVariables"]
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    argv = list(plist["ProgramArguments"][3:])
    allowlist = REPO / "sources" / "allowlist.json"
    db_path, report_path = tmp_path / "research.sqlite", tmp_path / "report.md"
    argv = [str(allowlist) if x.endswith("/sources/allowlist.json") else
            str(db_path) if x.endswith("/research.sqlite") else
            str(report_path) if x.endswith("/report.md") else x for x in argv]
    seen = {}

    def fake_run(cfg, **kwargs):
        seen["cfg"], seen["kwargs"] = cfg, kwargs
        return worker.RunResult(status="ok", failures=[])

    monkeypatch.setattr(worker, "run", fake_run)
    assert worker.main(argv) == 0
    capsys.readouterr()
    cfg = seen["cfg"]
    assert seen["kwargs"]["due_only"] is True
    assert cfg.provider == "ollama" and cfg.ollama_model == "qwen3.8:27b"
    assert cfg.ollama_url == "http://127.0.0.1:11434" and cfg.recipe_extraction_enabled is True
    assert cfg.allowlist_path == allowlist and cfg.db_path == db_path and cfg.report_path == report_path
    assert (cfg.max_urls, cfg.max_inference, cfg.max_inference_per_day) == (10, 10, 10)


def test_proposed_allowlist_and_adjacent_roster_are_a_valid_paired_configuration(tmp_path):
    allowlist_path = REPO / "sources" / "allowlist.json"
    allowlist = worker.load_allowlist(allowlist_path)
    conn = dbm.connect(tmp_path / "registry.sqlite")
    dbm.migrate(conn)
    summary = source_registry.load(conn, allowlist_path.parent / "roster.json")
    assert summary["status"] == "loaded"
    roster_urls = {row[0] for row in conn.execute("SELECT url FROM source_surfaces")}
    collectable = {row["url"] for row in allowlist if row.get("fetch")}
    assert collectable <= roster_urls
    assert all(source_registry.effective_denied(conn, url) is None for url in collectable)
    conn.close()


def test_enabled_recipe_path_uses_reviewed_adapter_options_offline(tmp_path):
    payloads = []
    fixture = None

    def post(_url, payload, _timeout):
        payloads.append(payload)
        prompt = payload["prompt"]
        meta = json.loads(prompt.split("\n\n", 1)[0].split(": ", 1)[1])
        text = prompt.split("<<<EVIDENCE>>>\n", 1)[1].split("\n<<<END EVIDENCE>>>", 1)[0]
        return {"response": json.dumps(fixture(text, meta))}

    cfg, pages, model, fixture_fn = setup_recipe_fixture(tmp_path, post=post)
    fixture = fixture_fn
    assert run_recipe_fixture(cfg, pages, model).ok
    recipe_payload = next(p for p in payloads if "recipe_extraction" in
                          json.loads(p["prompt"].split("\n\n", 1)[0].split(": ", 1)[1]))
    assert recipe_payload["model"] == "fixture-model"
    assert recipe_payload["options"]["num_ctx"] == 16384
    assert recipe_payload["options"]["num_predict"] == 4096
    assert recipe_payload["think"] is False
    conn = sqlite3.connect(str(cfg.db_path))
    assert conn.execute("SELECT context_tokens FROM inference_calls WHERE purpose='recipe_extraction'").fetchone()[0] == 16384
    conn.close()
