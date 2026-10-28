#!/usr/bin/env bash
# Make the Friday Web channel (https://<host>/web/...) explicit in Caddy and add a noindex header to it.
# The web channel runs INSIDE `friday serve` (port 8000), so the default Caddy handler already reaches it;
# this script only pins the route (with X-Robots-Tag: noindex) and KEEPS an existing /explore, /lab, /qa route.
#
#   sudo bash /opt/friday/deploy/web-https.sh        # add the /web route
#   sudo bash /opt/friday/deploy/web-https.sh --off  # remove it again (the default handler still forwards /web)
#
# Then, in the server env: FRIDAY_WEB_CHANNEL_ENABLED=true (and FRIDAY_PROFILE=pilot), restart friday, and
# create each tester's personal link: friday web invite --name ... --phone +91...
# The token is part of the URL path, so it appears in Caddy's access log: do not share that log.
#
# Order: explore-https.sh rewrites the whole Caddyfile; run it first, then lab-https.sh / qa-https.sh,
# then this script (those scripts do not know /web and would drop this explicit route; the default handler
# keeps /web working either way).
set -euo pipefail
# CADDYFILE overrides the path for tests only (tests/webchat/test_deploy.py), without root.
[[ $EUID -eq 0 || -n ${CADDYFILE:-} ]] || { echo "run with sudo"; exit 1; }
CF="${CADDYFILE:-/etc/caddy/Caddyfile}"
[[ -f $CF ]] || { echo "no $CF (this server does not use Caddy)"; exit 1; }
HOST=$(awk 'NF{print $1; exit}' "$CF")
[[ -n $HOST && $HOST != "{" ]] || { echo "cannot read the site name from $CF"; exit 1; }
APP_PORT="${FRIDAY_PORT:-8000}"
LAB_PORT="${FRIDAY_LAB_PORT:-8766}"
QA_PORT="${FRIDAY_QA_PORT:-8767}"
HAS_EXPLORE=0; grep -q 'handle_path /explore/\*' "$CF" && HAS_EXPLORE=1
HAS_LAB=0;     grep -q 'handle /lab/\*' "$CF" && HAS_LAB=1
HAS_QA=0;      grep -q 'handle /qa/\*' "$CF" && HAS_QA=1
BAK="$CF.bak.$(date +%s)"
cp "$CF" "$BAK"
OFF=0
[[ ${1:-} == "--off" ]] && OFF=1

{
  echo "$HOST {"
  echo "    encode gzip"
  if [[ $HAS_EXPLORE == 1 ]]; then
    cat <<CADDY
    handle_path /explore/* {
        reverse_proxy 127.0.0.1:8765
    }
CADDY
  fi
  if [[ $HAS_LAB == 1 ]]; then
    cat <<CADDY
    handle /lab/* {
        reverse_proxy 127.0.0.1:$LAB_PORT
    }
CADDY
  fi
  if [[ $HAS_QA == 1 ]]; then
    cat <<CADDY
    handle /qa/* {
        reverse_proxy 127.0.0.1:$QA_PORT
    }
CADDY
  fi
  if [[ $OFF == 0 ]]; then
    cat <<CADDY
    handle /web/* {
        header X-Robots-Tag "noindex, nofollow"
        reverse_proxy 127.0.0.1:$APP_PORT
    }
CADDY
  fi
  cat <<CADDY
    handle {
        reverse_proxy 127.0.0.1:$APP_PORT
    }
}
CADDY
} > "$CF"

if ! caddy validate --config "$CF" >/dev/null 2>&1; then
  echo "Caddyfile invalid; restoring the old one"; cp "$BAK" "$CF"; exit 1
fi
systemctl reload caddy
if [[ $OFF == 1 ]]; then echo "route removed"; else
  echo "OK. Next: set FRIDAY_WEB_CHANNEL_ENABLED=true, restart friday, then: friday web invite --name NAME --phone +91..."
fi
