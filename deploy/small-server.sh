#!/bin/bash
# Friday: one-command installer for a SMALL server (DigitalOcean 1 GB droplet, Ubuntu 24.04), pilot profile, no Docker.
# Run as root, after the first-boot script finished:   bash small-server.sh
# Gives: Caddy (free HTTPS at https://<ip-with-dashes>.sslip.io), service user 'friday', code in /opt/friday,
# secrets in /opt/friday/.env (chmod 600, typed here with hidden input, never in chat or git),
# systemd service 'friday' running `friday serve` (web app: WhatsApp webhook, background loops). For a real call test stop it first and run `friday listen` by hand.
# Re-runnable: asks before overwriting keys. Logs: journalctl -u friday -f
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Run as root (sudo bash small-server.sh)"; exit 1; }

REPO="${FRIDAY_REPO:-https://github.com/himanshugoel23/friday}"
APP=/opt/friday
export DEBIAN_FRONTEND=noninteractive

echo "== 0/6 swap (small servers run out of memory without it)"
if [ "$(swapon --show --noheadings | wc -l)" = 0 ]; then
  fallocate -l 2G /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
  chmod 600 /swapfile; mkswap /swapfile >/dev/null; swapon /swapfile
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  echo "swap added (2 GB)"
else
  echo "swap already present"
fi

echo "== 1/6 packages"
rm -f /etc/apt/sources.list.d/caddy-stable.list   # a leftover third-party Caddy repo returned 402; use Ubuntu's own package
apt-get update -y
apt-get install -y git curl ca-certificates debian-keyring debian-archive-keyring apt-transport-https gnupg python3 ufw ffmpeg   # ffmpeg: voice-note replies (Ogg/Opus) and decoding incoming voice notes
command -v caddy >/dev/null || apt-get install -y caddy
ufw allow 22/tcp >/dev/null; ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null; ufw --force enable >/dev/null

echo "== 2/6 service user and code"
id friday >/dev/null 2>&1 || useradd -r -m -d /home/friday -s /bin/bash friday
BRANCH="${FRIDAY_BRANCH:-claude/friday-phase-1}"   # the branch that holds the current code
if [ -d "$APP/.git" ]; then git -C "$APP" fetch origin "$BRANCH" && git -C "$APP" checkout "$BRANCH" && git -C "$APP" pull --ff-only origin "$BRANCH"; else git clone -b "$BRANCH" "$REPO" "$APP"; fi
chown -R friday:friday "$APP"
if ! su friday -c 'command -v ~/.local/bin/uv' >/dev/null 2>&1; then
  su friday -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
fi
su friday -c "cd $APP && ~/.local/bin/uv sync --no-dev --extra vad"   # onnxruntime for the optional neural voice detector (stays off until FRIDAY_VOICE_VAD_BACKEND=silero)

echo "== 3/6 public address"
IP="${FRIDAY_SERVER_IP:-$(curl -4 -fsS https://api.ipify.org)}"
HOST="$(echo "$IP" | tr . -).sslip.io"
echo "   Friday will be reachable at https://$HOST"

echo "== 4/6 keys (typed hidden; press Enter to keep an existing value)"
ENVF="$APP/.env"
[ -f "$ENVF" ] || su friday -c "cd $APP && ~/.local/bin/uv run friday init-env" >/dev/null   # fresh random secrets
chmod 600 "$ENVF"; chown friday:friday "$ENVF"
ask() { # name prompt
  local v; read -r -s -p "$2: " v </dev/tty; echo
  [ -n "$v" ] && FRIDAY_NEW_NAME="$1" FRIDAY_NEW_VAL="$v" python3 - "$ENVF" <<'PY'
import os, sys
p, k, v = sys.argv[1], os.environ["FRIDAY_NEW_NAME"], os.environ["FRIDAY_NEW_VAL"]
lines = [l for l in open(p).read().splitlines() if not l.startswith(k + "=")]
lines.append(f"{k}={v}")
open(p, "w").write("\n".join(lines) + "\n")
PY
  return 0
}
ask SARVAM_API_KEY "Sarvam API key"
ask OPENAI_API_KEY "OpenAI API key"
ask SARVAM_TELEPHONY_AUTH_ID "Vobiz Auth ID"
ask SARVAM_TELEPHONY_AUTH_TOKEN "Vobiz Auth Token"
ask FRIDAY_PILOT_ALLOWED_NUMBERS "Your own test phone, with +91 (the only number Friday may call)"
ask WHATSAPP_ACCESS_TOKEN "Meta WhatsApp access token (Enter to skip for now)"
ask WHATSAPP_PHONE_NUMBER_ID "Meta WhatsApp phone number ID (Enter to skip)"
ask WHATSAPP_APP_SECRET "Meta app secret (Enter to skip)"
ask WHATSAPP_VERIFY_TOKEN "A random word you choose as the webhook verify token (Enter to skip)"
unset FRIDAY_NEW_NAME FRIDAY_NEW_VAL

# non-secret settings (replace if present)
setv() { grep -v "^$1=" "$ENVF" > "$ENVF.tmp" || true; echo "$1=$2" >> "$ENVF.tmp"; mv "$ENVF.tmp" "$ENVF"; }
setv FRIDAY_MODE live
setv FRIDAY_PROFILE pilot
setv FRIDAY_LLM_PROVIDER openai
setv FRIDAY_TELEPHONY_PROVIDER sarvam
setv SARVAM_CALLER_IDS +918064267861
setv FRIDAY_PUBLIC_BASE_URL "https://$HOST"
setv FRIDAY_HOST 127.0.0.1
setv FRIDAY_PORT 8000
setv FRIDAY_DATABASE_URL "sqlite+aiosqlite:////opt/friday/var/friday.db"
mkdir -p "$APP/var"
chown -R friday:friday "$APP"; chmod 600 "$ENVF"

echo "== 5/6 HTTPS (Caddy)"
cat > /etc/caddy/Caddyfile <<CADDY
$HOST {
    encode gzip
    reverse_proxy 127.0.0.1:8000
}
CADDY
systemctl enable --now caddy; systemctl reload caddy || systemctl restart caddy

echo "== 6/6 Friday service"
cat > /etc/systemd/system/friday.service <<UNIT
[Unit]
Description=Friday (web app: WhatsApp webhook + background loops)
After=network-online.target
Wants=network-online.target

[Service]
User=friday
WorkingDirectory=$APP
ExecStart=/home/friday/.local/bin/uv run friday serve
Restart=on-failure
RestartSec=5
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
echo "== database changes (migrations)"
su friday -c "cd $APP && ~/.local/bin/uv run python -m friday.db.migrate up" || echo "WARNING: migrations did not apply; run friday doctor"
systemctl enable friday; systemctl restart friday   # restart so an existing server loads the new code
sleep 5
systemctl --no-pager status friday | head -12 || true
echo
echo "Done. Public address: https://$HOST"
echo "  logs:      journalctl -u friday -f"
echo "  check:     cd $APP && sudo -u friday ~/.local/bin/uv run friday doctor   (as friday user: /home/friday/.local/bin/uv)"
echo "  restart:   systemctl restart friday      stop (frees the number): systemctl stop friday"
echo "Webhook for Meta (WhatsApp): callback URL https://$HOST/webhooks/whatsapp  (verify token = the word you typed above)"
echo "Slice 0 check (no calls, no messages sent): cd $APP && sudo -u friday /home/friday/.local/bin/uv run friday doctor"
echo "Then message the Meta test number from your phone: Friday should reply."
