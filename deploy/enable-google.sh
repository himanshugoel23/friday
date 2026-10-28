#!/bin/bash
# Friday: switch the Google connector ON (after GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET were saved with
# deploy/set-key.sh). Run as root:   bash /opt/friday/deploy/enable-google.sh      (undo: ... off)
# Writes only NON-secret settings: FRIDAY_GOOGLE_REDIRECT_URI (= FRIDAY_PUBLIC_BASE_URL + /google/callback) and
# FRIDAY_GOOGLE_GMAIL_ENABLED. Prints names and set/missing only. Restarts the service.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Run as root"; exit 1; }
ENVF=/opt/friday/.env
get() { grep -E "^$1=" "$ENVF" | tail -1 | cut -d= -f2- | tr -d ' \r"'"'"; }
put() { if grep -qE "^$1=" "$ENVF"; then sed -i "s#^$1=.*#$1=$2#" "$ENVF"; else echo "$1=$2" >> "$ENVF"; fi; }
if [ "${1:-}" = "off" ]; then
  put FRIDAY_GOOGLE_GMAIL_ENABLED false; put FRIDAY_GOOGLE_ENABLED false; systemctl restart friday; echo "google gmail: off"; exit 0
fi
BASE=$(get FRIDAY_PUBLIC_BASE_URL); BASE=${BASE%/}
[ -n "$BASE" ] || { echo "FRIDAY_PUBLIC_BASE_URL is not set"; exit 2; }
put FRIDAY_GOOGLE_REDIRECT_URI "$BASE/google/callback"
put FRIDAY_GOOGLE_GMAIL_ENABLED true
put FRIDAY_GOOGLE_ENABLED true   # builds the consumer router that owns "connect google"
systemctl restart friday
echo "Redirect URI to put in Google Cloud (it is not a secret): $BASE/google/callback"
for k in GOOGLE_OAUTH_CLIENT_ID GOOGLE_OAUTH_CLIENT_SECRET FRIDAY_GOOGLE_REDIRECT_URI FRIDAY_GOOGLE_ENABLED FRIDAY_GOOGLE_GMAIL_ENABLED; do
  v=$(get "$k"); if [ -n "$v" ]; then echo "  $k  set"; else echo "  $k  MISSING"; fi
done
