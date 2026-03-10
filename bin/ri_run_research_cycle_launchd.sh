#!/bin/zsh
set -euo pipefail

export HOME="/Users/buddystudio1"
export USER="buddystudio1"
export SHELL="/bin/zsh"

export PATH="/opt/homebrew/opt/postgresql@16/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export DATABASE_URL="postgresql:///research_intelligence"
export OLLAMA_API_KEY="ollama-local"
export OLLAMA_KEEP_ALIVE="30m"

mkdir -p /Users/buddystudio1/ri_db/logs

cd /Users/buddystudio1/ri_db
/Users/buddystudio1/ri_db/bin/ri_run_research_cycle.sh
