#!/usr/bin/env bash
set -euo pipefail

"$HOME/ri_db/bin/ri_process_inbox.sh"
"$HOME/ri_db/bin/ri_build_atlas_input.sh"
"$HOME/ri_db/bin/ri_build_karen_input.sh"
