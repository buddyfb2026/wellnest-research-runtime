#!/usr/bin/env bash
set -euo pipefail

LOCK_NAME="${1:-}"
shift || true
[ -n "$LOCK_NAME" ] || { echo "usage: with_lock.sh <lock_name> <command...>"; exit 2; }

LOCKDIR="$HOME/ri_db/locks"
mkdir -p "$LOCKDIR"

LOCK="$LOCKDIR/$LOCK_NAME.lock"
PIDFILE="$LOCK/pid"
TSFILE="$LOCK/ts"

TTL_SECONDS="${LOCK_TTL_SECONDS:-7200}"

now_epoch() { date +%s; }

is_pid_alive() {
  local pid="${1:-}"
  [ -n "$pid" ] || return 1
  kill -0 "$pid" 2>/dev/null
}

lock_age_seconds() {
  if [ -f "$TSFILE" ]; then
    local ts
    ts="$(cat "$TSFILE" 2>/dev/null || echo "")"
    if [[ "$ts" =~ ^[0-9]+$ ]]; then
      echo $(( $(now_epoch) - ts ))
      return 0
    fi
  fi
  echo 999999
}

break_stale_lock_if_needed() {
  if [ -d "$LOCK" ]; then
    local pid age
    pid="$(cat "$PIDFILE" 2>/dev/null || echo "")"
    age="$(lock_age_seconds)"

    if ! is_pid_alive "$pid"; then
      rm -rf "$LOCK" 2>/dev/null || true
      return 0
    fi

    if [ "$age" -gt "$TTL_SECONDS" ]; then
      rm -rf "$LOCK" 2>/dev/null || true
      return 0
    fi
  fi
}

break_stale_lock_if_needed

if mkdir "$LOCK" 2>/dev/null; then
  echo "$$" > "$PIDFILE" 2>/dev/null || true
  echo "$(now_epoch)" > "$TSFILE" 2>/dev/null || true
  trap 'rm -rf "$LOCK" 2>/dev/null || true' EXIT
  exec "$@"
else
  echo "LOCKED: $LOCK_NAME" >&2
  exit 0
fi
