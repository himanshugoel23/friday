#!/bin/bash
# Friday: place ONE consumer test call from Friday to YOUR OWN allow-listed phone, in one command.
# This is the "call someone for me" path (request -> approval -> gate -> real call -> live engine ->
# report), pointed at your own phone. Run as root on the server:
#   bash /opt/friday/deploy/consumer-call-test.sh [options]
# Options (all optional; they are passed straight to `friday consumer call-test`):
#   --to +91XXXXXXXXXX   must be on FRIDAY_PILOT_ALLOWED_NUMBERS. Default: the first allow-listed number.
#   --who family|friend|provider   how Friday talks to the callee. Default: friend
#   --goal "text"        what the call should say, in your own words. Default: a short test message
#   --name "Himanshu"    how the callee hears your name in the first line
#   --callee-name "Name" how Friday addresses the callee
#   --max-seconds N      at most FRIDAY_CALLS_TEST_CALL_SECONDS (default 150)
#   --whatsapp-report    also send the report on WhatsApp (default: only printed here)
#   --dry-run            everything except the dial, on a simulated callee. No phone is called and the
#                        front door is NOT stopped.
# Examples:
#   bash /opt/friday/deploy/consumer-call-test.sh --dry-run
#   bash /opt/friday/deploy/consumer-call-test.sh --who friend --goal "main das minute mein pahunch raha hoon"
# What it does, in order (it prints each step):
#   1. pulls the latest code (fast-forward only; stops if that fails)
#   2. stops the front-door service (same port; the call needs the port free), unless --dry-run
#   3. runs the call test: it shows the plan and the exact first line, then asks you to type YES
#   4. starts the front-door service again, always, even if the call fails or you press Ctrl-C
# To stop a call in progress: Ctrl-C here, or `friday pause` from another window (kill switch), or
# `systemctl stop friday` (this script then cannot restart it; start it yourself afterwards).
# It never prints keys or the .env file. Paste back only the CALL SUMMARY lines it prints.
set -uo pipefail
[ "$(id -u)" = 0 ] || { echo "Run as root"; exit 1; }
DRY=0
for a in "$@"; do [ "$a" = "--dry-run" ] && DRY=1; done
echo "Consumer call test. Code: /opt/friday. Log of this run: /opt/friday/var/consumer_calls/last-run.log"
git config --global --add safe.directory /opt/friday 2>/dev/null || true
echo "Step 1: pulling the latest code..."
git -C /opt/friday pull --ff-only || { echo "git pull failed: stopping"; exit 1; }
mkdir -p /opt/friday/var/consumer_calls && chown -R friday: /opt/friday/var/consumer_calls 2>/dev/null || true
if [ "$DRY" = 0 ]; then
  trap 'echo "Starting the front door again..."; systemctl start friday' EXIT   # always comes back
  echo "Step 2: stopping the front door (the test call needs the port)..."
  systemctl stop friday
else
  echo "Step 2: dry run, the front door stays up."
fi
cd /opt/friday
echo "Step 3: running the call test. You will be asked to type YES before anything is dialled."
sudo -u friday env PYTHONUNBUFFERED=1 /home/friday/.local/bin/uv run friday consumer call-test "$@" 2>&1 | tee /opt/friday/var/consumer_calls/last-run.log
echo
echo "Transcript and call log: /opt/friday/var/consumer_calls/ (newest files). Full output: /opt/friday/var/consumer_calls/last-run.log"
