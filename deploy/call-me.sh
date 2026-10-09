#!/bin/bash
# Friday: place the salon-booking TEST call to the allow-listed founder number, in one command.
# Run as root on the server:   bash /opt/friday/deploy/call-me.sh [first-name] [when] [salon-name] [honorific]
# Stops the front-door service (same port), runs the call (you type YES), then starts the service again.
set -uo pipefail
[ "$(id -u)" = 0 ] || { echo "Run as root"; exit 1; }
NAME="${1:-Himanshu}"; WHEN="${2:-kal shaam}"; SALON="${3:-Shreya salon}"; HON="${4:-sir}"
git config --global --add safe.directory /opt/friday 2>/dev/null || true
git -C /opt/friday pull --ff-only || { echo "git pull failed: stopping"; exit 1; }
trap 'systemctl start friday' EXIT        # the front door always comes back, even if the call fails
systemctl stop friday
cd /opt/friday
sudo -u friday /home/friday/.local/bin/uv run friday livecall --playbook salon_booking \
  --to +918607549916 --on-behalf-of "$NAME" --when "$WHEN" --salon-name "$SALON" --honorific "$HON" --budget 600 --max-seconds 150
echo; echo "Transcript: /opt/friday/var/livecalls/ (newest file). Front door restarting."
