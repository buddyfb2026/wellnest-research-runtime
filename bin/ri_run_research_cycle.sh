#!/usr/bin/env bash
set -euo pipefail

echo "===== WELLNEST RESEARCH CYCLE START ====="
date

echo "Seeding upstream discovery..."
~/ri_db/bin/ri_seed_scour_job.sh "working parent household routines"
~/ri_db/bin/ri_seed_hans_job.sh "family organizer apps"

echo "Running upstream discovery..."
~/ri_db/bin/ri_run_scour.sh
~/ri_db/bin/ri_run_hans.sh

echo "Seeding analysis layer..."
~/ri_db/bin/ri_seed_scout_from_scour.sh
~/ri_db/bin/ri_seed_franz_from_hans.sh

echo "Running analysis layer..."
~/ri_db/bin/ri_run_scout.sh
~/ri_db/bin/ri_run_franz.sh

echo "Seeding opportunity layer..."
~/ri_db/bin/ri_seed_atlas_job.sh

echo "Running opportunity ranking..."
~/ri_db/bin/ri_run_atlas.sh

echo "Seeding feature spec generation..."
~/ri_db/bin/ri_seed_karen_job.sh

echo "Running feature spec generation..."
~/ri_db/bin/ri_run_karen.sh

echo "===== WELLNEST RESEARCH CYCLE COMPLETE ====="
date
