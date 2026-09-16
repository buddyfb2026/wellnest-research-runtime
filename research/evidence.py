"""Persistence helpers. Evidence is append-only; changed content becomes a new version."""
import json
import sqlite3
from typing import Any, Dict, Optional, Tuple

from .extract import Extracted
from .fetch import FetchResult, now_iso
from . import recipes


class PersistenceError(RuntimeError):
    """Raised when a write did not durably succeed. Callers must not report success."""


def upsert_source_hint(conn: sqlite3.Connection, hint: Dict[str, Any]) -> None:
    ts = now_iso()
    conn.execute(
        """INSERT INTO source_hints(url, source_type, attribution, access_basis, fetch_permitted,
               usage_constraints, discovery_origin, notes, first_seen_at, last_seen_at)
           VALUES(?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(url) DO UPDATE SET source_type=excluded.source_type, attribution=excluded.attribution,
               access_basis=excluded.access_basis, fetch_permitted=excluded.fetch_permitted,
               usage_constraints=excluded.usage_constraints, discovery_origin=excluded.discovery_origin,
               notes=excluded.notes, last_seen_at=excluded.last_seen_at""",
        (hint["url"], hint["source_type"], hint.get("attribution"), hint["access_basis"],
         1 if hint.get("fetch", False) else 0, hint.get("usage_constraints"), hint.get("discovery_origin"),
         hint.get("notes"), ts, ts),
    )


def record_fetch_attempt(conn: sqlite3.Connection, run_id: str, url: str, outcome: str, attempted_at: str,
                         http_status: Optional[int] = None, final_url: Optional[str] = None,
                         robots_status: Optional[str] = None, reason: Optional[str] = None,
                         evidence_id: Optional[int] = None) -> int:
    cur = conn.execute(
        """INSERT INTO fetch_attempts(run_id, url, attempted_at, outcome, http_status, final_url,
               robots_status, reason, evidence_id) VALUES(?,?,?,?,?,?,?,?,?)""",
        (run_id, url, attempted_at, outcome, http_status, final_url, robots_status, reason, evidence_id),
    )
    return int(cur.lastrowid)


def store_evidence(conn: sqlite3.Connection, hint: Dict[str, Any], fetched: FetchResult, ex: Extracted,
                   content_kind: str) -> Tuple[int, bool]:
    """Return (evidence_id, is_new). Identical content for the same URL is not re-inserted.
    Different content for a known URL becomes version N+1 that points at the row it supersedes."""
    existing = conn.execute(
        "SELECT id FROM evidence WHERE url=? AND content_hash=?", (hint["url"], ex.content_hash)
    ).fetchone()
    if existing:
        eid = int(existing["id"])
        recipes.attach_manifest(conn, eid, ex.locators, fetched.attempted_at)
        return eid, False
    prev = conn.execute(
        "SELECT id, version_no FROM evidence WHERE url=? ORDER BY version_no DESC LIMIT 1", (hint["url"],)
    ).fetchone()
    version_no = (int(prev["version_no"]) + 1) if prev else 1
    supersedes = int(prev["id"]) if prev else None
    cur = conn.execute(
        """INSERT INTO evidence(url, final_url, content_kind, content_hash, version_no, supersedes_id, fetched_at,
               published_at, published_at_basis, modified_at, title, attribution, source_type, access_basis,
               usage_constraints, excerpt, text_chars, injection_flags)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (hint["url"], fetched.final_url, content_kind, ex.content_hash, version_no, supersedes,
         fetched.attempted_at, ex.published_at, ex.published_at_basis, ex.modified_at, ex.title,
         hint.get("attribution"), hint["source_type"], hint["access_basis"], hint.get("usage_constraints"),
         ex.excerpt, len(ex.text), json.dumps(ex.injection_flags)),
    )
    eid = int(cur.lastrowid)
    conn.execute("INSERT INTO evidence_text(evidence_id, text) VALUES(?,?)", (eid, ex.text))
    recipes.attach_manifest(conn, eid, ex.locators, fetched.attempted_at)
    return eid, True


def load_evidence_text(conn: sqlite3.Connection, evidence_id: int) -> str:
    row = conn.execute("SELECT text FROM evidence_text WHERE evidence_id=?", (evidence_id,)).fetchone()
    return row["text"] if row else ""
