#!/bin/bash
# Robin: switch the public waitlist page (/robin) on or off. Writes only NON-secret settings, then restarts friday.
# Run as root:   bash /opt/friday/deploy/enable-robin-waitlist.sh [off]
# Optional:      ROBIN_CONTACT="WhatsApp DELETE to 98xxxxxx00" bash .../enable-robin-waitlist.sh   (shown on the privacy page)
set -euo pipefail
[ "$(id -u)" = 0 ] || [ -n "${FRIDAY_ENV_FILE:-}" ] || { echo "Run as root"; exit 1; }
case "${1:-}" in "") V=true ;; off) V=false ;; *) echo "Usage: enable-robin-waitlist.sh [off]"; exit 1 ;; esac
APP="${FRIDAY_APP:-/opt/friday}"; ENVF="${FRIDAY_ENV_FILE:-$APP/.env}"
[ -f "$ENVF" ] || { echo "No $ENVF"; exit 1; }
setv() { if grep -q "^$1=" "$ENVF"; then sed -i "s|^$1=.*|$1=$2|" "$ENVF"; else printf '%s=%s\n' "$1" "$2" >> "$ENVF"; fi; }
setv FRIDAY_ROBIN_WAITLIST_ENABLED "$V"
[ -n "${ROBIN_CONTACT:-}" ] && setv FRIDAY_ROBIN_WAITLIST_CONTACT "$(printf '%s' "$ROBIN_CONTACT" | tr -d '|&\n')"
echo "FRIDAY_ROBIN_WAITLIST_ENABLED=$V"
if [ -z "${FRIDAY_ENV_FILE:-}" ]; then systemctl restart friday && echo "friday restarted"; echo "Page: <your domain>/robin"; fi
