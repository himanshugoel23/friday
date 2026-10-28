#!/bin/bash
# Friday: switch the WhatsApp chat pilot ON on the server (names/values only, no secrets).
# Run as root:   bash /opt/friday/deploy/enable-chat-pilot.sh
# Sets FRIDAY_CHATBOT_ONBOARDING=true and FRIDAY_PILOT=true (only allow-listed testers onboard), restarts Friday.
# Undo: bash /opt/friday/deploy/enable-chat-pilot.sh off
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Run as root"; exit 1; }
APP="${FRIDAY_APP:-/opt/friday}"; ENVF="${FRIDAY_ENV_FILE:-$APP/.env}"
[ -f "$ENVF" ] || { echo "No $ENVF"; exit 1; }
VAL=true; [ "${1:-}" = "off" ] && VAL=false
setv() { FRIDAY_NEW_NAME="$1" FRIDAY_NEW_VAL="$2" python3 - "$ENVF" <<'PY'
import os, sys
p, k, v = sys.argv[1], os.environ["FRIDAY_NEW_NAME"], os.environ["FRIDAY_NEW_VAL"]
lines = [l for l in open(p).read().splitlines() if not l.startswith(k + "=")]
lines.append(f"{k}={v}")
open(p, "w").write("\n".join(lines) + "\n")
PY
}
setv FRIDAY_CHATBOT_ONBOARDING "$VAL"
setv FRIDAY_PILOT "$VAL"
chmod 600 "$ENVF"; chown friday:friday "$ENVF"
systemctl restart friday
echo "chat pilot: $VAL (FRIDAY_CHATBOT_ONBOARDING, FRIDAY_PILOT). Allowed testers = FRIDAY_PILOT_ALLOWED_NUMBERS + FRIDAY_CHATBOT_TESTERS."
echo "Now send 'hi' to the test number from an allowed phone. Logs: journalctl -u friday -n 40 --no-pager | cut -c1-220"
