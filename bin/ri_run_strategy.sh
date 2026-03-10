#!/usr/bin/env bash
set -euo pipefail

BIN_DIR="$HOME/ri_db/bin"
OUT_DIR="$HOME/ri_db/outputs"
INBOX_DIR="$HOME/ri_db/inbox"

mkdir -p "$INBOX_DIR/atlas" "$INBOX_DIR/karen"

ts="$(date +%Y-%m-%d_%H%M%S)"

atlas_in="$OUT_DIR/atlas_input.json"
karen_in="$OUT_DIR/karen_input.json"

test -s "$atlas_in"
test -s "$karen_in"

atlas_out="$INBOX_DIR/atlas/${ts}.atlas.json"
karen_out="$INBOX_DIR/karen/${ts}.karen.json"

"$BIN_DIR/with_lock.sh" "ri_atlas" "$BIN_DIR/oc_invoke_retry.sh" atlas "$atlas_in" > "$atlas_out" || true
"$BIN_DIR/with_lock.sh" "ri_karen" "$BIN_DIR/oc_invoke_retry.sh" karen "$karen_in" > "$karen_out" || true

test -s "$atlas_out" || rm -f "$atlas_out" 2>/dev/null || true
test -s "$karen_out" || rm -f "$karen_out" 2>/dev/null || true

"$HOME/ri_db/bin/ri_build_wellnest_dashboard_snapshot.sh"
