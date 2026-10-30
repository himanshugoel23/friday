#!/bin/bash
# Friday: store ONE API key on the server, typed hidden, never in chat or git.
# Run as root:   bash /opt/friday/deploy/set-key.sh GOOGLE_PLACES_API_KEY
# Allowed names are listed below. Prints only the LENGTH of what was saved, then restarts Friday.
# `show` as a second argument makes the paste visible on YOUR screen and clears it right after.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Run as root"; exit 1; }
NAME="${1:-}"
case "$NAME" in
  GOOGLE_PLACES_API_KEY|OPENAI_API_KEY|SARVAM_API_KEY|ELEVENLABS_API_KEY|ANTHROPIC_API_KEY|GOOGLE_OAUTH_CLIENT_ID|GOOGLE_OAUTH_CLIENT_SECRET|BROWSERBASE_API_KEY|BROWSERBASE_PROJECT_ID|STEEL_API_KEY|FRIDAY_REMOTE_BROWSER_CDP_URL) ;;
  *) echo "Usage: bash set-key.sh <GOOGLE_PLACES_API_KEY|OPENAI_API_KEY|SARVAM_API_KEY|ELEVENLABS_API_KEY|ANTHROPIC_API_KEY|GOOGLE_OAUTH_CLIENT_ID|GOOGLE_OAUTH_CLIENT_SECRET|BROWSERBASE_API_KEY|BROWSERBASE_PROJECT_ID|STEEL_API_KEY|FRIDAY_REMOTE_BROWSER_CDP_URL> [show]"; exit 1 ;;
esac
APP="${FRIDAY_APP:-/opt/friday}"; ENVF="${FRIDAY_ENV_FILE:-$APP/.env}"
[ -f "$ENVF" ] || { echo "No $ENVF: run small-server.sh first"; exit 1; }
if [ "${2:-}" = "show" ]; then read -r -p "$NAME: " V </dev/tty; clear; else read -r -s -p "$NAME (hidden): " V </dev/tty; echo; fi
V="$(printf %s "$V" | tr -d '[:space:]')"
[ -n "$V" ] || { echo "Nothing entered; nothing changed."; exit 0; }
FRIDAY_NEW_NAME="$NAME" FRIDAY_NEW_VAL="$V" python3 - "$ENVF" <<'PY'
import os, sys
p, k, v = sys.argv[1], os.environ["FRIDAY_NEW_NAME"], os.environ["FRIDAY_NEW_VAL"]
lines = [l for l in open(p).read().splitlines() if not l.startswith(k + "=")]
lines.append(f"{k}={v}")
open(p, "w").write("\n".join(lines) + "\n")
PY
chmod 600 "$ENVF"; chown friday:friday "$ENVF"
echo "saved $NAME (length ${#V})"
systemctl restart friday
echo "Friday restarted. Check: cd $APP && sudo -u friday /home/friday/.local/bin/uv run friday doctor 2>&1 | grep -i -E 'directory|geocoder|places'"
