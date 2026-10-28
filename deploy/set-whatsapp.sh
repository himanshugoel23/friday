#!/bin/bash
# Friday: store the WhatsApp (Meta Cloud API) values on the server, typed hidden, never in chat or git.
# Run as root on the server:   bash /opt/friday/deploy/set-whatsapp.sh
# Press Enter on any question to keep the stored value. Restarts the service at the end.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Run as root (sudo bash set-whatsapp.sh)"; exit 1; }
APP="${FRIDAY_APP:-/opt/friday}"
ENVF="${FRIDAY_ENV_FILE:-$APP/.env}"
[ -f "$ENVF" ] || { echo "No $ENVF: run small-server.sh first"; exit 1; }

setv() { # name value
  FRIDAY_NEW_NAME="$1" FRIDAY_NEW_VAL="$2" python3 - "$ENVF" <<'PY'
import os, sys
p, k, v = sys.argv[1], os.environ["FRIDAY_NEW_NAME"], os.environ["FRIDAY_NEW_VAL"]
lines = [l for l in open(p).read().splitlines() if not l.startswith(k + "=")]
lines.append(f"{k}={v}")
open(p, "w").write("\n".join(lines) + "\n")
PY
}
ask_plain() { local v; read -r -p "$2: " v </dev/tty; [ -n "$v" ] && setv "$1" "$v"; return 0; }
SHOW=0; [ "${1:-}" = "show" ] && SHOW=1   # `bash set-whatsapp.sh show`: the paste is visible on YOUR screen (not hidden)
ask_hidden() { # pasted secrets often carry spaces/newlines: strip all whitespace; show only the LENGTH
  local v
  if [ "$SHOW" = 1 ]; then read -r -p "$2: " v </dev/tty; else read -r -s -p "$2: " v </dev/tty; echo; fi
  v="$(printf %s "$v" | tr -d '[:space:]')"
  if [ -n "$v" ]; then setv "$1" "$v"; echo "   saved $1 (length ${#v})"; fi
  return 0
}

echo "WhatsApp values (Enter keeps the stored value)"
ask_plain  WHATSAPP_PHONE_NUMBER_ID "Phone number ID (not secret)"
ask_hidden WHATSAPP_ACCESS_TOKEN    "Access token (hidden; paste it here, NOT in chat)"
ask_hidden WHATSAPP_APP_SECRET      "App secret (hidden; App settings > Basic > Show)"
ask_plain  WHATSAPP_VERIFY_TOKEN    "Verify word you choose for the webhook (not secret; remember it)"
chmod 600 "$ENVF"; chown friday:friday "$ENVF"

systemctl restart friday
HOST="$(grep -m1 -E '^FRIDAY_PUBLIC_BASE_URL=' "$ENVF" | cut -d= -f2- || true)"
[ -n "$HOST" ] || HOST="https://$(curl -4 -fsS https://api.ipify.org | tr . -).sslip.io"
echo
echo "(An app secret is normally 32 characters; an access token is much longer, 150+.)"
echo "Saved and restarted. In Meta: WhatsApp > Configuration > Webhook:"
echo "  Callback URL: $HOST/webhooks/whatsapp"
echo "  Verify token: the word you typed above"
echo "  Then subscribe to the field: messages"
echo "Check:  cd $APP && sudo -u friday /home/friday/.local/bin/uv run friday doctor 2>&1 | head -45"
