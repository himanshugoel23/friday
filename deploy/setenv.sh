#!/bin/bash
# Set (or change) ONE non-secret setting in /opt/friday/.env, idempotent. Run as root on the server.
#   bash /opt/friday/deploy/setenv.sh FRIDAY_LLM_CALL_TURN_PROVIDER sarvam
# Never use this for keys (they would stay in your shell history): use enable-fast-voice.sh / the hidden prompt.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Run as root"; exit 1; }
[ $# -eq 2 ] || { echo "usage: setenv.sh NAME VALUE"; exit 1; }
case "$1" in *KEY*|*TOKEN*|*SECRET*|*PASSWORD*) echo "Refusing: $1 looks like a secret. Type secrets at a hidden prompt."; exit 1;; esac
ENVF=/opt/friday/.env
[ -z "$(tail -c1 "$ENVF")" ] || echo >> "$ENVF"
if grep -q "^$1=" "$ENVF"; then sed -i "s|^$1=.*|$1=$2|" "$ENVF"; else echo "$1=$2" >> "$ENVF"; fi
chown friday:friday "$ENVF"; chmod 600 "$ENVF"
echo "set $1=$2"
