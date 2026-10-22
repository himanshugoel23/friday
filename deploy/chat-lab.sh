#!/usr/bin/env bash
# Friday Chat Lab on the server (docs/CHAT_LAB.md): a WhatsApp-style test page for the chatbot,
# with NO WhatsApp. Simulator only: in-memory chat, fake calls, fake clock; it cannot message or
# call anyone and it does not read /opt/friday/.env.
#
# Run it inside tmux so it keeps running after you close the terminal:
#   tmux new -s lab
#   sudo bash /opt/friday/deploy/chat-lab.sh                       # prints the link with the token
#   sudo bash /opt/friday/deploy/chat-lab.sh --ttl-hours 2         # shorter-lived token
#   sudo bash /opt/friday/deploy/chat-lab.sh --public-url https://YOUR-HOST
# Detach with ctrl-b d; stop with ctrl-c inside the session.
#
# To open it from an iPad over HTTPS first run, once:  sudo bash /opt/friday/deploy/lab-https.sh
# (this script then prints the https link by itself). Any extra arguments go to `friday lab`.
set -euo pipefail
APP_DIR="${FRIDAY_APP_DIR:-/opt/friday}"
RUN_USER="${FRIDAY_RUN_USER:-friday}"
UV="${UV_BIN:-/home/$RUN_USER/.local/bin/uv}"
[ -x "$UV" ] || UV="$(command -v uv || true)"
[ -n "$UV" ] || { echo "uv not found (expected /home/$RUN_USER/.local/bin/uv)"; exit 1; }

# Run a command as the friday user (same pattern as deploy/zomato-explore.sh and call-me.sh).
as_friday() {
  if [ "$(id -u)" = 0 ] && [ "$RUN_USER" != root ]; then
    sudo -u "$RUN_USER" env PYTHONUNBUFFERED=1 "$@"
  else
    env PYTHONUNBUFFERED=1 "$@"
  fi
}

# Where "mark this reply wrong" notes go (gitignored var/).
mkdir -p "$APP_DIR/var/lab"
chown "$RUN_USER": "$APP_DIR/var" "$APP_DIR/var/lab" 2>/dev/null || true

# If lab-https.sh added the /lab route, print the https link by default.
ARGS=("$@")
if ! printf '%s\n' "$@" | grep -q -- '--public-url'; then
  CF=/etc/caddy/Caddyfile
  if [ -r "$CF" ] && grep -q 'handle /lab/\*' "$CF"; then
    HOST="$(awk 'NF{print $1; exit}' "$CF")"
    [ -z "$HOST" ] || ARGS+=(--public-url "https://$HOST")
  fi
fi

# The lab itself refuses to start if FRIDAY_MODE=live is set in the environment (it would stay on the
# simulator anyway; this is a second lock). It binds to 127.0.0.1 only; Caddy is the only way in.
as_friday "$UV" run --directory "$APP_DIR" friday lab --host 127.0.0.1 \
  --port "${FRIDAY_LAB_PORT:-8766}" --notes "$APP_DIR/var/lab/notes.jsonl" ${ARGS[@]+"${ARGS[@]}"}
