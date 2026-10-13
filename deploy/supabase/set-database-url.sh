#!/bin/bash
# Point Friday at its Supabase Postgres. Run as root on the server:
#   bash /opt/friday/deploy/supabase/set-database-url.sh
# Asks for the project ref and the database password at a HIDDEN prompt, tries the three ways to
# reach Supabase (direct, and the two pooler hosts: the direct one is IPv6-only, which many
# servers do not have), keeps the first that really connects, and writes FRIDAY_DATABASE_URL into
# /opt/friday/.env. Never prints or logs the password; nothing here is committed.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Run as root"; exit 1; }
ENVF=/opt/friday/.env
REF_DEFAULT="zxbiapcppbfnctndmnab"
read -r -p "Supabase project ref [$REF_DEFAULT]: " REF; REF="${REF:-$REF_DEFAULT}"
[[ "$REF" =~ ^[a-z0-9]{15,30}$ ]] || { echo "That does not look like a project ref"; exit 1; }
read -r -p "Region [ap-southeast-1]: " REGION; REGION="${REGION:-ap-southeast-1}"
read -r -s -p "Database password (hidden): " PW; echo
[ -n "$PW" ] || { echo "Empty password"; exit 1; }
export SB_REF="$REF" SB_REGION="$REGION" SB_PW="$PW"
URL=$(sudo -E -u friday /home/friday/.local/bin/uv run --directory /opt/friday python - <<'PY'
import asyncio, os, urllib.parse
import asyncpg

ref, region, pw = os.environ["SB_REF"], os.environ["SB_REGION"], os.environ["SB_PW"]
enc = urllib.parse.quote(pw, safe="")
cands = [
    ("direct", f"db.{ref}.supabase.co", 5432, "postgres"),
    ("pooler-aws-0", f"aws-0-{region}.pooler.supabase.com", 5432, f"postgres.{ref}"),
    ("pooler-aws-1", f"aws-1-{region}.pooler.supabase.com", 5432, f"postgres.{ref}"),
]

async def main():
    for name, host, port, user in cands:
        try:
            c = await asyncio.wait_for(
                asyncpg.connect(host=host, port=port, user=user, password=pw,
                                database="postgres", ssl="require"), 12)
            await c.fetchval("select 1")
            await c.close()
            print(f"postgresql+asyncpg://{user}:{enc}@{host}:{port}/postgres")
            import sys
            print(f"connected via {name}", file=sys.stderr)
            return
        except Exception as e:  # noqa: BLE001
            import sys
            print(f"{name}: {type(e).__name__}", file=sys.stderr)
asyncio.run(main())
PY
)
unset PW SB_PW
[ -n "$URL" ] || { echo "Could not connect any way: check the password (Project Settings > Database > Reset password) and the region"; exit 1; }
[ -z "$(tail -c1 "$ENVF")" ] || echo >> "$ENVF"
if grep -q '^FRIDAY_DATABASE_URL=' "$ENVF"; then
  sed -i "s|^FRIDAY_DATABASE_URL=.*|FRIDAY_DATABASE_URL=${URL//|/\\|}|" "$ENVF"
else
  echo "FRIDAY_DATABASE_URL=${URL}" >> "$ENVF"
fi
chown friday:friday "$ENVF"; chmod 600 "$ENVF"
unset URL
echo "FRIDAY_DATABASE_URL saved. Now run: systemctl restart friday"
