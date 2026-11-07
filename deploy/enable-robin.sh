#!/bin/bash
# Robin: switch the family core and the device API on or off. Writes only NON-secret settings, then restarts friday.
# Run as root:   bash /opt/friday/deploy/enable-robin.sh [off]
#
# On  : sets FRIDAY_ROBIN_ENABLED=true and FRIDAY_ROBIN_DEVICE_ENABLED=true. Nothing else.
# Refuses (exit 3, changes nothing) when FRIDAY_ROBIN_AUTHORITY_DRY_RUN=false, or when authority calls or
#         listen-in are already on: those stay OFF here and are never turned on by this script.
# Off : sets the two switches to false.
# The spoken lines stay PENDING: with them pending the real dial refuses, so no parent phone rings (docs/ROBIN_FAMILY_CORE.md).
# Tests run it with FRIDAY_ENV_FILE=<temp file> (no root, no restart).
set -euo pipefail
[ "$(id -u)" = 0 ] || [ -n "${FRIDAY_ENV_FILE:-}" ] || { echo "Run as root"; exit 1; }
case "${1:-}" in "") V=true ;; off) V=false ;; *) echo "Usage: enable-robin.sh [off]"; exit 1 ;; esac
APP="${FRIDAY_APP:-/opt/friday}"; ENVF="${FRIDAY_ENV_FILE:-$APP/.env}"
[ -f "$ENVF" ] || { echo "No $ENVF"; exit 1; }
getv() { grep -E "^$1=" "$ENVF" | tail -n 1 | cut -d= -f2- | tr -d "\"' " | tr '[:upper:]' '[:lower:]' || true; }
setv() { if grep -q "^$1=" "$ENVF"; then sed -i "s|^$1=.*|$1=$2|" "$ENVF"; else printf '%s=%s\n' "$1" "$2" >> "$ENVF"; fi; }
if [ "$V" = true ]; then
  case "$(getv FRIDAY_ROBIN_AUTHORITY_DRY_RUN)" in false|0|no|off) echo "REFUSED: FRIDAY_ROBIN_AUTHORITY_DRY_RUN is false (authority is LIVE). Set it to true first; nothing was changed."; exit 3 ;; esac
  case "$(getv FRIDAY_ROBIN_AUTHORITY_CALLS_ENABLED)" in true|1|yes|on) echo "REFUSED: FRIDAY_ROBIN_AUTHORITY_CALLS_ENABLED is on. Turn it off first; this script leaves authority off. Nothing was changed."; exit 3 ;; esac
  case "$(getv FRIDAY_ROBIN_LISTEN_IN_ENABLED)" in true|1|yes|on) echo "REFUSED: FRIDAY_ROBIN_LISTEN_IN_ENABLED is on. Turn it off first; this script leaves listen-in off. Nothing was changed."; exit 3 ;; esac
fi
setv FRIDAY_ROBIN_ENABLED "$V"
setv FRIDAY_ROBIN_DEVICE_ENABLED "$V"
state() { case "$(getv "$1")" in true|1|yes|on) echo on ;; *) echo off ;; esac; }
echo "Robin: $([ "$V" = true ] && echo ON || echo OFF)  (names only, no values)"
echo "  FRIDAY_ROBIN_ENABLED                  $(state FRIDAY_ROBIN_ENABLED)"
echo "  FRIDAY_ROBIN_DEVICE_ENABLED           $(state FRIDAY_ROBIN_DEVICE_ENABLED)"
echo "  FRIDAY_ROBIN_AUTHORITY_CALLS_ENABLED  $(state FRIDAY_ROBIN_AUTHORITY_CALLS_ENABLED)  (not touched)"
echo "  FRIDAY_ROBIN_LISTEN_IN_ENABLED        $(state FRIDAY_ROBIN_LISTEN_IN_ENABLED)  (not touched)"
echo "  FRIDAY_ROBIN_AUTHORITY_DRY_RUN        $([ "$(getv FRIDAY_ROBIN_AUTHORITY_DRY_RUN)" = "" ] && echo 'true (default)' || getv FRIDAY_ROBIN_AUTHORITY_DRY_RUN)  (not touched)"
echo "Spoken lines are PENDING founder approval: the real dial refuses, so no parent phone rings."
if [ -z "${FRIDAY_ENV_FILE:-}" ]; then
  systemctl restart friday && echo "friday restarted"
  echo "Check: friday doctor --section robin ; counts at /ops-status/<token>/robin"
fi
