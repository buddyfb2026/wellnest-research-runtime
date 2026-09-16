"""WEL-50 offline backup / restore of the isolated research SQLite store. Not a service.

    python3 scripts/wel50_store_backup.py backup  --db work/research.sqlite --out backups/research-YYYYMMDD.sqlite
    python3 scripts/wel50_store_backup.py restore --db restored/research-candidate.sqlite --from backups/research-YYYYMMDD.sqlite

Both commands take the established store lock (research/lock.py, the same advisory flock the
worker holds for its lifetime). If a worker holds it the command exits 3 and touches nothing, so a
backup never reads a store mid-write. The copy itself is SQLite's online backup API
(sqlite3.Connection.backup), followed by PRAGMA integrity_check on the result. No schema,
migration, network or model code is involved.

Restore is fresh-path only. The destination must not exist, must not be the backup file itself
(after resolving symlinks / relative paths), and must have no -journal/-wal/-shm companion; any of
these is refused before anything is opened, and nothing is ever deleted. The backup file and any
active store are left as they are. Pointing a configured service at the restored file is a later,
separately authorized operation with an exact target; this helper does not do it.

Exit codes: 0 ok, 1 refused/failed (reason on stderr), 3 locked (a worker holds the store).
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research.lock import StoreLock  # noqa: E402

SIDE_SUFFIXES = ("-journal", "-wal", "-shm")


def _integrity(path: Path) -> str:
    conn = sqlite3.connect(str(path))
    try:
        return str(conn.execute("PRAGMA integrity_check").fetchone()[0])
    finally:
        conn.close()


def _table_counts(path: Path) -> Dict[str, int]:
    conn = sqlite3.connect(str(path))
    try:
        names = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {n: int(conn.execute('SELECT COUNT(*) FROM "%s"' % n).fetchone()[0]) for n in names}
    finally:
        conn.close()


def _copy(src: Path, dst: Path) -> None:
    s = sqlite3.connect(str(src))
    d = sqlite3.connect(str(dst))
    try:
        s.backup(d)
    finally:
        d.close()
        s.close()


def backup(db: Path, out: Path) -> Dict[str, object]:
    if not db.exists():
        raise FileNotFoundError("store %s does not exist" % db)
    if out.exists():
        raise FileExistsError("backup target %s already exists; choose a new name" % out)
    out.parent.mkdir(parents=True, exist_ok=True)
    _copy(db, out)
    check = _integrity(out)
    if check != "ok":
        out.unlink()
        raise RuntimeError("backup integrity_check failed (%s); backup removed" % check)
    return {"action": "backup", "db": str(db), "out": str(out), "integrity": check, "tables": _table_counts(out)}


def check_fresh_destination(db: Path, src: Path) -> None:
    """Refuse anything but a brand-new destination path. Runs before any file is opened or locked."""
    if not src.exists():
        raise FileNotFoundError("backup %s does not exist" % src)
    if db.resolve() == src.resolve():
        raise ValueError("destination %s is the backup file itself; restore only into a new path" % db)
    if db.exists() or db.is_symlink():
        raise FileExistsError("destination %s already exists; restore only into a new path (nothing is overwritten)" % db)
    for suf in SIDE_SUFFIXES:
        side = db.with_name(db.name + suf)
        if side.exists() or side.is_symlink():
            raise FileExistsError("destination companion %s exists; choose a path with no journal/WAL/SHM "
                                  "companions (nothing is deleted)" % side)


def restore(db: Path, src: Path) -> Dict[str, object]:
    check_fresh_destination(db, src)
    try:
        check = _integrity(src)
    except sqlite3.DatabaseError as e:
        raise RuntimeError("backup %s is not a readable SQLite file (%s); not restored" % (src, e))
    if check != "ok":
        raise RuntimeError("backup %s fails integrity_check (%s); not restored" % (src, check))
    db.parent.mkdir(parents=True, exist_ok=True)
    _copy(src, db)
    check = _integrity(db)
    if check != "ok":
        raise RuntimeError("restored store fails integrity_check (%s)" % check)
    return {"action": "restore", "db": str(db), "from": str(src), "integrity": check, "tables": _table_counts(db)}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="wel50_store_backup")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backup"); b.add_argument("--db", required=True); b.add_argument("--out", required=True)
    r = sub.add_parser("restore"); r.add_argument("--db", required=True); r.add_argument("--from", dest="src", required=True)
    a = ap.parse_args(argv)
    db = Path(a.db)
    if a.cmd == "restore":
        try:
            check_fresh_destination(db, Path(a.src))   # refuse before the lock file is even created
        except Exception as e:
            print("%s: %s" % (type(e).__name__, e), file=sys.stderr)
            return 1
    lock = StoreLock(db)
    if not lock.acquire():
        print("store %s is held by a worker process (lock %s); nothing done" % (db, lock.path), file=sys.stderr)
        return 3
    try:
        res = backup(db, Path(a.out)) if a.cmd == "backup" else restore(db, Path(a.src))
    except Exception as e:
        print("%s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 1
    finally:
        lock.release()
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
