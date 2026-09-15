"""Per-source next-check times and finite backoff (WEL-41). No loop lives here.

    success            -> next check in 7 days, failure counter reset
    error (timeout, 5xx, 404, unusable text)
                       -> 1h, 4h, 24h, 72h, then 7d for every further consecutive failure
    blocked (robots, login wall, 401/403)
                       -> 7d, 30d, then `stalled`: never due again until a manual reset

A stalled or not-yet-due source is never requested. Failures never touch prior evidence.
"""
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional

Clock = Callable[[], datetime]

SUCCESS_INTERVAL = timedelta(days=7)
ERROR_BACKOFF = (timedelta(hours=1), timedelta(hours=4), timedelta(days=1), timedelta(days=3), timedelta(days=7))
BLOCKED_BACKOFF = (timedelta(days=7), timedelta(days=30))
BLOCKED_STALL_AFTER = 3


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def day_of(dt: datetime) -> str:
    """UTC calendar day used for the daily inference cap. Resets at 00:00 UTC."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")


def ensure_state(conn: sqlite3.Connection, url: str, now: datetime) -> None:
    """A newly permitted source is due immediately. Existing rows are left alone."""
    conn.execute("INSERT OR IGNORE INTO source_state(url, next_check_at, updated_at) VALUES(?,?,?)",
                 (url, iso(now), iso(now)))


def due_urls(conn: sqlite3.Connection, now: datetime, limit: int) -> List[str]:
    rows = conn.execute(
        "SELECT url FROM source_state WHERE stalled=0 AND next_check_at<=? ORDER BY next_check_at, url LIMIT ?",
        (iso(now), int(limit))).fetchall()
    return [r["url"] for r in rows]


def record_outcome(conn: sqlite3.Connection, url: str, outcome: str, reason: Optional[str], attempted_at: str,
                   now: datetime, evidence_id: Optional[int] = None) -> Dict[str, object]:
    """Advance the schedule for one attempt. Must run inside the attempt's transaction."""
    row = conn.execute("SELECT * FROM source_state WHERE url=?", (url,)).fetchone()
    failures = int(row["consecutive_failures"]) if row else 0
    stalled = 0
    if outcome == "ok":
        failures = 0
        next_at = now + SUCCESS_INTERVAL
    elif outcome == "blocked":
        failures += 1
        if failures >= BLOCKED_STALL_AFTER:
            stalled = 1
            next_at = now + BLOCKED_BACKOFF[-1]   # informational only: stalled rows are never selected
        else:
            next_at = now + BLOCKED_BACKOFF[min(failures, len(BLOCKED_BACKOFF)) - 1]
    else:
        failures += 1
        next_at = now + ERROR_BACKOFF[min(failures, len(ERROR_BACKOFF)) - 1]
    conn.execute(
        """INSERT INTO source_state(url, next_check_at, consecutive_failures, attempts, last_attempt_at, last_outcome,
               last_reason, last_success_at, last_evidence_id, stalled, updated_at)
           VALUES(?,?,?,1,?,?,?,?,?,?,?)
           ON CONFLICT(url) DO UPDATE SET next_check_at=excluded.next_check_at,
               consecutive_failures=excluded.consecutive_failures, attempts=source_state.attempts+1,
               last_attempt_at=excluded.last_attempt_at, last_outcome=excluded.last_outcome,
               last_reason=excluded.last_reason,
               last_success_at=COALESCE(excluded.last_success_at, source_state.last_success_at),
               last_evidence_id=COALESCE(excluded.last_evidence_id, source_state.last_evidence_id),
               stalled=excluded.stalled, updated_at=excluded.updated_at""",
        (url, iso(next_at), failures, attempted_at, outcome, reason,
         attempted_at if outcome == "ok" else None, evidence_id if outcome == "ok" else None, stalled, iso(now)),
    )
    return {"next_check_at": iso(next_at), "stalled": bool(stalled), "consecutive_failures": failures}


def reset_source(conn: sqlite3.Connection, url: str, by: str, reason: str, now: datetime) -> None:
    """Manual reset of a stalled/backed-off source: due now, failure counter cleared. History stays."""
    if not by or not reason:
        raise ValueError("reset requires --by and --reason")
    cur = conn.execute(
        "UPDATE source_state SET stalled=0, consecutive_failures=0, next_check_at=?, last_reason=?, updated_at=? WHERE url=?",
        (iso(now), "manual reset by %s: %s" % (by, reason), iso(now), url))
    if cur.rowcount != 1:
        raise ValueError("no scheduling state for %s" % url)
