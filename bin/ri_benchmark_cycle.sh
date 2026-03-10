#!/bin/zsh
set -euo pipefail

export DATABASE_URL="postgresql:///research_intelligence"
export PATH="/opt/homebrew/opt/postgresql@16/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export OLLAMA_API_KEY="ollama-local"
export OLLAMA_KEEP_ALIVE="30m"

mkdir -p ~/ri_db/logs
ts=$(date +"%Y-%m-%d_%H%M%S")
report=~/ri_db/logs/benchmark_$ts.log

scour_query="working-moms-household-systems-benchmark-$ts"
hans_query="family-organizer-apps-benchmark-$ts"

run_step() {
  local name="$1"
  shift
  local start end dur
  start=$(python3 - <<'PY'
import time
print(time.time())
PY
)
  echo "===== START $name =====" | tee -a "$report"
  date | tee -a "$report"
  "$@" | tee -a "$report"
  end=$(python3 - <<'PY'
import time
print(time.time())
PY
)
  dur=$(python3 - <<PY
start=$start
end=$end
print(round(end-start, 2))
PY
)
  echo "===== END $name (${dur}s) =====" | tee -a "$report"
  date | tee -a "$report"
  echo | tee -a "$report"
}

echo "BENCHMARK REPORT: $report"
echo "Started at $(date)" | tee -a "$report"
echo "scour_query=$scour_query" | tee -a "$report"
echo "hans_query=$hans_query" | tee -a "$report"
echo | tee -a "$report"

run_step "seed_scour" ~/ri_db/bin/ri_seed_scour_job.sh "$scour_query"
run_step "seed_hans" ~/ri_db/bin/ri_seed_hans_job.sh "$hans_query"
run_step "run_scour" ~/ri_db/bin/ri_run_scour.sh
run_step "run_hans" ~/ri_db/bin/ri_run_hans.sh

run_step "seed_scout" ~/ri_db/bin/ri_seed_scout_from_scour.sh
run_step "seed_franz" ~/ri_db/bin/ri_seed_franz_from_hans.sh
run_step "run_scout" ~/ri_db/bin/ri_run_scout.sh
run_step "run_franz" ~/ri_db/bin/ri_run_franz.sh

run_step "seed_atlas" ~/ri_db/bin/ri_seed_atlas_job.sh
run_step "run_atlas" ~/ri_db/bin/ri_run_atlas.sh

run_step "seed_karen" ~/ri_db/bin/ri_seed_karen_job.sh
run_step "run_karen" ~/ri_db/bin/ri_run_karen.sh

echo "Finished at $(date)" | tee -a "$report"
echo "$report"
