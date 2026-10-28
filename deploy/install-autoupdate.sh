#!/bin/bash
# Friday: ONE-TIME install of the self-updater. Paste this single line in the console as root:
#   cd /opt/friday && sudo -u friday git pull -q origin claude/friday-phase-1 && bash deploy/install-autoupdate.sh
# After this, updates, migrations and restarts happen by themselves within ~3 minutes of each push.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Run as root"; exit 1; }
APP=/opt/friday; ENVF="$APP/.env"
chmod +x "$APP/deploy/autoupdate.sh"
if ! grep -q '^FRIDAY_OPS_STATUS_TOKEN=' "$ENVF"; then
  echo "FRIDAY_OPS_STATUS_TOKEN=$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 28)" >> "$ENVF"
fi
TOKEN=$(grep '^FRIDAY_OPS_STATUS_TOKEN=' "$ENVF" | cut -d= -f2)
cat > /etc/systemd/system/friday-autoupdate.service <<U
[Unit]
Description=Friday self-update
[Service]
Type=oneshot
ExecStart=/bin/bash $APP/deploy/autoupdate.sh
U
cat > /etc/systemd/system/friday-autoupdate.timer <<U
[Unit]
Description=Friday self-update every 3 minutes
[Timer]
OnBootSec=1min
OnUnitActiveSec=3min
[Install]
WantedBy=timers.target
U
systemctl daemon-reload; systemctl enable --now friday-autoupdate.timer >/dev/null
rm -f "$APP/var/autoupdate/status.txt"
systemctl restart friday
systemctl start --no-block friday-autoupdate.service
echo "Installed. Read-only status link (it holds no secrets):"
echo "  https://64-227-183-183.sslip.io/ops-status/$TOKEN"
