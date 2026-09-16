"""Build one WEL-52 recipe pack from the authoritative research store."""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research.recipe_pack import ExportLockBusy, ExportRefused, export_recipe_pack  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("db", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--allow-fixture-evidence", action="store_true",
                        help="test only: stamp _fixture and permit fixture evidence")
    args = parser.parse_args()
    try:
        pack = export_recipe_pack(args.db, args.out,
                                  allow_fixture_evidence=args.allow_fixture_evidence)
    except (ExportLockBusy, ExportRefused, OSError, sqlite3.Error) as exc:
        parser.error(str(exc))
    print(json.dumps({"pack_id": pack["pack_id"], "generation": pack["generation"],
                      "recipes": len(pack["recipes"]), "withdrawn": len(pack["withdrawn"]),
                      "omitted": len(pack["omitted"])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
