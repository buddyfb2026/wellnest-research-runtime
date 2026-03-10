#!/usr/bin/env bash
set -euo pipefail
ROOT="$HOME/ri_db"
ARCH="$ROOT/archive/$(date +%Y-%m-%d)"
mkdir -p "$ARCH"
find "$ROOT/inbox" -maxdepth 2 -type f -name "*.json" -print0 | while IFS= read -r -d '' f; do
  cp -a "$f" "$ARCH/" 2>/dev/null || true
done
exec "$ROOT/bin/ri_cycle.sh"
