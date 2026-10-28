#!/bin/bash
# Friday: update the SMALL server in one command (code + packages + database + restart + health check).
# Run as root:   bash /opt/friday/deploy/small-update.sh
# (deploy/update.sh is for the Docker/AWS setup; this one is for the single droplet.)
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Run as root"; exit 1; }
APP="${FRIDAY_APP:-/opt/friday}"
BRANCH="${FRIDAY_BRANCH:-claude/friday-phase-1}"
UV=/home/friday/.local/bin/uv
as_friday() { sudo -u friday "$@"; }
cd "$APP"
echo "== 1/4 code"
as_friday git fetch origin "$BRANCH" 2>&1 | tail -1
as_friday git checkout "$BRANCH" 2>&1 | tail -1
as_friday git pull --ff-only origin "$BRANCH" 2>&1 | tail -2
echo "== 2/4 packages"
as_friday bash -c "cd $APP && $UV sync --no-dev --extra vad" 2>&1 | tail -2
echo "== 3/4 database (migrations)"
as_friday bash -c "cd $APP && $UV run python -m friday.db.migrate up" 2>&1 | tail -3
echo "== 4/4 restart + health check"
systemctl restart friday
sleep 20
as_friday bash -c "cd $APP && $UV run friday doctor" 2>&1 | grep -i -E "FAIL|ok,|migration" | head -8
echo "Done. Health: curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/health"
