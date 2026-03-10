#!/usr/bin/env bash
set -euo pipefail
shopt -s nullglob

ROOT="$HOME/ri_db"
IN="$ROOT/inbox"
TMP="$ROOT/tmp"
mkdir -p "$TMP"

adapt_one() {
  local f="$1"
  local out="$TMP/$(basename "$f").tmp"
  python3 - "$f" "$out" <<'PY'
import json,sys
src,dst=sys.argv[1],sys.argv[2]

with open(src,"r") as fh:
  d=json.load(fh)

schema=d.get("schema","")

if schema=="growth.creator_discovery.v2" and isinstance(d.get("creators"), list):
  items=[]
  for c in d["creators"]:
    items.append({
      "platform": c.get("platform"),
      "handle": c.get("handle"),
      "profile_url": c.get("profile_url"),
      "followers": c.get("followers", None)
    })
  out={
    "schema":"growth.creator_discovery.v1",
    "generated_at": d.get("generated_at"),
    "topic": d.get("topic"),
    "items": items
  }
  json.dump(out, open(dst,"w"), indent=2)
  sys.exit(0)

if schema=="competitor.discovery.v2" and isinstance(d.get("competitors"), list):
  items=[]
  for c in d["competitors"]:
    items.append({
      "name": c.get("name"),
      "website": c.get("website"),
      "category": c.get("category")
    })
  out={
    "schema":"competitor.discovery.v1",
    "generated_at": d.get("generated_at"),
    "items": items
  }
  json.dump(out, open(dst,"w"), indent=2)
  sys.exit(0)

json.dump(d, open(dst,"w"), indent=2)
PY
  mv "$out" "$f"
}

for f in "$IN"/scour/*.json; do
  adapt_one "$f"
done

for f in "$IN"/hans/*.json; do
  adapt_one "$f"
done
