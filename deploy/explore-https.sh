#!/usr/bin/env bash
# Open the Zomato explore run's watch page and code page over the server's HTTPS address
# (https://<host>/explore/...), so you can use them from an iPad/phone browser. No SSH tunnel needed.
# Founder approved this route on 2026-10-17.
#
#   sudo bash /opt/friday/deploy/explore-https.sh        # add the /explore route to Caddy
#   sudo bash /opt/friday/deploy/explore-https.sh --off  # remove it again
#
# The route only forwards /explore/* to 127.0.0.1:8765, where zomato-explore.sh listens while it runs
# (otherwise Caddy answers 502). Every page needs an unguessable token that the run prints.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }
CF=/etc/caddy/Caddyfile
[[ -f $CF ]] || { echo "no $CF (this server does not use Caddy)"; exit 1; }
HOST=$(awk 'NF{print $1; exit}' "$CF")
[[ -n $HOST && $HOST != "{" ]] || { echo "cannot read the site name from $CF"; exit 1; }
BAK="$CF.bak.$(date +%s)"
cp "$CF" "$BAK"
if [[ ${1:-} == "--off" ]]; then
  cat > "$CF" <<CADDY
$HOST {
    encode gzip
    reverse_proxy 127.0.0.1:8000
}
CADDY
else
  cat > "$CF" <<CADDY
$HOST {
    encode gzip
    handle_path /explore/* {
        reverse_proxy 127.0.0.1:8765
    }
    handle {
        reverse_proxy 127.0.0.1:8000
    }
}
CADDY
fi
if ! caddy validate --config "$CF" >/dev/null 2>&1; then
  echo "Caddyfile invalid; restoring the old one"; cp "$BAK" "$CF"; exit 1
fi
systemctl reload caddy
if [[ ${1:-} == "--off" ]]; then echo "route removed"; else
  echo "OK. Next: sudo bash /opt/friday/deploy/zomato-explore.sh --public-url https://$HOST/explore"
fi
