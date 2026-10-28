#!/usr/bin/env bash
# Friday QA on the server (docs/QA_MANUAL.md): a page for your iPad with a Run button per scenario.
# The calls are REAL (Vobiz + Sarvam) but go ONLY to the one number on FRIDAY_PILOT_ALLOWED_NUMBERS,
# which must be your own phone. Run it inside tmux so it keeps running after you close the terminal:
#
#   tmux new -s qa
#   sudo bash /opt/friday/deploy/qa-live.sh                    # prints the link with the token
#   sudo bash /opt/friday/deploy/qa-live.sh --ttl-hours 2      # shorter-lived token
#   sudo bash /opt/friday/deploy/qa-live.sh --public-url https://YOUR-HOST
#   sudo FRIDAY_QA_MAX_SPEND_INR=200 FRIDAY_QA_MAX_CALLS_PER_DAY=30 bash /opt/friday/deploy/qa-live.sh   # other caps
# Detach with ctrl-b d; stop with ctrl-c inside the session (the front door starts again by itself).
#
# To open it from an iPad over HTTPS first run, once:  sudo bash /opt/friday/deploy/qa-https.sh
# (this script then prints the https link by itself). Any extra arguments go to `friday qa serve`.
#
# What this script does:
#   1. pulls the latest code (fast-forward only)
#   2. stops the front-door service (a QA call starts its own Friday on the same port so Vobiz can call
#      back into it) and starts it again when you stop this script, even after an error
#   3. sets the QA switches for THIS process only: FRIDAY_QA_LIVE=true (the default everywhere else is OFF)
#   4. runs `friday qa serve` on 127.0.0.1:8767 (Caddy is the only way in)
# `friday qa serve` itself refuses unless FRIDAY_MODE=live, FRIDAY_PROFILE=pilot and exactly one number
# is on FRIDAY_PILOT_ALLOWED_NUMBERS. Kill switch: `friday pause` from another window.
set -euo pipefail
APP_DIR="${FRIDAY_APP_DIR:-/opt/friday}"
RUN_USER="${FRIDAY_RUN_USER:-friday}"
UV="${UV_BIN:-/home/$RUN_USER/.local/bin/uv}"
[ -x "$UV" ] || UV="$(command -v uv || true)"
[ -n "$UV" ] || { echo "uv not found (expected /home/$RUN_USER/.local/bin/uv)"; exit 1; }

# Pass any FRIDAY_QA_* setting given to this script (for example FRIDAY_QA_MAX_SPEND_INR=200) on to the
# friday process; nothing else of this environment is passed on.
export FRIDAY_QA_LIVE=true   # QA mode is ON for this process tree only; the default everywhere else is OFF
QA_ENV=()
while IFS= read -r kv; do QA_ENV+=("$kv"); done < <(env | grep '^FRIDAY_QA_' || true)

as_friday() {
  if [ "$(id -u)" = 0 ] && [ "$RUN_USER" != root ]; then
    sudo -u "$RUN_USER" env PYTHONUNBUFFERED=1 ${QA_ENV[@]+"${QA_ENV[@]}"} "$@"
  else
    env PYTHONUNBUFFERED=1 "$@"
  fi
}

if [ "${FRIDAY_QA_SKIP_PULL:-0}" != 1 ]; then
  git config --global --add safe.directory "$APP_DIR" 2>/dev/null || true
  git -C "$APP_DIR" pull --ff-only || { echo "git pull failed: stopping"; exit 1; }
fi

# Notes, runs and the pending lines you heard go here (gitignored var/).
mkdir -p "$APP_DIR/var/qa" "$APP_DIR/var/livecalls" "$APP_DIR/var/consumer_calls"
chown -R "$RUN_USER": "$APP_DIR/var/qa" "$APP_DIR/var/livecalls" "$APP_DIR/var/consumer_calls" 2>/dev/null || true

if [ "$(id -u)" = 0 ] && [ "${FRIDAY_QA_KEEP_FRONT_DOOR:-0}" != 1 ]; then
  trap 'echo "Starting the front door again..."; systemctl start friday' EXIT   # always comes back
  echo "Stopping the front door (QA calls need the port)..."
  systemctl stop friday || true
fi

# If lab-https.sh / qa-https.sh added the /qa route, print the https link by default.
ARGS=("$@")
if ! printf '%s\n' "$@" | grep -q -- '--public-url'; then
  CF=/etc/caddy/Caddyfile
  if [ -r "$CF" ] && grep -q 'handle /qa/\*' "$CF"; then
    HOST="$(awk 'NF{print $1; exit}' "$CF")"
    [ -z "$HOST" ] || ARGS+=(--public-url "https://$HOST")
  fi
fi

as_friday "$UV" run --directory "$APP_DIR" friday qa serve --host 127.0.0.1 \
  --port "${FRIDAY_QA_PORT:-8767}" ${ARGS[@]+"${ARGS[@]}"}
