#!/usr/bin/env bash
# Open the Friday QA page over the server's HTTPS address (https://<host>/qa/...), so you can use it
# from an iPad/phone browser. Same pattern as deploy/lab-https.sh (the Chat Lab); this script only
# adds or removes the /qa route and KEEPS an existing /explore and /lab route.
#
#   sudo bash /opt/friday/deploy/qa-https.sh        # add the /qa route to Caddy
#   sudo bash /opt/friday/deploy/qa-https.sh --off  # remove it again
#
# The route only forwards /qa/* to 127.0.0.1:8767, where deploy/qa-live.sh listens while it runs
# (otherwise Caddy answers 502). Every page and API call needs the unguessable token that the QA
# page prints, and the token stops working after a few hours. The token is part of the URL path, so
# it also appears in Caddy's access log: do not share that log.
#
# Order: explore-https.sh rewrites the whole Caddyfile (it knows only /explore). If you use several,
# run explore-https.sh first, then lab-https.sh, then this script.
set -euo pipefail
# CADDYFILE overrides the path for tests only (tests/qa/test_deploy_scripts.py), without root.
[[ $EUID -eq 0 || -n ${CADDYFILE:-} ]] || { echo "run with sudo"; exit 1; }
CF="${CADDYFILE:-/etc/caddy/Caddyfile}"
[[ -f $CF ]] || { echo "no $CF (this server does not use Caddy)"; exit 1; }
HOST=$(awk 'NF{print $1; exit}' "$CF")
[[ -n $HOST && $HOST != "{" ]] || { echo "cannot read the site name from $CF"; exit 1; }
QA_PORT="${FRIDAY_QA_PORT:-8767}"
LAB_PORT="${FRIDAY_LAB_PORT:-8766}"
HAS_EXPLORE=0
grep -q 'handle_path /explore/\*' "$CF" && HAS_EXPLORE=1
HAS_LAB=0
grep -q 'handle /lab/\*' "$CF" && HAS_LAB=1
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
  if [[ $OFF == 0 ]]; then
    cat <<CADDY
    handle /qa/* {
        reverse_proxy 127.0.0.1:$QA_PORT
    }
CADDY
  fi
  cat <<CADDY
    handle {
        reverse_proxy 127.0.0.1:8000
    }
}
CADDY
} > "$CF"

if ! caddy validate --config "$CF" >/dev/null 2>&1; then
  echo "Caddyfile invalid; restoring the old one"; cp "$BAK" "$CF"; exit 1
fi
systemctl reload caddy
if [[ $OFF == 1 ]]; then echo "route removed"; else
  echo "OK. Next: sudo bash /opt/friday/deploy/qa-live.sh   (it prints the https://$HOST/qa/... link)"
fi
