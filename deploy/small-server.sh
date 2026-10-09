#!/bin/bash
# Friday: one-command installer for a SMALL server (DigitalOcean 1 GB droplet, Ubuntu 24.04), pilot profile, no Docker.
# Run as root, after the first-boot script finished:   bash small-server.sh
# Gives: Caddy (free HTTPS at https://<ip-with-dashes>.sslip.io), service user 'friday', code in /opt/friday,
# secrets in /opt/friday/.env (chmod 600, typed here with hidden input, never in chat or git),
# systemd service 'friday' running `friday listen` (answers calls to the Vobiz number, calls out on request).
# Re-runnable: asks before overwriting keys. Logs: journalctl -u friday -f
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Run as root (sudo bash small-server.sh)"; exit 1; }

REPO="${FRIDAY_REPO:-https://github.com/himanshugoel23/friday}"
APP=/opt/friday
export DEBIAN_FRONTEND=noninteractive

echo "== 1/6 packages"
apt-get update -y
apt-get install -y git curl ca-certificates debian-keyring debian-archive-keyring apt-transport-https gnupg python3 ufw
rm -f /etc/apt/sources.list.d/caddy-stable.list   # the third-party Caddy repo was returning 402; use Ubuntu's own package
apt-get update -y
command -v caddy >/dev/null || apt-get install -y caddy
ufw allow 22/tcp >/dev/null; ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null; ufw --force enable >/dev/null

echo "== 2/6 service user and code"
id friday >/dev/null 2>&1 || useradd -r -m -d /home/friday -s /bin/bash friday
if [ -d "$APP/.git" ]; then git -C "$APP" pull --ff-only; else git clone "$REPO" "$APP"; fi
chown -R friday:friday "$APP"
if ! su friday -c 'command -v ~/.local/bin/uv' >/dev/null 2>&1; then
  su friday -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
fi
su friday -c "cd $APP && ~/.local/bin/uv sync --no-dev"

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
unset FRIDAY_NEW_NAME FRIDAY_NEW_VAL

# non-secret settings (replace if present)
setv() { grep -v "^$1=" "$ENVF" > "$ENVF.tmp" || true; echo "$1=$2" >> "$ENVF.tmp"; mv "$ENVF.tmp" "$ENVF"; }
setv FRIDAY_MODE live
setv FRIDAY_PROFILE pilot
setv FRIDAY_LLM_PROVIDER openai
setv FRIDAY_TELEPHONY_PROVIDER sarvam
setv SARVAM_CALLER_IDS +918064267861
setv FRIDAY_PILOT_ALLOWED_NUMBERS +918607549916
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
Description=Friday (front door + calling)
After=network-online.target
Wants=network-online.target

[Service]
User=friday
WorkingDirectory=$APP
ExecStart=/home/friday/.local/bin/uv run friday listen
ExecStopPost=/home/friday/.local/bin/uv run friday listen --restore
Restart=on-failure
RestartSec=5
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now friday
sleep 5
systemctl --no-pager status friday | head -12 || true
echo
echo "Done. Public address: https://$HOST"
echo "  logs:      journalctl -u friday -f"
echo "  check:     cd $APP && sudo -u friday ~/.local/bin/uv run friday doctor   (as friday user: /home/friday/.local/bin/uv)"
echo "  restart:   systemctl restart friday      stop (frees the number): systemctl stop friday"
echo "Then call +91 80 6426 7861 from 8607549916."
