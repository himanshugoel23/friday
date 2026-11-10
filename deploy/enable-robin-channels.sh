#!/bin/bash
# Robin: switch ONE extra Robin feature on or off. Writes only NON-secret settings, then restarts friday.
# Run as root:   bash /opt/friday/deploy/enable-robin-channels.sh <parent-whatsapp|forwarded-calls|concierge> [off]
#
#   parent-whatsapp   FRIDAY_ROBIN_PARENT_WHATSAPP_ENABLED   Robin talks to the parent on WhatsApp (needs the Meta token and approved templates)
#   forwarded-calls   FRIDAY_ROBIN_FORWARDED_CALLS_ENABLED   Robin answers a call forwarded from a family phone (needs Vobiz + the carrier forwarding test)
#   concierge         FRIDAY_ROBIN_CONCIERGE_ENABLED         the human desk (needs the staff list, TOTP check and family lookup wired by engineering [U])
#
# Same lock as enable-robin.sh: on THE ON PATH it refuses (exit 3, changes nothing) when FRIDAY_ROBIN_AUTHORITY_DRY_RUN=false, or when authority calls or
# listen-in are on. It never turns authority calls, listen-in or screen-first on, and never sets FRIDAY_ROBIN_AUTHORITY_DRY_RUN. It does not turn on
# FRIDAY_ROBIN_ENABLED either: run deploy/enable-robin.sh first. Off is always allowed.
# Tests run it with FRIDAY_ENV_FILE=<temp file> (no root, no restart).
set -euo pipefail
[ "$(id -u)" = 0 ] || [ -n "${FRIDAY_ENV_FILE:-}" ] || { echo "Run as root"; exit 1; }
USAGE="Usage: enable-robin-channels.sh <parent-whatsapp|forwarded-calls|concierge> [off]"
case "${1:-}" in
  parent-whatsapp) KEY=FRIDAY_ROBIN_PARENT_WHATSAPP_ENABLED ;;
  forwarded-calls) KEY=FRIDAY_ROBIN_FORWARDED_CALLS_ENABLED ;;
  concierge) KEY=FRIDAY_ROBIN_CONCIERGE_ENABLED ;;
  *) echo "$USAGE"; exit 1 ;;
esac
case "${2:-}" in "") V=true ;; off) V=false ;; *) echo "$USAGE"; exit 1 ;; esac
APP="${FRIDAY_APP:-/opt/friday}"; ENVF="${FRIDAY_ENV_FILE:-$APP/.env}"
[ -f "$ENVF" ] || { echo "No $ENVF"; exit 1; }
getv() { grep -E "^$1=" "$ENVF" | tail -n 1 | cut -d= -f2- | tr -d "\"' " | tr '[:upper:]' '[:lower:]' || true; }
setv() { if grep -q "^$1=" "$ENVF"; then sed -i "s|^$1=.*|$1=$2|" "$ENVF"; else printf '%s=%s\n' "$1" "$2" >> "$ENVF"; fi; }
if [ "$V" = true ]; then
  case "$(getv FRIDAY_ROBIN_AUTHORITY_DRY_RUN)" in false|0|no|off) echo "REFUSED: FRIDAY_ROBIN_AUTHORITY_DRY_RUN is false (authority is LIVE). Set it to true first; nothing was changed."; exit 3 ;; esac
  case "$(getv FRIDAY_ROBIN_AUTHORITY_CALLS_ENABLED)" in true|1|yes|on) echo "REFUSED: FRIDAY_ROBIN_AUTHORITY_CALLS_ENABLED is on. Turn it off first; this script leaves authority off. Nothing was changed."; exit 3 ;; esac
  case "$(getv FRIDAY_ROBIN_LISTEN_IN_ENABLED)" in true|1|yes|on) echo "REFUSED: FRIDAY_ROBIN_LISTEN_IN_ENABLED is on. Turn it off first; this script leaves listen-in off. Nothing was changed."; exit 3 ;; esac
  case "$(getv FRIDAY_ROBIN_ENABLED)" in true|1|yes|on) ;; *) echo "REFUSED: FRIDAY_ROBIN_ENABLED is off. Run deploy/enable-robin.sh first. Nothing was changed."; exit 3 ;; esac
fi
setv "$KEY" "$V"
state() { case "$(getv "$1")" in true|1|yes|on) echo on ;; *) echo off ;; esac; }
echo "$KEY=$V  (names only, no values)"
echo "  FRIDAY_ROBIN_AUTHORITY_CALLS_ENABLED  $(state FRIDAY_ROBIN_AUTHORITY_CALLS_ENABLED)  (not touched)"
echo "  FRIDAY_ROBIN_LISTEN_IN_ENABLED        $(state FRIDAY_ROBIN_LISTEN_IN_ENABLED)  (not touched)"
echo "  FRIDAY_ROBIN_AUTHORITY_DRY_RUN        $([ "$(getv FRIDAY_ROBIN_AUTHORITY_DRY_RUN)" = "" ] && echo 'true (default)' || getv FRIDAY_ROBIN_AUTHORITY_DRY_RUN)  (not touched)"
echo "Spoken lines are PENDING founder approval: the real dial refuses, so no parent phone rings."
if [ -z "${FRIDAY_ENV_FILE:-}" ]; then
  systemctl restart friday && echo "friday restarted"
  echo "Check: friday doctor --section robin"
fi
