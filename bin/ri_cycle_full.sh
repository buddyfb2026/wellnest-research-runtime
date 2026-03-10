#!/usr/bin/env bash
set -euo pipefail
"$HOME/ri_db/bin/ri_cycle_archive.sh"
"$HOME/ri_db/bin/ri_normalize_entities_from_payloads.sh" || true

"$HOME/ri_db/bin/ri_build_wellnest_dashboard_snapshot.sh"
