#!/usr/bin/env bash
# Friday: founder-supervised REAL-site explore run of the Zomato connector (docs/ZOMATO_EXPLORE.md).
# Run on the server (as root or as the friday user):
#   bash /opt/friday/deploy/zomato-explore.sh                       # real zomato.com, login with YOUR number
#   bash /opt/friday/deploy/zomato-explore.sh --fake                # dry run on the local FAKE site first
#   bash /opt/friday/deploy/zomato-explore.sh --add-item "Margherita" --hold 600
# Any extra arguments go straight to `friday connectors zomato-explore` (see --help there).
# It logs in with the FIRST number of FRIDAY_PILOT_ALLOWED_NUMBERS (read by the app from
# /opt/friday/.env; this script never prints the env). It stops before any order and never pays.
set -euo pipefail
APP_DIR="${FRIDAY_APP_DIR:-/opt/friday}"
RUN_USER="${FRIDAY_RUN_USER:-friday}"
UV="${UV_BIN:-/home/$RUN_USER/.local/bin/uv}"
[ -x "$UV" ] || UV="$(command -v uv || true)"
[ -n "$UV" ] || { echo "uv not found (expected /home/$RUN_USER/.local/bin/uv)"; exit 1; }

# Run a command as the friday user (same pattern as deploy/call-me.sh), passing only what we need.
as_friday() {
  if [ "$(id -u)" = 0 ] && [ "$RUN_USER" != root ]; then
    sudo -u "$RUN_USER" env PYTHONUNBUFFERED=1 ${PLAYWRIGHT_CHROMIUM_PATH:+PLAYWRIGHT_CHROMIUM_PATH="$PLAYWRIGHT_CHROMIUM_PATH"} "$@"
  else
    env PYTHONUNBUFFERED=1 "$@"
  fi
}
UVRUN=("$UV" run --directory "$APP_DIR" --extra browser)

# 1) A virtual display for the headed Chromium.
if ! command -v xvfb-run >/dev/null 2>&1; then
  CMD="apt-get install -y xvfb"
  if [ "$(id -u)" = 0 ]; then
    echo "xvfb-run is missing. Installing it now with:  $CMD"
    $CMD
  else
    echo "xvfb-run is missing. Run this once as root, then start again:  sudo $CMD"
    exit 1
  fi
fi

# 2) Chromium: use the one we can already find (PLAYWRIGHT_CHROMIUM_PATH or /opt/pw-browsers).
FOUND="$(as_friday "${UVRUN[@]}" python -c \
  'from friday.connectors.browser.playwright_session import find_chromium; print(find_chromium() or "")' \
  2>/dev/null | tail -n1 || true)"
if [ -z "$FOUND" ]; then
  echo "No Chromium found (checked PLAYWRIGHT_CHROMIUM_PATH and /opt/pw-browsers)."
  echo "Installing one with 'playwright install chromium' (only because none was found)."
  as_friday "${UVRUN[@]}" playwright install chromium
  echo "Installed. If Friday still cannot find it, set PLAYWRIGHT_CHROMIUM_PATH to the chrome binary."
else
  echo "Chromium found."
fi

# 3) The run, under a virtual display. Output is the two links you open; nothing secret is printed.
mkdir -p "$APP_DIR/var/connectors" && chown "$RUN_USER": "$APP_DIR/var" "$APP_DIR/var/connectors" 2>/dev/null || true
set +e
as_friday xvfb-run -a --server-args="-screen 0 1280x960x24" \
  "${UVRUN[@]}" friday connectors zomato-explore "$@"
RC=$?
set -e

LAST="$(ls -1dt "$APP_DIR"/var/connectors/zomato-explore/*/ 2>/dev/null | head -n1 || true)"
echo
echo "Exit code $RC (0 = finished, 3 = stopped safely, see REASON above)."
[ -z "$LAST" ] || echo "Zip it for the lead:  $UV run --directory $APP_DIR friday connectors pack-run ${LAST%/}"
exit "$RC"
