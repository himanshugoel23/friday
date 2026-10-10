#!/bin/bash
# Friday: place the salon-booking TEST call to the allow-listed founder number, in one command.
# Run as root on the server:
#   bash /opt/friday/deploy/call-me.sh [first-name] [when] [salon-name] [honorific] [mode] [services] [fallback-when]
#     first-name     the owner's first name Friday uses ("Himanshu sir"). Default Himanshu
#     when           e.g. "kal shaam", or ONE specific time: "aaj shaam 5 baje". Default "kal shaam"
#     salon-name     as written, e.g. "Shreya Salon" (the voice reads it in Devanagari). Default "Shreya Salon"
#     honorific      sir | madam | ji. Default sir
#     mode           quote-only (default: she only asks the price, books nothing)
#                    book-now   (she WILL book: needs a specific time in [when]; books that time, or
#                                [fallback-when] if the first is busy, if the price is within Rs 600)
#     services       what the owner wants, e.g. "haircut, beard trim". Default haircut
#     fallback-when  book-now only: a second specific time, e.g. "kal shaam 5 baje" (optional)
#   Older calls still work: the first five arguments keep their meaning ('book-now' as 5th).
#   Examples:
#     bash /opt/friday/deploy/call-me.sh Himanshu "kal shaam" "Shreya Salon" sir quote-only "haircut, beard trim"
#     bash /opt/friday/deploy/call-me.sh Himanshu "aaj shaam 5 baje" "Shreya Salon" sir book-now "haircut" "kal shaam 5 baje"
# Stops the front-door service (same port), runs the call (you type YES), then starts the service again.
set -uo pipefail
[ "$(id -u)" = 0 ] || { echo "Run as root"; exit 1; }
NAME="${1:-Himanshu}"; WHEN="${2:-kal shaam}"; SALON="${3:-Shreya Salon}"; HON="${4:-sir}"; MODE="${5:-}"
SERVICES="${6:-haircut}"; FALLBACK="${7:-}"
MODEFLAGS=()
case "$MODE" in
  book-now) MODEFLAGS=(--mode book --book-now) ;;
  quote-only|"") MODEFLAGS=(--mode quote-only) ;;
  *) echo "5th argument (mode) must be 'quote-only' or 'book-now' (or empty)"; exit 1 ;;
esac
if [ -n "$FALLBACK" ]; then
  [ "$MODE" = "book-now" ] || { echo "fallback-when (7th argument) only works with book-now"; exit 1; }
  MODEFLAGS+=(--fallback-when "$FALLBACK")
fi
git config --global --add safe.directory /opt/friday 2>/dev/null || true
git -C /opt/friday pull --ff-only || { echo "git pull failed: stopping"; exit 1; }
trap 'systemctl start friday' EXIT        # the front door always comes back, even if the call fails
systemctl stop friday
cd /opt/friday
sudo -u friday /home/friday/.local/bin/uv run friday livecall --playbook salon_booking \
  --to +918607549916 --on-behalf-of "$NAME" --when "$WHEN" --salon-name "$SALON" --honorific "$HON" --services "$SERVICES" --budget 600 --max-seconds 150 "${MODEFLAGS[@]}"
echo; echo "Transcript: /opt/friday/var/livecalls/ (newest file). Front door restarting."
