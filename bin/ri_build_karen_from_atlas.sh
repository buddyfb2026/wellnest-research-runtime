#!/usr/bin/env bash
set -euo pipefail

IN="$HOME/ri_db/inbox/atlas"
OUT="$HOME/ri_db/outputs/karen_input.json"

latest="$(ls -1t "$IN"/*.atlas.json | head -n 1)"

python3 - "$latest" "$OUT" <<'PY'
import json,sys
src,dst=sys.argv[1],sys.argv[2]
d=json.load(open(src))
out={
  "created_at": d.get("run_id",""),
  "top_opportunities": d.get("top_opportunities", [])
}
json.dump(out, open(dst,"w"), indent=2)
PY

test -s "$OUT"
echo "OK: wrote $OUT"
