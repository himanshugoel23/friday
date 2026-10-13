#!/bin/bash
# Point Friday at a Supabase Postgres. Run as root on the server:
#   bash /opt/friday/deploy/supabase/set-database-url.sh
# Asks for the project ref (letters, from the project URL) and the database password at a HIDDEN
# prompt; writes FRIDAY_DATABASE_URL into /opt/friday/.env. Never prints the password.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Run as root"; exit 1; }
ENVF=/opt/friday/.env
read -r -p "Supabase project ref (e.g. abcdefghijklmnopqrst): " REF
[[ "$REF" =~ ^[a-z0-9]{15,30}$ ]] || { echo "That does not look like a project ref"; exit 1; }
read -r -s -p "Database password (hidden): " PW; echo
[ -n "$PW" ] || { echo "Empty password"; exit 1; }
ENC=$(python3 -c 'import sys,urllib.parse;print(urllib.parse.quote(sys.argv[1],safe=""))' "$PW")
URL="postgresql+asyncpg://postgres:${ENC}@db.${REF}.supabase.co:5432/postgres"
[ -z "$(tail -c1 "$ENVF")" ] || echo >> "$ENVF"
if grep -q '^FRIDAY_DATABASE_URL=' "$ENVF"; then
  sed -i "s|^FRIDAY_DATABASE_URL=.*|FRIDAY_DATABASE_URL=${URL//|/\\|}|" "$ENVF"
else
  echo "FRIDAY_DATABASE_URL=${URL}" >> "$ENVF"
fi
chown friday:friday "$ENVF"; chmod 600 "$ENVF"
unset PW ENC URL
echo "FRIDAY_DATABASE_URL saved for project ${REF}. Now: systemctl restart friday"
