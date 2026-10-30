#!/bin/bash
# Friday: switch the managed remote browser (Browserbase) on or off. Writes only NON-secret settings.
# Run as root:   bash /opt/friday/deploy/enable-remote-browser.sh        (on)
# Undo:          bash /opt/friday/deploy/enable-remote-browser.sh off
# Keys (BROWSERBASE_API_KEY, BROWSERBASE_PROJECT_ID) are NOT touched: use deploy/set-key.sh for those.
# Re-running deploy/enable-web-test.sh writes FRIDAY_REMOTE_BROWSER_ENABLED=false again: run this after it.
# Prints setting NAMES and values that are not secret (on/off, provider name, cap), then restarts friday.
set -euo pipefail
[ "$(id -u)" = 0 ] || [ -n "${FRIDAY_ENV_FILE:-}" ] || { echo "Run as root"; exit 1; }
case "${1:-}" in
  "") ENABLED=true ;;
  off) ENABLED=false ;;
  *) echo "Usage: bash enable-remote-browser.sh [off]"; exit 1 ;;
esac
APP="${FRIDAY_APP:-/opt/friday}"; ENVF="${FRIDAY_ENV_FILE:-$APP/.env}"
[ -f "$ENVF" ] || { echo "No $ENVF"; exit 1; }
setv() {  # replace the key in place or append it; the values here are fixed, non-secret words/numbers
  if grep -q "^$1=" "$ENVF"; then sed -i "s|^$1=.*|$1=$2|" "$ENVF"; else printf '%s=%s\n' "$1" "$2" >> "$ENVF"; fi
}
setv FRIDAY_REMOTE_BROWSER_PROVIDER browserbase
setv FRIDAY_REMOTE_BROWSER_DAILY_SESSIONS 6
setv FRIDAY_REMOTE_BROWSER_ENABLED "$ENABLED"
for k in BROWSERBASE_API_KEY BROWSERBASE_PROJECT_ID; do
  if grep -q "^$k=." "$ENVF"; then echo "$k: set"; else echo "$k: MISSING (run deploy/set-key.sh $k)"; fi
done
echo "FRIDAY_REMOTE_BROWSER_ENABLED=$ENABLED  FRIDAY_REMOTE_BROWSER_PROVIDER=browserbase  FRIDAY_REMOTE_BROWSER_DAILY_SESSIONS=6"
if [ -z "${FRIDAY_ENV_FILE:-}" ]; then systemctl restart friday && echo "friday restarted"; fi
