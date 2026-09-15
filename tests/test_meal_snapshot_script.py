"""WEL-42 snapshot builder safety (review finding 3).

The builder must never damage the database it is pointed at, and must not silently lose content
that is committed but still living in a -wal sidecar.
"""
import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

from research.db import connect, migrate
from research.meal_guides import MEAL_GUIDES
from research.rules import RULES

_spec = importlib.util.spec_from_file_location(
    "wel42_build_snapshot", Path(__file__).resolve().parent.parent / "scripts" / "wel42_build_snapshot.py"
)
builder = importlib.util.module_from_spec(_spec)
sys.modules["wel42_build_snapshot"] = builder
_spec.loader.exec_module(builder)


SUPPORT = "Rinse fresh fruits and vegetables under running water."
PROBLEM = "Unwashed fruits and vegetables"


def make_db(path: Path, *, wal: bool = False) -> None:
    c = connect(path)
    migrate(c)
    if wal:
        c.execute("PRAGMA journal_mode=WAL")
    import hashlib

    text = "%s\n%s" % (SUPPORT, PROBLEM)

    c.execute(
        """INSERT INTO evidence(id, url, content_kind, content_hash, version_no, fetched_at,
                published_at_basis, attribution, source_type, access_basis, excerpt, text_chars,
                injection_flags)
           VALUES(1, 'https://www.cdc.gov/food-safety/prevention/index.html', 'live', ?, 1,
                  '2026-09-15T15:33:48Z', 'meta:dc.date',
                  'U.S. Centers for Disease Control and Prevention', 'government', 'public', 'x', 10, '[]')""",
        (hashlib.sha256(text.encode()).hexdigest(),),
    )
    c.execute("INSERT INTO evidence_text(evidence_id, text) VALUES(1, ?)", (text,))

    # Also stand up the evidence each registered guide cites, built from that guide's own anchors
    # plus its gating rule's sentences. Keeps this fixture honest as the registry grows.
    next_id = 2
    for guide in MEAL_GUIDES.values():
        rule = next(r for r in RULES if r.rule_id == guide.rule_id)
        for url in guide.source_urls:
            sentences = [i.anchor for i in guide.items if i.source_url == url]
            sentences += list(rule.support_sentences) + list(rule.problem_sentences)
            body = "\n".join(sentences)
            c.execute(
                """INSERT INTO evidence(id, url, content_kind, content_hash, version_no, fetched_at,
                        published_at_basis, title, attribution, source_type, access_basis, excerpt,
                        text_chars, injection_flags)
                   VALUES(?, ?, 'live', ?, 1, '2026-09-15T18:12:54Z', 'unknown', ?,
                          'Good Housekeeping (Hearst)', 'publication', 'public', 'x', ?, '[]')""",
                (next_id, url, hashlib.sha256(body.encode()).hexdigest(),
                 "Fixture article for %s" % guide.rule_id, len(body)),
            )
            c.execute("INSERT INTO evidence_text(evidence_id, text) VALUES(?, ?)", (next_id, body))
            next_id += 1
    c.commit()
    c.close()


def source_fingerprint(path: Path):
    c = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    try:
        return (
            c.execute("SELECT COUNT(*) FROM evidence").fetchone()[0],
            c.execute("SELECT COUNT(*) FROM candidates").fetchone()[0],
            c.execute("SELECT text FROM evidence_text WHERE evidence_id=1").fetchone()[0],
        )
    finally:
        c.close()


# ---- alias / overlap refusal, before any mutation ------------------------------------------------

def test_REPRO_work_equal_to_source_is_refused_and_source_survives(tmp_path):
    src = tmp_path / "research.sqlite"
    make_db(src)
    before = source_fingerprint(src)

    with pytest.raises(builder.UnsafePaths):
        builder.build(src, tmp_path / "out.json", src)

    assert src.exists(), "the source database must still exist"
    assert source_fingerprint(src) == before


def test_work_symlinked_to_source_is_refused(tmp_path):
    src = tmp_path / "research.sqlite"
    make_db(src)
    link = tmp_path / "alias.sqlite"
    link.symlink_to(src)
    before = source_fingerprint(src)

    with pytest.raises(builder.UnsafePaths):
        builder.build(src, tmp_path / "out.json", link)
    assert source_fingerprint(src) == before


def test_work_hardlinked_to_source_is_refused(tmp_path):
    src = tmp_path / "research.sqlite"
    make_db(src)
    hard = tmp_path / "hard.sqlite"
    import os

    os.link(src, hard)
    before = source_fingerprint(src)

    with pytest.raises(builder.UnsafePaths):
        builder.build(src, tmp_path / "out.json", hard)
    assert source_fingerprint(src) == before


def test_relative_path_alias_of_source_is_refused(tmp_path, monkeypatch):
    src = tmp_path / "research.sqlite"
    make_db(src)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(builder.UnsafePaths):
        builder.build(src, tmp_path / "out.json", Path("./research.sqlite"))
    assert src.exists()


def test_output_equal_to_source_is_refused(tmp_path):
    src = tmp_path / "research.sqlite"
    make_db(src)
    before = source_fingerprint(src)
    with pytest.raises(builder.UnsafePaths):
        builder.build(src, src, tmp_path / "work.sqlite")
    assert source_fingerprint(src) == before


def test_work_equal_to_output_is_refused(tmp_path):
    src = tmp_path / "research.sqlite"
    make_db(src)
    shared = tmp_path / "same"
    with pytest.raises(builder.UnsafePaths):
        builder.build(src, shared, shared)


def test_missing_source_is_refused_without_creating_anything(tmp_path):
    out = tmp_path / "out.json"
    with pytest.raises(builder.UnsafePaths):
        builder.build(tmp_path / "nope.sqlite", out, tmp_path / "work.sqlite")
    assert not out.exists()


# ---- WAL-committed content must survive the copy --------------------------------------------------

def test_REPRO_content_committed_to_wal_is_retained(tmp_path):
    """A plain file copy of the .sqlite would miss rows still living in the -wal sidecar."""
    src = tmp_path / "research.sqlite"
    make_db(src, wal=True)

    # Commit a second evidence row and hold the connection OPEN with autocheckpoint disabled, so the
    # row stays in the -wal sidecar and is genuinely absent from the main database file. Closing the
    # connection would checkpoint it back and the test would no longer discriminate.
    c = sqlite3.connect(src)
    try:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA wal_autocheckpoint=0")
        c.execute(
            """INSERT INTO evidence(id, url, content_kind, content_hash, version_no, fetched_at,
                    published_at_basis, attribution, source_type, access_basis, excerpt, text_chars,
                    injection_flags)
               VALUES(999, 'https://example.gov/second', 'live', 'hash2', 1, '2026-09-15T00:00:00Z',
                      'unknown', 'Publisher', 'government', 'public', 'x', 10, '[]')"""
        )
        c.commit()

        # Precondition: a plain file copy of the .sqlite really does miss the row.
        import shutil

        naive = tmp_path / "naive-copy.sqlite"
        shutil.copyfile(src, naive)
        naive_conn = sqlite3.connect(naive)
        naive_ids = [r[0] for r in naive_conn.execute("SELECT id FROM evidence ORDER BY id")]
        naive_conn.close()
        assert 999 not in naive_ids, "precondition: file copy loses the WAL-committed row"

        result = builder.build(src, tmp_path / "out.json", tmp_path / "work.sqlite")
    finally:
        c.close()

    work = sqlite3.connect(result["work"])
    ids = [r[0] for r in work.execute("SELECT id FROM evidence ORDER BY id")]
    work.close()
    assert 999 in ids, "WAL-committed row was lost by the copy"


def test_build_does_not_modify_the_source(tmp_path):
    src = tmp_path / "research.sqlite"
    make_db(src)
    before = source_fingerprint(src)

    builder.build(src, tmp_path / "out.json", tmp_path / "work.sqlite")

    assert source_fingerprint(src) == before, "source candidates/evidence must be untouched"
    assert before[1] == 0, "no candidate was written to the source"


def test_candidate_is_written_to_the_working_copy_and_stays_pending(tmp_path):
    src = tmp_path / "research.sqlite"
    make_db(src)
    result = builder.build(src, tmp_path / "out.json", tmp_path / "work.sqlite")

    work = sqlite3.connect(result["work"])
    work.row_factory = sqlite3.Row
    rows = work.execute("SELECT * FROM candidates").fetchall()
    work.close()
    assert len(rows) >= 1
    for row in rows:
        assert row["state"] == "pending" and row["state_set_by"] == "worker"
        assert row["publishable"] == 0
    assert result["snapshot"]["details"] == [], "pending candidates export nothing"


def test_preview_approval_touches_only_the_working_copy(tmp_path):
    src = tmp_path / "research.sqlite"
    make_db(src)
    first = builder.build(src, tmp_path / "out.json", tmp_path / "work.sqlite")
    guide_rule = next(iter(MEAL_GUIDES))
    work = sqlite3.connect(result_work := first["work"])
    cid = work.execute(
        "SELECT id FROM candidates WHERE generator LIKE ?", ("rule:%s@%%" % guide_rule,)
    ).fetchone()[0]
    work.close()
    assert result_work

    result = builder.build(src, tmp_path / "preview.json", tmp_path / "work2.sqlite", (cid,))
    assert len(result["snapshot"]["details"]) == 1
    assert result["snapshot"]["_preview_warning"].startswith("PREVIEW ONLY")
    assert (
        result["snapshot"]["details"][0]["candidate"]["state_set_by"]
        == "human:PREVIEW-NOT-A-REAL-APPROVAL"
    )
    # The source still has no candidates at all.
    assert source_fingerprint(src)[1] == 0
