#!/usr/bin/env bash
set -euo pipefail

ROOT="$HOME/ri_db"
LOG="$ROOT/logs/research.log"
INBOX="$ROOT/inbox"

mkdir -p "$ROOT/logs" "$INBOX/scour" "$INBOX/hans"

ts="$(date +%Y-%m-%d_%H%M%S)"

scour_out="$INBOX/scour/${ts}.scour.json"
hans_out="$INBOX/hans/${ts}.hans.json"

echo "RUN $ts" >> "$LOG"

"$ROOT/bin/with_lock.sh" "research_scour" "$ROOT/bin/oc_invoke_retry_prompt.sh" scour \
"Return JSON only.
schema: growth.creator_discovery.v2
run_id: $ts
topic: household management, groceries, errands, family coordination, home routines

Output EXACTLY:
{
  \"schema\":\"growth.creator_discovery.v2\",
  \"run_id\":\"$ts\",
  \"generated_at\":\"<iso>\",
  \"topic\":\"household management\",
  \"creators\":[
    {\"platform\":\"YouTube|TikTok|Instagram|Pinterest|Facebook|X\",\"handle\":\"...\",\"profile_url\":\"...\",\"notes\":\"...\"}
  ]
}

Rules:
- creators must have 20-60 entries
- include real handles + real profile URLs
- no rubrics, archetypes, or strategy text" \
> "$scour_out" 2>> "$LOG" || true

"$ROOT/bin/with_lock.sh" "research_hans" "$ROOT/bin/oc_invoke_retry_prompt.sh" hans \
"Return JSON only.
schema: competitor.discovery.v2
run_id: $ts
topic: apps for household calm (errands, groceries, to-dos, family coordination, home management)

Output EXACTLY:
{
  \"schema\":\"competitor.discovery.v2\",
  \"run_id\":\"$ts\",
  \"generated_at\":\"<iso>\",
  \"competitors\":[
    {\"name\":\"...\",\"website\":\"...\",\"category\":\"...\",\"notes\":\"...\"}
  ]
}

Rules:
- competitors must have 10-40 entries
- include real websites
- no strategy text" \
> "$hans_out" 2>> "$LOG" || true

test -s "$scour_out" || rm -f "$scour_out" 2>/dev/null || true
test -s "$hans_out" || rm -f "$hans_out" 2>/dev/null || true

echo "DONE $ts" >> "$LOG"
