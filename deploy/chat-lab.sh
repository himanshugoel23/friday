#!/usr/bin/env bash
# Friday Chat Lab on the server (docs/CHAT_LAB.md): a WhatsApp-style test page for the chatbot,
# with NO WhatsApp. Simulator only: in-memory chat, fake calls, fake clock; it cannot message or
# call anyone and it does not read /opt/friday/.env.
#
# Run it inside tmux so it keeps running after you close the terminal:
#   tmux new -s lab
#   sudo bash /opt/friday/deploy/chat-lab.sh                       # prints the link with the token
#   sudo bash /opt/friday/deploy/chat-lab.sh --ttl-hours 2         # shorter-lived token
#   sudo bash /opt/friday/deploy/chat-lab.sh --use-stored-key      # reuse the OpenAI key already on the server (never printed); real replies, costs money
#   sudo bash /opt/friday/deploy/chat-lab.sh --with-model          # asks for the OpenAI key (hidden); real replies, costs money
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
    sudo -u "$RUN_USER" --preserve-env=OPENAI_API_KEY,FRIDAY_LLM_PROVIDER env PYTHONUNBUFFERED=1 "$@"
  else
    env PYTHONUNBUFFERED=1 "$@"
  fi
}

# --with-model: ask for the OpenAI key (hidden), keep it ONLY in this process's environment (never written
# to disk, never in git) so the page's "real model" switch works; replies then feel real and COST money.
NEWARGS=()
for a in "$@"; do
  if [ "$a" = "--use-stored-key" ]; then
    # Reuse the OpenAI key already stored for the Friday service. The shell (running as root) copies it into
    # THIS process's environment only: it is never printed, never written elsewhere, never in git or chat.
    ENVF="$APP_DIR/.env"
    [ -r "$ENVF" ] || { echo "No readable $ENVF"; exit 1; }
    OPENAI_API_KEY="$(grep -m1 -E '^OPENAI_API_KEY=' "$ENVF" | cut -d= -f2- | tr -d '[:space:]"'"'"'')"
    [ -n "$OPENAI_API_KEY" ] || { echo "OPENAI_API_KEY is not set in $ENVF"; exit 1; }
    export OPENAI_API_KEY FRIDAY_LLM_PROVIDER=openai
    echo "   using the stored OpenAI key (length ${#OPENAI_API_KEY}); turn on 'real model' in the page's switches (?dev=1)."
  elif [ "$a" = "--with-model" ]; then
    read -r -s -p "OpenAI API key (hidden; only for this lab session): " OPENAI_API_KEY </dev/tty; echo
    OPENAI_API_KEY="$(printf %s "$OPENAI_API_KEY" | tr -d '[:space:]')"
    export OPENAI_API_KEY FRIDAY_LLM_PROVIDER=openai
    echo "   key received (length ${#OPENAI_API_KEY}); turn on 'real model' in the page's switches."
  else
    NEWARGS+=("$a")
  fi
done
set -- ${NEWARGS[@]+"${NEWARGS[@]}"}

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
