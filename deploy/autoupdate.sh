#!/bin/bash
# Friday: self-updating small server (docs/AUTOUPDATE.md). Run by a systemd timer as root every 3 minutes.
# If origin has new commits on the branch: pull (fast-forward only), uv sync, migrate, restart, health check.
# Writes a plain-text report to var/autoupdate/status.txt (served read-only at /ops-status/<token>).
# The report never contains secrets. It runs only this fixed sequence; it does not execute other scripts.
set -uo pipefail
APP="${FRIDAY_APP:-/opt/friday}"
BRANCH="${FRIDAY_BRANCH:-claude/friday-phase-1}"
UV=/home/friday/.local/bin/uv
STATE="$APP/var/autoupdate"
mkdir -p "$STATE"; chown -R friday:friday "$APP/var" 2>/dev/null
exec 9>"$STATE/lock"; flock -n 9 || exit 0
as_friday() { sudo -u friday "$@"; }
cd "$APP" || exit 1
as_friday git fetch -q origin "$BRANCH" 2>/dev/null
LOCAL=$(as_friday git rev-parse HEAD); REMOTE=$(as_friday git rev-parse "origin/$BRANCH")
if [ "$LOCAL" = "$REMOTE" ] && [ -f "$STATE/status.txt" ]; then exit 0; fi
REPORT="$STATE/status.txt.new"
{
echo "== autoupdate $(date -u +%FT%TZ)"
echo "from $LOCAL"
if [ "$LOCAL" != "$REMOTE" ]; then
  as_friday git checkout -q "$BRANCH" 2>&1 | tail -1
  as_friday git merge --ff-only -q "origin/$BRANCH" 2>&1 | tail -2
  echo "to   $(as_friday git rev-parse HEAD)"
  echo "-- packages"; as_friday bash -c "cd $APP && $UV sync --no-dev --extra vad" 2>&1 | tail -2
  echo "-- migrate";  as_friday bash -c "cd $APP && $UV run python -m friday.db.migrate up" 2>&1 | tail -4
  echo "-- restart";  systemctl restart friday; sleep 20
fi
echo "-- service: $(systemctl is-active friday)"
echo "-- health:  $(curl -s -m 8 -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health)"
echo "-- doctor"
as_friday bash -c "cd $APP && $UV run friday doctor" 2>&1 | grep -E "\[FAIL\]|\[WARN\]|ok,|DOCTOR" | cut -c1-300 | head -30
} > "$REPORT" 2>&1
mv "$REPORT" "$STATE/status.txt"; chown friday:friday "$STATE/status.txt"
